"""Agent-assisted orchestration: prepare, curate moments.json, render, review."""
import argparse
import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
import platform
import sys
import uuid
from common import default_backend, clean_output, job_path, desktop, digest, duration, read_json, write_json
from contact_sheet import contact_sheet
from render import DEFAULT_CONFIG, render
from transcribe import indexed_transcript, transcribe
from align import align_moment
from verify import verify_job


def new_folder(video):
    root = desktop()
    base = f"Reels - {video.stem} - {date.today().isoformat()}"
    path, suffix = root/base, 2
    while path.exists():
        path = root/f"{base} ({suffix})"
        suffix += 1
    return path


def validate_moments(data, words, length, count):
    if not data.get("transcript_read_in_full") or not data.get("offer"):
        raise ValueError("NEEDS_REVIEW: read the whole transcript and identify the offer")
    # Validate the original cue schedule; aligned selected words can cross estimated neighbours.
    words = [{**w, "start": w.get("est_start", w["start"]), "end": w.get("est_end", w["end"])} for w in words]
    # A transcript made from a longer, untrimmed recording may run past the end of this file.
    # Words that start after the source ends are unusable (never selectable) rather than fatal.
    usable = [w for w in words if math.isfinite(w["start"]) and w["start"] < length]
    for i, word in enumerate(words):
        if not all(math.isfinite(word[k]) for k in ("start", "end")) or not 0 <= word["start"] < word["end"]:
            raise ValueError(f"NEEDS_REVIEW: word {i} ({word['text']!r}) timings start={word['start']}, end={word['end']} must be finite with 0 <= start < end")
    if not usable:
        raise ValueError(f"NEEDS_REVIEW: no words start inside the source ({length}s)")
    if len(usable) < len(words):
        print(f"Warning: {len(words)-len(usable)} transcript words fall after the video ends "
              f"({length:.1f}s); check the transcript matches this exact file.", flush=True)
    for i, (a, b) in enumerate(zip(words, words[1:])):
        if a["end"] > b["start"]+.001:
            raise ValueError(f"NEEDS_REVIEW: word timings overlap at word {i+1}: start={b['start']}, end={b['end']}; previous end={a['end']}")
    candidates = data.get("candidates", [])
    if len(candidates) != 10:
        raise ValueError("NEEDS_REVIEW: score exactly 10 candidates")
    ids, selected = set(), []
    for candidate in candidates:
        number = candidate["id"]
        if not isinstance(number, int) or number < 1 or number in ids:
            raise ValueError("NEEDS_REVIEW: candidate numbers must be unique positive integers")
        ids.add(number)
        scores = candidate["scores"]
        if set(scores) != {"hook", "clarity", "proof", "offer_fit"} or any(type(v) is not int or not 1 <= v <= 5 for v in scores.values()):
            raise ValueError("NEEDS_REVIEW: all four scores must be integers 1–5")
        first, last = candidate["first_word"], candidate["last_word"]
        if not isinstance(first, int) or not isinstance(last, int) or not 0 <= first < last < len(words):
            raise ValueError("NEEDS_REVIEW: invalid inclusive word indexes")
        if words[last]["end"] > length+.1:
            raise ValueError(f"NEEDS_REVIEW: candidate {number} ends after the video ends")
        start = words[first]["start"]
        # Do not include the next sentence in the 0.4 second tail.
        end = min(words[last]["end"]+.4, length, words[last+1]["start"] if last+1 < len(words) else length)
        candidate.update(start=start, end=end, first_word_start=start, total=sum(scores.values()))
        if not 20 <= end-start <= 59 or not candidate.get("reason") or not candidate.get("headline"):
            raise ValueError("NEEDS_REVIEW: candidates need 20–59 seconds, a headline and a reason")
        if not candidate.get("complete_sentences"):
            raise ValueError("NEEDS_REVIEW: confirm complete sentence boundaries")
        if candidate.get("selected"):
            if not 1 <= len(candidate.get("instagram_caption", "").split()) < 120:
                raise ValueError("NEEDS_REVIEW: selected moments need post copy under 120 words")
            if not 1 <= len(candidate.get("cover_text", "").split()) < 5:
                raise ValueError("NEEDS_REVIEW: selected moments need cover text under 5 words")
            selected.append(candidate)
    if len(selected) != count:
        raise ValueError(f"NEEDS_REVIEW: select exactly {count} candidates")
    by_time = sorted(selected, key=lambda m: m["start"])
    if any(a["end"] > b["start"]+.001 for a,b in zip(by_time, by_time[1:])):
        raise ValueError("NEEDS_REVIEW: selected moments overlap")
    return selected


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--video", type=Path, required=True)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--transcript", type=Path)
    group.add_argument("--no-transcript", action="store_true", help="ignore supplied/discovered subtitles; transcribe audio")
    p.add_argument("--count", type=int, default=None, choices=range(2,6), help="default: 2 below 5 minutes, otherwise 3")
    p.add_argument("--out", type=Path)
    p.add_argument("--rerender", type=int, help="candidate id in moments.json")
    p.add_argument("--backend", choices=("faster-whisper", "mlx-whisper"), default=default_backend())
    args = p.parse_args(argv)
    print(f"Operating system: {platform.system()} {platform.release()}", flush=True)
    video = args.video.expanduser().resolve(strict=True)
    out = args.out.expanduser().resolve() if args.out else new_folder(video)
    if out == video or out in video.parents:
        raise ValueError("NEEDS_REVIEW: use a new output folder separate from the source")
    print(f"Output: {out}", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    manifest = job_path(out, "job.json")
    if not manifest.exists():
        if any(out.iterdir()):
            raise ValueError("NEEDS_REVIEW: output folder is not empty; use a new folder")
        length = duration(video)
        if length < 70:
            raise ValueError("NEEDS_INPUT: video must be at least 70 seconds")
        job = {"version": 1, "video": str(video), "baseline": {"duration": length, "size": video.stat().st_size, "sha256": digest(video)}, "reels": {}}
        manifest.parent.mkdir(parents=True, exist_ok=True)
        write_json(manifest, job)
        write_json(out/"reel-maker.config.json", DEFAULT_CONFIG)
    job = read_json(manifest)
    if job["video"] != str(video) or digest(video) != job["baseline"]["sha256"]:
        raise ValueError("NEEDS_REVIEW: source differs from this job's original")
    args.count = args.count or (2 if job["baseline"]["duration"] < 300 else 3)
    if job["baseline"]["duration"] < 300:
        print(f"Short video: making {args.count} reels; default is 2 unless 3 strong non-overlapping moments exist.", flush=True)
    words_path = job_path(out, "words.json")
    if args.no_transcript and words_path.exists() and read_json(words_path).get("timing") != "whisper":
        raise ValueError("NEEDS_INPUT: --no-transcript requires a new --out folder for this subtitle-based job; saved word indexes must be preserved")
    if not words_path.exists():
        scratch = out/"working files"/uuid.uuid4().hex
        scratch.mkdir(parents=True)
        result = transcribe(video, args.transcript, scratch/"words.json", args.backend, args.no_transcript)
        write_json(words_path, result)
        job_path(out, "transcript.txt").write_text(indexed_transcript(result), encoding="utf-8")
    transcript = read_json(words_path)
    moments_path = out/"moments.json"
    if not moments_path.exists():
        template = {"offer": "", "transcript_read_in_full": False, "selection_note": "", "candidates": [
            {"id": i, "first_word": None, "last_word": None, "headline": "", "reason": "",
             "scores": {"hook": 1, "clarity": 1, "proof": 1, "offer_fit": 1}, "complete_sentences": False,
             "selected": False, "instagram_caption": "", "cover_text": "", "participants": []} for i in range(1,11)]}
        write_json(moments_path, template)
        print("NEEDS_REVIEW: read working files/transcript.txt and working files/words.json, score 10 candidates in moments.json, then rerun.")
        return 2
    moments = read_json(moments_path)
    selected = validate_moments(moments, transcript["words"], job["baseline"]["duration"], args.count)
    config = {**DEFAULT_CONFIG, **read_json(out/"reel-maker.config.json")}
    for field in ("font_path", "logo_path"):
        if config.get(field):
            path = Path(config[field]).expanduser()
            config[field] = str(path if path.is_absolute() else out/path)
    if args.rerender and args.rerender not in {m["id"] for m in selected}:
        raise ValueError("NEEDS_REVIEW: --rerender must name a selected candidate; change selections first")
    job["backend"] = args.backend
    desired = {str(m["id"]) for m in selected}
    job["reels"] = {key: val for key,val in job["reels"].items() if key in desired}
    # Always align a fresh copy of the original schedule, including legacy jobs.
    originals = [{**w, "start": w.get("est_start", w["start"]),
                  "end": w.get("est_end", w["end"])} for w in transcript["words"]]
    source_key = hashlib.sha256(json.dumps([
        [w["text"], w["start"], w["end"]] for w in originals]).encode()).hexdigest()
    aligned_words = {}
    for moment in selected:
        key = str(moment["id"])
        alignment_key = [2, moment["first_word"], moment["last_word"], args.backend, source_key]
        current = [dict(w) for w in originals]
        cached = job.get("alignment", {}).get(key)
        if cached and cached["key"] == alignment_key:
            moment.update(cached["boundaries"])
            for index, times in cached["times"].items():
                current[int(index)].update(start=times[0], end=times[1])
        else:
            moment.update(audio_fade_in=0, first_word_text=current[moment["first_word"]]["text"])
            align_moment(video, current, moment, job["baseline"]["duration"],
                         out/"working files"/"alignment", args.backend)
            job.setdefault("alignment", {})[key] = {"key": alignment_key, "boundaries": {
                field: moment[field] for field in ("start", "end", "first_word_start", "first_word_text",
                                                  "audio_fade_in", "alignment") if field in moment},
                "times": {str(i): [current[i]["start"], current[i]["end"]]
                          for i in range(moment["first_word"], moment["last_word"]+1)}}
        aligned_words[key] = [{k: v for k, v in w.items() if k not in ("est_start", "est_end")}
                              for w in current]
    ordered = sorted(selected, key=lambda m: m["start"])
    if any(a["end"] > b["start"]+.001 for a,b in zip(ordered, ordered[1:])):
        raise ValueError("NEEDS_REVIEW: aligned selected moments overlap; adjust word ranges")
    if any(not 20 <= m["end"]-m["start"] <= 59 for m in selected):
        raise ValueError("NEEDS_REVIEW: aligned moment must remain 20–59 seconds; adjust word ranges")
    for number, moment in enumerate(selected, 1):
        moment["reel_number"] = number
        key = str(moment["id"])
        signature_data = {"moment": moment, "words": [{k: w[k] for k in ("text", "start", "end", "display") if k in w}
                                                         for w in aligned_words[key][moment["first_word"]:moment["last_word"]+1]], "config": {k: v for k,v in config.items() if k not in ("font_path", "logo_path")}}
        for field in ("font_path", "logo_path"):
            if config.get(field):
                signature_data[field+"_sha256"] = digest(config[field])
        signature = hashlib.sha256(json.dumps(signature_data, sort_keys=True).encode()).hexdigest()
        if moment["id"] != args.rerender and key in job["reels"]:
            if job["reels"][key].get("signature") != signature:
                raise ValueError(f"NEEDS_REVIEW: candidate {key} or branding changed; rerun with --rerender {key}")
            continue
        if args.rerender and moment["id"] != args.rerender:
            raise ValueError(f"NEEDS_REVIEW: candidate {key} has no render; run without --rerender first")
        tag = uuid.uuid4().hex[:12]
        work = out/"working files"/f"reel-{key}-{tag}"
        slug = re.sub(r"[^a-z0-9]+", "-", moment["headline"].lower()).strip("-")[:48] or "moment"
        output = out/f"Reel {number} - {slug}.mp4"
        pending = out/f"render-{key}-{tag}.mp4"
        print(f"Rendering Reel {number}/{len(selected)} (candidate {key}); this may take several minutes.", flush=True)
        render(video, moment, aligned_words[key], config, pending, work)
        # Only retire the old final after the replacement has rendered successfully.
        if output.exists():
            archive = out/"working files"/"superseded"
            archive.mkdir(parents=True, exist_ok=True)
            output.rename(archive/f"{output.stem}-{tag}.mp4")
        pending.rename(output)
        job["reels"][key] = {"signature": signature, "reel_number": number, "file": output.name, "metadata": str((work/"render.json").relative_to(out)),
                             "evidence": str((work/"evidence").relative_to(out))}
        write_json(manifest, job)
        if job_path(out, "reviews.json").exists():
            reviews = read_json(job_path(out, "reviews.json"))
            reviews.pop(key, None)
            write_json(job_path(out, "reviews.json"), reviews)
    write_json(moments_path, moments)
    write_json(manifest, job)
    posts = []
    for moment in selected:
        posts += [f"Reel {moment['reel_number']}: {moment['headline']} (candidate {moment['id']})", f"Source: {moment['start']:.3f}–{moment['end']:.3f}s",
                  f"Why: {moment['reason']}", "Caption: " + moment.get("instagram_caption", ""),
                  "Cover: " + moment.get("cover_text", ""), "Participants: " + ", ".join(moment.get("participants", [])), ""]
    (out/"clips-and-captions.txt").write_text("\n".join(posts), encoding="utf-8")
    reports = verify_job(out)
    contact_sheet(out)
    clean_output(out, job)
    complete = len(reports) == args.count and all(c["status"] == "PASS" for r in reports for c in r["checks"].values())
    print("All checks passed." if complete else "NEEDS_REVIEW: see tests.md, inspect stills and machine audio evidence; record working files/reviews.json, then run verify.py.")
    return 0 if complete else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
