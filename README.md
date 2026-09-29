# 牛盾支付 Open SDK for Python

牛盾支付 开放支付平台 Python SDK，封装支付下单、关闭、退款、订单查询与回调验签。

> **适配 牛盾支付 Open ≥ 1.0** · **Python 3.10+** · Apache-2.0 · 依赖 `cryptography`（RSA 签名），HTTP 走标准库 `urllib`

## 功能

- RSA 双向签名（SHA256withRSA，`cryptography` PKCS#1 v1.5），自动签名请求 / 验签响应与回调
- 走 JSON 签名路径，与开源版后端 `reqTime`（北京时间字面量）契约对齐
- 15 个开放接口：支付（下单/关单/查询/同步）、退款（退款/查询/同步）、转账（转账/查询/同步）、
  分账（分账/查询/同步）、网关（预下单/查单）+ 回调链路自检探针 `ping()`
- 异步回调验签（`verify_notice`）
- 联调 Demo：单命令启动的本地调试页 + 模拟回调接收端点（见下）
- 完整类型标注（`TypedDict` / `dataclass`）

## 安装（源码引入）

```bash
pip install git+https://gitee.com/qyyapp/niudun-pay-py.git
```

```python
from niudun_open_sdk import Config, NiuDunClient, NiuDunError
```

## 快速开始

```python
client = NiuDunClient(
    Config(
        service_url="https://sandbox.niudunpay.cn",
        mch_no="M200000001",
        app_id="APP001",
        private_key=merchant_private_key_pem,   # PEM 文本（PKCS#8）
        public_key=platform_public_key_pem,     # PEM 文本（X.509）
        timeout=30000,
    )
)

# 支付下单
result = client.pay({
    "bizOrderNo": "PAY20250805001",
    "title": "测试商品",
    "amount": 100,             # 分
    "method": "wechat_qr",
    "notifyUrl": "https://example.com/notify",
})
print(result["data"]["payBody"])

# 回调验签
# ok = client.verify_notice(raw_body)
```

### 联调回显钩子（observer）

排障时可拿到每次调用的「签名后完整请求体」与「平台原始响应体」（响应验签**之前**回调，
验签失败也能拿到原文）；不设置时零开销。每次交易调用建议用独立 client 实例（避免多线程共享状态）：

```python
client = NiuDunClient(config).set_observer(
    on_request=lambda signed_json: print("请求:", signed_json),
    on_response=lambda raw_body: print("响应:", raw_body),
)
```

## 联调 Demo

单命令启动的本地联调工具，**所有交易调用都经 SDK 真实调用链**（签名 / 请求 / 验签），
同时验证 SDK 与平台 unipay 接口两侧。HTTP 层用标准库 `http.server`，零新增运行时依赖。

```bash
python -m niudun_open_sdk.demo             # 默认端口 9794
python -m niudun_open_sdk.demo --port=9795 # 覆盖端口
```

启动后打开 <http://127.0.0.1:9794> ：

| 页面区域 | 说明 |
|---|---|
| 左栏 | 15 个开放接口按业务域分组（支付 / 退款 / 转账 / 分账 / 网关） |
| 中栏 | 字段表单（含嵌套列表、嵌套对象行编辑器）+ 发送按钮 + 结果回显 |
| 右栏 | **随表单实时生成的 Python 调用代码**（可直接复制到项目里用） |
| 底部 | 回调记录（页面轮询 `/demo/callbacks`） |

**页面内连接配置**（右上角「连接配置」按钮，保存在浏览器 localStorage，服务端只存内存、不落盘）：

- 平台服务地址（如 `http://127.0.0.1:9999`）、商户号、应用号（可选）
- 商户私钥（PKCS#8 PEM）、平台公钥（X.509 PEM）：字段缺省=保持原值、空串=清空、非空=替换
  （替换前做 PEM 解析校验，格式错即时提示）；密钥**不返回**给页面，只报「是否已配置」
- 「测试连接」按钮 → 服务端代调平台探针 `GET /unipay/callback/ping`（规避浏览器跨域）

**回调闭环**：把表单里 `notifyUrl` 的 `@callbackBase` 展开后的地址填给平台（页面默认已填
`http://127.0.0.1:9794/callback/pay`），平台异步通知会 POST 到本服务，服务端用平台公钥验签后
入队，页面底部实时展示「时间 / 类型 / 验签结果 / code / msg / 原始报文」；`POST /demo/callbacks/clear` 清空。

**结果回显**：每次交易都会显示 SDK 实际发出的签名请求体、平台原始响应、响应验签结果
（`true` 通过 / `false` 失败 / **「未签名」表示平台异常响应不带 sign**，非验签失败）、耗时与错误消息；
业务失败也是 HTTP 200 + `success:false`，错误消息形如 `[20023] 未找到指定的商户配置`。

**demo HTTP 契约**（供脚本/其它语言对照）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/`、`/index.html` | GET | 调试页 |
| `/demo/config` | GET / POST | 脱敏状态 / 保存配置 |
| `/demo/ping` | POST | 代调平台探针 |
| `/demo/{action}` | POST | 走 SDK 真实调用链（action 见下） |
| `/demo/callbacks` | GET | 回调记录列表 |
| `/demo/callbacks/clear` | POST | 清空回调记录 |
| `/callback/{pay\|refund\|transfer\|alloc}` | POST | 平台异步通知接收端点，固定返回 `SUCCESS` |

action 取值：`pay` `close` `query-pay-order` `sync-pay-order` `refund` `query-refund-order`
`sync-refund-order` `transfer` `query-transfer-order` `sync-transfer-order` `alloc`
`query-alloc-order` `sync-alloc-order` `gateway-pre-pay` `gateway-query`。

> 页面与五语言 SDK 联调 Demo 同源（Java 版端口 9799），路由与响应形状逐字对齐
> `_doc/design/sdk-demo-contract.md`。

## 测试

```bash
python -m unittest discover -s tests -t . -v
```

黄金向量（`tests/test_golden_vector.py`）与后端签名契约同源断言，V1/V2/V3 三组向量要求签名串与
RSA 签名值**字节级相等**（见 [`_doc/design/sdk-test-vectors.md`](https://gitee.com/qyyapp)）。

## 接口文档

- [接入准备](https://doc.open.niudun.cn/api/getting-started) · [签名规则](https://doc.open.niudun.cn/api/signature)
- 黄金测试向量：见 [`tests/test_golden_vector.py`](tests/test_golden_vector.py)（与后端签名契约同源断言）

## License

Apache-2.0，可自由用于商业项目与闭源集成，协议全文见 [LICENSE](LICENSE)。主仓库 [牛盾支付 Open](https://gitee.com/qyyapp) 核心为 LGPL-3.0-or-later，本 SDK 作为独立仓按 Apache-2.0 单独发布。

## 开源许可与来源

本项目基于 [DaxPay](https://github.com/opendaxpay) 开放的支付 SDK 改造，
按牛盾支付的命名规则重命名并适配，核心签名验签协议保持一致。

原项目采用 **Apache License 2.0**，本项目遵循同一许可：
`LICENSE` 文件中保留了原始版权与许可声明，任何修改均在源码中可见。
