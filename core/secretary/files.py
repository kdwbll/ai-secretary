from __future__ import annotations

import hashlib
import shutil
import zipfile
from datetime import date, datetime
from pathlib import Path

from .database import Database
from .memory import MemoryEngine


class FilePipeline:
    def __init__(self, files_root: Path, database: Database, memory: MemoryEngine):
        self.files_root, self.database, self.memory = files_root, database, memory

    def ingest(self, source: Path, original_name: str = "") -> dict:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        existing = self.database.rows("SELECT * FROM files WHERE hash=?", (digest,))
        if existing:
            return {**existing[0], "duplicate": True}
        month = date.today().strftime("%Y-%m")
        target_dir = self.files_root / month
        target_dir.mkdir(parents=True, exist_ok=True)
        original_name = original_name or source.name
        safe_name = original_name.replace("/", "_").replace("\\", "_")
        target = target_dir / f"{digest[:10]}-{safe_name}"
        shutil.copy2(source, target)
        text = self.extract(target)
        relative = str(target.relative_to(self.files_root.parent))
        with self.database.connect() as db:
            db.execute("INSERT INTO files(hash,original_name,stored_path,created_at,extracted_text) VALUES(?,?,?,?,?)", (digest, original_name, relative, datetime.now().isoformat(timespec="seconds"), text))
        self.memory.append_daily(f"收录文件 [{original_name}](../../{relative})：{text[:300] or '暂无可提取文字'}", "文件上传", inferred=not bool(text))
        return {"hash": digest, "original_name": original_name, "stored_path": relative, "extracted_text": text, "duplicate": False}

    def extract(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".csv", ".json", ".log"}:
            return path.read_text(encoding="utf-8", errors="replace")[:200000]
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
                return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)[:200000]
            except ImportError:
                return "PDF 解析组件未安装，请安装 documents 可选依赖"
        if suffix == ".docx":
            try:
                from docx import Document
                return "\n".join(p.text for p in Document(str(path)).paragraphs)[:200000]
            except ImportError:
                return "Word 解析组件未安装，请安装 documents 可选依赖"
        if suffix in {".xlsx", ".xlsm"}:
            try:
                from openpyxl import load_workbook
                book = load_workbook(path, read_only=True, data_only=True)
                return "\n".join(",".join("" if v is None else str(v) for v in row) for sheet in book for row in sheet.iter_rows(values_only=True))[:200000]
            except ImportError:
                return "Excel 解析组件未安装，请安装 documents 可选依赖"
        if suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                names = [name for name in archive.namelist() if not name.startswith("__MACOSX/")]
            return "压缩包内容：\n" + "\n".join(names[:500])
        return ""
