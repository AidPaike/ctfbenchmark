from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from droplet.datasets import DatasetLoader, read_env_flag
from droplet.database import (
    ChallengeProgress,
    Submission,
    get_current_session_id,
    get_engine,
    increment_session_id,
)
from droplet.events import EventStore
from droplet.models import Challenge, ChallengeStatus, now
from sqlmodel import Session, desc, select

logger = logging.getLogger("droplet.manager")


# [1] Proxy constants cover both upper and lower case because different tools (curl, pip, Docker) respect different conventions
# 代理常量同时覆盖大写和小写，因为不同工具（curl、pip、Docker）遵循不同的命名约定
PROXY_URL_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
NO_PROXY_KEYS = ("NO_PROXY", "no_proxy")
DEFAULT_DOCKER_NO_PROXY = "127.0.0.1,localhost,::1,host.docker.internal,pypi.tuna.tsinghua.edu.cn"
DEFAULT_READY_TIMEOUT_SECONDS = 90
DEFAULT_COMPOSE_TIMEOUT_SECONDS = 300
DEFAULT_MAX_CONCURRENT_ENVIRONMENTS = 2


class DropletManager:
    """
    Manages the full lifecycle of a CTF challenge set: discovery, start/stop,
    health checks, scoring, and cleanup.  Each challenge template lives under
    ``dataset_root``; runtime copies are placed under ``work_root`` so the
    originals are never mutated (important for proxy injection and port
    rewriting).
    """

    def __init__(
        self,
        dataset_root: Path = Path("datasets/demo-xbow"),
        work_root: Path = Path("data/work"),
        public_host: str = "127.0.0.1",
        compose_prefix: str = "droplet",
        dataset_loader: DatasetLoader | None = None,
        event_store: EventStore | None = None,
    ) -> None:
        self.dataset_root = dataset_root
        self.work_root = work_root
        self.public_host = public_host
        self.compose_prefix = compose_prefix
        self.challenges: dict[str, Challenge] = {}

        self.dataset_loader = dataset_loader or DatasetLoader()
        self.events = event_store or EventStore()

        self.docker_proxy = _normalise_proxy(os.getenv("DROPLET_DOCKER_PROXY"))
        self.docker_no_proxy = _normalise_no_proxy(
            os.getenv("DROPLET_DOCKER_NO_PROXY") or os.getenv("NO_PROXY"),
            DEFAULT_DOCKER_NO_PROXY,
        )
        self.ready_timeout_seconds = int(
            os.getenv("DROPLET_TARGET_READY_TIMEOUT", str(DEFAULT_READY_TIMEOUT_SECONDS))
        )
        self.compose_timeout_seconds = int(
            os.getenv("DROPLET_COMPOSE_TIMEOUT_SECONDS", str(DEFAULT_COMPOSE_TIMEOUT_SECONDS))
        )
        self.max_concurrent = int(
            os.getenv("DROPLET_MAX_CONCURRENT_ENVIRONMENTS", str(DEFAULT_MAX_CONCURRENT_ENVIRONMENTS))
        )
        self._start_lock = threading.Lock()

        self.work_root.mkdir(parents=True, exist_ok=True)
        # [4] Cleanup leftover directories from a previous unclean shutdown to avoid disk leaks or zombie Docker projects
        # 清理上次异常退出残留的目录，避免磁盘泄漏或僵尸 Docker 项目
        self._cleanup_orphan_work_dirs()
        self._cleanup_legacy_work_dirs()
        # [5] Start a background daemon thread to detect containers killed externally
        # 启动后台守护线程来检测被外部终止的容器
        self._start_watchdog()

    # ------------------------------------------------------------------
    # Public challenge interface
    # ------------------------------------------------------------------

    # [6] Delegates discovery to the injected DatasetLoader; records an event for observability
    # 将发现委托给注入的 DatasetLoader；记录事件以便可观测性
    def load_tasks(self) -> None:
        logger.info(f"Loading challenges from {self.dataset_root}")
        self.challenges = self.dataset_loader.load(
            self.dataset_root,
            read_flag=read_env_flag,
            infer_expose=self._infer_expose,
        )
        logger.info(f"Loaded {len(self.challenges)} challenges")
        self._restore_progress()
        logger.info(f"Restored progress for {sum(1 for c in self.challenges.values() if c.solved)} solved challenges")
        self.events.record(
            "challenges_loaded",
            "题目元数据已加载",
            data={"count": len(self.challenges), "dataset_root": str(self.dataset_root)},
        )

    def list_challenges(self) -> list[dict[str, Any]]:
        return [c.public() for c in self.challenges.values()]

    def get_challenge(self, challenge_id: str) -> Challenge:
        if challenge_id not in self.challenges:
            raise KeyError("Challenge not found")
        return self.challenges[challenge_id]

    # [7] Asynchronous start: validates limit, marks starting, then spawns a background thread
    # 异步启动：验证限制、标记为启动中，然后启动后台线程
    def start_challenge(self, challenge_id: str) -> Challenge:
        challenge = self.get_challenge(challenge_id)

        with self._start_lock:
            if challenge.status in (ChallengeStatus.starting, ChallengeStatus.stopping):
                return challenge

            if challenge.status == ChallengeStatus.running:
                return challenge

            active_count = self._count_active_challenges()
            if active_count >= self.max_concurrent:
                logger.warning(
                    f"Concurrent limit reached ({active_count}/{self.max_concurrent}), "
                    f"cannot start {challenge_id}",
                    extra={"challenge_id": challenge_id},
                )
                raise RuntimeError(
                    f"Maximum concurrent environments ({self.max_concurrent}) reached. "
                    f"Please stop another environment first."
                )

            challenge.status = ChallengeStatus.starting
            challenge.error_message = None

        logger.info(f"Starting challenge {challenge_id}", extra={"challenge_id": challenge_id})
        self.events.record(
            "challenge_start_requested",
            "请求启动题目环境",
            challenge_id=challenge.id,
            data={"status": challenge.status.value},
        )

        thread = threading.Thread(
            target=self._do_start_challenge,
            args=(challenge_id,),
            daemon=True,
        )
        thread.start()

        return challenge

    def _count_active_challenges(self) -> int:
        return sum(
            1
            for c in self.challenges.values()
            if c.status in (ChallengeStatus.running, ChallengeStatus.starting, ChallengeStatus.stopping)
        )

    # [8] Background worker: performs the actual Docker Compose lifecycle
    # 后台工作线程：执行实际的 Docker Compose 生命周期
    def _do_start_challenge(self, challenge_id: str) -> None:
        challenge = self.get_challenge(challenge_id)

        if challenge.status == ChallengeStatus.running:
            self._stop_compose(challenge)

        work_dir = (self.work_root / "challenges" / challenge_id).resolve()
        if work_dir.exists():
            shutil.rmtree(work_dir)

        challenge.target_url = None
        challenge.ports = []
        challenge.work_dir = None
        challenge.compose_project = None
        challenge.error_message = None
        challenge.started_at = None
        challenge.finished_at = None

        try:
            result = self._start_compose(challenge, work_dir)

            if challenge.status != ChallengeStatus.starting:
                self._stop_compose(challenge)
                return

            challenge.work_dir = result["work_dir"]
            challenge.compose_project = result["project"]
            challenge.target_url = result["target_url"]
            challenge.ports = result["ports"]
            challenge.started_at = now()
            logger.info(
                f"Challenge {challenge_id} started on {challenge.target_url}",
                extra={"challenge_id": challenge_id, "target_url": challenge.target_url},
            )
            self.events.record(
                "challenge_started",
                "题目环境启动完成",
                challenge_id=challenge.id,
                data={"target_url": challenge.target_url, "ports": challenge.ports},
            )
            challenge.status = ChallengeStatus.running
        except Exception as exc:
            logger.error(
                f"Challenge {challenge_id} failed to start: {exc}",
                extra={"challenge_id": challenge_id},
                exc_info=True,
            )
            if challenge.status == ChallengeStatus.starting:
                challenge.status = ChallengeStatus.error
                challenge.error_message = str(exc)
                self.events.record(
                    "challenge_start_failed",
                    "题目环境启动失败",
                    challenge_id=challenge.id,
                    level="error",
                    data={"error": str(exc)},
                )
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)


    # [8] Batch start: skip already-running and explicitly judged-solved challenges; collect per-challenge errors
    # 批量启动：跳过已在运行和显式判题通过的题目；收集每个题目的错误
    def start_all(self, challenge_ids: list[str] | None = None) -> dict[str, Any]:
        selected = challenge_ids or list(self.challenges)
        started: list[str] = []
        already_running: list[str] = []
        skipped_limit: list[str] = []
        errors: dict[str, str] = {}

        for challenge_id in selected:
            try:
                challenge = self.get_challenge(challenge_id)
                if challenge.status == ChallengeStatus.running:
                    already_running.append(challenge.id)
                    continue
                if challenge.status == ChallengeStatus.solved:
                    continue
                self.start_challenge(challenge.id)
                started.append(challenge.id)
            except RuntimeError as exc:
                if "Maximum concurrent" in str(exc):
                    skipped_limit.append(challenge_id)
                else:
                    errors[challenge_id] = str(exc)
            except Exception as exc:
                errors[challenge_id] = str(exc)

        return {
            "total": len(selected),
            "started": started,
            "already_running": already_running,
            "skipped_limit": skipped_limit,
            "errors": errors,
            "running": sum(1 for c in self.challenges.values() if c.status == ChallengeStatus.running),
        }

    def stop_all(self) -> dict[str, Any]:
        stopped: list[str] = []
        errors: dict[str, str] = {}
        for challenge in list(self.challenges.values()):
            if challenge.status not in (ChallengeStatus.running, ChallengeStatus.starting):
                continue
            try:
                self.stop_challenge(challenge.id)
                stopped.append(challenge.id)
            except Exception as exc:
                errors[challenge.id] = str(exc)
        return {"stopped": stopped, "errors": errors}

    def stop_challenge(self, challenge_id: str) -> Challenge:
        challenge = self.get_challenge(challenge_id)
        with self._start_lock:
            if challenge.status == ChallengeStatus.stopping:
                return challenge
            if challenge.status not in (ChallengeStatus.running, ChallengeStatus.starting):
                return challenge
            challenge.status = ChallengeStatus.stopping

        logger.info(f"Stopping challenge {challenge_id}", extra={"challenge_id": challenge_id})
        self.events.record(
            "challenge_stop_requested",
            "请求停止题目环境",
            challenge_id=challenge.id,
            data={"status": challenge.status.value},
        )

        thread = threading.Thread(
            target=self._do_stop_challenge,
            args=(challenge_id,),
            daemon=True,
        )
        thread.start()
        return challenge

    def _do_stop_challenge(self, challenge_id: str) -> None:
        challenge = self.get_challenge(challenge_id)
        self._stop_compose(challenge)
        with self._start_lock:
            if challenge.status == ChallengeStatus.stopping:
                challenge.status = ChallengeStatus.not_started
                challenge.target_url = None
                challenge.ports = []
                challenge.work_dir = None
                challenge.compose_project = None
                challenge.finished_at = now()
        logger.info(f"Challenge {challenge_id} stopped", extra={"challenge_id": challenge_id})
        self.events.record(
            "challenge_stopped",
            "题目环境已停止",
            challenge_id=challenge.id,
        )

    def reset_challenge(self, challenge_id: str) -> Challenge:
        challenge = self.get_challenge(challenge_id)
        with self._start_lock:
            if challenge.status in (ChallengeStatus.starting, ChallengeStatus.stopping):
                return challenge
            challenge.status = ChallengeStatus.starting
            challenge.error_message = None

        thread = threading.Thread(
            target=self._do_reset_challenge,
            args=(challenge_id,),
            daemon=True,
        )
        thread.start()
        return challenge

    def _do_reset_challenge(self, challenge_id: str) -> None:
        challenge = self.get_challenge(challenge_id)
        self._stop_compose(challenge)
        self._clear_progress(challenge_id)
        self._do_start_challenge(challenge_id)

    def reset_all_challenges(self) -> dict[str, Any]:
        """Increment the global session id so all progress appears reset."""
        new_session = increment_session_id()
        for c in self.challenges.values():
            c.solved = False
            c.hint_viewed = False
            c.hint_penalty = 0.0
            c.submission_count = 0
            c.score = 0.0
            if c.status == ChallengeStatus.solved:
                c.status = ChallengeStatus.not_started
        logger.info(f"All challenges reset to new session {new_session}")
        self.events.record(
            "challenges_reset_all",
            "所有题目已重置",
            data={"new_session_id": new_session},
        )
        return {
            "reset": True,
            "new_session_id": new_session,
            "total": len(self.challenges),
        }

    def get_submissions(self, challenge_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return submission history for the current session."""
        session_id = get_current_session_id()
        engine = get_engine()
        with Session(engine) as session:
            stmt = (
                select(Submission)
                .where(
                    Submission.challenge_id == challenge_id,
                    Submission.session_id == session_id,
                )
                .order_by(desc(Submission.created_at))
                .limit(limit)
            )
            results = []
            for sub in session.exec(stmt):
                results.append({
                    "id": sub.id,
                    "challenge_id": sub.challenge_id,
                    "answer": sub.answer,
                    "correct": sub.correct,
                    "score_before": sub.score_before,
                    "score_after": sub.score_after,
                    "created_at": sub.created_at.isoformat() if sub.created_at else None,
                })
            return results

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_progress(self, challenge: Challenge) -> None:
        """Write challenge submission state to DB for the current session."""
        session_id = get_current_session_id()
        engine = get_engine()
        with Session(engine) as session:
            stmt = select(ChallengeProgress).where(
                ChallengeProgress.challenge_id == challenge.id,
                ChallengeProgress.session_id == session_id,
            )
            prog = session.exec(stmt).first()
            if prog is None:
                prog = ChallengeProgress(
                    challenge_id=challenge.id,
                    session_id=session_id,
                )
                session.add(prog)
            prog.solved = challenge.solved
            prog.hint_viewed = challenge.hint_viewed
            prog.hint_penalty = challenge.hint_penalty
            prog.submission_count = challenge.submission_count
            prog.score = challenge.score
            prog.updated_at = now()
            session.commit()

    def _record_submission(
        self,
        challenge: Challenge,
        answer: str,
        correct: bool,
        score_before: float,
        score_after: float,
    ) -> None:
        session_id = get_current_session_id()
        engine = get_engine()
        with Session(engine) as session:
            sub = Submission(
                challenge_id=challenge.id,
                session_id=session_id,
                answer=answer,
                correct=correct,
                score_before=score_before,
                score_after=score_after,
            )
            session.add(sub)
            session.commit()

    def _restore_progress(self) -> None:
        """Restore submission state from DB after loading dataset."""
        session_id = get_current_session_id()
        engine = get_engine()
        with Session(engine) as session:
            stmt = select(ChallengeProgress).where(
                ChallengeProgress.session_id == session_id
            )
            for prog in session.exec(stmt):
                if prog.challenge_id not in self.challenges:
                    continue
                c = self.challenges[prog.challenge_id]
                c.solved = prog.solved
                c.hint_viewed = prog.hint_viewed
                c.hint_penalty = prog.hint_penalty
                c.submission_count = prog.submission_count
                c.score = prog.score
                if prog.solved:
                    c.status = ChallengeStatus.solved

    def _clear_progress(self, challenge_id: str) -> None:
        """Reset submission state for a single challenge in the current session."""
        session_id = get_current_session_id()
        engine = get_engine()
        with Session(engine) as session:
            stmt = select(ChallengeProgress).where(
                ChallengeProgress.challenge_id == challenge_id,
                ChallengeProgress.session_id == session_id,
            )
            prog = session.exec(stmt).first()
            if prog is not None:
                prog.solved = False
                prog.hint_viewed = False
                prog.hint_penalty = 0.0
                prog.submission_count = 0
                prog.score = 0.0
                prog.updated_at = now()
                session.add(prog)
                session.commit()
        if challenge_id in self.challenges:
            c = self.challenges[challenge_id]
            c.solved = False
            c.hint_viewed = False
            c.hint_penalty = 0.0
            c.submission_count = 0
            c.score = 0.0

    # [9] Auto-judge submission by comparing the answer against the expected flag
    # 通过将答案与期望的 Flag 比较来自动判题
    def submit(self, challenge_id: str, answer: str) -> dict[str, Any]:
        challenge = self.get_challenge(challenge_id)
        if challenge.status != ChallengeStatus.running:
            raise ValueError("Challenge is not running")

        challenge.submission_count += 1
        correct = answer.strip() == challenge.expected_flag.strip()
        score_before = 1.0 if correct else 0.0
        score_after = max(0.0, score_before + challenge.hint_penalty)

        if correct:
            challenge.solved = True
            challenge.score = score_after
            challenge.status = ChallengeStatus.solved
            challenge.finished_at = now()
            self._stop_compose(challenge)
            logger.info(
                f"Challenge {challenge_id} solved!",
                extra={"challenge_id": challenge_id, "score": score_after},
            )
        else:
            logger.info(
                f"Challenge {challenge_id} incorrect submission ({challenge.submission_count} total)",
                extra={"challenge_id": challenge_id},
            )

        self._persist_progress(challenge)
        self._record_submission(challenge, answer, correct, score_before, score_after)

        self.events.record(
            "submission_judged",
            "提交已判题",
            challenge_id=challenge.id,
            data={
                "correct": correct,
                "score_before_hint_penalty": score_before,
                "score_after_hint_penalty": score_after,
                "submission_count": challenge.submission_count,
            },
        )

        return {
            "accepted": True,
            "judged": True,
            "correct": correct,
            "score_before_hint_penalty": score_before,
            "score_after_hint_penalty": score_after,
            "submission_count": challenge.submission_count,
            "message": "Correct!" if correct else "Incorrect flag",
        }

    def hint(self, challenge_id: str) -> dict[str, Any]:
        challenge = self.get_challenge(challenge_id)
        if not challenge.hint:
            raise ValueError("Hint not available")
        challenge.hint_viewed = True
        challenge.hint_penalty -= 0.1
        self._persist_progress(challenge)
        self.events.record(
            "hint_viewed",
            "查看题目提示",
            challenge_id=challenge.id,
            data={"penalty": -0.1, "hint_penalty": challenge.hint_penalty},
        )
        return {
            "hint_id": "hint-1",
            "content": challenge.hint,
            "penalty": -0.1,
            "hint_penalty": challenge.hint_penalty,
        }

    def stats(self) -> dict[str, Any]:
        total = len(self.challenges)
        solved = sum(1 for c in self.challenges.values() if c.solved)
        running = sum(1 for c in self.challenges.values() if c.status == ChallengeStatus.running)
        starting = sum(1 for c in self.challenges.values() if c.status == ChallengeStatus.starting)
        return {
            "total_challenges": total,
            "solved": solved,
            "running": running,
            "starting": starting,
            "overall_score": _ratio(solved, total),
        }

    def shutdown(self) -> None:
        if hasattr(self, "_watchdog_stop"):
            self._watchdog_stop.set()
        thread = getattr(self, "_watchdog_thread", None)
        if thread is not None:
            thread.join(timeout=1)
        for challenge in list(self.challenges.values()):
            if challenge.status == ChallengeStatus.running:
                self._stop_compose(challenge)
                challenge.status = ChallengeStatus.not_started
                challenge.target_url = None
                challenge.ports = []
                challenge.work_dir = None
                challenge.compose_project = None

    # ------------------------------------------------------------------
    # Docker Compose lifecycle
    # ------------------------------------------------------------------

    # [10] Template-copy pattern: copy the whole tree so we can mutate without touching the git-tracked original
    # 模板复制模式：复制整个目录树，这样可以在不触碰 git 跟踪的原始文件的情况下进行修改
    def _start_compose(self, challenge: Challenge, work_dir: Path) -> dict[str, Any]:
        work_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(challenge.root, work_dir, dirs_exist_ok=True)
        compose_path = work_dir / "docker-compose.yml"
        # [11] Strip stale proxy first, then inject current proxy — prevents old addresses from leaking into the build
        # 先剥离过时代理，再注入当前代理 —— 防止旧地址泄漏到构建中
        self._strip_proxy_config(work_dir, compose_path)
        self._apply_docker_proxy(work_dir, compose_path)
        # [12] Let Docker pick host ports via "0:container_port" to eliminate the TOCTOU race.
        # 让 Docker 通过 "0:container_port" 选择主机端口，消除 TOCTOU 竞争。
        exposed = self._rewrite_ports(compose_path, challenge.expose)
        project = f"{self.compose_prefix}_{challenge.id}"
        command = ["docker", "compose", "-p", project, "-f", str(compose_path), "up", "-d"]
        if _env_enabled("DROPLET_FORCE_REBUILD"):
            command.insert(-1, "--build")
        docker_env = self._docker_environment()
        logger.debug(
            f"Docker compose up: {' '.join(command)}",
            extra={"challenge_id": challenge.id, "docker_command": " ".join(command)},
        )
        try:
            result = subprocess.run(
                command,
                cwd=str(work_dir),
                env=docker_env,
                capture_output=True,
                text=True,
                timeout=self.compose_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            subprocess.run(
                ["docker", "compose", "-p", project, "-f", str(compose_path), "down", "-v", "--remove-orphans"],
                cwd=str(work_dir), env=docker_env, check=False, capture_output=True, text=True,
            )
            raise RuntimeError(
                f"Docker Compose timed out after {self.compose_timeout_seconds}s: {' '.join(command)}"
            ) from exc
        if result.returncode != 0:
            detail = _compose_error(command, result)
            logger.error(
                f"Docker compose failed for {challenge.id}: {detail[:200]}",
                extra={"challenge_id": challenge.id, "docker_command": " ".join(command)},
            )
            subprocess.run(
                ["docker", "compose", "-p", project, "-f", str(compose_path), "down", "-v", "--remove-orphans"],
                cwd=str(work_dir), env=docker_env, check=False, capture_output=True, text=True,
            )
            raise RuntimeError(detail)

        # [12a] Resolve the actual host ports Docker bound.  This is the source of truth.
        # 解析 Docker 实际绑定主机端口。这是唯一可信来源。
        exposed = self._resolve_ports(project, exposed, docker_env)

        target_url = None
        ports: list[int] = []
        if exposed:
            endpoint = exposed[0]
            target_url = f"{endpoint['protocol']}://{self.public_host}:{endpoint['host_port']}"
            ports = [item["host_port"] for item in exposed]
            endpoints = [
                {
                    "type": item["protocol"],
                    "label": item.get("name", "target"),
                    "url": f"{item['protocol']}://{self.public_host}:{item['host_port']}",
                    "host": self.public_host,
                    "port": item["host_port"],
                    "service": item.get("service"),
                }
                for item in exposed
            ]
            # [13] Block until the service is actually reachable so callers can rely on target_url being ready
            # 阻塞直到服务实际可达，这样调用方可以确信 target_url 已就绪
            self._wait_for_endpoints(endpoints)

        return {
            "project": project,
            "work_dir": str(work_dir),
            "target_url": target_url,
            "ports": ports,
        }

    def _wait_for_endpoints(self, endpoints: list[dict[str, Any]]) -> None:
        deadline = time.monotonic() + self.ready_timeout_seconds
        last_error = "no endpoint checked"
        pending = list(endpoints)
        attempt = 0
        while pending and time.monotonic() < deadline:
            remaining = []
            for endpoint in pending:
                ok, error = _endpoint_ready(endpoint)
                if ok:
                    continue
                last_error = error
                remaining.append(endpoint)
            if not remaining:
                return
            pending = remaining
            attempt += 1
            # Exponential backoff capped at 5 seconds — fast at first for snappy
            # services, then gentler for slow-starting containers.
            delay = min(2 ** (attempt - 1) * 0.25, 5.0)
            time.sleep(delay)
        if pending:
            labels = ", ".join(str(item.get("url") or item.get("label") or item) for item in pending)
            raise RuntimeError(f"Target endpoint not ready before timeout: {labels}; last_error={last_error}")

    # [14] down -v --remove-orphans ensures volumes are also removed; work_dir is deleted afterwards
    # down -v --remove-orphans 确保卷也被删除；之后删除 work_dir
    def _stop_compose(self, challenge: Challenge) -> None:
        project = challenge.compose_project
        work_dir = challenge.work_dir
        if project:
            command = ["docker", "compose", "-p", project]
            if work_dir:
                compose_path = Path(work_dir) / "docker-compose.yml"
                if compose_path.exists():
                    command.extend(["-f", str(compose_path)])
            command.extend(["down", "-v", "--remove-orphans"])
            logger.debug(
                f"Docker compose down: {' '.join(command)}",
                extra={"challenge_id": challenge.id, "docker_command": " ".join(command)},
            )
            subprocess.run(
                command,
                cwd=work_dir or None,
                env=self._docker_environment(),
                check=False,
                capture_output=True,
                text=True,
            )
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _cleanup_orphan_work_dirs(self) -> None:
        challenges_dir = self.work_root / "challenges"
        if not challenges_dir.exists():
            return
        for entry in challenges_dir.iterdir():
            if not entry.is_dir():
                continue
            project = f"{self.compose_prefix}_{entry.name}"
            command = ["docker", "compose", "-p", project]
            compose_path = entry / "docker-compose.yml"
            if compose_path.exists():
                command.extend(["-f", str(compose_path.resolve())])
            command.extend(["down", "-v", "--remove-orphans"])
            subprocess.run(
                command,
                cwd=str(entry),
                env=self._docker_environment(),
                check=False,
                capture_output=True,
                text=True,
            )
            shutil.rmtree(entry, ignore_errors=True)

    def _cleanup_legacy_work_dirs(self) -> None:
        legacy_attempts = self.work_root / "attempts"
        if legacy_attempts.exists():
            shutil.rmtree(legacy_attempts, ignore_errors=True)

    # ------------------------------------------------------------------
    # Watchdog: detect externally stopped containers
    # ------------------------------------------------------------------

    def _start_watchdog(self) -> None:
        self._watchdog_stop = threading.Event()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(timeout=10):
            self._check_container_health()

    # [15] Watchdog: detect containers killed externally AND services that are running
    # but no longer reachable (e.g. crashed process inside container).
    # 守护线程：检测被外部杀死的容器，以及容器在运行但内部服务已崩溃的情况。
    def _check_container_health(self) -> None:
        for challenge in list(self.challenges.values()):
            if challenge.status != ChallengeStatus.running:
                continue
            if not self._is_compose_running(challenge):
                logger.warning(
                    f"Challenge {challenge.id} stopped externally (detected by watchdog)",
                    extra={"challenge_id": challenge.id},
                )
                self._stop_compose(challenge)
                challenge.status = ChallengeStatus.not_started
                challenge.target_url = None
                challenge.ports = []
                challenge.work_dir = None
                challenge.compose_project = None
                challenge.error_message = "Environment stopped externally"
                self.events.record(
                    "challenge_stopped_externally",
                    "题目环境已在平台外停止",
                    challenge_id=challenge.id,
                    level="warning",
                )
                continue

            # Container is running — also verify the endpoint is reachable.
            # 容器在运行，同时验证端口是否可达。
            if challenge.ports and challenge.target_url:
                for item in challenge.expose:
                    host_port = item.get("host_port")
                    if host_port is None:
                        continue
                    endpoint = {
                        "type": item.get("protocol", "tcp"),
                        "host": self.public_host,
                        "port": host_port,
                        "url": challenge.target_url,
                    }
                    ok, error = _endpoint_ready(endpoint)
                    if not ok:
                        logger.warning(
                            f"Challenge {challenge.id} endpoint unhealthy: {error}",
                            extra={"challenge_id": challenge.id, "error": error},
                        )
                        # Mark as error so the user knows the environment is broken
                        challenge.status = ChallengeStatus.error
                        challenge.error_message = f"Endpoint unreachable: {error}"
                        self.events.record(
                            "challenge_endpoint_unhealthy",
                            "题目环境端口不可达",
                            challenge_id=challenge.id,
                            level="warning",
                            data={"error": error, "target_url": challenge.target_url},
                        )
                        break

    def _is_compose_running(self, challenge: Challenge) -> bool:
        project = challenge.compose_project
        if not project:
            return False
        try:
            result = subprocess.run(
                ["docker", "compose", "-p", project, "ps", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=10,
                env=self._docker_environment(),
            )
            if result.returncode != 0:
                return False
            containers = _parse_compose_ps_json(result.stdout)
            return any(c.get("State") == "running" or c.get("State") == "Running" for c in containers)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Docker helpers: proxy injection / port rewriting
    # ------------------------------------------------------------------

    def _docker_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        if not self.docker_proxy:
            return env
        for key in PROXY_URL_KEYS:
            env[key] = self.docker_proxy
        if self.docker_no_proxy:
            for key in NO_PROXY_KEYS:
                env[key] = self.docker_no_proxy
        return env

    def _apply_docker_proxy(self, work_dir: Path, compose_path: Path) -> None:
        if not self.docker_proxy:
            return

        data = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
        changed = False
        for service in (data.get("services") or {}).values():
            build = service.get("build") if isinstance(service, dict) else None
            if not build:
                continue
            if isinstance(build, str):
                build = {"context": build}
                service["build"] = build
            if not isinstance(build, dict):
                continue
            build["args"] = _proxy_build_args(build.get("args"), self.docker_proxy, self.docker_no_proxy)
            changed = True
        if changed:
            compose_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def _strip_proxy_config(self, work_dir: Path, compose_path: Path) -> None:
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
        changed = False
        for service in (data.get("services") or {}).values():
            build = service.get("build") if isinstance(service, dict) else None
            if not isinstance(build, dict):
                continue
            args = _without_proxy_build_args(build.get("args"))
            if args != build.get("args"):
                changed = True
                if args:
                    build["args"] = args
                else:
                    build.pop("args", None)
        if changed:
            compose_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        for dockerfile in work_dir.rglob("Dockerfile"):
            text = dockerfile.read_text(encoding="utf-8")
            lines = [
                line
                for line in text.splitlines()
                if not _is_proxy_dockerfile_line(line)
            ]
            if lines != text.splitlines():
                dockerfile.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

    def _rewrite_ports(self, compose_path: Path, expose: list[dict[str, Any]]) -> list[dict[str, Any]]:
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
        services = data.get("services") or {}
        out = []
        for item in expose:
            service = services.get(item["service"])
            if not service:
                continue
            # Let Docker pick the host port to eliminate the TOCTOU race.
            service["ports"] = _replace_port(service.get("ports", []), int(item["container_port"]), 0)
            out.append({**item, "host_port": 0})
        compose_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return out

    def _resolve_ports(
        self, project: str, exposed: list[dict[str, Any]], docker_env: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Query Docker for the actual host ports it bound after `up -d`."""
        resolved = []
        for item in exposed:
            service = item.get("service")
            container_port = item.get("container_port")
            if service is None or container_port is None:
                resolved.append(item)
                continue
            actual = self._query_host_port(project, service, int(container_port), docker_env)
            if actual is None:
                raise RuntimeError(
                    f"Could not resolve host port for {service}:{container_port} in project {project}"
                )
            resolved.append({**item, "host_port": actual})
        return resolved

    def _query_host_port(
        self, project: str, service: str, container_port: int, docker_env: dict[str, str]
    ) -> int | None:
        """Run `docker compose port` and return the host port number."""
        command = [
            "docker", "compose", "-p", project,
            "port", service, str(container_port),
        ]
        for attempt in range(3):
            result = subprocess.run(
                command,
                env=docker_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                line = result.stdout.strip()
                # Output: "0.0.0.0:54321"
                if ":" in line:
                    try:
                        return int(line.rsplit(":", 1)[1])
                    except ValueError:
                        pass
            # Container may still be starting; back off briefly
            time.sleep(0.3 * (attempt + 1))
        return None

    def _infer_expose(self, compose_path: Path) -> list[dict[str, Any]]:
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
        expose = []
        for service_name, service in (data.get("services") or {}).items():
            for port in service.get("ports", []) or []:
                target = str(port).split(":")[-1].split("/")[0]
                if target.isdigit():
                    container_port = int(target)
                    protocol = "http" if container_port in {80, 8080, 8000, 5000, 3000} else "tcp"
                    expose.append({
                        "name": "web" if protocol == "http" else service_name,
                        "protocol": protocol,
                        "service": service_name,
                        "container_port": container_port,
                    })
        return expose or [{"name": "web", "protocol": "http", "service": "web", "container_port": 80}]


# ----------------------------------------------------------------------
# Standalone helpers
# ----------------------------------------------------------------------

# [16] Use "0:container_port" in docker-compose.yml and let Docker pick the host port
# directly.  This eliminates the TOCTOU race condition that existed when we
# bound a socket ourselves, closed it, and then asked Docker to bind the same
# port a moment later.
#
# After docker compose up we query the actual bound port with
#   docker compose -p <project> port <service> <container_port>
# which returns "0.0.0.0:<host_port>".
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return int(sock.getsockname()[1])


def _compose_error(command: list[str], result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stderr or result.stdout or "").strip()
    if output:
        output = output[-2000:]
        return f"Docker Compose failed with exit code {result.returncode}: {output}"
    return f"Docker Compose failed with exit code {result.returncode}: {' '.join(command)}"


# [17] Handles both single JSON array and one-object-per-line output from different Docker Compose versions
# 处理不同 Docker Compose 版本产生的单行 JSON 数组和每行一个对象两种输出格式
def _parse_compose_ps_json(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass

    containers: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            containers.append(item)
    return containers


def _normalise_proxy(value: str | None) -> str | None:
    if not value:
        return None
    proxy = value.strip()
    if not proxy:
        return None
    if "://" not in proxy:
        proxy = f"http://{proxy}"
    return proxy


def _env_enabled(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _normalise_no_proxy(value: str | None, default: str) -> str:
    values = []
    seen = set()
    for raw in (value or "", default):
        for item in raw.split(","):
            token = item.strip()
            if token and token not in seen:
                seen.add(token)
                values.append(token)
    return ",".join(values)


def _proxy_build_args(args: Any, proxy: str, no_proxy: str | None) -> list[str]:
    order: list[str] = []
    values: dict[str, str | None] = {}
    for key, value in _build_arg_pairs(args):
        if key not in values:
            order.append(key)
        values[key] = value

    for key in PROXY_URL_KEYS:
        if key not in values:
            order.append(key)
        values[key] = proxy
    if no_proxy:
        for key in NO_PROXY_KEYS:
            if key not in values:
                order.append(key)
            values[key] = no_proxy

    return [key if values[key] is None else f"{key}={values[key]}" for key in order]


def _without_proxy_build_args(args: Any) -> list[str]:
    return [
        key if value is None else f"{key}={value}"
        for key, value in _build_arg_pairs(args)
        if key not in {*PROXY_URL_KEYS, *NO_PROXY_KEYS}
    ]


# [18] Normalise build args from dict or list form. A bare key like "FLAG" (no "=") is treated as ("FLAG", None).
# 将字典或列表形式的构建参数规范化。像 "FLAG" 这样没有 "=" 的裸键被视为 ("FLAG", None)。
def _build_arg_pairs(args: Any) -> list[tuple[str, str | None]]:
    if args is None:
        return []
    if isinstance(args, dict):
        return [(str(key), None if value is None else str(value)) for key, value in args.items()]
    if isinstance(args, list):
        pairs = []
        for item in args:
            text = str(item)
            if "=" in text:
                key, value = text.split("=", 1)
                pairs.append((key, value))
            else:
                pairs.append((text, None))
        return pairs
    return [(str(args), None)]


def _is_proxy_dockerfile_line(line: str) -> bool:
    stripped = line.strip()
    for key in (*PROXY_URL_KEYS, *NO_PROXY_KEYS):
        if stripped.startswith(f"ENV {key}=") or stripped.startswith(f"ENV {key} "):
            return True
        if stripped.startswith(f"ARG {key}=") or stripped == f"ARG {key}":
            return True
    return False


def _replace_port(ports: list[Any], container_port: int, host_port: int) -> list[str]:
    out = []
    replaced = False
    for port in ports:
        value = str(port)
        if value.split(":")[-1].split("/")[0] == str(container_port):
            out.append(f"{host_port}:{container_port}")
            replaced = True
        else:
            out.append(value)
    if not replaced:
        out.append(f"{host_port}:{container_port}")
    return out


# [19] For HTTP we accept any status < 500 (including 404, which just means the service is alive). For TCP we just check connectivity.
# 对于 HTTP，接受任何 < 500 的状态码（包括 404，这只表示服务是活的）。对于 TCP，只检查连通性。
def _endpoint_ready(endpoint: dict[str, Any]) -> tuple[bool, str]:
    host = str(endpoint.get("host") or "127.0.0.1")
    port = int(endpoint.get("port") or 0)
    if port <= 0:
        return False, "endpoint has no port"
    protocol = str(endpoint.get("type") or "").lower()
    if protocol == "http":
        url = str(endpoint.get("url") or f"http://{host}:{port}")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=3) as response:
                return int(response.status) < 500, f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            return int(exc.code) < 500, f"HTTP {exc.code}"
        except Exception as exc:
            return False, str(exc)
    try:
        with socket.create_connection((host, port), timeout=3):
            return True, ""
    except Exception as exc:
        return False, str(exc)


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0
