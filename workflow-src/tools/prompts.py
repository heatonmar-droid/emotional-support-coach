"""Load one prompt language at a time. / 每次只加载一种语言的提示词。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(name: str, language: str) -> str:
    return (ROOT / f"{name}.{language}.txt").read_text(encoding="utf-8")
