"""密钥文本容错测试 — 各种「能看不能用」的 PEM 粘贴形态都应解析出同一把密钥

对照 Go 版 `niudun/pem_test.go` 同名用例：五语言 SDK 行为一致。
运行：python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import unittest

from cryptography.hazmat.primitives import serialization

from niudun_open_sdk.rsa import (
    load_private_key,
    load_public_key,
    rsa_sign,
    rsa_verify,
    validate_public_key_pem,
)
from tests.vectors import PRIVATE_KEY, PUBLIC_KEY, V1


def split_pem(pem: str) -> tuple[str, str, str]:
    """拆出 PEM 的头行 / 正文 / 尾行"""
    lines = pem.strip().split("\n")
    return lines[0], "\n".join(lines[1:-1]), lines[-1]


def rewrap(body: str, sep: str, width: int = 64) -> str:
    """把正文按 width 重新分行，行间以 sep 连接（width <= 0 表示整段一行）"""
    flat = body.replace("\n", "")
    if width <= 0:
        return flat
    return sep.join(flat[i : i + width] for i in range(0, len(flat), width))


HEAD, BODY, FOOT = split_pem(PUBLIC_KEY)
FLAT = rewrap(BODY, "", 0)
BODY_LF = rewrap(BODY, "\n")
BODY_SPACE = rewrap(BODY, " ")
BODY_NBSP = rewrap(BODY, "\u00a0")

WANT_SPKI = load_public_key(PUBLIC_KEY).public_bytes(
    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
)

PUBLIC_KEY_CASES = {
    "标准 PEM": PUBLIC_KEY,
    "正文单行不换行": f"{HEAD}\n{FLAT}\n{FOOT}",
    "正文换行→空格": f"{HEAD}\n{BODY_SPACE}\n{FOOT}",
    "全文压成一行": f"{HEAD} {BODY_SPACE} {FOOT}",
    "BEGIN 行尾换行→空格": f"{HEAD} {BODY_LF}\n{FOOT}",
    "END 前换行→空格": f"{HEAD}\n{BODY_LF} {FOOT}",
    "正文含 NBSP": f"{HEAD}\n{FLAT[:64]}\u00a0{FLAT[64:]}\n{FOOT}",
    "NBSP 当换行分隔符": f"{HEAD}\n{BODY_NBSP}\n{FOOT}",
    "正文含零宽空格": f"{HEAD}\n{FLAT[:64]}\u200b{FLAT[64:]}\n{FOOT}",
    "正文含 BOM": f"{HEAD}\n{FLAT[:64]}\ufeff{FLAT[64:]}\n{FOOT}",
    "裸 Base64（无头尾标记）": FLAT,
    "CRLF 换行": PUBLIC_KEY.replace("\n", "\r\n"),
    "CR 换行": PUBLIC_KEY.strip().replace("\n", "\r"),
    "前后带说明文字": f"这是平台公钥：\n{PUBLIC_KEY}\n请妥善保管",
}


class PemToleranceTest(unittest.TestCase):
    """变形密钥文本的解析容错"""

    def test_public_key_variants(self) -> None:
        """公钥各种粘贴形态都应解析出同一把公钥"""
        for name, text in PUBLIC_KEY_CASES.items():
            with self.subTest(case=name):
                got = load_public_key(text).public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                self.assertEqual(WANT_SPKI, got)

    def test_private_key_variants(self) -> None:
        """私钥同样覆盖变形形态（PKCS#8）"""
        priv_head, priv_body, priv_foot = split_pem(PRIVATE_KEY)
        priv_flat = rewrap(priv_body, "", 0)
        want = load_private_key(PRIVATE_KEY).private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        cases = {
            "标准 PEM": PRIVATE_KEY,
            "全文压成一行": f"{priv_head} {rewrap(priv_body, ' ')} {priv_foot}",
            "正文含 NBSP": f"{priv_head}\n{priv_flat[:64]}\u00a0{priv_flat[64:]}\n{priv_foot}",
            "裸 Base64（无头尾标记）": priv_flat,
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                got = load_private_key(text).private_bytes(
                    serialization.Encoding.DER,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
                self.assertEqual(want, got)

    def test_flattened_public_key_still_verifies(self) -> None:
        """变形公钥仍可完成验签"""
        sign = rsa_sign(V1.sign_str, PRIVATE_KEY)
        self.assertTrue(rsa_verify(V1.sign_str, sign, f"{HEAD} {BODY_SPACE} {FOOT}"))

    def test_validate_entry_allows_flattened(self) -> None:
        """联调页保存配置走的校验入口放行变形公钥"""
        validate_public_key_pem(f"{HEAD} {BODY_SPACE} {FOOT}")

    def test_error_messages(self) -> None:
        """非法输入给出可定位的报错"""
        cases = [
            ("   ", "内容为空"),
            ("这不是密钥", "不是合法的 Base64"),
            ("-----BEGIN PUBLIC KEY-----", "未找到密钥内容"),
            ("YWJjZGVmZ2g=", "需为 X.509"),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as ctx:
                    load_public_key(text)
                self.assertIn(want, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
