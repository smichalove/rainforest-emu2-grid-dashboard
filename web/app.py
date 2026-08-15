"""FastAPI Application for Rainforest EMU-2 Grid & Solar Web Kiosk."""

import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import BASE_DIR, DATA_DIR, WEB_HOST, WEB_PORT
from .db_reader import get_latest_reading, get_24h_history, get_ai_summary
from .sensors import fetch_purpleair, fetch_awair, fetch_weather
from .spectral_engine import compute_multi_spectrum
from .sync_service import run_sync_loop, sync_from_pi

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("rainforest.web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup and background tasks."""
    logger.info("Initializing Rainforest Web Kiosk...")
    await asyncio.to_thread(sync_from_pi)
    sync_task = asyncio.create_task(run_sync_loop(interval_secs=15))
    yield
    sync_task.cancel()
    logger.info("Rainforest Web Kiosk shutdown.")


app = FastAPI(
    title="Rainforest EMU-2 Grid & Solar Kiosk",
    description="Real-time web-based energy monitor & smart meter kiosk",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = BASE_DIR / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def get_dashboard():
    """Serves the primary Fullscreen Kiosk Dashboard."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse({"status": "Dashboard frontend initializing..."}, status_code=200)


@app.get("/api/telemetry/live")
async def get_live_telemetry():
    """Aggregates all instantaneous real-time metrics across Grid, Solar, Battery, and Air Sensors."""
    latest_grid = get_latest_reading()
    history_24h = get_24h_history(cutoff_hours=1)

    se_latest = history_24h["solaredge"]["values"][-1] if history_24h["solaredge"]["values"] else 0.160
    ch_latest = history_24h["chilicon"]["values"][-1] if history_24h["chilicon"]["values"] else 1.240
    total_solar_kw = round(se_latest + ch_latest, 3)

    bat_kw = history_24h["battery"]["power_kw"][-1] if history_24h["battery"]["power_kw"] else 0.0
    bat_soc = history_24h["battery"]["soc_percent"][-1] if history_24h["battery"]["soc_percent"] else 50.0

    net_grid_kw = round(latest_grid["kw"], 3)
    house_load_kw = max(0.2, round(net_grid_kw + total_solar_kw + bat_kw, 3))

    purpleair = fetch_purpleair()
    awair = fetch_awair()
    weather = fetch_weather()

    return {
        "grid": {
            "net_kw": net_grid_kw,
            "house_load_kw": house_load_kw,
            "timestamp": latest_grid["timestamp"],
            "is_stale": latest_grid["is_stale"],
            "status_text": f"{-net_grid_kw:.3f} kW | Solar Export" if net_grid_kw < 0 else f"{net_grid_kw:.3f} kW | Grid Import"
        },
        "solar": {
            "total_kw": total_solar_kw,
            "solaredge_kw": se_latest,
            "chilicon_kw": ch_latest
        },
        "battery": {
            "power_kw": bat_kw,
            "soc_percent": bat_soc,
            "status": "Discharging" if bat_kw > 0.1 else ("Charging" if bat_kw < -0.1 else "Idle")
        },
        "air_quality": {
            "purpleair": purpleair,
            "awair": awair
        },
        "weather": weather
    }


@app.get("/api/telemetry/history")
async def get_history(hours: int = 24):
    """Returns the 24-hour time series dataset."""
    return get_24h_history(cutoff_hours=hours)


@app.get("/api/telemetry/history14d")
async def get_history_14d():
    """Returns the 14-day overview time series dataset for Slide 2."""
    return get_24h_history(cutoff_hours=336)


@app.get("/api/telemetry/spectrum")
async def get_spectrum():
    """Computes Discrete Fourier Transform (DFT) spectrum for Slide 3."""
    history = get_24h_history(cutoff_hours=24)
    return compute_multi_spectrum(history)


@app.get("/api/summary")
async def get_summary(slide: int = Query(default=1)):
    """Returns the AI narrative watermark summary for the specified slide."""
    return get_ai_summary(slide=slide)


@app.websocket("/ws/telemetry")
async def websocket_telemetry_stream(websocket: WebSocket):
    """Streams live sensor updates to connected kiosk display clients."""
    await websocket.accept()
    try:
        while True:
            live_data = await get_live_telemetry()
            await websocket.send_json(live_data)
            await asyncio.sleep(5)
    except (WebSocketDisconnect, Exception):
        pass
