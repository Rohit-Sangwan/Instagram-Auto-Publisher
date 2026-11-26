import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.sqlite import insert

from app.assets import CAROUSEL_LIMIT, MediaError, budget, checksum, fetch, run, stage
from app.db import (MEDIA, Account, Activity, Asset, Download, LoginSession, Mapping, Media, Publish,
                    Published, Schedule, Session, Settings, Source, System, Usage, log)
from app.meta import FIELDS, PUBLISH, Instagram, MetaError
from app.security import cipher, media_url

ACTIVE = ("waiting", "ready", "uploading", "uncertain")


def token(account):
    if account.state != "connected" or account.expires <= time.time():
        if account.state == "connected":
            account.state = "reconnect"
        raise MetaError("Reconnect the Instagram account", 190)
    return cipher().decrypt(account.token.encode()).decode()


def error_message(error):
    if isinstance(error, (MetaError, MediaError)):
        return str(error)
    return f"Operation failed ({type(error).__name__})"


def retry(db, job, error, account=None):
    job.attempts += 1
    job.error = error_message(error)
    if account and isinstance(error, MetaError) and error.code in (10, 190, 200):
        account.state = "reconnect"
    job.next_run = time.time() + max(getattr(error, "wait", 0), min(3600, 30 * 2 ** min(7, job.attempts)))
    log(db, f"Job {job.id}: {job.error}", "error")


def sync(source_id):
    with Session() as db, Instagram().client as http:
        api = Instagram(http)
        source = db.get(Source, source_id)
        if not source or not source.enabled or not source.account_id:
            return
        account = db.get(Account, source.account_id)
        now = time.time()
        try:
            access = token(account)
            targets = list(db.scalars(select(Mapping.account_id).where(Mapping.source_id == source.id)))
            threshold = source.watermark or (0 if source.existing else source.created)
            initial = source.last_sync is None and source.existing
            discovered = []
            for item in api.pages(access, f"{account.ig_id}/media", FIELDS):
                timestamp = datetime.fromisoformat(item["timestamp"]).timestamp()
                if timestamp < threshold:
                    break
                kind = "REELS" if item.get("media_product_type") == "REELS" else item["media_type"]
                if kind not in source.kinds:
                    continue
                discovered.append((item, timestamp, kind))
                if initial and len(discovered) >= source.initial_count:
                    break
            for item, timestamp, kind in sorted(discovered, key=lambda entry: entry[1], reverse=not source.oldest):
                media = db.scalar(select(Media).where(Media.ig_id == item["id"]))
                if media is None:
                    media = Media(ig_id=item["id"], source_id=source.id, permalink=item.get("permalink"),
                                  timestamp=timestamp, kind=kind)
                    db.add(media)
                    db.flush()
                    db.add(Download(media_id=media.id))
                for destination in targets:
                    if destination == account.id:
                        continue
                    job = db.scalar(select(Publish.id).where(Publish.media_id == media.id,
                                                               Publish.account_id == destination))
                if job is None:
                        download = db.scalar(select(Download).where(Download.media_id == media.id))
                        present = db.scalar(select(Asset.id).where(Asset.media_id == media.id).limit(1))
                        if not present and download.state == "downloaded":
                            download.state = "pending"
                            download.attempts = 0
                        state = "ready" if present else ("failed" if download.state == "failed" else "waiting")
                        db.add(Publish(media_id=media.id, account_id=destination, state=state, priority=source.priority))
            source.watermark = max([threshold, 1] + [item[1] for item in discovered])
            source.last_sync = now
            source.next_sync = now + source.interval * 60
            source.status = f"Checked {len(discovered)} matching items"
            log(db, f"Synced @{source.username}. {source.status}.")
            db.commit()
        except Exception as error:
            db.rollback()
            if isinstance(error, MetaError) and error.code in (10, 190, 200):
                account.state = "reconnect"
            source.status = error_message(error)
            source.next_sync = now + max(source.interval * 60, getattr(error, "wait", 0))
            log(db, f"Sync for @{source.username}: {source.status}", "error")
            db.commit()


def download(job_id):
    with Session() as db, tempfile.TemporaryDirectory(dir=MEDIA) as directory, Instagram().client as http:
        if not db.execute(update(Download).where(Download.id == job_id, Download.state == "pending")
                          .values(state="downloading", progress=0)).rowcount:
            return
        db.commit()
        job = db.get(Download, job_id)
        media = db.get(Media, job.media_id)
        account = db.get(Account, db.get(Source, media.source_id).account_id)
        api = Instagram(http)
        files = []
        try:
            access = token(account)
            entry = api.graph(access, media.ig_id, fields=FIELDS)
            carousel = media.kind == "CAROUSEL_ALBUM"
            entries = list(api.pages(access, f"{media.ig_id}/children", "id,media_type,media_url")) if carousel else [entry]
            if not entries or carousel and not 2 <= len(entries) <= CAROUSEL_LIMIT:
                raise MediaError("Unsupported carousel item count")
            settings = db.get(Settings, 1)
            temporary = Path(directory) / "input"
            for position, item in enumerate(entries):
                temporary.unlink(missing_ok=True)
                limit = budget(settings)
                if limit <= 0:
                    raise MediaError("Storage limit reached")
                if not item.get("media_url"):
                    raise MediaError("Instagram did not provide a media URL")

                def progress(value):
                    job.progress = (position * 100 + value) // len(entries)
                    db.commit()

                fetch(item["media_url"], temporary, limit, progress)
                job.state = "processing"
                db.commit()
                files.append(stage(temporary, item["media_type"], position, carousel))
            if media.kind in ("REELS", "VIDEO"):
                temporary.unlink(missing_ok=True)
                try:
                    if not entry.get("thumbnail_url") or budget(settings) <= 0:
                        raise MediaError("Original cover unavailable")
                    fetch(entry["thumbnail_url"], temporary, budget(settings), lambda value: None)
                    files.append(stage(temporary, "IMAGE", -1))
                except (MediaError, OSError):
                    cover = Path(directory) / "cover.jpg"
                    run("ffmpeg", "-nostdin", "-v", "error", "-i", str(MEDIA / files[0]["filename"]),
                        "-frames:v", "1", str(cover))
                    files.append(stage(cover, "IMAGE", -1))
            media.checksum = checksum(files)
            db.add_all(Asset(media_id=media.id, **file) for file in files)
            job.state, job.progress, job.error = "downloaded", 100, None
            db.execute(update(Publish).where(Publish.media_id == media.id, Publish.state == "waiting").values(state="ready"))
            log(db, f"Processed media {media.id}")
            db.commit()
        except Exception as error:
            db.rollback()
            for file in files:
                (MEDIA / file["filename"]).unlink(missing_ok=True)
            retry(db, job, error, account)
            job.state = "failed" if job.attempts >= 5 or account.state != "connected" else "pending"
            if job.state == "failed":
                db.execute(update(Publish).where(Publish.media_id == media.id, Publish.state == "waiting")
                           .values(state="failed", error=job.error))
            db.commit()


def next_slot(db, job, settings, schedule, now, source_id):
    if settings.paused or not (settings.automatic or job.manual):
        return None
    if not job.manual and source_id and not db.get(Source, source_id).enabled:
        return None
    zone = ZoneInfo(schedule.timezone)
    midnight = datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    count = db.scalar(select(func.count()).select_from(Published).where(
        Published.account_id == job.account_id, Published.created >= midnight.timestamp()))
    last = db.scalar(select(func.max(Published.created)).where(Published.account_id == job.account_id))
    candidate = max(now, job.next_run, last + schedule.interval * 60 if last else 0)
    if count >= schedule.daily:
        candidate = max(candidate, (midnight + timedelta(days=1)).timestamp())
    if job.manual or schedule.start == schedule.end:
        return candidate
    local = datetime.fromtimestamp(candidate, zone)
    clock = local.strftime("%H:%M")
    if schedule.start < schedule.end:
        if schedule.start <= clock < schedule.end:
            return candidate
        if clock >= schedule.end:
            local += timedelta(days=1)
    elif clock >= schedule.start or clock < schedule.end:
        return candidate
    hour, minute = map(int, schedule.start.split(":"))
    return local.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0).timestamp()


def eligible(db, job, settings, schedule, now):
    slot = next_slot(db, job, settings, schedule, now, db.get(Media, job.media_id).source_id)
    return slot is not None and slot <= now


def quota(db, api, account, access):
    result = api.quota(access, account.ig_id)
    used, total = int(result["quota_usage"]), int(result["config"]["quota_total"])
    values = {"used": used, "quota": total, "checked": time.time()}
    statement = insert(Usage).values(account_id=account.id, **values)
    db.execute(statement.on_conflict_do_update(index_elements=[Usage.account_id], set_=values))
    db.commit()
    return max(0, total - used)


def payload(asset, carousel=False):
    url = media_url(asset.filename)
    if asset.kind == "IMAGE":
        return {"image_url": url}
    return {"video_url": url, "media_type": "VIDEO" if carousel else "REELS"}


def container_status(api, access, identifier):
    return api.graph(access, identifier, fields="status_code").get("status_code")


def defer_processing(db, job):
    job.poll_count += 1
    job.state, job.next_run = "ready", time.time() + 60
    if job.poll_count >= 5:
        job.state = "failed"
        job.error = "Instagram container is still processing after five checks. Retry to check again."
    db.commit()


def finish(db, job, media, ig_id=None, permalink=None):
    db.add(Published(job_id=job.id, media_id=media.id, account_id=job.account_id,
                     checksum=media.checksum, origin=media.permalink, ig_id=ig_id, permalink=permalink))
    job.state, job.error = "published", None
    usage = db.scalar(select(Usage).where(Usage.account_id == job.account_id))
    if usage:
        usage.used = min(usage.quota, usage.used + 1)
    log(db, f"Published media {media.id} to destination {job.account_id}")
    db.commit()


def publish(job_id):
    with Session() as db, Instagram().client as http:
        job = db.get(Publish, job_id)
        if not job or job.state not in ("ready", "uncertain"):
            return
        previous = job.state
        if not db.execute(update(Publish).where(Publish.id == job_id, Publish.state == previous)
                          .values(state="uploading")).rowcount:
            return
        db.commit()
        media, account = db.get(Media, job.media_id), db.get(Account, job.account_id)
        settings = db.get(Settings, 1)
        api = Instagram(http)
        try:
            if job.sent_at:
                access = token(account)
                status = container_status(api, access, job.container)
                if status == "PUBLISHED":
                    finish(db, job, media)
                else:
                    job.state = "uncertain"
                    job.error = f"Publish outcome unconfirmed ({status}). Verify on Instagram before taking action."
                    job.next_run = time.time() + 900
                    db.commit()
                return
            duplicate = db.scalar(select(Published.id).where(Published.account_id == account.id, or_(
                Published.media_id == media.id, Published.checksum == media.checksum,
                Published.origin == media.permalink if media.permalink else False)))
            if duplicate and job.generation == 0:
                job.state, job.error = "skipped", "Already published to this destination"
                db.commit()
                return
            unresolved = db.scalar(select(Publish.id).join(Media, Media.id == Publish.media_id).where(
                Publish.id != job.id, Publish.account_id == account.id, Publish.sent_at.is_not(None),
                Publish.state == "uncertain", or_(Media.id == media.id, Media.checksum == media.checksum,
                                                 Media.permalink == media.permalink if media.permalink else False)
            ).limit(1))
            if unresolved:
                raise MetaError("A matching publish is awaiting reconciliation", wait=900)
            assets = list(db.scalars(select(Asset).where(Asset.media_id == media.id).order_by(Asset.position)))
            body = [asset for asset in assets if asset.position >= 0]
            if not body or not all((MEDIA / asset.filename).is_file() for asset in assets):
                raise MediaError("Processed media is missing")
            if settings.dry_run:
                job.state, job.error = "dry_run", None
                log(db, f"Dry run validated media {media.id} for destination {account.id}")
                db.commit()
                return
            if PUBLISH not in account.scopes:
                raise MetaError("Destination lacks Instagram content publishing permission", 200)
            access = token(account)
            if quota(db, api, account, access) <= 0:
                raise MetaError("Instagram publishing quota exhausted", wait=3600)
            endpoint = f"{account.ig_id}/media"
            if not job.container:
                if media.kind == "CAROUSEL_ALBUM":
                    for asset in body[len(job.children):]:
                        child = api.graph(access, endpoint, "POST", is_carousel_item=True,
                                          **payload(asset, carousel=True))["id"]
                        job.children = [*job.children, child]
                        db.commit()
                    states = [container_status(api, access, child) for child in job.children]
                    if any(status in ("ERROR", "EXPIRED") for status in states):
                        job.children, job.poll_count = [], 0
                        raise MetaError("Instagram rejected or expired a carousel child")
                    if any(status != "FINISHED" for status in states):
                        defer_processing(db, job)
                        return
                    params = {"media_type": "CAROUSEL", "children": ",".join(job.children)}
                else:
                    params = payload(body[0])
                    cover = next((asset for asset in assets if asset.position == -1), None)
                    if cover:
                        params["cover_url"] = media_url(cover.filename)
                job.container = api.graph(access, endpoint, "POST", **params)["id"]
                job.poll_count = 0
                db.commit()
            status = container_status(api, access, job.container)
            if status != "FINISHED":
                if status in ("ERROR", "EXPIRED"):
                    job.container = None
                    job.children, job.poll_count = [], 0
                    raise MetaError(f"Instagram container status {status}")
                defer_processing(db, job)
                return
            db.refresh(settings)
            if settings.dry_run or not eligible(db, job, settings, db.get(Schedule, 1), time.time()):
                job.state = "ready"
                db.commit()
                return
            db.refresh(account)
            access = token(account)
            job.sent_at = time.time()
            db.commit()
            try:
                result = api.graph(access, f"{account.ig_id}/media_publish", "POST", creation_id=job.container)
            except MetaError as error:
                if not error.uncertain:
                    job.sent_at = None
                    db.commit()
                raise
            identifier = str(result["id"])
            finish(db, job, media, identifier)
            try:
                permalink = api.graph(access, identifier, fields="permalink").get("permalink")
                db.scalar(select(Published).where(Published.job_id == job.id)).permalink = permalink
                db.commit()
            except Exception as error:
                db.rollback()
                log(db, f"Could not save permalink for publish job {job.id}: {error_message(error)}", "warning")
                db.commit()
        except Exception as error:
            # Preserve changes made in response to an API or media failure. An
            # invalidated SQLAlchemy transaction must be rolled back first.
            if not db.is_active or not isinstance(error, (MetaError, MediaError)):
                db.rollback()
            retry(db, job, error, account)
            job.state = ("uncertain" if job.sent_at else
                         "failed" if account.state != "connected" or
                         (job.attempts >= 5 and not getattr(error, "wait", 0)) else "ready")
            db.commit()


def refresh_accounts():
    with Session() as db, Instagram().client as http:
        api = Instagram(http)
        now = time.time()
        for account in db.scalars(select(Account).where(Account.state == "connected")):
            if account.expires <= now:
                account.state = "reconnect"
                log(db, f"@{account.username} token expired", "warning")
                db.commit()
                continue
            if account.expires - now < 7 * 86400 and now - account.issued >= 86400:
                try:
                    result = api.refresh(token(account))
                    db.execute(update(Account).where(Account.id == account.id, Account.state == "connected",
                                                     Account.token == account.token).values(
                        token=cipher().encrypt(result["access_token"].encode()).decode(),
                        expires=now + result["expires_in"], issued=now))
                except MetaError as error:
                    if error.code == 190:
                        db.execute(update(Account).where(Account.id == account.id, Account.state == "connected",
                                                         Account.token == account.token).values(state="reconnect"))
                    log(db, f"Token refresh for @{account.username}: {error}", "error")
                db.commit()
            db.refresh(account)
            if account.state == "connected" and PUBLISH in account.scopes:
                try:
                    quota(db, api, account, token(account))
                except Exception as error:
                    db.rollback()
                    if isinstance(error, MetaError) and error.code in (10, 190, 200):
                        db.execute(update(Account).where(Account.id == account.id, Account.state == "connected",
                                                         Account.token == account.token).values(state="reconnect"))
                    log(db, f"Quota check for @{account.username}: {error_message(error)}", "warning")
                    db.commit()


def cleanup():
    with Session() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        settings = db.get(Settings, 1)
        now = time.time()
        active = select(Publish.media_id).where(Publish.state.in_(ACTIVE))
        old = now - settings.retention_days * 86400
        assets = list(db.scalars(select(Asset).where(Asset.media_id.not_in(active), or_(
            Asset.created < old,
            Asset.media_id.in_(select(Published.media_id)),
        ))))
        for asset in assets:
            (MEDIA / asset.filename).unlink(missing_ok=True)
            db.delete(asset)
        db.commit()
        known = set(db.scalars(select(Asset.filename)))
        for path in MEDIA.iterdir():
            if path.stat().st_mtime < now - 86400 and path.name not in known:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
        db.execute(delete(LoginSession).where(LoginSession.expires < now))
        db.execute(delete(Activity).where(Activity.created < now - 90 * 86400))
        for record in db.scalars(select(System).where(System.key.startswith("login:"))):
            if record.value["until"] < now:
                db.delete(record)
        db.commit()


def recover():
    with Session() as db:
        db.execute(update(Download).where(Download.state.in_(("downloading", "processing"))).values(state="pending"))
        db.execute(update(Publish).where(Publish.state == "uploading", Publish.sent_at.is_not(None)).values(state="uncertain"))
        db.execute(update(Publish).where(Publish.state == "uploading", Publish.sent_at.is_(None)).values(state="ready"))
        db.commit()


def sync_due():
    now = time.time()
    with Session() as db:
        if db.get(Settings, 1).paused:
            return
        source_ids = list(db.scalars(select(Source.id).where(
            Source.enabled.is_(True), Source.account_id.in_(select(Account.id).where(
                Account.state == "connected", Account.expires > now)), Source.next_sync <= now)
            .order_by(Source.priority.desc(), Source.next_sync, Source.id).limit(10)))
    for source_id in source_ids:
        sync(source_id)


def downloads_due():
    now = time.time()
    with Session() as db:
        settings = db.get(Settings, 1)
        if settings.paused:
            return
        downloading = list(db.scalars(select(Download.id).join(Media, Media.id == Download.media_id)
            .join(Source, Source.id == Media.source_id).join(Account, Account.id == Source.account_id)
            .where(Download.state == "pending", Download.next_run <= now, Source.enabled.is_(True),
                   Account.state == "connected", Account.expires > now).order_by(Source.priority.desc(), Download.id)
            .limit(settings.downloads)))
    dispatch(download, downloading)


def publishes_due():
    now = time.time()
    with Session() as db:
        settings, schedule = db.get(Settings, 1), db.get(Schedule, 1)
        publishing = []
        destinations = set()
        for job in db.scalars(select(Publish).join(Account, Account.id == Publish.account_id).where(
            Publish.state.in_(("ready", "uncertain")), Publish.next_run <= now,
            Account.state == "connected", Account.expires > now
        ).order_by(Publish.manual.desc(), Publish.priority.desc(), Publish.id)):
            if job.account_id not in destinations and (job.state == "uncertain" or eligible(db, job, settings, schedule, now)):
                publishing.append(job.id)
                destinations.add(job.account_id)
                if len(publishing) >= settings.uploads:
                    break
    dispatch(publish, publishing)


def dispatch(operation, identifiers):
    if identifiers:
        with ThreadPoolExecutor(max_workers=len(identifiers)) as executor:
            list(executor.map(operation, identifiers))


def scheduler():
    service = BackgroundScheduler()
    for operation in (sync_due, downloads_due, publishes_due):
        service.add_job(operation, "interval", seconds=15, max_instances=1, coalesce=True)
    service.add_job(refresh_accounts, "interval", minutes=30, max_instances=1, coalesce=True,
                    next_run_time=datetime.now() + timedelta(seconds=15))
    service.add_job(cleanup, "interval", hours=1, max_instances=1, coalesce=True)
    service.start()
    return service
