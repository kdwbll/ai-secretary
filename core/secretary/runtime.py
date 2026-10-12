"""In-process control plane for the local SecondBrain service."""
from __future__ import annotations

import os
import signal
import threading


class ServiceRuntime:
    """Expose pause/terminate state without depending on a platform launcher."""

    def __init__(self) -> None:
        self._paused = threading.Event()
        self._terminating = threading.Event()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def terminating(self) -> bool:
        return self._terminating.is_set()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def request_termination(self) -> None:
        """Let the HTTP response flush, then stop the hosting process."""
        if self._terminating.is_set():
            return
        self._terminating.set()
        threading.Timer(0.35, self._terminate_process).start()

    @staticmethod
    def _terminate_process() -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    def status(self, version: str, can_control: bool) -> dict[str, object]:
        state = "terminating" if self.terminating else "paused" if self.paused else "running"
        return {"state": state, "version": version, "can_control": can_control}
