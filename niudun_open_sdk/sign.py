"""签名字符串构造 — 严格复刻后端 JsonSignStrUtil

权威源: cn.niudun.open.payment.common.util.JsonSignStrUtil
规则（对照 sdk-test-vectors.md 第一节）:
① 嵌套对象用 `.` 连接（terminal.terminalNo）；数组用 `[索引]`（goodsDetail[0]）
② null 跳过；空字符串参与（put 空串）
③ 数字按字面 toString（整数值浮点去尾零，对齐 BigDecimal.stripTrailingZeros）
④ 布尔小写字面量 true / false
⑤ key 按 ASCII 字典序升序（Java TreeMap / JS 默认 sort 同为 code unit 序）
⑥ key 等于 sign（大小写不敏感）不参与
⑦ `k1=v1&k2=v2` 拼接，末尾无 &，值不转义不编码
"""
from __future__ import annotations

import json
from typing import Any, Dict


def _format_scalar(value: Any) -> str:
    """标量字面量格式化 — 对齐 Java toString / JS String() 语义"""
    if isinstance(value, bool):
        # 布尔必须小写：Python str(True) 是 "True"，与平台口径不符
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # 整数值浮点去掉小数点（100.0 → "100"），对齐 BigDecimal 去尾零
        if value.is_integer():
            return str(int(value))
        return repr(value)
    return str(value)


def _flatten(prefix: str, value: Any, result: Dict[str, str]) -> None:
    """递归扁平化（对照后端 JsonSignStrUtil#flatten）"""
    if value is None:
        return
    # bool 是 int 的子类，必须先于数字判定
    if isinstance(value, (bool, int, float, str)):
        result[prefix] = _format_scalar(value)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _flatten(f"{prefix}[{index}]", item, result)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten(key if prefix == "" else f"{prefix}.{key}", item, result)


def build_sign_str(json_str: str) -> str:
    """构造待签名字符串（复刻 JsonSignStrUtil#buildSignStr）

    :param json_str: 已序列化的 JSON 字符串（原始报文，不要先反序列化为对象再回序列化）
    :return: 扁平化 + 排序 + 排除 sign 后的 `k=v&k=v` 串
    """
    root = json.loads(json_str)
    flat: Dict[str, str] = {}
    _flatten("", root, flat)
    parts = [
        f"{key}={flat[key]}"
        for key in sorted(flat)
        if key.lower() != "sign"
    ]
    return "&".join(parts)
