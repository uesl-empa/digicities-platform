"""Onboarding-agent endpoints — drive the agent (a platform plugin) from React.

Uses the agent's headless AgentSession (same conversation code as the Streamlit
plugin) with a per-session store. Upload a working folder (.zip) to propose a
mapping, then send messages to walk the decisions, build, and ask the graph.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.workspace import WorkspaceContext

from .deps import get_ctx

# The agent lives as a mounted module; put it on the path so we can import it.
_MODULES = os.getenv("MODULES_DIR", "/app/data/modules")
if _MODULES not in sys.path:
    sys.path.insert(0, _MODULES)

router = APIRouter(prefix="/api/workspaces/{workspace_id}/agent", tags=["agent"])

# session_id -> AgentSession (in-memory; one process)
_SESSIONS: dict[str, Any] = {}


def _new_session(ctx: WorkspaceContext):
    from onboarding_agent.headless import AgentSession
    ws_root = str(Path(os.getenv("USECASES_DIR", "/app/data/usecases")) / ctx.id)
    return AgentSession(
        ctx.id, ws_root, ctx, ctx.graphdb_repository or ctx.id,
        model=os.getenv("LLM_MODEL", "sonnet"),
    )


def _get(session_id: str):
    sess = _SESSIONS.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="agent session not found — start a new one")
    return sess


class StartBody(BaseModel):
    model: str | None = None
    chat_id: str | None = None


@router.get("/models")
def models() -> list[dict[str, str]]:
    from onboarding_agent.headless import MODELS
    return MODELS


@router.get("/chats")
def chats(ctx: WorkspaceContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    """Persisted conversations for this workspace."""
    return _new_session(ctx).list_chats()


@router.post("/session")
def start_session(body: StartBody | None = None, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Open a conversation — fresh, or load a persisted chat_id; optional model."""
    sid = uuid.uuid4().hex
    sess = _new_session(ctx)
    if body and body.model:
        sess.set_model(body.model)
    _SESSIONS[sid] = sess
    if body and body.chat_id:
        sess.load_chat(body.chat_id)
    return {"session_id": sid, **sess.snapshot()}


class ModelBody(BaseModel):
    session_id: str
    model: str


@router.post("/model")
def set_model(body: ModelBody, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, str]:
    _get(body.session_id).set_model(body.model)
    return {"model": body.model}


class Message(BaseModel):
    session_id: str
    text: str


@router.post("/message")
def message(body: Message, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    return _get(body.session_id).send(body.text)


@router.get("/message/stream")
def message_stream(session_id: str, text: str, ctx: WorkspaceContext = Depends(get_ctx)):
    """Server-sent events: `token` as the LLM writes, then `result` with the full turn."""
    import json as _json
    from fastapi.responses import StreamingResponse

    sess = _get(session_id)

    def gen():
        for kind, data in sess.send_stream(text):
            yield f"event: {kind}\ndata: {_json.dumps(data)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/state")
def state(session_id: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    return _get(session_id).snapshot()


@router.post("/upload")
async def upload(
    session_id: str = Form(...),
    file: UploadFile = File(...),
    ctx: WorkspaceContext = Depends(get_ctx),
) -> dict[str, Any]:
    """Upload a working folder as a .zip; the agent reads it and proposes a mapping."""
    sess = _get(session_id)
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload the working folder as a .zip")
    tmp = Path(tempfile.mkdtemp())
    zpath = tmp / file.filename
    zpath.write_bytes(await file.read())
    try:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp / "x")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Bad zip: {exc}") from exc
    root = tmp / "x"
    # If the zip had a single top-level folder, descend into it.
    entries = [p for p in root.iterdir() if not p.name.startswith("__MACOSX")]
    folder = entries[0] if len(entries) == 1 and entries[0].is_dir() else root
    # record the uploaded-file marker the way the UI does, for the chat log
    sess.state.oa_messages.append(("user", f"📦 Uploaded `{file.filename}`"))
    return sess.propose(folder)
