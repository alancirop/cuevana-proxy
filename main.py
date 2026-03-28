from fastapi import FastAPI, HTTPException, Query
import httpx
import logging
from urllib.parse import quote
import os
import json
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cuevana Proxy", version="4.0.0")

BASE_URL     = "https://cuevana.gs/wp-api/v1"
FLARESOLVERR = os.getenv("FLARESOLVERR_URL", "http://localhost:8191")

class State:
    request_count: int = 0

state = State()

def extract_json(body: str) -> dict:
    """Extrae JSON del body aunque venga envuelto en HTML de FlareSolverr"""
    # Intentar parsear directo
    try:
        return json.loads(body)
    except:
        pass

    # Buscar JSON dentro del HTML — FlareSolverr a veces lo envuelve en <pre>
    match = re.search(r'<pre[^>]*>(.*?)</pre>', body, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass

    # Buscar el primer { hasta el ultimo }
    start = body.find('{')
    end   = body.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(body[start:end+1])
        except:
            pass

    raise ValueError(f"No se pudo extraer JSON del body: {body[:200]}")

async def fetch_via_flaresolverr(url: str) -> dict:
    state.request_count += 1
    logger.info(f"FlareSolverr GET: {url}")

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(f"{FLARESOLVERR}/v1", json={
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000
        })
        data = resp.json()
        logger.info(f"FlareSolverr status: {data.get('status')}")

        if data.get("status") != "ok":
            raise HTTPException(status_code=502, detail=f"FlareSolverr error: {data.get('message')}")

        solution    = data.get("solution", {})
        http_status = solution.get("status", 0)
        body        = solution.get("response", "")

        logger.info(f"HTTP status cuevana: {http_status}")

        if http_status not in (200, 201):
            raise HTTPException(status_code=http_status, detail=f"Error cuevana: {http_status}")

        try:
            return extract_json(body)
        except Exception as e:
            logger.error(f"JSON error: {e}")
            raise HTTPException(status_code=502, detail="Respuesta invalida de cuevana")

@app.get("/")
async def root():
    return {
        "status": "ok",
        "mode": "flaresolverr_full_proxy",
        "flaresolverr": FLARESOLVERR,
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
    return await fetch_via_flaresolverr(url)

@app.get("/search")
async def search(
    postType: str = Query("movies"),
    q: str = Query(...),
    postsPerPage: int = Query(50)
):
    url = f"{BASE_URL}/search?postType={postType}&q={quote(q)}&postsPerPage={postsPerPage}"
    return await fetch_via_flaresolverr(url)

@app.get("/player")
async def player(postId: int = Query(...), demo: int = Query(0)):
    url = f"{BASE_URL}/player?postId={postId}&demo={demo}"
    return await fetch_via_flaresolverr(url)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
