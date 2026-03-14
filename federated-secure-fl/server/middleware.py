"""
FastAPI Middleware — Phase 0
Provides /health and /admit endpoints.
JWT verification is stubbed; real JWKS integration in Phase 2.
"""

import os
import time
import uuid
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from dotenv import load_dotenv
from shared.logger import get_logger, log_event, Timer

load_dotenv()

# ───────────────────────── Configuration ─────────────────────────
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")

# ───────────────────────── Logging ───────────────────────────────
log = get_logger("middleware")

# ───────────────────────── App ───────────────────────────────────
app = FastAPI(title="FL Middleware", version="0.1.0")


class AdmitResponse(BaseModel):
    allowed: bool
    client_id: str


# TODO Phase 3 — replace with real OPA /v1/data/fl/allow call
# Input will be JWT claims: {client_id, role}
# OPA Rego policy is ready in policy/fl_policy.rego
def check_policy(client_id: str, role: str) -> bool:
    return True


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every HTTP request with method, path, status, and duration."""
    cid = str(uuid.uuid4())
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 2)
    log_event(log, "http_request",
        correlation_id=cid,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/admit", response_model=AdmitResponse)
async def admit(authorization: Optional[str] = Header(None)):
    """
    Admit a client based on Bearer token.
    Phase 0: stub — accepts any well-formed Bearer token.
    Phase 2: real JWKS verification via Keycloak.
    """
    cid = str(uuid.uuid4())

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(status_code=401, detail="Empty token")

    with Timer() as t:
        # ── Stub: extract a fake client_id from the token ──
        # In Phase 2 this will decode the JWT and extract claims
        client_id = f"client_{hash(token) % 10000:04d}"

    log_event(log, "admit_decision",
        correlation_id=cid,
        client_id=client_id,
        has_token=authorization.startswith("Bearer "),
        token_valid=True,       # Phase 2: set from real verification result
        result="allowed",       # Phase 2: "rejected" on bad token
        duration_ms=t.duration_ms,
    )

    return AdmitResponse(allowed=True, client_id=client_id)


# ───────────────────────── Main ─────────────────────────────────

def main() -> None:
    """Run middleware with Uvicorn."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
