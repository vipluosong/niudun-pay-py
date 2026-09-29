"""RSA 签名/验签 — SHA256withRSA，对照后端 RsaSignUtil

私钥 PKCS#8 PEM；公钥 X.509 PEM；数据显式 UTF-8；输出标准 Base64（非 URL-safe、无换行）。
"""
from __future__ import annotations

import base64
import re

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# 密钥文本容错归一。
#
# 从网页、聊天窗口、PDF、IDE 复制 PEM 时，正文换行常被替换成空格或不换行空格（NBSP），
# 或整段压成一行、混入零宽字符，甚至只剩裸 Base64。这里在标准解析失败后做一次归一：
# 剥掉头尾标记、剔除全部空白与不可见字符，再按 Base64（含无填充变体）解出 DER，
# 交由 cryptography 按 X.509 / PKCS#1 解析（与 Go/Java/Node/PHP 版同一套行为）。
_INVISIBLE_RE = re.compile(r"[\s\u200b\u200c\u200d\u2060\ufeff\u00ad]+")
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]+")


def _strip_armor(text: str) -> str:
    """剥掉 -----BEGIN xxx----- / -----END xxx----- 标记，返回中间内容"""
    body = text
    begin = body.find("-----BEGIN")
    if begin >= 0:
        body = body[begin + len("-----BEGIN"):]
        # 跳过 " xxx-----" 到起始标记结束
        close = body.find("-----")
        if close >= 0:
            body = body[close + len("-----"):]
    end = body.find("-----END")
    if end >= 0:
        body = body[:end]
    return body


def _to_der(text: str, label: str) -> bytes:
    """从任意形态的密钥文本中提取 DER"""
    if not text or not text.strip():
        raise ValueError(f"{label}内容为空")
    body = _INVISIBLE_RE.sub("", _strip_armor(text))
    if not body:
        raise ValueError("未找到密钥内容，请确认已完整复制 PEM（含 BEGIN / END 两行）")
    unpadded = body.rstrip("=")
    if not _BASE64_RE.fullmatch(unpadded) or len(unpadded) % 4 == 1:
        raise ValueError("密钥内容不是合法的 Base64，请确认复制完整且未混入其它字符")
    try:
        # 部分来源会去掉 Base64 末尾的填充等号，这里补齐后再严格解码
        return base64.b64decode(unpadded + "=" * (-len(unpadded) % 4), validate=True)
    except Exception as error:  # noqa: BLE001 - 归一后仍失败，回显底层原因
        raise ValueError(f"密钥内容不是合法的 Base64：{error}") from error


def load_private_key(private_key_pem: str):
    """加载商户私钥（PKCS#8 优先，回退 PKCS#1）

    文本先经容错归一，兼容换行丢失 / 混入不可见字符的粘贴形态。
    """
    try:
        return serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    except Exception:  # noqa: BLE001 - 标准 PEM 解析失败，落到容错归一
        pass
    der = _to_der(private_key_pem, "私钥")
    try:
        return serialization.load_der_private_key(der, password=None)
    except Exception as error:  # noqa: BLE001 - 归一后仍不是私钥
        raise ValueError(
            "私钥解析失败：需为 PKCS#8（-----BEGIN PRIVATE KEY-----）"
            "或 PKCS#1（-----BEGIN RSA PRIVATE KEY-----）格式的 RSA 私钥"
        ) from error


def load_public_key(public_key_pem: str):
    """加载平台公钥（X.509 优先，回退 PKCS#1）

    文本先经容错归一，兼容换行丢失 / 混入不可见字符的粘贴形态。
    """
    try:
        return serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    except Exception:  # noqa: BLE001 - 标准 PEM 解析失败，落到容错归一
        pass
    der = _to_der(public_key_pem, "公钥")
    try:
        return serialization.load_der_public_key(der)
    except Exception as error:  # noqa: BLE001 - 归一后仍不是公钥
        raise ValueError(
            "公钥解析失败：需为 X.509（-----BEGIN PUBLIC KEY-----）"
            "或 PKCS#1（-----BEGIN RSA PUBLIC KEY-----）格式的 RSA 公钥"
        ) from error


def validate_private_key_pem(private_key_pem: str) -> None:
    """校验商户私钥是否可解析（联调页保存配置时即时反馈）；失败抛带原因的异常"""
    load_private_key(private_key_pem)


def validate_public_key_pem(public_key_pem: str) -> None:
    """校验平台公钥是否可解析（联调页保存配置时即时反馈）；失败抛带原因的异常"""
    load_public_key(public_key_pem)


def rsa_sign(data: str, private_key_pem: str) -> str:
    """RSA 签名（SHA256withRSA，UTF-8，Base64 输出）— 对照后端 RsaSignUtil#sign"""
    private_key = load_private_key(private_key_pem)
    signature = private_key.sign(
        data.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
    )
    return base64.b64encode(signature).decode("ascii")


def rsa_verify(data: str, sign_b64: str, public_key_pem: str) -> bool:
    """RSA 验签（SHA256withRSA）— 对照后端 RsaSignUtil#verify

    验签失败返回 False（不抛异常），便于调用方直接做布尔判定。
    """
    public_key = load_public_key(public_key_pem)
    try:
        public_key.verify(
            base64.b64decode(sign_b64),
            data.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False
