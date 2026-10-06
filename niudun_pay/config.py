"""SDK 配置 — 对照 sdk-contract.md 第十节"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """客户端配置

    :param service_url: 网关地址（自动去尾斜杠），如 https://ndpay-api.qyyapp.com
    :param mch_no: 商户号
    :param private_key: 商户私钥 PEM（PKCS#8，-----BEGIN PRIVATE KEY-----）
    :param public_key: 平台公钥 PEM（X.509，-----BEGIN PUBLIC KEY-----）
    :param app_id: 应用号（可选，空则回落默认应用）
    :param timeout: 请求超时毫秒，默认 30000
    """

    service_url: str
    mch_no: str
    private_key: str
    public_key: str
    app_id: Optional[str] = None
    timeout: int = 30000
