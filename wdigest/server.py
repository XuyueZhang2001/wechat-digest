"""本地网页界面：管理信源、定义话题、运行分析。

只用标准库。默认只绑定 127.0.0.1，不对局域网开放。
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import markdown
from .config import Event, Source, load_event, load_sources
from .dataxapi import DataXAPI
from .llm import LLM
from .pipeline import analyze, ingest, write_report
from .store import Store
from .suggest import suggest_keywords
from .tomlwrite import dump_event, dump_sources

ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = ROOT / "sources.toml"
EVENTS_DIR = ROOT / "events"
DB_PATH = ROOT / "data" / "wdigest.db"
REPORTS_DIR = ROOT / "reports"
WEB_INDEX = ROOT / "web" / "index.html"

JOBS: dict[str, "Job"] = {}
JOBS_LOCK = threading.Lock()


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"
    log: list[str] = field(default_factory=list)
    report_html: str = ""
    report_md: str = ""
    report_file: str = ""
    error: str = ""
    spent: float = 0.0
    created: float = field(default_factory=time.time)

    def line(self, text) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {text}")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "log": self.log,
            "report_html": self.report_html,
            "report_file": self.report_file,
            "error": self.error,
            "spent": self.spent,
        }


def _load_sources() -> list[Source]:
    return load_sources(SOURCES_PATH) if SOURCES_PATH.exists() else []


def _events() -> list[dict]:
    items = []
    for path in sorted(EVENTS_DIR.glob("*.toml")):
        if path.name.startswith("_"):
            continue
        try:
            event = load_event(path)
        except Exception:  # noqa: BLE001 - 坏文件不应拖垮界面
            continue
        items.append(
            {
                "file": path.name,
                "name": event.name,
                "description": event.description,
                "window_days": event.window_days,
                "sets": event.sets(),
            }
        )
    return items


def _state() -> dict:
    sources = _load_sources()
    stats = Store(DB_PATH).stats()
    by_name = {row["source_name"]: row for row in stats["by_source"]}
    payload = []
    for source in sources:
        row = by_name.get(source.name, {})
        payload.append(
            {
                "id": source.id,
                "name": source.name,
                "kind": source.kind,
                "feed": source.feed,
                "account": source.account,
                "weight": source.weight,
                "angle": source.angle,
                "enabled": source.enabled,
                "configured": bool(
                    (source.kind == "rss" and source.feed)
                    or (source.kind == "dataxapi" and source.account)
                ),
                "count": row.get("n", 0),
                "latest": (row.get("latest") or "")[:10],
            }
        )
    with JOBS_LOCK:
        jobs = [
            {"id": job.id, "kind": job.kind, "status": job.status}
            for job in sorted(JOBS.values(), key=lambda j: j.created, reverse=True)[:10]
        ]
    return {"sources": payload, "events": _events(), "jobs": jobs}


def _parse_groups(text: str) -> list[str]:
    return [term.strip() for term in text.split(",") if len(term.strip()) >= 2]


def _parse_sets(text: str) -> list[list[list[str]]]:
    sets: list[list[list[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        groups = [_parse_groups(part) for part in line.split("|")]
        groups = [group for group in groups if group]
        if groups:
            sets.append(groups)
    return sets


def _run_job(job: Job, body: dict) -> None:
    try:
        store = Store(DB_PATH)
        sources = _load_sources()
        event = load_event(EVENTS_DIR / str(body["file"]))
        llm = LLM()
        if body.get("no_llm"):
            llm.api_key = ""
            job.line("仅检索模式：不调用模型、不补全文")
        client = DataXAPI()
        bundle = analyze(
            store,
            event,
            llm,
            top_n=int(body.get("top", 40)),
            api_client=client,
            enrich_top=int(body.get("enrich_top", 6)),
            min_score=float(body.get("min_score", 0.6) or 0.6),
            max_cost=float(body.get("max_cost", 0) or 0),
            log=job.line,
        )
        path = write_report(bundle, sources, out_dir=str(REPORTS_DIR))
        job.report_md = path.read_text(encoding="utf-8")
        job.report_html = markdown.render(job.report_md)
        job.report_file = path.name
        job.spent = round(client.spent, 4)
        job.status = "done"
        job.line(f"完成：{path.name}")
    except Exception as exc:  # noqa: BLE001 - 错误要回显到界面
        job.status = "error"
        job.error = str(exc)
        job.line(f"失败：{exc}")


def _ingest_job(job: Job, body: dict) -> None:
    try:
        store = Store(DB_PATH)
        sources = _load_sources()
        client = DataXAPI()
        summary = ingest(
            sources,
            store,
            api_client=client,
            api_pages=int(body.get("pages", 1)),
            log=job.line,
        )
        job.spent = round(client.spent, 4)
        job.line(json.dumps(summary, ensure_ascii=False))
        job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.error = str(exc)
        job.line(f"失败：{exc}")


def _start(kind: str, target, body: dict) -> Job:
    job = Job(id=uuid.uuid4().hex[:10], kind=kind)
    with JOBS_LOCK:
        JOBS[job.id] = job
    threading.Thread(target=target, args=(job, body), daemon=True).start()
    return job


class Handler(BaseHTTPRequestHandler):
    server_version = "wechat-digest/0.2"

    # ---------- helpers ----------

    def _json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def log_message(self, *args) -> None:  # 静默访问日志
        pass

    # ---------- routing ----------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            if not WEB_INDEX.exists():
                self._text("web/index.html 不存在", 500)
                return
            self._text(WEB_INDEX.read_text(encoding="utf-8"), 200, "text/html; charset=utf-8")
            return
        if path == "/api/state":
            self._json(_state())
            return
        if path.startswith("/api/jobs/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            if not job:
                self._json({"error": "not found"}, 404)
                return
            self._json(job.as_dict())
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._body()

        if path == "/api/sources":
            sources = _load_sources()
            sid = re.sub(r"[^a-zA-Z0-9_-]", "", str(body.get("id") or ""))
            if not sid:
                sid = f"src{len(sources) + 1}"
            existing = next((s for s in sources if s.id == sid), None)
            if existing:
                existing.name = str(body.get("name") or existing.name)
                existing.kind = str(body.get("kind") or existing.kind)
                existing.feed = str(body.get("feed") or "")
                existing.account = str(body.get("account") or "")
                existing.weight = float(body.get("weight") or 1.0)
                existing.angle = str(body.get("angle") or "")
                existing.enabled = bool(body.get("enabled", True))
            else:
                sources.append(
                    Source(
                        id=sid,
                        name=str(body.get("name") or sid),
                        kind=str(body.get("kind") or "rss"),
                        feed=str(body.get("feed") or ""),
                        account=str(body.get("account") or ""),
                        weight=float(body.get("weight") or 1.0),
                        angle=str(body.get("angle") or ""),
                        enabled=bool(body.get("enabled", True)),
                    )
                )
            dump_sources(sources, SOURCES_PATH)
            self._json({"ok": True, "id": sid})
            return

        if path == "/api/sources/toggle":
            sources = _load_sources()
            target = next((s for s in sources if s.id == body.get("id")), None)
            if not target:
                self._json({"error": "not found"}, 404)
                return
            target.enabled = not target.enabled
            dump_sources(sources, SOURCES_PATH)
            self._json({"ok": True, "enabled": target.enabled})
            return

        if path == "/api/events":
            raw_sets = body.get("sets")
            if isinstance(raw_sets, str):
                # 表单提交的是文本，必须按行/组解析，不能当数组遍历。
                sets = _parse_sets(raw_sets)
            elif isinstance(raw_sets, list):
                sets = raw_sets
            else:
                sets = []

            if not sets:
                subject = _parse_groups(str(body.get("subject") or ""))
                angle = _parse_groups(str(body.get("angle") or ""))
                if subject or angle:
                    sets = [[subject, angle]] if subject and angle else [[subject or angle]]

            normalized: list[list[list[str]]] = []
            for group_set in sets:
                if not isinstance(group_set, list):
                    continue
                groups: list[list[str]] = []
                for group in group_set:
                    if isinstance(group, str):
                        group = [group]
                    if not isinstance(group, list):
                        continue
                    terms = [str(term).strip() for term in group if len(str(term).strip()) >= 2]
                    if terms:
                        groups.append(terms)
                if groups:
                    normalized.append(groups)
            sets = normalized

            flat = [term for group_set in sets for group in group_set for term in group]
            if not sets or all(len(term) <= 1 for term in flat):
                self._json(
                    {"error": "关键词太短。每个词至少两个字，格式是「主体词, 别名 | 角度词」"},
                    400,
                )
                return
            if len(flat) > 60:
                self._json({"error": "关键词太多，建议每套 2-3 组、每组不超过 10 个词"}, 400)
                return

            file_name = str(body.get("file") or "").strip()
            if not file_name:
                file_name = f"ui-{int(time.time())}.toml"
            if not file_name.endswith(".toml"):
                file_name += ".toml"
            event = Event(
                name=str(body.get("name") or "未命名话题"),
                description=str(body.get("description") or ""),
                window_days=int(body.get("window_days") or 90),
                keyword_sets=sets,
            )
            dump_event(event, EVENTS_DIR / file_name)
            self._json({"ok": True, "file": file_name})
            return

        if path == "/api/suggest":
            name = str(body.get("name") or "").strip()
            if not name:
                self._json({"error": "先填话题名称"}, 400)
                return
            llm = LLM()
            if not llm.enabled:
                self._json({"error": "未配置模型 Key（WDIGEST_API_KEY）"}, 400)
                return
            try:
                result = suggest_keywords(llm, name, str(body.get("description") or ""))
            except Exception as exc:  # noqa: BLE001 - 回显给界面
                self._json({"error": str(exc)}, 500)
                return
            self._json(
                {
                    "ok": True,
                    "sets": result["sets"],
                    "subject": result["subject"],
                    "angle": result["angle"],
                }
            )
            return

        if path == "/api/run":
            if not body.get("file"):
                self._json({"error": "缺少话题文件"}, 400)
                return
            job = _start("run", _run_job, body)
            self._json({"ok": True, "job": job.id})
            return

        if path == "/api/ingest":
            job = _start("ingest", _ingest_job, body)
            self._json({"ok": True, "job": job.id})
            return

        self._json({"error": "not found"}, 404)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/sources":
            sid = (query.get("id") or [""])[0]
            sources = [s for s in _load_sources() if s.id != sid]
            dump_sources(sources, SOURCES_PATH)
            self._json({"ok": True})
            return
        if parsed.path == "/api/events":
            name = (query.get("file") or [""])[0]
            if name and "/" not in name and "\\" not in name:
                target = EVENTS_DIR / name
                if target.exists():
                    target.unlink()
            self._json({"ok": True})
            return
        self._json({"error": "not found"}, 404)


def serve(port: int = 8765, host: str = "127.0.0.1") -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"界面已启动：http://{host}:{port}")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
