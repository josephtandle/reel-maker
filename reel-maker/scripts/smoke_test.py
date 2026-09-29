#!/usr/bin/env python3
"""Exercise the public CLI with synthetic video, imported words and audio only."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from rm_env import ffmpeg, fingerprint, probe, read_json, write_json, run, log, encoder, encoder_args


def main(keep=False):
    started = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix="reel-maker-smoke-"))
    outcomes = []
    try:
        video = root/"sample 'quoted' ü video.mp4"
        audio = root/"audio sample.m4a"
        log("Building 90-second synthetic media")
        sound = "0.055*sin(2*PI*440*t)*if(lt(mod(t,0.35),0.24),1,0.02)"
        encoding = ["-c:v","libx264","-preset","ultrafast","-crf","32","-pix_fmt","yuv420p"] if encoder()=="libx264" else encoder_args(28)
        run([ffmpeg(),"-nostdin","-y","-v","error","-f","lavfi","-i",
             "testsrc2=size=1280x720:rate=30","-f","lavfi","-i",f"aevalsrc='{sound}':s=48000",
             "-t","90","-filter_complex","color=yellow:s=220x160:r=30[box];[0:v][box]overlay=x='mod(t*100,1060)':y='400+100*sin(t)'[sample]",
             "-map","[sample]","-map","1:a:0",*encoding,"-c:a","aac","-b:a","128k",video])
        run([ffmpeg(),"-nostdin","-y","-v","error","-i",video,"-vn","-c:a","copy",audio])
        # Unique sentences avoid the deliberate repeated-hallucination filter.
        templates = [
            "Here's the mistake most people make with pricing.",
            "Why do you spend 20 hours doing this every week?",
            "You can stop guessing and measure the results in 3 days.",
            "The secret is simple and your clients will see the difference.",
            "Most people miss this because they never check the numbers.",
            "The answer finally became clear when we saved 12 hours.",
        ]
        words, cursor, index = [], .2, 0
        while cursor < 88:
            text = templates[index%len(templates)] + f" Experiment {index+1} saved {index+3} hours for clients."
            segment = []
            for token in text.split():
                if cursor+.3 >= 89:
                    break
                segment.append({"word":token,"start":round(cursor,3),"end":round(cursor+.29,3)})
                cursor += .35
            if segment:
                words.append({"start":segment[0]["start"],"end":segment[-1]["end"],
                              "text":" ".join(w["word"] for w in segment),"words":segment})
            cursor += .12
            index += 1
        fixture = root/"fixture.json"
        write_json(fixture,{"language":"en","segments":words})
        before = {str(p):fingerprint(p) for p in (video,audio)}
        env = dict(os.environ,REEL_MAKER_HOME=str(root/"home"),REEL_MAKER_NO_REEXEC="1",
                   PYTHONDONTWRITEBYTECODE="1",REEL_MAKER_NO_FACES="1")
        write_json(root/"home"/"brand.json", {"handle":"@CREATOR"})
        cli = Path(__file__).with_name("reelmaker.py")
        for label,source,count,extra in (("video-auto",video,2,[]),("video-fit",video,1,["--layout","fit","--style","clean"]),
                                         ("video-fill",video,1,["--layout","fill"]),("audio-only",audio,1,[])):
            job = root/label
            log("Smoke: " + label)
            result = subprocess.run([sys.executable,str(cli),"make",str(source),"--out",str(job),
                                     "--transcript",str(fixture),"--count",str(count),"--auto",*extra],
                                    env=env,capture_output=True,text=True)
            if result.returncode:
                raise AssertionError(label+" CLI failed:\n"+result.stdout+"\n"+result.stderr)
            for name in ("captions.txt","contact-sheet.jpg","moments.json","report.json"):
                assert (job/name).is_file(), name
            mp4s = list(job.glob("Reel *.mp4"))
            assert len(mp4s)==count, (label,len(mp4s),count)
            report = read_json(job/"report.json")
            assert report["status"]=="PASS",report
            manifest = read_json(job/"working"/"renders.json")
            for reel in manifest["reels"]:
                path = job/reel["file"]
                meta = probe(path)
                assert (meta["width"],meta["height"])==(1080,1920)
                assert 20<=meta["duration"]<=60
                assert abs(meta["duration"]-reel["duration"])<.5
                assert meta["has_audio"]
                assert abs(float(reel["final_loudness"]["input_i"])+14)<=.5
                if label == "video-fill":
                    assert "flags=lanczos,unsharp=5:5:0.6" in reel["filter_graph"]
                    assert read_json(job/reel["work"]/"crop.json")["segments"][0]["crop"]["h"] == 720
                assert path.with_suffix(".srt").is_file()
            assert fingerprint(source)==before[str(source)]
            outcomes.append((label,"PASS",str(count)+" reels; V1–V7 passed"))
        outcomes.append(("source integrity","PASS","Both media files unchanged"))
        elapsed = time.monotonic()-started
        outcomes.append(("runtime","PASS" if elapsed<180 else "WARN",f"{elapsed:.1f}s (target <180s)"))
        print("\nCheck | Result | Detail")
        for row in outcomes:
            print(" | ".join(row))
        log("Smoke test PASS")
        return 0
    except Exception as exc:
        print("smoke | FAIL | " + str(exc))
        log("Preserved failing job at " + str(root))
        keep = True
        return 1
    finally:
        if keep:
            log("Smoke artifacts: " + str(root))
        else:
            shutil.rmtree(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep",action="store_true")
    raise SystemExit(main(parser.parse_args().keep))
