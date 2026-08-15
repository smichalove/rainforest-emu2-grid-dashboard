"""Background sync task that pulls data files from the Raspberry Pi Collector to 520c."""

import os
import time
import subprocess
import logging
from pathlib import Path
from typing import Optional

from .config import (
    DATA_DIR,
    PI_COLLECTOR_HOST,
    PI_COLLECTOR_USER,
    PI_COLLECTOR_PATH
)

logger = logging.getLogger("rainforest.sync")


def sync_from_pi(
    host: str = PI_COLLECTOR_HOST,
    user: str = PI_COLLECTOR_USER,
    remote_path: str = PI_COLLECTOR_PATH,
    dest_dir: Path = DATA_DIR
) -> bool:
    """Uses rsync over SSH to synchronize telemetry files from the active Pi collector."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # Target files to synchronize
    include_patterns = [
        "--include=grid_history.db*",
        "--include=gemini_summary.json",
        "--include=*.csv",
        "--exclude=*"
    ]

    cmd = [
        "rsync",
        "-avz",
        "-e", "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=4",
        *include_patterns,
        f"{user}@{host}:{remote_path}/",
        str(dest_dir) + "/"
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            logger.info("Successfully synced telemetry files from Pi.")
            return True
        else:
            logger.warning(f"Rsync warning: {res.stderr.strip() or res.stdout.strip()}")
            return False
    except subprocess.TimeoutExpired:
        logger.warning(f"Sync timed out connecting to {user}@{host}")
        return False
    except Exception as e:
        logger.error(f"Error during sync: {e}")
        return False


async def run_sync_loop(interval_secs: int = 15):
    """Asynchronous background loop that runs continuously within FastAPI lifespan."""
    import asyncio
    logger.info(f"Starting background sync loop targeting {PI_COLLECTOR_HOST} (every {interval_secs}s)...")
    while True:
        try:
            await asyncio.to_thread(sync_from_pi)
        except Exception as e:
            logger.error(f"Sync loop error: {e}")
        await asyncio.sleep(interval_secs)
