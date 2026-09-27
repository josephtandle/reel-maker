"""Local-only I/O, tool discovery and portable output locations."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def run(args):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Command failed: {args!r}\n{result.stderr[-6000:]}")
    return result.stdout


def ffmpeg():
    executable = os.environ.get("REEL_MAKER_FFMPEG") or shutil.which("ffmpeg")
    if not executable:
        try:
            import imageio_ffmpeg
            executable = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError as exc:
            raise RuntimeError("NEEDS_INPUT: install imageio-ffmpeg in the job venv") from exc
    return executable


def probe(path):
    executable = os.environ.get("REEL_MAKER_FFPROBE") or shutil.which("ffprobe")
    if not executable:
        raise RuntimeError("NEEDS_INPUT: ffprobe is required for verified durations; imageio-ffmpeg alone does not supply it")
    return json.loads(run([executable, "-v", "error", "-show_streams", "-show_format", "-of", "json", path]))


def duration(path):
    return float(probe(path)["format"]["duration"])


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def desktop():
    if platform.system() == "Windows":
        # CSIDL_DESKTOPDIRECTORY resolves redirected/OneDrive known folders.
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf):
            raise RuntimeError("NEEDS_INPUT: Windows Desktop could not be resolved")
        return Path(buf.value)
    if "microsoft" in platform.release().lower():
        win = run(["powershell.exe", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"]).strip()
        return Path(run(["wslpath", "-u", win]).strip())
    if platform.system() == "Linux" and shutil.which("xdg-user-dir"):
        return Path(run(["xdg-user-dir", "DESKTOP"]).strip())
    return Path.home() / "Desktop"


def video_stream(info):
    return next(s for s in info["streams"] if s["codec_type"] == "video")


def encoder_args():
    available = run([ffmpeg(), "-hide_banner", "-encoders"])
    for name in ("libx264", "h264_videotoolbox", "libopenh264", "h264_mf"):
        if name in available:
            return ["-c:v", name] + (["-crf", "20", "-preset", "veryfast"] if name == "libx264" else ["-b:v", "6M"])
    raise RuntimeError("NEEDS_INPUT: no H.264 encoder; try the imageio-ffmpeg build")


def job_path(out, name):
    """Read legacy top-level state, otherwise use the tidy resumable state directory."""
    out = Path(out)
    return out/name if (out/name).exists() else out/"working files"/name


def clean_output(out, job):
    """Archive job-created intermediates and superseded renders, preserving every file."""
    out = Path(out)
    work = out/"working files"
    work.mkdir(exist_ok=True)
    keep = {"working files", "contact-sheet.jpg", "tests.md", "moments.json",
            "clips-and-captions.txt", "reel-maker.config.json"}
    keep.update(reel["file"] for reel in job["reels"].values())
    moved = {}
    for path in out.iterdir():
        if path.name in keep:
            continue
        target = work/path.name
        suffix = 2
        while target.exists():
            target = work/f"{path.stem}-{suffix}{path.suffix}"
            suffix += 1
        path.rename(target)
        moved[path.name] = str(target.relative_to(out))
    config_path = out/"reel-maker.config.json"
    if config_path.exists():
        config = read_json(config_path)
        for field in ("font_path", "logo_path"):
            if not config.get(field):
                continue
            asset = Path(config[field])
            if asset.is_absolute():
                try:
                    asset = asset.relative_to(out)
                except ValueError:
                    continue
            if asset.parts and asset.parts[0] in moved:
                config[field] = str(Path(moved[asset.parts[0]]).joinpath(*asset.parts[1:]))
        write_json(config_path, config)
