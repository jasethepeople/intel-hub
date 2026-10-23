"""Unified Intelligence Hub — MCP orchestrator host (v2).

Config convention per server:
  command, args_list  -> how to spawn the server
  env                 -> environment variables (${VARS} expanded)
  tool                -> tool name to call (default "search")
  tool_args           -> argument template; "{query}" is substituted
"""
import asyncio
import json
import os
import re
import sys
import time

import hub_cache
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CONFIG_PATH = os.environ.get("HUB_CONFIG", "mcp_servers.json")
TIERS = ["literature", "code", "vulns"]


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)["mcpServers"]
    for spec in cfg.values():
        if "env" in spec:
            spec["env"] = {k: os.path.expandvars(v) for k, v in spec["env"].items()}
    return cfg


async def query_server(name: str, spec: dict, query: str) -> dict:
    params = StdioServerParameters(
        command=spec["command"],
        args=spec.get("args_list", spec.get("args", [])),
        env={**os.environ, **spec.get("env", {})},
    )
    tool = spec.get("tool", "search")
    template = spec.get("tool_args", {"query": "{query}"})
    args = {
        k: (v.replace("{query}", query) if isinstance(v, str) else v)
        for k, v in template.items()
    }
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
                text = "".join(
                    c.text for c in result.content if getattr(c, "text", None)
                )
                return {"server": name, "tier": spec.get("tier", name), "raw": text}
    except Exception as e:
        return {"server": name, "tier": spec.get("tier", name), "error": str(e)}


def parse_results(server: str, payload: dict) -> list[dict]:
    if "error" in payload:
        return [{
            "tier": payload["tier"], "source": server,
            "title": f"[error] {payload['error']}", "url": "", "snippet": "",
        }]
    try:
        data = json.loads(payload["raw"])
    except json.JSONDecodeError:
        return [{
            "tier": payload["tier"], "source": server,
            "title": payload["raw"][:200], "url": "", "snippet": "",
        }]

    if isinstance(data, dict) and isinstance(data.get("results"), list):
        for r in data["results"]:
            r.setdefault("tier", payload["tier"])
            r.setdefault("source", server)
        return data["results"]

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [
            {
                "tier": "code", "source": "github",
                "title": item.get("full_name"),
                "url": item.get("html_url"),
                "snippet": item.get("description") or "",
                "stars": item.get("stargazers_count"),
                "updated": item.get("updated_at"),
            }
            for item in data["items"]
        ]
    return []


def dedupe(results: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in results:
        key = re.sub(r"\W+", "", (r.get("title") or "").lower())[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


async def broadcast(query: str, use_cache: bool = True) -> dict:
    if use_cache:
        cached = hub_cache.get(query)
        if cached:
            cached["cached"] = True
            return cached

    servers = load_config()
    payloads = await asyncio.gather(
        *(query_server(name, spec, query) for name, spec in servers.items())
    )
    all_results = dedupe(
        [r for p in payloads for r in parse_results(p["server"], p)]
    )
    report = {
        "query": query,
        "total": len(all_results),
        "tiers": {t: [r for r in all_results if r.get("tier") == t] for t in TIERS},
        "cached": False,
    }
    hub_cache.put(query, report)
    return report


def render_cli(report: dict) -> None:
    flag = " [cached]" if report.get("cached") else ""
    print(f"\n=== {report['query']}  ({report['total']} results){flag} ===")
    for tier in TIERS:
        print(f"\n--- {tier.upper()} ({len(report['tiers'][tier])}) ---")
        for r in report["tiers"][tier]:
            print(f"  [{r.get('source')}] {r.get('title')}\n"
                  f"      {r.get('url')}\n"
                  f"      {(r.get('snippet') or '')[:160]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('usage: python orchestrator.py "search query" [--no-cache]')
    no_cache = "--no-cache" in sys.argv
    q = " ".join(a for a in sys.argv[1:] if not a.startswith("--"))
    render_cli(asyncio.run(broadcast(q, use_cache=not no_cache)))


# ---------- health probing ----------

async def _init_and_list(params):
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.list_tools()


async def check_server_health(name: str, spec: dict) -> dict:
    if not spec.get("health_check", True):
        return {"ok": None, "skipped": True}
    params = StdioServerParameters(
        command=spec["command"],
        args=spec.get("args_list", spec.get("args", [])),
        env={**os.environ, **spec.get("env", {})},
    )
    t0 = time.monotonic()
    try:
        tools = await asyncio.wait_for(_init_and_list(params), timeout=8)
        return {
            "ok": True,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "tools": len(tools.tools),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


async def check_health() -> dict:
    servers = load_config()
    results = await asyncio.gather(
        *(check_server_health(n, s) for n, s in servers.items())
    )
    return dict(zip(servers, results))
