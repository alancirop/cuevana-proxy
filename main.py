from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import httpx
import asyncio
import logging
from datetime import datetime, timedelta
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cuevana Proxy", version="1.0.0")

# ── Estado del proxy ──────────────────────────────────────
class ProxyState:
    cf_clearance: str = os.getenv("CF_CLEARANCE", "")
    last_updated: datetime = datetime.now()
    request_count: int = 0

state = ProxyState()

BASE_URL = "https://cuevana.gs/wp-api/v1"

def get_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Referer": "https://cuevana.gs/peliculas/",
        "Accept": "*/*",
        "Accept-Language": "es-US,es-419;q=0.9,es;q=0.8",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Cookie": f"cf_clearance={state.cf_clearance}",
    }

async def fetch_cuevana(url: str) -> dict:
    state.request_count += 1
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=get_headers())
        logger.info(f"GET {url} → HTTP {resp.status_code}")
        if resp.status_code == 403:
            raise HTTPException(status_code=403, detail="Cookie expirada — actualizá CF_CLEARANCE en Railway")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Error de cuevana")
        return resp.json()

# ── Endpoints ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status": "ok",
        "cf_clearance_set": bool(state.cf_clearance),
        "last_updated": state.last_updated.isoformat(),
        "requests_total": state.request_count,
    }

@app.get("/listing/{tipo}")
async def listing(
    tipo: str,
    page: int = Query(1),
    orderBy: str = Query("false"),
    order: str = Query("desc"),
    postsPerPage: int = Query(24)
):
    url = f"{BASE_URL}/listing/{tipo}?page={page}&orderBy={orderBy}&order={order}&postType={tipo}&postsPerPage={postsPerPage}"
    return await fetch_cuevana(url)

@app.get("/search")
async def search(
    postType: str = Query("movies"),
    q: str = Query(...),
    postsPerPage: int = Query(50)
):
    from urllib.parse import quote
    url = f"{BASE_URL}/search?postType={postType}&q={quote(q)}&postsPerPage={postsPerPage}"
    return await fetch_cuevana(url)

@app.get("/player")
async def player(
    postId: int = Query(...),
    demo: int = Query(0)
):
    url = f"{BASE_URL}/player?postId={postId}&demo={demo}"
    return await fetch_cuevana(url)

@app.get("/sliders")
async def sliders(
    page: int = Query(1),
    postType: str = Query("movies"),
    postsPerPage: int = Query(6)
):
    url = f"{BASE_URL}/sliders?page={page}&postType={postType}&postsPerPage={postsPerPage}"
    return await fetch_cuevana(url)

# ── Actualizar cookie via API (protegida con secret) ──────
@app.post("/update-cookie")
async def update_cookie(
    cookie: str = Query(...),
    secret: str = Query(...)
):
    expected = os.getenv("ADMIN_SECRET", "cambiar-esto")
    if secret != expected:
        raise HTTPException(status_code=401, detail="Secret inválido")
    state.cf_clearance = cookie
    state.last_updated = datetime.now()
    logger.info(f"✅ Cookie actualizada: {cookie[:30]}...")
    return {"status": "ok", "updated_at": state.last_updated.isoformat()}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
