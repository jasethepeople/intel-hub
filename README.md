# Unified Intelligence Hub

A local, modular dashboard + orchestrator that uses the Model Context Protocol
to query four data tiers simultaneously from one search box:

| Tier | Sources |
|---|---|
| literature | Open Library, arXiv, Internet Archive, Google Books |
| code | GitHub (official MCP server), local repos (ripgrep) |
| vulns | NVD CVE keyword search, local ExploitDB (searchsploit) |
| hub | orchestrator, SQLite caches, pins, watchlist, page fetch |

## Quick start

```bash
# Python 3.10+, uv, ripgrep recommended
export GITHUB_TOKEN=ghp_...          # optional, GitHub tier
export NVD_API_KEY=...               # optional, better NVD rate limits
# edit CODE_ROOT in mcp_servers.json

python -m venv .venv && source .venv/bin/activate
pip install "mcp[cli]" httpx fastapi uvicorn

# headless check
python orchestrator.py "log4shell"

# dashboard
python hub.py    # open http://127.0.0.1:8471
```

## Files

- `mcp_servers.json` — server registry (spawn args, env, tool templates)
- `orchestrator.py` — parallel MCP client host; `broadcast()`, `check_health()`; CLI
- `hub.py` — FastAPI dashboard + scheduler + REST API
- `hub_cache.py` — 15-min query cache (`hub_cache.db`)
- `hub_store.py` — pins, fetched-page cache, watchlist (`hub_store.db`)
- `mcp_hub_server.py` — re-export the whole hub as an MCP server for other clients
- `servers/` — the three custom MCP server tiers

## API

- `GET /api/search?q=` — broadcast search (tiers grouped, deduped)
- `POST /api/pin` / `GET /api/pins` / `DELETE /api/pin/{id}` / `GET /api/pins/export?format=md|json`
- `POST /api/fetch` `{url}` — fetch+cache full page text
- `GET /api/pages/search?q=` — full-text search over cached pages
- `GET /api/health` — per-server MCP health + tool count
- `GET|POST|DELETE /api/watch...` — scheduled queries with new-item diffing

## Running as a service

See `intel-hub.service` in the repo (user systemd unit). Watches only fire
while `hub.py` is running.

## Security notes

- Binds 127.0.0.1 only. Do not expose without adding auth.
- `/api/fetch` is http/https only, 500 KB text cap, 20 s timeout — but it can
  reach internal hosts. Restrict it if you ever proxy outward.
- The hub's own MCP server must NOT be registered in its own mcp_servers.json
  (infinite recursion).
