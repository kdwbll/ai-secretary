from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

from .database import Database
from .memory import MemoryEngine


METRICS = {
    "steps": {"label": "步数", "unit": "步", "mode": "sum"},
    "heart_rate": {"label": "心率", "unit": "次/分", "mode": "avg"},
    "resting_heart_rate": {"label": "静息心率", "unit": "次/分", "mode": "avg"},
    "sleep_hours": {"label": "睡眠", "unit": "小时", "mode": "sum"},
    "weight": {"label": "体重", "unit": "kg", "mode": "avg"},
    "active_energy": {"label": "活动能量", "unit": "千卡", "mode": "sum"},
    "distance": {"label": "步行跑步距离", "unit": "km", "mode": "sum"},
}

APPLE_TYPES = {
    "HKQuantityTypeIdentifierStepCount": "steps",
    "HKQuantityTypeIdentifierHeartRate": "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_heart_rate",
    "HKQuantityTypeIdentifierBodyMass": "weight",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_energy",
    "HKQuantityTypeIdentifierDistanceWalkingRunning": "distance",
}

COLUMN_ALIASES = {
    "steps": ("steps", "step", "步数"),
    "heart_rate": ("heart_rate", "heartrate", "heart rate", "心率", "bpm"),
    "resting_heart_rate": ("resting_heart_rate", "resting heart rate", "静息心率"),
    "sleep_hours": ("sleep_hours", "sleep duration", "sleep_duration", "睡眠时长", "睡眠"),
    "weight": ("weight", "body_weight", "体重"),
    "active_energy": ("active_energy", "calories", "calorie", "卡路里", "活动能量"),
    "distance": ("distance", "步行距离", "运动距离"),
}

DATE_COLUMNS = ("recorded_at", "datetime", "date", "time", "start_time", "timestamp", "日期", "时间")


class HealthService:
    def __init__(self, database: Database, memory: MemoryEngine):
        self.database = database
        self.memory = memory

    def import_file(self, path: Path, original_name: str) -> dict[str, Any]:
        raw = path.read_bytes()
        source = "Apple 健康" if self._looks_like_apple(original_name, raw) else "小米运动/通用导入"
        samples: list[dict[str, Any]] = []
        suffix = Path(original_name).suffix.lower()
        if suffix == ".zip":
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if any("apple_health_export" in info.filename.lower() or info.filename.lower().endswith("export.xml") for info in archive.infolist()):
                    source = "Apple 健康"
                for info in archive.infolist():
                    if info.is_dir() or info.file_size > 250_000_000:
                        continue
                    name = info.filename.lower()
                    if name.endswith((".xml", ".csv", ".json")):
                        samples.extend(self._parse_bytes(archive.read(info), name, source))
        else:
            samples = self._parse_bytes(raw, original_name, source)
        inserted = self._store(samples)
        if inserted:
            metrics = sorted({sample["metric"] for sample in samples if sample["metric"] in METRICS})
            labels = "、".join(METRICS[item]["label"] for item in metrics)
            self.memory.upsert_fact(
                "health.md", "指标与趋势",
                f"已连接 {source} 数据：{labels}（最近导入 {inserted} 条）",
                f"{date.today().isoformat()} 健康数据导入",
                old_fact=f"已连接 {source} 数据：",
            )
        return {"ok": True, "source": source, "imported": inserted, "detected": len(samples)}

    def summary(self, days: int = 14) -> dict[str, Any]:
        days = max(7, min(days, 90))
        start = (date.today() - timedelta(days=days - 1)).isoformat()
        rows = self.database.rows(
            "SELECT recorded_at,metric,value,unit,source FROM health_samples WHERE recorded_at>=? ORDER BY recorded_at",
            (start,),
        )
        grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        sources: dict[str, int] = defaultdict(int)
        for row in rows:
            metric = row["metric"]
            if metric not in METRICS:
                continue
            day = str(row["recorded_at"])[:10]
            grouped[metric][day].append(float(row["value"]))
            sources[row["source"]] += 1
        dates = [(date.today() - timedelta(days=offset)).isoformat() for offset in reversed(range(days))]
        series = []
        for metric, meta in METRICS.items():
            values = []
            for day in dates:
                points = grouped[metric].get(day, [])
                value = (sum(points) if meta["mode"] == "sum" else sum(points) / len(points)) if points else None
                values.append(round(value, 2) if value is not None else None)
            non_null = [value for value in values if value is not None]
            series.append({"metric": metric, **meta, "values": values, "latest": non_null[-1] if non_null else None})
        return {"days": days, "dates": dates, "series": series, "sources": [{"name": key, "count": value} for key, value in sorted(sources.items())], "sample_count": len(rows)}

    def sync_samples(self, samples: list[dict[str, Any]], source: str = "Android Health Connect") -> dict[str, Any]:
        """Store structured, read-only health records sent by a paired phone."""
        normalized: list[dict[str, Any]] = []
        for item in samples:
            metric = str(item.get("metric") or "")
            recorded_at = str(item.get("recorded_at") or "").strip()
            value = self._number(item.get("value"))
            if metric not in METRICS or not recorded_at or value is None:
                continue
            external_id = str(item.get("external_id") or "").strip()
            sample = self._sample(
                recorded_at, metric, value,
                str(item.get("unit") or METRICS[metric]["unit"]), source,
                {"external_id": external_id, "recorded_at": recorded_at, "metric": metric, "value": value},
            )
            if external_id:
                sample["external_id"] = hashlib.sha256(f"{source}:{external_id}".encode()).hexdigest()
            normalized.append(sample)
        inserted = self._sync_store(normalized)
        if inserted:
            labels = "、".join(METRICS[key]["label"] for key in sorted({item["metric"] for item in normalized}))
            self.memory.upsert_fact(
                "health.md", "指标与趋势", f"已连接 {source} 数据：{labels}（最近同步 {inserted} 条）",
                f"{date.today().isoformat()} Android 健康同步", old_fact=f"已连接 {source} 数据：",
            )
        latest = max((item["recorded_at"] for item in normalized), default="")
        return {"ok": True, "source": source, "received": len(samples), "detected": len(normalized), "imported": inserted, "latest": latest}

    def _sync_store(self, samples: list[dict[str, Any]]) -> int:
        changed = 0
        with self.database.connect() as db:
            for sample in samples:
                cursor = db.execute(
                    "INSERT INTO health_samples(recorded_at,metric,value,unit,source,external_id) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(external_id) DO UPDATE SET recorded_at=excluded.recorded_at,value=excluded.value,unit=excluded.unit,source=excluded.source "
                    "WHERE health_samples.recorded_at<>excluded.recorded_at OR health_samples.value<>excluded.value "
                    "OR health_samples.unit<>excluded.unit OR health_samples.source<>excluded.source",
                    (sample["recorded_at"], sample["metric"], sample["value"], sample["unit"], sample["source"], sample["external_id"]),
                )
                changed += cursor.rowcount
        return changed

    def _parse_bytes(self, raw: bytes, name: str, source: str) -> list[dict[str, Any]]:
        suffix = Path(name).suffix.lower()
        if suffix == ".xml":
            return list(self._parse_apple_xml(raw))
        if suffix == ".json":
            return list(self._parse_json(raw, source))
        if suffix == ".csv":
            return list(self._parse_csv(raw, source))
        return []

    @staticmethod
    def _looks_like_apple(name: str, raw: bytes) -> bool:
        return name.lower().endswith(".xml") or b"HKQuantityTypeIdentifier" in raw[:2_000_000] or b"apple_health_export" in raw[:2_000_000]

    def _parse_apple_xml(self, raw: bytes) -> Iterable[dict[str, Any]]:
        for _, element in ElementTree.iterparse(io.BytesIO(raw), events=("end",)):
            if element.tag != "Record":
                element.clear()
                continue
            kind = element.attrib.get("type", "")
            metric = APPLE_TYPES.get(kind)
            recorded_at = element.attrib.get("startDate", "")
            value = self._number(element.attrib.get("value"))
            if kind == "HKCategoryTypeIdentifierSleepAnalysis":
                start, end = self._datetime(recorded_at), self._datetime(element.attrib.get("endDate", ""))
                if start and end and "InBed" not in element.attrib.get("value", ""):
                    metric, value = "sleep_hours", max(0.0, (end - start).total_seconds() / 3600)
            if metric and value is not None and recorded_at:
                yield self._sample(recorded_at, metric, value, METRICS[metric]["unit"], "Apple 健康", element.attrib)
            element.clear()

    def _parse_csv(self, raw: bytes, source: str) -> Iterable[dict[str, Any]]:
        text = raw.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        for row in csv.DictReader(io.StringIO(text), dialect=dialect):
            yield from self._samples_from_mapping(row, source)

    def _parse_json(self, raw: bytes, source: str) -> Iterable[dict[str, Any]]:
        value = json.loads(raw.decode("utf-8-sig", errors="replace"))
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                produced = list(self._samples_from_mapping(item, source))
                if produced:
                    yield from produced
                else:
                    stack.extend(item.values())

    def _samples_from_mapping(self, row: dict[str, Any], source: str) -> Iterable[dict[str, Any]]:
        normalized = {str(key).strip().lower(): value for key, value in row.items()}
        recorded_at = next((normalized[key] for key in DATE_COLUMNS if key in normalized and normalized[key]), None)
        if recorded_at is None:
            return
        for metric, aliases in COLUMN_ALIASES.items():
            key = next((alias for alias in aliases if alias in normalized), None)
            if not key:
                continue
            value = self._number(normalized[key])
            if value is None:
                continue
            if metric == "sleep_hours" and value > 24:
                value /= 60
            yield self._sample(str(recorded_at), metric, value, METRICS[metric]["unit"], source, row)

    @staticmethod
    def _sample(recorded_at: str, metric: str, value: float, unit: str, source: str, raw: Any) -> dict[str, Any]:
        stamp = recorded_at.replace("/", "-")
        identity = hashlib.sha256(json.dumps([stamp, metric, value, source, raw], ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        return {"recorded_at": stamp, "metric": metric, "value": value, "unit": unit, "source": source, "external_id": identity}

    def _store(self, samples: list[dict[str, Any]]) -> int:
        inserted = 0
        with self.database.connect() as db:
            for sample in samples:
                cursor = db.execute(
                    "INSERT OR IGNORE INTO health_samples(recorded_at,metric,value,unit,source,external_id) VALUES(?,?,?,?,?,?)",
                    (sample["recorded_at"], sample["metric"], sample["value"], sample["unit"], sample["source"], sample["external_id"]),
                )
                inserted += cursor.rowcount
        return inserted

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _datetime(value: str) -> datetime | None:
        for candidate in (value, value.replace(" +", "+")):
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                pass
        return None
