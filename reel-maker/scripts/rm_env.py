"""Standard-library environment detection and shell-free local media tools."""
from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from functools import lru_cache


class NeedsInput(ValueError):
    """An actionable missing input or dependency (exit 2)."""


def log(message):
    print("[reel-maker] " + str(message), flush=True)


def home():
    return Path(os.environ.get("REEL_MAKER_HOME", "~/.reel-maker")).expanduser().resolve()


def venv_python():
    return home() / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def reexec():
    target = venv_python()
    if os.environ.get("REEL_MAKER_NO_REEXEC") == "1" or not target.exists():
        return
    # Resolve prefix, not executable symlinks: venv python often links to system python.
    if Path(sys.prefix).resolve() == (home() / "venv").resolve():
        return
    args = [str(target), str(Path(__file__).with_name("reelmaker.py")), *sys.argv[1:]]
    if os.name == "nt":
        raise SystemExit(subprocess.call(args))
    os.execv(str(target), args)


def run(args, check=True):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError("Command failed: " + str(args[0]) + "\n" + result.stderr[-4000:])
    return result


def long_run(args, label):
    """Bound output memory and emit progress while a blocking installer works."""
    log(label)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace", dir=home()) as output:
        child = subprocess.Popen([str(a) for a in args], stdout=output, stderr=output)
        try:
            last = time.monotonic()
            while child.poll() is None:
                time.sleep(.25)
                if time.monotonic() - last >= 25:
                    log(label + " — still working")
                    last = time.monotonic()
        except BaseException:
            child.terminate()
            child.wait()
            raise
        if child.returncode:
            output.seek(0, 2)
            output.seek(max(0, output.tell() - 6000))
            raise RuntimeError(output.read() + "\nFix: check free disk space and connectivity, then rerun setup --yes.")


def available(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ValueError, ImportError):
        return False


def apple_silicon():
    return platform.system() == "Darwin" and platform.machine().lower() in ("arm64", "aarch64")


def system_ffmpeg():
    return os.environ.get("REEL_MAKER_FFMPEG") or shutil.which("ffmpeg")


@lru_cache(None)
def ffmpeg():
    path = system_ffmpeg()
    if path:
        return str(path)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise NeedsInput("ffmpeg is missing. Run reelmaker.py setup --yes (includes a local ffmpeg fallback).") from exc


def ffprobe():
    return os.environ.get("REEL_MAKER_FFPROBE") or shutil.which("ffprobe")


def probe(path):
    """Normalized metadata; ffmpeg stderr is a complete ffprobe-free fallback."""
    if ffprobe():
        data = json.loads(run([ffprobe(), "-v", "error", "-show_streams", "-show_format", "-of", "json", path]).stdout)
        video = next((s for s in data["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")), None)
        audio = any(s["codec_type"] == "audio" for s in data["streams"])
        rotation = 0
        if video:
            rotation = float(video.get("tags", {}).get("rotate", 0))
            for side in video.get("side_data_list", []):
                rotation = float(side.get("rotation", rotation))
        w, h = (int(video["width"]), int(video["height"])) if video else (0, 0)
        rate = video.get("avg_frame_rate", "30/1") if video else "30/1"
        a, _, b = rate.partition("/")
        fps = float(a) / (float(b or 1) or 1)
        duration = float(data.get("format", {}).get("duration") or max((float(s.get("duration", 0)) for s in data["streams"]), default=0))
    else:
        result = run([ffmpeg(), "-hide_banner", "-i", path], check=False)
        text = result.stderr
        match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
        if not match:
            raise NeedsInput("Cannot read media duration. Check that the input is a playable local media file.")
        duration = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
        video = next((line for line in text.splitlines() if "Video:" in line and "attached pic" not in line), "")
        size = re.search(r"\b(\d{2,5})x(\d{2,5})\b", video)
        w, h = (int(size[1]), int(size[2])) if size else (0, 0)
        audio = "Audio:" in text
        rot = re.search(r"(?:rotation of|rotate\s*:)\s*(-?[\d.]+)", text)
        rotation = float(rot[1]) if rot else 0
        rate = re.search(r"([\d.]+) fps", video)
        fps = float(rate[1]) if rate else 30
    if round(rotation) % 180:
        w, h = h, w
    if duration <= 0:
        raise NeedsInput("Input has no readable duration.")
    return {"path": str(Path(path).resolve()), "duration": duration, "width": w, "height": h,
            "has_video": bool(w and h), "has_audio": audio, "fps": fps or 30, "rotation": rotation}


@lru_cache(None)
def encoder():
    listing = run([ffmpeg(), "-hide_banner", "-encoders"]).stdout
    for name in ("libx264", "h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf", "h264_mf", "libopenh264"):
        if re.search(r"\b" + name + r"\b", listing):
            return name
    raise NeedsInput("No H.264 encoder found. Install a full ffmpeg build or run setup --yes with imageio-ffmpeg.")


def encoder_args(crf=20):
    name = encoder()
    return ["-c:v", name] + (["-preset", "veryfast", "-crf", str(crf)] if name == "libx264" else ["-b:v", "8M"]) + ["-pix_fmt", "yuv420p"]


def fingerprint(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        h.update(stream.read(64 * 1024 * 1024))
    size = path.stat().st_size
    h.update(str(size).encode("ascii"))
    return {"size": size, "sha256": h.hexdigest()}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def desktop():
    candidates = []
    try:
        if os.name == "nt":
            buf = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:
                candidates.append(Path(buf.value))
        elif "microsoft" in platform.release().lower():
            win = run(["powershell.exe", "-NoProfile", "-Command", "[Environment]::GetFolderPath(\"Desktop\")"]).stdout.strip()
            candidates.append(Path(run(["wslpath", "-u", win]).stdout.strip()))
        elif shutil.which("xdg-user-dir"):
            candidates.append(Path(run(["xdg-user-dir", "DESKTOP"]).stdout.strip()))
    except (OSError, RuntimeError):
        pass
    candidates.extend([Path.home() / "Desktop", Path.cwd()])
    return next(p for p in candidates if p.is_dir())


def source_job(source, out=None):
    from datetime import date
    source = Path(source).resolve()
    base = Path(out).resolve() if out else desktop() / ("Reels - " + source.stem + " - " + date.today().isoformat())
    target, n = base, 2
    while target.exists():
        marker = target / "working" / "source.json"
        if marker.exists() and read_json(marker).get("path") == str(source):
            return target
        if not any(target.iterdir()):
            return target
        if out:
            raise NeedsInput("Output folder is not a job for this source. Choose a new --out folder.")
        target = base.with_name(base.name + " (" + str(n) + ")")
        n += 1
    return target
