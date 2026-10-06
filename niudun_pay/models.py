"""请求/响应模型 — 对照 sdk-contract.md 第二、四、五及 6.1–6.14 节

键名即报文键名（camelCase），SDK 直接序列化该 dict，不做键名转换。
TypedDict 仅用于编辑器提示，运行时就是普通 dict。

约定：
- 标注 `# 必填` 的键必须由调用方提供（运行时不做校验，由平台参数校验兜底）；
- 标注 `# 二选一` 的键组至少提供一个；
- 金额一律 int，单位**分**（最小货币单位，如 100 = 1.00 元）；
- 时间字段为字符串字面量：请求侧 GMT+8 `yyyy-MM-dd HH:mm:ss`，响应侧北京时间同格式。
"""
from __future__ import annotations

from typing import Any, List, Optional, TypedDict

# ======================================================================
# 公共结构
# ======================================================================


class NiuDunResult(TypedDict, total=False):
    """统一响应结构（契约第五节）"""

    code: int  # 业务状态码，0 成功，非 0 失败
    msg: str  # 提示信息（是 msg 非 message）
    data: Optional[Any]  # 业务数据，失败时通常 null
    sign: str  # 平台 RSA 响应签名（Base64）
    resTime: str  # 响应时间（北京时间 yyyy-MM-dd HH:mm:ss）
    reqId: str  # 请求 ID 回显


class CommonParam(TypedDict, total=False):
    """公共请求参数（所有业务请求继承，对照契约第四节）

    mchNo / appId / reqId / reqTime / nonceStr 由 SDK 自动注入，调用方无需传。
    """

    mchNo: str
    appId: str
    reqId: str
    reqTime: str  # 请求时间（SDK 自动生成，北京时间 yyyy-MM-dd HH:mm:ss 字面量）
    nonceStr: str
    clientIp: str
    sign: str


# ======================================================================
# 共享嵌套类型（契约 6.6 节）
# ======================================================================


class TerminalInfo(TypedDict, total=False):
    """终端信息（线下 POS / 收银台场景，挂在 PayParam 上）"""

    terminalNo: str
    storeNo: str
    operatorId: str
    deviceName: str
    deviceIp: str
    longitude: float
    latitude: float


class GoodsDetail(TypedDict, total=False):
    """商品明细（单品营销 / 电子发票；PayParam 与 GatewayPrePayParam 共用）"""

    goodsId: str  # 必填，商户侧商品编码
    goodsName: str  # 必填，商品名称
    quantity: int  # 必填，商品数量（≥1）
    unitPrice: int  # 必填，商品单价（分）
    category: str  # 商品分类（支付宝独有）
    description: str
    showUrl: str


# ======================================================================
# 支付族（6.1 / 6.2 / 6.4 / 6.11）
# ======================================================================


class PayParam(CommonParam, total=False):
    """支付下单请求参数（契约 6.1 节）"""

    bizOrderNo: str  # 必填，商户订单号（≤100）
    title: str  # 必填，支付标题（≤100）
    description: str  # 支付描述（≤50）
    amount: int  # 必填，支付金额（分）
    currency: str  # 币种 ISO 4217，缺省 cny
    product: str  # 支付产品编码（空则路由自动选择）
    method: str  # 支付方式编码（路由模式一般必填；被扫可空）
    capability: str  # 支付能力编码
    openId: str  # 用户 OpenId（微信 jsapi/mini 场景必填）
    channelAppId: str  # 通道应用 AppId（微信 wxAppId 等）
    authCode: str  # 付款码（被扫支付必填）
    limitPay: List[str]  # 限制支付类型，如 ["no_credit"]
    extraParam: str  # 支付扩展参数（JSON 字符串）
    goodsDetail: List[GoodsDetail]  # 订单商品明细
    notifyUrl: str  # 异步通知地址（≤200）
    returnUrl: str  # 同步跳转地址（≤200）
    attach: str  # 商户扩展参数，回调原样返回（≤500）
    expiredTime: str  # 过期时间（北京时间 yyyy-MM-dd HH:mm:ss，空默认 30 分钟）
    terminal: TerminalInfo  # 终端信息
    source: str  # 订单来源标识
    allocation: bool  # 是否为分账订单（分账链路前置条件）


class NormalPayResult(TypedDict, total=False):
    """支付下单响应结果（契约 6.1 节）"""

    bizOrderNo: str  # 商户订单号
    orderNo: str  # 平台业务单号
    tradeNo: str  # 资金交易号
    status: str  # 资金态: init / processing / success / fail / close / cancel
    payBody: str  # 支付参数体（二维码链接 / 调起参数 / 跳转 URL）
    payBodyType: str  # code_url / pay_info / redirect_url


# 契约后端类名为 NormalPayResult，保留 PayResult 作为历史别名
PayResult = NormalPayResult


class CloseParam(CommonParam, total=False):
    """关闭/撤销订单请求参数（契约 6.2 节；响应 data 为 null，凭 code == 0 判断成功）"""

    orderNo: str  # 二选一，平台支付订单号(tradeNo)或网关订单号（优先）
    bizOrderNo: str  # 二选一，商户订单号
    useCancel: bool  # 是否使用撤销方式（部分通道支持，不支持则忽略）


class PayQueryParam(CommonParam, total=False):
    """查询支付订单请求参数（契约 6.4 节）"""

    orderNo: str  # 二选一，订单号（优先）
    bizOrderNo: str  # 二选一，商户订单号


class PayOrderResult(TypedDict, total=False):
    """支付订单查询结果（契约 6.4 节）"""

    bizOrderNo: str  # 商户订单号
    orderNo: str  # 平台业务单号
    tradeNo: str  # 资金交易号
    outOrderNo: str  # 通道系统交易号
    title: str
    description: str
    channel: str  # 支付通道
    method: str  # 支付方式
    limitPay: str  # 限制用户支付类型
    amount: int  # 金额（分）
    currency: str  # 币种 ISO 4217（如 cny/usd，缺省 cny）
    realAmount: int  # 实收金额（分）
    refundableBalance: int  # 可退款余额（分）
    status: str  # 支付状态
    refundStatus: str  # 退款状态
    provider: str  # 支付渠道（微信/支付宝/银联）
    payTime: str  # 支付时间（北京时间）
    closeTime: str  # 关闭时间（北京时间）
    expiredTime: str  # 过期时间（北京时间）
    terminalNo: str  # 终端设备编码
    storeNo: str  # 门店号
    buyerId: str  # 付款用户 ID
    attach: str  # 商户扩展参数（原样返回）
    errorMsg: str  # 错误信息


class PaySyncParam(CommonParam, total=False):
    """支付订单同步参数（契约 6.11 节；orderNo / bizOrderNo / outOrderNo 至少一个）"""

    orderNo: str  # 平台业务单号
    bizOrderNo: str  # 商户订单号
    outOrderNo: str  # 通道系统交易号


# ======================================================================
# 退款族（6.3 / 6.5 / 6.11）
# ======================================================================


class RefundParam(CommonParam, total=False):
    """退款请求参数（契约 6.3 节）"""

    tradeNo: str  # 二选一，原支付资金交易号（优先）
    bizOrderNo: str  # 二选一，原支付商户业务订单号
    amount: int  # 必填，退款金额（分，>0，支持部分退款）
    reason: str  # 退款原因（≤50）
    bizRefundNo: str  # 商户退款号（不传则系统生成）


class RefundResult(TypedDict, total=False):
    """退款响应结果（契约 6.3 节）"""

    refundNo: str  # 平台退款号
    bizRefundNo: str  # 商户退款号
    status: str  # 退款状态
    errorMsg: str  # 错误信息（失败时返回）


class RefundQueryParam(CommonParam, total=False):
    """查询退款订单请求参数（契约 6.5 节）"""

    refundNo: str  # 二选一，平台退款号（优先）
    bizRefundNo: str  # 二选一，商户退款号


class RefundOrderResult(TypedDict, total=False):
    """退款订单查询结果（契约 6.5 节）"""

    refundNo: str  # 平台退款号
    bizRefundNo: str  # 商户退款号
    tradeNo: str  # 原支付资金交易号
    bizOrderNo: str  # 原支付商户业务订单号
    outRefundNo: str  # 通道退款流水号
    amount: int  # 退款金额（分）
    orderAmount: int  # 订单总金额（分）
    status: str  # 退款状态
    reason: str  # 退款原因
    finishTime: str  # 退款完成时间（北京时间）
    errorMsg: str  # 错误信息


class RefundSyncParam(CommonParam, total=False):
    """退款订单同步参数（契约 6.11 节；refundNo 与 bizRefundNo 至少一个）"""

    refundNo: str  # 平台退款号（优先）
    bizRefundNo: str  # 商户退款号


# ======================================================================
# 转账族（6.7 / 6.10 / 6.11）
# ======================================================================


class ReportInfo(TypedDict, total=False):
    """转账场景报备信息（对照 Java `TransferParam.ReportInfo`）

    微信转账场景报备，字段含义由通道场景定义决定（如 1000 现金营销场景需报备活动名称）。
    """

    infoType: str  # 报备信息类型
    infoContent: str  # 报备信息内容


class TransferParam(CommonParam, total=False):
    """转账请求参数（契约 6.7 节）

    幂等维度：通道 + 商户转账号 + 商户号——同组合重复发起会拦截，失败单可复用原单号重试。
    """

    channel: str  # 必填，转账通道（wechat / alipay / douyin）
    channelMchNo: str  # 必填，通道商户号（转账凭证组装与通道路由用）
    bizTransferNo: str  # 必填，商户转账号（幂等键，同一商户同一通道下唯一）
    amount: int  # 必填，转账金额（分，>0）
    title: str  # 转账标题
    reason: str  # 转账原因/备注（≤200）
    payeeType: str  # 必填，收款人账号类型（微信=openid；支付宝=user_id/open_id/login_name；抖音=openid/phone）
    payeeAccount: str  # 必填，收款人账号
    payeeName: str  # 收款人姓名（微信：<0.3 元禁填，≥2000 元必填）
    attach: str  # 商户扩展参数，回调原样返回
    notifyUrl: str  # 回调通知地址
    reportInfos: List[ReportInfo]  # 转账场景报备信息（微信转账场景必填，留空由通道兜底）
    transferScene: str  # 转账场景标识（支付宝=场景配置 ID；抖音=枚举码如 1001；微信不传）


class TransferResult(TypedDict, total=False):
    """转账响应结果（契约 6.7 节 TransferCreateResult）"""

    transferNo: str  # 平台转账单号
    bizTransferNo: str  # 商户转账号
    status: str  # 转账状态
    confirmUrl: str  # 确认收款跳转地址（部分通道需收款人确认收款）


class TransferQueryParam(CommonParam, total=False):
    """转账订单查询请求参数（契约 6.10 节）

    transferNo 单独可查；bizTransferNo 须配 channel，与发起幂等维度保持一致。
    """

    transferNo: str  # 二选一，平台转账单号（优先）
    channel: str  # 配对，转账通道
    bizTransferNo: str  # 配对，商户转账号


class TransferOrderResult(TypedDict, total=False):
    """转账订单查询结果（契约 6.10 节）"""

    transferNo: str  # 平台转账单号
    bizTransferNo: str  # 商户转账号
    outTransferNo: str  # 通道转账单号
    relationNo: str  # 关联单号
    amount: int  # 转账金额（分）
    currency: str  # 币种 ISO 4217
    channel: str  # 转账通道
    provider: str  # 支付渠道（微信/支付宝/抖音）
    status: str  # 转账状态
    title: str  # 转账标题
    finishTime: str  # 转账完成时间
    errorMsg: str  # 错误信息


class TransferSyncParam(CommonParam, total=False):
    """转账订单同步参数（契约 6.11 节；transferNo 单独可查，bizTransferNo 须配 channel）"""

    transferNo: str  # 平台转账单号（优先）
    channel: str  # 转账通道（与商户转账号配对使用）
    bizTransferNo: str  # 商户转账号（与转账通道配对使用）


# ======================================================================
# 分账族（6.8 / 6.9 / 6.11）
# ======================================================================


class AllocReceiver(TypedDict, total=False):
    """分账接收方（对照 Java `AllocParam.Receiver`，契约 6.8 节）

    receiverType 取值见平台 `AllocReceiverTypeEnum`：
    MERCHANT_ID / PERSONAL_OPENID / PERSONAL_SUB_OPENID / USER_ID / LOGIN_NAME。
    """

    receiverType: str  # 必填，接收方类型
    receiverAccount: str  # 必填，接收方账号（≤128）
    receiverName: str  # 接收方姓名（部分通道/类型必填）
    amount: int  # 必填，分账金额（分，≥1）


class AllocParam(CommonParam, total=False):
    """分账请求参数（契约 6.8 节）

    原支付订单须在**下单时声明** `allocation=true`（分账订单），否则通道拒绝分账。
    接收方列表直接传入完整明细（极简模式，接收方绑定由调用方提前在通道侧完成）。
    """

    bizAllocNo: str  # 必填，商户分账单号（幂等键，同一应用下唯一，≤100）
    tradeNo: str  # 二选一，原支付资金交易号（优先）
    bizOrderNo: str  # 二选一，原支付商户业务订单号
    title: str  # 分账标题
    description: str  # 分账描述（≤500）
    receivers: List[AllocReceiver]  # 必填，接收方列表（至少一个）
    attach: str  # 商户扩展参数，回调时原样返回
    notifyUrl: str  # 异步通知地址


class AllocResult(TypedDict, total=False):
    """分账响应结果（契约 6.8 节）"""

    allocNo: str  # 平台分账单号
    bizAllocNo: str  # 商户分账单号
    status: str  # 分账状态
    errorMsg: str  # 错误信息（失败时返回）


class AllocQueryParam(CommonParam, total=False):
    """分账订单查询请求参数（契约 6.9 节；仅查本地单，不调通道）"""

    allocNo: str  # 二选一，平台分账单号（优先）
    bizAllocNo: str  # 二选一，商户分账单号


class AllocDetail(TypedDict, total=False):
    """分账接收方明细（对照 Java `AllocOrderResult.AllocDetail`）"""

    receiverType: str  # 接收方类型
    receiverAccount: str  # 接收方账号
    receiverName: str  # 接收方姓名
    amount: int  # 分账金额（分）
    result: str  # 该接收方分账结果
    errorMsg: str  # 错误信息
    finishTime: str  # 完成时间


class AllocOrderResult(TypedDict, total=False):
    """分账订单查询结果（契约 6.9 节）"""

    allocNo: str  # 平台分账单号
    bizAllocNo: str  # 商户分账单号
    tradeNo: str  # 原支付资金交易号
    bizOrderNo: str  # 商户业务订单号
    outAllocNo: str  # 通道分账单号
    amount: int  # 分账总金额（分）
    status: str  # 分账状态
    finishTime: str  # 分账完成时间
    channel: str  # 支付通道
    attach: str  # 商户扩展参数（原样返回）
    errorMsg: str  # 错误信息
    details: List[AllocDetail]  # 分账接收方明细列表


class AllocSyncParam(CommonParam, total=False):
    """分账订单同步参数（契约 6.11 节；allocNo 与 bizAllocNo 至少一个）"""

    allocNo: str  # 平台分账单号（优先）
    bizAllocNo: str  # 商户分账单号


# ======================================================================
# 订单同步统一结果（6.11 节：四个 SyncResult 字段完全一致）
# ======================================================================


class SyncResult(TypedDict, total=False):
    """订单同步结果（四个同步接口形状统一）"""

    orderStatus: str  # 同步后的订单状态
    adjust: bool  # 本次同步是否订正了本地状态（true = 本地状态被通道结果修正）


# 四个同步接口结果结构一致，按接口名分别导出便于类型标注
PaySyncResult = SyncResult
RefundSyncResult = SyncResult
AllocSyncResult = SyncResult
TransferSyncResult = SyncResult


# ======================================================================
# 网关族（6.12 / 6.13）
# ======================================================================


class GatewayPrePayParam(CommonParam, total=False):
    """网关预下单请求参数（契约 6.12 节）

    产品语义「网关支付」：由平台收银台承接支付项选择与调起，商户侧只需拿到跳转地址。
    """

    bizOrderNo: str  # 必填，商户订单号（≤100）
    title: str  # 必填，支付标题（≤100）
    description: str  # 支付描述
    amount: int  # 必填，支付金额（分）
    currency: str  # 币种 ISO 4217，缺省 cny
    gatewayPayType: str  # 网关支付类型：cashier（统一收银台）/ aggregate（聚合扫码一码多付）
    notifyUrl: str  # 异步通知地址
    returnUrl: str  # 同步跳转地址
    attach: str  # 商户扩展参数
    extraParam: str  # 支付扩展参数（JSON 字符串）
    expiredTime: str  # 过期时间（GMT+8 字面量）
    storeNo: str  # 门店编号
    goodsDetail: List[GoodsDetail]  # 订单商品明细（结构同 6.6）
    allocation: bool  # 是否为分账订单


class GatewayPrePayResult(TypedDict, total=False):
    """网关预下单结果（契约 6.12 节）"""

    orderNo: str  # 平台网关单号
    bizOrderNo: str  # 商户订单号
    status: str  # 订单状态
    gatewayType: str  # 网关支付类型（cashier / aggregate）
    h5Url: str  # H5 收银台跳转地址
    miniUrl: str  # 小程序收银台跳转地址
    expiredTime: str  # 过期时间


class GatewayOrderQueryParam(CommonParam, total=False):
    """网关订单查询请求参数（契约 6.13 节）

    注意基类差异：本参数继承**平台公共参数** `PaymentCommonParam`（非商户公共参数），
    `mchNo` / `appId` 是参数自身的可选字段，用于网关侧按应用定位订单（缺省由 SDK 注入）。
    """

    orderNo: str  # 二选一，平台网关单号
    bizOrderNo: str  # 二选一，商户业务单号
    appId: str  # 应用号
    mchNo: str  # 商户号


class GatewayOrderResult(TypedDict, total=False):
    """网关订单查询结果（契约 6.13 节）"""

    orderNo: str  # 平台网关单号
    bizOrderNo: str  # 商户业务单号
    gatewayType: str  # 网关支付类型
    title: str  # 支付标题
    description: str  # 支付描述
    amount: int  # 金额（分）
    currency: str  # 币种
    status: str  # 订单状态
    expiredTime: str  # 过期时间
    payTime: str  # 支付时间
    channel: str  # 支付通道
    method: str  # 支付方式
    product: str  # 支付产品编码
    tradeNo: str  # 资金交易号
    outOrderNo: str  # 通道系统交易号
    fundStatus: str  # 资金状态
    attach: str  # 商户扩展参数
    returnUrl: str  # 同步跳转地址


# ======================================================================
# 自检探针（6.14）
# ======================================================================


class PingParam(CommonParam, total=False):
    """签名自检探针请求参数（契约 6.14 节）

    仅公共参数、无业务字段；mchNo / appId / reqId / reqTime / nonceStr 由 SDK 注入。
    """


class PingResult(TypedDict, total=False):
    """签名自检探针结果（契约 6.14 节）

    回显平台侧解析结果，供对接方核对商户身份与签名串构造。
    """

    mchNo: str  # 商户号
    appId: str  # 应用号
    appFromDefault: bool  # 是否回落平台默认应用
    serverSignStr: str  # 服务端待签串（验签失败时与本地发出报文比对定位差异）


__all__ = [
    "AllocDetail",
    "AllocOrderResult",
    "AllocParam",
    "AllocQueryParam",
    "AllocReceiver",
    "AllocResult",
    "AllocSyncParam",
    "AllocSyncResult",
    "CloseParam",
    "CommonParam",
    "NiuDunResult",
    "GatewayOrderQueryParam",
    "GatewayOrderResult",
    "GatewayPrePayParam",
    "GatewayPrePayResult",
    "GoodsDetail",
    "NormalPayResult",
    "PayOrderResult",
    "PayParam",
    "PayQueryParam",
    "PayResult",
    "PaySyncParam",
    "PaySyncResult",
    "PingParam",
    "PingResult",
    "RefundOrderResult",
    "RefundParam",
    "RefundQueryParam",
    "RefundResult",
    "RefundSyncParam",
    "RefundSyncResult",
    "ReportInfo",
    "SyncResult",
    "TerminalInfo",
    "TransferOrderResult",
    "TransferParam",
    "TransferQueryParam",
    "TransferResult",
    "TransferSyncParam",
    "TransferSyncResult",
]
