"""Code tier: ripgrep wrapper over the CODE_ROOT directory tree."""
import json
import os
import shutil
import subprocess

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("localcode")
ROOT = os.path.abspath(os.environ.get("CODE_ROOT", os.path.expanduser("~/code")))


@mcp.tool()
def repos() -> str:
    """List top-level projects under the code root."""
    if not os.path.isdir(ROOT):
        return json.dumps({"results": [{"tier": "code", "source": "localcode",
            "title": f"[error] CODE_ROOT not found: {ROOT}", "url": "", "snippet": ""}]})
    dirs = sorted(d for d in os.listdir(ROOT)
                  if os.path.isdir(os.path.join(ROOT, d)) and not d.startswith("."))
    return json.dumps({"results": [
        {"tier": "code", "source": "localcode", "title": d,
         "url": "file://" + os.path.join(ROOT, d), "snippet": ""}
        for d in dirs
    ]})


@mcp.tool()
def search(query: str, limit: int = 20) -> str:
    """Literal, case-insensitive code search across all local repos."""
    if not shutil.which("rg"):
        return json.dumps({"results": [{"tier": "code", "source": "localcode",
            "title": "[error] ripgrep (rg) not installed", "url": "", "snippet": ""}]})
    proc = subprocess.run(
        ["rg", "--json", "-i", "-m", str(limit), "--max-columns", "300",
         "--glob", "!node_modules", "--glob", "!target", "--glob", "!.git",
         query, ROOT],
        capture_output=True, text=True, timeout=30,
    )
    results = []
    for line in proc.stdout.splitlines():
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("type") != "match":
            continue
        d = evt["data"]
        path = d["path"]["text"]
        results.append({
            "tier": "code", "source": "localcode",
            "title": f"{os.path.relpath(path, ROOT)}:{d['line_number']}",
            "url": "file://" + path,
            "snippet": d["lines"]["text"].strip()[:300],
        })
        if len(results) >= limit:
            break
    return json.dumps({"results": results})


if __name__ == "__main__":
    mcp.run()
