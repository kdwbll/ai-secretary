from __future__ import annotations

import json
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .database import Database
from .files import FilePipeline
from .memory import MemoryDocument, MemoryEngine
from .models import ModelRouter, PROVIDER_TEMPLATES, Route
from .reports import ReportService
from .service import SecretaryService
from .storage import LocalStorage

ROOT = Path(os.environ.get("SECOND_BRAIN_ROOT", Path(__file__).resolve().parents[2])).resolve()
DB = Database(ROOT / "data" / "second-brain.db")
MEMORY = MemoryEngine(LocalStorage(ROOT / "memory"), DB)
MODELS = ModelRouter(DB)
SERVICE = SecretaryService(MEMORY, DB, MODELS, ROOT / "core" / "prompts")
FILES = FilePipeline(ROOT / "files", DB, MEMORY)
REPORTS = ReportService(MEMORY, DB)


class ChatInput(BaseModel):
    message: str


class MemoryInput(BaseModel):
    content: str


class ProviderInput(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    models: list[str] = []
    kind: str = "openai"


class RouteInput(BaseModel):
    task: str
    provider: str
    model: str
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None


class SmsInput(BaseModel):
    text: str
    sender: str = ""


class NotificationInput(BaseModel):
    package: str
    title: str = ""
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    SERVICE.initialize()
    scheduler = None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        morning_hour, morning_minute = map(int, (DB.setting("morning_time", "07:30") or "07:30").split(":"))
        review_hour, review_minute = map(int, (DB.setting("review_time", "22:30") or "22:30").split(":"))
        scheduler.add_job(REPORTS.morning, "cron", hour=morning_hour, minute=morning_minute, id="morning")
        scheduler.add_job(REPORTS.evening, "cron", hour=review_hour, minute=review_minute, id="evening")
        scheduler.add_job(REPORTS.weekly, "cron", day_of_week="sun", hour=23, minute=0, id="weekly")
        scheduler.start()
    except ImportError:
        pass
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="第二大脑", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.1.0"}


@app.post("/api/chat")
def chat(body: ChatInput):
    return SERVICE.chat(body.message)


@app.get("/api/interview")
def interview():
    return {"questions": SERVICE.interview_questions()}


@app.get("/api/memory")
def memory_list():
    return {"files": list(MEMORY.storage.list(".md"))}


@app.get("/api/memory/{path:path}")
def memory_get(path: str):
    try:
        return {"path": path, "content": MEMORY.storage.read_text(path)}
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "记忆文件不存在")


@app.put("/api/memory/{path:path}")
def memory_put(path: str, body: MemoryInput):
    try:
        old = MEMORY.storage.read_text(path)
        MEMORY.storage.write_text(path, body.content)
        MEMORY.parse(path)
    except Exception as exc:
        if 'old' in locals():
            MEMORY.storage.write_text(path, old)
        raise HTTPException(400, f"保存失败：{exc}")
    DB.record_mutation(path, old, body.content, "用户在记忆浏览器中编辑", "user")
    MEMORY.rebuild_index()
    return {"ok": True}


@app.get("/api/search")
def search(q: str):
    return {"results": MEMORY.search(q)}


@app.get("/api/providers")
def providers():
    return {"templates": PROVIDER_TEMPLATES, "providers": MODELS.providers(), "routes": DB.rows("SELECT * FROM model_routes ORDER BY task")}


@app.post("/api/providers")
def provider_save(body: ProviderInput):
    MODELS.save_provider(body.name, body.base_url, body.api_key, body.models, body.kind)
    return {"ok": True}


@app.post("/api/routes")
def route_save(body: RouteInput):
    MODELS.set_route(Route(**body.model_dump()))
    return {"ok": True}


@app.get("/api/usage")
def usage():
    rows = DB.rows("SELECT COALESCE(SUM(prompt_tokens),0) prompt_tokens,COALESCE(SUM(completion_tokens),0) completion_tokens,COALESCE(SUM(estimated_cost),0) estimated_cost FROM ai_calls WHERE created_at >= date('now','start of month')")
    return rows[0]


@app.post("/api/ingest/sms")
def ingest_sms(body: SmsInput):
    return SERVICE.ingest_sms(body.text, body.sender)


@app.post("/api/ingest/notification")
def ingest_notification(body: NotificationInput):
    return SERVICE.ingest_notification(body.package, body.title, body.text)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload").suffix
    with NamedTemporaryFile(suffix=suffix, delete=False) as temp:
        shutil.copyfileobj(file.file, temp)
        temp_path = Path(temp.name)
    try:
        return FILES.ingest(temp_path, file.filename or "upload")
    finally:
        temp_path.unlink(missing_ok=True)


@app.post("/api/reports/{kind}")
def report(kind: str):
    functions = {"morning": REPORTS.morning, "evening": REPORTS.evening, "weekly": REPORTS.weekly}
    if kind not in functions:
        raise HTTPException(404, "未知报告类型")
    return {"content": functions[kind]()}


@app.get("/api/reports")
def reports():
    return {"reports": DB.rows("SELECT id,created_at,kind,content FROM reports ORDER BY id DESC LIMIT 30")}


WEB = ROOT / "web"
app.mount("/assets", StaticFiles(directory=str(WEB)), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str = ""):
    return FileResponse(WEB / "index.html")
