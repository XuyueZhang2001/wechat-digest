"""最小 LLM 客户端：兼容 OpenAI /v1/chat/completions 的服务都能用。

只依赖标准库，避免为了一次 HTTP 请求引入 SDK。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class LLM:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, timeout: int = 180) -> None:
        self.api_key = (
            api_key
            or os.environ.get("WDIGEST_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        self.base_url = (
            base_url
            or os.environ.get("WDIGEST_BASE_URL")
            or "https://api.deepseek.com/v1"
        ).rstrip("/")
        self.model = model or os.environ.get("WDIGEST_MODEL") or "deepseek-chat"
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def chat(self, system: str, user: str, temperature: float = 0.2,
             max_tokens: int = 3000) -> str:
        if not self.enabled:
            raise LLMError("未配置 API key（设置 WDIGEST_API_KEY 或 DEEPSEEK_API_KEY）")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                obj = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise LLMError(f"HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001 - 网络错误统一转成 LLMError
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc

        try:
            return obj["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("响应结构异常") from exc

    def json(self, system: str, user: str, max_tokens: int = 3000) -> dict:
        text = self.chat(system, user, max_tokens=max_tokens)
        data = _extract_json(text)
        if data is None:
            retry = user + "\n\n再次强调：只输出一个合法的 JSON 对象，不要任何解释、不要代码块标记。"
            text = self.chat(system, retry, max_tokens=max_tokens)
            data = _extract_json(text)
        if data is None:
            raise LLMError("模型未返回可解析的 JSON")
        return data
