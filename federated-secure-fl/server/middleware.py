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
import httpx
import requests
from jose import jwt, JWTError
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


OPA_URL = os.getenv("OPA_URL", "http://opa:8181")

def check_policy(client_id: str, role: str) -> bool:
    """
    Calls OPA PDP to evaluate fl/allow policy.
    Input: {client_id, role}
    Returns: True if allowed, False if denied.
    """
    try:
        payload = {
            "input": {
                "client_id": client_id,
                "role": role,
            }
        }
        r = httpx.post(
            f"{OPA_URL}/v1/data/fl/allow",
            json=payload,
            timeout=5.0,
        )
        result = r.json().get("result", False)
        return bool(result)
    except Exception as e:
        log_event(log, "policy_check_error",
            client_id=client_id,
            error=str(e),
        )
        return False   # fail closed — deny on error

_jwks_cache = {"keys": None, "fetched_at": 0}

def get_jwks():
    if time.time() - _jwks_cache["fetched_at"] > 300:
        r = httpx.get(f"{KEYCLOAK_URL}/realms/fl-realm/protocol/openid-connect/certs")
        r.raise_for_status()
        _jwks_cache["keys"] = r.json()
        _jwks_cache["fetched_at"] = time.time()
    return _jwks_cache["keys"]


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
        try:
            claims = jwt.decode(
                token,
                get_jwks(),
                algorithms=["RS256"],
                audience="account",
                options={"verify_aud": False, "verify_exp": True}
            )
            client_id = claims.get("clientId") or claims.get("preferred_username") or claims.get("sub")
            if not client_id:
                raise ValueError("Could not extract client_id from token")
            
            token_valid = True
            
            role = claims.get("realm_access", {}).get("roles", [])
            role_str = "trainer" if "trainer" in role else "unknown"
        except Exception as e:
            token_valid = False
            error_msg = str(e)
            client_id = "unknown"

    if not token_valid:
        log_event(log, "admit_decision",
            correlation_id=cid,
            client_id=client_id,
            token_valid=False,
            result="rejected",
            rejection_reason=error_msg,
            duration_ms=t.duration_ms,
        )
        raise HTTPException(status_code=401, detail=error_msg)

    policy_allowed = check_policy(client_id, role_str)

    if not policy_allowed:
        log_event(log, "admit_decision",
            correlation_id=cid,
            client_id=client_id,
            token_valid=True,
            result="rejected",
            rejection_reason="policy_denied",
            duration_ms=t.duration_ms,
        )
        # E2: Non-blocking signal to Trust Engine on policy denial.
        # Fire-and-forget — never block, never raise, never retry.
        _server_host = os.getenv("SERVER_HOST", "server")
        try:
            requests.post(
                f"http://{_server_host}:9081/trust/policy-warning",
                json={"client_id": client_id, "reason": "policy_denied"},
                timeout=2,
            )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="Policy denied: client not authorized")

    log_event(log, "admit_decision",
        correlation_id=cid,
        client_id=client_id,
        token_valid=True,
        result="allowed",
        rejection_reason=None,
        duration_ms=t.duration_ms,
        policy_checked=True,
        policy_result="allowed",
    )

    return AdmitResponse(allowed=True, client_id=client_id)


# ───────────────────────── Main ─────────────────────────────────

def main() -> None:
    """Run middleware with Uvicorn."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)


if __name__ == "__main__":
    main()
