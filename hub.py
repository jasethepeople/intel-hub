"""Unified Intelligence Hub — dashboard v5 (watchlist + scheduled refresh)."""
import asyncio
import time

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

import hub_store
from orchestrator import TIERS, broadcast, check_health

app = FastAPI(title="Unified Intelligence Hub", docs_url=None, redoc_url=None)


class PinBody(BaseModel):
    item: dict
    query: str = ""


class FetchBody(BaseModel):
    url: str


class WatchBody(BaseModel):
    query: str
    interval_sec: int = 86400


# ---------- scheduled refresh ----------

async def run_watch(w: dict) -> None:
    """Re-run a watched query, diff against previous snapshot, record the run."""
    report = await broadcast(w["query"])
    items = [r for t in report["tiers"].values() for r in t]
    keys = [hub_store.key_of(r) for r in items]
    prev = hub_store.latest_keys(w["id"])
    new_items = [r for r, k in zip(items, keys) if k not in prev]
    hub_store.record_run(w["id"], report["total"], new_items, keys)


async def scheduler_loop() -> None:
    while True:
        for w in hub_store.due_watches(time.time()):
            try:
                await run_watch(w)
            except Exception:
                pass  # a failed run just retries next tick
        await asyncio.sleep(15)


@app.on_event("startup")
async def _startup() -> None:
    asyncio.create_task(scheduler_loop())


PAGE = """<!doctype html><meta charset=utf-8><title>Intel Hub</title>
<style>
 body{font:14px/1.5 system-ui;margin:0;background:#0d1117;color:#e6edf3}
 header{padding:14px 24px;display:flex;gap:10px;align-items:center;
        border-bottom:1px solid #30363d;flex-wrap:wrap}
 input,select{padding:9px 12px;border-radius:8px;border:1px solid #30363d;
              background:#161b22;color:inherit}
 input{flex:1;min-width:160px}
 button{padding:9px 16px;border-radius:8px;border:0;background:#1f6feb;
        color:#fff;cursor:pointer}
 button.ghost,button.sm{background:#21262d;border:1px solid #30363d}
 button.sm{padding:3px 10px;font-size:11px}
 label{font-size:12px;color:#8b949e;display:flex;gap:4px;align-items:center}
 #status{font-size:12px;color:#8b949e;width:100%}
 #health{display:none;padding:8px 24px;font-size:12px;border-bottom:1px solid #21262d}
 #grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;padding:16px 24px}
 .pane h2,.sec h2{font-size:13px;text-transform:uppercase;color:#8b949e}
 .card{border:1px solid #30363d;border-radius:8px;padding:10px 12px;
       margin-bottom:10px;background:#161b22}
 .card a{color:#58a6ff;text-decoration:none;font-weight:600;word-break:break-all}
 .card .src{color:#8b949e;font-size:11px}
 .card p{margin:6px 0;font-size:12px;color:#c9d1d9}
 .card .acts{display:flex;gap:6px;margin-top:8px}
 .sec{display:none;padding:0 24px 24px}
 .CRITICAL{color:#f85149}.HIGH{color:#f0883e}.MEDIUM{color:#e3b341}
 .ok{color:#3fb950}.bad{color:#f85149}
 a.exp{color:#8b949e;font-size:12px;margin-left:10px}
 #modal{display:none;position:fixed;inset:5% 10%;background:#161b22;
        border:1px solid #30363d;border-radius:10px;padding:16px;z-index:9;
        overflow:auto;white-space:pre-wrap;font-size:12px}
 #modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:8}
</style>
<header>
 <input id=q placeholder="Search literature, code, and vulnerabilities…" autofocus
        onkeydown="if(event.key==='Enter')go()">
 <button onclick=go()>Search</button>
 <label><input type=checkbox id=f-literature checked>lit</label>
 <label><input type=checkbox id=f-code checked>code</label>
 <label><input type=checkbox id=f-vulns checked>vulns</label>
 <select id=sev-sort>
   <option value=none>severity: none</option>
   <option value=sort>severity: sort</option>
   <option value=high>severity: high+ only</option>
 </select>
 <input id=pq placeholder="…in cached pages" style="flex:0 0 160px"
        onkeydown="if(event.key==='Enter')searchPages()">
 <button class=ghost onclick=searchPages()>pages</button>
 <button class=ghost onclick="toggle('pins')">pinned (<span id=pincount>0</span>)</button>
 <button class=ghost onclick="toggle('watch')">watch (<span id=watchcount>0</span>)</button>
 <button class=ghost onclick=health()>health</button>
 <span id=status></span>
</header>
<div id=health></div>
<div id=grid>{panes}</div>
<div class=sec id=pins>
 <h2>pinned <a class=exp href="/api/pins/export?format=md" download>pins.md</a>
 <a class=exp href="/api/pins/export?format=json" download>pins.json</a></h2>
 <div id=pins-list></div>
</div>
<div class=sec id=watch>
 <h2>watched queries</h2>
 <div style="display:flex;gap:8px;margin-bottom:12px">
  <input id=wq placeholder="query to watch" style="flex:1">
  <select id=wint>
   <option value=3600>every hour</option>
   <option value=21600>every 6 hours</option>
   <option value=86400 selected>daily</option>
  </select>
  <button onclick=addWatch()>watch</button>
 </div>
 <div id=watch-list></div>
</div>
<div class=sec id=pages><h2>cached pages</h2><div id=pages-list></div></div>
<div id=modal-bg onclick=closeModal()></div><div id=modal></div>
<script>
let LAST={flat:[],query:""};
const SEV={CRITICAL:0,HIGH:1,MEDIUM:2,LOW:3,NONE:4};

function go(){
  const q=document.getElementById('q').value; if(!q) return;
  fetch('/api/search?q='+encodeURIComponent(q)).then(r=>r.json()).then(d=>{
    LAST=d; LAST.flat=[];
    document.getElementById('status').textContent=d.cached?'cached result':'fresh query';
    const mode=document.getElementById('sev-sort').value;
    for(const t of d.tiers_order){
      const el=document.getElementById('pane-'+t); if(!el) continue;
      el.style.display=document.getElementById('f-'+t).checked?'':'none';
      let items=d.tiers[t];
      if(t==='vulns'&&mode!=='none'){
        items=[...items].sort((a,b)=>(SEV[a.severity]??9)-(SEV[b.severity]??9));
        if(mode==='high') items=items.filter(i=>(SEV[i.severity]??9)<=1);
      }
      el.innerHTML=`<h2>${t} (${items.length})</h2>`+items.map(c=>{
        const uid=LAST.flat.push(c)-1;
        return `<div class=card><span class=src>[${c.source}${c.severity?
          ' · <b class='+c.severity+'>'+c.severity+'</b>':''}]</span><br>
          <a href="${c.url}" target=_blank>${c.title||''}</a>
          <p>${(c.snippet||'').slice(0,220)}</p>
          <div class=acts><button class=sm onclick=pinItem(${uid})>pin</button>
          <button class=sm onclick="fetchPage('${encodeURIComponent(c.url)}')">view</button></div></div>`;
      }).join('');
    }
  });
}

async function pinItem(uid){
  const c=LAST.flat[uid]; if(!c||!c.url) return;
  await fetch('/api/pin',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({item:c,query:LAST.query})});
  loadPins();
}

async function loadPins(){
  const pins=await (await fetch('/api/pins')).json();
  document.getElementById('pincount').textContent=pins.length;
  document.getElementById('pins-list').innerHTML=pins.map(p=>
    `<div class=card><span class=src>[${p.source||p.tier||''}] from "${p.query||''}"</span><br>
     <a href="${p.url}" target=_blank>${p.title||''}</a>
     <p>${(p.snippet||'').slice(0,220)}</p>
     <div class=acts><button class=sm onclick=unpin(${p.id})>unpin</button></div></div>`).join('')
    || '<i>nothing pinned yet</i>';
}

async function unpin(id){
  await fetch('/api/pin/'+id,{method:'DELETE'}); loadPins();
}

// ---------- watchlist ----------

async function loadWatches(){
  const ws=await (await fetch('/api/watch')).json();
  document.getElementById('watchcount').textContent=ws.length;
  document.getElementById('watch-list').innerHTML=ws.map(w=>{
    const hrs=w.interval_sec/3600;
    const when=w.last_run?new Date(w.last_run*1000).toLocaleString():'never';
    return `<div class=card><span class=src>every ${hrs}h · last run ${when} · ${w.last_total??0} results</span><br>
     <b>${w.query}</b> ${w.last_new?`<span class=bad>— ${w.last_new} new</span>`:''}
     <div class=acts><button class=sm onclick=watchNew(${w.id})>new</button>
     <button class=sm onclick=runWatch(${w.id})>run</button>
     <button class=sm onclick=delWatch(${w.id})>del</button></div></div>`;
  }).join('')||'<i>no watched queries</i>';
}

async function addWatch(){
  const q=document.getElementById('wq').value; if(!q) return;
  await fetch('/api/watch',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({query:q,interval_sec:+document.getElementById('wint').value})});
  document.getElementById('wq').value=''; loadWatches();
}

async function delWatch(id){
  await fetch('/api/watch/'+id,{method:'DELETE'}); loadWatches();
}

async function runWatch(id){
  await fetch('/api/watch/'+id+'/run',{method:'POST'}); loadWatches();
}

async function watchNew(id){
  const items=await (await fetch('/api/watch/'+id+'/new')).json();
  showModal(items.length
    ? items.map(c=>`[${c.source}] ${c.title}\n${c.url}\n${(c.snippet||'').slice(0,200)}`).join('\n\n')
    : 'no new items since previous run');
}

// ---------- misc ----------

function toggle(el){
  const e=document.getElementById(el);
  e.style.display=e.style.display==='none'?'block':'none';
  if(el==='pins'&&e.style.display==='block') loadPins();
  if(el==='watch'&&e.style.display==='block') loadWatches();
}

async function searchPages(){
  const q=document.getElementById('pq').value; if(!q) return;
  const items=await (await fetch('/api/pages/search?q='+encodeURIComponent(q))).json();
  document.getElementById('pages').style.display='block';
  document.getElementById('pages-list').innerHTML=items.map(c=>
    `<div class=card><a href="${c.url}" target=_blank>${c.url}</a><p>${c.snippet}</p>
     <div class=acts><button class=sm onclick="fetchPage('${encodeURIComponent(c.url)}')">view</button></div></div>`).join('')
    || '<i>no matches in cached pages — use a result card’s “view” button to cache pages first</i>';
}

async function health(){
  const h=await (await fetch('/api/health')).json();
  document.getElementById('health').style.display='block';
  document.getElementById('health').innerHTML=Object.entries(h).map(([n,s])=>
    s.skipped ? `<span style="margin-right:14px;color:#8b949e">○ ${n} (skipped)</span>`
    : `<span style="margin-right:14px"><span class="${s.ok?'ok':'bad'}">●</span>
       ${n} ${s.ok?s.latency_ms+'ms, '+s.tools+' tools':'— '+s.error.slice(0,60)}</span>`).join('');
}

async function fetchPage(enc){
  const url=decodeURIComponent(enc); if(!url) return;
  const r=await (await fetch('/api/fetch',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({url})})).json();
  showModal(`${url}\nstatus ${r.status}${r.cached?' (cached)':''}\n${r.error||''}\n\n`+
    (r.content||'').slice(0,20000));
}

function showModal(text){
  document.getElementById('modal').textContent=text;
  document.getElementById('modal').style.display='block';
  document.getElementById('modal-bg').style.display='block';
}

function closeModal(){
  document.getElementById('modal').style.display='none';
  document.getElementById('modal-bg').style.display='none';
}

loadPins(); loadWatches(); health();
</script>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    panes = "".join(f'<div class=pane id=pane-{t}><h2>{t}</h2></div>' for t in TIERS)
    return PAGE.replace("{panes}", panes)


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1), no_cache: bool = False):
    report = await broadcast(q, use_cache=not no_cache)
    report["tiers_order"] = TIERS
    return report


@app.post("/api/pin")
async def pin(body: PinBody):
    return {"id": hub_store.add_pin(body.item, body.query)}


@app.get("/api/pins")
async def pins():
    return hub_store.list_pins()


@app.delete("/api/pin/{pin_id}")
async def unpin(pin_id: int):
    hub_store.remove_pin(pin_id)
    return {"removed": pin_id}


@app.get("/api/pins/export")
async def export_pins(format: str = "md"):
    pins = hub_store.list_pins()
    if format == "json":
        return JSONResponse(
            pins, headers={"Content-Disposition": "attachment; filename=pins.json"}
        )
    def _pin_line(p):
        q = f' · query: "{p["query"]}"' if p["query"] else ""
        return (
            f"- [{p['title']}]({p['url']})\n"
            f"  - source: {p['source']} · tier: {p['tier']}{q}\n"
            f"  - {(p['snippet'] or '')[:300]}"
        )

    md = "# Pinned Results\n\n" + "\n\n".join(_pin_line(p) for p in pins)
    return PlainTextResponse(
        md, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=pins.md"},
    )


@app.post("/api/fetch")
async def fetch(body: FetchBody):
    return await hub_store.fetch_url(body.url)


@app.get("/api/pages/search")
async def pages_search(q: str = Query(..., min_length=1)):
    return hub_store.search_pages(q)


@app.get("/api/health")
async def health():
    return await check_health()


# ---------- watchlist endpoints ----------

@app.get("/api/watch")
async def watch_list():
    return hub_store.list_watches()


@app.post("/api/watch")
async def watch_add(body: WatchBody):
    return {"id": hub_store.add_watch(body.query, body.interval_sec)}


@app.delete("/api/watch/{wid}")
async def watch_del(wid: int):
    hub_store.remove_watch(wid)
    return {"removed": wid}


@app.post("/api/watch/{wid}/run")
async def watch_run_now(wid: int):
    w = hub_store.get_watch(wid)
    if not w:
        return JSONResponse({"error": "not found"}, status_code=404)
    await run_watch(w)
    return {"ran": wid}


@app.get("/api/watch/{wid}/new")
async def watch_new_items(wid: int):
    return hub_store.latest_new(wid)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8471)
