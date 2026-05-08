import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from aibcr_client import build_roads, fetch_results


OUT_DIR = Path(os.environ.get("BAC_OUT_DIR", "bac_capture"))
EVENTS_FILE = OUT_DIR / "events.jsonl"
ROAD_FILE = OUT_DIR / "road_store.json"

app = FastAPI(title="Baccarat Capture API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

collector_process: asyncio.subprocess.Process | None = None


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def read_events(limit: int) -> list[dict[str, Any]]:
    if not EVENTS_FILE.exists():
        return []

    lines = EVENTS_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            events.append(json.loads(line))
        except Exception:
            pass
    return events


def latest_result(table_id: str | None = None) -> dict[str, Any] | None:
    if not EVENTS_FILE.exists():
        return None

    lines = EVENTS_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except Exception:
            continue

        if event.get("kind") != "game" or event.get("winner") == -1:
            continue
        if table_id and str(event.get("tableID")) != str(table_id):
            continue
        return event
    return None


@app.on_event("startup")
async def maybe_start_collector() -> None:
    global collector_process
    OUT_DIR.mkdir(exist_ok=True)

    if os.environ.get("RUN_COLLECTOR", "1") != "1":
        return

    table = os.environ.get("BAC_TABLE", "1008")
    args = ["python", "-u", "bac_auto_capture.py", "--table", table, "--headless"]

    collector_process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async def pump_logs() -> None:
        assert collector_process and collector_process.stdout
        while True:
            line = await collector_process.stdout.readline()
            if not line:
                break
            print("[collector]", line.decode("utf-8", errors="replace").rstrip(), flush=True)

    asyncio.create_task(pump_logs())


@app.on_event("shutdown")
async def stop_collector() -> None:
    if collector_process and collector_process.returncode is None:
        collector_process.terminate()


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "baccarat-capture-api",
        "endpoints": ["/health", "/road", "/road/{table_id}", "/latest", "/events"],
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "collector": bool(collector_process and collector_process.returncode is None),
        "eventsFile": str(EVENTS_FILE),
        "roadFile": str(ROAD_FILE),
    }


@app.get("/road")
async def road() -> dict[str, Any]:
    return read_json(ROAD_FILE, {})


@app.get("/road/{table_id}")
async def road_one(table_id: str) -> dict[str, Any]:
    store = read_json(ROAD_FILE, {})
    return store.get(str(table_id), {})


@app.get("/latest")
async def latest(table_id: str | None = Query(default=None)) -> dict[str, Any]:
    return latest_result(table_id) or {}


@app.get("/events")
async def events(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict[str, Any]]:
    return read_events(limit)


@app.get("/aibcr/raw")
async def aibcr_raw(table: str = Query(default="all")) -> dict[str, Any]:
    try:
        return fetch_results(table=table)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/aibcr/roads")
async def aibcr_roads(
    game_code: str | None = Query(default=None),
    table_id: str | None = Query(default=None),
    table: str = Query(default="all"),
) -> dict[str, Any]:
    try:
        return {
            "code": 200,
            "data": build_roads(game_code=game_code, table_id=table_id, table=table),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
