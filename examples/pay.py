# 牛盾聚合支付下单示例 — Python
# 运行前：启动后端（niudun-start，端口 9999），并替换为真实商户密钥
# 运行：python examples/pay.py

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from niudun_pay import Config, NiuDunClient, NiuDunError  # noqa: E402

# 商户私钥 + 平台公钥（PEM 文本，生产环境从配置中心/环境变量读取，切勿硬编码）
PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
（替换为你的商户私钥）
-----END PRIVATE KEY-----"""

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
（替换为平台公钥）
-----END PUBLIC KEY-----"""


def main() -> None:
    client = NiuDunClient(
        Config(
            service_url="http://127.0.0.1:9999",
            mch_no="M200000001",
            app_id="APP001",
            private_key=PRIVATE_KEY,
            public_key=PUBLIC_KEY,
            timeout=30000,
        )
    )

    try:
        result = client.pay(
            {
                "bizOrderNo": "PAY20250805001",
                "title": "测试商品",
                "amount": 100,  # 分
                "method": "wechat_qr",
                "notifyUrl": "https://example.com/notify",
            }
        )
    except NiuDunError as error:
        print(f"下单失败: {error}")
        return

    # 支付参数体：二维码链接 (code_url) / 调起参数 (pay_info) / 跳转 URL (redirect_url)
    print(f"下单成功: orderNo={result.get('data', {}).get('orderNo')}")
    print(f"支付参数体: {result.get('data', {}).get('payBody')}")

    # 回调验签（异步通知原文）
    # ok = client.verify_notice(raw_body)


if __name__ == "__main__":
    main()
