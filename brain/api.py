"""FastAPI app: REST + WebSocket on top of BrainGraph."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from brain.auth import (
    BasicAuthMiddleware,
    SessionStore,
    credentials_from_env,
    websocket_authorized,
)
from brain.coach import export_dashboard, get_questions
from brain.graph import BrainGraph
from brain.parser import parse_thought, parsed_to_node_fields
from brain.seed import seed_demo_nodes
from brain.storage import Storage
from brain.visualizer import export_graph
from brain.voice import VoiceUnavailableError, transcribe


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
DEFAULT_DB = os.path.join(REPO_ROOT, "brain.json")


def _resolve_db_path(explicit: str | None) -> str:
    """Priority: explicit arg > STORAGE_PATH > BRAIN_DB (legacy) > DEFAULT_DB."""
    return (
        explicit
        or os.environ.get("STORAGE_PATH")
        or os.environ.get("BRAIN_DB")
        or DEFAULT_DB
    )


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict) -> None:
        stale: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


def create_app(db_path: str | None = None) -> FastAPI:
    storage = Storage(_resolve_db_path(db_path))
    state: dict[str, Any] = {}
    sessions = SessionStore()
    state["sessions"] = sessions

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state["graph"] = BrainGraph.load(storage)
        seed_demo_nodes(state["graph"])
        state["manager"] = ConnectionManager()
        yield
        try:
            state["graph"].save()
        except Exception:
            pass

    app = FastAPI(lifespan=lifespan, title="second-brain-graph")

    # ---------- middleware (trusted hosts → auth) ----------

    allowed_hosts_env = os.environ.get("ALLOWED_HOSTS", "*").strip()
    if allowed_hosts_env and allowed_hosts_env != "*":
        hosts = [h.strip() for h in allowed_hosts_env.split(",") if h.strip()]
        if hosts:
            app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    username, password_hash = credentials_from_env()
    auth_enabled = bool(username and password_hash)
    if auth_enabled:
        app.add_middleware(
            BasicAuthMiddleware,
            username=username,
            password_hash=password_hash,
            sessions=sessions,
        )
    state["auth_enabled"] = auth_enabled

    def g() -> BrainGraph:
        return state["graph"]

    async def notify() -> None:
        await state["manager"].broadcast({"type": "graph_changed"})

    # ---------- static & index ----------

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    if os.path.isdir(FRONTEND_DIR):
        app.mount(
            "/static",
            StaticFiles(directory=FRONTEND_DIR),
            name="static",
        )

    # ---------- REST ----------

    @app.get("/api/graph")
    async def get_graph():
        return export_graph(g())

    @app.post("/api/nodes")
    async def create_node(payload: dict):
        node_type = payload.pop("type", "task")
        try:
            nid = g().add_node(node_type, **payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        g().save()
        await notify()
        return g().get_node(nid)

    @app.patch("/api/nodes/{node_id}")
    async def patch_node(node_id: str, payload: dict):
        try:
            g().update_node(node_id, **payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        g().save()
        await notify()
        return g().get_node(node_id)

    @app.delete("/api/nodes/{node_id}")
    async def delete_node(node_id: str):
        try:
            g().soft_delete(node_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        g().save()
        await notify()
        return {"ok": True}

    @app.post("/api/nodes/{node_id}/restore")
    async def restore_node(node_id: str):
        try:
            g().restore(node_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        g().save()
        await notify()
        return g().get_node(node_id)

    @app.post("/api/edges")
    async def create_edge(payload: dict):
        try:
            g().add_edge(payload["from"], payload["to"], payload["type"])
        except KeyError as e:
            raise HTTPException(status_code=400, detail=f"missing field: {e}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        g().save()
        await notify()
        return {"ok": True}

    @app.delete("/api/edges")
    async def delete_edge(payload: dict):
        try:
            g().remove_edge(payload["from"], payload["to"], payload["type"])
        except KeyError as e:
            raise HTTPException(status_code=400, detail=f"missing field: {e}")
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        g().save()
        await notify()
        return {"ok": True}

    @app.get("/api/actionable")
    async def actionable(free_time: int | None = None, strict: bool = False):
        return g().get_actionable(free_time_minutes=free_time, strict_time_filter=strict)

    @app.post("/api/undo")
    async def undo():
        try:
            g().undo_last_action()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        g().save()
        await notify()
        return {"ok": True}

    @app.get("/api/audit")
    async def audit(limit: int = 100):
        return g().get_audit_log(limit=limit)

    # ---------- coach ----------

    @app.get("/api/coach/dashboard")
    async def coach_dashboard():
        return export_dashboard(g())

    @app.post("/api/coach")
    async def coach():
        try:
            return get_questions(g())
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"coach failed: {e}")

    # ---------- voice + parser ----------

    @app.post("/api/voice")
    async def voice(audio: UploadFile = File(...)):
        data = await audio.read()
        try:
            text = transcribe(data, filename=audio.filename or "audio.webm")
        except VoiceUnavailableError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"text": text}

    @app.post("/api/thoughts")
    async def thoughts(payload: dict):
        text = (payload.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="text must be a non-empty string")
        try:
            parsed = parse_thought(text)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"parser failed: {e}")
        node_type, fields = parsed_to_node_fields(parsed)
        try:
            nid = g().add_node(node_type, **fields)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        g().save()
        await notify()
        return {
            "node": g().get_node(nid),
            "parsed": parsed,
            "needs_review": fields["status"] == "inbox",
        }

    # ---------- WebSocket ----------

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        if state.get("auth_enabled") and not websocket_authorized(ws, sessions):
            await ws.close(code=1008)
            return
        await state["manager"].connect(ws)
        try:
            while True:
                # we don't expect inbound messages; keep the socket open
                await ws.receive_text()
        except WebSocketDisconnect:
            state["manager"].disconnect(ws)
        except Exception:
            state["manager"].disconnect(ws)

    return app


app = create_app()
