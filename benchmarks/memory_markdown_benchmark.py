#!/usr/bin/env python3
"""Release gate for the incremental Markdown memory index.

This benchmark deliberately creates real Markdown files.  It measures the
filesystem reconciliation path as well as indexed retrieval, so a fast test
that only pre-populates SQLite cannot satisfy the gate.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from core.secretary.database import Database
from core.secretary.memory import MemoryEngine
from core.secretary.storage import LocalStorage


DEFAULT_NOTES = 3_000
LIMITS_MS = {
    "cold_index": 15_000.0,
    "warm_reconcile": 2_500.0,
    "incremental_update": 1_000.0,
    "search_p95": 100.0,
}


class CountingStorage(LocalStorage):
    def __init__(self, root: Path):
        super().__init__(root)
        self.reads = 0
        self.lists = 0

    def read_text(self, relative: str) -> str:
        self.reads += 1
        return super().read_text(relative)

    def list(self, suffix: str = ""):
        self.lists += 1
        return super().list(suffix)

    def reset_counts(self) -> None:
        self.reads = 0
        self.lists = 0


def elapsed_ms(action) -> float:
    started = time.perf_counter()
    action()
    return (time.perf_counter() - started) * 1_000


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, int(len(ordered) * 0.95) - 1)]


def note_text(index: int, marker: str = "") -> str:
    return (
        "---\n"
        f"id: archive-{index:04d}\n"
        "type: daily\n"
        "related: []\n"
        "updated: 2026-10-13T00:00:00+08:00\n"
        "---\n\n"
        f"# 归档记录 {index:04d}\n\n"
        f"- 项目 archivekey{index:04d} 的真实 Markdown 性能样本。{marker}\n"
    )


def run_benchmark(notes: int = DEFAULT_NOTES) -> dict:
    if notes < 100:
        raise ValueError("notes must be at least 100")

    with tempfile.TemporaryDirectory(prefix="secondbrain-memory-benchmark-") as temporary:
        root = Path(temporary)
        memory_root = root / "memory"
        archive_root = memory_root / "daily"
        archive_root.mkdir(parents=True)
        for index in range(notes):
            (archive_root / f"archive-{index:04d}.md").write_text(note_text(index), encoding="utf-8")

        storage = CountingStorage(memory_root)
        memory = MemoryEngine(storage, Database(root / "benchmark.db"))
        cold_ms = elapsed_ms(memory.sync_index)
        indexed = memory.database.rows("SELECT count(*) AS total FROM memory_documents")[0]["total"]

        storage.reset_counts()
        warm_ms = elapsed_ms(memory.sync_index)
        warm_io = {"directory_scans": storage.lists, "markdown_reads": storage.reads}

        query_times = []
        storage.reset_counts()
        for index in range(0, notes, max(1, notes // 200)):
            query = f"archivekey{index:04d}"
            started = time.perf_counter()
            results = memory.search(query, limit=5)
            query_times.append((time.perf_counter() - started) * 1_000)
            expected = f"daily/archive-{index:04d}.md"
            if not results or results[0]["path"] != expected:
                raise AssertionError(f"indexed search did not return {expected}")
        search_io = {"directory_scans": storage.lists, "markdown_reads": storage.reads}

        changed = notes // 2
        changed_path = f"daily/archive-{changed:04d}.md"
        storage.write_text(changed_path, note_text(changed, " uniquechangedmarker"))
        storage.reset_counts()
        incremental_ms = elapsed_ms(memory.sync_index)
        incremental_io = {"directory_scans": storage.lists, "markdown_reads": storage.reads}
        changed_results = memory.search("uniquechangedmarker", limit=5)

        timings = {
            "cold_index": round(cold_ms, 3),
            "warm_reconcile": round(warm_ms, 3),
            "incremental_update": round(incremental_ms, 3),
            "search_p50": round(statistics.median(query_times), 3),
            "search_p95": round(percentile_95(query_times), 3),
            "search_max": round(max(query_times), 3),
        }
        checks = {
            "all_markdown_files_indexed": indexed == notes,
            "warm_reconcile_reads_no_markdown": warm_io["markdown_reads"] == 0,
            "search_scans_no_directories": search_io["directory_scans"] == 0,
            "search_reads_no_markdown": search_io["markdown_reads"] == 0,
            "incremental_reads_one_markdown": incremental_io["markdown_reads"] == 1,
            "changed_note_is_searchable": bool(changed_results and changed_results[0]["path"] == changed_path),
        }
        thresholds = {
            name: timings[name] <= limit for name, limit in LIMITS_MS.items()
        }
        return {
            "benchmark": "real-markdown-memory-index",
            "notes": notes,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "timings_ms": timings,
            "io": {
                "warm_reconcile": warm_io,
                "indexed_searches": search_io,
                "incremental_update": incremental_io,
            },
            "limits_ms": LIMITS_MS,
            "checks": checks,
            "thresholds": thresholds,
            "passed": all(checks.values()) and all(thresholds.values()),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes", type=int, default=DEFAULT_NOTES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.notes)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
