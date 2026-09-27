"""Mechanical and machine-listening checks plus digest-bound still review."""
import argparse
from pathlib import Path
from common import job_path, digest, duration, ffmpeg, probe, read_json, run, video_stream, write_json
from align import energy_frames, extract_audio, matched_pairs, normalized, whisper_words

LABELS = ["Length 20–59 s", "1080×1920", "Whole foreground", "Headline safe and readable",
          "Caption sync ±0.5 s", "Clean first word", "Face clear", "Audio present",
          "Source unchanged", "Decodes to end"]
REVIEW_TESTS = {"T3", "T4", "T7"}
FILLERS = {"um", "uh", "er", "ah"}


def machine_listen(reel, metadata, evidence, backend="faster-whisper", aligner=None):
    wav = evidence/"speech.wav"
    result = {"T5": {"status": "NEEDS_REVIEW"}, "T6": {"status": "NEEDS_REVIEW"}}
    try:
        extract_audio(reel, wav)
        opening_frames = [(t,rms) for t,rms in energy_frames(wav) if t < 1]
        frames = [(t,rms) for t,rms in opening_frames if t < .3]
        result["T6"]["energy_first_0_3"] = frames
        heard = (aligner or whisper_words)(wav, backend)
        events = metadata["events"]
        expected = [{"text": e["words"][e["active"]], "start": e["start"], "end": e["end"]} for e in events]
        pairs = matched_pairs(expected, heard)
        fillers = {i for i, word in enumerate(expected) if normalized(word["text"]) in FILLERS}
        eligible = {i: j for i, j in pairs.items() if i not in fillers}
        unmatched = [dict(index=i, **word) for i, word in enumerate(expected)
                     if i not in fillers and i not in pairs]
        offsets = {i: max(abs(expected[i]["start"]-heard[j]["start"]),
                          abs(expected[i]["end"]-heard[j]["end"])) for i,j in eligible.items()}
        within = sum(v <= .5 for v in offsets.values())/len(offsets) if offsets else 0
        maximum = max(offsets.values(), default=None)
        length = metadata["moment"]["end"]-metadata["moment"]["start"]
        samples = []
        for fraction in (.25, .5, .75):
            t = length*fraction
            nearby = [i for i in offsets if abs(expected[i]["start"]-t) <= 3]
            caption_near = [w for w in expected if abs(w["start"]-t) <= 3]
            heard_near = [w for w in heard if abs(w["start"]-t) <= 3]
            blank = not caption_near and not heard_near
            sample_max = max((offsets[i] for i in nearby), default=None)
            samples.append({"fraction": fraction, "time": t, "offset_seconds": sample_max,
                            "status": ("PASS" if blank else "EXCLUDED") if sample_max is None else
                                      ("PASS" if sample_max <= .5 else "FAIL"),
                            "heard": " ".join(w["text"] for w in heard_near),
                            "visible": " ".join(w["text"] for w in caption_near)})
        passed = within >= .9 and maximum is not None and maximum <= 1 and all(s["status"] != "FAIL" for s in samples)
        result["T5"] = {"status": ("PASS" if passed else "FAIL") if offsets else "NEEDS_REVIEW",
                        "matched_share": len(pairs)/len(expected) if expected else 0,
                        "matched_word_count": len(offsets),
                        "unmatched_words": unmatched,
                        "filler_words": [dict(index=i, **expected[i]) for i in sorted(fillers)],
                        "within_half_second_share": within, "max_offset": maximum, "samples": samples,
                        "word_offsets": [{"index": i, "offset_seconds": offsets[i]} for i in offsets],
                        "evidence": "Finished reel re-transcribed; sync scored only on matched non-filler caption words"}
        moment = metadata["moment"]
        # Caption display-skips must not change which spoken word starts the cut.
        intended = moment.get("first_word_text")
        first_pair = (0 if heard and normalized(heard[0]["text"]) == normalized(intended) else None) if intended else pairs.get(0)
        first_start = heard[first_pair]["start"] if first_pair is not None else None
        quiet_lead = bool(frames and frames[0][1] < .006)
        first_matches = first_pair == 0 and first_start is not None and first_start <= .3
        preword_noise = first_start is not None and any(
            rms >= .006 and t+.02 <= first_start-.04 for t,rms in frames)
        alignment = moment.get("alignment", {})
        lead = moment.get("first_word_start", moment["start"])-moment["start"]
        fade = metadata.get("audio_fade_in", 0)
        continuous = (alignment.get("status") == "PASS" and
                      alignment.get("start_strategy") == "continuous_speech" and
                      abs(fade-.12) < .001 and 0 <= lead <= .081 and
                      first_matches and abs(first_start-lead) <= .1)
        speech_in_first_second = any(rms >= .006 for _,rms in opening_frames) and any(
            w["start"] < 1 and w["end"] > 0 for w in heard)
        # Energy alone cannot identify a syllable: require the intended first word as well.
        result["T6"] = {"status": "PASS" if first_matches and speech_in_first_second and
                        ((quiet_lead and not preword_noise) or continuous) else "NEEDS_REVIEW",
                        "evidence": "First-second speech and intended onset; quiet gap or aligned 80 ms preroll with 120 ms fade",
                        "energy_first_1_0": opening_frames, "speech_in_first_second": speech_in_first_second,
                        "continuous_speech_fallback": continuous, "audio_fade_in": fade,
                        "energy_first_0_3": frames, "first_word_start": first_start,
                        "first_word_matches": first_matches, "quiet_lead": quiet_lead, "preword_noise": preword_noise}
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        for item in result.values():
            item["evidence"] = str(exc)
    alignment = metadata["moment"].get("alignment")
    if alignment and alignment["status"] != "PASS" and not (
            0 < alignment.get("matched_share", 0) < .9 and alignment.get("start_strategy")):
        # Completed low-share alignment is advisory; missing/failed alignment is not.
        result["T5"]["status"] = "NEEDS_REVIEW"
        result["T5"]["alignment_reason"] = alignment["reason"]
    return result


def opening_picture(reel, metadata, evidence):
    """Compare foreground only; moving titles/progress must not mask a still speaker."""
    from PIL import Image, ImageChops, ImageStat
    pictures, paths = [], []
    for index, t in enumerate((0, .5, .96)):
        path = evidence/f"opening-{index}.png"
        run([ffmpeg(), "-nostdin", "-y", "-ss", str(t), "-i", reel, "-frames:v", "1", path])
        geo = next((s["layout"] for s in metadata.get("layout_segments", [])
                    if s["start"] <= t < s["end"]), metadata["layout"])
        with Image.open(path) as image:
            pictures.append(image.crop((geo["x"], geo["video_y"], geo["x"]+geo["width"],
                                        geo["video_y"]+geo["height"])).convert("L").resize((160, 90)))
        paths.append(str(path))
    differences = [ImageStat.Stat(ImageChops.difference(pictures[0], p)).mean[0] for p in pictures[1:]]
    return {"stills": paths, "mean_pixel_changes": differences, "still_foreground": max(differences) < 1,
            "speaker_identity": "Unverified; inspect opening stills for active-speaker lag"}


def verify_reel(video, reel, baseline, metadata, evidence, review=None, backend="faster-whisper"):
    evidence.mkdir(parents=True, exist_ok=True)
    info, length = probe(reel), duration(reel)
    stream = video_stream(info)
    geo, moment = metadata["layout"], metadata["moment"]
    frame_paths = []
    for fraction in (.25, .5, .75):
        target = evidence / f"still-{int(fraction*100)}.jpg"
        if not target.exists():
            run([ffmpeg(), "-nostdin", "-n", "-ss", str(length*fraction), "-i", reel, "-frames:v", "1", target])
        frame_paths.append(str(target))
    mechanical = {
        "T1": 20 <= length <= 59 and length < baseline["duration"] and abs(length-(moment["end"]-moment["start"])) <= .5,
        "T2": (stream["width"], stream["height"]) == (1080, 1920),
        "T3": 0 <= metadata["strip"] <= metadata["source_height"]*.08 and geo["width"] <= 1080 and geo["height"] <= 880,
        "T4": 220 <= geo["headline_y"] and geo["headline_y"]+200 <= geo["video_y"] and geo["caption_y"]+170 <= 1540,
        "T5": all(0 <= e["start"] < e["end"] <= length+.05 and 2 <= len(e["words"]) <= 5 for e in metadata["events"]),
        "T6": 0 <= moment["first_word_start"]-moment["start"] <= .301,
        "T7": geo["caption_y"] >= geo["video_y"]+geo["height"] and geo["headline_y"]+200 <= geo["video_y"],
        "T8": any(s["codec_type"] == "audio" for s in info["streams"]),
        "T9": Path(video).stat().st_size == baseline["size"] and digest(video) == baseline["sha256"],
    }
    for segment in metadata.get("layout_segments", []):
        g, box = segment["layout"], segment["crop"]
        mechanical["T3"] &= (0 <= segment["strip"] <= box["height"]*.08 and
                             0 <= box["x"] <= metadata["source_width"]-box["width"] and
                             0 <= box["y"] <= metadata["source_height"]-box["height"] and
                             g["width"] <= 1080 and g["height"] <= 880)
        mechanical["T4"] &= 220 <= g["headline_y"] and g["headline_y"]+200 <= g["video_y"] and g["caption_y"]+170 <= 1540
        mechanical["T7"] &= g["caption_y"] >= g["video_y"]+g["height"] and g["headline_y"]+200 <= g["video_y"]
    try:
        # ffmpeg exits nonzero on decode errors; -xerror makes errors fatal.
        run([ffmpeg(), "-nostdin", "-v", "error", "-xerror", "-i", reel, "-f", "null", "-"])
        mechanical["T10"] = True
    except RuntimeError:
        mechanical["T10"] = False
    machine = machine_listen(reel, metadata, evidence, backend)
    opening = opening_picture(reel, metadata, evidence)
    machine["T6"]["opening_picture"] = opening
    machine["T6"]["silent_still_opening"] = opening["still_foreground"] and not machine["T6"].get("speech_in_first_second", False)
    if machine["T6"]["silent_still_opening"]:
        machine["T6"]["status"] = "NEEDS_REVIEW"
    fingerprint = digest(reel)
    review = review if review and review.get("sha256") == fingerprint else {}
    checks = {}
    for number, label in enumerate(LABELS, 1):
        key = f"T{number}"
        status = "PASS" if mechanical[key] else "FAIL"
        detail = "Measured mechanically"
        if status == "PASS" and key in REVIEW_TESTS:
            item = review.get(key, {})
            valid = item.get("pass") is True and bool(item.get("note"))
            status = "PASS" if valid else ("FAIL" if item.get("pass") is False else "NEEDS_REVIEW")
            detail = item.get("note", "Inspect all three stills; machine checks cannot prove visual quality")
        if key in machine and mechanical[key]:
            status = machine[key]["status"]
            detail = machine[key].get("evidence", "Machine audio evidence unavailable")
            if machine[key].get("alignment_reason"):
                detail += "; " + machine[key]["alignment_reason"]
        checks[key] = {"status": status, "label": label, "evidence": detail}
    return {"file": str(reel), "sha256": fingerprint, "duration": length, "stills": frame_paths, "checks": checks,
            "alignment": moment.get("alignment"), "machine_audio": machine}


def verify_job(out):
    job = read_json(job_path(out, "job.json"))
    reviews = read_json(job_path(out, "reviews.json")) if (job_path(out, "reviews.json")).exists() else {}
    reports = []
    for key, reel in sorted(job.get("reels", {}).items(), key=lambda item: int(item[0])):
        metadata = read_json(out/reel["metadata"])
        reports.append(verify_reel(Path(job["video"]), out/reel["file"], job["baseline"], metadata,
                                   out/reel["evidence"], reviews.get(key), job.get("backend", "faster-whisper")))
    write_json(job_path(out, "tests.json"), reports)
    lines = ["# Reel checks", "", "PASS requires measured checks and explicit still inspection plus machine listening. Estimated subtitle times do not prove sync.", "",
             "| Reel | " + " | ".join(f"T{i}" for i in range(1,11)) + " |", "|---|" + "---|"*10]
    for result in reports:
        lines.append("| " + Path(result["file"]).name + " | " + " | ".join(result["checks"][f"T{i}"]["status"] for i in range(1,11)) + " |")
    for result in reports:
        lines += ["", f"## {Path(result['file']).name}", "", f"SHA-256: `{result['sha256']}`", ""]
        lines += [f"- {key} {check['label']}: {check['status']}. {check['evidence']}" for key, check in result["checks"].items()]
        timing = result.get("machine_audio", {}).get("T5", {})
        for field, label in (("filler_words", "Excluded fillers"), ("unmatched_words", "Unmatched caption words")):
            words = ", ".join(f"#{w['index']} {w['text']}" for w in timing.get(field, [])) or "none"
            lines.append(f"- {label}: {words}")
        for label, metric in (("Caption alignment", timing), ("Source alignment", result.get("alignment") or {})):
            if "matched_share" in metric:
                share = metric["matched_share"]
                lines.append(f"- {label} share: {share:.1%}")
                if share < .9:
                    words = ", ".join(f"#{w['index']} {w['text']}" for w in metric.get("unmatched_words", [])) or "none listed"
                    lines.append(f"- WARNING: {label} share below 0.90; look at the listed unmatched words: {words}.")
        lines += [f"- Still: {path}" for path in result["stills"]]
    (out/"tests.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return reports


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    reports = verify_job(args.out)
    raise SystemExit(0 if reports and all(c["status"] == "PASS" for r in reports for c in r["checks"].values()) else 2)
