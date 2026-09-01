"""Onboarding-agent endpoints — drive the agent (a platform plugin) from React.

Uses the agent's headless AgentSession (same conversation code as the Streamlit
plugin) with a per-session store. Upload a working folder (.zip) to propose a
mapping, then send messages to walk the decisions, build, and ask the graph.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
import zipfile
from collections import OrderedDict
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

# session_id -> AgentSession. In-memory, one process, and *bounded*: an LRU
# capped at $AGENT_SESSION_CAP (default 32). Every session the store holds
# keeps a live LLM conversation plus (after an upload) a temp working folder,
# so an unbounded dict leaks both under any real traffic.
_SESSIONS: "OrderedDict[str, Any]" = OrderedDict()


def _session_cap() -> int:
    try:
        return max(1, int(os.getenv("AGENT_SESSION_CAP", "32")))
    except ValueError:
        return 32


def _dispose(sess: Any) -> None:
    """Release an evicted session's on-disk footprint (its upload tmp dir)."""
    tmp = getattr(sess, "_upload_tmp", None)
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


def _put(session_id: str, sess: Any) -> None:
    _SESSIONS[session_id] = sess
    _SESSIONS.move_to_end(session_id)
    while len(_SESSIONS) > _session_cap():
        _, oldest = _SESSIONS.popitem(last=False)
        _dispose(oldest)


def _new_session(ctx: WorkspaceContext):
    from onboarding_agent.headless import AgentSession
    from .deps import ws_root
    return AgentSession(
        ctx.id, str(ws_root(ctx)), ctx, ctx.graphdb_repository or ctx.id,
        model=os.getenv("LLM_MODEL", "sonnet"),
    )


def _get(session_id: str):
    sess = _SESSIONS.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="agent session not found — start a new one")
    _SESSIONS.move_to_end(session_id)  # touched → most recently used
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
    _put(sid, sess)
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


class ModeBody(BaseModel):
    session_id: str
    mode: str                # "auto" (apply defaults) | "manual" (walk decisions)


@router.post("/mode")
def set_mode(body: ModeBody, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, str]:
    sess = _get(body.session_id)
    sess.set_mode(body.mode)
    return {"mode": sess.state.oa_mode}


class ApiKeyBody(BaseModel):
    provider: str            # "anthropic" | "mistral"
    key: str | None = None   # falsy clears the stored key


@router.post("/api-key")
def set_api_key(body: ApiKeyBody, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Set (and persist) an LLM provider key from the settings panel; returns the
    updated settings (key status never echoes the key itself)."""
    if body.provider not in ("anthropic", "mistral"):
        raise HTTPException(status_code=400, detail="provider must be 'anthropic' or 'mistral'")
    sess = _new_session(ctx)
    sess.set_api_key(body.provider, (body.key or "").strip() or None)
    return sess.settings()


@router.get("/settings")
def settings(ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Settings-panel data: per-provider key status + the read-only folder where the
    agent stores this workspace's artifacts (chats, ingestion report, provenance)."""
    return _new_session(ctx).settings()


class Message(BaseModel):
    session_id: str
    text: str


@router.post("/message")
def message(body: Message, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    return _get(body.session_id).send(body.text)


def _stream_response(sess, text: str):
    import json as _json
    from fastapi.responses import StreamingResponse

    def gen():
        for kind, data in sess.send_stream(text):
            yield f"event: {kind}\ndata: {_json.dumps(data)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/message/stream")
def message_stream(session_id: str, text: str, ctx: WorkspaceContext = Depends(get_ctx)):
    """Server-sent events: `token` as the LLM writes, then `result` with the full turn.

    GET exists for EventSource clients; long messages should use the POST
    variant so the text rides in the body, not the query string / access logs.
    """
    return _stream_response(_get(session_id), text)


@router.post("/message/stream")
def message_stream_post(body: Message, ctx: WorkspaceContext = Depends(get_ctx)):
    """Same SSE stream, message in the request body (fetch + ReadableStream)."""
    return _stream_response(_get(body.session_id), body.text)


@router.get("/state")
def state(session_id: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    return _get(session_id).snapshot()


@router.post("/upload")
async def upload(
    session_id: str = Form(...),
    file: UploadFile = File(...),
    ctx: WorkspaceContext = Depends(get_ctx),
) -> dict[str, Any]:
    """Upload a working folder as a .zip, OR a single file. A single file is ADDED to the
    current working folder when one already exists (e.g. drop in an onboarding guide, or a
    file a previous read missed) and the folder is re-read; otherwise it becomes a one-file
    working folder. The agent reads the result and proposes a mapping."""
    sess = _get(session_id)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file was uploaded")
    name = Path(file.filename).name            # basename only — no path traversal
    data = await file.read()

    # ── a .zip → a fresh working folder (replaces any prior upload) ──────────────
    if name.lower().endswith(".zip"):
        prev = getattr(sess, "_upload_tmp", None)
        if prev:
            shutil.rmtree(prev, ignore_errors=True)
        tmp = Path(tempfile.mkdtemp(prefix="oa-upload-"))
        sess._upload_tmp = str(tmp)
        zpath = tmp / "upload.zip"
        zpath.write_bytes(data)
        root = (tmp / "x").resolve()
        try:
            with zipfile.ZipFile(zpath) as z:
                for m in z.infolist():
                    # zip-slip guard: no entry may land outside the extract root
                    target = (root / m.filename).resolve()
                    if root != target and root not in target.parents:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Zip entry escapes its root: {m.filename!r}")
                z.extractall(root)
        except HTTPException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Bad zip: {exc}") from exc
        # If the zip had a single top-level folder, descend into it.
        entries = [p for p in root.iterdir() if not p.name.startswith("__MACOSX")]
        folder = entries[0] if len(entries) == 1 and entries[0].is_dir() else root
        sess._upload_folder = str(folder)
        sess.state.oa_messages.append(("user", f"📦 Uploaded `{name}`"))
        return sess.propose(folder)

    # ── a single file added to the current working folder → re-read it ───────────
    existing = getattr(sess, "_upload_folder", None)
    if existing and Path(existing).is_dir():
        (Path(existing) / name).write_bytes(data)
        sess.state.oa_messages.append(("user", f"📎 Added `{name}` to the working folder"))
        return sess.propose(Path(existing))

    # ── a single file with no prior folder → a one-file working folder ───────────
    prev = getattr(sess, "_upload_tmp", None)
    if prev:
        shutil.rmtree(prev, ignore_errors=True)
    tmp = Path(tempfile.mkdtemp(prefix="oa-upload-"))
    sess._upload_tmp = str(tmp)
    folder = tmp / "x"
    folder.mkdir()
    (folder / name).write_bytes(data)
    sess._upload_folder = str(folder)
    sess.state.oa_messages.append(("user", f"📄 Uploaded `{name}`"))
    return sess.propose(folder)
