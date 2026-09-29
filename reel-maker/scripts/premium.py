#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Optional Remotion renderer. Python 3.9+, standard library only."""
import argparse
from collections import deque
from datetime import datetime
import importlib
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import uuid


PREMIUM = Path(__file__).resolve().parents[1] / "premium"


class RenderError(RuntimeError):
    pass


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def finite(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (ValueError, TypeError):
        return default


def run(command, cwd=None):
    """Stream foreground child output; keep a bounded diagnostic tail."""
    if "remotion" in command and "render" in command:
        print("Running: " + " ".join(str(arg) for arg in command), flush=True)
    process = subprocess.Popen([str(arg) for arg in command], cwd=cwd,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
    lines = queue.Queue()

    def read_output():
        try:
            for line in process.stdout:
                lines.put(line.rstrip())
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    tail = deque(maxlen=40)
    heartbeat = time.monotonic()
    try:
        while True:
            try:
                line = lines.get(timeout=1)
                if line is None:
                    break
                tail.append(line)
                print(line, flush=True)
            except queue.Empty:
                pass
            if time.monotonic() - heartbeat >= 30:
                print("Premium render: still working...", flush=True)
                heartbeat = time.monotonic()
        code = process.wait()
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    finally:
        reader.join(timeout=2)
        process.stdout.close()
    if code:
        detail = "\n".join(tail)
        print("Last 40 process output lines:\n" + detail, file=sys.stderr)
        if "ENOTCACHED" in detail:
            diagnosis = "Dependencies are not cached for offline installation; install them once with network access enabled."
        elif re.search(r"chrome|chromium|browser|download", detail, re.I):
            diagnosis = "Browser setup failed; try `npx remotion browser ensure` in the premium folder and check network access."
        elif re.search(r"font|fetch|ENOTFOUND|ETIMEDOUT|network", detail, re.I):
            diagnosis = "A download failed; check access to npm, Google Fonts, and the browser download host."
        else:
            diagnosis = "Rendering failed; inspect the process output above and verify the input clip and props."
        raise RenderError(diagnosis)


def find_ffmpeg():
    override = os.environ.get("REEL_MAKER_FFMPEG")
    if override:
        resolved = shutil.which(override)
        if resolved:
            return resolved
        raise RenderError("REEL_MAKER_FFMPEG does not point to an executable.")
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        return importlib.import_module("imageio_ffmpeg").get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        raise RenderError("Install ffmpeg or set REEL_MAKER_FFMPEG to its executable.")


def duration(path, ffmpeg):
    probe = shutil.which("ffprobe")
    if probe:
        result = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration",
                                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                                capture_output=True, text=True)
        value = finite(result.stdout)
        if result.returncode == 0 and value > 0:
            return value
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                            capture_output=True, text=True)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise RenderError("Could not determine clip duration: " + str(path))
    hours, minutes, seconds = map(float, match.groups())
    return hours * 3600 + minutes * 60 + seconds


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def card_segments(data, length):
    vw, vh = finite(data.get("source_w")), finite(data.get("source_h"))
    if vw <= 0 or vh <= 0:
        raise RenderError("crop.json needs positive source_w and source_h.")
    area = data.get("black_bars") or {"x": 0, "y": 0, "w": vw, "h": vh}
    ax, ay = max(0, finite(area.get("x"))), max(0, finite(area.get("y")))
    aw = min(finite(area.get("w"), vw), vw - ax)
    ah = min(finite(area.get("h"), vh), vh - ay)
    if aw <= 0 or ah <= 0:
        ax, ay, aw, ah = 0, 0, vw, vh
    whole = {"x": ax, "y": ay, "w": aw, "h": ah, "mode": "contain"}
    faces = [f for f in (data.get("faces") or []) if isinstance(f, dict)
             and finite(f.get("w")) > 0 and finite(f.get("h")) > 0]
    raw = data.get("segments") or [{"from": 0, "to": length}]
    segments = []
    cursor = 0.0
    for segment in sorted(raw, key=lambda item: finite(item.get("from"))):
        start = max(cursor, min(length, finite(segment.get("from"))))
        end = max(start, min(length, finite(segment.get("to"), length)))
        if end <= start:
            continue
        if start > cursor:
            segments.append({"from": cursor, "to": start, "crop": whole.copy()})
        visible = [f for f in faces if start <= finite(f.get("t"), -1) < end]
        crop = whole.copy()
        if visible and data.get("layout") != "fit":
            head_top = percentile([finite(f.get("y")) - 0.62 * finite(f.get("h")) for f in visible], 0.1)
            chin = percentile([finite(f.get("y")) + 1.1 * finite(f.get("h")) for f in visible], 0.9)
            height = max((chin - head_top) / 0.68, 0.66 * ah)
            y = head_top - 0.09 * height
            if y + height > ay + ah:
                height = min((ay + ah - head_top) / 0.91, 1.3 * ah)
                y = ay + ah - height
            if height > 0:
                width = height * 960 / 990
                center = statistics.median([finite(f.get("x")) + finite(f.get("w")) / 2 for f in visible])
                # If the crop extends beyond both sides, keep its center in the active area.
                x = (max(ax, min(ax + aw - width, center - width / 2))
                     if width <= aw else ax + (aw - width) / 2)
                crop = {"x": x, "y": y, "w": width, "h": height, "mode": "cover"}
        segments.append({"from": start, "to": end, "crop": crop})
        cursor = end
    if cursor < length:
        segments.append({"from": cursor, "to": length, "crop": whole.copy()})
    return int(vw), int(vh), segments


def clean_words(raw, length):
    words = []
    for word in raw:
        if not isinstance(word, dict) or not word.get("text"):
            continue
        start = max(0, finite(word.get("start")))
        end = min(length, finite(word.get("end")))
        if end > start:
            words.append({"text": str(word["text"]), "start": start, "end": end})
    return sorted(words, key=lambda word: word["start"])


def measure_audio(source, ffmpeg):
    result = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(source), "-vn", "-af",
                             "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                             "-f", "null", "-"], capture_output=True, text=True)
    matches = re.findall(r'\{\s*"input_i"[\s\S]*?\}', result.stderr)
    if result.returncode or not matches:
        print("\n".join(result.stderr.splitlines()[-40:]), file=sys.stderr)
        raise RenderError("Loudness measurement failed; verify that the rendered clip has an audio track.")
    measurement = json.loads(matches[-1])
    return measurement


def normalize_audio(source, ffmpeg):
    measurement = measure_audio(source, ffmpeg)
    integrated = float(measurement["input_i"])
    if not math.isfinite(integrated):
        print("Audio is silent; -14 LUFS cannot be reached without adding sound.", flush=True)
        return source
    print("Rendered integrated loudness: %.2f LUFS" % integrated, flush=True)
    if abs(integrated + 14) <= .5:
        return source
    candidates, measurements = [source], [measurement]
    temporary = []
    chosen = 0
    try:
        def correct(filters):
            fixed = source.with_name(source.stem + "-audio-" + uuid.uuid4().hex + ".mp4")
            temporary.append(fixed)
            run([ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-i", source,
                 "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", filters,
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", fixed])
            measurements.append(measure_audio(fixed, ffmpeg))
            candidates.append(fixed)

        settings = {"measured_I": "input_i", "measured_TP": "input_tp", "measured_LRA": "input_lra",
                    "measured_thresh": "input_thresh", "offset": "target_offset"}
        if all(math.isfinite(float(measurement[field])) for field in settings.values()):
            filters = "loudnorm=I=-14:TP=-1.5:LRA=11:linear=true"
            filters += "".join(":%s=%s" % (option, measurement[field]) for option, field in settings.items())
            correct(filters)
        corrected = float(measurements[-1]["input_i"])
        if not math.isfinite(corrected) or abs(corrected + 14) > .5:
            correct(f"volume={-14-integrated}dB,alimiter=limit=0.79:level=false:asc=1,aresample=48000")
        safe = [i for i, item in enumerate(measurements) if float(item["input_tp"]) <= -1.0]
        def distance(i):
            value = float(measurements[i]["input_i"])
            return abs(value + 14) if math.isfinite(value) else math.inf
        chosen = min(safe or range(len(measurements)), key=distance)
        corrected = float(measurements[chosen]["input_i"])
        if not math.isfinite(corrected) or abs(corrected + 14) > .5:
            print(f"Loudness {corrected:.2f} LUFS (target -14; peaks limited the correction)", flush=True)
        return candidates[chosen]
    finally:
        for candidate in temporary:
            if candidate != candidates[chosen]:
                candidate.unlink(missing_ok=True)


def render_reel(number, moment, job, brand, home, args, npx, ffmpeg):
    working = job / "working" / ("reel-%d" % number)
    clip = working / "clip.mp4"
    if not clip.is_file():
        raise RenderError("Missing clip: " + str(clip) + ". Run the default pipeline first.")
    length = duration(clip, ffmpeg) - 0.05
    if length <= 0:
        raise RenderError("The clip is too short to render.")
    crop = read_json(working / "crop.json")
    vw, vh, segments = card_segments(crop, length)
    words_file = working / "words.json"
    words = clean_words(read_json(words_file) if words_file.exists() else [], length)
    public = job / "working" / "premium-public"
    public.mkdir(parents=True, exist_ok=True)
    video_file = "reel-%d.mp4" % number
    shutil.copy2(clip, public / video_file)
    cta_word = str(brand.get("cta_word") or "MORE")
    props = {
        "videoFile": video_file, "videoWidth": vw, "videoHeight": vh, "durationSec": length, "fps": 30,
        "eyebrow": args.eyebrow if args.eyebrow is not None else str(brand.get("handle") or brand.get("name") or ""),
        "headline": str(moment.get("headline") or "A moment worth sharing"), "words": words,
        "cropSegments": segments,
        "speakers": [{"from": 0, "to": length, "name": str(moment["speaker"]),
                      "role": str(moment.get("speaker_role") or "")}] if moment.get("speaker") else [],
        "brandName": str(brand.get("name") or "Your Name"), "handle": str(brand.get("handle") or "@yourhandle"),
        "brandColor": str(brand.get("color") or "#2E86DE"), "accentColor": str(brand.get("accent") or "#F5C3C6"),
        "cta": str(brand.get("cta_text") or "Follow for more").replace("{CTA_WORD}", cta_word),
    }
    if brand.get("logo"):
        logo = Path(str(brand["logo"])).expanduser()
        if not logo.is_absolute():
            logo = home / logo
        if not logo.is_file() or logo.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
            raise RenderError("Brand logo must be an existing PNG, JPG, WebP, or SVG file.")
        logo_name = "brand-logo" + logo.suffix.lower()
        shutil.copy2(logo, public / logo_name)
        props["logoFile"] = logo_name
        # An omitted aspect keeps intrinsic artwork visible with object-fit: contain.
        props["logoAspect"] = max(0.1, finite(brand.get("logo_aspect"), 1))
    props_file = working / "premium-props.json"
    props_file.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary = working / ("premium-" + uuid.uuid4().hex + ".mp4")
    run([npx, "--no-install", "remotion", "render", "src/index.tsx", "reel", temporary,
         "--props=" + str(props_file), "--public-dir=" + str(public), "--concurrency", str(args.concurrency)], cwd=PREMIUM)
    rendered = normalize_audio(temporary, ffmpeg)
    manifest_path = job / "working" / "renders.json"
    reels = read_json(manifest_path).get("reels", []) if manifest_path.exists() else []
    standard = next((reel for reel in reels if reel.get("number") == number), None)
    if standard is not None:
        stem = Path(standard["file"]).stem
    else:
        custom_slug = moment.get("slug")
        title = custom_slug if isinstance(custom_slug, str) and custom_slug else props["headline"]
        title = title.replace("*", "").replace("'", "").replace("’", "").lower()
        slug = re.sub(r"[^a-z0-9]+", "-", title).strip("-")[:70] or "highlight"
        stem = "Reel %d - %s" % (number, slug)
    final = job / (stem + " (premium).mp4")
    archived = None
    if final.exists():
        old = job / "working" / "old"
        old.mkdir(parents=True, exist_ok=True)
        archived = old / (final.stem + "-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".mp4")
        shutil.move(str(final), str(archived))
    try:
        shutil.move(str(rendered), str(final))
    except OSError:
        if archived is not None and not final.exists():
            shutil.move(str(archived), str(final))
        raise
    return str(final)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--only", help="Comma-separated reel numbers (selected moments in file order)")
    parser.add_argument("--yes", action="store_true", help="Allow one-time local npm dependency installation")
    parser.add_argument("--eyebrow")
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency must be positive")
    only = None
    if args.only:
        try:
            only = {int(value.strip()) for value in args.only.split(",")}
            if not only or min(only) < 1:
                raise ValueError()
        except ValueError:
            parser.error("--only must contain positive reel numbers, e.g. 1,2")
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    try:
        node_version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout if node else ""
        match = re.match(r"v?(\d+)", node_version.strip())
        ready = bool(match and int(match.group(1)) >= 18 and npm and npx)
    except (OSError, subprocess.SubprocessError):
        ready = False
    if not ready:
        print("Premium mode needs Node.js 18 or newer, npm, and npx. Install the LTS version from https://nodejs.org, then reopen your terminal.", file=sys.stderr)
        return 2
    if not (PREMIUM / "node_modules").is_dir():
        if not args.yes:
            print("Premium mode needs a one-time install of Remotion (~250 MB including a headless Chrome download) into %s. Re-run with --yes to allow it." % PREMIUM)
            return 3
        run([npm, "install", "--no-fund", "--no-audit"], cwd=PREMIUM)
    job = args.out.expanduser().resolve()
    data = read_json(job / "moments.json")
    moments = [moment for moment in data.get("moments", []) if moment.get("selected", False)]
    if only and not only.issubset(set(range(1, len(moments) + 1))):
        raise RenderError("--only refers to a reel number outside the selected moments.")
    home = Path(os.environ.get("REEL_MAKER_HOME", str(Path.home() / ".reel-maker"))).expanduser()
    brand_file = home / "brand.json"
    brand = read_json(brand_file) if brand_file.exists() else {}
    ffmpeg = find_ffmpeg()
    files = [render_reel(number, moment, job, brand, home, args, npx, ffmpeg)
             for number, moment in enumerate(moments, 1) if only is None or number in only]
    print("RESULT " + json.dumps({"status": "ok", "files": files}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RenderError, OSError, ValueError, TypeError, KeyError) as error:
        print("Premium mode: " + str(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Premium mode: interrupted.", file=sys.stderr)
        sys.exit(1)
