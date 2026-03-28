from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import httpx
import asyncio
import logging
from datetime import datetime
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cuevana Proxy", version="3.0.0")

BASE_URL      = "https://cuevana.gs/wp-api/v1"
FLARESOLVERR  = os.getenv("FLARESOLVERR_URL", "http://localhost:8191")

class State:
    request_count: int = 0

state = State()

async def fetch_via_flaresolverr(url: str) -> dict:
    """Hace TODAS las requests a través de FlareSolverr para evitar bloqueos de IP"""
    state.request_count += 1
    logger.info(f"FlareSolverr GET: {url}")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{FLARESOLVERR}/v1", json={
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000
        })
        data = resp.json()
        
        if data.get("status") != "ok":
            logger.error(f"FlareSolverr error: {data.get('message')}")
            raise HTTPException(status_code=502, detail=f"FlareSolverr error: {data.get('message')}")
        
        solution = data.get("solution", {})
        status   = solution.get("status", 0)
        body     = solution.get("response", "")
        
        logger.info(f"FlareSolverr → HTTP {status}")
        
        if status != 200:
            raise HTTPException(status_code=status, detail="Error de cuevana via FlareSolverr")
        
        import json
        try:
            return json.loads(body)
        except:
            raise HTTPException(status_code=502, detail="Respuesta inválida de cuevana")

@app.get("/")
async def root():
    return {
        "status": "ok",
        "requests_total": state.request_count,
        "flaresolverr": FLARESOLVERR,
        "mode": "full_proxy"
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
    from urllib.parse import quote
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
