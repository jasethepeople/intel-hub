"""Vulns tier: NVD CVE keyword search + local ExploitDB (searchsploit)."""
import json
import os
import shutil
import subprocess

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vulns")


def _severity(cve: dict) -> str:
    for key in ("cvssMetricV31", "cvssMetricV40", "cvssMetricV2"):
        metrics = cve.get("metrics", {}).get(key) or []
        if metrics:
            sev = metrics[0].get("cvssData", {}).get("baseSeverity")
            if sev:
                return sev
            if key == "cvssMetricV2":
                return metrics[0].get("baseSeverity", "")
    return ""


@mcp.tool()
async def search(query: str, limit: int = 10) -> str:
    """Search CVEs via NVD and local ExploitDB via searchsploit (if installed)."""
    results = []

    headers = {}
    if os.environ.get("NVD_API_KEY"):
        headers["apiKey"] = os.environ["NVD_API_KEY"]

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://services.nvd.nist.gov/rest/json/cves/2.0",
            params={"keywordSearch": query, "resultsPerPage": min(limit, 20)},
            headers=headers,
        )
        for item in r.json().get("vulnerabilities", []):
            cve = item["cve"]
            desc = next((d["value"] for d in cve.get("descriptions", []) if d["lang"] == "en"), "")
            results.append({
                "tier": "vulns", "source": "nvd", "id": cve["id"],
                "title": f"{cve['id']}: {desc[:120]}",
                "url": f"https://nvd.nist.gov/vuln/detail/{cve['id']}",
                "snippet": desc[:400], "date": cve.get("published"),
                "severity": _severity(cve),
            })

    if shutil.which("searchsploit"):
        proc = subprocess.run(
            ["searchsploit", "--json", query],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(proc.stdout)
            for item in data.get("RESULTS_EXPLOIT", [])[:limit]:
                results.append({
                    "tier": "vulns", "source": "exploitdb",
                    "title": f"[{item.get('EDB-ID')}] {item.get('Title')}",
                    "url": "https://www.exploit-db.com/exploits/" + str(item.get("EDB-ID", "")),
                    "snippet": item.get("Path", ""),
                })
        except json.JSONDecodeError:
            pass

    return json.dumps({"results": results})


if __name__ == "__main__":
    mcp.run()
