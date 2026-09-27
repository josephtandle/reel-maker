"""Read subtitles or transcribe locally; never invent spoken content."""
import argparse
import html
from pathlib import Path
import re
from common import duration, ffmpeg, run, write_json


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


def find_transcript(video):
    video = Path(video)
    candidates = sorted(p for p in video.parent.iterdir() if p.is_file() and
                        p.suffix.lower() in {".srt", ".vtt"} and
                        (video.stem.casefold() in p.stem.casefold() or
                         "transcript" in p.stem.casefold()))
    if not candidates:
        return None
    if len(candidates) == 1:
        chosen = candidates[0]
    else:
        length = duration(video)
        def distance(path):
            cues = subtitles(path)["cues"]
            return abs(max((cue["end"] for cue in cues), default=0)-length)
        chosen = min(candidates, key=distance)
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


def transcribe(video, transcript, out, backend="faster-whisper"):
    if transcript is None:
        transcript = find_transcript(video)
    if transcript:
        result = subtitles(transcript)
        result["transcript"] = str(Path(transcript).resolve())
    else:
        print("Local transcription may take 10–30 minutes; model download needs network on first use.", flush=True)
        audio = out.parent / "speech.wav"
        run([ffmpeg(), "-nostdin", "-n", "-i", video, "-vn", "-ar", "16000", "-ac", "1", audio])
        words = []
        try:
            if backend == "mlx-whisper":
                import mlx_whisper
                segments = mlx_whisper.transcribe(str(audio), path_or_hf_repo="mlx-community/whisper-small-mlx", word_timestamps=True)["segments"]
                for segment in segments:
                    if not looping(segment["text"]):
                        words.extend({"text": w["word"].strip(), "start": w["start"], "end": w["end"]} for w in segment["words"])
            else:
                from faster_whisper import WhisperModel
                model = WhisperModel("small", compute_type="int8")
                segments, _ = model.transcribe(str(audio), word_timestamps=True)
                for segment in segments:
                    print(f"Transcribed through {segment.end:.0f}s", flush=True)
                    if not looping(segment.text):
                        words.extend({"text": w.word.strip(), "start": w.start, "end": w.end} for w in segment.words or [])
        except (ImportError, OSError, RuntimeError) as exc:
            raise RuntimeError("NEEDS_INPUT: local Whisper unavailable; attach VTT/SRT. " + str(exc)) from exc
        result = {"timing": "whisper", "words": words, "skipped": []}
    if not result["words"]:
        raise ValueError("NEEDS_INPUT: no speech/transcript words found")
    write_json(out, result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--transcript", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--backend", choices=("faster-whisper", "mlx-whisper"), default="faster-whisper")
    a = p.parse_args()
    transcribe(a.video, a.transcript, a.out, a.backend)
