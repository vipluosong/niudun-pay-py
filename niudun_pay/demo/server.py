"""牛盾聚合支付 Python SDK 联调 Demo 服务端

对照 `_doc/design/sdk-demo-contract.md` 第二节（demo HTTP 契约），与 Java 版
`cn.niudun.open.sdk.demo.DemoServer` 逐字对齐路由与响应形状。

设计要点：
- HTTP 层用标准库 `http.server`（`ThreadingHTTPServer`），SDK 零新增运行时依赖；
- 每次交易调用创建带独立 observer 的 client 实例，无线程共享状态；
- 配置整体替换（读方每次取最新快照），服务端只存内存不落盘；
- 页面文件按 pathlib 运行时读盘，改页面无需重启。
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Optional, Union
from urllib.parse import urlsplit

from niudun_pay.client import NiuDunClient
from niudun_pay.config import Config
from niudun_pay.errors import NiuDunError
from niudun_pay.rsa import validate_private_key_pem, validate_public_key_pem

# 默认监听端口（五语言端口规划：go 9791 / node 9792 / php 9793 / python 9794 / java 9799）
DEFAULT_PORT = 9794
# 默认平台服务地址（页面「连接配置」可随时改）
DEFAULT_SERVICE_URL = "http://127.0.0.1:9999"
# 回调记录保留上限（超出丢弃最老记录，新的在队首）
MAX_CALLBACKS = 200
# 调试页文件（随包分发，见 pyproject 的 package-data）
INDEX_FILE = Path(__file__).with_name("index.html")

def _signed_ping_action(client: NiuDunClient, param: Dict[str, Any]) -> None:
    """signed-ping 的交易调试包装：非 0 业务码转成异常（与其它接口的失败回显一致）

    探针 SDK 方法 `signed_ping` 本身不抛业务异常（探针职责是报告结果），
    在交易调试路径上把它转成与其它接口一致的错误回显；完整诊断走 /demo/signed-ping。
    """
    result = client.signed_ping(param)
    code = result.get("code", -1)
    if code != 0:
        raise NiuDunError(code, result.get("msg") or "")


# action → SDK 调用映射表（15 个业务接口 + 签名自检探针，新增接口只需在此登记一行）
# Python SDK 的 param 就是 dict（TypedDict 仅编辑器提示），页面提交的参数可直传；
# 值为方法名字符串时走 getattr 分发，特殊行为（探针非 0 码转错误路径）登记可调用对象
ACTIONS: Dict[str, Union[str, Callable[[NiuDunClient, Dict[str, Any]], None]]] = {
    # 支付族
    "pay": "pay",
    "close": "close",
    "query-pay-order": "query_pay_order",
    "sync-pay-order": "sync_pay_order",
    # 退款族
    "refund": "refund",
    "query-refund-order": "query_refund_order",
    "sync-refund-order": "sync_refund_order",
    # 转账族
    "transfer": "transfer",
    "query-transfer-order": "query_transfer_order",
    "sync-transfer-order": "sync_transfer_order",
    # 分账族
    "alloc": "alloc",
    "query-alloc-order": "query_alloc_order",
    "sync-alloc-order": "sync_alloc_order",
    # 网关族
    "gateway-pre-pay": "gateway_pre_pay",
    "gateway-query": "gateway_query",
    # 自检族：探针非 0 码在此转成异常，与其它接口的失败回显行为一致（完整诊断走 /demo/signed-ping）
    "signed-ping": _signed_ping_action,
}


# ======================================================================
# 运行期共享状态
# ======================================================================


def _now_gmt8() -> str:
    """当前时间的 GMT+8 字面量（yyyy-MM-dd HH:mm:ss）— 与 SDK 的 reqTime 同源"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def _trim_to_none(value: Any) -> Optional[str]:
    """取字符串并去首尾空白；空/缺失返回 None（对照 Java StrUtil.trimToNull）"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class DemoState:
    """共享状态：连接配置快照 + 回调记录队列

    配置以整体替换的方式更新（写方持锁换引用，读方取快照），保证单次调用内一致；
    回调记录用带 maxlen 的 deque（队首最新、超限自动丢最老），append/clear 由锁保护。
    """

    def __init__(self, port: int) -> None:
        self._lock = threading.Lock()
        self._config: Dict[str, Optional[str]] = {
            "serviceUrl": DEFAULT_SERVICE_URL,
            "mchNo": None,
            "appId": None,
            "privateKey": None,
            "publicKey": None,
        }
        # 对外可达的回调基址（生成默认 notifyUrl 用，跨机联调时以页面提示为准）
        self.callback_base = f"http://127.0.0.1:{port}"
        self.callbacks: Deque[Dict[str, Any]] = deque(maxlen=MAX_CALLBACKS)

    def snapshot(self) -> Dict[str, Optional[str]]:
        """取当前配置快照（密钥为 PEM 原文，仅服务端内存持有）"""
        with self._lock:
            return dict(self._config)

    def replace(self, config: Dict[str, Optional[str]]) -> None:
        """整体替换配置"""
        with self._lock:
            self._config = dict(config)

    @staticmethod
    def to_config(snapshot: Dict[str, Optional[str]]) -> Config:
        """配置快照 → SDK Config（密钥缺失时给空串，由调用方先行拦截）"""
        return Config(
            service_url=snapshot.get("serviceUrl") or DEFAULT_SERVICE_URL,
            mch_no=snapshot.get("mchNo") or "",
            private_key=snapshot.get("privateKey") or "",
            public_key=snapshot.get("publicKey") or "",
            app_id=snapshot.get("appId"),
        )

    def config_info(self) -> Dict[str, Any]:
        """当前配置的脱敏状态（不返回密钥内容，仅返回是否已配置）"""
        snapshot = self.snapshot()
        return {
            "serviceUrl": snapshot.get("serviceUrl"),
            "mchNo": snapshot.get("mchNo"),
            "appId": snapshot.get("appId"),
            "callbackBase": self.callback_base,
            "privateKeySet": bool((snapshot.get("privateKey") or "").strip()),
            "publicKeySet": bool((snapshot.get("publicKey") or "").strip()),
        }

    def add_callback(self, record: Dict[str, Any]) -> None:
        """新记录入队首（超上限自动丢最老）"""
        with self._lock:
            self.callbacks.appendleft(record)

    def callback_records(self) -> list:
        """回调记录列表（新的在队首）"""
        with self._lock:
            return list(self.callbacks)

    def clear_callbacks(self) -> None:
        """清空回调记录"""
        with self._lock:
            self.callbacks.clear()


# ======================================================================
# HTTP 服务
# ======================================================================


class DemoServer(ThreadingHTTPServer):
    """多线程 HTTP 服务（持有共享状态；每次请求一个线程，交易调用互不阻塞）"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple, state: DemoState) -> None:
        super().__init__(address, DemoHandler)
        self.state = state


class DemoHandler(BaseHTTPRequestHandler):
    """路由分发与各端点实现（路由顺序见 sdk-demo-contract.md §2.1）"""

    server_version = "牛盾聚合支付DemoPython/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def state(self) -> DemoState:
        """共享状态（挂在 server 上，多线程共享）"""
        return self.server.state  # type: ignore[attr-defined]

    # 覆盖默认的每请求 stderr 访问日志（与 Java 版一致，只在关键动作打日志）
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    # ------------------------------------------------------------------
    # 分发
    # ------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        # 去掉 query 串（页面不带 query，但 curl 调试常带 ?x=1）
        path = urlsplit(self.path).path
        try:
            # 调试页与静态资源
            if method == "GET" and path in ("/", "/index.html"):
                self._send_page()
                return
            # 连接配置：GET 读取脱敏状态 / POST 页面保存（配置存浏览器，服务端仅内存）
            if path == "/demo/config" and method in ("GET", "POST"):
                self._handle_config(method)
                return
            # 以下四条必须排在 /demo/* 通配交易路由之前，
            # 否则会被当作交易 action（解析空 body 报错）
            if method == "GET" and path == "/demo/callbacks":
                records = self.state.callback_records()
                self._send_json(200, {"count": len(records), "records": records})
                return
            if method == "POST" and path == "/demo/callbacks/clear":
                self.state.clear_callbacks()
                self._send_json(200, {"ok": True})
                return
            # 连通性自检：服务端代调平台探针（浏览器直连平台地址会跨域，故由本服务中转）
            if method == "POST" and path == "/demo/ping":
                self._handle_ping()
                return
            # 签名链路自检：服务端代调签名自检探针 POST /unipay/ping（「测试连接」第二段）
            if method == "POST" and path == "/demo/signed-ping":
                self._handle_signed_ping()
                return
            # 交易调试（经 SDK 真实调用链）
            if method == "POST" and path.startswith("/demo/"):
                self._handle_trade(path[len("/demo/"):])
                return
            # 平台异步通知接收端点（返回固定 SUCCESS，平台要求 HTTP 2xx 且 body 为 SUCCESS）
            if method == "POST" and (path == "/callback" or path.startswith("/callback/")):
                self._handle_callback(path[len("/callback"):].lstrip("/"))
                return
            self._send_json(404, {"error": f"not found: {path}"})
        except Exception as error:  # noqa: BLE001 - 兜底：任何异常都回 JSON 而非断连
            try:
                self._send_json(500, {"error": str(error)})
            except Exception:  # noqa: BLE001 - 响应已提交，无法回写
                pass

    # ------------------------------------------------------------------
    # /demo/config 连接配置（页面内配置，服务端只存内存不落盘）
    # ------------------------------------------------------------------

    def _handle_config(self, method: str) -> None:
        if method == "GET":
            self._send_json(200, self.state.config_info())
            return

        try:
            body = self._read_json_body()
        except ValueError:
            # 请求体非 UTF-8 或非 JSON：与空 body 同义处理，落到必填校验分支（对齐 Go/Node 的 400 响应）
            body = {}
        service_url = (_trim_to_none(body.get("serviceUrl")) or "")
        mch_no = (_trim_to_none(body.get("mchNo")) or "")
        if not service_url or not mch_no:
            self._send_json(400, {"error": "服务地址与商户号不能为空"})
            return

        # 密钥字段语义：缺省=保持原值；空串=清空；非空=替换（先做 PEM 解析校验，即时反馈格式错误）
        current = self.state.snapshot()
        private_key = current.get("privateKey")
        if "privateKey" in body:
            value = _trim_to_none(body.get("privateKey"))
            if value is None:
                private_key = None
            else:
                try:
                    validate_private_key_pem(value)
                except Exception as error:  # noqa: BLE001 - 校验失败细节回显给页面
                    self._send_json(400, {"error": f"商户私钥无效: {error}"})
                    return
                private_key = value

        public_key = current.get("publicKey")
        if "publicKey" in body:
            value = _trim_to_none(body.get("publicKey"))
            if value is None:
                public_key = None
            else:
                try:
                    validate_public_key_pem(value)
                except Exception as error:  # noqa: BLE001 - 校验失败细节回显给页面
                    self._send_json(400, {"error": f"平台公钥无效: {error}"})
                    return
                public_key = value

        # 整体替换配置（读方每次取最新快照）
        self.state.replace(
            {
                "serviceUrl": service_url,
                "mchNo": mch_no,
                "appId": _trim_to_none(body.get("appId")),
                "privateKey": private_key,
                "publicKey": public_key,
            }
        )
        print(f"[配置] 页面更新连接配置: {service_url} 商户 {mch_no}", flush=True)
        self._send_json(200, self.state.config_info())

    # ------------------------------------------------------------------
    # /demo/ping 连通性自检（服务端中转，规避浏览器跨域）
    # ------------------------------------------------------------------

    def _handle_ping(self) -> None:
        """代调平台自检探针 `GET /unipay/callback/ping`，供页面「测试连接」按钮使用"""
        config = self.state.to_config(self.state.snapshot())
        result: Dict[str, Any] = {"serviceUrl": config.service_url}
        begin = time.monotonic()
        try:
            marker = NiuDunClient(config).ping()
            result["success"] = True
            result["marker"] = marker
            result["durationMs"] = int((time.monotonic() - begin) * 1000)
        except Exception as error:  # noqa: BLE001 - 探针失败属联调有效结果
            message = str(error)
            # 401/404 是探针链路上最常见的两种情况，直接给出可操作的排查方向
            if "HTTP 401" in message or "HTTP 404" in message:
                message += "（需平台版本包含部署自检探针 /unipay/callback/ping，且网关放行该前缀）"
            result["success"] = False
            result["error"] = message
            result["durationMs"] = int((time.monotonic() - begin) * 1000)
        self._send_json(200, result)

    # ------------------------------------------------------------------
    # /demo/signed-ping 签名链路自检（服务端中转，规避浏览器跨域）
    # ------------------------------------------------------------------

    def _handle_signed_ping(self) -> None:
        """代调签名自检探针 `POST /unipay/ping`，供页面「测试连接」第二段使用：
        判定当前配置的商户号/应用/商户私钥/签名串构造是否正确、能否发起真实调用
        """
        snapshot = self.state.snapshot()
        result: Dict[str, Any] = {"serviceUrl": snapshot.get("serviceUrl")}
        begin = time.monotonic()
        private_key = (snapshot.get("privateKey") or "").strip()
        public_key = (snapshot.get("publicKey") or "").strip()
        if not private_key or not public_key:
            result["success"] = False
            result["hint"] = (
                "尚未配置商户私钥，请先在「连接配置」中填写"
                if not private_key
                else "尚未配置平台公钥（响应无法验签），请先在「连接配置」中填写"
            )
            self._send_json(200, result)
            return
        # observer 捕获发出报文与原始响应，供页面比对签名串（发出 JSON vs 服务端待签串）
        captured: Dict[str, Optional[str]] = {"request": None, "response": None}
        client = NiuDunClient(self.state.to_config(snapshot)).set_observer(
            on_request=lambda signed: captured.__setitem__("request", signed),
            on_response=lambda raw: captured.__setitem__("response", raw),
        )
        try:
            probe = client.signed_ping({})
            code = probe.get("code", -1)
            result["success"] = code == 0
            result["code"] = code
            result["msg"] = probe.get("msg")
            result["data"] = probe.get("data")
            if code != 0:
                result["hint"] = _classify_probe_error(code)
        except Exception as error:  # noqa: BLE001 - 硬错误：网络不通 / HTTP 非 200 / 响应验签失败（平台公钥问题）
            message = str(error)
            result["success"] = False
            result["error"] = message
            if "响应验签失败" in message:
                result["hint"] = "平台响应验签失败：请核对「连接配置」中的平台公钥"
            elif "HTTP 404" in message:
                result["hint"] = "网关未放行「商户开放 API」(/unipay) 接口组，需在部署面板开启"
        finally:
            result["requestBody"] = captured["request"]
            result["responseBody"] = captured["response"]
            result["durationMs"] = int((time.monotonic() - begin) * 1000)
        self._send_json(200, result)

    # ------------------------------------------------------------------
    # /demo/* 交易调试
    # ------------------------------------------------------------------

    def _handle_trade(self, action: str) -> None:
        try:
            param = self._read_json_body()
        except ValueError as error:
            # 请求体非 UTF-8 或非 JSON：按统一回显结构返回（对齐 Go 版，不让 500 破坏契约形状）
            self._send_json(
                200,
                {
                    "success": False,
                    "requestBody": None,
                    "responseBody": None,
                    "durationMs": 0,
                    "signVerified": None,
                    "result": None,
                    "error": f"请求参数解析失败: {error}",
                },
            )
            return
        snapshot = self.state.snapshot()
        if not (snapshot.get("privateKey") or "").strip():
            self._send_json(
                200,
                {
                    "success": False,
                    "requestBody": None,
                    "responseBody": None,
                    "durationMs": 0,
                    "signVerified": None,
                    "result": None,
                    "error": "尚未配置商户私钥，请点击右上角「连接配置」填写后重试",
                },
            )
            return

        action_impl = ACTIONS.get(action)
        if action_impl is None:
            self._send_json(404, {"error": f"unknown action: {action}"})
            return

        # observer 捕获本次调用的请求体/响应体（每次调用独立实例，线程安全）
        captured: Dict[str, Optional[str]] = {"request": None, "response": None}
        client = NiuDunClient(self.state.to_config(snapshot)).set_observer(
            on_request=lambda signed: captured.__setitem__("request", signed),
            on_response=lambda raw: captured.__setitem__("response", raw),
        )

        begin = time.monotonic()
        error_message: Optional[str] = None
        try:
            if callable(action_impl):
                action_impl(client, dict(param))
            else:
                getattr(client, action_impl)(dict(param))
        except Exception as error:  # noqa: BLE001 - SDK 抛出（业务失败/验签失败/网络异常）属有效联调结果
            error_message = str(error)
        duration_ms = int((time.monotonic() - begin) * 1000)

        # 组装统一回显结构：SDK 实际发出的签名请求 + 平台原始响应 + 解析结果 + 验签
        self._send_json(
            200,
            {
                "success": error_message is None,
                "requestBody": captured["request"],
                "responseBody": captured["response"],
                "durationMs": duration_ms,
                "signVerified": _verify_response(captured["response"], snapshot),
                "result": _parse_result(captured["response"]),
                "error": error_message,
            },
        )

    # ------------------------------------------------------------------
    # /callback/* 异步通知接收
    # ------------------------------------------------------------------

    def _handle_callback(self, callback_type: str) -> None:
        body = self._read_body()
        snapshot = self.state.snapshot()
        record: Dict[str, Any] = {
            "time": _now_gmt8(),
            "type": callback_type,
            "signVerified": False,
            "code": None,
            "msg": None,
            "body": body,
        }
        public_key = (snapshot.get("publicKey") or "").strip()
        if not public_key:
            record["signVerified"] = False
            record["msg"] = "平台公钥未配置，无法验签（请在页面「连接配置」中补充）"
        else:
            try:
                record["signVerified"] = NiuDunClient(self.state.to_config(snapshot)).verify_notice(body)
                payload = json.loads(body)
                record["code"] = payload.get("code")
                record["msg"] = payload.get("msg")
            except Exception as error:  # noqa: BLE001 - 解析失败也留记录，便于页面排查
                record["signVerified"] = False
                record["msg"] = f"解析失败: {error}"
        self.state.add_callback(record)
        print(
            f"[回调] {record['time']} {record['type'] or '(通用)'} 验签={record['signVerified']}",
            flush=True,
        )
        # 平台要求 HTTP 2xx 且 body 等于 SUCCESS（忽略大小写）
        self._send_text(200, "SUCCESS")

    # ------------------------------------------------------------------
    # HTTP 基础设施
    # ------------------------------------------------------------------

    def _read_body(self) -> str:
        """读取请求体原始文本（按 Content-Length 读定长，避免阻塞）"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return ""
        return self.rfile.read(length).decode("utf-8")

    def _read_json_body(self) -> Dict[str, Any]:
        """读取并解析 JSON 请求体；空 body 视为空对象（对照 Java JSONUtil.parseObj("")）"""
        body = self._read_body().strip()
        if not body:
            return {}
        payload = json.loads(body)
        return payload if isinstance(payload, dict) else {}

    def _send_page(self) -> None:
        """返回调试页（运行时读盘，改页面无需重启）"""
        if not INDEX_FILE.is_file():
            self._send_json(500, {"error": f"调试页文件不存在: {INDEX_FILE}"})
            return
        data = INDEX_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, body: Dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, status: int, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ======================================================================
# 响应辅助（demo 层独立复核，便于对照 SDK 内部行为）
# ======================================================================


def _verify_response(response_body: Optional[str], snapshot: Dict[str, Optional[str]]) -> Optional[bool]:
    """响应验签复核

    返回 None 表示响应不带签名——平台业务异常经全局异常处理器返回 Result 形状（无 sign），
    页面据此显示「未签名」而非「验签失败」。
    """
    if not response_body:
        return None
    try:
        payload = json.loads(response_body)
        if not isinstance(payload, dict) or not payload.get("sign"):
            return None
        return NiuDunClient(DemoState.to_config(snapshot)).verify_notice(response_body)
    except Exception:  # noqa: BLE001 - 验签异常一律视为未通过
        return False


def _parse_result(response_body: Optional[str]) -> Any:
    """从原始响应解析展示对象（业务失败时不抛异常，原样透出 code/msg）"""
    if not response_body:
        return None
    try:
        return json.loads(response_body)
    except Exception:  # noqa: BLE001 - 非 JSON 响应原样透出
        return {"parseError": response_body}


def _classify_probe_error(code: int) -> str:
    """探针错误码分类提示（对照契约 6.14 诊断表）"""
    if code == 20052:
        return "验签失败：商户私钥与平台上配置的公钥不配对，或签名串构造不一致——比对「发出报文」与响应 msg 中的服务端待签串"
    if code in (10408, 10409):
        return "Nonce 防重放拦截：请勿复用请求（每次点击都会生成新 nonce）"
    if code in (10410, 10411):
        return "请求时间超窗：本机时钟偏差过大，或 reqTime 未按 GMT+8 yyyy-MM-dd HH:mm:ss 字面量"
    return f"商户号/应用类错误（code {code}）：核对 mchNo 与 appId 是否存在且启用"


# ======================================================================
# 启动
# ======================================================================


def serve(port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> DemoServer:
    """创建并启动 demo 服务（返回 server 实例，便于测试与优雅关闭）

    :param port: 监听端口，默认 9794
    :param host: 监听地址，默认仅本机
    """
    state = DemoState(port)
    server = DemoServer((host, port), state)

    print("牛盾聚合支付 Python SDK 联调 Demo 已启动", flush=True)
    print(f"  调试页面 : http://{host}:{port}", flush=True)
    print(f"  平台地址 : {state.config_info()['serviceUrl']}  (商户未配置，请打开页面填写)", flush=True)
    print("  密钥状态 : 商户私钥 未配置 / 平台公钥 未配置  (可在页面「连接配置」中随时修改)", flush=True)
    print(f"  回调基址 : {state.callback_base}  (支付通知可填 {state.callback_base}/callback/pay)", flush=True)
    print(
        "  连接配置 : 本实现无配置文件，请打开页面在「连接配置」中填写参数"
        "（保存在浏览器本地，服务端不落盘）",
        flush=True,
    )
    print("  停止服务 : Ctrl+C", flush=True)

    thread = threading.Thread(target=server.serve_forever, name="niudun-demo", daemon=True)
    thread.start()
    return server


def main(argv: Optional[list] = None) -> None:
    """命令行入口：`python -m niudun_pay.demo [--port=9794]`"""
    parser = argparse.ArgumentParser(
        prog="python -m niudun_pay.demo",
        description="牛盾聚合支付 Python SDK 联调 Demo（调试页 + 模拟回调接收端点）",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"监听端口，默认 {DEFAULT_PORT}")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1（仅本机）")
    args = parser.parse_args(argv)

    server = serve(port=args.port, host=args.host)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n已停止", flush=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
