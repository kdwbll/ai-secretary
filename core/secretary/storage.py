from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable


class Storage(ABC):
    """Storage boundary; a future encrypted implementation can replace this class."""

    @abstractmethod
    def read_text(self, relative: str) -> str: ...

    @abstractmethod
    def write_text(self, relative: str, content: str) -> None: ...

    @abstractmethod
    def delete(self, relative: str) -> None: ...

    @abstractmethod
    def list(self, suffix: str = "") -> Iterable[str]: ...


class LocalStorage(Storage):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("路径越界")
        return path

    def read_text(self, relative: str) -> str:
        return self._path(relative).read_text(encoding="utf-8")

    def repair_utf8(self, relative: str) -> str:
        """Keep a byte-for-byte backup, then normalize a damaged text file to UTF-8."""
        path = self._path(relative)
        raw = path.read_bytes()
        backup = path.with_name(path.name + ".invalid-utf8-" + datetime.now().strftime("%Y%m%d%H%M%S") + ".bak")
        backup.write_bytes(raw)
        content = raw.decode("utf-8", errors="replace")
        self.write_text(relative, content)
        return content

    def write_text(self, relative: str, content: str) -> None:
        path = self._path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        # A fixed ``.tmp`` name races when the Android collector, chat memory
        # and scheduled reports update the same daily note at once.  Each
        # writer gets a unique temporary file and the final replace is atomic.
        temp_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False, dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp",
            ) as temp:
                temp.write(content)
                temp.flush()
                os.fsync(temp.fileno())
                temp_path = Path(temp.name)
            os.replace(temp_path, path)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def delete(self, relative: str) -> None:
        self._path(relative).unlink(missing_ok=True)

    def list(self, suffix: str = "") -> Iterable[str]:
        return sorted(
            str(path.relative_to(self.root))
            for path in self.root.rglob(f"*{suffix}")
            if path.is_file()
        )
