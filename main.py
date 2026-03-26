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
import docker
from datetime import datetime

app = FastAPI(title="Server Monitor", version="1.0.0", docs_url=None, redoc_url=None)

# Docker client — lazy init
_docker_client = None

def get_docker():
    """Docker client'ı lazy olarak başlat."""
    global _docker_client
    if _docker_client is None:
        try:
            _docker_client = docker.from_env()
            _docker_client.ping()  # bağlantıyı test et
        except Exception:
            _docker_client = None
    return _docker_client

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

# Container friendly names — Coolify container ID → okunabilir isim
CONTAINER_LABELS = {
    "web-i8w8w0g8o8kw48c4wcsc4owk": "MINIBAR",
    "backend-z400og88sk08so80ss8o4844": "EVENTFLOW",
    "app-e480kocw4s88ckc8wcsowsoc": "ROYAL CABANA",
    "app-i8ggkoowk4s8okc4gso8kg4w": "AI HABERLERI",
    "worker-i8ggkoowk4s8okc4gso8kg4w": "AI HABERLERI WORKER",
}


def _get_friendly_name(container_name: str) -> str:
    """Container adından friendly name döndür."""
    for key, label in CONTAINER_LABELS.items():
        if key in container_name:
            return label
    return container_name


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


def _calc_cpu_percent(stats: dict) -> float:
    """Docker stats'tan CPU yüzdesini hesapla."""
    try:
        cpu = stats["cpu_stats"]
        pre = stats["precpu_stats"]
        delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        sys_delta = cpu["system_cpu_usage"] - pre["system_cpu_usage"]
        ncpus = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage", [1]))
        if sys_delta > 0 and delta > 0:
            return round((delta / sys_delta) * ncpus * 100, 2)
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return 0.0


@app.get("/containers", dependencies=[Depends(verify_api_key)])
def containers():
    """Docker container stats — docker stats benzeri çıktı."""
    if not get_docker():
        return {"timestamp": datetime.utcnow().isoformat(), "count": 0, "containers": []}

    result = []
    for c in get_docker().containers.list(all=True):
        info = {
            "id": c.short_id,
            "name": c.name,
            "label": _get_friendly_name(c.name),
            "image": c.image.tags[0] if c.image.tags else c.image.short_id,
            "status": c.status,
            "state": c.attrs.get("State", {}).get("Health", {}).get("Status", c.status),
        }

        if c.status == "running":
            try:
                stats = c.stats(stream=False)
                mem = stats.get("memory_stats", {})
                mem_usage = mem.get("usage", 0)
                mem_limit = mem.get("limit", 1)
                net = stats.get("networks", {})
                net_rx = sum(v.get("rx_bytes", 0) for v in net.values())
                net_tx = sum(v.get("tx_bytes", 0) for v in net.values())

                info.update({
                    "cpu_percent": _calc_cpu_percent(stats),
                    "mem_usage_mb": round(mem_usage / (1024**2), 1),
                    "mem_limit_mb": round(mem_limit / (1024**2), 1),
                    "mem_percent": round((mem_usage / mem_limit) * 100, 1) if mem_limit else 0,
                    "net_rx": net_rx,
                    "net_tx": net_tx,
                })
            except Exception:
                info.update({"cpu_percent": 0, "mem_usage_mb": 0, "mem_limit_mb": 0, "mem_percent": 0, "net_rx": 0, "net_tx": 0})
        else:
            info.update({"cpu_percent": 0, "mem_usage_mb": 0, "mem_limit_mb": 0, "mem_percent": 0, "net_rx": 0, "net_tx": 0})

        result.append(info)

    return {"timestamp": datetime.utcnow().isoformat(), "count": len(result), "containers": result}


@app.get("/containers/{container_id}/logs", dependencies=[Depends(verify_api_key)])
def container_logs(container_id: str, tail: int = 100):
    """Container loglarını döndür. tail parametresi ile son N satır."""
    if not get_docker():
        raise HTTPException(status_code=503, detail="Docker not available")

    # container_id veya name ile bul
    try:
        container = get_docker().containers.get(container_id)
    except docker.errors.NotFound:
        # İsimle ara
        found = None
        for c in get_docker().containers.list(all=True):
            if container_id in c.name or container_id == c.short_id:
                found = c
                break
        if not found:
            raise HTTPException(status_code=404, detail="Container not found")
        container = found

    try:
        logs = container.logs(tail=min(tail, 500), timestamps=True).decode("utf-8", errors="replace")
        lines = logs.strip().split("\n") if logs.strip() else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "container_id": container.short_id,
        "name": container.name,
        "label": _get_friendly_name(container.name),
        "lines": lines,
        "count": len(lines),
    }
