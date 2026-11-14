"""DataXAPI 客户端：只封装用到的三个接口，标准库实现。

接口文档：
- 列表  GET /v1/wechat_mp/accounts/articles/list
- 详情  GET /v1/wechat_mp/articles/get
- 搜号  GET /v1/wechat/accounts/search
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class DataXAPIError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 0,
                 charged: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
        self.charged = charged


class DataXAPI:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 timeout: int = 60) -> None:
        self.api_key = api_key or os.environ.get("DATAXAPI_API_KEY", "")
        self.base_url = (
            base_url
            or os.environ.get("DATAXAPI_BASE_URL")
            or "https://api.dataxapi.com/v1"
        ).rstrip("/")
        self.timeout = timeout
        self.spent = 0.0
        self.calls = 0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, params: dict) -> dict:
        if not self.enabled:
            raise DataXAPIError("unauthorized", "未配置 DATAXAPI_API_KEY")
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                obj = {}
            raise DataXAPIError(
                obj.get("code", "http_error"),
                obj.get("message", raw[:300]),
                exc.code,
                bool(obj.get("charged")),
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 统一转成可读错误
            raise DataXAPIError("network_error", f"{type(exc).__name__}: {exc}") from exc

        self.calls += 1
        billing = (payload.get("meta") or {}).get("billing") or {}
        try:
            self.spent += float(billing.get("amount") or 0)
        except (TypeError, ValueError):
            pass
        return payload

    def search_account(self, query: str) -> list[dict]:
        payload = self._get("/wechat/accounts/search", {"query": query})
        return (payload.get("data") or {}).get("items") or []

    def list_articles(self, account_id: str, pages: int = 1) -> list[dict]:
        items: list[dict] = []
        cursor = None
        for _ in range(max(1, pages)):
            params: dict[str, str] = {"id": account_id}
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/wechat_mp/accounts/articles/list", params)
            items.extend((payload.get("data") or {}).get("items") or [])
            page = payload.get("page") or {}
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")
            if not cursor:
                break
        return items

    def get_article(self, url: str) -> dict:
        payload = self._get("/wechat_mp/articles/get", {"url": url})
        return (payload.get("data") or {}).get("item") or {}
