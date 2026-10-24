"""Wall server: receives pushes from senders and drives the wall display live.

Run on the machine connected to the big screen:
    python server.py
Then open http://localhost:8765/ fullscreen (kiosk) on that screen.
"""
import hmac
import json
import mimetypes
import re
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import quote, unquote

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from starlette.requests import ClientDisconnect

BASE = Path(__file__).parent
CONFIG_PATH = BASE / "config.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
TOKEN_GENERATED = CONFIG.get("token", "") in ("", "change-me")
if TOKEN_GENERATED:
    # never run with no token or the default one: pick a random one and remember it
    CONFIG["token"] = secrets.token_urlsafe(9)
    CONFIG_PATH.write_text(json.dumps(CONFIG, indent=2) + "\n", encoding="utf-8")
TOKEN = CONFIG["token"]
MAX_UPLOAD = int(CONFIG.get("max_upload_mb", 2048)) * 1024 * 1024
UPLOADS = BASE / "uploads"
UPLOADS.mkdir(exist_ok=True)

LAYOUTS = {"single": 1, "split": 2, "focus": 3, "grid": 4}
PROGRESS_INTERVAL = 0.08  # seconds between progress updates sent to the wall
TEXT_EXT = {".txt", ".md", ".log", ".csv", ".json", ".py", ".ini", ".cfg", ".xml", ".yaml", ".yml"}

app = FastAPI(title="Wall")
clients: set[WebSocket] = set()
state = {"layout": "single", "blackout": False, "slots": {}}  # slots: {int: item}


# ---------- helpers ----------

async def broadcast(msg: dict) -> None:
    data = json.dumps(msg)
    for ws in list(clients):
        try:
            await ws.send_text(data)
        except Exception:
            clients.discard(ws)


def public_state() -> dict:
    return {"layout": state["layout"], "blackout": state["blackout"],
            "slots": {str(k): v for k, v in state["slots"].items()}}


def token_ok(conn: Request | WebSocket) -> bool:
    """Token from the X-Wall-Token header, or ?token= where headers can't be set (WebSocket, <img src>)."""
    given = conn.headers.get("x-wall-token") or conn.query_params.get("token") or ""
    return hmac.compare_digest(given.encode(), TOKEN.encode())


def is_local(conn: Request | WebSocket) -> bool:
    return conn.client is not None and conn.client.host in ("127.0.0.1", "::1")


def check_token(request: Request) -> None:
    if not token_ok(request):
        raise HTTPException(status_code=401, detail="Wrong or missing token")


def can_view(conn: Request | WebSocket) -> bool:
    """The wall display on this machine may watch without a token; everyone else needs it."""
    return is_local(conn) or token_ok(conn)


def safe_name(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^\w.\- ()]", "_", name)[:120] or "file"


def kind_of(name: str) -> str:
    mime = mimetypes.guess_type(name)[0] or ""
    ext = Path(name).suffix.lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if ext == ".pdf":
        return "pdf"
    if mime.startswith("text/") or ext in TEXT_EXT:
        return "text"
    return "file"


def pick_slot(requested: int) -> int:
    n = LAYOUTS[state["layout"]]
    if 1 <= requested <= n:
        return requested
    for i in range(1, n + 1):
        if i not in state["slots"]:
            return i
    unpinned = [(item["t"], i) for i, item in state["slots"].items()
                if i <= n and not item.get("pinned")]
    return min(unpinned)[1] if unpinned else 1


def delete_upload(item: dict | None) -> None:
    if item and item.get("file"):
        still_used = any(other.get("file") == item["file"] for other in state["slots"].values())
        if not still_used:
            (UPLOADS / item["file"]).unlink(missing_ok=True)


# ---------- routes ----------

@app.get("/")
async def display_page():
    return FileResponse(BASE / "display.html")


@app.get("/control")
async def control_page():
    return FileResponse(BASE / "control.html")


@app.get("/files/{name}")
async def get_file(name: str, request: Request):
    if not can_view(request):
        raise HTTPException(status_code=401, detail="Wrong or missing token")
    path = UPLOADS / Path(name).name
    if not path.is_file():
        raise HTTPException(status_code=404)
    headers = {"X-Content-Type-Options": "nosniff"}
    if path.suffix.lower() != ".pdf":  # the browser's PDF viewer refuses to run in a sandbox
        headers["Content-Security-Policy"] = "sandbox"  # uploaded HTML/SVG can't run scripts here
    return FileResponse(path, headers=headers)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not can_view(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    clients.add(ws)
    await ws.send_text(json.dumps({"type": "state", "state": public_state()}))
    try:
        while True:
            await ws.receive_text()  # keep-alive; the wall never needs to send anything
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


@app.post("/api/push")
async def push(request: Request):
    """Streamed upload. Headers: X-Filename, X-From, X-Slot (optional), X-Wall-Token."""
    check_token(request)
    name = safe_name(unquote(request.headers.get("x-filename", "file")))
    sender = unquote(request.headers.get("x-from", "unknown"))[:40]
    total = int(request.headers.get("content-length") or 0)
    if total > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD // 1048576} MB")
    try:
        requested = int(request.headers.get("x-slot") or 0)
    except ValueError:
        requested = 0
    slot = pick_slot(requested)
    tid = uuid.uuid4().hex[:10]
    stored = f"{tid}_{name}"
    dest = UPLOADS / stored

    await broadcast({"type": "receiving", "id": tid, "slot": slot, "name": name,
                     "from": sender, "total": total})

    received, last = 0, 0.0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
                received += len(chunk)
                if received > MAX_UPLOAD:  # no Content-Length was sent, or it lied
                    break
                now = time.monotonic()
                if now - last >= PROGRESS_INTERVAL:
                    last = now
                    await broadcast({"type": "progress", "id": tid, "slot": slot,
                                     "received": received, "total": total})
    except ClientDisconnect:
        dest.unlink(missing_ok=True)
        await broadcast({"type": "failed", "id": tid, "slot": slot, "reason": "Sender disconnected"})
        return {"ok": False}

    if received > MAX_UPLOAD:
        dest.unlink(missing_ok=True)
        await broadcast({"type": "failed", "id": tid, "slot": slot, "reason": "File too large"})
        raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD // 1048576} MB")

    if total and received != total:
        dest.unlink(missing_ok=True)
        await broadcast({"type": "failed", "id": tid, "slot": slot, "reason": "Transfer incomplete"})
        raise HTTPException(status_code=400, detail="Transfer incomplete")

    await broadcast({"type": "progress", "id": tid, "slot": slot,
                     "received": received, "total": total or received})

    item = {"id": tid, "name": name, "from": sender, "kind": kind_of(name),
            "file": stored, "url": f"/files/{quote(stored)}",
            "size": received, "t": time.time(), "pinned": False}
    if item["kind"] == "text":
        item["text"] = dest.read_text(encoding="utf-8", errors="replace")[:20000]

    old = state["slots"].get(slot)
    state["slots"][slot] = item
    delete_upload(old)
    await broadcast({"type": "show", "id": tid, "slot": slot, "item": item})
    return {"ok": True, "slot": slot, "id": tid}


@app.post("/api/command")
async def command(request: Request):
    """JSON body: {"action": "clear"|"layout"|"pin"|"unpin"|"blackout", ...}"""
    check_token(request)
    body = await request.json()
    action = body.get("action")
    slot = int(body.get("slot") or 0)

    if action == "clear":
        targets = [slot] if slot else [i for i, it in state["slots"].items() if not it.get("pinned")]
        for i in targets:
            delete_upload(state["slots"].pop(i, None))
    elif action == "clear_all":
        for i in list(state["slots"]):
            delete_upload(state["slots"].pop(i, None))
    elif action == "layout":
        layout = body.get("layout")
        if layout not in LAYOUTS:
            raise HTTPException(status_code=400, detail=f"Layout must be one of {list(LAYOUTS)}")
        state["layout"] = layout
    elif action in ("pin", "unpin"):
        if slot in state["slots"]:
            state["slots"][slot]["pinned"] = action == "pin"
    elif action == "blackout":
        value = body.get("on")
        state["blackout"] = (not state["blackout"]) if value is None else bool(value)
    else:
        raise HTTPException(status_code=400, detail="Unknown action")

    await broadcast({"type": "state", "state": public_state()})
    return {"ok": True, "state": public_state()}


@app.get("/api/state")
async def get_state(request: Request):
    if not can_view(request):
        raise HTTPException(status_code=401, detail="Wrong or missing token")
    return public_state()


def lan_ip() -> str:
    """Best guess at this machine's address on the local network."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the outgoing interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    host, port = CONFIG.get("host", "0.0.0.0"), int(CONFIG.get("port", 8765))
    ip = lan_ip()
    print("Wall server is running.\n")
    print(f"  Wall display (open on the TV):  http://localhost:{port}/")
    print(f"  Address for WallClient:         http://{ip}:{port}")
    print(f"  Phone control page:             http://{ip}:{port}/control")
    if TOKEN_GENERATED:
        print(f"\n  New token (saved in config.json): {TOKEN}")
        print("  Put the same token into WallClient's Settings.")
    print("\nPress Ctrl+C to stop.")
    uvicorn.run(app, host=host, port=port, log_level="warning")
