#!/usr/bin/env python3
"""Universal Video Processor for KookAI Server.

Provides complete video understanding capabilities for any LLM backend (Gemini,
Codex, Claude, Kimi, Grok):
1. Downloads metadata and native VTT captions via yt-dlp.
2. Extracts scene-aware or keyframe images via ffmpeg (clamped to max 2.0 FPS).
3. Performs 16x16 grayscale perceptual frame deduplication (threshold <= 2.0) to drop static frames.
4. Parses native subtitles or falls back to Groq (whisper-large-v3) or OpenAI (whisper-1)
   transcription using pure Python stdlib HTTP calls.
"""

from __future__ import annotations

import io
import json
import logging
import math
import mimetypes
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# --- Constants & Rules ---
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".wmv"}
MAX_FPS = 2.0
SCENE_THRESHOLD = 0.20
SCENE_MIN_FRAMES = 8
KEYFRAME_MIN = 4
MAX_READ_DIMENSION = 1998
DEDUP_THUMB = 16
DEDUP_THRESHOLD = 2.0
MAX_WHISPER_UPLOAD_BYTES = 24 * 1024 * 1024

SHOWINFO_TS_RE = re.compile(r"pts_time:([0-9.]+)")
VTT_TS_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")
VTT_TAG_RE = re.compile(r"<[^>]+>")

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3"
OPENAI_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_MODEL = "whisper-1"

WATCH_HELP_RESPONSE = """⚠️ **ไม่พบ URL วิดีโอ หรือไฟล์วิดีโอสำหรับคำสั่ง `/watch`**

💡 **ตัวอย่างวิธีใช้งานคำสั่ง `/watch` ที่ถูกต้อง:**

1. **ระบุ URL วิดีโอ (YouTube, TikTok, Vimeo, Loom ฯลฯ):**
   - `/watch https://youtu.be/dQw4w9WgXcQ เกิดอะไรขึ้นตอนนาทีที่ 0:30?`
   - `/watch https://vimeo.com/123456 สรุปประเด็นหลักในคลิปนี้`

2. **ระบุช่วงเวลาที่ต้องการโฟกัส (เพื่อความรายละเอียดเฟรมภาพที่สูงขึ้น):**
   - `/watch https://youtu.be/abc --start 1:15 --end 2:30 อธิบายฉากนี้`

3. **แนบไฟล์วิดีโอในแชต หรืออัปโหลดจากมือถือ (`.mp4`, `.mov`, `.mkv`, `.webm`):**
   - แนบไฟล์วิดีโอในช่องแชต แล้วพิมพ์: `/watch หน้าจอขึ้น error ตอนไหน?`"""


def is_url(source: str) -> bool:
    if not source or source.startswith("-"):
        return False
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_video_source(source: str) -> bool:
    """Check if the string is a video URL or a local video file path."""
    if not source:
        return False
    s = source.strip()
    if is_url(s):
        # Known video domains or common video extensions in query
        domain = urlparse(s).netloc.lower()
        if any(d in domain for d in ("youtube.com", "youtu.be", "vimeo.com", "tiktok.com", "loom.com", "x.com", "twitter.com")):
            return True
        path_suffix = Path(urlparse(s).path).suffix.lower()
        return path_suffix in VIDEO_EXTENSIONS
    p = Path(s).expanduser()
    return p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS


def extract_video_target(message_text: str, attached_media: list[str] | None = None) -> str | None:
    """Find a valid video URL or file path in the message text or attached media."""
    if attached_media:
        for path in attached_media:
            if Path(path).suffix.lower() in VIDEO_EXTENSIONS:
                return path

    tokens = message_text.strip().split()
    for token in tokens:
        clean_token = token.strip("\",'\"`()[]{}")
        if is_url(clean_token) and is_video_source(clean_token):
            return clean_token
        if not is_url(clean_token):
            try:
                p = Path(clean_token).expanduser()
                if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                    return str(p)
            except Exception:
                pass

    msg_trim = message_text.strip()
    if is_video_source(msg_trim):
        return msg_trim

    return None


def parse_time(value: str | float | int | None) -> float | None:
    """Parse SS, MM:SS, or HH:MM:SS into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    return None


def format_time(seconds: float) -> str:
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def get_video_metadata(video_path: str) -> dict:
    if shutil.which("ffprobe") is None:
        return {"duration_seconds": 0.0, "width": None, "height": None, "codec": None, "has_audio": False}

    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(Path(video_path).resolve()),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout or "{}")
        streams = data.get("streams", [])
        fmt = data.get("format", {})
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        duration = float(fmt.get("duration") or video_stream.get("duration") or 0.0)
        return {
            "duration_seconds": duration,
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "codec": video_stream.get("codec_name"),
            "has_audio": audio_stream is not None,
        }
    except Exception:
        return {"duration_seconds": 0.0, "width": None, "height": None, "codec": None, "has_audio": False}


# --- Frame Extraction & Deduplication ---

def _scale_filter(resolution: int) -> str:
    return (
        f"scale=w='min({resolution},iw)':h='min({MAX_READ_DIMENSION},ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )


def _even_indices(count: int, n: int) -> list[int]:
    if n >= count:
        return list(range(count))
    if n <= 1:
        return [0]
    return [round(i * (count - 1) / (n - 1)) for i in range(n)]


def _frame_delta(a: bytes, b: bytes) -> float:
    if not a or len(a) != len(b):
        return float("inf")
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _thumb_frames(paths: list[Path]) -> list[bytes]:
    if not paths or shutil.which("ffmpeg") is None:
        return []
    paths = [Path(p) for p in paths]
    m = re.match(r"(.*?)(\d+)(\.[A-Za-z0-9]+)$", paths[0].name)
    if m is None:
        return []
    prefix, digits, ext = m.group(1), m.group(2), m.group(3)
    pattern = str(paths[0].parent / f"{prefix}%0{len(digits)}d{ext}")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-start_number", str(int(digits)),
        "-i", pattern,
        "-vf", f"scale={DEDUP_THUMB}:{DEDUP_THUMB},format=gray",
        "-f", "rawvideo",
        "-",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode != 0:
            return []
        chunk = DEDUP_THUMB * DEDUP_THUMB
        data = res.stdout
        if len(data) != chunk * len(paths):
            return []
        return [data[i * chunk:(i + 1) * chunk] for i in range(len(paths))]
    except Exception:
        return []


def dedupe_perceptual(candidates: list[dict], threshold: float = DEDUP_THRESHOLD) -> tuple[list[dict], int]:
    if len(candidates) <= 1:
        return candidates, 0
    thumbs = _thumb_frames([Path(c["path"]) for c in candidates])
    if len(thumbs) != len(candidates):
        return candidates, 0

    kept = [candidates[0]]
    last = thumbs[0]
    dropped: list[dict] = []
    for cand, thumb in zip(candidates[1:], thumbs[1:]):
        if _frame_delta(thumb, last) <= threshold:
            dropped.append(cand)
        else:
            kept.append(cand)
            last = thumb

    for cand in dropped:
        try:
            Path(cand["path"]).unlink()
        except OSError:
            pass
    for i, frame in enumerate(kept):
        frame["index"] = i
    return kept, len(dropped)


def extract_scene_candidates(
    video_path: str,
    out_dir: Path,
    resolution: int = 512,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    threshold: float = SCENE_THRESHOLD,
) -> list[dict]:
    if shutil.which("ffmpeg") is None:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    for existing in out_dir.glob("frame_*.jpg"):
        existing.unlink()

    output_pattern = str(out_dir / "frame_%04d.jpg")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-y"]
    if start_seconds is not None:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    if end_seconds is not None:
        cmd += ["-to", f"{end_seconds:.3f}"]

    vf = f"select='eq(n\\,0)+gt(scene\\,{threshold})',{_scale_filter(resolution)},showinfo"
    cmd += ["-i", str(Path(video_path).resolve()), "-vf", vf, "-vsync", "vfr", "-q:v", "4", output_pattern]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return []

    offset = start_seconds or 0.0
    timestamps = [round(offset + float(m.group(1)), 2) for m in SHOWINFO_TS_RE.finditer(res.stderr)]
    frames = sorted(out_dir.glob("frame_*.jpg"))
    out = []
    for i, path in enumerate(frames):
        ts = timestamps[i] if i < len(timestamps) else offset
        out.append({
            "index": i,
            "timestamp_seconds": ts,
            "path": str(path),
            "reason": "first-frame" if i == 0 else "scene-change",
        })
    return out


def extract_uniform_frames(
    video_path: str,
    out_dir: Path,
    fps: float,
    resolution: int = 512,
    max_frames: int = 100,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> list[dict]:
    if shutil.which("ffmpeg") is None:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    for existing in out_dir.glob("frame_*.jpg"):
        existing.unlink()

    output_pattern = str(out_dir / "frame_%04d.jpg")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start_seconds is not None:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    if end_seconds is not None:
        cmd += ["-to", f"{end_seconds:.3f}"]

    cmd += [
        "-i", str(Path(video_path).resolve()),
        "-vf", f"fps={fps},{_scale_filter(resolution)}",
        "-frames:v", str(max_frames),
        "-q:v", "4",
        output_pattern,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return []

    offset = start_seconds or 0.0
    frames = sorted(out_dir.glob("frame_*.jpg"))
    return [
        {
            "index": i,
            "timestamp_seconds": round(offset + (i / fps if fps > 0 else 0.0), 2),
            "path": str(p),
            "reason": "uniform",
        }
        for i, p in enumerate(frames)
    ]


def extract_keyframes(
    video_path: str,
    out_dir: Path,
    resolution: int = 512,
    max_frames: int | None = 50,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    dedup: bool = True,
) -> tuple[list[dict], dict]:
    if shutil.which("ffmpeg") is None:
        return [], {"engine": "none", "candidate_count": 0, "selected_count": 0}

    out_dir.mkdir(parents=True, exist_ok=True)
    for existing in out_dir.glob("frame_*.jpg"):
        existing.unlink()

    output_pattern = str(out_dir / "frame_%04d.jpg")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-y"]
    if start_seconds is not None:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    if end_seconds is not None:
        cmd += ["-to", f"{end_seconds:.3f}"]
    cmd += [
        "-skip_frame", "nokey",
        "-i", str(Path(video_path).resolve()),
        "-vf", f"{_scale_filter(resolution)},showinfo",
        "-vsync", "vfr",
        "-q:v", "4",
        output_pattern,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return [], {"engine": "none", "candidate_count": 0, "selected_count": 0}

    offset = start_seconds or 0.0
    timestamps = [round(offset + float(m.group(1)), 2) for m in SHOWINFO_TS_RE.finditer(res.stderr)]
    files = sorted(out_dir.glob("frame_*.jpg"))
    candidates = [
        {"index": i, "timestamp_seconds": timestamps[i] if i < len(timestamps) else offset, "path": str(p), "reason": "keyframe"}
        for i, p in enumerate(files)
    ]

    candidate_count = len(candidates)
    if candidate_count < KEYFRAME_MIN:
        # Fallback to uniform
        meta = get_video_metadata(video_path)
        duration = meta["duration_seconds"] or 10.0
        fps = min(MAX_FPS, max(0.5, 20.0 / duration))
        frames = extract_uniform_frames(video_path, out_dir, fps, resolution, max_frames or 50, start_seconds, end_seconds)
        deduped, n_dropped = dedupe_perceptual(frames) if dedup else (frames, 0)
        return deduped, {"engine": "uniform", "candidate_count": candidate_count, "deduped_count": n_dropped, "selected_count": len(deduped), "fallback": True}

    deduped, n_dropped = dedupe_perceptual(candidates) if dedup else (candidates, 0)
    cap = len(deduped) if max_frames is None else max_frames
    selected_indices = _even_indices(len(deduped), cap)
    selected = [deduped[i] for i in selected_indices]

    keep_paths = {s["path"] for s in selected}
    for cand in deduped:
        if cand["path"] not in keep_paths:
            try:
                Path(cand["path"]).unlink()
            except OSError:
                pass
    for i, frame in enumerate(selected):
        frame["index"] = i

    return selected, {"engine": "keyframe", "candidate_count": candidate_count, "deduped_count": n_dropped, "selected_count": len(selected), "fallback": False}


# --- Subtitle & Whisper Transcription ---

def parse_vtt(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    segments = []
    i = 0
    while i < len(lines):
        match = VTT_TS_RE.match(lines[i])
        if not match:
            i += 1
            continue
        g = match.groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000.0
        end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000.0
        i += 1
        cue_lines = []
        while i < len(lines) and lines[i].strip():
            cleaned = VTT_TAG_RE.sub("", lines[i]).strip()
            if cleaned:
                cue_lines.append(cleaned)
            i += 1
        cue_text = " ".join(cue_lines).strip()
        if cue_text:
            segments.append({"start": round(start, 2), "end": round(end, 2), "text": cue_text})
        i += 1

    # Dedupe rolling YouTube captions
    deduped = []
    for seg in segments:
        if deduped and seg["text"] == deduped[-1]["text"]:
            deduped[-1]["end"] = seg["end"]
            continue
        if deduped and seg["text"].startswith(deduped[-1]["text"] + " "):
            deduped[-1]["text"] = seg["text"]
            deduped[-1]["end"] = seg["end"]
            continue
        deduped.append(seg)
    return deduped


def format_transcript(segments: list[dict]) -> str:
    lines = []
    for seg in segments:
        start = int(seg["start"])
        stamp = f"[{start // 60:02d}:{start % 60:02d}]"
        lines.append(f"{stamp} {seg['text']}")
    return "\n".join(lines)


def filter_transcript_range(segments: list[dict], start_sec: float | None, end_sec: float | None) -> list[dict]:
    if start_sec is None and end_sec is None:
        return segments
    lo = start_sec if start_sec is not None else float("-inf")
    hi = end_sec if end_sec is not None else float("inf")
    return [s for s in segments if s["end"] >= lo and s["start"] <= hi]


_whisper_key_rr_index = 0

def parse_key_candidates(raw_val: str) -> list[str]:
    """Parse comma, space, or line separated API keys from a raw string."""
    if not raw_val:
        return []
    cleaned = raw_val.replace("\n", ",").replace(";", ",").replace(" ", ",")
    parts = [p.strip().strip("\"'") for p in cleaned.split(",") if p.strip()]
    return [p for p in parts if p]

def load_all_whisper_keys(preferred: str | None = None) -> list[tuple[str, str]]:
    """Return all valid (backend, key) pairs found in environment variables and .env files."""
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    env_map = [
        ("GROQ_API_KEYS", "groq"),
        ("GROQ_API_KEY", "groq"),
        ("OPENAI_API_KEYS", "openai"),
        ("OPENAI_API_KEY", "openai"),
    ]
    if preferred:
        env_map = [item for item in env_map if item[1] == preferred]

    # 1. Environment variables
    for env_name, backend in env_map:
        val = os.environ.get(env_name, "").strip()
        for key in parse_key_candidates(val):
            if key not in seen:
                seen.add(key)
                results.append((backend, key))

    # 2. .env config files
    dotenv_paths = [Path.home() / ".config" / "watch" / ".env", Path.cwd() / ".env"]
    for path in dotenv_paths:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                k, _, v = raw.partition("=")
                k = k.strip()
                v = v.strip().strip("\"'")
                for env_name, backend in env_map:
                    if k == env_name:
                        for key in parse_key_candidates(v):
                            if key not in seen:
                                seen.add(key)
                                results.append((backend, key))
        except OSError:
            pass

    return results

def load_whisper_key(preferred: str | None = None) -> tuple[str | None, str | None]:
    """Get next (backend, key) using round-robin rotation from the pool of available keys."""
    global _whisper_key_rr_index
    keys = load_all_whisper_keys(preferred)
    if not keys:
        return None, None
    idx = _whisper_key_rr_index % len(keys)
    _whisper_key_rr_index += 1
    return keys[idx]


def _post_whisper_multipart(endpoint: str, api_key: str, model: str, audio_path: Path) -> dict:
    boundary = f"----WatchBoundary{uuid.uuid4().hex}"
    eol = b"\r\n"
    buf = io.BytesIO()

    for name, value in [("model", model), ("response_format", "verbose_json"), ("temperature", "0")]:
        buf.write(f"--{boundary}".encode() + eol)
        buf.write(f'Content-Disposition: form-data; name="{name}"'.encode() + eol + eol)
        buf.write(str(value).encode() + eol)

    mimetype = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    buf.write(f"--{boundary}".encode() + eol)
    buf.write(f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"'.encode() + eol)
    buf.write(f"Content-Type: {mimetype}".encode() + eol + eol)
    buf.write(audio_path.read_bytes() + eol)
    buf.write(f"--{boundary}--".encode() + eol)

    body = buf.getvalue()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "KookAI-VideoProcessor/1.0 (+python-urllib)",
    }

    req = Request(endpoint, data=body, headers=headers, method="POST")
    context = ssl.create_default_context()
    with urlopen(req, timeout=300, context=context) as response:
        payload = response.read().decode("utf-8", errors="replace")
        return json.loads(payload)


def transcribe_video_audio(video_path: str, work_dir: Path, backend: str | None = None, api_key: str | None = None) -> tuple[list[dict], str]:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for audio transcription")

    audio_out = work_dir / "audio.mp3"
    audio_out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(Path(video_path).resolve()),
        "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        str(audio_out.resolve()),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not audio_out.exists() or audio_out.stat().st_size == 0:
        raise RuntimeError("ffmpeg failed to extract audio from video")

    # Build key candidate list for round-robin and instant failover
    candidate_keys: list[tuple[str, str]] = []
    if backend and api_key:
        candidate_keys.append((backend, api_key))
    else:
        all_keys = load_all_whisper_keys(backend)
        if all_keys:
            global _whisper_key_rr_index
            start_idx = _whisper_key_rr_index % len(all_keys)
            _whisper_key_rr_index += 1
            # Reorder starting from round-robin index
            candidate_keys = all_keys[start_idx:] + all_keys[:start_idx]

    if not candidate_keys:
        raise ValueError("No Whisper API key found (GROQ_API_KEY or OPENAI_API_KEY required)")

    last_error: Exception | None = None
    for cand_backend, cand_key in candidate_keys:
        endpoint = GROQ_ENDPOINT if cand_backend == "groq" else OPENAI_ENDPOINT
        model = GROQ_MODEL if cand_backend == "groq" else OPENAI_MODEL
        try:
            resp = _post_whisper_multipart(endpoint, cand_key, model, audio_out)
            segments = []
            for seg in resp.get("segments") or []:
                t = (seg.get("text") or "").strip()
                if t:
                    segments.append({
                        "start": round(float(seg.get("start") or 0.0), 2),
                        "end": round(float(seg.get("end") or 0.0), 2),
                        "text": t,
                    })
            if not segments and resp.get("text"):
                segments.append({"start": 0.0, "end": 0.0, "text": resp["text"].strip()})

            return segments, cand_backend
        except Exception as err:
            masked_key = cand_key[:6] + "..." + cand_key[-4:] if len(cand_key) > 10 else "*****"
            logging.warning(f"Whisper API key ({cand_backend}:{masked_key}) failed with error: {err}. Attempting next key...")
            last_error = err

    raise RuntimeError(f"All Whisper API keys failed. Last error: {last_error}")


def get_ytdlp_cmd() -> list[str] | None:
    """Resolve the yt-dlp executable command or python module fallback."""
    if shutil.which("yt-dlp") is not None:
        return ["yt-dlp"]
    bindir = Path(sys.executable).parent
    for name in ("yt-dlp.exe", "yt-dlp", "Scripts/yt-dlp.exe", "Scripts/yt-dlp"):
        candidate = bindir / name
        if candidate.exists():
            return [str(candidate)]
    try:
        import yt_dlp
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        return None


# --- Main High-Level Video Processing Function ---

def process_video_source(
    source: str,
    start: str | None = None,
    end: str | None = None,
    detail: str = "balanced",
    max_frames: int | None = None,
    resolution: int = 512,
    whisper_backend: str | None = None,
    no_whisper: bool = False,
    out_dir: str | Path | None = None,
) -> dict:
    """Orchestrate complete video processing for KookAI prompts."""
    if out_dir:
        work = Path(out_dir).expanduser().resolve()
    else:
        cache_base = Path.cwd() / ".kookai_cache" / "video"
        cache_base.mkdir(parents=True, exist_ok=True)
        work = cache_base / f"video_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)

    url_src = is_url(source)
    video_path: str | None = None
    subtitle_path: str | None = None
    info: dict = {}

    if url_src:
        ytdlp_cmd = get_ytdlp_cmd()
        if not ytdlp_cmd:
            raise RuntimeError("yt-dlp is required to process video URLs")
        # Download metadata + subs first
        dl_template = str(work / "video.%(ext)s")
        cmd = ytdlp_cmd + [
            "-N", "8",
            "-f", "bv*[height<=720]+ba/b[height<=720]/bv+ba/b",
            "--merge-output-format", "mp4",
            "--write-info-json", "--write-subs", "--write-auto-subs",
            "--sub-langs", "en.*", "--sub-format", "vtt", "--convert-subs", "vtt",
            "--no-playlist", "--ignore-errors",
            "-o", dl_template, "--", source,
        ]
        subprocess.run(cmd, capture_output=True, text=True)

        info_json = work / "video.info.json"
        if info_json.exists():
            try:
                raw_info = json.loads(info_json.read_text(encoding="utf-8"))
                info = {
                    "title": raw_info.get("title"),
                    "uploader": raw_info.get("uploader") or raw_info.get("channel"),
                    "duration": raw_info.get("duration"),
                    "url": raw_info.get("webpage_url") or source,
                }
            except Exception:
                info = {"url": source}

        for candidate in sorted(work.glob("video*.vtt")):
            subtitle_path = str(candidate)
            break

        for ext in (".mp4", ".mkv", ".webm", ".mov"):
            for candidate in work.glob(f"video*{ext}"):
                video_path = str(candidate)
                break
            if video_path:
                break
    else:
        p = Path(source).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Local video file not found: {p}")
        video_path = str(p)
        info = {"title": p.name, "url": str(p)}

    meta = get_video_metadata(video_path) if video_path else {}
    full_duration = meta.get("duration_seconds") or float(info.get("duration") or 0.0)

    start_sec = parse_time(start)
    end_sec = parse_time(end)
    eff_start = start_sec if start_sec is not None else 0.0
    eff_end = end_sec if end_sec is not None else full_duration

    # Extract frames
    frames: list[dict] = []
    frame_meta: dict = {}
    if detail != "transcript" and video_path:
        frame_dir = work / "frames"
        cap = max_frames if max_frames is not None else (50 if detail == "efficient" else 100)
        if detail == "efficient":
            frames, frame_meta = extract_keyframes(video_path, frame_dir, resolution=resolution, max_frames=cap, start_seconds=start_sec, end_seconds=end_sec)
        else: # balanced / token-burner
            scene_candidates = extract_scene_candidates(video_path, frame_dir, resolution=resolution, start_seconds=start_sec, end_seconds=end_sec)
            if len(scene_candidates) >= SCENE_MIN_FRAMES:
                deduped, n_dropped = dedupe_perceptual(scene_candidates)
                selected_indices = _even_indices(len(deduped), cap)
                frames = [deduped[i] for i in selected_indices]
                for i, f in enumerate(frames):
                    f["index"] = i
                frame_meta = {"engine": "scene", "candidate_count": len(scene_candidates), "deduped_count": n_dropped, "selected_count": len(frames)}
            else:
                fps = min(MAX_FPS, max(0.5, 30.0 / max(1.0, eff_end - eff_start)))
                unif = extract_uniform_frames(video_path, frame_dir, fps, resolution, cap, start_sec, end_sec)
                deduped, n_dropped = dedupe_perceptual(unif)
                frames = deduped
                frame_meta = {"engine": "uniform", "candidate_count": len(unif), "deduped_count": n_dropped, "selected_count": len(frames), "fallback": True}

    # Transcript handling
    transcript_segments: list[dict] = []
    transcript_source: str | None = None
    if subtitle_path:
        transcript_segments = parse_vtt(subtitle_path)
        if transcript_segments:
            transcript_source = "captions"

    if not transcript_segments and not no_whisper and video_path and meta.get("has_audio", True):
        try:
            whisper_segs, used_backend = transcribe_video_audio(video_path, work, backend=whisper_backend)
            if whisper_segs:
                transcript_segments = whisper_segs
                transcript_source = f"whisper ({used_backend})"
        except Exception as exc:
            print(f"[video_processor] Whisper transcription fallback skipped: {exc}", file=sys.stderr)

    if transcript_segments and (start_sec is not None or end_sec is not None):
        transcript_segments = filter_transcript_range(transcript_segments, start_sec, end_sec)

    transcript_text = format_transcript(transcript_segments) if transcript_segments else ""

    # Build prompt summary snippet
    prompt_lines = [
        "---",
        "### 🎥 Video Analysis Data",
        f"- **Source:** {info.get('url') or source}",
        f"- **Title:** {info.get('title') or 'N/A'}",
        f"- **Duration:** {format_time(full_duration)} ({full_duration:.1f}s)",
        f"- **Extracted Frames:** {len(frames)} images ({frame_meta.get('engine', detail)} engine)",
        f"- **Transcript Source:** {transcript_source or 'none'}",
        "",
        "#### Frames Extracted (Chronological):",
    ]
    for f in frames:
        prompt_lines.append(f"- `{Path(f['path']).name}` (t={format_time(f['timestamp_seconds'])})")

    if transcript_text:
        prompt_lines += [
            "",
            "#### Video Transcript:",
            "```",
            transcript_text,
            "```",
        ]
    prompt_lines.append("---")

    return {
        "work_dir": str(work),
        "source": source,
        "title": info.get("title"),
        "duration_seconds": full_duration,
        "frames": frames,
        "frame_paths": [f["path"] for f in frames],
        "transcript_segments": transcript_segments,
        "transcript_text": transcript_text,
        "transcript_source": transcript_source,
        "prompt_summary": "\n".join(prompt_lines),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python video_processor.py <video-url-or-file-path>", file=sys.stderr)
        sys.exit(1)
    src = sys.argv[1]
    res = process_video_source(src)
    print(json.dumps({
        "title": res["title"],
        "duration": res["duration_seconds"],
        "frames_count": len(res["frames"]),
        "transcript_lines": len(res["transcript_segments"]),
        "transcript_source": res["transcript_source"],
    }, indent=2))
