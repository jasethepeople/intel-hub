"""Result cache for the hub. SQLite, TTL-based, keyed by query string."""
import json
import os
import sqlite3
import time

DB_PATH = os.environ.get("HUB_CACHE_DB", "hub_cache.db")
TTL = int(os.environ.get("HUB_CACHE_TTL", "900"))  # 15 min


def _conn():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS cache "
        "(query TEXT PRIMARY KEY, ts REAL, payload TEXT)"
    )
    return con


def get(query):
    con = _conn()
    row = con.execute("SELECT ts, payload FROM cache WHERE query = ?", (query,)).fetchone()
    con.close()
    if row and time.time() - row[0] < TTL:
        return json.loads(row[1])
    return None


def put(query, payload):
    con = _conn()
    con.execute(
        "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
        (query, time.time(), json.dumps(payload)),
    )
    con.commit()
    con.close()


def purge():
    con = _conn()
    con.execute("DELETE FROM cache WHERE ts < ?", (time.time() - TTL,))
    con.commit()
    con.close()
