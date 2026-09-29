"""牛盾支付 SDK 客户端 — 对照 sdk-contract.md 第二、十节

执行链路：填充公共参数 → 序列化 → 对 JSON 报文签名 → POST → 按原始响应体验签 → 返回 NiuDunResult。
时间字段一律使用北京时间 `yyyy-MM-dd HH:mm:ss` 字面量（平台按报文规范字面量验签）。
"""
from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from niudun_open_sdk.config import Config
from niudun_open_sdk.errors import NiuDunError, ErrorCode
from niudun_open_sdk.models import (
    AllocParam,
    AllocQueryParam,
    AllocSyncParam,
    CloseParam,
    NiuDunResult,
    GatewayOrderQueryParam,
    GatewayPrePayParam,
    PayParam,
    PayQueryParam,
    PaySyncParam,
    PingParam,
    RefundParam,
    RefundQueryParam,
    RefundSyncParam,
    TransferParam,
    TransferQueryParam,
    TransferSyncParam,
)
from niudun_open_sdk.rsa import rsa_sign, rsa_verify
from niudun_open_sdk.sign import build_sign_str

DEFAULT_TIMEOUT = 30000


def _now_beijing() -> str:
    """当前时间的北京时间字面量（yyyy-MM-dd HH:mm:ss）— 对照后端 @JsonFormat(GMT+8)"""
    beijing = datetime.now(timezone.utc) + timedelta(hours=8)
    return beijing.strftime("%Y-%m-%d %H:%M:%S")


class NiuDunObserver:
    """SDK 调用观测接口（联调/排障场景）

    挂在 [NiuDunClient][niudun_open_sdk.client.NiuDunClient] 上可拿到每次调用
    「签名后的完整请求体」与「平台原始响应体」，便于与后端日志逐字对照。
    不设置则零开销，不影响正常调用链。

    可直接继承本类覆写两个方法，也可用
    [set_observer][niudun_open_sdk.client.NiuDunClient.set_observer] 传入两个回调函数。
    """

    def on_request(self, signed_json: str) -> None:
        """请求已签名待发出（signed_json 为含 sign 字段的完整请求 JSON）"""
        raise NotImplementedError

    def on_response(self, raw_body: str) -> None:
        """收到平台原始响应体（在响应验签**之前**回调，验签失败时也可拿到原文）"""
        raise NotImplementedError


class _CallbackObserver(NiuDunObserver):
    """由两个可选回调函数组装的观测器（函数为 None 时跳过，无任何额外开销）"""

    def __init__(
        self,
        on_request: Optional[Callable[[str], None]] = None,
        on_response: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_request = on_request
        self._on_response = on_response

    def on_request(self, signed_json: str) -> None:
        if self._on_request is not None:
            self._on_request(signed_json)

    def on_response(self, raw_body: str) -> None:
        if self._on_response is not None:
            self._on_response(raw_body)


class NiuDunClient:
    """牛盾支付 开放接口客户端

    单实例可复用；配置见 [Config][niudun_open_sdk.config.Config]。
    联调场景可挂载 observer 观测每次调用的原始报文；多线程下每个调用建议使用独立实例。
    """

    def __init__(self, config: Config, observer: Optional[NiuDunObserver] = None) -> None:
        self._config = config
        self._service_url = config.service_url.rstrip("/")
        # 配置以毫秒计（与其它语言 SDK 对齐），urllib 需要秒
        self._timeout = (config.timeout or DEFAULT_TIMEOUT) / 1000
        # 观测回调（未设置时为 None，执行链路里零分支开销）
        self._on_request: Optional[Callable[[str], None]] = None
        self._on_response: Optional[Callable[[str], None]] = None
        if observer is not None:
            self._on_request = observer.on_request
            self._on_response = observer.on_response

    def set_observer(
        self,
        on_request: Optional[Callable[[str], None]] = None,
        on_response: Optional[Callable[[str], None]] = None,
    ) -> "NiuDunClient":
        """设置调用观测回调（联调排障用），返回自身便于链式调用

        :param on_request: 请求签名后、发送前回调，入参为含 sign 的完整请求 JSON
        :param on_response: 收到原始响应后、验签前回调，入参为平台原始响应体文本
        """
        self._on_request = on_request
        self._on_response = on_response
        return self

    # ==================================================================
    # 执行入口
    # ==================================================================

    def execute(
        self,
        path: str,
        param: Dict[str, Any],
        *,
        throw_on_biz_error: bool = True,
    ) -> NiuDunResult:
        """通用执行入口

        :param path: 接口路径，如 `/unipay/pay`
        :param param: 业务参数（键名即报文键名）
        :param throw_on_biz_error: False 时非 0 业务码不抛异常而是原样返回 NiuDunResult
            （签名自检探针的职责是报告检查结果，失败码/失败消息本身就是有效答案）；
            响应验签失败仍抛异常（那是平台公钥配置问题，属于硬错误而非探针答案）
        :return: 平台响应（已验签；throw_on_biz_error=True 时 code 已确认为 0）
        :raises NiuDunError: HTTP 异常 / 验签失败 / 业务 code != 0（后者仅在 throw_on_biz_error 时）
        """
        request_param: Dict[str, Any] = dict(param)
        # 注入公共字段（调用方已显式传入时不覆盖）
        request_param.setdefault("mchNo", self._config.mch_no)
        if self._config.app_id and "appId" not in request_param:
            request_param["appId"] = self._config.app_id
        request_param.setdefault("reqId", str(uuid.uuid4()))
        request_param.setdefault("reqTime", _now_beijing())
        request_param.setdefault("nonceStr", secrets.token_hex(16))

        # 走 JSON 签名路径：序列化 → 对 JSON 签名 → 注入 sign → 重新序列化发送
        json_for_sign = json.dumps(request_param, ensure_ascii=False)
        sign_str = build_sign_str(json_for_sign)
        request_param["sign"] = rsa_sign(sign_str, self._config.private_key)
        body_text = json.dumps(request_param, ensure_ascii=False)
        if self._on_request is not None:
            self._on_request(body_text)

        raw_body = self._post(self._service_url + path, body_text.encode("utf-8"))
        # 验签在反序列化前先回调原文（验签失败时调用方也能拿到平台返回的原始报文）
        if self._on_response is not None:
            self._on_response(raw_body)

        try:
            result: NiuDunResult = json.loads(raw_body)
        except ValueError as error:
            raise NiuDunError(-1, f"响应解析失败: {raw_body}") from error
        if not isinstance(result, dict):
            raise NiuDunError(-1, f"响应解析失败: {raw_body}")

        # 验签策略：带 sign 的响应强制校验；成功响应必须带签名；失败响应可无签名。
        # 平台业务异常经全局异常处理器返回 Result 形状（code/message，无 sign，data 为 null），
        # 若一并按「必验签」处理，业务错误会被误报为验签失败、真实错误码与消息全部丢失。
        code = result.get("code", -1)
        sign = result.get("sign")
        if sign:
            # 用原始报文验签（不可先反序列化再签名，会丢精度与字面量格式）
            if not rsa_verify(build_sign_str(raw_body), sign, self._config.public_key):
                raise NiuDunError(ErrorCode.SIGN_VERIFY_FAILED, "响应验签失败")
        elif code == ErrorCode.SUCCESS:
            # 成功响应必须带签名，否则来源不可信（防伪造成功响应）
            raise NiuDunError(ErrorCode.SIGN_VERIFY_FAILED, "响应缺少签名，无法验证来源")

        if code != ErrorCode.SUCCESS:
            # 消息字段兼容：NiuDunResult 用 msg，管理 API Result 用 message（平台异常响应形状）
            msg = result.get("msg") or result.get("message") or ""
            if throw_on_biz_error:
                raise NiuDunError(code, msg)
            # 非 0 码时 data 必为空，原样返回（探针诊断路径）
            return result
        return result

    # ==================================================================
    # 支付族
    # ==================================================================

    def pay(self, param: PayParam) -> NiuDunResult:
        """支付下单 — POST /unipay/pay"""
        return self.execute("/unipay/pay", dict(param))

    def close(self, param: CloseParam) -> NiuDunResult:
        """关闭/撤销订单 — POST /unipay/close（响应 data 为 null，凭 code == 0 判断成功）"""
        return self.execute("/unipay/close", dict(param))

    def query_pay_order(self, param: PayQueryParam) -> NiuDunResult:
        """查询支付订单 — POST /unipay/query/pay-order（仅查本地单，不调通道）"""
        return self.execute("/unipay/query/pay-order", dict(param))

    def sync_pay_order(self, param: PaySyncParam) -> NiuDunResult:
        """支付订单同步 — POST /unipay/sync/order/pay（主动拉通道最新状态并回写本地，回调丢失的兜底补偿）"""
        return self.execute("/unipay/sync/order/pay", dict(param))

    # ==================================================================
    # 退款族
    # ==================================================================

    def refund(self, param: RefundParam) -> NiuDunResult:
        """退款 — POST /unipay/refund"""
        return self.execute("/unipay/refund", dict(param))

    def query_refund_order(self, param: RefundQueryParam) -> NiuDunResult:
        """查询退款订单 — POST /unipay/query/refund-order（仅查本地单，不调通道）"""
        return self.execute("/unipay/query/refund-order", dict(param))

    def sync_refund_order(self, param: RefundSyncParam) -> NiuDunResult:
        """退款订单同步 — POST /unipay/sync/order/refund"""
        return self.execute("/unipay/sync/order/refund", dict(param))

    # ==================================================================
    # 转账族
    # ==================================================================

    def transfer(self, param: TransferParam) -> NiuDunResult:
        """转账 — POST /unipay/transfer（通道直连，幂等维度：通道 + 商户转账号 + 商户号）"""
        return self.execute("/unipay/transfer", dict(param))

    def query_transfer_order(self, param: TransferQueryParam) -> NiuDunResult:
        """查询转账订单 — POST /unipay/query/transfer-order（仅查本地单，不调通道）"""
        return self.execute("/unipay/query/transfer-order", dict(param))

    def sync_transfer_order(self, param: TransferSyncParam) -> NiuDunResult:
        """转账订单同步 — POST /unipay/sync/order/transfer"""
        return self.execute("/unipay/sync/order/transfer", dict(param))

    # ==================================================================
    # 分账族
    # ==================================================================

    def alloc(self, param: AllocParam) -> NiuDunResult:
        """分账 — POST /unipay/alloc（原支付单须下单时声明 allocation=true）"""
        return self.execute("/unipay/alloc", dict(param))

    def query_alloc_order(self, param: AllocQueryParam) -> NiuDunResult:
        """查询分账订单 — POST /unipay/query/alloc-order（仅查本地单，不调通道）"""
        return self.execute("/unipay/query/alloc-order", dict(param))

    def sync_alloc_order(self, param: AllocSyncParam) -> NiuDunResult:
        """分账订单同步 — POST /unipay/sync/order/alloc"""
        return self.execute("/unipay/sync/order/alloc", dict(param))

    # ==================================================================
    # 网关族
    # ==================================================================

    def gateway_pre_pay(self, param: GatewayPrePayParam) -> NiuDunResult:
        """网关预下单 — POST /unipay/gateway/pre-pay（返回收银台跳转地址 h5Url / miniUrl）"""
        return self.execute("/unipay/gateway/pre-pay", dict(param))

    def gateway_query(self, param: GatewayOrderQueryParam) -> NiuDunResult:
        """网关订单查询 — POST /unipay/gateway/query"""
        return self.execute("/unipay/gateway/query", dict(param))

    # ==================================================================
    # 探针与回调
    # ==================================================================

    def signed_ping(self, param: PingParam) -> NiuDunResult:
        """签名自检探针 — POST /unipay/ping（走完整验签链路，一键判定商户号/应用/私钥/签名串是否可用）

        与免签名的 [ping][niudun_open_sdk.client.NiuDunClient.ping] 互补：本方法由持商户私钥方发起，
        非 0 业务码不抛异常而是原样返回，供调用方按 code 分类诊断（20052=验签失败且 msg 含服务端待签串；
        10408-10411=nonce/时钟；其余=商户号/应用类）；响应验签失败仍抛异常（平台公钥配置问题）。
        """
        return self.execute("/unipay/ping", dict(param), throw_on_biz_error=False)

    def ping(self) -> str:
        """回调链路自检探针 — GET /unipay/callback/ping（免签名免登录，返回固定标识文本）

        用于部署自检：探针可达即代表「通道回调」接口组已放行、后端地址配置正确。
        """
        request = urllib.request.Request(self._service_url + "/unipay/callback/ping", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise NiuDunError(-1, f"探针请求失败: HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise NiuDunError(-1, f"探针请求失败: {error.reason}") from error

    def verify_notice(self, raw_body: str) -> bool:
        """回调通知验签（原始 HTTP body 字符串）— 对照契约第八节"""
        try:
            obj = json.loads(raw_body)
        except (TypeError, ValueError):
            return False
        if not isinstance(obj, dict) or not obj.get("sign"):
            return False
        return rsa_verify(build_sign_str(raw_body), obj["sign"], self._config.public_key)

    # ==================================================================
    # HTTP 基础设施
    # ==================================================================

    def _post(self, url: str, body: bytes) -> str:
        """POST JSON 报文并返回原始响应文本"""
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise NiuDunError(-1, f"请求失败: HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise NiuDunError(-1, f"请求失败: {error.reason}") from error


__all__ = ["DEFAULT_TIMEOUT", "NiuDunClient", "NiuDunObserver"]
