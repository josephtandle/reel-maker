"""Cut, normalize, compose and retain reviewable per-reel intermediates."""
from __future__ import annotations
import json
import math
from pathlib import Path
import re
import shutil
import textwrap
import tempfile
from rm_env import NeedsInput, ffmpeg, run, probe, encoder_args, log, read_json, write_json, fingerprint
from rm_brand import load
from rm_moments import bounds, slug
from rm_crop import plan
from rm_graphics import assets, caption_track, contact_sheet


def loudness(path, start=None, duration=None):
    args = [ffmpeg(), "-nostdin", "-hide_banner", "-nostats"]
    if start is not None:
        args += ["-ss", str(start)]
    args += ["-i", path]
    if duration is not None:
        args += ["-t", str(duration)]
    args += ["-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]
    result = run(args)
    matches = re.findall(r'\{\s*"input_i".*?\}', result.stderr, re.S)
    if not matches:
        raise RuntimeError("ffmpeg did not return loudness measurements.")
    return json.loads(matches[-1])


def choose_audio_candidate(measurements):
    """Return the closest-to-target index, preferring peak-safe candidates."""
    safe = [i for i, m in enumerate(measurements) if float(m["input_tp"]) <= -1.0]
    def distance(i):
        integrated = float(measurements[i]["input_i"])
        return abs(integrated+14) if math.isfinite(integrated) else math.inf
    return min(safe or range(len(measurements)), key=distance)


def finalize_audio(path):
    measurement = loudness(path)
    integrated = float(measurement["input_i"])
    if math.isfinite(integrated) and abs(integrated+14) <= .5:
        return measurement
    candidates = [path]
    measurements = [measurement]
    temporary = []
    try:
        def correct(audio):
            with tempfile.NamedTemporaryFile(prefix=path.stem+"-audio-", suffix=".mp4",
                                             dir=path.parent, delete=False) as output:
                fixed = Path(output.name)
            temporary.append(fixed)
            run([ffmpeg(),"-nostdin","-hide_banner","-y","-v","error","-i",path,
                 "-map","0:v:0","-map","0:a:0","-c:v","copy","-af",audio,
                 "-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",fixed])
            measurements.append(loudness(fixed))
            candidates.append(fixed)

        fields = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        if all(math.isfinite(float(measurement[k])) for k in fields):
            audio = ("loudnorm=I=-14:TP=-1.5:LRA=11:linear=true"
                     ":measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}"
                     ":measured_thresh={input_thresh}:offset={target_offset}").format(**measurement)
            correct(audio)
        corrected_i = float(measurements[-1]["input_i"])
        if math.isfinite(integrated) and (not math.isfinite(corrected_i) or abs(corrected_i+14) > .5):
            correct(f"volume={-14-integrated}dB,alimiter=limit=0.79:level=false:asc=1,aresample=48000")
        chosen = choose_audio_candidate(measurements)
        if chosen:
            candidates[chosen].replace(path)
        measurement = measurements[chosen]
    finally:
        for candidate in temporary:
            candidate.unlink(missing_ok=True)
    integrated = float(measurement["input_i"])
    if not math.isfinite(integrated) or abs(integrated+14) > .5:
        log(f"Loudness {integrated:.2f} LUFS (target -14; peaks limited the correction)")
    return measurement


def cut(source, start, duration, work, source_info):
    log("Measuring and normalizing audio")
    if not source_info["has_audio"]:
        raise NeedsInput("Rendering requires an audio stream. Supply a video or audio file with sound.")
    measure = loudness(source, start, duration)
    write_json(work/"loudness.json", measure)
    audio = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if all(math.isfinite(float(measure[k])) for k in ("input_i","input_tp","input_lra","input_thresh","target_offset")):
        audio += ":measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:measured_thresh={input_thresh}:offset={target_offset}:linear=true".format(**measure)
    audio += f",afade=t=in:st=0:d=0.02,afade=t=out:st={max(0,duration-.15)}:d=0.15"
    clip = work / ("clip.mp4" if source_info["has_video"] else "clip.m4a")
    args = [ffmpeg(),"-nostdin","-y","-v","error","-ss",str(start),"-i",source,"-t",str(duration),"-map","0:a:0","-af",audio,"-c:a","aac","-b:a","192k","-ar","48000"]
    if source_info["has_video"]:
        args += ["-map","0:v:0","-vf","scale=w='min(1920,iw)':h='min(1920,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                 "-r",str(min(30,source_info.get("fps",30))),*encoder_args(18)]
    else:
        args += ["-vn"]
    run(args+["-movflags","+faststart",clip])
    return clip


def relative_words(all_words, moment, start, end):
    if "first_word" in moment and "last_word" in moment:
        chosen = all_words[int(moment["first_word"]):int(moment["last_word"])+1]
    else:
        chosen = [w for w in all_words if w["end"] > start and w["start"] < end]
    result = [{"text":str(w.get("display",w["text"])).strip(),"start":max(0,w["start"]-start),
               "end":min(end-start,w["end"]-start)} for w in chosen if str(w.get("display",w["text"])).strip()]
    while result and result[0]["text"].lower().strip(".,!?") in {"um","uh","er","ah"}:
        result.pop(0)
    while result and result[-1]["text"].lower().strip(".,!?") in {"um","uh","er","ah"}:
        result.pop()
    return result


def compose(clip, work, output, crop, moment, brand, words, duration, style, no_logo):
    assets(work,moment,brand,crop["layout"],no_logo)
    track, events = caption_track(words,duration,work,brand,style)
    if not events:
        raise NeedsInput("No visible caption words remain. Review transcript display fields.")
    inputs = ["-i",clip]
    graph = []
    next_input = 1
    current = "base"
    def image_input(name):
        nonlocal next_input
        idx = next_input
        next_input += 1
        inputs.extend(["-loop","1","-framerate","30","-i",work/name])
        return f"{idx}:v"
    if crop["layout"] == "audiogram":
        bg = image_input("background.png")
        graph += [f"[{bg}]setsar=1[background]",
                  f"[0:a]showwaves=s=900x240:mode=cline:rate=30:colors=0x{brand['accent'][1:]}[wave]",
                  "[background][wave]overlay=90:1000[base]"]
    elif crop["layout"] == "fill":
        segments = crop["segments"]
        box = segments[0]["crop"]
        expression = str(segments[-1]["crop"]["x"])
        for segment in reversed(segments[:-1]):
            expression = f"if(lt(t,{segment['to']}),{segment['crop']['x']},{expression})"
        sharpen = ",unsharp=5:5:0.6" if max(1080/box["w"],1920/box["h"]) > 2 else ""
        graph.append(f"[0:v]crop={box['w']}:{box['h']}:x='{expression}':y={box['y']},scale=1080:1920:flags=lanczos{sharpen},setsar=1[base]")
    else:
        box = crop["black_bars"]
        # Blur at quarter size to avoid an expensive full-resolution blur.
        filters = run([ffmpeg(),"-hide_banner","-filters"]).stdout
        blur = "boxblur=8:2" if "boxblur" in filters else "gblur=sigma=8"
        dark = "eq=brightness=-0.16" if " eq " in filters else "lutrgb=r=val*0.6:g=val*0.6:b=val*0.6"
        graph += [f"[0:v]crop={box['w']}:{box['h']}:{box['x']}:{box['y']},split=2[a][b]",
                  f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,{blur},{dark},scale=1080:1920,setsar=1[bg]",
                  "[b]scale=1080:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[fg]",
                  "[bg][fg]overlay=(W-w)/2:820-h/2[base]"]
    def overlay(stream, x, y, suffix="", fade=None):
        nonlocal current
        out = "layer" + str(len(graph))
        if fade is not None:
            faded = out+"fade"
            graph.append(f"[{stream}]format=rgba,fade=t=in:st={fade}:d=0.35:alpha=1[{faded}]")
            stream = faded
        graph.append(f"[{current}][{stream}]overlay=x='{x}':y='{y}'{suffix}[{out}]")
        current = out
    if crop["layout"] == "fill":
        overlay(image_input("scrim.png"),0,0)
    overlay(image_input("headline.png"),"-1080*max(0,1-t/0.4)",190,fade=0)
    if brand.get("handle") or brand.get("name"):
        overlay(image_input("eyebrow.png"),0,130)
    if brand.get("logo") and not no_logo:
        overlay(image_input("logo.png"),"W-w-60",80)
    if moment.get("speaker"):
        overlay(image_input("name.png"),0,1150,":enable='lt(t,4)'")
    caption_index = next_input
    next_input += 1
    # safe=0 is needed for per-file framerate directives; all entries are internal basenames.
    inputs += ["-f","concat","-safe","0","-i",track]
    overlay(f"{caption_index}:v",0,1280,":eof_action=pass")
    overlay(image_input("cta.png"),0,1490,":enable='gte(t,"+str(max(0,duration-3))+")'",fade=max(0,duration-3))
    overlay(image_input("progress.png"),f"-1080+1080*min(t/{duration},1)",1912)
    graph.append(f"[{current}]fps=30,format=yuv420p[out]")
    command = [ffmpeg(),"-nostdin","-y","-v","error","-filter_complex_threads","1",*inputs,
               "-filter_complex",";".join(graph),"-map","[out]","-map","0:a:0","-t",str(duration),
               *encoder_args(),"-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",output]
    log("Composing " + output.name)
    run(command)
    return {"events":events,"filter_graph":";".join(graph),"accent":brand["accent"],"layout":crop["layout"]}


def write_srt(words, target):
    groups, group = [], []
    for word in words:
        candidate = " ".join(w["text"] for w in group+[word])
        if group and (len(textwrap.wrap(candidate,width=42))>2 or word["start"]-group[-1]["end"]>.7):
            groups.append(group)
            group = []
        group.append(word)
        if re.search(r"[.!?]$",word["text"]):
            groups.append(group)
            group = []
    if group:
        groups.append(group)
    def stamp(t):
        ms = round(t*1000)
        return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"
    blocks = []
    for group in groups:
        lines = textwrap.wrap(" ".join(w["text"] for w in group),width=42,break_long_words=True)
        chunks = [lines[i:i+2] for i in range(0,len(lines),2)]
        start, duration = group[0]["start"], group[-1]["end"]-group[0]["start"]
        for i,chunk in enumerate(chunks):
            cue_start = start + duration*i/len(chunks)
            cue_end = start + duration*(i+1)/len(chunks)
            blocks.append(f"{len(blocks)+1}\n{stamp(cue_start)} --> {stamp(cue_end)}\n"+"\n".join(chunk))
    target.write_text("\n\n".join(blocks)+"\n",encoding="utf-8")


def archive(path, job):
    if not path.exists():
        return
    directory = Path(job)/"working"/"old"
    directory.mkdir(parents=True,exist_ok=True)
    dest, n = directory/path.name, 2
    while dest.exists():
        dest = directory/f"{path.stem} ({n}){path.suffix}"
        n += 1
    path.rename(dest)


def render(job, only=None, layout="auto", style="bold", no_logo=False, keep_temp=False):
    job = Path(job).resolve()
    data = read_json(job/"moments.json")
    transcript = read_json(job/"working"/"transcript.json")
    source = data["source"]
    if job in Path(source["path"]).resolve().parents:
        raise NeedsInput("Source must be outside the job folder. Choose a new --out folder.")
    if fingerprint(source["path"]) != {k:source[k] for k in ("size","sha256")}:
        raise NeedsInput("Source changed since transcription. Start a new job before rendering.")
    brand = load()
    selected = [m for m in data["moments"] if m.get("selected")]
    if not selected:
        raise NeedsInput("No moments selected. Set selected=true in moments.json.")
    if only is not None:
        valid_numbers = {str(i) for i in range(1, len(selected)+1)}
        if not only or not set(only).issubset(valid_numbers):
            raise NeedsInput(f"--only takes reel numbers 1..{len(selected)} as shown in report.md")
    manifest_path = job/"working"/"renders.json"
    previous = read_json(manifest_path).get("reels",[]) if manifest_path.exists() else []
    numbering = {m["id"]:i for i,m in enumerate(selected,1)}
    if only and any(numbering.get(r["id"]) != r["number"] for r in previous):
        raise NeedsInput("Selected moment order changed. Run render without --only to refresh reel numbering.")
    reels = []
    for number,moment in enumerate(selected,1):
        if only and str(number) not in only:
            old = next((r for r in previous if r["id"] == moment["id"] and r["number"] == number),None)
            if old:
                reels.append(old)
            continue
        if not 1 <= len(moment.get("headline","").split()) <= 7:
            raise NeedsInput("Headlines must contain 1–7 words. Edit moments.json.")
        start,end = bounds(moment,transcript["words"],source["duration"])
        work = job/"working"/f"reel-{number}"
        work.mkdir(parents=True,exist_ok=True)
        clip = cut(source["path"],start,end-start,work,source)
        words = relative_words(transcript["words"],moment,start,end)
        moment = dict(moment)
        headline = moment["headline"]
        spoken = " ".join(w["text"] for w in words)
        first_sentence = re.split(r'(?<=[.!?])\s+', spoken, maxsplit=1)[0]
        moment.setdefault("hook_line", first_sentence or headline)
        moment.setdefault("post_caption", headline)
        moment.setdefault("cover_text", " ".join(headline.replace("*", "").split()[:5]))
        write_json(work/"words.json",words)
        actual_layout = layout if layout != "auto" else moment.get("layout","auto")
        if actual_layout not in ("auto","fill","fit"):
            raise NeedsInput("Moment layout must be auto, fill or fit.")
        crop = plan(clip,work,actual_layout)
        custom_slug = moment.get("slug")
        name = f"Reel {number} - {slug(custom_slug if isinstance(custom_slug, str) and custom_slug else headline)}"
        temporary = work/"render-pending.mp4"
        meta = compose(clip,work,temporary,crop,moment,brand,words,end-start,style,no_logo)
        meta["final_loudness"] = finalize_audio(temporary)
        for path in job.glob(f"Reel {number} - *"):
            if path.suffix.lower() in (".mp4",".srt") and not path.stem.endswith("(premium)"):
                archive(path,job)
        output = job/(name+".mp4")
        temporary.replace(output)
        write_srt(words,job/(name+".srt"))
        reel = {"number":number,"id":moment["id"],"file":output.name,"duration":end-start,"start":start,"end":end,
                "headline":moment["headline"],"hook_line":moment["hook_line"],"post_caption":moment["post_caption"],
                "cover_text":moment["cover_text"],"work":str(work.relative_to(job)),**meta}
        write_json(work/"render.json",reel)
        reels.append(reel)
        write_json(manifest_path,{"version":2,"reels":reels + [r for r in previous if r["number"]>number]})
        if not keep_temp:
            # Only disposable generated PNGs/face samples are removed; contract files remain.
            for png in work.glob("word-*.png"):
                png.unlink()
            if (work/"faces").exists():
                shutil.rmtree(work/"faces")
    if not reels:
        raise NeedsInput("No current reels were rendered.")
    if not only:
        for old in previous:
            if old["number"] > len(selected):
                archive(job/old["file"],job)
                archive((job/old["file"]).with_suffix(".srt"),job)
    write_json(manifest_path,{"version":2,"reels":reels})
    contact_sheet(job,reels,brand)
    (job/"captions.txt").write_text("\n\n".join(
        f"{r['file']}\nDuration: {r['duration']:.2f}s\nHEADLINE: {r['headline']}\nHOOK: {r['hook_line']}\nPOST CAPTION:\n{r['post_caption']}\nCOVER TEXT: {r['cover_text']}" for r in reels)+"\n",encoding="utf-8")
    from rm_verify import verify
    return verify(job)
