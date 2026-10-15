from __future__ import annotations

import json
import mimetypes
import os
import sys
import zipfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .database import Database
from .auth import AccessControl
from .connectors import ImapConnector
from .files import FilePipeline
from .health import HealthService
from .goals import GoalService
from .runner import TaskRunner
from .event_hub import EventHub
from .memory import MemoryDocument, MemoryEngine
from .models import ModelError, ModelRouter, PROVIDER_TEMPLATES, Route
from .reports import ReportService
from .notifications import NotificationService
from .service import SecretaryService
from .storage import LocalStorage
from .secrets import SecretStore
from .web_search import WebSearchService
from .runtime import ServiceRuntime
from .safety import ApprovalError, ApprovalService
from .actions import UsefulActionService
from .artifacts import ArtifactConflict, ArtifactService, safe_file_preview

# ROOT is deliberately user-writable state (database, memory, uploads).  In a
# frozen desktop build the code and static assets live in PyInstaller's
# temporary bundle, so keep those resources separate from user data.
RESOURCE_ROOT = Path(os.environ.get(
    "SECOND_BRAIN_RESOURCES_ROOT",
    getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]),
)).resolve()
ROOT = Path(os.environ.get("SECOND_BRAIN_ROOT", RESOURCE_ROOT)).resolve()
APP_VERSION = "0.15.0"
RUNTIME = ServiceRuntime()
DB = Database(ROOT / "data" / "second-brain.db")
ACCESS = AccessControl(DB)
SECRETS = SecretStore(ROOT / "data" / ".secrets-key")
SECRETS.migrate_database(DB)
MEMORY = MemoryEngine(LocalStorage(ROOT / "memory"), DB)
MODELS = ModelRouter(DB, SECRETS)
NOTIFICATIONS = NotificationService(DB)
WEB_SEARCH = WebSearchService(DB, SECRETS)
SERVICE = SecretaryService(MEMORY, DB, MODELS, RESOURCE_ROOT / "core" / "prompts", NOTIFICATIONS.publish, SECRETS, WEB_SEARCH)
FILES = FilePipeline(ROOT / "files", DB, MEMORY, MODELS)
REPORTS = ReportService(MEMORY, DB, NOTIFICATIONS.publish)
HEALTH = HealthService(DB, MEMORY)
GOALS = GoalService(DB)
RUNNER = TaskRunner(DB, NOTIFICATIONS)
EVENTS = EventHub(DB)
SAFETY = ApprovalService(DB)
ACTIONS = UsefulActionService(DB, SAFETY)
ARTIFACTS = ArtifactService(DB)


class ChatInput(BaseModel):
    message: str
    provider: Optional[str] = None
    model: Optional[str] = None
    file_hashes: list[str] = Field(default_factory=list)
    file_note: str = ""


class ChatDeleteInput(BaseModel):
    delete_memory: bool = False


class MemoryInput(BaseModel):
    content: str


class MemoryDecision(BaseModel):
    accept: bool


class ProviderInput(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    models: list[str] = []
    kind: str = "openai"
    consumption_level: str = "medium"


class RouteInput(BaseModel):
    task: str
    provider: str
    model: str
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None


class ModelPriceInput(BaseModel):
    provider: str
    model: str
    input_per_million: float
    output_per_million: float
    currency: str = "CNY"


class CostSettingsInput(BaseModel):
    usd_cny_rate: float


class SmsInput(BaseModel):
    text: str
    sender: str = ""


class NotificationInput(BaseModel):
    package: str
    title: str = ""
    text: str


class EventInput(BaseModel):
    source: str = Field(min_length=1, max_length=80)
    kind: str = Field(min_length=1, max_length=120)
    payload: dict = Field(default_factory=dict)
    trust: str = Field(default="untrusted", pattern="^(untrusted|local|paired_device)$")


class CalendarEventInput(BaseModel):
    external_id: str = Field(min_length=1, max_length=160)
    title: str = Field(default="（无标题日程）", max_length=500)
    start_at: str = Field(min_length=1, max_length=64)
    end_at: str = Field(min_length=1, max_length=64)
    all_day: bool = False
    location: str = Field(default="", max_length=1000)
    description: str = Field(default="", max_length=4000)
    calendar_name: str = Field(default="", max_length=200)


class CalendarSyncInput(BaseModel):
    window_start: str = Field(min_length=1, max_length=64)
    window_end: str = Field(min_length=1, max_length=64)
    events: list[CalendarEventInput] = Field(default_factory=list, max_length=200)


class HealthSampleInput(BaseModel):
    external_id: str = Field(min_length=1, max_length=240)
    recorded_at: str = Field(min_length=1, max_length=64)
    metric: str = Field(pattern="^(steps|heart_rate|resting_heart_rate|sleep_hours|weight|active_energy|distance)$")
    value: float
    unit: str = Field(default="", max_length=40)


class HealthSyncInput(BaseModel):
    source: str = Field(default="Android Health Connect", max_length=120)
    samples: list[HealthSampleInput] = Field(default_factory=list, max_length=5000)


class EmailAccountInput(BaseModel):
    name: str
    host: str
    port: int = 993
    username: str
    authorization_code: str = ""
    enabled: bool = True


class PairInput(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    device_name: str = Field(default="未命名设备", max_length=80)


class LocationSettingsInput(BaseModel):
    enabled: bool = False
    default_label: str = Field(default="", max_length=120)
    default_latitude: Optional[float] = None
    default_longitude: Optional[float] = None
    map_provider: str = "amap"
    map_api_key: str = ""
    map_security_code: str = ""
    map_web_service_key: str = ""


class LocationReportInput(BaseModel):
    source: str
    latitude: float
    longitude: float
    label: str = Field(default="", max_length=120)
    enabled: bool = True


class WebSearchSettingsInput(BaseModel):
    enabled: bool = False
    provider: str = "bocha"
    api_key: str = ""
    searxng_url: str = ""


class NotificationSettingsInput(BaseModel):
    enabled: bool = False
    quiet_start: str = Field(default="22:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str = Field(default="07:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    dedup_minutes: int = Field(default=60, ge=1, le=1440)
    daily_limit: int = Field(default=3, ge=1, le=20)


class GoalCreateInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    due_at: Optional[str] = Field(default=None, max_length=64)


class GoalUpdateInput(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    due_at: Optional[str] = Field(default=None, max_length=64)


class GoalStatusInput(BaseModel):
    status: str


class TaskCreateInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    due_at: Optional[str] = Field(default=None, max_length=64)
    position: Optional[int] = Field(default=None, ge=0)
    schedule: str = Field(default="manual", pattern="^(manual|once|interval|event)$")
    next_run_at: Optional[str] = Field(default=None, max_length=64)
    max_retries: int = Field(default=3, ge=0, le=10)
    interval_minutes: int = Field(default=0, ge=0, le=525600)
    event_source: str = Field(default="", max_length=80)
    event_kind: str = Field(default="", max_length=120)
    enabled: bool = True


class TaskUpdateInput(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    due_at: Optional[str] = Field(default=None, max_length=64)
    position: Optional[int] = Field(default=None, ge=0)
    schedule: Optional[str] = Field(default=None, pattern="^(manual|once|interval|event)$")
    next_run_at: Optional[str] = Field(default=None, max_length=64)
    max_retries: Optional[int] = Field(default=None, ge=0, le=10)
    interval_minutes: Optional[int] = Field(default=None, ge=0, le=525600)
    event_source: Optional[str] = Field(default=None, max_length=80)
    event_kind: Optional[str] = Field(default=None, max_length=120)
    enabled: Optional[bool] = None


class TaskStatusInput(BaseModel):
    status: str

class TaskRunFinishInput(BaseModel):
    success: bool
    result: dict = Field(default_factory=dict)
    error: str = Field(default="", max_length=2000)


class ApprovalCreateInput(BaseModel):
    action_type: str = Field(min_length=1, max_length=120)
    level: str = Field(pattern="^(read|draft|write|irreversible)$")
    connector: str = Field(default="", max_length=80)
    goal_id: Optional[int] = None
    summary: str = Field(min_length=1, max_length=500)
    target: str = Field(default="", max_length=500)
    exact_payload: dict = Field(default_factory=dict)
    expires_minutes: int = Field(default=30, ge=1, le=1440)


class ApprovalDecisionInput(BaseModel):
    decision: str = Field(pattern="^(approve|deny|revoke)$")
    edited_payload: Optional[dict] = None


class ConnectorPermissionInput(BaseModel):
    enabled: bool


class ForgetInput(BaseModel):
    phrase: str = Field(min_length=1, max_length=500)
    goal_ids: list[int] = Field(default_factory=list, max_length=100)
    expires_minutes: int = Field(default=15, ge=1, le=1440)


class TemplateCreateInput(BaseModel):
    title: str = Field(default="", max_length=200)
    due_at: Optional[str] = Field(default=None, max_length=64)


class CalendarSuggestionInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    start_at: str = Field(min_length=1, max_length=64)
    end_at: str = Field(min_length=1, max_length=64)
    all_day: bool = False
    location: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=4000)
    goal_id: Optional[int] = None


class EmailDraftCreateInput(BaseModel):
    recipients: list[str] = Field(min_length=1, max_length=50)
    cc: list[str] = Field(default_factory=list, max_length=50)
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=50000)
    goal_id: Optional[int] = None
    account_id: Optional[int] = None
    source: str = Field(default="manual", max_length=200)


class EmailDraftUpdateInput(BaseModel):
    recipients: Optional[list[str]] = Field(default=None, max_length=50)
    cc: Optional[list[str]] = Field(default=None, max_length=50)
    subject: Optional[str] = Field(default=None, max_length=500)
    body: Optional[str] = Field(default=None, max_length=50000)


class ArtifactCreateInput(BaseModel):
    kind: str = Field(pattern="^(plan|checklist|timeline|budget)$")
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=500000)
    mime_type: str = Field(default="text/markdown", max_length=120)
    source: str = Field(default="", max_length=1000)
    goal_id: Optional[int] = None
    chat_id: Optional[int] = None


class ArtifactUpdateInput(BaseModel):
    content: str = Field(min_length=1, max_length=500000)
    base_version: int = Field(ge=1)
    actor: str = Field(default="user", pattern="^(user|assistant)$")
    source: str = Field(default="manual edit", max_length=1000)
    confirm_overwrite: bool = False


def upload_limit_bytes() -> int:
    try:
        megabytes = int(DB.setting("max_upload_mb", "200") or 200)
    except ValueError:
        megabytes = 200
    return max(1, min(megabytes, 2048)) * 1024 * 1024


async def save_upload_to_temp(file: UploadFile, suffix: str, limit_bytes: Optional[int] = None) -> Path:
    limit = limit_bytes if limit_bytes is not None else upload_limit_bytes()
    total = 0
    temp = NamedTemporaryFile(suffix=suffix, delete=False)
    path = Path(temp.name)
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise HTTPException(413, f"文件超过本机上传上限（{limit // 1024 // 1024} MB）")
            temp.write(chunk)
        temp.flush()
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        temp.close()


def sync_email_accounts(refresh: bool = False) -> dict:
    try:
        SAFETY.require("read", connector="email")
    except ApprovalError as exc:
        return {"accounts": [], "messages": 0, "attachments": 0, "disabled": True, "error": str(exc)}
    accounts = DB.rows("SELECT * FROM email_accounts WHERE enabled=1 ORDER BY id")
    result = {"accounts": [], "messages": 0, "attachments": 0}
    for account in accounts:
        item = {"name": account["name"], "username": account["username"], "ok": False, "count": 0}
        try:
            connector = ImapConnector(account["host"], account["username"], SECRETS.decrypt(account["authorization_code"]), account["port"])
            messages = connector.recent(20) if refresh else connector.unread(20)
            for message in messages:
                if not refresh and DB.rows("SELECT 1 FROM email_seen WHERE account_id=? AND message_uid=?", (account["id"], message["uid"])):
                    continue
                attachment_records = []
                for attachment in message.get("attachments", []):
                    if attachment.get("skipped"):
                        attachment_records.append({"name": attachment["name"], "skipped": True, "reason": "附件超过读取大小限制"})
                        continue
                    suffix = (Path(attachment["name"]).suffix or mimetypes.guess_extension(attachment.get("content_type", "")) or "")[:16]
                    original_name = attachment["name"] + suffix if not Path(attachment["name"]).suffix and suffix else attachment["name"]
                    temp_path = None
                    try:
                        with NamedTemporaryFile(suffix=suffix, delete=False) as temp:
                            temp.write(attachment["data"])
                            temp_path = Path(temp.name)
                        stored = FILES.ingest(temp_path, original_name)
                        attachment_records.append({
                            "hash": stored["hash"],
                            "name": stored["original_name"],
                            "summary": (stored.get("extracted_text") or "")[:1000],
                            "url": f"/api/files/{stored['hash']}/content",
                        })
                        result["attachments"] += 1
                    except Exception as exc:
                        attachment_records.append({"name": attachment["name"], "skipped": True, "reason": str(exc)[:200]})
                    finally:
                        if temp_path:
                            temp_path.unlink(missing_ok=True)
                SERVICE.ingest_email(message["subject"], message["from"], message["body"], attachment_records, message["uid"])
                with DB.connect() as db:
                    db.execute("INSERT OR IGNORE INTO email_seen(account_id,message_uid,processed_at) VALUES(?,?,datetime('now','localtime'))", (account["id"], message["uid"]))
                item["count"] += 1
            with DB.connect() as db:
                db.execute("UPDATE email_accounts SET last_sync=datetime('now','localtime') WHERE id=?", (account["id"],))
            item["ok"] = True
            result["messages"] += item["count"]
        except Exception as exc:
            item["error"] = str(exc)
        result["accounts"].append(item)
    return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    SERVICE.initialize()
    RUNNER.recover()
    scheduler = None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        morning_hour, morning_minute = map(int, (DB.setting("morning_time", "07:30") or "07:30").split(":"))
        review_hour, review_minute = map(int, (DB.setting("review_time", "22:30") or "22:30").split(":"))
        def scheduled(task):
            def run():
                if not RUNTIME.paused and not RUNTIME.terminating:
                    task()
            return run
        scheduler.add_job(scheduled(REPORTS.morning), "cron", hour=morning_hour, minute=morning_minute, id="morning")
        scheduler.add_job(scheduled(REPORTS.evening), "cron", hour=review_hour, minute=review_minute, id="evening")
        scheduler.add_job(scheduled(REPORTS.weekly), "cron", day_of_week="sun", hour=23, minute=0, id="weekly")
        scheduler.add_job(scheduled(sync_email_accounts), "interval", minutes=30, id="email-sync", max_instances=1)
        scheduler.add_job(scheduled(MEMORY.sync_index), "interval", seconds=15, id="memory-index", max_instances=1)
        scheduler.add_job(scheduled(RUNNER.wake_due), "interval", minutes=1, id="task-runner", max_instances=1)
        scheduler.add_job(scheduled(RUNNER.wake_events), "interval", seconds=15, id="event-runner", max_instances=1)
        scheduler.start()
    except ImportError:
        pass
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="第二大脑", version=APP_VERSION, lifespan=lifespan)

PUBLIC_API_PATHS = {"/api/health", "/api/auth/status", "/api/auth/pair", "/api/auth/local-token"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _parse_host(value: str, default_port: int = 80) -> Optional[tuple[str, int]]:
    """Return a normalized host and port, rejecting malformed Host values."""
    try:
        parsed = urlsplit("//" + value)
        if parsed.hostname is None or parsed.username is not None or parsed.password is not None:
            return None
        if parsed.path or parsed.query or parsed.fragment:
            return None
        host = parsed.hostname.rstrip(".").lower()
        port = parsed.port if parsed.port is not None else default_port
        if not 1 <= port <= 65535:
            return None
        return host, port
    except ValueError:
        return None


def _allowed_host(value: str) -> bool:
    parsed = _parse_host(value)
    return bool(parsed and AccessControl.is_trusted_network(parsed[0]))


def _same_origin(origin: str, host_header: str, scheme: str) -> bool:
    try:
        if origin == "null":
            return False
        origin_parts = urlsplit(origin)
        if origin_parts.scheme.lower() != scheme.lower() or origin_parts.username or origin_parts.password:
            return False
        if origin_parts.path not in {"", "/"} or origin_parts.query or origin_parts.fragment:
            return False
        default_port = 443 if scheme.lower() == "https" else 80
        origin_host = _parse_host(origin_parts.netloc, default_port)
        request_host = _parse_host(host_header, default_port)
        if not origin_host or not request_host:
            return False
        origin_port = origin_parts.port or default_port
    except ValueError:
        return False
    # Host headers omit the scheme's default port.  Normalize both sides
    # before comparing so `http://localhost` matches `Host: localhost:80`.
    request_port = request_host[1]
    return origin_host[0] == request_host[0] and origin_port == request_port


def request_token(request: Request) -> Optional[str]:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.headers.get("x-second-brain-token") or request.cookies.get("second_brain_token")


@app.middleware("http")
async def protect_personal_api(request: Request, call_next):
    path = request.url.path
    host_header = request.headers.get("host", "")
    if not _allowed_host(host_header):
        return JSONResponse({"detail": "不接受此 Host；请通过 localhost 或本机/局域网 IP 访问"}, status_code=400)

    origin = request.headers.get("origin")
    if origin and not _same_origin(origin, host_header, request.url.scheme):
        return JSONResponse({"detail": "请求来源与当前站点不一致"}, status_code=403)

    authorization = request.headers.get("authorization", "")
    cookie_token = request.cookies.get("second_brain_token")
    if request.method not in SAFE_METHODS and cookie_token and not authorization and not origin:
        return JSONResponse({"detail": "使用浏览器 Cookie 的写请求必须提供同源 Origin"}, status_code=403)

    if path.startswith("/api/") and not ACCESS.is_trusted_network(request.client.host if request.client else None):
        return JSONResponse({"detail": "只允许本机或可信局域网设备访问"}, status_code=403)
    if not path.startswith("/api/") or path in PUBLIC_API_PATHS:
        return await call_next(request)
    if not ACCESS.verify(request_token(request)):
        return JSONResponse(
            {"detail": "此设备尚未配对，请先在电脑设置页生成配对码"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if RUNTIME.paused and request.method not in {"GET", "HEAD", "OPTIONS"} and not path.startswith("/api/service/"):
        return JSONResponse({"detail": "核心服务已暂停；请在电脑网页端恢复服务", "code": "service_paused"}, status_code=423)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION, "state": RUNTIME.status(APP_VERSION, False)["state"]}


def local_service_control(request: Request) -> None:
    if not ACCESS.is_loopback(request.client.host if request.client else None):
        raise HTTPException(403, "服务控制仅允许在电脑本机网页端操作")


@app.get("/api/service/status")
def service_status(request: Request):
    local = ACCESS.is_loopback(request.client.host if request.client else None)
    return RUNTIME.status(APP_VERSION, local)


@app.post("/api/service/pause")
def service_pause(request: Request):
    local_service_control(request)
    RUNTIME.pause()
    return RUNTIME.status(APP_VERSION, True)


@app.post("/api/service/resume")
def service_resume(request: Request):
    local_service_control(request)
    RUNTIME.resume()
    return RUNTIME.status(APP_VERSION, True)


@app.post("/api/service/terminate")
def service_terminate(request: Request):
    local_service_control(request)
    RUNTIME.request_termination()
    return RUNTIME.status(APP_VERSION, True)


@app.get("/api/auth/status")
def auth_status(request: Request):
    local = ACCESS.is_loopback(request.client.host if request.client else None)
    authenticated = ACCESS.verify(request_token(request))
    return {"authenticated": authenticated, "local": local, "requires_pairing": not authenticated}


@app.get("/api/auth/local-token")
def auth_local_token(request: Request):
    if not ACCESS.is_loopback(request.client.host if request.client else None):
        raise HTTPException(403, "本机令牌只能由电脑本机获取")
    token = ACCESS.browser_token()
    response = JSONResponse({"token": token})
    response.set_cookie("second_brain_token", token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 365)
    return response


@app.post("/api/auth/pair")
def auth_pair(body: PairInput):
    try:
        result = ACCESS.pair(body.code, body.device_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    response = JSONResponse(result)
    response.set_cookie(
        "second_brain_token",
        result["token"],
        httponly=True,
        samesite="strict",
        max_age=60 * 60 * 24 * 365,
    )
    return response


@app.post("/api/auth/pairing-code")
def auth_pairing_code(request: Request):
    if not ACCESS.is_loopback(request.client.host if request.client else None):
        raise HTTPException(403, "只能在电脑本机生成配对码")
    return ACCESS.create_pairing_code()


@app.get("/api/auth/devices")
def auth_devices(request: Request):
    if not ACCESS.is_loopback(request.client.host if request.client else None):
        raise HTTPException(403, "只能在电脑本机管理设备")
    return {"devices": ACCESS.devices()}


@app.delete("/api/auth/devices/{token_id}")
def auth_device_revoke(token_id: int, request: Request):
    if not ACCESS.is_loopback(request.client.host if request.client else None):
        raise HTTPException(403, "只能在电脑本机管理设备")
    if not ACCESS.revoke(token_id):
        raise HTTPException(404, "设备不存在或已撤销")
    return {"ok": True}


@app.post("/api/chat")
def chat(body: ChatInput):
    try:
        return SERVICE.chat(body.message, body.provider, body.model, body.file_hashes, body.file_note)
    except ModelError as exc:
        raise HTTPException(429 if exc.code == "rate_limited" else 503, detail={"code": exc.code, "message": exc.user_message, "retryable": exc.retryable})


@app.post("/api/chat/stream")
def chat_stream(body: ChatInput):
    def events():
        try:
            for item in SERVICE.chat_stream(body.message, body.provider, body.model, body.file_hashes, body.file_note):
                yield f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
        except ModelError as exc:
            payload = {"code": exc.code, "message": exc.user_message, "retryable": exc.retryable}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception:
            payload = {"code": "internal_error", "message": "处理失败，请重试；若持续出现请查看服务日志", "retryable": True}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/chats")
def chats(limit: int = 100, q: str = ""):
    return {"chats": SERVICE.chat_history(limit, q)}


@app.get("/api/chats/state")
def chat_state():
    return SERVICE.chat_state()


@app.post("/api/chats/{chat_id}/retry-memory")
def retry_chat_memory(chat_id: int):
    try:
        return SERVICE.retry_chat_memory(chat_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.delete("/api/chats/{chat_id}")
def chat_delete(chat_id: int, body: ChatDeleteInput):
    try:
        return SERVICE.delete_chat(chat_id, body.delete_memory)
    except KeyError:
        raise HTTPException(404, "聊天记录不存在")


@app.get("/api/interview")
def interview():
    return {"questions": SERVICE.interview_questions()}


@app.get("/api/profile/status")
def profile_status():
    return SERVICE.profile_status()


@app.post("/api/interview/complete")
def interview_complete():
    return SERVICE.complete_interview()


@app.get("/api/memory")
def memory_list():
    return {"files": list(MEMORY.storage.list(".md")), "candidates": MEMORY.pending_facts()}


@app.get("/api/memory-candidates")
def memory_candidates():
    return {"candidates": MEMORY.pending_facts()}


@app.post("/api/memory-candidates/{candidate_id}/resolve")
def memory_decision(candidate_id: int, body: MemoryDecision):
    try:
        MEMORY.resolve_fact(candidate_id, body.accept)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}


@app.get("/api/memory/{path:path}")
def memory_get(path: str):
    try:
        return {"path": path, "content": MEMORY.storage.read_text(path)}
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "记忆文件不存在")


@app.put("/api/memory/{path:path}")
def memory_put(path: str, body: MemoryInput):
    try:
        MEMORY.edit(path, body.content)
    except Exception as exc:
        raise HTTPException(400, f"保存失败：{exc}")
    return {"ok": True}


@app.get("/api/search")
def search(q: str):
    return {"results": MEMORY.search(q)}


@app.get("/api/goals")
def goals(include_closed: bool = True):
    return {"goals": GOALS.list_goals(include_closed)}


@app.post("/api/goals")
def goal_create(body: GoalCreateInput, x_idempotency_key: Optional[str] = Header(default=None)):
    try:
        return GOALS.create_goal(body.title, body.description, body.due_at, x_idempotency_key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/goal-templates")
def goal_templates():
    return {"templates": GOALS.templates()}


@app.post("/api/goal-templates/{template_id}")
def goal_template_create(template_id: str, body: TemplateCreateInput, x_idempotency_key: Optional[str] = Header(default=None)):
    try:
        return GOALS.create_from_template(template_id, title=body.title, due_at=body.due_at, idempotency_key=x_idempotency_key)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/goals/{goal_id}")
def goal_get(goal_id: int):
    try:
        return GOALS.goal(goal_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.put("/api/goals/{goal_id}")
def goal_update(goal_id: int, body: GoalUpdateInput):
    try:
        return GOALS.update_goal(goal_id, body.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/goals/{goal_id}/status")
def goal_status(goal_id: int, body: GoalStatusInput):
    try:
        return GOALS.set_goal_status(goal_id, body.status)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/goals/{goal_id}/events")
def goal_events(goal_id: int, limit: int = 100):
    try:
        GOALS.goal(goal_id)
        return {"events": GOALS.events(goal_id, limit)}
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/goals/{goal_id}/tasks")
def task_create(goal_id: int, body: TaskCreateInput, x_idempotency_key: Optional[str] = Header(default=None)):
    try:
        return GOALS.create_task(
            goal_id, body.title, body.description, body.due_at, body.position,
            x_idempotency_key, body.schedule, body.next_run_at, body.max_retries,
            body.interval_minutes, body.event_source, body.event_kind, body.enabled,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.put("/api/tasks/{task_id}")
def task_update(task_id: int, body: TaskUpdateInput):
    try:
        return GOALS.update_task(task_id, body.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/tasks/{task_id}/status")
def task_status(task_id: int, body: TaskStatusInput):
    try:
        return GOALS.set_task_status(task_id, body.status)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))

@app.post("/api/tasks/{task_id}/runs")
def task_run_start(task_id: int):
    try: return RUNNER.start(task_id)
    except KeyError as exc: raise HTTPException(404, str(exc))
    except ValueError as exc: raise HTTPException(409, str(exc))

@app.post("/api/task-runs/{run_id}/finish")
def task_run_finish(run_id: int, body: TaskRunFinishInput):
    try: return RUNNER.finish(run_id, body.success, body.result, body.error)
    except KeyError as exc: raise HTTPException(404, str(exc))


@app.post("/api/task-runs/{run_id}/pause")
def task_run_pause(run_id: int):
    try:
        return RUNNER.pause(run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/activity")
def task_activity(goal_id: Optional[int] = None, limit: int = 100):
    return {"activity": RUNNER.activity(goal_id, limit)}


@app.get("/api/calendar/local")
def local_calendar_events():
    return {"events": ACTIONS.calendar_events()}


@app.get("/api/calendar/conflicts")
def calendar_conflicts(start_at: str, end_at: str):
    try:
        return {"conflicts": ACTIONS.calendar_conflicts(start_at, end_at)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/calendar/suggestions")
def calendar_suggestion(body: CalendarSuggestionInput, x_idempotency_key: Optional[str] = Header(default=None)):
    try:
        return ACTIONS.suggest_calendar(body.model_dump(exclude={"goal_id"}), goal_id=body.goal_id, idempotency_key=x_idempotency_key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/calendar/suggestions/{approval_id}/execute")
def calendar_suggestion_execute(approval_id: int):
    try:
        return ACTIONS.execute_calendar(approval_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ApprovalError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/email/drafts")
def email_drafts():
    return {"drafts": ACTIONS.drafts()}


@app.post("/api/email/drafts")
def email_draft_create(body: EmailDraftCreateInput):
    try:
        return ACTIONS.create_draft(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.put("/api/email/drafts/{draft_id}")
def email_draft_update(draft_id: int, body: EmailDraftUpdateInput):
    try:
        return ACTIONS.update_draft(draft_id, body.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.delete("/api/email/drafts/{draft_id}")
def email_draft_delete(draft_id: int):
    try:
        ACTIONS.delete_draft(draft_id)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/artifacts")
def artifact_list(goal_id: Optional[int] = None):
    return {"artifacts": ARTIFACTS.list(goal_id)}


@app.post("/api/artifacts")
def artifact_create(body: ArtifactCreateInput):
    try:
        return ARTIFACTS.create(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/artifacts/{artifact_id}")
def artifact_get(artifact_id: int):
    try:
        return ARTIFACTS.get(artifact_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.put("/api/artifacts/{artifact_id}")
def artifact_update(artifact_id: int, body: ArtifactUpdateInput):
    try:
        return ARTIFACTS.update(artifact_id, **body.model_dump())
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ArtifactConflict as exc:
        raise HTTPException(409, str(exc))


@app.delete("/api/artifacts/{artifact_id}")
def artifact_delete(artifact_id: int):
    try:
        ARTIFACTS.delete(artifact_id)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/artifacts/{artifact_id}/preview", response_class=HTMLResponse)
def artifact_preview(artifact_id: int):
    try:
        return HTMLResponse(ARTIFACTS.render_html(artifact_id), headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/artifacts/{artifact_id}/export")
def artifact_export(artifact_id: int, format: str = "md"):
    try:
        content, media_type, filename = ARTIFACTS.export(artifact_id, format)
        return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/approvals")
def approval_list(status: str = "", limit: int = 100):
    return {"approvals": SAFETY.list(status, limit)}


@app.post("/api/approvals")
def approval_create(body: ApprovalCreateInput, x_idempotency_key: Optional[str] = Header(default=None)):
    try:
        return SAFETY.request(
            body.action_type, body.level, body.summary, connector=body.connector,
            goal_id=body.goal_id, target=body.target, exact_payload=body.exact_payload,
            expires_minutes=body.expires_minutes, idempotency_key=x_idempotency_key,
        )
    except ApprovalError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/approvals/{approval_id}/decision")
def approval_decide(approval_id: int, body: ApprovalDecisionInput):
    try:
        return SAFETY.decide(approval_id, body.decision, edited_payload=body.edited_payload)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ApprovalError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/connectors/permissions")
def connector_permissions():
    return {"connectors": SAFETY.connectors()}


@app.put("/api/connectors/permissions/{connector}")
def connector_permission_update(connector: str, body: ConnectorPermissionInput):
    try:
        return SAFETY.set_connector(connector, body.enabled)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/audit")
def action_audit(goal_id: Optional[int] = None, connector: str = "", date_from: str = "", date_to: str = "", limit: int = 200):
    return {
        "audit": SAFETY.audit(goal_id=goal_id, connector=connector, date_from=date_from, date_to=date_to, limit=limit),
        "integrity": SAFETY.verify_audit_chain(),
    }


@app.get("/api/audit/export")
def action_audit_export(goal_id: Optional[int] = None, connector: str = "", date_from: str = "", date_to: str = ""):
    payload = {
        "version": APP_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "integrity": SAFETY.verify_audit_chain(),
        "audit": SAFETY.audit(goal_id=goal_id, connector=connector, date_from=date_from, date_to=date_to, limit=1000),
    }
    return JSONResponse(payload, headers={"Content-Disposition": 'attachment; filename="second-brain-audit.json"'})


@app.post("/api/forget")
def forget_request(body: ForgetInput, x_idempotency_key: Optional[str] = Header(default=None)):
    return SAFETY.request(
        "data.forget", "irreversible", f"忘掉与“{body.phrase}”有关的数据",
        connector="", target="本机记忆、未来任务与派生索引",
        exact_payload={"phrase": body.phrase, "goal_ids": body.goal_ids},
        expires_minutes=body.expires_minutes, idempotency_key=x_idempotency_key,
    )


@app.post("/api/forget/{approval_id}/execute")
def forget_execute(approval_id: int):
    try:
        approval = SAFETY.claim(approval_id, action_type="data.forget", connector="", actor="forget-service")
        payload = approval["exact_payload"]
        changed = MEMORY.forget(str(payload.get("phrase") or ""))
        goal_ids = [int(value) for value in payload.get("goal_ids", [])]
        cancelled = 0
        if goal_ids:
            placeholders = ",".join("?" for _ in goal_ids)
            with DB.connect() as db:
                cursor = db.execute(
                    f"UPDATE tasks SET enabled=0,status='cancelled',updated_at=datetime('now','localtime') "
                    f"WHERE goal_id IN ({placeholders}) AND status IN ('pending','in_progress','blocked')", tuple(goal_ids),
                )
                cancelled = cursor.rowcount
        result = {"removed_memory_lines": changed, "cancelled_future_tasks": cancelled}
        SAFETY.finish(approval_id, success=True, result=result, actor="forget-service")
        return result
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ApprovalError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        try:
            SAFETY.finish(approval_id, success=False, error=str(exc), actor="forget-service")
        except Exception:
            pass
        raise HTTPException(500, f"遗忘操作失败：{exc}")


@app.get("/api/providers")
def providers():
    return {"templates": PROVIDER_TEMPLATES, "providers": MODELS.providers(), "routes": DB.rows("SELECT * FROM model_routes ORDER BY task")}


@app.post("/api/providers")
def provider_save(body: ProviderInput):
    try:
        MODELS.save_provider(body.name, body.base_url, body.api_key, body.models, body.kind, body.consumption_level)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.delete("/api/providers/{provider_id}")
def provider_delete(provider_id: int):
    name = MODELS.delete_provider(provider_id)
    if not name:
        raise HTTPException(404, "供应商不存在")
    return {"ok": True, "name": name}


@app.post("/api/model-prices")
def model_price_save(body: ModelPriceInput):
    try:
        MODELS.save_price(body.provider, body.model, body.input_per_million, body.output_per_million, body.currency)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.get("/api/cost-settings")
def cost_settings():
    return {"usd_cny_rate": float(DB.setting("usd_cny_rate", "7.20") or 7.20)}


@app.post("/api/cost-settings")
def cost_settings_save(body: CostSettingsInput):
    try:
        MODELS.set_usd_cny_rate(body.usd_cny_rate)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.get("/api/email/accounts")
def email_accounts():
    return {"accounts": DB.rows("SELECT id,name,host,port,username,enabled,last_sync FROM email_accounts ORDER BY id")}


@app.post("/api/email/accounts")
def email_account_save(body: EmailAccountInput):
    if not body.authorization_code:
        existing = DB.rows("SELECT authorization_code FROM email_accounts WHERE username=?", (body.username,))
        if not existing:
            raise HTTPException(400, "首次连接必须填写邮箱授权码")
        authorization_code = existing[0]["authorization_code"]
    else:
        authorization_code = SECRETS.encrypt(body.authorization_code)
    with DB.connect() as db:
        db.execute(
            "INSERT INTO email_accounts(name,host,port,username,authorization_code,enabled) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET name=excluded.name,host=excluded.host,port=excluded.port,authorization_code=excluded.authorization_code,enabled=excluded.enabled",
            (body.name, body.host, body.port, body.username, authorization_code, int(body.enabled)),
        )
    return {"ok": True}


@app.get("/api/location/settings")
def location_settings():
    default = DB.rows("SELECT label,latitude,longitude,enabled,updated_at FROM locations WHERE source='default'")
    return {
        "enabled": DB.setting("location_enabled", "0") == "1",
        "default": default[0] if default else None,
        "map_provider": DB.setting("map_provider", "amap"),
        "has_map_api_key": bool(DB.setting("map_api_key", "")),
        "has_map_security_code": bool(DB.setting("map_security_code", "")),
        "has_map_web_service_key": bool(DB.setting("map_web_service_key", "")),
        "sources": DB.rows("SELECT source,label,latitude,longitude,enabled,updated_at FROM locations ORDER BY updated_at DESC"),
    }


@app.post("/api/location/settings")
def location_settings_save(body: LocationSettingsInput):
    if body.map_provider != "amap":
        raise HTTPException(400, "当前版本仅支持高德地图")
    if (body.default_latitude is None) != (body.default_longitude is None):
        raise HTTPException(400, "默认位置的经纬度需要同时填写")
    DB.set_setting("location_enabled", "1" if body.enabled else "0")
    DB.set_setting("map_provider", body.map_provider)
    if body.map_api_key:
        DB.set_setting("map_api_key", SECRETS.encrypt(body.map_api_key))
    if body.map_security_code:
        DB.set_setting("map_security_code", SECRETS.encrypt(body.map_security_code))
    if body.map_web_service_key:
        DB.set_setting("map_web_service_key", SECRETS.encrypt(body.map_web_service_key))
    with DB.connect() as db:
        db.execute(
            "INSERT INTO locations(source,label,latitude,longitude,enabled,updated_at) VALUES('default',?,?,?,?,datetime('now','localtime')) "
            "ON CONFLICT(source) DO UPDATE SET label=excluded.label,latitude=excluded.latitude,longitude=excluded.longitude,enabled=excluded.enabled,updated_at=excluded.updated_at",
            (body.default_label.strip(), body.default_latitude, body.default_longitude, int(body.enabled)),
        )
    return {"ok": True}


@app.post("/api/location/report")
def location_report(body: LocationReportInput):
    if body.source not in {"browser", "android"}:
        raise HTTPException(400, "位置来源必须是浏览器或 Android")
    if not (-90 <= body.latitude <= 90 and -180 <= body.longitude <= 180):
        raise HTTPException(400, "经纬度超出范围")
    with DB.connect() as db:
        db.execute(
            "INSERT INTO locations(source,label,latitude,longitude,enabled,updated_at) VALUES(?,?,?,?,?,datetime('now','localtime')) "
            "ON CONFLICT(source) DO UPDATE SET label=excluded.label,latitude=excluded.latitude,longitude=excluded.longitude,enabled=excluded.enabled,updated_at=excluded.updated_at",
            (body.source, body.label.strip(), body.latitude, body.longitude, int(body.enabled)),
        )
    return {"ok": True, "source": body.source}


@app.get("/api/map/config")
def map_config():
    key = DB.setting("map_api_key", "") or ""
    security = DB.setting("map_security_code", "") or ""
    return {
        "provider": DB.setting("map_provider", "amap"),
        "api_key": SECRETS.decrypt(key),
        "security_code": SECRETS.decrypt(security),
    }


@app.get("/api/notification-settings")
def notification_settings():
    return {
        "enabled": DB.setting("notifications_enabled", "0") == "1",
        "quiet_start": DB.setting("quiet_start", "22:30") or "22:30",
        "quiet_end": DB.setting("quiet_end", "07:30") or "07:30",
        "dedup_minutes": int(DB.setting("notification_dedup_minutes", "60") or 60),
        "daily_limit": int(DB.setting("notification_daily_limit", "3") or 3),
    }


@app.post("/api/notification-settings")
def notification_settings_save(body: NotificationSettingsInput):
    DB.set_setting("notifications_enabled", "1" if body.enabled else "0")
    DB.set_setting("quiet_start", body.quiet_start)
    DB.set_setting("quiet_end", body.quiet_end)
    DB.set_setting("notification_dedup_minutes", str(body.dedup_minutes))
    DB.set_setting("notification_daily_limit", str(body.daily_limit))
    return {"ok": True, **notification_settings()}


@app.get("/api/web-search/settings")
def web_search_settings():
    return {
        "enabled": DB.setting("web_search_enabled", "0") == "1",
        "provider": DB.setting("web_search_provider", "bocha") or "bocha",
        "has_api_key": bool(DB.setting("bocha_search_api_key", "")),
        "searxng_url": DB.setting("searxng_url", "") or "",
    }


@app.post("/api/web-search/settings")
def web_search_settings_save(body: WebSearchSettingsInput):
    if body.provider not in {"bocha", "searxng"}:
        raise HTTPException(400, "联网搜索供应商必须是博查搜索或 SearXNG")
    if body.provider == "searxng" and body.searxng_url:
        from urllib.parse import urlparse
        parsed = urlparse(body.searxng_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(400, "SearXNG 地址必须是完整的 HTTP 或 HTTPS 地址")
    DB.set_setting("web_search_enabled", "1" if body.enabled else "0")
    DB.set_setting("web_search_provider", body.provider)
    DB.set_setting("searxng_url", body.searxng_url.strip())
    if body.api_key:
        DB.set_setting("bocha_search_api_key", SECRETS.encrypt(body.api_key))
    return {"ok": True}


@app.get("/api/notifications")
def notifications(after_id: int = 0, limit: int = 50):
    return {"notifications": NOTIFICATIONS.since(after_id, limit)}


@app.post("/api/email/sync")
def email_sync(refresh: bool = False):
    return sync_email_accounts(refresh)


@app.post("/api/routes")
def route_save(body: RouteInput):
    MODELS.set_route(Route(**body.model_dump()))
    return {"ok": True}


@app.get("/api/usage")
def usage():
    MODELS.seed_known_prices()
    rows = DB.rows("SELECT COALESCE(SUM(prompt_tokens),0) prompt_tokens,COALESCE(SUM(completion_tokens),0) completion_tokens,COALESCE(SUM(estimated_cost),0) estimated_cost FROM ai_calls")
    breakdown = DB.rows("SELECT provider,model,SUM(prompt_tokens) prompt_tokens,SUM(completion_tokens) completion_tokens,SUM(estimated_cost) estimated_cost FROM ai_calls GROUP BY provider,model HAVING SUM(prompt_tokens)+SUM(completion_tokens)>0 ORDER BY estimated_cost DESC")
    return {**rows[0], "breakdown": breakdown}


@app.get("/api/usage/activity")
def usage_activity(days: int = 365):
    days = max(7, min(days, 730))
    end = date.today()
    start = end - timedelta(days=days - 1)
    rows = DB.rows(
        "SELECT substr(created_at,1,10) day,COALESCE(SUM(prompt_tokens),0) prompt_tokens,"
        "COALESCE(SUM(completion_tokens),0) completion_tokens,COALESCE(SUM(estimated_cost),0) estimated_cost "
        "FROM ai_calls WHERE substr(created_at,1,10)>=? AND substr(created_at,1,10)<=? GROUP BY day",
        (start.isoformat(), end.isoformat()),
    )
    by_day = {row["day"]: row for row in rows}
    activity = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        row = by_day.get(day, {})
        prompt = int(row.get("prompt_tokens", 0))
        completion = int(row.get("completion_tokens", 0))
        activity.append({
            "date": day,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "estimated_cost": float(row.get("estimated_cost", 0)),
        })
    totals = DB.rows(
        "SELECT COALESCE(SUM(prompt_tokens),0) prompt_tokens,COALESCE(SUM(completion_tokens),0) completion_tokens,"
        "COALESCE(SUM(estimated_cost),0) estimated_cost FROM ai_calls"
    )[0]
    return {"start": start.isoformat(), "end": end.isoformat(), "days": activity, "totals": totals}


@app.post("/api/ingest/sms")
def ingest_sms(body: SmsInput):
    try:
        SAFETY.require("read", connector="sms")
    except ApprovalError as exc:
        raise HTTPException(403, str(exc))
    return SERVICE.ingest_sms(body.text, body.sender)


@app.post("/api/ingest/notification")
def ingest_notification(body: NotificationInput):
    try:
        SAFETY.require("read", connector="notification")
    except ApprovalError as exc:
        raise HTTPException(403, str(exc))
    return SERVICE.ingest_notification(body.package, body.title, body.text)


@app.post("/api/ingest/calendar")
def ingest_calendar(body: CalendarSyncInput):
    try:
        SAFETY.require("read", connector="calendar")
        return SERVICE.ingest_calendar_events(
            [item.model_dump() for item in body.events], body.window_start, body.window_end
        )
    except ApprovalError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/ingest/health")
def ingest_health(body: HealthSyncInput):
    try:
        SAFETY.require("read", connector="health")
        result = HEALTH.sync_samples([item.model_dump() for item in body.samples], body.source)
        if result["imported"]:
            EVENTS.publish("health", "synced", {"title": "Android 健康数据同步", **result}, "paired_device")
        return result
    except ApprovalError as exc:
        raise HTTPException(403, str(exc))


@app.post("/api/events")
def publish_event(body: EventInput):
    try:
        if body.source in {"email", "calendar", "sms", "notification", "location", "health", "files"}:
            SAFETY.require("read", connector=body.source)
    except ApprovalError as exc:
        raise HTTPException(403, str(exc))
    return EVENTS.publish(body.source, body.kind, body.payload, body.trust)


@app.get("/api/events")
def events(source: Optional[str] = None, limit: int = 100):
    limit = max(1, min(limit, 500))
    if source:
        rows = DB.rows("SELECT id,created_at,source,kind,payload,status FROM events WHERE source=? ORDER BY id DESC LIMIT ?", (source, limit))
    else:
        rows = DB.rows("SELECT id,created_at,source,kind,payload,status FROM events ORDER BY id DESC LIMIT ?", (limit,))
    for row in rows:
        row["payload"] = json.loads(row["payload"] or "{}")
    return {"events": rows}


@app.get("/api/health/summary")
def health_summary(days: int = 14):
    return HEALTH.summary(days)


@app.post("/api/health/import")
async def health_import(file: UploadFile = File(...)):
    try:
        SAFETY.require("read", connector="health")
    except ApprovalError as exc:
        raise HTTPException(403, str(exc))
    suffix = Path(file.filename or "health-data").suffix.lower()
    if suffix not in {".zip", ".xml", ".csv", ".json"}:
        raise HTTPException(400, "请选择 Apple 健康 XML/ZIP，或小米运动 CSV/JSON/ZIP")
    temp_path = await save_upload_to_temp(file, suffix)
    try:
        result = HEALTH.import_file(temp_path, file.filename or "health-data")
        EVENTS.publish("health", "imported", {"title": file.filename or "健康数据", **result}, "local")
        return result
    except (ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, f"健康数据无法识别：{exc}")
    finally:
        temp_path.unlink(missing_ok=True)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    try:
        SAFETY.require("read", connector="files")
    except ApprovalError as exc:
        raise HTTPException(403, str(exc))
    suffix = Path(file.filename or "upload").suffix
    temp_path = await save_upload_to_temp(file, suffix)
    try:
        result = FILES.ingest(temp_path, file.filename or "upload")
        if not result.get("duplicate"):
            EVENTS.publish("file", "analyzed", {
                "title": result.get("original_name", file.filename or "文件"),
                "hash": result.get("hash", ""),
                "summary": str(result.get("extracted_text", ""))[:1000],
            }, "local")
        return result
    finally:
        temp_path.unlink(missing_ok=True)


@app.get("/api/files")
def file_list(limit: int = 100):
    limit = max(1, min(limit, 500))
    return {"files": DB.rows("SELECT hash,original_name,stored_path,created_at,extracted_text FROM files ORDER BY created_at DESC LIMIT ?", (limit,))}


@app.get("/api/files/{digest}/content")
def file_content(digest: str):
    rows = DB.rows("SELECT original_name,stored_path FROM files WHERE hash=?", (digest,))
    if not rows:
        raise HTTPException(404, "文件不存在")
    path = (ROOT / rows[0]["stored_path"]).resolve()
    files_root = (ROOT / "files").resolve()
    if files_root not in path.parents or not path.is_file():
        raise HTTPException(404, "归档原件不存在")
    media_type = mimetypes.guess_type(rows[0]["original_name"])[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/files/{digest}/preview", response_class=HTMLResponse)
def file_preview(digest: str):
    rows = DB.rows("SELECT original_name,extracted_text FROM files WHERE hash=?", (digest,))
    if not rows:
        raise HTTPException(404, "文件不存在")
    return HTMLResponse(
        safe_file_preview(rows[0]["original_name"], rows[0]["extracted_text"]),
        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; frame-src 'none'", "Cache-Control": "private, no-store"},
    )


@app.delete("/api/files/{digest}")
def file_delete(digest: str):
    try:
        return FILES.delete(digest)
    except KeyError:
        raise HTTPException(404, "文件不存在")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/files/{digest}/reanalyze")
def file_reanalyze(digest: str):
    try:
        return FILES.reanalyze(digest)
    except KeyError:
        raise HTTPException(404, "文件不存在")
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/reports/{kind}")
def report(kind: str):
    functions = {"morning": REPORTS.morning, "evening": REPORTS.evening, "weekly": REPORTS.weekly}
    if kind not in functions:
        raise HTTPException(404, "未知报告类型")
    return {"content": functions[kind]()}


@app.get("/api/reports")
def reports():
    return {"reports": DB.rows("SELECT id,created_at,kind,content FROM reports ORDER BY id DESC LIMIT 30")}


WEB = RESOURCE_ROOT / "web"
app.mount("/assets", StaticFiles(directory=str(WEB)), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str = ""):
    # The workspace is a local single-page app.  Never let a browser retain an
    # old HTML shell after an in-place desktop update; its asset revisions then
    # reliably select the matching JavaScript and styles.
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})
