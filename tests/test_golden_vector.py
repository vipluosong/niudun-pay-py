"""黄金向量测试 — 五语言 SDK 签名行为一致性的硬验收标准

对照 `_doc/design/sdk-test-vectors.md`：V1/V2/V3 各断言三件套
（签名串严格相等 / 签名值 Base64 严格相等 / 公钥验签通过），V3 另加篡改失败用例。
运行：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import unittest

from niudun_pay.rsa import rsa_sign, rsa_verify
from niudun_pay.sign import build_sign_str
from tests.vectors import ALL_VECTORS, PRIVATE_KEY, PUBLIC_KEY, V3


class GoldenVectorTest(unittest.TestCase):
    """黄金向量：签名串拼接与 RSA 签名/验签"""

    def test_sign_str_matches_contract(self) -> None:
        """签名串拼接一致（排序 / 排除 sign / 嵌套与列表 / 中文与特殊字符不转义）"""
        for vector in ALL_VECTORS:
            with self.subTest(vector=vector.name):
                payload = json.dumps(vector.payload, ensure_ascii=False)
                self.assertEqual(vector.sign_str, build_sign_str(payload))

    def test_sign_value_matches_contract(self) -> None:
        """RSA 签名值一致（SHA256withRSA Base64）"""
        for vector in ALL_VECTORS:
            with self.subTest(vector=vector.name):
                self.assertEqual(vector.sign, rsa_sign(vector.sign_str, PRIVATE_KEY))

    def test_verify_with_public_key(self) -> None:
        """公钥验签通过"""
        for vector in ALL_VECTORS:
            with self.subTest(vector=vector.name):
                self.assertTrue(rsa_verify(vector.sign_str, vector.sign, PUBLIC_KEY))

    def test_tampered_payload_fails_verify(self) -> None:
        """篡改 msg 后验签失败"""
        tampered = dict(V3.payload)
        tampered["msg"] = "tampered"
        payload = json.dumps(tampered, ensure_ascii=False)
        self.assertFalse(rsa_verify(build_sign_str(payload), V3.sign, PUBLIC_KEY))

    def test_sign_key_is_excluded(self) -> None:
        """sign 字段（大小写不敏感）不参与签名串"""
        sign_str = build_sign_str(json.dumps({"a": "1", "sign": "x", "Sign": "y"}))
        self.assertEqual("a=1", sign_str)

    def test_null_skipped_and_empty_string_kept(self) -> None:
        """null 跳过；空字符串参与（对照 flatten 规则）"""
        sign_str = build_sign_str(json.dumps({"a": None, "b": "", "c": 0}))
        self.assertEqual("b=&c=0", sign_str)


if __name__ == "__main__":
    unittest.main()
