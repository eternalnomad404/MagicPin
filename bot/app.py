"""HTTP surface for the magicpin judge harness.

Endpoints: POST /v1/context, POST /v1/tick, POST /v1/reply,
           GET /v1/healthz, GET /v1/metadata, POST /v1/teardown (optional)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from . import config
from .composer import precompose, tick
from .logging_util import log_event
from .replies import handle_reply
from .store import SCOPES, parse_iso, store

app = FastAPI(title="Nukkad — Vera challenge bot", version=config.BOT_VERSION, docs_url=None, redoc_url=None)


class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int = 1
    payload: dict[str, Any] = Field(default_factory=dict)
    delivered_at: Optional[str] = None


class TickBody(BaseModel):
    now: Optional[str] = None
    available_triggers: list[str] = Field(default_factory=list)


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: Optional[str] = "merchant"
    message: str = ""
    received_at: Optional[str] = None
    turn_number: Optional[int] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@app.get("/")
async def root():
    return {"service": "nukkad-vera-bot", "version": config.BOT_VERSION}


@app.get("/v1/healthz")
async def healthz():
    return {"status": "ok", "uptime_seconds": store.uptime_seconds(), "contexts_loaded": store.counts()}


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": config.TEAM_NAME,
        "team_members": config.TEAM_MEMBERS,
        "model": config.COMPOSE_MODEL,
        "approach": config.APPROACH,
        "contact_email": config.CONTACT_EMAIL,
        "version": config.BOT_VERSION,
        "submitted_at": config.SUBMITTED_AT,
    }


@app.post("/v1/context")
async def push_context(request: Request):
    try:
        body = ContextBody.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        return JSONResponse({"accepted": False, "reason": "malformed", "details": str(exc)[:300]}, status_code=400)
    if body.scope not in SCOPES:
        return JSONResponse({"accepted": False, "reason": "invalid_scope",
                             "details": f"scope must be one of {list(SCOPES)}"}, status_code=400)
    status, current = await store.upsert(body.scope, body.context_id, body.version, body.payload, body.delivered_at or _now_iso())
    if status == "stale":
        return JSONResponse({"accepted": False, "reason": "stale_version", "current_version": current}, status_code=409)
    log_event("context_in", scope=body.scope, context_id=body.context_id, version=body.version)
    if body.scope == "trigger":
        asyncio.create_task(precompose(store, body.context_id))
    elif body.scope in ("merchant", "category", "customer"):
        # a fresh version invalidates cached compositions that depended on it
        for tid, entry in list(store.compose_cache.items()):
            trg = store.get("trigger", tid) or {}
            merchant = store.merchant_for_trigger(trg) or {}
            if (body.scope == "merchant" and trg.get("merchant_id") == body.context_id) or \
               (body.scope == "customer" and trg.get("customer_id") == body.context_id) or \
               (body.scope == "category" and merchant.get("category_slug") == body.context_id):
                store.compose_cache.pop(tid, None)
                asyncio.create_task(precompose(store, tid))
    return {"accepted": True, "ack_id": f"ack_{body.context_id}_v{body.version}", "stored_at": _now_iso()}


@app.post("/v1/tick")
async def tick_endpoint(request: Request):
    try:
        body = TickBody.model_validate(await request.json())
    except (ValidationError, ValueError):
        body = TickBody()
    now = parse_iso(body.now) or datetime.now(timezone.utc)
    try:
        actions = await tick(store, now, body.available_triggers)
    except Exception as exc:  # never return a malformed response
        log_event("tick_error", error=str(exc)[:400])
        actions = []
    log_event("tick", now=body.now, requested=len(body.available_triggers), sent=len(actions))
    return {"actions": actions}


@app.post("/v1/reply")
async def reply_endpoint(request: Request):
    try:
        body = ReplyBody.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        return JSONResponse({"action": "wait", "wait_seconds": 600,
                             "rationale": f"Malformed reply payload: {str(exc)[:120]}"}, status_code=200)
    try:
        return await handle_reply(store, body.model_dump())
    except Exception as exc:
        log_event("reply_error", error=str(exc)[:400], conversation_id=body.conversation_id)
        return {"action": "wait", "wait_seconds": 1800, "rationale": "Internal error while composing; backing off rather than sending something wrong."}


@app.post("/v1/teardown")
async def teardown():
    store.teardown()
    log_event("teardown")
    return {"ok": True, "wiped": True}
