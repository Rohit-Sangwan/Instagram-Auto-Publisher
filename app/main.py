import hmac
import os
import re
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psutil
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from filelock import FileLock
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session as DatabaseSession
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.staticfiles import StaticFiles

from app.assets import CAROUSEL_LIMIT, MediaError, budget, checksum, run, stage
from app.db import (MEDIA, ROOT, Account, Activity, Admin, Asset, Download, LoginSession, Mapping, Media,
                    Publish, Published, Schedule, Session, Settings, Source, System, Usage, log)
from app.meta import BASIC, PUBLISH, Instagram, MetaError
from app.security import cipher, digest, passwords, random_token, signature, verify
from app.worker import next_slot, recover, scheduler

COOKIE = "publisher_session"
KINDS = ["IMAGE", "VIDEO", "REELS", "CAROUSEL_ALBUM"]
NAME = re.compile(r"[a-f0-9]{32}\.(jpg|mp4)")
PUBLIC = os.getenv("PUBLIC_URL", "http://localhost:5173").rstrip("/")
SECURE = PUBLIC.startswith("https://")
DUMMY = passwords.hash(random_token())


@asynccontextmanager
async def lifespan(app):
    with FileLock(str(ROOT / "publisher.lock"), timeout=0):
        async with running(app):
            yield


@asynccontextmanager
async def running(app):
    if not SECURE and urlsplit(PUBLIC).hostname not in ("localhost", "127.0.0.1"):
        raise RuntimeError("PUBLIC_URL must use HTTPS outside local development")
    if len(os.environ["MEDIA_SECRET"]) < 32:
        raise RuntimeError("MEDIA_SECRET must contain at least 32 characters")
    cipher()
    command.upgrade(Config("alembic.ini"), "head")
    with Session() as db:
        if not db.scalar(select(Admin.id).limit(1)):
            password = os.environ["ADMIN_PASSWORD"]
            if len(password) < 14:
                raise RuntimeError("ADMIN_PASSWORD must contain at least 14 characters")
            db.add(Admin(username=os.getenv("ADMIN_USERNAME", "admin"), password=passwords.hash(password)))
        if not db.get(Settings, 1):
            workers = min(8, max(1, int(os.getenv("DOWNLOAD_WORKERS", "1"))))
            db.add_all([Settings(id=1, downloads=workers), Schedule(id=1)])
        db.commit()
    recover()
    service = scheduler()
    app.state.scheduler = service
    try:
        yield
    finally:
        service.shutdown()


app = FastAPI(title="Instagram Auto Publisher", lifespan=lifespan, openapi_url=None,
              docs_url=None, redoc_url=None)


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "private, no-store"
    return response


def database():
    with Session() as db:
        yield db


DB = Annotated[DatabaseSession, Depends(database)]


def require_origin(request):
    if request.headers.get("origin") != PUBLIC:
        raise HTTPException(403, "Invalid request origin")


def authenticated(request: Request, db: DB):
    cookie = request.cookies.get(COOKIE, "")
    session = db.scalar(select(LoginSession).where(LoginSession.digest == digest(cookie))) if cookie else None
    if not session or session.expires <= time.time():
        raise HTTPException(401, "Sign in to continue")
    if request.method not in ("GET", "HEAD"):
        require_origin(request)
        if not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), session.csrf.encode()):
            raise HTTPException(403, "Invalid CSRF token")
    return session


Auth = Annotated[LoginSession, Depends(authenticated)]


def item(db, model, identifier):
    result = db.get(model, identifier)
    if result is None:
        raise HTTPException(404, "Record not found")
    return result


def fields(record, keys):
    return {key: getattr(record, key) for key in keys.split()}


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


@app.get("/api/health")
def health(db: DB):
    db.execute(text("SELECT 1"))
    if not app.state.scheduler.running:
        raise HTTPException(503, "Scheduler is stopped")
    return {"status": "ok", "scheduler": True}


@app.post("/api/login")
def login(data: Login, request: Request, response: Response, db: DB):
    require_origin(request)
    now = time.time()
    key = "login:" + digest(request.client.host if request.client else "unknown")
    # Serialize the rate-limit check and reservation across concurrent requests.
    db.execute(text("BEGIN IMMEDIATE"))
    record = db.scalar(select(System).where(System.key == key))
    attempts = record.value if record and record.value["until"] > now else {"count": 0, "until": now + 900}
    if attempts["count"] >= 8:
        raise HTTPException(429, "Too many sign-in attempts. Try again in 15 minutes.")
    attempts = {**attempts, "count": attempts["count"] + 1}
    if record:
        record.value = attempts
    else:
        db.add(System(key=key, value=attempts))
    db.commit()
    admin = db.scalar(select(Admin).where(Admin.username == data.username))
    if not verify(admin.password if admin else DUMMY, data.password) or not admin:
        raise HTTPException(401, "Incorrect username or password")
    session_id = random_token()
    session = LoginSession(digest=digest(session_id), admin_id=admin.id, expires=now + 43200, csrf=random_token())
    old = request.cookies.get(COOKIE)
    if old:
        db.execute(delete(LoginSession).where(LoginSession.digest == digest(old)))
    db.add(session)
    db.execute(delete(System).where(System.key == key))
    db.commit()
    response.set_cookie(COOKIE, session_id, max_age=43200, httponly=True, secure=SECURE, samesite="lax")
    return {"csrf": session.csrf}


@app.get("/api/session")
def session(auth: Auth):
    return {"csrf": auth.csrf}


@app.post("/api/logout")
def logout(auth: Auth, response: Response, db: DB):
    db.delete(auth)
    db.commit()
    response.delete_cookie(COOKIE, secure=SECURE, httponly=True, samesite="lax")
    return {"ok": True}


@app.get("/api/schema")
def schema(auth: Auth):
    return app.openapi()


@app.post("/api/instagram/connect")
def connect(auth: Auth, db: DB, source_only: bool = False, account_id: int | None = None):
    if not os.getenv("META_APP_ID") or not os.getenv("META_APP_SECRET") or not SECURE:
        raise HTTPException(409, "Configure Meta app credentials and an HTTPS public URL")
    if account_id is not None:
        item(db, Account, account_id)
    state = f"{'source' if source_only else 'publish'}.{account_id or 0}.{random_token()}"
    auth.oauth, auth.oauth_until = digest(state), time.time() + 600
    db.commit()
    with Instagram().client as client:
        return {"url": Instagram(client).authorize(state, source_only)}


@app.get("/api/instagram/callback", include_in_schema=False)
def callback(auth: Auth, db: DB, state: str = "", code: str = ""):
    if not auth.oauth or not auth.oauth_until or auth.oauth_until < time.time() or not hmac.compare_digest(
            auth.oauth, digest(state)):
        raise HTTPException(403, "OAuth state expired or invalid")
    consumed = db.execute(update(LoginSession).where(LoginSession.id == auth.id, LoginSession.oauth == digest(state))
                          .values(oauth=None, oauth_until=None)).rowcount
    db.commit()
    if not consumed:
        raise HTTPException(403, "OAuth state already used")
    if not code:
        return RedirectResponse("/?instagram=denied", 303)
    try:
        expected = int(state.split(".")[1])
        with Instagram().client as client:
            api = Instagram(client)
            credentials, profile, scopes = api.exchange(code)
            access = credentials["access_token"]
            if expected and str(profile["user_id"]) != item(db, Account, expected).ig_id:
                raise MetaError("Choose the same Instagram account when reconnecting")
            if not scopes:
                scopes = [BASIC]
                if state.startswith("publish."):
                    api.quota(access, str(profile["user_id"]))
                    scopes.append(PUBLISH)
            if BASIC not in scopes:
                raise MetaError("Instagram media permission was not granted")
            if state.startswith("publish.") and PUBLISH not in scopes:
                raise MetaError("Instagram publishing permission was not granted")
    except (MetaError, KeyError, IndexError, TypeError):
        log(db, "Instagram authorization failed. Check Meta app access and granted permissions.", "error")
        db.commit()
        return RedirectResponse("/?instagram=error", 303)
    identifier = str(profile["user_id"])
    account = db.scalar(select(Account).where(Account.ig_id == identifier))
    if account is None:
        account = Account(ig_id=identifier)
        db.add(account)
    account.username, account.picture = profile["username"], profile.get("profile_picture_url")
    account.token = cipher().encrypt(access.encode()).decode()
    account.issued = time.time()
    account.expires = account.issued + credentials["expires_in"]
    account.scopes, account.state = scopes, "connected"
    log(db, f"Connected @{account.username}")
    db.commit()
    return RedirectResponse("/?instagram=connected", 303)


@app.delete("/api/accounts/{identifier}")
def disconnect(identifier: int, auth: Auth, db: DB):
    account = item(db, Account, identifier)
    if db.scalar(select(Publish.id).where(Publish.account_id == identifier, Publish.state == "uploading").limit(1)):
        raise HTTPException(409, "A publish is in progress")
    account.state, account.token, account.expires, account.scopes = "removed", "", 0, []
    log(db, f"Disconnected @{account.username}")
    db.commit()
    return {"ok": True}


class SourceInput(BaseModel):
    profile: str = Field(min_length=1, max_length=200)
    destinations: list[int] = Field(min_length=1, max_length=30)
    kinds: list[Literal["IMAGE", "VIDEO", "REELS", "CAROUSEL_ALBUM"]] = Field(min_length=1, max_length=4)
    enabled: bool = True
    interval: int = Field(30, ge=5, le=1440)
    initial_count: int = Field(30, ge=1, le=500)
    existing: bool = True
    oldest: bool = True
    priority: int = Field(0, ge=-100, le=100)


def profile_name(value):
    value = value.strip()
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.netloc.lower() not in ("instagram.com", "www.instagram.com"):
            raise HTTPException(422, "Enter an Instagram username or profile URL")
        value = parsed.path.strip("/")
    value = value.removeprefix("@").lower()
    if not re.fullmatch(r"[a-z0-9_.]{1,30}", value) or value in ("reel", "reels", "p", "explore", "stories"):
        raise HTTPException(422, "Enter an Instagram username or profile URL")
    return value


def destination(db, identifier):
    account = item(db, Account, identifier)
    if account.state != "connected" or PUBLISH not in account.scopes or account.expires <= time.time():
        raise HTTPException(409, "Select a connected Instagram destination with publishing permission")
    return account


def save_source(data, db, source=None):
    name = profile_name(data.profile)
    account = db.scalar(select(Account).where(func.lower(Account.username) == name,
                                             Account.state == "connected", Account.expires > time.time()))
    if not account:
        raise HTTPException(422, "Authorize this professional account first, or use Manual import with a file you can repost")
    for identifier in set(data.destinations):
        if destination(db, identifier).id == account.id:
            raise HTTPException(422, "Choose a different destination to avoid reposting loops")
    collision = db.scalar(select(Source).where(Source.username == name))
    if collision and (not source or source.id != collision.id):
        raise HTTPException(409, "This source already exists")
    if source is None:
        source = Source(username=name, account_id=account.id, kinds=[])
        db.add(source)
        db.flush()
    elif source.account_id != account.id:
        raise HTTPException(422, "Create a new source to switch Instagram accounts")
    elif data.existing and not source.existing:
        source.watermark, source.last_sync = 0, None
    source.username = name
    for key in ("kinds", "enabled", "interval", "initial_count", "existing", "oldest", "priority"):
        setattr(source, key, getattr(data, key))
    source.next_sync = 0
    db.execute(delete(Mapping).where(Mapping.source_id == source.id))
    db.add_all(Mapping(source_id=source.id, account_id=i) for i in set(data.destinations))
    db.execute(update(Publish).where(Publish.media_id.in_(select(Media.id).where(Media.source_id == source.id)),
                                    Publish.account_id.not_in(set(data.destinations)),
                                    Publish.state.in_(("waiting", "ready"))).values(state="cancelled"))
    log(db, f"Saved source @{name}")
    db.commit()
    return {"id": source.id}


@app.post("/api/sources")
def add_source(data: SourceInput, auth: Auth, db: DB):
    return save_source(data, db)


@app.put("/api/sources/{identifier}")
def edit_source(identifier: int, data: SourceInput, auth: Auth, db: DB):
    return save_source(data, db, item(db, Source, identifier))


@app.post("/api/sources/{identifier}/sync")
def sync_source(identifier: int, auth: Auth, db: DB):
    source = item(db, Source, identifier)
    if not source.enabled:
        raise HTTPException(409, "Enable the source before syncing")
    source.next_sync = 0
    db.commit()
    return {"ok": True}


@app.post("/api/import", openapi_extra={"requestBody": {
    "required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "required": ["account_id", "authorized", "files"],
        "properties": {"account_id": {"type": "integer"}, "authorized": {"type": "boolean"},
                       "permalink": {"type": "string"},
                       "files": {"type": "array", "items": {"type": "string", "format": "binary"}}},
    }}},
}})
async def import_files(auth: Auth, db: DB, request: Request):
    length = request.headers.get("content-length", "")
    if not length.isascii() or not length.isdigit() or len(length) > 10 or int(length) > 1024 ** 3:
        raise HTTPException(413, "Provide a known upload size of no more than 1 GiB")
    async with request.form(max_files=CAROUSEL_LIMIT, max_fields=3, max_part_size=1024) as form:
        files = form.getlist("files")
        account_id = form.get("account_id")
        permalink = form.get("permalink", "")
        if (not isinstance(account_id, str) or not re.fullmatch(r"[0-9]{1,18}", account_id)
                or not isinstance(permalink, str) or not all(isinstance(file, UploadFile) for file in files)):
            raise HTTPException(422, "Provide a destination, authorized media files, and an optional permalink")
        return await run_in_threadpool(save_import, db, int(account_id),
                                       form.get("authorized") == "true", files, permalink)


def save_import(db, account_id, authorized, files, permalink):
    destination(db, account_id)
    if not authorized or not 1 <= len(files) <= CAROUSEL_LIMIT:
        raise HTTPException(422, f"Provide 1–{CAROUSEL_LIMIT} media files and confirm that you can repost them")
    if permalink and not re.fullmatch(r"https://(?:www\.)?instagram\.com/(?:p|reel|tv)/[\w-]{1,64}/?", permalink):
        raise HTTPException(422, "Enter a canonical Instagram post or reel URL")
    if permalink:
        permalink = "https://www.instagram.com/" + "/".join(urlsplit(permalink).path.strip("/").split("/")) + "/"
    settings = db.get(Settings, 1)
    staged = []
    try:
        with tempfile.TemporaryDirectory(dir=MEDIA) as folder:
            for position, upload in enumerate(files):
                path = Path(folder) / str(position)
                limit = budget(settings)
                if limit <= 0:
                    raise MediaError("Storage limit reached")
                kind = "IMAGE" if (upload.content_type or "").startswith("image/") else "VIDEO"
                if upload.size is None or not 0 < upload.size <= limit:
                    raise MediaError("File is empty or exceeds the storage limit")
                with path.open("wb") as output:
                    shutil.copyfileobj(upload.file, output, 256 * 1024)
                staged.append(stage(path, kind, position, len(files) > 1))
                path.unlink()
            if len(staged) == 1 and staged[0]["kind"] == "VIDEO":
                cover = Path(folder) / "cover.jpg"
                run("ffmpeg", "-nostdin", "-v", "error", "-i", str(MEDIA / staged[0]["filename"]),
                    "-frames:v", "1", str(cover))
                staged.append(stage(cover, "IMAGE", -1))
        kind = "CAROUSEL_ALBUM" if len(files) > 1 else ("REELS" if staged[0]["kind"] == "VIDEO" else "IMAGE")
        media = Media(ig_id=f"manual-{uuid.uuid4().hex}", permalink=permalink or None,
                      kind=kind, timestamp=time.time(), checksum=checksum(staged))
        db.add(media)
        db.flush()
        db.add_all(Asset(media_id=media.id, **asset) for asset in staged)
        db.add(Publish(media_id=media.id, account_id=account_id, state="ready"))
        log(db, f"Manually imported media {media.id}")
        db.commit()
        return {"id": media.id}
    except Exception as error:
        db.rollback()
        for asset in staged:
            (MEDIA / asset["filename"]).unlink(missing_ok=True)
        if isinstance(error, MediaError):
            raise HTTPException(422, str(error)) from None
        raise


class QueueInput(BaseModel):
    action: Literal["retry", "publish", "skip", "cancel", "delete", "republish", "priority", "confirm_published",
                    "confirm_not_published"]
    priority: int = Field(0, ge=-100, le=100)
    instagram_id: str | None = Field(None, pattern=r"^\d{1,40}$")


@app.post("/api/queue/{identifier}")
def queue_action(identifier: int, data: QueueInput, auth: Auth, db: DB):
    db.execute(text("BEGIN IMMEDIATE"))
    job = item(db, Publish, identifier)
    media = db.get(Media, job.media_id)
    if job.state == "uploading":
        raise HTTPException(409, "Publishing is in progress")
    action = data.action
    if job.state == "uncertain":
        if action == "confirm_published":
            if data.instagram_id and db.scalar(select(Published.id).where(Published.ig_id == data.instagram_id)):
                raise HTTPException(409, "That Instagram media ID is already recorded")
            db.add(Published(job_id=job.id, media_id=media.id, account_id=job.account_id,
                             checksum=media.checksum, origin=media.permalink, ig_id=data.instagram_id))
            job.state, job.error = "published", None
        elif action == "confirm_not_published":
            job.sent_at, job.container, job.state = None, None, "ready"
            job.children, job.poll_count = [], 0
            job.attempts, job.error, job.next_run, job.manual = 0, None, 0, False
        else:
            raise HTTPException(409, "Verify the publishing outcome on Instagram first")
    elif action == "priority":
        job.priority = data.priority
    elif action == "delete":
        if job.state not in ("failed", "skipped", "cancelled", "dry_run"):
            raise HTTPException(409, "Cancel or skip an unpublished item before deleting it")
        # Keep the job tombstone so a sync cannot recreate it.
        job.state = "deleted"
    elif action in ("skip", "cancel"):
        if job.state not in ("waiting", "ready", "failed", "dry_run"):
            raise HTTPException(409, "This job cannot be cancelled or skipped")
        job.state = "skipped" if action == "skip" else "cancelled"
    elif action in ("retry", "publish", "republish"):
        destination(db, job.account_id)
        if action == "republish":
            if job.state != "published":
                raise HTTPException(409, "Only published items can be explicitly republished")
            generation = db.scalar(select(func.max(Publish.generation)).where(
                Publish.media_id == media.id, Publish.account_id == job.account_id))
            pending = db.scalar(select(Publish.id).where(Publish.media_id == media.id, Publish.account_id == job.account_id,
                                Publish.state.in_(("waiting", "ready", "uploading", "uncertain"))).limit(1))
            if pending:
                raise HTTPException(409, "A publish is already queued for this media")
            job = Publish(media_id=media.id, account_id=job.account_id, generation=generation + 1,
                          priority=job.priority, manual=True)
            db.add(job)
        elif job.state not in ("failed", "ready", "dry_run", "cancelled", "skipped"):
            raise HTTPException(409, "This job cannot be queued again")
        has_assets = db.scalar(select(Asset.id).where(Asset.media_id == media.id).limit(1))
        if has_assets:
            job.state = "ready"
        else:
            download = db.scalar(select(Download).where(Download.media_id == media.id))
            if not download:
                raise HTTPException(409, "This manual import has expired. Import the original files again.")
            if download.state not in ("downloading", "processing"):
                download.state, download.attempts, download.next_run, download.error = "pending", 0, 0, None
            job.state = "waiting"
        job.manual, job.error, job.attempts, job.next_run = action != "retry", None, 0, 0
        if job.state == "ready" and job.poll_count >= 5:
            job.poll_count = 0
    else:
        raise HTTPException(409, "No uncertain publishing outcome to confirm")
    log(db, f"Queue action {action} for media {media.id}")
    db.commit()
    return {"ok": True}


class SettingsInput(BaseModel):
    automatic: bool
    paused: bool
    dry_run: bool
    downloads: int = Field(ge=1, le=8)
    uploads: int = Field(ge=1, le=8)
    storage_mb: int = Field(ge=300, le=1_000_000)
    file_mb: int = Field(ge=1, le=1000)
    retention_days: int = Field(ge=1, le=365)
    timezone: str = Field(max_length=64)
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    daily: int = Field(ge=1, le=100)
    interval: int = Field(ge=1, le=1440)


@app.put("/api/settings")
def settings(data: SettingsInput, auth: Auth, db: DB):
    try:
        ZoneInfo(data.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "Use a valid IANA time zone") from None
    if not data.dry_run and not SECURE:
        raise HTTPException(409, "Live publishing requires a public HTTPS URL")
    for target in (db.get(Settings, 1), db.get(Schedule, 1)):
        for key, value in data.model_dump().items():
            if key in target.__table__.columns:
                setattr(target, key, value)
    log(db, "Updated automation settings")
    db.commit()
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard(auth: Auth, db: DB, offset: int = 0, limit: int = 50):
    limit, offset = min(200, max(1, limit)), max(0, offset)
    usage = {u.account_id: u for u in db.scalars(select(Usage))}
    accounts = []
    now = time.time()
    automation, schedule = db.get(Settings, 1), db.get(Schedule, 1)
    for account in db.scalars(select(Account).where(Account.state != "removed").order_by(Account.username)):
        entry = fields(account, "id ig_id username picture state expires")
        entry["state"] = "reconnect" if account.expires <= now else account.state
        entry["can_publish"] = PUBLISH in account.scopes
        entry["quota"] = usage[account.id].quota - usage[account.id].used if account.id in usage else None
        accounts.append(entry)
    sources = [{**fields(s, "id username enabled interval kinds initial_count existing oldest priority last_sync status"),
                "destinations": list(db.scalars(select(Mapping.account_id).where(Mapping.source_id == s.id)))}
               for s in db.scalars(select(Source).order_by(Source.priority.desc(), Source.id))]
    queue = []
    for job, media, account, source, download in db.execute(
        select(Publish, Media, Account, Source, Download).join(Media, Media.id == Publish.media_id)
        .join(Account, Account.id == Publish.account_id).outerjoin(Source, Source.id == Media.source_id)
        .outerjoin(Download, Download.media_id == Media.id).where(Publish.state != "deleted")
        .order_by(Publish.id.desc()).offset(offset).limit(limit)
    ):
        assets = list(db.scalars(select(Asset).where(Asset.media_id == media.id).order_by(Asset.position)))
        previews = [{"id": a.id, "mime": a.mime} for a in assets]
        result = db.scalar(select(Published).where(Published.job_id == job.id)) if job.state == "published" else None
        slot = next_slot(db, job, automation, schedule, now, media.source_id) if job.state == "ready" else None
        queue.append({**fields(job, "id state priority next_run error"),
                      "source": source.username if source else "Manual import", "destination": account.username,
                      "kind": media.kind, "size": sum(a.size for a in assets), "assets": previews,
                      "duration": sum(a.duration or 0 for a in assets), "origin": media.permalink,
                      "permalink": result.permalink if result else None,
                      "scheduled_for": slot if slot is not None and slot > now else None,
                      "progress": download.progress if download else 100,
                      "download": download.state if download else None,
                      "error": job.error or (download.error if download else None)})
    counts = dict(db.execute(select(Publish.state, func.count()).group_by(Publish.state)).all())
    counts["discovered"] = db.scalar(select(func.count()).select_from(Media))
    counts["downloaded"] = db.scalar(select(func.count()).select_from(Download).where(Download.state == "downloaded"))
    options = {**fields(automation, "automatic paused dry_run downloads uploads storage_mb file_mb retention_days"),
               **fields(schedule, "timezone start end daily interval")}
    ram, disk = psutil.virtual_memory(), shutil.disk_usage(MEDIA)
    storage = sum(path.stat().st_size for path in MEDIA.iterdir() if path.is_file())
    return {"accounts": accounts, "sources": sources, "queue": queue, "counts": counts,
            "settings": options, "cpu": psutil.cpu_percent(interval=0.05), "ram": ram.percent,
            "disk_free": disk.free, "storage": storage, "running": app.state.scheduler.running,
            "logs": [fields(row, "id created level message") for row in db.scalars(
                select(Activity).order_by(Activity.id.desc()).limit(70))]}


@app.get("/api/preview/{identifier}")
def preview(identifier: int, auth: Auth, db: DB):
    asset = item(db, Asset, identifier)
    return asset_response(asset)


def asset_response(asset):
    path = MEDIA / asset.filename
    if not NAME.fullmatch(asset.filename) or not path.is_file() or path.is_symlink():
        raise HTTPException(404, "Media unavailable")
    return FileResponse(path, media_type=asset.mime)


@app.api_route("/media/{filename}", methods=["GET", "HEAD"], include_in_schema=False)
def signed_media(filename: str, until: int, sig: str, db: DB):
    now = time.time()
    if (not NAME.fullmatch(filename) or not now <= until <= now + 3600
            or not re.fullmatch(r"[a-f0-9]{64}", sig) or not hmac.compare_digest(signature(filename, until), sig)):
        raise HTTPException(404, "Media unavailable")
    asset = db.scalar(select(Asset).where(Asset.filename == filename))
    if not asset:
        raise HTTPException(404, "Media unavailable")
    return asset_response(asset)


if frontend := os.getenv("LOCAL_FRONTEND_DIR"):
    app.mount("/", StaticFiles(directory=frontend, html=True), name="local_dashboard")
