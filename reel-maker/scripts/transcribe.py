"""Read subtitles or transcribe locally; never invent spoken content."""
import argparse
import html
import math
from pathlib import Path
import re
from common import default_backend, duration, ffmpeg, run, write_json
from progress import progress


def timestamp(value):
    parts = value.replace(",", ".").split(":")
    return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))


def spread(text, start, end):
    tokens = text.split()
    weights = [max(1, sum(c.isalnum() for c in t)) for t in tokens]
    total = sum(weights)
    cursor = start
    words = []
    for token, weight in zip(tokens, weights):
        stop = cursor + (end - start) * weight / total
        words.append({"text": token, "start": cursor, "end": stop})
        cursor = stop
    return words


def looping(text):
    tokens = text.lower().split()
    return any(len(tokens) >= n * 5 and any(tokens[i:i+n] * 5 == tokens[i:i+5*n]
               for i in range(len(tokens)-5*n+1)) for n in range(1, 7))


def subtitles(path):
    data = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    words, skipped, cues = [], [], []
    for block in re.split(r"\n\s*\n", data):
        lines = block.splitlines()
        for i, line in enumerate(lines):
            if "-->" not in line:
                continue
            left, right = line.split("-->", 1)
            start, end = timestamp(left.strip()), timestamp(right.strip().split()[0])
            text = html.unescape(re.sub(r"<[^>]+>", "", " ".join(lines[i+1:])))
            if end <= start:
                raise ValueError("NEEDS_REVIEW: subtitle cue has non-positive duration")
            if looping(text):
                skipped.append({"start": start, "end": end, "reason": "repetition loop"})
            else:
                cues.append({"start": start, "end": end, "first_word": len(words), "text": text})
                words.extend(spread(text, start, end))
            break
    # Cue indexes are stable; subtitle cues must arrive in chronological order.
    if any(a["end"] > b["start"] + .001 for a, b in zip(words, words[1:])):
        raise ValueError("NEEDS_REVIEW: overlapping subtitle cues; select the intended speaker first")
    return {"timing": "character-estimate", "words": words, "skipped": skipped, "cues": cues}


def transcript_stem(path):
    return re.sub(r"(?:-transcript| transcript)$", "", Path(path).stem.casefold())


def find_transcript(video):
    video = Path(video)
    candidates = sorted(p for p in video.parent.iterdir() if p.is_file() and
                        p.suffix.lower() in {".srt", ".vtt"} and
                        transcript_stem(p).startswith(transcript_stem(video)))
    if not candidates:
        return None
    if len(candidates) == 1:
        chosen = candidates[0]
    else:
        length = duration(video)
        ranked = []
        for path in candidates:
            try:
                result = subtitles(path)
                last = max((cue["end"] for cue in result["cues"]+result["skipped"]), default=0)
                ranked.append((abs(last-length), path))
            except (ValueError, OSError) as exc:
                print(f"Ignoring transcript {path.name}: {exc}", flush=True)
        if not ranked:
            return None
        chosen = min(ranked)[1]
    print(f"Transcript selected: {chosen.name}", flush=True)
    return chosen


def indexed_transcript(result):
    cues = result.get("cues")
    if cues is None:
        # Whisper words have no supplied cue boundaries: group by sentence or 10 words.
        cues, first = [], 0
        for i, word in enumerate(result["words"]):
            if word["text"].endswith((".", "!", "?")) or i-first >= 9 or i == len(result["words"])-1:
                chunk = result["words"][first:i+1]
                cues.append({"start": chunk[0]["start"], "end": chunk[-1]["end"],
                             "first_word": first, "text": " ".join(w["text"] for w in chunk)})
                first = i+1
    return "".join(f"[{cue['start']:.3f}-{cue['end']:.3f}] #{cue['first_word']} {cue['text']}\n" for cue in cues)


def normalize_words(words, length):
    """Retain lexical indexes after empty removal; reserve 20 ms per word."""
    words = [dict(w, text=w["text"].strip()) for w in words if w["text"].strip()]
    if len(words)*.02 > length:
        raise ValueError("NEEDS_REVIEW: source too short for 20 ms word timings")
    previous = 0
    for i, word in enumerate(words):
        start, end = float(word["start"]), float(word["end"])
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError(f"NEEDS_REVIEW: word {i} timings start={start}, end={end} must be finite")
        ceiling = length-.02*(len(words)-i-1)
        start = max(previous, min(max(0, start), ceiling-.02))
        next_start = float(words[i+1]["start"]) if i+1 < len(words) else length
        if math.isfinite(next_start) and next_start >= start+.02:
            ceiling = min(ceiling, next_start)
        end = min(ceiling, max(start+.02, end))
        word.update(start=start, end=end)
        previous = end
    return words


def recognize(audio, backend):
    words = []
    try:
        with progress(f"Transcribing with {backend}"):
            if backend == "mlx-whisper":
                import mlx_whisper
                segments = mlx_whisper.transcribe(str(audio), path_or_hf_repo="mlx-community/whisper-small-mlx", word_timestamps=True)["segments"]
                for segment in segments:
                    if not looping(segment["text"]):
                        words.extend({"text": w["word"].strip(), "start": w["start"], "end": w["end"]} for w in segment.get("words", []))
            else:
                from faster_whisper import WhisperModel
                model = WhisperModel("small", compute_type="int8")
                segments, _ = model.transcribe(str(audio), word_timestamps=True)
                for segment in segments:
                    if not looping(segment.text):
                        words.extend({"text": w.word.strip(), "start": w.start, "end": w.end} for w in segment.words or [])
    except (ImportError, OSError, RuntimeError) as exc:
        raise RuntimeError("NEEDS_INPUT: local Whisper unavailable; install/cache the chosen backend. " + str(exc)) from exc
    return words


def transcript_matches(video, transcript, result, length, out, backend):
    if not transcript_stem(transcript).startswith(transcript_stem(video)):
        print(f"Ignoring transcript {Path(transcript).name}: filename does not start with video stem.", flush=True)
        return False
    last = max((c["end"] for c in result["cues"]+result["skipped"]), default=0)
    if last-length > min(length*.2, 600):
        print(f"Ignoring transcript {Path(transcript).name}: last cue {last:.1f}s exceeds video {length:.1f}s by more than 20% or 10 minutes.", flush=True)
        return False
    sample = out.parent/"transcript-sample.wav"
    sample_length = min(60, length)
    run([ffmpeg(), "-nostdin", "-y", "-i", video, "-t", str(sample_length), "-vn", "-ar", "16000", "-ac", "1", sample])
    heard = recognize(sample, backend)
    tokens = lambda text: re.findall(r"\w+", text.casefold())
    expected = set(tokens(" ".join(w["text"] for w in result["words"]
                                  if w["start"] < sample_length and w["end"] > 0)))
    spoken = tokens(" ".join(w["text"] for w in heard))
    share = sum(w in expected for w in spoken)/len(spoken) if spoken else 0
    if share < .4:
        print(f"Ignoring transcript {Path(transcript).name}: audio sample word overlap {share:.0%} is below 40%.", flush=True)
        return False
    print(f"Transcript audio check: {share:.0%} word overlap in first {sample_length:.0f}s.", flush=True)
    return True


def transcribe(video, transcript, out, backend=None, no_transcript=False):
    backend = backend or default_backend()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    length = duration(video)
    if no_transcript:
        transcript = None
    elif transcript is None:
        transcript = find_transcript(video)
    result = None
    if transcript:
        try:
            candidate = subtitles(transcript)
            if transcript_matches(video, transcript, candidate, length, out, backend):
                result = {**candidate, "transcript": str(Path(transcript).resolve())}
        except (ValueError, OSError) as exc:
            print(f"Ignoring transcript {Path(transcript).name}: {exc}", flush=True)
    if result is None:
        print("Local transcription may take 10–30 minutes; model download needs network on first use.", flush=True)
        audio = out.parent/"speech.wav"
        run([ffmpeg(), "-nostdin", "-y", "-i", video, "-vn", "-ar", "16000", "-ac", "1", audio])
        result = {"timing": "whisper", "words": normalize_words(recognize(audio, backend), length), "skipped": []}
    if not result["words"]:
        raise ValueError("NEEDS_INPUT: no speech/transcript words found")
    write_json(out, result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--video", type=Path, required=True)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--transcript", type=Path)
    group.add_argument("--no-transcript", action="store_true")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--backend", choices=("faster-whisper", "mlx-whisper"), default=default_backend())
    a = p.parse_args()
    transcribe(a.video, a.transcript, a.out, a.backend, a.no_transcript)
