import hashlib
import json
import os
import shutil
import subprocess
import uuid
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps

from app.db import MEDIA

Image.MAX_IMAGE_PIXELS = 32_000_000
CAROUSEL_LIMIT = 20


class MediaError(Exception):
    pass


def allowed_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    roots = ("cdninstagram.com", "fbcdn.net", "fbsbx.com")
    return (parsed.scheme == "https" and parsed.port in (None, 443)
            and not parsed.username and not parsed.password
            and any(host == root or host.endswith("." + root) for root in roots))


def fetch(url, target, limit, progress, client=None):
    if not allowed_url(url):
        raise MediaError("Instagram returned an unsupported media host")
    with (client or httpx.Client(timeout=45, trust_env=False, follow_redirects=False)) as http:
        with http.stream("GET", url) as response:
            if response.status_code != 200:
                raise MediaError(f"Media download returned HTTP {response.status_code}")
            mime = response.headers.get("content-type", "").split(";")[0]
            if not (mime.startswith(("image/", "video/")) or mime == "application/octet-stream"):
                raise MediaError("Unexpected download MIME type")
            raw_length = response.headers.get("content-length", "")
            length = int(raw_length) if raw_length.isdigit() else 0
            if length > limit:
                raise MediaError("File exceeds the download size limit")
            size = 0
            previous = -10
            with target.open("wb") as output:
                for chunk in response.iter_bytes(256 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise MediaError("File exceeds the download size limit")
                    output.write(chunk)
                    if length and (percent := min(99, size * 100 // length)) >= previous + 10:
                        progress(percent)
                        previous = percent
            if not size or (length and size != length):
                raise MediaError("Incomplete media download")


def run(*command):
    try:
        return subprocess.run(command, capture_output=True, check=True, timeout=600).stdout
    except (OSError, subprocess.SubprocessError):
        raise MediaError(f"{command[0]} could not process the file") from None


def image(source, target, cover=False):
    with Image.open(source) as original:
        if original.width * original.height > Image.MAX_IMAGE_PIXELS:
            raise MediaError("Image exceeds the maximum pixel count")
        original.verify()
    with Image.open(source) as original:
        width, height = original.size
        if (original.format == "JPEG" and (cover or 320 <= width <= 1440 and
                0.8 <= width / height <= 1.91) and source.stat().st_size <= 8_000_000
                and original.getexif().get(274, 1) == 1 and original.mode == "RGB"):
            shutil.copyfile(source, target)
            return
        converted = ImageOps.exif_transpose(original).convert("RGB")
        width, height = converted.size
        ratio = width / height if cover else min(1.91, max(0.8, width / height))
        canvas_width, canvas_height = max(width, round(height * ratio)), max(height, round(width / ratio))
        if canvas_width * canvas_height > Image.MAX_IMAGE_PIXELS:
            raise MediaError("Image canvas is too large")
        canvas = Image.new("RGB", (canvas_width, canvas_height))
        canvas.paste(converted, ((canvas_width - width) // 2, (canvas_height - height) // 2))
        width = min(1440, max(320, canvas_width))
        canvas.resize((width, round(width * canvas_height / canvas_width)),
                      Image.Resampling.LANCZOS).save(target, quality=92, optimize=True)


def video(source, target, carousel=False):
    inputs = ("-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,avi,mpeg,mpegts,flv,asf")
    probe = json.loads(run("ffprobe", "-v", "error", *inputs, "-show_format", "-show_streams", "-of", "json",
                           str(source)))
    stream = next((s for s in probe["streams"] if s["codec_type"] == "video" and
                   not s.get("disposition", {}).get("attached_pic")), None)
    if not stream:
        raise MediaError("File contains no playable video channel")
    audio = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)
    duration = float(probe["format"].get("duration", 0))
    if not 3 <= duration <= (60 if carousel else 900):
        raise MediaError("Video duration is outside the selected publishing format")
    frame_rate = float(Fraction(stream.get("avg_frame_rate", "0/1").replace("0/0", "0/1")))
    size_limit = 100_000_000 if carousel else 300_000_000
    bitrate = min(20_000_000, int(size_limit * 7.5 / duration) - 128_000)
    compatible = (source.stat().st_size <= size_limit and 0.01 <= stream["width"] / stream["height"] <= 10
                  and stream["codec_name"] in ("h264", "hevc") and stream.get("pix_fmt") == "yuv420p"
                  and stream.get("field_order") in (None, "progressive")
                  and stream["width"] <= 1920 and 23 <= frame_rate <= 60
                  and int(stream.get("bit_rate", 0)) <= 25_000_000
                  and (not audio or audio["codec_name"] == "aac" and int(audio["channels"]) <= 2
                       and int(audio.get("sample_rate", 0)) <= 48000
                       and int(audio.get("bit_rate", 128000)) <= 132000))
    codecs = ["-c", "copy"] if compatible else [
        "-vf", f"scale=w='min(1920,trunc(iw/2)*2)':h=-2:flags=lanczos,fps={min(60, max(30, round(frame_rate)))}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-maxrate", str(bitrate), "-bufsize", str(bitrate * 2),
        "-flags", "+cgop", "-c:a", "aac", "-ar", "48000", "-ac", str(min(2, audio["channels"]) if audio else 2),
        "-b:a", "128k"]
    run("ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "2", *inputs, "-i", str(source),
        "-map", f"0:{stream['index']}", "-map", "0:a:0?", *codecs, "-use_editlist", "0",
        "-movflags", "+faststart", str(target))
    if target.stat().st_size > size_limit:
        raise MediaError("Processed video exceeds Instagram's size limit")
    return duration


def fingerprint(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def stage(source, kind, position, carousel=False):
    mime, extension = ("image/jpeg", "jpg") if kind == "IMAGE" else ("video/mp4", "mp4")
    filename = f"{uuid.uuid4().hex}.{extension}"
    output = MEDIA / filename
    try:
        duration = None
        if kind == "IMAGE":
            image(source, output, cover=position < 0)
        else:
            duration = video(source, output, carousel)
        return dict(position=position, kind=kind, filename=filename, mime=mime, size=output.stat().st_size,
                    duration=duration, checksum=fingerprint(source))
    except (OSError, ValueError, Image.DecompressionBombError):
        output.unlink(missing_ok=True)
        raise MediaError("Media failed format or integrity validation") from None
    except Exception:
        output.unlink(missing_ok=True)
        raise


def budget(settings):
    maximum = settings.storage_mb * 1_000_000
    used = sum(path.stat().st_size for path in MEDIA.rglob("*") if path.is_file())
    available = shutil.disk_usage(MEDIA).free - 200_000_000
    return min(settings.file_mb * 1_000_000, maximum - used, available)


def checksum(assets):
    return hashlib.sha256("|".join(a["checksum"] for a in assets if a["position"] >= 0).encode()).hexdigest()
