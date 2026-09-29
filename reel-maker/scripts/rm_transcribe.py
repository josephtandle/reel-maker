"""Offline transcription/import with stable word indices and source evidence."""
from __future__ import annotations
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from rm_env import NeedsInput, available, apple_silicon, home, read_json, write_json, log, probe, fingerprint, ffmpeg, run


def choose_backend(requested="auto"):
    modules = {"mlx": "mlx_whisper", "faster": "faster_whisper", "whisper": "whisper"}
    order = (["mlx"] if apple_silicon() else []) + ["faster", "whisper"]
    if requested != "auto":
        order = [requested]
    return next((name for name in order if available(modules.get(name, "__missing__"))), None)


def mlx_repo(model):
    return "mlx-community/whisper-" + model + ("" if model == "large-v3-turbo" else "-mlx")


@contextmanager
def heartbeat(message):
    stop = threading.Event()
    def beat():
        while not stop.wait(25):
            log(message + " — still working")
    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def spread(text, start, end):
    tokens = text.split()
    total = sum(len(t) for t in tokens) or 1
    cursor = start
    result = []
    for token in tokens:
        finish = cursor + (end - start) * len(token) / total
        result.append({"text": token, "start": cursor, "end": finish})
        cursor = finish
    return result


def imported(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = read_json(path)
        if data.get("words"):
            return data["words"], data.get("language")
        words = []
        for segment in data.get("segments", []):
            words.extend(segment.get("words") or spread(segment.get("text", ""), float(segment["start"]), float(segment["end"])))
        return words, data.get("language")
    if path.suffix.lower() not in (".srt", ".vtt"):
        raise NeedsInput("Transcript must be JSON, SRT or VTT.")
    text = path.read_text(encoding="utf-8-sig")
    words = []
    def seconds(stamp):
        parts = stamp.replace(",", ".").split(":")
        return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.splitlines()
        for i, line in enumerate(lines):
            match = re.search(r"([\d:,\.]+)\s*-->\s*([\d:,\.]+)", line)
            if match:
                clean = re.sub(r"<[^>]+>", "", " ".join(lines[i+1:]))
                words.extend(spread(clean, seconds(match[1]), seconds(match[2])))
                break
    return words, None


def normalize(raw, duration):
    words, cursor = [], 0.0
    for item in raw:
        text = str(item.get("text", item.get("word", ""))).strip()
        if not text:
            continue
        start = max(cursor, min(duration, float(item["start"])))
        end = max(start, min(duration, float(item["end"])))
        if start >= duration or end <= start:
            continue
        word = {"text": text, "start": round(start, 4), "end": round(end, 4)}
        if "display" in item:
            word["display"] = str(item["display"])
        words.append(word)
        cursor = end
    # Collapse consecutive hallucination loops to their first occurrence.
    i = 0
    while i < len(words):
        removed = False
        for n in range(3, min(31, (len(words)-i)//4 + 1)):
            key = [w["text"].lower() for w in words[i:i+n]]
            repeats = 1
            while [w["text"].lower() for w in words[i+repeats*n:i+(repeats+1)*n]] == key:
                repeats += 1
            if repeats >= 4:
                del words[i+n:i+repeats*n]
                removed = True
                break
        i += n if removed else 1
    for i, word in enumerate(words):
        word["i"] = i
    return words


def sentences(words):
    result, first = [], 0
    def emit(last):
        nonlocal first
        result.append({"start": words[first]["start"], "end": words[last]["end"],
                       "first_word": first, "last_word": last,
                       "text": " ".join(w["text"] for w in words[first:last+1])})
        first = last + 1
    for i, word in enumerate(words):
        if i-first+1 > 35:
            split = max(range(first, i), key=lambda n: words[n+1]["start"]-words[n]["end"])
            emit(split)
        gap = words[i+1]["start"]-word["end"] if i+1 < len(words) else 0
        if (i == len(words)-1 or re.search(r"[.!?][\"’\x27]*$", word["text"])
                or gap > .7 or (i-first+1 >= 18 and gap > .35)):
            emit(i)
    return result


def timestamp(seconds):
    return f"{int(seconds)//60:02d}:{seconds%60:04.1f}"


def transcribe(source, job, backend="auto", model=None, transcript=None, language=None, force=False):
    source, job = Path(source).resolve(), Path(job).resolve()
    if not source.is_file():
        raise NeedsInput("Input file does not exist: " + str(source))
    if source == job or job in source.parents:
        raise NeedsInput("Keep the source outside the output job folder to protect it from generated-file collisions.")
    settings = read_json(home()/"settings.json") if (home()/"settings.json").exists() else {}
    model = model or settings.get("model", "small")
    work = job / "working"
    work.mkdir(parents=True, exist_ok=True)
    info = {**probe(source), **fingerprint(source)}
    marker = work / "source.json"
    if marker.exists() and read_json(marker).get("path") != str(source):
        raise NeedsInput("This job belongs to a different source. Choose a new --out folder.")
    cache = work / "transcript.json"
    if cache.exists() and not force:
        old = read_json(cache)
        same_import = not transcript or old.get("import_fingerprint") == fingerprint(transcript)
        if old.get("source") == str(source) and old.get("model") == model and old.get("source_fingerprint") == fingerprint(source) and same_import:
            log("Using cached transcript")
            return old
    if not info["has_audio"] and not transcript:
        raise NeedsInput("Source has no audio. Supply a transcript with --transcript.")
    write_json(marker, info)
    if transcript:
        log("Importing transcript")
        raw, detected = imported(transcript)
        chosen = "import"
    else:
        chosen = choose_backend(backend)
        if not chosen:
            if backend in ("mlx", "faster"):
                package = {"mlx": "mlx-whisper", "faster": "faster-whisper"}[backend]
                raise NeedsInput(f"{package} is not installed. Run: setup --yes --backend {backend}")
            if backend == "whisper":
                raise NeedsInput("openai-whisper is not installed. Run: setup --yes --backend faster and use --backend faster")
            raise NeedsInput("No transcription backend is installed. Run reelmaker.py setup --yes or pass --transcript FILE.")
        wav = work / "audio.wav"
        log("Extracting mono audio")
        run([ffmpeg(), "-nostdin", "-y", "-v", "error", "-i", source, "-vn", "-ar", "16000", "-ac", "1", wav])
        # Every normal invocation is offline. Only setup --yes may download models.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        log("Transcribing with " + chosen)
        punctuation = {"condition_on_previous_text": False,
                       "initial_prompt": "Hello, and welcome. Today we'll talk about it. Ready? Let's go."}
        with heartbeat("Transcribing"):
            if chosen == "faster":
                from faster_whisper import WhisperModel
                engine = WhisperModel(model, device="auto", compute_type="int8", local_files_only=True, download_root=str(home()/"models"/"faster"))
                segments, meta = engine.transcribe(str(wav), word_timestamps=True, vad_filter=True, language=language, **punctuation)
                raw = [{"text": w.word, "start": w.start, "end": w.end} for s in segments for w in (s.words or [])]
                detected = meta.language
            elif chosen == "mlx":
                import mlx_whisper
                from huggingface_hub import snapshot_download
                local = snapshot_download(mlx_repo(model), local_files_only=True, cache_dir=str(home()/"models"/"mlx"))
                result = mlx_whisper.transcribe(str(wav), path_or_hf_repo=local, word_timestamps=True, language=language, **punctuation)
                raw = [w for s in result["segments"] for w in s.get("words", [])]
                detected = result.get("language")
            else:
                import whisper
                model_path = home()/"models"/"whisper"/(model + ".pt")
                if not model_path.is_file():
                    raise NeedsInput("Whisper model is not cached. Use setup --yes with mlx/faster, or place your downloaded .pt model in " + str(model_path.parent))
                result = whisper.load_model(str(model_path)).transcribe(str(wav), word_timestamps=True, language=language, **punctuation)
                raw = [w for s in result["segments"] for w in s.get("words", [])]
                detected = result.get("language")
    words = normalize(raw, info["duration"])
    if not words:
        raise NeedsInput("No timed words found. Check the transcript or supply a recording with speech.")
    result = {"version": 2, "source": str(source), "backend": chosen, "model": model,
              "language": language or detected or "und", "duration": info["duration"], "has_video": info["has_video"],
              "source_fingerprint": fingerprint(source), "words": words, "segments": sentences(words)}
    if transcript:
        result["import_fingerprint"] = fingerprint(transcript)
    write_json(cache, result)
    (work/"transcript.txt").write_text("\n".join(f"[{timestamp(s['start'])}-{timestamp(s['end'])}] #{s['first_word']} {s['text']}" for s in result["segments"]) + "\n", encoding="utf-8")
    log(f"Transcript ready: {len(words)} words")
    return result
