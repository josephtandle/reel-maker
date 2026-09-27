"""Bounded local Whisper alignment and PCM evidence; never download a model here."""
from array import array
import difflib
from functools import lru_cache
import math
from pathlib import Path
import re
import sys
import wave
from common import ffmpeg, run


def normalized(text):
    return re.sub(r"[^\w]", "", text.casefold().replace("_", ""))


@lru_cache(maxsize=2)
def local_model(backend):
    if backend == "faster-whisper":
        from faster_whisper import WhisperModel
        return WhisperModel("small", compute_type="int8", local_files_only=True)
    from huggingface_hub import snapshot_download
    return snapshot_download("mlx-community/whisper-small-mlx", local_files_only=True)


def whisper_words(audio, backend="faster-whisper"):
    failures = []
    for engine in (backend, "mlx-whisper" if backend == "faster-whisper" else "faster-whisper"):
        try:
            if engine == "mlx-whisper":
                import mlx_whisper
                result = mlx_whisper.transcribe(str(audio), path_or_hf_repo=local_model(engine), word_timestamps=True)
                words = [{"text": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
                         for segment in result["segments"] for w in segment.get("words", [])]
            else:
                segments, _ = local_model(engine).transcribe(str(audio), word_timestamps=True)
                words = [{"text": w.word.strip(), "start": float(w.start), "end": float(w.end)}
                         for segment in segments for w in (segment.words or [])]
            return [w for w in words if normalized(w["text"]) and
                    math.isfinite(w["start"]) and math.isfinite(w["end"]) and 0 <= w["start"] < w["end"]]
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            failures.append(f"{engine}: {exc}")
    raise RuntimeError("Local Whisper unavailable (install backend and cache its model when permitted): " + "; ".join(failures))


def extract_audio(video, target, start=0, length=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg(), "-nostdin", "-y", "-v", "error", "-ss", str(start), "-i", video]
    if length is not None:
        command += ["-t", str(length)]
    run(command + ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", target])


def energy_frames(wav):
    """20 ms mono PCM RMS, scaled to full amplitude, using only the standard library."""
    with wave.open(str(wav), "rb") as source:
        if source.getsampwidth() != 2 or source.getnchannels() != 1:
            raise ValueError("Expected mono 16-bit PCM")
        samples = array("h", source.readframes(source.getnframes()))
        rate = source.getframerate()
    if sys.byteorder != "little":
        samples.byteswap()
    hop = max(1, round(rate*.02))
    return [(i/rate, math.sqrt(sum(v*v for v in samples[i:i+hop])/len(samples[i:i+hop]))/32768)
            for i in range(0, len(samples), hop)]


def silence_start(frames, first, offset=0):
    """End of the nearest >=60 ms quiet gap before speech; no arbitrary lead-in."""
    gaps, beginning = [], None
    for relative, rms in frames:
        t = offset + relative
        if t + .02 > first + .001:
            break
        if rms < .006:
            if beginning is None:
                beginning = t
            if t+.02-beginning >= .059:
                gaps.append(t+.02)
        else:
            beginning = None
    # Long pauses are not lead-ins. Keep at most 300 ms of proven quiet before the word.
    boundary = gaps[-1] if gaps and first-gaps[-1] <= .3 else first
    return max(offset, boundary-.02 if gaps and boundary == gaps[-1] else boundary), bool(gaps and first-gaps[-1] <= .3)


def quiet_runs(frames, offset=0, threshold=.006, minimum=.059):
    runs, begin = [], None
    for relative, rms in frames + [(frames[-1][0]+.02 if frames else 0, 1)]:
        t = offset + relative
        if rms < threshold:
            begin = t if begin is None else begin
        else:
            if begin is not None and t-begin >= minimum:
                runs.append((begin, t))
            begin = None
    return runs


def snap_to_speech(refined, first, last, frames, offset, prev_end, anchors=None):
    """Keep word boundaries out of proven quiet: a word never starts or ends inside a >=60 ms gap,
    and a late Whisper start moves back to the voiced onset after the previous word ended."""
    runs = quiet_runs(frames, offset)
    out = dict(refined)
    for i in range(first, last+1):
        s, e = out[i]
        if anchors is not None and i not in anchors:
            prev_end = e
            continue
        for qs, qe in runs:
            if qs <= s < qe and qe < e-.02:
                s = qe
                break
        else:
            before = [qe for qs, qe in runs if prev_end-.001 <= qe <= s and s-qe <= .6]
            if before:
                s = before[-1]
        for qs, qe in runs:
            if qs < e <= qe and qs > s+.02:
                e = qs
                break
        # Energy is supporting evidence, not permission to overlap another word.
        s = max(s, prev_end)
        if s < e:
            out[i] = (s, e)
        prev_end = e
    return out


def matched_pairs(expected, heard):
    a, b = [normalized(w["text"]) for w in expected], [normalized(w["text"]) for w in heard]
    return {i+k: j+k for i, j, size in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks()
            for k in range(size) if a[i+k]}


def align_moment(video, words, moment, length, work, backend="faster-whisper", aligner=None):
    first, last = moment["first_word"], moment["last_word"]
    selected = words[first:last+1]
    for word in selected:
        word["start"] = word.get("est_start", word["start"])
        word["end"] = word.get("est_end", word["end"])
    start = max(0, selected[0].get("est_start", selected[0]["start"])-2)
    end = min(length, selected[-1].get("est_end", selected[-1]["end"])+2)
    wav = Path(work)/f"alignment-{moment['id']}.wav"
    report = {"status": "NEEDS_REVIEW", "matched_share": 0, "max_drift": 0, "window": [start, end]}
    try:
        extract_audio(video, wav, start, end-start)
        heard = (aligner or whisper_words)(wav, backend)
        heard = [{**w, "start": w["start"]+start, "end": w["end"]+start} for w in heard
                 if 0 <= w["start"] < w["end"] <= end-start+.05]
        # Include neighbouring text so repeated short words do not steal padding anchors.
        indexes = [i for i, w in enumerate(words)
                   if w.get("est_start", w["start"]) < end and w.get("est_end", w["end"]) > start]
        pairs = matched_pairs([words[i] for i in indexes], heard)
        anchors = {indexes[i]: heard[j] for i, j in pairs.items()}
        hits = sum(i in anchors for i in range(first, last+1))
        report["matched_share"] = hits/len(selected)
        report["unmatched_words"] = [dict(index=i, text=words[i]["text"])
                                     for i in range(first, last+1) if i not in anchors]
        if not hits:
            raise RuntimeError("No transcript words matched local Whisper; retaining estimated timing")
        refined = {}
        for i in range(first, last+1):
            if i in anchors:
                refined[i] = (anchors[i]["start"], anchors[i]["end"])
                continue
            left = max((k for k in anchors if k < i), default=first-1)
            right = min((k for k in anchors if k > i), default=last+1)
            lo = anchors[left]["end"] if left in anchors else start
            hi = anchors[right]["start"] if right in anchors else end
            need = .02*(right-left-1)
            if hi-lo < need and left in anchors:
                lo = max(anchors[left]["start"]+.02, hi-need)
                if left in refined:
                    refined[left] = (refined[left][0], min(refined[left][1], lo))
            # Keep uncertain tokens beside an anchor, never across a long pause.
            budget = .3*(right-left-1)
            if hi-lo > budget:
                midpoint = sum((words[k]["start"]+words[k]["end"])/2
                               for k in range(left+1, right))/(right-left-1)
                if left in anchors and (right not in anchors or midpoint-lo <= hi-midpoint):
                    hi = lo+budget
                else:
                    lo = hi-budget
            weights = [max(1, len(normalized(words[k]["text"]))) for k in range(left+1, right)]
            total = sum(weights)
            pos = i-left-1
            refined[i] = (lo+(hi-lo)*sum(weights[:pos])/total,
                          lo+(hi-lo)*sum(weights[:pos+1])/total)
        frames = energy_frames(wav)
        refined = snap_to_speech(refined, first, last, frames, start,
                                 anchors.get(first-1, {}).get("end", start), anchors)
        if any(not 0 <= s < e <= length for s, e in refined.values()) or any(
                refined[i][1] > refined[i+1][0]+.001 for i in range(first, last)):
            raise RuntimeError("Whisper anchors overlap or leave no interpolation space; retaining estimated timing")
        report["max_drift"] = max(abs(t-words[i].get("est_"+field, words[i][field]))
                                  for i, times in refined.items() for field, t in zip(("start", "end"), times))
        for i, (s, e) in refined.items():
            words[i].setdefault("est_start", words[i]["start"])
            words[i].setdefault("est_end", words[i]["end"])
            words[i].update(start=s, end=e)
        cut_start, quiet = silence_start(frames, words[first]["start"], start)
        if not quiet:
            cut_start = max(0, words[first]["start"]-.08)
        next_start = min((w["start"] for w in heard if w["start"] >= words[last]["end"]-.001), default=length)
        moment.update(start=cut_start, first_word_start=words[first]["start"],
                      first_word_text=words[first]["text"], audio_fade_in=0 if quiet else .12,
                      end=min(length, words[last]["end"]+.15, next_start))
        report.update(status="PASS" if report["matched_share"] >= .9 else "NEEDS_REVIEW",
                      silence_gap_found=quiet, start_strategy="quiet_gap" if quiet else "continuous_speech",
                      audio_fade_in=moment["audio_fade_in"],
                      reason="Whisper matched words; unmatched words placed beside anchors")
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        report["reason"] = str(exc)
    moment["alignment"] = report
    return report
