"""Observable output checks with machine-readable and plain-English reports."""
from __future__ import annotations
import math
from pathlib import Path
from rm_env import ffmpeg, run, probe, fingerprint, read_json, write_json, log


def frame(path, t, target):
    run([ffmpeg(),"-nostdin","-y","-v","error","-ss",str(max(0,t)),"-i",path,"-frames:v","1",target])
    from PIL import Image
    with Image.open(target) as image:
        return image.convert("RGB")


def accent_pixels(image, accent):
    from PIL import ImageColor
    color = ImageColor.getrgb(accent)
    return sum(all(abs(p[i]-color[i]) <= 40 for i in range(3)) for p in image.crop((0,1280,1080,1500)).getdata())


def verify(job):
    from PIL import Image, ImageChops
    from rm_render import loudness
    job = Path(job)
    data = read_json(job/"moments.json")
    manifest = read_json(job/"working"/"renders.json")
    source = data["source"]
    source_ok = Path(source["path"]).is_file() and fingerprint(source["path"]) == {k:source[k] for k in ("size","sha256")}
    rows = []
    def check(reel, code, passed, detail, warning=False):
        rows.append({"reel":reel,"check":code,"status":"WARN" if warning else "PASS" if passed else "FAIL","detail":detail})
    if not manifest["reels"]:
        check("job","V0",False,"No rendered reels found")
    for reel in manifest["reels"]:
        name, path = reel["file"], job/reel["file"]
        log("Checking " + name)
        try:
            info = probe(path)
            duration = info["duration"]
            valid = data.get("min",20)-1 <= duration <= data.get("max",60)+1 and abs(duration-reel["duration"]) <= .5
            check(name,"V1",valid,f"Duration {duration:.2f}s; planned {reel['duration']:.2f}s")
            check(name,"V2",info["width"] == 1080 and info["height"] == 1920,f"{info['width']} × {info['height']}")
            check(name,"V3",info["has_audio"],"Audio stream present" if info["has_audio"] else "Missing audio")
            measure = loudness(path) if info["has_audio"] else {"input_i":"-inf"}
            integrated = float(measure["input_i"])
            check(name,"V4",math.isfinite(integrated) and abs(integrated+14)<=1.0,
                  f"Integrated loudness {integrated:.2f} LUFS",warning=info["has_audio"] and
                  (not math.isfinite(integrated) or 1.0 < abs(integrated+14) <= 2.0))
            work = job/reel["work"]
            events = reel.get("events",[])
            event = next((e for e in events if e["start"] >= .6 and e["end"]-e["start"] >= .1),events[0] if events else None)
            if event:
                t = (event["start"]+event["end"])/2
                image = frame(path,t,work/"verify-output.png")
                pixels = accent_pixels(image,reel["accent"])
                check(name,"V5 captions",pixels>150,f"{pixels} accent pixels in the caption band")
                # Text-specific evidence, plus comparison with the pre-overlay clip.
                with Image.open(work/"headline.png") as title:
                    alpha = title.convert("RGBA").getchannel("A")
                    title_pixels = sum(v>200 for v in alpha.getdata())
                band = image.crop((0,190,1080,500))
                clip = work/"clip.mp4"
                if clip.exists():
                    baseline = frame(clip,t,work/"verify-clip.png").resize((1080,1920)).crop((0,190,1080,500))
                else:
                    with Image.open(work/"background.png") as bg:
                        baseline = bg.convert("RGB").crop((0,190,1080,500))
                changed = ImageChops.difference(band,baseline).getbbox() is not None
                # White text pixels should exist at the expected opaque glyph positions.
                mask = alpha.point(lambda p: 255 if p>240 else 0)
                opaque = [(pixel,m) for pixel,m in zip(band.getdata(),mask.getdata()) if m]
                bright = sum(min(pixel)>155 for pixel,_ in opaque)
                check(name,"V5 headline",changed and title_pixels>150 and bright>100,
                      f"Headline differs from clip; {bright} bright glyph pixels")
            else:
                check(name,"V5 captions",False,"No timed caption events")
            decoded = run([ffmpeg(),"-nostdin","-v","error","-i",path,"-f","null","-"],check=False)
            check(name,"V6",decoded.returncode == 0 and not decoded.stderr.strip(),
                  "Complete decode succeeded" if not decoded.stderr.strip() else decoded.stderr[-500:])
            check(name,"V7",source_ok,"Source size and first-64-MB-plus-size hash unchanged" if source_ok else "Source file changed or missing")
        except (OSError,ValueError,RuntimeError) as exc:
            check(name,"V0",False,str(exc))
    status = "FAIL" if any(r["status"]=="FAIL" for r in rows) else "PASS"
    report = {"version":2,"status":status,"checks":rows,"files":[r["file"] for r in manifest["reels"]]}
    write_json(job/"report.json",report)
    lines = ["# Reel verification", "", "Overall: " + status, "", "| Reel | Check | Status | Detail |", "|---|---|---|---|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row[k]).replace("|","/").replace("\n"," ") for k in ("reel","check","status","detail")) + " |")
    (job/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    log("Verification " + status)
    return report

