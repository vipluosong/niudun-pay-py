"""牛盾支付 Python SDK 联调 Demo

单命令启动的本地联调工具，所有交易调用都经 [NiuDunClient][niudun_open_sdk.client.NiuDunClient]
走 SDK 真实调用链（签名 / 请求 / 验签），同时验证 SDK 与平台 unipay 接口两侧：

- `GET /` 内嵌调试页（`demo/index.html`）
- `GET|POST /demo/config` 连接配置（服务端只存内存、不落盘；页面保存在浏览器 localStorage）
- `POST /demo/ping` 连通性自检（服务端代调平台探针，规避浏览器跨域）
- `POST /demo/{action}` 调 SDK 发起真实请求，回显「签名后请求体 + 平台原始响应 + 验签结果」
- `POST /callback/{pay|refund|transfer|alloc}` 接收平台异步通知，验签后暂存
- `GET /demo/callbacks` 回调记录（页面轮询）；`POST /demo/callbacks/clear` 清空

启动：`python -m niudun_open_sdk.demo`（默认端口 9794，`--port=` 可覆盖）。
HTTP 层用标准库 `http.server`，不给 SDK 引入任何 Web 框架依赖。
"""
from niudun_open_sdk.demo.server import DEFAULT_PORT, main, serve

__all__ = ["DEFAULT_PORT", "main", "serve"]
