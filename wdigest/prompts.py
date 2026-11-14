"""加载 prompts/ 下的模板，便于不碰代码就调提示词。"""

from __future__ import annotations

from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"缺少提示词文件：{path}")
    return path.read_text(encoding="utf-8")


def render(name: str, values: dict[str, str]) -> str:
    text = load(name)
    for key, value in values.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text
