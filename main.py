from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import httpx
import asyncio
import logging
from datetime import datetime, timedelta
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cuevana Proxy", version="2.0.0")

BASE_URL        = "https://cuevana.gs/wp-api/v1"
FLARESOLVERR   = os.getenv("FLARESOLVERR_URL", "http://localhost:8191")
ADMIN_SECRET   = os.getenv("ADMIN_SECRET", "tvfamiliar2026")

# ── Estado ────────────────────────────────────────────────
class State:
    cf_clearance: str = ""
    user_agent: str   = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    last_renewed: datetime = datetime.min
    renewing: bool    = False
    request_count: int = 0

state = State()

# ── Renovar cookie via FlareSolverr ──────────────────────
async def renovar_cookie() -> bool:
    if state.renewing:
        logger.info("Ya renovando, esperando...")
        for _ in range(30):
            await asyncio.sleep(1)
            if not state.renewing:
                break
        return bool(state.cf_clearance)

    state.renewing = True
    logger.info("🔄 Renovando cf_clearance via FlareSolverr...")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{FLARESOLVERR}/v1", json={
                "cmd": "request.get",
                "url": "https://cuevana.gs/wp-api/v1/listing/movies?page=1&postsPerPage=1",
                "maxTimeout": 60000
            })
            data = resp.json()
            logger.info(f"FlareSolverr status: {data.get('status')}")

            if data.get("status") == "ok":
                solution = data.get("solution", {})
                cookies  = solution.get("cookies", [])
                ua       = solution.get("userAgent", state.user_agent)

                cf = next((c["value"] for c in cookies if c["name"] == "cf_clearance"), "")
                if cf:
                    state.cf_clearance = cf
                    state.user_agent   = ua
                    state.last_renewed = datetime.now()
                    logger.info(f"✅ cf_clearance renovada: {cf[:30]}...")
                    state.renewing = False
                    return True
                else:
                    logger.warning("⚠️ FlareSolverr no devolvió cf_clearance")
            else:
                logger.error(f"❌ FlareSolverr error: {data.get('message')}")
    except Exception as e:
        logger.error(f"❌ Error FlareSolverr: {e}")

    state.renewing = False
    return False

async def get_headers() -> dict:
    # Renovar si expiró (cada 20 horas)
    edad = datetime.now() - state.last_renewed
    if not state.cf_clearance or edad > timedelta(hours=20):
        logger.info("Cookie expirada o vacía, renovando...")
        await renovar_cookie()

    return {
        "User-Agent": state.user_agent,
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
    headers = await get_headers()

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers=headers)
        logger.info(f"GET {url} → HTTP {resp.status_code}")

        if resp.status_code == 403:
            # Cookie expirada — renovar y reintentar
            logger.warning("403 detectado — renovando cookie...")
            state.cf_clearance = ""  # forzar renovación
            headers = await get_headers()
            async with httpx.AsyncClient(timeout=20.0) as client2:
                resp = await client2.get(url, headers=headers)
                logger.info(f"Reintento → HTTP {resp.status_code}")
                if resp.status_code != 200:
                    raise HTTPException(status_code=resp.status_code, detail="Error después de renovar cookie")

        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Error de cuevana")

        return resp.json()

# ── Endpoints ─────────────────────────────────────────────

@app.get("/")
async def root():
    edad = datetime.now() - state.last_renewed
    return {
        "status": "ok",
        "cf_clearance_set": bool(state.cf_clearance),
        "cookie_age_minutes": int(edad.total_seconds() / 60) if state.cf_clearance else -1,
        "last_renewed": state.last_renewed.isoformat(),
        "requests_total": state.request_count,
        "flaresolverr": FLARESOLVERR,
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
async def player(postId: int = Query(...), demo: int = Query(0)):
    url = f"{BASE_URL}/player?postId={postId}&demo={demo}"
    return await fetch_cuevana(url)

@app.on_event("startup")
async def startup():
    logger.info("🚀 Servidor iniciado — renovando cookie inicial...")
    asyncio.create_task(renovar_cookie())

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
