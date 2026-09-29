"""Conservative black-bar detection and stable face-aware shot crops."""
from __future__ import annotations
import math
import os
import re
import statistics
from pathlib import Path
from rm_env import available, ffmpeg, run, write_json, probe, log


def face_classifiers():
    import cv2
    directory = Path(cv2.data.haarcascades)
    classifiers = []
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml"):
        path = directory/name
        if not path.is_file():
            raise RuntimeError("Missing face cascade")
        classifier = cv2.CascadeClassifier(str(path))
        if classifier.empty():
            raise RuntimeError("Invalid face cascade")
        classifiers.append(classifier)
    return classifiers


def plan(clip, work, layout="auto"):
    info = probe(clip)
    w, h, duration = info["width"], info["height"], info["duration"]
    if not info["has_video"]:
        result = {"source_w": 0, "source_h": 0, "layout": "audiogram", "faces_found": 0, "samples": 0, "segments": [], "faces": [], "black_bars": {"x": 0, "y": 0, "w": 0, "h": 0}}
        write_json(Path(work)/"crop.json", result)
        return result
    detected = run([ffmpeg(), "-nostdin", "-hide_banner", "-i", clip, "-vf", "fps=2,cropdetect=limit=0.06:round=2:reset=1:skip=0", "-an", "-f", "null", "-"], check=False)
    boxes = [tuple(map(int, b)) for b in re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", detected.stderr)]
    boxes = [(bw,bh,x,y) for bw,bh,x,y in boxes if bw > w*.35 and bh > h*.35 and x+bw <= w and y+bh <= h]
    active = {"x": 0, "y": 0, "w": w, "h": h}
    if len(boxes) >= max(2, duration):
        x, y = min(b[2] for b in boxes), min(b[3] for b in boxes)
        active = {"x": x, "y": y, "w": max(b[0]+b[2] for b in boxes)-x, "h": max(b[1]+b[3] for b in boxes)-y}
    faces, sample_count, fits = [], math.ceil(duration*2), 0
    crop_width = min(active["w"], int(active["h"]*9/16)//2*2)
    if os.environ.get("REEL_MAKER_NO_FACES") != "1":
        try:
            import cv2
            classifiers = face_classifiers()
            frames = Path(work)/"faces"
            frames.mkdir(exist_ok=True)
            run([ffmpeg(), "-nostdin", "-y", "-v", "error", "-i", clip, "-vf", "fps=2,scale=640:-2", frames/"frame-%05d.jpg"])
            for i, file in enumerate(sorted(frames.glob("frame-*.jpg"))):
                frame = cv2.imread(str(file))
                if frame is None:
                    continue
                gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                found = []
                for classifier in classifiers:
                    if classifier.empty():
                        continue
                    found = classifier.detectMultiScale(gray, 1.1, 4, minSize=(25, 25))
                    if len(found):
                        break
                if len(found):
                    scale = w/frame.shape[1]
                    x,y,fw,fh = max(found, key=lambda b: b[2]*b[3])
                    faces.append({"t": i*.5, "x": int(x*scale), "y": int(y*scale), "w": int(fw*scale), "h": int(fh*scale)})
                    extent = (max(b[0]+b[2] for b in found)-min(b[0] for b in found))*scale
                    fits += len(found) == 1 or extent <= crop_width
        except Exception:
            log("Warning: face detection unavailable; using centered crop (re-run setup --yes)")
            faces, fits = [], 0
    if layout == "auto":
        layout = "fill" if active["w"]/active["h"] <= .7 or (len(faces)/max(sample_count,1) >= .4 and fits >= len(faces)*.6) else "fit"
    if active["w"]/active["h"] < 9/16:
        layout = "fit"
    # Require a new center to persist for 1.5 seconds; no tracking jitter.
    shots, begin = [], 0
    for i in range(1, len(faces)-2):
        old = faces[i-1]["x"] + faces[i-1]["w"]/2
        center = faces[i]["x"] + faces[i]["w"]/2
        upcoming = faces[i:i+4]
        stable = len(upcoming) == 4 and upcoming[-1]["t"]-upcoming[0]["t"] <= 1.6 and all(abs(f["x"]+f["w"]/2-center) < .2*crop_width for f in upcoming)
        if abs(center-old) > .35*crop_width and stable and faces[i]["t"]-(faces[begin]["t"] if begin else 0) >= 1.5 and duration-faces[i]["t"] >= 1.5:
            shots.append((0 if not shots else faces[begin]["t"], faces[i]["t"], faces[begin:i]))
            begin = i
    shots.append((faces[begin]["t"] if shots else 0, duration, faces[begin:]))
    segments = []
    for start, end, samples in shots:
        center = statistics.median(f["x"]+f["w"]/2 for f in samples) if samples else active["x"]+active["w"]/2
        x = max(active["x"], min(active["x"]+active["w"]-crop_width, int(center-crop_width/2)//2*2))
        segments.append({"from": start, "to": end, "crop": {"x": x, "y": active["y"], "w": crop_width, "h": active["h"]}})
    result = {"source_w": w, "source_h": h, "layout": layout, "faces_found": len(faces), "samples": sample_count,
              "segments": segments, "faces": faces, "black_bars": active}
    write_json(Path(work)/"crop.json", result)
    return result
