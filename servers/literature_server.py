"""Literature tier: Open Library + arXiv + Internet Archive + Google Books."""
import asyncio
import json
import xml.etree.ElementTree as ET

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("literature")
ATOM = {"a": "http://www.w3.org/2005/Atom"}


@mcp.tool()
async def search(query: str, limit: int = 10) -> str:
    """Search books and papers across Open Library, arXiv, Internet Archive,
    and Google Books."""
    n = min(limit, 10)
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
        ol, ax, ia, gb = await asyncio.gather(
            c.get("https://openlibrary.org/search.json",
                  params={"q": query, "limit": n}),
            c.get("https://export.arxiv.org/api/query",
                  params={"search_query": f"all:{query}", "max_results": n}),
            c.get("https://archive.org/advancedsearch.php",
                  params={"q": query,
                          "fl[]": ["identifier", "title", "creator", "year"],
                          "rows": n, "output": "json"}),
            c.get("https://www.googleapis.com/books/v1/volumes",
                  params={"q": query, "maxResults": n}),
        )

    results = []

    for doc in ol.json().get("docs", [])[:n]:
        results.append({
            "tier": "literature", "source": "openlibrary",
            "title": doc.get("title"),
            "url": f"https://openlibrary.org{doc.get('key', '')}",
            "snippet": ", ".join((doc.get("author_name") or [])[:3]),
            "year": doc.get("first_publish_year"),
        })

    root = ET.fromstring(ax.text)
    for entry in root.findall("a:entry", ATOM):
        results.append({
            "tier": "literature", "source": "arxiv",
            "title": " ".join((entry.findtext("a:title", "", ATOM) or "").split()),
            "url": entry.findtext("a:id", "", ATOM),
            "snippet": " ".join((entry.findtext("a:summary", "", ATOM) or "").split())[:300],
            "date": entry.findtext("a:published", "", ATOM),
        })

    for doc in ia.json().get("response", {}).get("docs", []):
        t = doc.get("title")
        title = t[0] if isinstance(t, list) else t
        cr = doc.get("creator")
        creator = ", ".join(cr[:2]) if isinstance(cr, list) else (cr or "")
        results.append({
            "tier": "literature", "source": "internet-archive",
            "title": title,
            "url": f"https://archive.org/details/{doc.get('identifier', '')}",
            "snippet": creator,
            "year": doc.get("year"),
        })

    for item in gb.json().get("items", []):
        v = item.get("volumeInfo", {})
        results.append({
            "tier": "literature", "source": "google-books",
            "title": v.get("title"),
            "url": v.get("infoLink") or v.get("canonicalVolumeLink") or "",
            "snippet": ", ".join((v.get("authors") or [])[:3]),
            "year": (v.get("publishedDate") or "")[:4],
        })

    return json.dumps({"results": results})


if __name__ == "__main__":
    mcp.run()
