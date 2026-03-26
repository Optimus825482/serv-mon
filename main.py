"""
Coolify Server Monitor API
Lightweight system metrics endpoint for remote monitoring.
"""
import os
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
import psutil
import time
import platform
from datetime import datetime

app = FastAPI(title="Server Monitor", version="1.0.0", docs_url=None, redoc_url=None)

# CORS — dashboard origin'ini .env'den al, yoksa wildcard
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# API Key koruması — Coolify'da env olarak set edilecek
API_KEY = os.getenv("MONITOR_API_KEY", "")

START_TIME = time.time()


async def verify_api_key(request: Request):
    """API key varsa kontrol et, yoksa açık bırak."""
    if not API_KEY:
        return
    key = request.headers.get("X-API-Key") or request.query_params.get("key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/")
def root():
    """Root path'i metrics'e yönlendir."""
    return RedirectResponse(url="/health")


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/metrics", dependencies=[Depends(verify_api_key)])
def metrics():
    cpu_freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    load = psutil.getloadavg()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": int(time.time() - START_TIME),
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": {
            "percent": psutil.cpu_percent(interval=0.5),
            "per_core": psutil.cpu_percent(interval=0, percpu=True),
            "cores_physical": psutil.cpu_count(logical=False),
            "cores_logical": psutil.cpu_count(logical=True),
            "freq_mhz": round(cpu_freq.current, 1) if cpu_freq else None,
        },
        "memory": {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": disk.percent,
        },
        "network": {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        },
        "load_average": {
            "1min": round(load[0], 2),
            "5min": round(load[1], 2),
            "15min": round(load[2], 2),
        },
    }
