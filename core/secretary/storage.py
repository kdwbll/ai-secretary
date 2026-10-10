from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
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

    def write_text(self, relative: str, content: str) -> None:
        path = self._path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(path)

    def delete(self, relative: str) -> None:
        self._path(relative).unlink(missing_ok=True)

    def list(self, suffix: str = "") -> Iterable[str]:
        return sorted(
            str(path.relative_to(self.root))
            for path in self.root.rglob(f"*{suffix}")
            if path.is_file()
        )
