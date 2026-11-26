import os
import time
from pathlib import Path

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column as column, sessionmaker

ROOT = Path(os.getenv("DATA_DIR", "data")).resolve()
ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
MEDIA = ROOT / "media"
MEDIA.mkdir(mode=0o700, exist_ok=True)
engine = create_engine("sqlite:///" + (ROOT / "publisher.sqlite3").as_posix(), connect_args={"timeout": 30})
Session = sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine, "connect")
def configure(connection, record):
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")


class Base(DeclarativeBase):
    id: Mapped[int] = column(primary_key=True)


class Admin(Base):
    __tablename__ = "admin_users"
    username: Mapped[str] = column(unique=True)
    password: Mapped[str]


class LoginSession(Base):
    __tablename__ = "admin_sessions"
    digest: Mapped[str] = column(unique=True)
    admin_id: Mapped[int] = column(ForeignKey("admin_users.id"))
    expires: Mapped[float] = column(index=True)
    csrf: Mapped[str]
    oauth: Mapped[str | None]
    oauth_until: Mapped[float | None]


class System(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = column(unique=True)
    value: Mapped[dict] = column(JSON)


class Account(Base):
    __tablename__ = "instagram_accounts"
    ig_id: Mapped[str] = column(unique=True)
    username: Mapped[str] = column(index=True)
    picture: Mapped[str | None]
    token: Mapped[str]
    expires: Mapped[float]
    state: Mapped[str] = column(default="connected")
    scopes: Mapped[list] = column(JSON)
    issued: Mapped[float] = column(default=time.time)


class Source(Base):
    __tablename__ = "source_profiles"
    username: Mapped[str] = column(unique=True)
    account_id: Mapped[int | None] = column(ForeignKey("instagram_accounts.id"))
    enabled: Mapped[bool] = column(default=True)
    interval: Mapped[int] = column(default=30)
    kinds: Mapped[list] = column(JSON)
    initial_count: Mapped[int] = column(default=30)
    existing: Mapped[bool] = column(default=True)
    oldest: Mapped[bool] = column(default=True)
    priority: Mapped[int] = column(default=0)
    created: Mapped[float] = column(default=time.time)
    watermark: Mapped[float] = column(default=0)
    next_sync: Mapped[float] = column(default=0, index=True)
    last_sync: Mapped[float | None]
    status: Mapped[str] = column(default="Waiting")


class Mapping(Base):
    __tablename__ = "source_destination_mappings"
    __table_args__ = (UniqueConstraint("source_id", "account_id"),)
    source_id: Mapped[int] = column(ForeignKey("source_profiles.id"), index=True)
    account_id: Mapped[int] = column(ForeignKey("instagram_accounts.id"))


class Media(Base):
    __tablename__ = "discovered_media"
    ig_id: Mapped[str] = column(unique=True)
    source_id: Mapped[int | None] = column(ForeignKey("source_profiles.id"), index=True)
    permalink: Mapped[str | None] = column(index=True)
    kind: Mapped[str]
    timestamp: Mapped[float]
    checksum: Mapped[str | None] = column(index=True)


class Asset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (UniqueConstraint("media_id", "position"),)
    media_id: Mapped[int] = column(ForeignKey("discovered_media.id"), index=True)
    position: Mapped[int]
    kind: Mapped[str]
    filename: Mapped[str] = column(unique=True, index=True)
    mime: Mapped[str]
    size: Mapped[int]
    duration: Mapped[float | None]
    checksum: Mapped[str]
    created: Mapped[float] = column(default=time.time, index=True)


class Download(Base):
    __tablename__ = "download_jobs"
    media_id: Mapped[int] = column(ForeignKey("discovered_media.id"), unique=True)
    state: Mapped[str] = column(default="pending", index=True)
    progress: Mapped[int] = column(default=0)
    attempts: Mapped[int] = column(default=0)
    next_run: Mapped[float] = column(default=0)
    error: Mapped[str | None]


class Publish(Base):
    __tablename__ = "publishing_jobs"
    __table_args__ = (UniqueConstraint("media_id", "account_id", "generation"),)
    media_id: Mapped[int] = column(ForeignKey("discovered_media.id"), index=True)
    account_id: Mapped[int] = column(ForeignKey("instagram_accounts.id"), index=True)
    generation: Mapped[int] = column(default=0)
    state: Mapped[str] = column(default="waiting", index=True)
    priority: Mapped[int] = column(default=0)
    manual: Mapped[bool] = column(default=False)
    attempts: Mapped[int] = column(default=0)
    next_run: Mapped[float] = column(default=0)
    error: Mapped[str | None]
    container: Mapped[str | None]
    children: Mapped[list] = column(JSON, default=list, server_default="[]")
    poll_count: Mapped[int] = column(default=0, server_default="0")
    sent_at: Mapped[float | None]
    created: Mapped[float] = column(default=time.time)


class Published(Base):
    __tablename__ = "published_media"
    job_id: Mapped[int] = column(ForeignKey("publishing_jobs.id"), unique=True)
    media_id: Mapped[int] = column(ForeignKey("discovered_media.id"))
    account_id: Mapped[int] = column(ForeignKey("instagram_accounts.id"), index=True)
    checksum: Mapped[str]
    origin: Mapped[str | None]
    ig_id: Mapped[str | None] = column(unique=True)
    permalink: Mapped[str | None]
    created: Mapped[float] = column(default=time.time, index=True)


class Schedule(Base):
    __tablename__ = "publishing_schedules"
    timezone: Mapped[str] = column(default="Asia/Kolkata")
    start: Mapped[str] = column(default="09:00")
    end: Mapped[str] = column(default="21:00")
    daily: Mapped[int] = column(default=3)
    interval: Mapped[int] = column(default=120)


class Settings(Base):
    __tablename__ = "automation_settings"
    automatic: Mapped[bool] = column(default=False)
    paused: Mapped[bool] = column(default=False)
    dry_run: Mapped[bool] = column(default=True)
    downloads: Mapped[int] = column(default=1)
    uploads: Mapped[int] = column(default=1)
    storage_mb: Mapped[int] = column(default=5000)
    file_mb: Mapped[int] = column(default=300)
    retention_days: Mapped[int] = column(default=7)


class Usage(Base):
    __tablename__ = "api_usage"
    account_id: Mapped[int] = column(ForeignKey("instagram_accounts.id"), unique=True)
    quota: Mapped[int]
    used: Mapped[int]
    checked: Mapped[float] = column(default=time.time)


class Activity(Base):
    __tablename__ = "activity_logs"
    created: Mapped[float] = column(default=time.time, index=True)
    level: Mapped[str]
    message: Mapped[str]


def log(db, message, level="info"):
    db.add(Activity(message=message, level=level))
