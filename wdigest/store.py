"""SQLite 存储：文章入库、精确去重、SimHash 近重复检测。"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    feed      TEXT,
    weight    REAL DEFAULT 1.0,
    angle     TEXT,
    enabled   INTEGER DEFAULT 1,
    account_id TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    id           TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL,
    source_name  TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    author       TEXT,
    published_at TEXT NOT NULL,
    body         TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    simhash      TEXT,
    dup_of       TEXT,
    fetched_at   TEXT NOT NULL,
    fulltext     INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_id);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    report_path TEXT,
    stats_json  TEXT
);
"""


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "")).lower()


def content_hash(text: str) -> str:
    return hashlib.sha1(_norm(text).encode("utf-8")).hexdigest()


def simhash(text: str, bits: int = 64) -> int:
    """字符 3-gram 的 SimHash，对转载、改标题、加导语比较稳。"""
    cleaned = _norm(text)[:8000]
    if not cleaned:
        return 0
    vector = [0] * bits
    for i in range(len(cleaned) - 2):
        gram = cleaned[i : i + 3]
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(bits):
            vector[bit] += 1 if (value >> bit) & 1 else -1
    result = 0
    for bit in range(bits):
        if vector[bit] > 0:
            result |= 1 << bit
    return result


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """给旧库补列，避免升级时丢数据。"""
        article_cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(articles)")}
        if "fulltext" not in article_cols:
            self.conn.execute("ALTER TABLE articles ADD COLUMN fulltext INTEGER DEFAULT 1")
        source_cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(sources)")}
        if "account_id" not in source_cols:
            self.conn.execute("ALTER TABLE sources ADD COLUMN account_id TEXT")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- sources ----------

    def upsert_source(self, sid: str, name: str, feed: str = "", weight: float = 1.0,
                      angle: str = "", enabled: bool = True) -> None:
        self.conn.execute(
            """INSERT INTO sources (id, name, feed, weight, angle, enabled)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, feed=excluded.feed, weight=excluded.weight,
                 angle=excluded.angle, enabled=excluded.enabled""",
            (sid, name, feed, weight, angle, int(enabled)),
        )
        self.conn.commit()

    def source_weights(self) -> dict[str, float]:
        rows = self.conn.execute("SELECT id, weight FROM sources").fetchall()
        return {row["id"]: float(row["weight"] or 1.0) for row in rows}

    def get_account_id(self, source_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT account_id FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        return row["account_id"] if row else None

    def set_account_id(self, source_id: str, account_id: str) -> None:
        self.conn.execute(
            "UPDATE sources SET account_id = ? WHERE id = ?", (account_id, source_id)
        )
        self.conn.commit()

    # ---------- articles ----------

    def add_article(self, *, source_id: str, source_name: str, title: str, url: str,
                    author: str, published_at: str, body: str,
                    fulltext: bool = True) -> str:
        """返回 inserted / duplicate / near_duplicate。

        fulltext=False 时允许 body 为空或只是摘要，后续用付费接口补全文。
        """
        body = (body or "").strip()
        if not body and fulltext:
            return "empty"

        # 同源同标题直接判重：付费接口的 URL 带易变的 sessionid，
        # 补全文后正文哈希也会变，只靠 URL/哈希会漏。
        same_title = self.conn.execute(
            "SELECT id FROM articles WHERE source_id = ? AND title = ?",
            (source_id, title),
        ).fetchone()
        if same_title:
            return "duplicate"

        digest = content_hash(f"{title}\n{body}")
        existing = self.conn.execute(
            "SELECT id FROM articles WHERE content_hash = ?", (digest,)
        ).fetchone()
        if existing:
            return "duplicate"

        article_id = hashlib.sha1(
            f"{source_id}|{url}|{title}".encode("utf-8")
        ).hexdigest()[:16]
        exists = self.conn.execute(
            "SELECT id FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        if exists:
            return "duplicate"

        fingerprint = simhash(f"{title}\n{body}")
        dup_of = None
        if fulltext and body:
            recent = self.conn.execute(
                """SELECT id, simhash FROM articles
                   WHERE simhash IS NOT NULL AND fulltext = 1
                   ORDER BY fetched_at DESC LIMIT 500"""
            ).fetchall()
            for row in recent:
                try:
                    other = int(row["simhash"])
                except (TypeError, ValueError):
                    continue
                if hamming(fingerprint, other) <= 3:
                    dup_of = row["id"]
                    break

        now = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")
        self.conn.execute(
            """INSERT INTO articles
               (id, source_id, source_name, title, url, author, published_at, body,
                content_hash, simhash, dup_of, fetched_at, fulltext)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (article_id, source_id, source_name, title, url, author,
             published_at or now, body, digest, str(fingerprint), dup_of, now,
             int(fulltext)),
        )
        self.conn.commit()
        return "inserted"

    def update_content(self, article_id: str, body: str, title: str | None = None,
                       published_at: str | None = None, author: str | None = None) -> bool:
        """把摘要桩补成全文。"""
        body = (body or "").strip()
        if not body:
            return False
        row = self.conn.execute(
            "SELECT title FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        if not row:
            return False
        final_title = title or row["title"]
        self.conn.execute(
            """UPDATE articles SET body = ?, title = ?,
                   published_at = COALESCE(?, published_at),
                   author = COALESCE(?, author),
                   content_hash = ?, simhash = ?, fulltext = 1
               WHERE id = ?""",
            (
                body,
                final_title,
                published_at,
                author,
                content_hash(f"{final_title}\n{body}"),
                str(simhash(f"{final_title}\n{body}")),
                article_id,
            ),
        )
        self.conn.commit()
        return True

    def cleanup_duplicates(self) -> int:
        """同一信源下标题相同的文章只保留一份，优先保留全文版。"""
        cursor = self.conn.execute(
            """DELETE FROM articles
               WHERE rowid NOT IN (
                   SELECT rowid FROM (
                       SELECT rowid,
                              ROW_NUMBER() OVER (
                                  PARTITION BY source_id, title
                                  ORDER BY fulltext DESC, fetched_at DESC
                              ) AS rn
                       FROM articles
                   )
                   WHERE rn = 1
               )"""
        )
        self.conn.commit()
        return cursor.rowcount

    def iter_articles(self, since: str, until: str):
        cur = self.conn.execute(
            """SELECT * FROM articles
               WHERE published_at >= ? AND published_at <= ?
               ORDER BY published_at DESC""",
            (since, until),
        )
        for row in cur:
            yield row

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        dup = self.conn.execute(
            "SELECT COUNT(*) FROM articles WHERE dup_of IS NOT NULL"
        ).fetchone()[0]
        by_source = self.conn.execute(
            """SELECT source_name, COUNT(*) AS n, MAX(published_at) AS latest
               FROM articles GROUP BY source_name ORDER BY n DESC"""
        ).fetchall()
        return {
            "total": total,
            "near_duplicate": dup,
            "by_source": [dict(r) for r in by_source],
        }

    def record_run(self, event: str, report_path: str, stats_json: str) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")
        self.conn.execute(
            "INSERT INTO runs (event, created_at, report_path, stats_json) VALUES (?, ?, ?, ?)",
            (event, now, report_path, stats_json),
        )
        self.conn.commit()
