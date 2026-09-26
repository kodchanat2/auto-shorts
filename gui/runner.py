"""Run render_shorts.py as a subprocess: command building, progress parsing, one job per project."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Iterator

import render_shorts as R

SCRIPT = R.SCRIPT_DIR / "render_shorts.py"
MODE_FLAGS = {"dry": ["--dry-run"], "tts": ["--tts-only"], "render": []}


class JobRunning(RuntimeError):
    pass


@dataclass(frozen=True)
class Progress:
    stage: int
    stages: int
    label: str
    done: int
    total: int

    @property
    def fraction(self) -> float:
        within = self.done / self.total if self.total else 0.0
        return min(1.0, (self.stage - 1 + within) / self.stages)


def parse_line(line: str) -> Progress | None:
    if not line.startswith(R.PROGRESS_PREFIX):
        return None
    try:
        ev = json.loads(line[len(R.PROGRESS_PREFIX):])
        return Progress(ev["stage"], ev["stages"], ev["label"], ev["done"], ev["total"])
    except (ValueError, KeyError, TypeError):
        return None


def build_command(project: str, mode: str, video: str | None = None) -> list[str]:
    if mode not in MODE_FLAGS:
        raise ValueError(f"unknown mode {mode}")
    cmd = [sys.executable, str(SCRIPT), project, "--progress", *MODE_FLAGS[mode]]
    if video:
        cmd += ["-o", video]
    return cmd


class JobRegistry:
    """At most one running render per project (parallel runs would share build/)."""

    def __init__(self) -> None:
        self._jobs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def start(self, project: str, cmd: list[str]) -> subprocess.Popen:
        with self._lock:
            running = self._jobs.get(project)
            if running and running.poll() is None:
                raise JobRunning(project)
            proc = subprocess.Popen(cmd, cwd=R.SCRIPT_DIR, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1,
                                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                                    start_new_session=True)  # own group so cancel also stops ffmpeg
            self._jobs[project] = proc
            return proc

    def cancel(self, project: str) -> bool:
        with self._lock:
            proc = self._jobs.get(project)
        if not proc or proc.poll() is not None:
            return False
        os.killpg(proc.pid, signal.SIGTERM)
        return True

    def finish(self, project: str) -> None:
        with self._lock:
            proc = self._jobs.get(project)
            if proc and proc.poll() is not None:
                del self._jobs[project]

    def is_running(self, project: str) -> bool:
        with self._lock:
            proc = self._jobs.get(project)
        return bool(proc and proc.poll() is None)


def stream_lines(proc: subprocess.Popen) -> Iterator[str]:
    assert proc.stdout is not None
    for line in proc.stdout:
        yield line
    proc.wait()
