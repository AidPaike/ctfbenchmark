from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from droplet.database import init_db, migrate_jsonl_to_sqlite
from droplet.events import DEFAULT_EVENT_LOG
from droplet.logging_config import setup_logging
from droplet.manager import DropletManager


# [1] Module-level singleton: one DropletManager instance shared across all requests
# 模块级单例：一个 DropletManager 实例被所有请求共享
logger = logging.getLogger("droplet.app")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

ADMIN_TOKEN = "droplet_dev_admin"
manager = DropletManager(
    dataset_root=Path(os.getenv("DROPLET_DATASET_ROOT", _PROJECT_ROOT / "datasets")),
    work_root=Path(os.getenv("DROPLET_WORK_ROOT", _PROJECT_ROOT / "data" / "work")),
    public_host=os.getenv("DROPLET_PUBLIC_HOST", "127.0.0.1"),
)


# [2] Simple bearer token check; accepts the hardcoded admin token OR any token starting with "droplet_"
# 简单的 bearer token 检查；接受硬编码的管理员 token 或任何以 "droplet_" 开头的 token
def require_auth(authorization: Annotated[str | None, Header()] = None) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token != ADMIN_TOKEN and not token.startswith("droplet_"):
        raise HTTPException(status_code=401, detail="Invalid bearer token")


# [3] Parse environment variable as boolean: "0", "false", "no", "off" are all falsy
# 将环境变量解析为布尔值："0"、"false"、"no"、"off" 都被视为假
def _env_enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _prestart_ids() -> list[str] | None:
    raw = os.getenv("DROPLET_PRESTART_IDS", "").strip()
    if not raw:
        return None
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


app = FastAPI(title="Droplet", version="0.6.0")

# [4] CORS restricted to the frontend origin only; not open to arbitrary domains
# CORS 仅限前端来源；不对任意域名开放
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:10349", "http://127.0.0.1:10349"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# [5] Request logging middleware: captures method, path, status, and duration
# 请求日志中间件：记录方法、路径、状态和耗时
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)
    logger.info(
        f"{request.method} {request.url.path} → {response.status_code} ({duration_ms}ms)",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


# [5] FastAPI lifecycle hooks: load challenges on startup, graceful shutdown on exit
# FastAPI 生命周期钩子：启动时加载题目，退出时优雅关闭
@app.on_event("startup")
def startup() -> None:
    setup_logging()
    init_db()
    migrate_jsonl_to_sqlite(DEFAULT_EVENT_LOG)
    manager.load_tasks()
    logger.info("Droplet startup complete", extra={"challenge_count": len(manager.challenges)})
    app.state.prestart = None
    if _env_enabled("DROPLET_PRESTART_CHALLENGES", default=True):
        import threading

        def _deferred_start() -> None:
            prestart_ids = _prestart_ids()
            if _env_enabled("DROPLET_PREFETCH_IMAGES", default=True):
                logger.info("Pre-pulling Docker images before starting challenges...")
                manager.prefetch_images(prestart_ids)
                # Wait for prefetch to finish so the progress bar is visible in the frontend
                import time
                while manager.prefetch_progress().get("running"):
                    time.sleep(1)
                logger.info("Image prefetch complete, starting challenges...")
            app.state.prestart = manager.start_all(prestart_ids)

        threading.Thread(target=_deferred_start, daemon=True).start()


@app.on_event("shutdown")
def shutdown() -> None:
    manager.shutdown()


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "challenges": len(manager.challenges),
        "running": sum(1 for c in manager.challenges.values() if c.status.value == "running"),
        "starting": sum(1 for c in manager.challenges.values() if c.status.value == "starting"),
        "solved": sum(1 for c in manager.challenges.values() if c.solved),
        "prestart": getattr(app.state, "prestart", None),
    }


@app.get("/api/challenges")
def list_challenges(_: None = Depends(require_auth)) -> list[dict]:
    return manager.list_challenges()


@app.get("/api/datasets")
def list_datasets(_: None = Depends(require_auth)) -> dict[str, int]:
    return manager.dataset_totals()


@app.get("/api/challenges/{challenge_id}")
def get_challenge(challenge_id: str, _: None = Depends(require_auth)) -> dict:
    try:
        return manager.get_challenge(challenge_id).public()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/events")
def list_events(
    challenge_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    _: None = Depends(require_auth),
) -> list[dict]:
    return manager.events.list(challenge_id=challenge_id, limit=limit)


@app.get("/api/challenges/{challenge_id}/events")
def list_challenge_events(
    challenge_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    _: None = Depends(require_auth),
) -> list[dict]:
    try:
        manager.get_challenge(challenge_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return manager.events.list(challenge_id=challenge_id, limit=limit)


@app.post("/api/challenges/{challenge_id}/events/clear")
def clear_challenge_events(challenge_id: str, _: None = Depends(require_auth)) -> dict:
    try:
        manager.get_challenge(challenge_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return manager.events.clear(challenge_id=challenge_id)


@app.post("/api/events/clear")
def clear_events(payload: dict | None = None, _: None = Depends(require_auth)) -> dict:
    challenge_id = (
        str(payload.get("challenge_id")) if payload and payload.get("challenge_id") else None
    )
    if challenge_id is not None:
        try:
            manager.get_challenge(challenge_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return manager.events.clear(challenge_id=challenge_id)


@app.post("/api/challenges/{challenge_id}/events")
def append_challenge_event(
    challenge_id: str, payload: dict, _: None = Depends(require_auth)
) -> dict:
    try:
        manager.get_challenge(challenge_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    event_type = str(payload.get("event_type") or "agent_event")
    message = str(payload.get("message") or event_type)
    level = str(payload.get("level") or "info")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return manager.events.record(
        event_type,
        message,
        challenge_id=challenge_id,
        level=level,
        data=data,
    )


@app.post("/api/challenges/prefetch")
def prefetch_images(payload: dict | None = None, _: None = Depends(require_auth)) -> dict:
    challenge_ids = payload.get("challenge_ids") if payload else None
    if challenge_ids is not None:
        challenge_ids = [str(item).lower() for item in challenge_ids]
    return manager.prefetch_images(challenge_ids)


@app.get("/api/challenges/prefetch/progress")
def prefetch_progress(_: None = Depends(require_auth)) -> dict:
    return manager.prefetch_progress()


@app.post("/api/challenges/start-all")
def start_all_challenges(payload: dict | None = None, _: None = Depends(require_auth)) -> dict:
    challenge_ids = payload.get("challenge_ids") if payload else None
    if challenge_ids is not None:
        challenge_ids = [str(item).lower() for item in challenge_ids]
    return manager.start_all(challenge_ids)


@app.post("/api/challenges/stop-all")
def stop_all_challenges(_: None = Depends(require_auth)) -> dict:
    return manager.stop_all()


# [6] All native API routes follow the same pattern: try/except -> HTTPException conversion
# 所有原生 API 路由遵循相同的模式：try/except -> HTTPException 转换
@app.post("/api/challenges/{challenge_id}/start")
def start_challenge(challenge_id: str, _: None = Depends(require_auth)) -> dict:
    try:
        result = manager.start_challenge(challenge_id).public()
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/challenges/{challenge_id}/stop")
def stop_challenge(challenge_id: str, _: None = Depends(require_auth)) -> dict:
    try:
        result = manager.stop_challenge(challenge_id).public()
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/challenges/reset-all")
def reset_all_challenges(_: None = Depends(require_auth)) -> dict:
    try:
        return manager.reset_all_challenges()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/challenges/{challenge_id}/reset")
def reset_challenge(challenge_id: str, _: None = Depends(require_auth)) -> dict:
    try:
        result = manager.reset_challenge(challenge_id).public()
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/challenges/{challenge_id}/submit")
def submit(challenge_id: str, payload: dict, _: None = Depends(require_auth)) -> dict:
    try:
        return manager.submit(challenge_id, payload["answer"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/challenges/{challenge_id}/hint")
def hint(challenge_id: str, _: None = Depends(require_auth)) -> dict:
    try:
        return manager.hint(challenge_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/challenges/{challenge_id}/submissions")
def list_submissions(
    challenge_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    _: None = Depends(require_auth),
) -> list[dict]:
    try:
        manager.get_challenge(challenge_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return manager.get_submissions(challenge_id, limit=limit)


@app.get("/api/stats")
def stats(_: None = Depends(require_auth)) -> dict:
    return manager.stats()


# ------------------------------------------------------------------
# [7] Compatibility routes (Tencent-style API)
# These translate between Droplet's native model and Tencent's expected field names/structures
# 兼容路由（腾讯风格 API）
# 这些路由在 Droplet 原生模型和腾讯预期的字段名/结构之间进行转换
# ------------------------------------------------------------------


@app.get("/api/v1/challenges")
def compat_challenges(_: None = Depends(require_auth)) -> dict:
    challenges = manager.list_challenges()
    return {
        "current_stage": "competition",
        "challenges": [
            {
                "challenge_code": c["id"],
                "difficulty": c["difficulty"],
                "points": {"easy": 200, "medium": 300, "hard": 500}.get(c["difficulty"], 100),
                "hint_viewed": c["hint_viewed"],
                "solved": c["solved"],
                "status": c["status"],
                "target_url": c["target_url"],
                "error_message": c["error_message"],
                "target_info": {
                    "ip": manager.public_host,
                    "port": c["ports"],
                },
            }
            for c in challenges
        ],
    }


@app.get("/api/v1/hint/{challenge_code}")
def compat_hint(challenge_code: str, _: None = Depends(require_auth)) -> dict:
    try:
        challenge = manager.get_challenge(challenge_code.lower())
        first_use = not challenge.hint_viewed
        result = manager.hint(challenge.id)
        return {
            "hint_content": result["content"],
            "penalty_points": abs(int(result["penalty"] * 1000)),
            "first_use": first_use,
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/answer")
def compat_answer(payload: dict, _: None = Depends(require_auth)) -> dict:
    try:
        challenge = manager.get_challenge(payload["challenge_code"].lower())
        result = manager.submit(challenge.id, payload["answer"])
        return {
            "correct": False,
            "judged": False,
            "accepted": bool(result["accepted"]),
            "earned_points": 0,
            "is_solved": challenge.solved,
            "message": result["message"],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
