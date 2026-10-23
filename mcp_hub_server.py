"""Intel Hub exposed as an MCP server over stdio.

Add to any MCP client config (NOT to this project's own mcp_servers.json —
that would recurse):
    "intel-hub": {
      "command": "uv",
      "args": ["run", "--with", "mcp[cli],httpx", "python", "/abs/path/to/mcp_hub_server.py"]
    }
"""
import json

from mcp.server.fastmcp import FastMCP

import hub_store
from orchestrator import broadcast

mcp = FastMCP("intel-hub")


@mcp.tool()
async def search(query: str, no_cache: bool = False) -> str:
    """Broadcast a query across all tiers; returns merged, deduped, grouped results."""
    report = await broadcast(query, use_cache=not no_cache)
    return json.dumps(report)


@mcp.tool()
async def fetch_page(url: str) -> str:
    """Fetch and cache the full text of a result URL."""
    return json.dumps(await hub_store.fetch_url(url))


@mcp.tool()
def pin_result(title: str, url: str, snippet: str = "", source: str = "",
               tier: str = "", query: str = "") -> str:
    """Pin a result for later review."""
    item = {"title": title, "url": url, "snippet": snippet,
            "source": source, "tier": tier}
    return json.dumps({"id": hub_store.add_pin(item, query)})


@mcp.tool()
def pinned() -> str:
    """List all pinned results, newest first."""
    return json.dumps({"results": hub_store.list_pins()})


@mcp.tool()
def unpin(pin_id: int) -> str:
    """Remove a pinned result by id."""
    hub_store.remove_pin(pin_id)
    return json.dumps({"removed": pin_id})


if __name__ == "__main__":
    mcp.run()
