"""Log an experiment run to a folder: params, metrics per step, artifacts, and where and from which commit.

A run is `<RUNLOG_DIR>/<project>/runs/<run id>/`: `run.json`, `params.json`, `metrics.jsonl`, `artifacts/`.
"""

import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType, TracebackType
from typing import IO, Literal, TypeVar

from typing_extensions import Self

__all__ = ["Run", "RunStatus"]

RunStatus = Literal["running", "finished", "failed", "killed"]
SignalHandler = Callable[[int, FrameType | None], object] | int | signal.Handlers | None
ENV_ROOT = "RUNLOG_DIR"
RunT = TypeVar("RunT", bound="Run")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: Mapping[str, object]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    os.replace(tmp, path)


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _new_run_id() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


class Run:
    """One run, as a context manager; its status is `finished`, `failed` or `killed` when the block exits.

    Raises:
        ValueError: The project name is empty, has a slash, or starts with a dot or underscore.
        RuntimeError: Neither `RUNLOG_DIR` nor `root` gives the folder to log to.
    """

    def __init__(
        self,
        project: str,
        name: str | None = None,
        params: Mapping[str, object] | None = None,
        experiment: str | None = None,
        tags: Mapping[str, str] | None = None,
        root: Path | str | None = None,
    ) -> None:
        if not project or "/" in project or project.startswith((".", "_")):
            raise ValueError(f"invalid project name {project!r}")
        base = root if root is not None else os.environ.get(ENV_ROOT)
        if base is None:
            raise RuntimeError(f"set {ENV_ROOT} or pass root= (the metrics root folder)")
        self.run_id = _new_run_id()
        self.dir = Path(base) / project / "runs" / self.run_id
        self.artifacts_dir = self.dir / "artifacts"
        self._info: dict[str, object] = {
            "name": name or self.run_id,
            "experiment": experiment,
            "status": "running",
            "start": None,
            "end": None,
            "host": socket.gethostname(),
            "git_sha": _git("rev-parse", "HEAD"),
            "git_dirty": None,
            "command": " ".join(sys.argv),
            "tags": {**self._env_tags(), **(tags or {})},
        }
        self._params = dict(params or {})
        self._steps: dict[str, int] = {}
        self._metrics: IO[str] | None = None
        self._previous_sigterm: SignalHandler = None
        self._installed_sigterm = False

    @staticmethod
    def _env_tags() -> dict[str, str]:
        job = os.environ.get("SLURM_JOB_ID")
        return {"slurm_job_id": job} if job else {}

    def __enter__(self) -> Self:
        self.artifacts_dir.mkdir(parents=True)
        status = _git("status", "--porcelain")
        self._info["git_dirty"] = None if status is None else bool(status)
        self._info["start"] = _now()
        _write_json(self.dir / "run.json", self._info)
        _write_json(self.dir / "params.json", self._params)
        self._metrics = (self.dir / "metrics.jsonl").open("a", encoding="utf-8")
        if threading.current_thread() is threading.main_thread():
            self._previous_sigterm = signal.signal(signal.SIGTERM, self._on_sigterm)
            self._installed_sigterm = True
        return self

    def _on_sigterm(self, signum: int, frame: FrameType | None) -> None:
        raise SystemExit(128 + signum)

    def log(self, metrics: Mapping[str, float], step: int | None = None) -> None:
        """Append metrics, at `step` or each metric's next step."""
        ts = time.time()
        lines = []
        for key, value in metrics.items():
            current = step if step is not None else self._steps.get(key, -1) + 1
            self._steps[key] = current
            lines.append(json.dumps({"key": key, "value": float(value), "step": current, "ts": ts}))
        if self._metrics is None:
            raise RuntimeError("log() outside the run's with-block")
        self._metrics.write("\n".join(lines) + "\n")
        self._metrics.flush()

    def log_params(self, params: Mapping[str, object]) -> None:
        """Add params; a param already logged can't change (ValueError names it)."""
        clash = {k for k in params if k in self._params and self._params[k] != params[k]}
        if clash:
            raise ValueError(f"params are immutable once logged: {sorted(clash)}")
        self._params.update(params)
        _write_json(self.dir / "params.json", self._params)

    def artifact(self, path: Path | str, name: str | None = None) -> Path:
        """Copy a file or folder into the run's artifacts, as `name` if given; return where it went."""
        source = Path(path)
        target = self.artifacts_dir / (name or source.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
            return target
        shutil.copy2(source, tmp)
        os.replace(tmp, target)
        return target

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        status: RunStatus = "finished"
        if isinstance(exc, SystemExit) and exc.code in (0, None):
            status = "finished"
        elif isinstance(exc, (KeyboardInterrupt, SystemExit)):
            status = "killed"
        elif exc is not None:
            status = "failed"
        if self._metrics is not None:
            self._metrics.close()
        self._info["status"] = status
        self._info["end"] = _now()
        _write_json(self.dir / "run.json", self._info)
        if self._installed_sigterm:
            previous = self._previous_sigterm
            signal.signal(signal.SIGTERM, signal.SIG_DFL if previous is None else previous)
