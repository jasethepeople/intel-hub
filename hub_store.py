"""Persistent store for the hub: pins, fetched-page cache, watchlist."""
import json
import os
import re
import sqlite3
import time
from urllib.parse import urlparse

DB_PATH = os.environ.get("HUB_STORE_DB", "hub_store.db")
FETCH_TTL = int(os.environ.get("HUB_FETCH_TTL", "86400"))  # 24h
MAX_FETCH_BYTES = 500_000


def _conn():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS pins ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, url TEXT,"
        "snippet TEXT, source TEXT, tier TEXT, query TEXT, ts REAL)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS fetch_cache ("
        "url TEXT PRIMARY KEY, ts REAL, status INTEGER, content TEXT)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS watchlist ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT UNIQUE,"
        "interval_sec INTEGER DEFAULT 86400, enabled INTEGER DEFAULT 1,"
        "last_run REAL, last_total INTEGER, last_new INTEGER DEFAULT 0)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS watch_runs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, watch_id INTEGER,"
        "ts REAL, total INTEGER, new_count INTEGER,"
        "new_items TEXT, keys TEXT)"
    )
    return con


# ---------- pins ----------

def add_pin(item: dict, query: str = "") -> int:
    con = _conn()
    cur = con.execute(
        "INSERT INTO pins(title,url,snippet,source,tier,query,ts) VALUES(?,?,?,?,?,?,?)",
        (item.get("title"), item.get("url"), item.get("snippet"),
         item.get("source"), item.get("tier"), query, time.time()),
    )
    con.commit()
    pid = cur.lastrowid
    con.close()
    return pid


def list_pins() -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT id,title,url,snippet,source,tier,query,ts FROM pins ORDER BY ts DESC"
    ).fetchall()
    con.close()
    cols = ["id", "title", "url", "snippet", "source", "tier", "query", "ts"]
    return [dict(zip(cols, r)) for r in rows]


def remove_pin(pin_id: int) -> None:
    con = _conn()
    con.execute("DELETE FROM pins WHERE id = ?", (pin_id,))
    con.commit()
    con.close()


# ---------- fetched-page cache ----------

def get_fetch(url: str) -> dict | None:
    con = _conn()
    row = con.execute(
        "SELECT ts,status,content FROM fetch_cache WHERE url = ?", (url,)
    ).fetchone()
    con.close()
    if row and time.time() - row[0] < FETCH_TTL:
        return {"status": row[1], "content": row[2], "cached": True}
    return None


def put_fetch(url: str, status: int, content: str) -> None:
    con = _conn()
    con.execute(
        "INSERT OR REPLACE INTO fetch_cache VALUES (?, ?, ?, ?)",
        (url, time.time(), status, content),
    )
    con.commit()
    con.close()


async def fetch_url(url: str) -> dict:
    """Fetch full text of a URL, cached for FETCH_TTL. http/https only, size-capped."""
    if urlparse(url).scheme not in ("http", "https"):
        return {"status": 400, "content": "",
                "error": "only http/https URLs are fetchable", "cached": False}
    cached = get_fetch(url)
    if cached:
        return cached
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "intel-hub/1.0"})
            text = r.text[:MAX_FETCH_BYTES] if r.status_code == 200 else ""
            put_fetch(url, r.status_code, text)
            return {"status": r.status_code, "content": text, "cached": False}
    except Exception as e:
        return {"status": 0, "content": "", "error": str(e), "cached": False}


def search_pages(query: str, limit: int = 20) -> list[dict]:
    """Substring search across all cached page contents; returns match context."""
    con = _conn()
    rows = con.execute(
        "SELECT url, content FROM fetch_cache WHERE content LIKE ?",
        (f"%{query}%",),
    ).fetchall()
    con.close()
    out, q = [], query.lower()
    for url, content in rows:
        idx = content.lower().find(q)
        if idx == -1:
            continue
        start = max(0, idx - 120)
        snippet = " ".join(content[start:idx + len(query) + 180].split())
        out.append({
            "url": url,
            "snippet": ("…" if start else "") + snippet + "…",
        })
        if len(out) >= limit:
            break
    return out


# ---------- watchlist / scheduled refresh ----------

def key_of(item: dict) -> str:
    """Stable identity key for diffing a result against a previous run."""
    return re.sub(r"\W+", "", ((item.get("url") or item.get("title") or "").lower()))[:100]


def add_watch(query: str, interval_sec: int = 86400) -> int:
    con = _conn()
    con.execute(
        "INSERT INTO watchlist(query, interval_sec) VALUES (?, ?) "
        "ON CONFLICT(query) DO UPDATE SET interval_sec = excluded.interval_sec",
        (query, interval_sec),
    )
    con.commit()
    wid = con.execute(
        "SELECT id FROM watchlist WHERE query = ?", (query,)
    ).fetchone()[0]
    con.close()
    return wid


def list_watches() -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT id, query, interval_sec, enabled, last_run, last_total, last_new "
        "FROM watchlist ORDER BY id"
    ).fetchall()
    con.close()
    cols = ["id", "query", "interval_sec", "enabled", "last_run", "last_total", "last_new"]
    return [dict(zip(cols, r)) for r in rows]


def get_watch(wid: int) -> dict | None:
    for w in list_watches():
        if w["id"] == wid:
            return w
    return None


def remove_watch(wid: int) -> None:
    con = _conn()
    con.execute("DELETE FROM watchlist WHERE id = ?", (wid,))
    con.execute("DELETE FROM watch_runs WHERE watch_id = ?", (wid,))
    con.commit()
    con.close()


def due_watches(now: float) -> list[dict]:
    return [
        w for w in list_watches()
        if w["enabled"] and (not w["last_run"] or now - w["last_run"] >= w["interval_sec"])
    ]


def latest_keys(wid: int) -> set:
    con = _conn()
    row = con.execute(
        "SELECT keys FROM watch_runs WHERE watch_id = ? ORDER BY ts DESC LIMIT 1",
        (wid,),
    ).fetchone()
    con.close()
    return set(json.loads(row[0])) if row else set()


def latest_new(wid: int) -> list[dict]:
    con = _conn()
    row = con.execute(
        "SELECT new_items FROM watch_runs "
        "WHERE watch_id = ? AND new_count > 0 ORDER BY ts DESC LIMIT 1",
        (wid,),
    ).fetchone()
    con.close()
    return json.loads(row[0]) if row else []


def record_run(wid: int, total: int, new_items: list[dict], keys: list[str]) -> None:
    con = _conn()
    con.execute(
        "INSERT INTO watch_runs(watch_id, ts, total, new_count, new_items, keys) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (wid, time.time(), total, len(new_items),
         json.dumps(new_items), json.dumps(keys)),
    )
    con.execute(
        "UPDATE watchlist SET last_run = ?, last_total = ?, last_new = ? WHERE id = ?",
        (time.time(), total, len(new_items), wid),
    )
    con.commit()
    con.close()
