"""Public provider adapter; no private relay or silent fallback.
公开服务适配器；不包含生产中转服务或静默模型回退。
"""

import os
from langchain_core.messages import AIMessage
from openai import OpenAI

PROVIDERS = {
    "reply": ("REPLY", ""),
    "safety": ("SAFETY", ""),
    "memory": ("MEMORY", ""),
    "openrouter": ("OPENROUTER", "https://openrouter.ai/api/v1"),
    "deepseek": ("DEEPSEEK", "https://api.deepseek.com"),
    "ark": ("ARK", "https://ark.cn-beijing.volces.com/api/v3"),
}


def call_llm(
    *,
    messages,
    model,
    provider,
    temperature,
    max_completion_tokens,
    timeout_seconds=20,
    response_format=None,
):
    prefix, default_url = PROVIDERS[provider]
    key = os.environ.get(f"{prefix}_API_KEY", "").strip()
    base_url = os.environ.get(f"{prefix}_BASE_URL") or default_url
    if not key or not base_url or not model:
        raise RuntimeError(f"Set {prefix}_API_KEY / 请配置模型凭证")
    payload = {}
    if provider == "openrouter":
        payload["reasoning"] = {"effort": "none", "exclude": True}
    elif provider in {"deepseek", "ark"}:
        payload["thinking"] = {"type": "disabled"}
    role = {"human": "user", "ai": "assistant", "system": "system"}
    try:
        with OpenAI(
            api_key=key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        ) as client:
            result = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": role[m.type], "content": m.content} for m in messages
                ],
                temperature=temperature,
                max_tokens=max_completion_tokens,
                response_format=response_format,
                extra_body=payload,
            )
        choice = result.choices[0]
        return AIMessage(
            content=choice.message.content or "",
            response_metadata={"finish_reason": choice.finish_reason},
        )
    except Exception:
        # Do not propagate provider error bodies, URLs, or user content into logs.
        # 不把上游错误正文、URL 或用户内容写入日志。
        raise RuntimeError("Model request failed / 模型请求失败") from None


def extract_text(message) -> str:
    return str(message.content or "").strip()
