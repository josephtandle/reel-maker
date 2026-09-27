"""Render a reel using Pillow text and shell-free ffmpeg argument lists."""
import math
from pathlib import Path
import platform
import re
import subprocess
import tempfile
from PIL import Image, ImageColor, ImageDraw, ImageFont
from common import duration, encoder_args, ffmpeg, probe, run, video_stream, write_json

DEFAULT_CONFIG = {"accent_color": "#FFD166", "font_path": None, "logo_path": None,
                  "cta_text": None, "bottom_trim_fraction": 0, "bottom_trim_evidence": None}


def layout(width, height):
    scale = min(1080 / width, 880 / height)
    fw, fh = max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)
    y = math.floor(220 + (890 - fh) / 2)
    return {"width": fw, "height": fh, "x": (1080-fw)//2,
            "headline_y": y, "video_y": y+230, "caption_y": y+260+fh,
            "cta_y": y+201, "progress_y": 1534}


def font(size, custom=None):
    candidates = [custom] if custom else []
    if platform.system() == "Darwin":
        candidates += ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"]
    elif platform.system() == "Windows":
        import os
        base = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        candidates += [base / "arialbd.ttf", base / "segoeuib.ttf"]
    else:
        candidates += ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        candidates += sorted(Path("/usr/share/fonts").glob("**/*Bold*.ttf"))
    if custom and not Path(custom).is_file():
        raise ValueError("NEEDS_INPUT: configured font does not exist")
    for path in candidates:
        if path and Path(path).is_file():
            return ImageFont.truetype(str(path), size, index=1 if str(path).endswith("Helvetica.ttc") else 0)
    return ImageFont.load_default(size=size)


def text_png(tokens, target, height, config, active=None, size=62, max_width=1000):
    # Fixed canvas; two balanced lines; no orphan final word.
    image = Image.new("RGBA", (1080, height))
    draw = ImageDraw.Draw(image)
    for px in range(size, 17, -2):
        f = font(px, config.get("font_path"))
        width = lambda row: draw.textlength(" ".join(tokens[i] for i in row), font=f)
        rows = [list(range(len(tokens)))]
        if width(rows[0]) > max_width and len(tokens) >= 4:
            split = min(range(2, len(tokens)-1), key=lambda n: abs(width(list(range(n)))-width(list(range(n,len(tokens))))))
            rows = [list(range(split)), list(range(split, len(tokens)))]
        line_height = px + (4 if height <= 50 else 15)
        if max((width(row) for row in rows), default=0) <= max_width-12 and len(rows)*line_height <= height:
            break
    else:
        raise ValueError("NEEDS_REVIEW: text cannot fit legibly; shorten the headline/CTA or caption words")
    y = (height-len(rows)*line_height)//2
    for row in rows:
        x = (1080-width(row)) / 2
        if max_width < 950:  # reserve room for optional logo at upper-right
            x -= 65
        for i in row:
            fill = config["accent_color"] if i == active else "white"
            draw.text((x, y), tokens[i], font=f, fill=fill, stroke_width=6 if height > 50 else 2,
                      stroke_fill="black", anchor="la")  # ascender line keeps one shared baseline per row
            x += draw.textlength(tokens[i] + " ", font=f)
        y += line_height
    image.save(target)


def cleaned(words):
    result = []
    sentence = True
    for word in words:
        text = word.get("display", word["text"]).strip()
        # An empty display is how the agent removes a doubled word or false start.
        if not text:
            continue
        # Preserve names/acronyms; ambiguous casing is curated with display.
        text = re.sub(r"\bi(?=[’' ]|\b)", "I", text)
        if sentence:
            text = text[:1].upper() + text[1:]
        sentence = text.endswith((".", "!", "?"))
        result.append({**word, "text": text})
    return result


def groups(words):
    # Partition into 2–5 words; a singleton is never silently displayed.
    if len(words) < 2:
        raise ValueError("NEEDS_REVIEW: fewer than two usable caption words")
    result, i = [], 0
    while i < len(words):
        n = min(5, len(words)-i)
        if len(words)-i-n == 1:
            n -= 1
        result.append(words[i:i+n])
        i += n
    return result


def caption_track(words, start, length, work, config):
    blank = work / "blank.png"
    Image.new("RGBA", (1080, 170)).save(blank)
    events = []
    for group in groups(cleaned(words)):
        for active, word in enumerate(group):
            s, e = max(0, word["start"]-start), min(length, word["end"]-start)
            if e <= s:
                continue
            name = f"word-{len(events):04d}.png"
            text_png([w["text"] for w in group], work/name, 170, config, active)
            events.append({"start": s, "end": e, "file": name, "words": [w["text"] for w in group], "active": active})
    lines, cursor = ["ffconcat version 1.0"], 0.0
    for event in events:
        if event["start"] > cursor + .00001:
            lines += ["file blank.png", f"duration {event['start']-cursor:.8f}"]
        lines += [f"file {event['file']}", f"duration {event['end']-event['start']:.8f}"]
        cursor = event["end"]
    if cursor < length:
        lines += ["file blank.png", f"duration {length-cursor:.8f}"]
    lines += ["file blank.png"]
    path = work / "captions.ffconcat"
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")
    return path, events


def detect_active_picture(video, width, height):
    """Union of cropdetect boxes across the cut: only remove persistent black borders."""
    result = subprocess.run([ffmpeg(), "-nostdin", "-hide_banner", "-i", str(video),
                             "-vf", "cropdetect=limit=0.094:round=2:reset=1:skip=0",
                             "-an", "-f", "null", "-"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("cropdetect failed: " + result.stderr[-2000:])
    boxes = [tuple(map(int, box)) for box in re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", result.stderr)]
    boxes = [(w,h,x,y) for w,h,x,y in boxes if w > 0 and h > 0 and x+w <= width and y+h <= height]
    if not boxes:
        return {"width": width, "height": height, "x": 0, "y": 0}
    x = min(b[2] for b in boxes)//2*2
    y = min(b[3] for b in boxes)//2*2
    right = min(width, math.ceil(max(b[2]+b[0] for b in boxes)/2)*2)
    bottom = min(height, math.ceil(max(b[3]+b[1] for b in boxes)/2)*2)
    return {"width": right-x, "height": bottom-y, "x": x, "y": y}


def union_crop(a, b):
    x, y = min(a["x"], b["x"]), min(a["y"], b["y"])
    return {"x": x, "y": y, "width": max(a["x"]+a["width"], b["x"]+b["width"])-x,
            "height": max(a["y"]+a["height"], b["y"]+b["height"])-y}


def group_layout_samples(samples, length, tolerance=4):
    """Union small detector jitter; absorb short flashes without removing picture."""
    segments = []
    for t, crop in samples:
        if segments and all(abs(crop[k]-segments[-1]["crop"][k]) <= tolerance for k in crop):
            segments[-1]["crop"] = union_crop(segments[-1]["crop"], crop)
        else:
            if segments:
                segments[-1]["end"] = t
            segments.append({"start": t, "end": length, "crop": crop})
    while len(segments) > 1:
        short = next((i for i,s in enumerate(segments) if s["end"]-s["start"] < 1), None)
        if short is None:
            break
        # Choose the neighbour requiring least extra retained area.
        neighbours = [i for i in (short-1, short+1) if 0 <= i < len(segments)]
        def area(i):
            box = union_crop(segments[short]["crop"], segments[i]["crop"])
            return box["width"]*box["height"]
        neighbour = min(neighbours, key=area)
        target, source = segments[neighbour], segments[short]
        target.update(start=min(target["start"], source["start"]), end=max(target["end"], source["end"]),
                      crop=union_crop(target["crop"], source["crop"]))
        segments.pop(short)
    return segments


def detect_layout_segments(video, width, height, length):
    result = subprocess.run([ffmpeg(), "-nostdin", "-hide_banner", "-i", str(video), "-vf",
                             "fps=2:start_time=0,cropdetect=limit=0.094:round=2:reset=1:skip=0",
                             "-an", "-f", "null", "-"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("cropdetect failed: " + result.stderr[-2000:])
    full = {"width": width, "height": height, "x": 0, "y": 0}
    samples = []
    for t, w, h, x, y in re.findall(r"t:([\d.]+).*?crop=(-?\d+):(-?\d+):(-?\d+):(-?\d+)", result.stderr):
        w, h, x, y = map(int, (w, h, x, y))
        crop = {"width": w, "height": h, "x": x, "y": y}
        if not (0 < w <= width and 0 < h <= height and 0 <= x <= width-w and 0 <= y <= height-h):
            crop = dict(full)
        if float(t) < length:
            samples.append((float(t), crop))
    if not samples:
        samples = [(0, full)]
    samples[0] = (0, samples[0][1])
    segments = group_layout_samples(samples, length)
    widen_vertical_crops(video, width, height, segments)
    return segments


def widen_vertical_crops(video, width, height, segments):
    """Only retain vertical cuts supported by full-width pure black in 90% of samples.

    Decode RGB so both limited- and full-range black map to zero. Any nonzero
    pixel counts as picture. Stream through a temporary file to bound memory;
    missing/failed evidence conservatively restores the entire vertical extent.
    """
    edges = [[] for _ in segments]
    with tempfile.TemporaryFile() as raw:
        result = subprocess.run([ffmpeg(), "-nostdin", "-v", "error", "-i", str(video),
                                 "-vf", "fps=2:start_time=0,format=rgb24", "-an",
                                 "-f", "rawvideo", "-"], stdout=raw, stderr=subprocess.PIPE)
        if result.returncode == 0:
            raw.seek(0)
            index, size = 0, width*height*3
            while True:
                frame = raw.read(size)
                if len(frame) != size:
                    break
                box = Image.frombytes("RGB", (width, height), frame).getbbox()
                # A wholly black frame is ambiguous, not proof of any border.
                top, bottom = (box[1], height-box[3]) if box else (0, 0)
                for i, segment in enumerate(segments):
                    if segment["start"] <= index/2 < segment["end"]:
                        edges[i].append((top, bottom))
                        break
                index += 1
    for segment, observed in zip(segments, edges):
        top = bottom = 0
        if observed:
            rank = len(observed)-math.ceil(.9*len(observed))
            top = sorted(pair[0] for pair in observed)[rank]//2*2
            bottom = sorted(pair[1] for pair in observed)[rank]//2*2
        crop = segment["crop"]
        y = min(crop["y"], top)
        end = max(crop["y"]+crop["height"], height-bottom)
        crop.update(y=y, height=end-y)


def picture_graph(segments, trim, sar, blur, darken):
    """Render each cropped picture and its own blurred background, then concatenate."""
    graph = []
    many = len(segments) > 1
    if many:
        graph.append(f"[0:v]split={len(segments)}"+"".join(f"[source{i}]" for i in range(len(segments))))
    for i, segment in enumerate(segments):
        box = segment["crop"]
        strip = int(box["height"]*trim)//2*2
        geo = layout(round(box["width"]*sar), box["height"]-strip)
        segment.update(layout=geo, strip=strip)
        source = f"source{i}" if many else "0:v"
        a, b, bg, fg = (f"{name}{i}" if many else name for name in ("a", "b", "bg", "fg"))
        prefix = f"trim=start={segment['start']}:end={segment['end']},setpts=PTS-STARTPTS," if many else ""
        graph += [f"[{source}]{prefix}crop={box['width']}:{box['height']-strip}:{box['x']}:{box['y']},split=2[{a}][{b}]",
                  f"[{a}]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,{blur}{darken},setsar=1[{bg}]",
                  f"[{b}]scale={geo['width']}:{geo['height']},setsar=1[{fg}]",
                  f"[{bg}][{fg}]overlay={geo['x']}:{geo['video_y']}[{f'piece{i}' if many else 'v0'}]"]
    if many:
        graph.append("".join(f"[piece{i}]" for i in range(len(segments)))+f"concat=n={len(segments)}:v=1:a=0[v0]")
    return graph


def layout_position(segments, key):
    expression = str(segments[-1]["layout"][key])
    for segment in reversed(segments[:-1]):
        expression = f"if(lt(t,{segment['end']}),{segment['layout'][key]},{expression})"
    return expression


def render(video, moment, words, config, output, work):
    work.mkdir(parents=True, exist_ok=False)
    start, end = float(moment["start"]), float(moment["end"])
    length = end-start
    if not 20 <= length <= 59:
        raise ValueError("NEEDS_REVIEW: reel length must be 20–59 seconds")
    ImageColor.getrgb(config["accent_color"])
    selected = words[moment["first_word"]:moment["last_word"]+1]
    info = probe(video)
    stream = video_stream(info)
    if not any(s["codec_type"] == "audio" for s in info["streams"]):
        raise ValueError("NEEDS_INPUT: original has no audio; never fabricate sound")
    cut = work / "cut.mp4"
    enc = encoder_args()
    cut_command = [ffmpeg(), "-nostdin", "-n", "-ss", str(start), "-i", video, "-t", str(length),
                   "-map", "0:v:0", "-map", "0:a:0", *enc, "-c:a", "aac", cut]
    run(cut_command)
    if abs(duration(cut)-length) > .5:
        raise ValueError("Cut duration differs by more than 0.5 seconds")
    stream = video_stream(probe(cut))  # rotation metadata has now been applied
    width, height = int(stream["width"]), int(stream["height"])
    segments = detect_layout_segments(cut, width, height, length)
    active = segments[0]["crop"]
    pixel_aspect = 1
    sar = stream.get("sample_aspect_ratio", "1:1")
    if sar not in ("1:1", "N/A", "0:1"):
        a, b = map(int, sar.split(":"))
        pixel_aspect = a/b
    trim = float(config.get("bottom_trim_fraction", 0))
    if not 0 <= trim <= .08 or (trim and not config.get("bottom_trim_evidence")):
        raise ValueError("NEEDS_REVIEW: bottom trim requires stamp evidence and must be <=8%")
    title = moment["headline"]
    if not 1 <= len(title.split()) < 8:
        raise ValueError("NEEDS_REVIEW: headline must have 1–7 words")
    text_png(title.split(), work/"headline.png", 200, config, size=76,
             max_width=840 if config.get("logo_path") else 1000)
    track, events = caption_track(selected, start, length, work, config)
    Image.new("RGBA", (1080, 6), config["accent_color"]).save(work/"progress.png")
    cta = config.get("cta_text")
    if cta:
        text_png(cta.split(), work/"cta.png", 28, config, size=22)
    inputs = ["-i", cut, "-loop", "1", "-i", work/"headline.png", "-f", "concat", "-safe", "1", "-i", track,
              "-loop", "1", "-i", work/"progress.png"]
    filters = run([ffmpeg(), "-hide_banner", "-filters"])
    blur = "boxblur=30:5" if "boxblur" in filters else "gblur=sigma=30"
    darken = ",eq=brightness=-0.12" if " eq " in filters else ",lutrgb=r=val*0.88:g=val*0.88:b=val*0.88"
    graph = picture_graph(segments, trim, pixel_aspect, blur, darken)
    geo, strip = segments[0]["layout"], segments[0]["strip"]
    graph += [f"[v0][1:v]overlay=x='-1080*max(0,1-t/0.4)':y='{layout_position(segments, 'headline_y')}'[v1]",
             f"[v1][2:v]overlay=0:'{layout_position(segments, 'caption_y')}':eof_action=pass[v2]",
             f"[v2][3:v]overlay=x='-1080+1080*min(t/{length},1)':y=1534[v3]"]
    current, index = "v3", 4
    if cta:
        inputs += ["-loop", "1", "-i", work/"cta.png"]
        graph.append(f"[{current}][{index}:v]overlay=0:'{layout_position(segments, 'cta_y')}':enable='gte(t,{length-3})'[vcta]")
        current, index = "vcta", index+1
    if config.get("logo_path"):
        with Image.open(config["logo_path"]) as logo:
            logo = logo.convert("RGBA")
            logo.thumbnail((80, 80))
            logo.save(work/"logo.png")
        inputs += ["-loop", "1", "-i", work/"logo.png"]
        graph.append(f"[{current}][{index}:v]overlay=970:'{layout_position(segments, 'headline_y')}'[vlogo]")
        current = "vlogo"
    graph.append(f"[{current}]fps=25,format=yuv420p[v]")
    fade = float(moment.get("audio_fade_in", 0))
    audio_filters = ["-af", f"afade=t=in:st=0:d={fade}"] if fade else []
    command = [ffmpeg(), "-nostdin", "-n", "-filter_complex_threads", "1", *inputs,
               "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "0:a:0", "-t", str(length),
               *enc, *audio_filters, "-c:a", "aac", "-movflags", "+faststart", output]
    run(command)
    if abs(duration(output)-length) > .5:
        raise ValueError("Rendered duration differs by more than 0.5 seconds")
    metadata = {"layout": geo, "layout_segments": segments, "audio_fade_in": fade,
                "source_width": width, "source_height": height, "strip": strip,
                "active_picture": active, "events": events, "moment": moment, "filter_graph": ";".join(graph),
                "cut_command": [str(x) for x in cut_command], "render_command": [str(x) for x in command]}
    write_json(work/"render.json", metadata)
    return metadata


if __name__ == "__main__":
    import argparse
    from common import read_json
    parser = argparse.ArgumentParser(description="Render one word-aligned reel; use make_reels.py for a complete job")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--words", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--headline", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    words = read_json(args.words)["words"]
    indexes = [i for i,w in enumerate(words) if w["start"] >= args.start-.001 and w["end"] <= args.end+.001]
    if not indexes or abs(words[indexes[0]]["start"]-args.start) > .001:
        parser.error("start must equal the intended first word timestamp")
    if args.end-words[indexes[-1]]["end"] > .401:
        parser.error("end must be within 0.4 seconds of the final word")
    config = {**DEFAULT_CONFIG, **read_json(args.config)}
    for field in ("font_path", "logo_path"):
        if config.get(field) and not Path(config[field]).is_absolute():
            config[field] = str(args.config.parent/config[field])
    render(args.video, {"start": args.start, "end": args.end, "first_word_start": args.start,
           "first_word": indexes[0], "last_word": indexes[-1], "headline": args.headline},
           words, config, args.out, args.work)
