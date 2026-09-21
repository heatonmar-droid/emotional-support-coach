"""Robust JSON parsing without raw-output telemetry. / 健壮 JSON 解析，不记录原始输出。"""

import json
import logging
import re
from typing import Callable, Optional

logger = logging.getLogger(__name__)
_CODE_FENCE_RE = re.compile("```(?:json)?\\s*\\n?(.*?)\\n?```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(",\\s*([}\\]])")


def _try_loads_dict(candidate: str) -> Optional[dict]:
    """json.loads 且仅接受 dict（节点契约都是对象）；失败返回 None。"""
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_code_fence(text: str) -> Optional[str]:
    """策略②：提取第一个 ```json/``` 代码块内容。"""
    match = _CODE_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return None


def _extract_balanced_object(text: str) -> Optional[str]:
    """策略③：从第一个 { 开始，字符串/转义感知地找到平衡的闭合 }。"""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def _repair_common_issues(candidate: str) -> str:
    """策略④：一次性修复常见问题——尾逗号、单引号键/值、未闭合括号。

    只做保守文本变换，不保证语义；修复后仅再尝试一次 json.loads。
    """
    repaired = candidate.strip()
    repaired = _TRAILING_COMMA_RE.sub("\\1", repaired)
    if '"' not in repaired and "'" in repaired:
        repaired = repaired.replace("'", '"')
    depth_obj = 0
    depth_arr = 0
    in_string = False
    escaped = False
    for ch in repaired:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth_obj += 1
        elif ch == "}":
            depth_obj -= 1
        elif ch == "[":
            depth_arr += 1
        elif ch == "]":
            depth_arr -= 1
    if in_string:
        repaired += '"'
    repaired += "]" * max(depth_arr, 0)
    repaired += "}" * max(depth_obj, 0)
    return repaired


def parse_json_robust(
    text: str,
    fallback_factory: Optional[Callable[[], dict]] = None,
    node_name: str = "",
) -> dict:
    """从 LLM 输出中健壮地解析出一个 dict。

    策略链 ①直接 loads ②代码块 ③平衡 {...} ④修复后再试；全部失败调用
    fallback_factory()（未提供时返回 {}）。日志只记录策略，不包含原始正文。
    Log the parsing strategy only, never the raw model output.
    本函数不抛异常（fallback_factory 自身抛出除外——调用方兜底逻辑必须自持）。
    """
    raw = str(text or "")
    stripped = raw.strip()
    if stripped:
        parsed = _try_loads_dict(stripped)
        if parsed is not None:
            return parsed
    strategy_hit: Optional[int] = None
    result: Optional[dict] = None
    fence = _extract_code_fence(raw)
    if fence:
        result = _try_loads_dict(fence)
        if result is not None:
            strategy_hit = 2
    balanced = None
    if result is None:
        balanced = _extract_balanced_object(raw)
        if balanced:
            result = _try_loads_dict(balanced)
            if result is not None:
                strategy_hit = 3
    if result is None:
        candidate = fence or balanced or stripped
        if candidate:
            result = _try_loads_dict(_repair_common_issues(candidate))
            if result is not None:
                strategy_hit = 4
    if result is not None:
        logger.info(
            "[json_parsing_robust] node=%s degraded parse ok at strategy %s",
            node_name,
            strategy_hit,
        )
        return result
    logger.warning(
        "[json_parsing_robust] node=%s all strategies failed, using fallback",
        node_name,
    )
    if fallback_factory is not None:
        fallback = fallback_factory()
        return fallback if isinstance(fallback, dict) else {}
    return {}
