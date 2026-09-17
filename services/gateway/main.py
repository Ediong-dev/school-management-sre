import os
import random

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="School Gateway")
Instrumentator().instrument(app).expose(app)

AUTH_URL      = os.getenv("AUTH_URL",      "http://auth:3001")
ACADEMICS_URL = os.getenv("ACADEMICS_URL", "http://academics:3002")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://dashboard:3003")

TIMEOUT = httpx.Timeout(10.0, connect=2.0)

# Fault injection for Lab 7 canary demos. Injected via env var.
GATEWAY_FAILURE_RATE = float(os.getenv("GATEWAY_FAILURE_RATE", "0"))

# Headers we never forward — these are hop-by-hop or cause breakage.
HOP_BY_HOP = {
    "host", "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade",
    "content-length",
}

async def _proxy(base_url: str, path: str, request: Request) -> Response:
    """Forward request to upstream, preserve status, body, and headers."""
    # Fault injection for Lab 7 canary demos.
    if GATEWAY_FAILURE_RATE > 0 and random.random() < GATEWAY_FAILURE_RATE:
        raise HTTPException(status_code=500, detail="Injected gateway failure")

    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            upstream = await client.request(
                request.method,
                f"{base_url}/{path}",
                content=body,
                params=request.query_params,
                headers=headers,
            )
        except httpx.RequestError as e:
            return Response(
                content=f'{{"detail":"Upstream unavailable: {e}"}}',
                status_code=503,
                media_type="application/json",
            )

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={k: v for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP},
        media_type=upstream.headers.get("content-type"),
    )

@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway"}

@app.api_route("/api/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_auth(path: str, request: Request):
    return await _proxy(AUTH_URL, path, request)

@app.api_route("/api/academics/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_academics(path: str, request: Request):
    return await _proxy(ACADEMICS_URL, path, request)

@app.api_route("/api/dashboard/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_dashboard(path: str, request: Request):
    return await _proxy(DASHBOARD_URL, path, request)