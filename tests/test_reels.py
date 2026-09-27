"""Run with pytest or, offline, python -m unittest discover -s tests -v."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "reel-maker" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from common import job_path, digest, ffmpeg, read_json, run, write_json
from render import layout, groups, text_png, DEFAULT_CONFIG, cleaned
from transcribe import spread, subtitles
from make_reels import main
from verify import verify_job
from PIL import Image


class Units(unittest.TestCase):
    def test_caption_sentence_case(self):
        words = spread("oh my god! i met Alice at NASA.", 0, 9)
        self.assertEqual([w["text"] for w in cleaned(words)],
                         ["Oh", "my", "god!", "I", "met", "Alice", "at", "NASA."])

    def test_character_weight_timing(self):
        words = spread("a bbb cc", 10, 16)
        self.assertEqual([(w["start"], w["end"]) for w in words], [(10,11), (11,14), (14,16)])

    def test_safe_zones_and_portrait(self):
        for width,height in ((1920,1080),(1080,1920),(1080,1080),(640,360),(200,3000)):
            g = layout(width,height)
            self.assertLessEqual(g["height"],880)
            self.assertLessEqual(g["width"],1080)
            self.assertGreaterEqual(g["headline_y"],220)
            self.assertLessEqual(g["caption_y"]+170,1540)
            self.assertLessEqual(g["headline_y"]+200,g["video_y"])
            self.assertGreaterEqual(g["caption_y"],g["video_y"]+g["height"])
            self.assertLess(abs(g["width"]/g["height"]-width/height),.02)
        self.assertEqual(layout(1080,1920)["height"],880)

    def test_fixed_caption_height_and_no_singletons(self):
        with tempfile.TemporaryDirectory() as d:
            for n in range(2,20):
                self.assertTrue(all(2 <= len(g) <= 5 for g in groups(list(range(n)))))
            for words in (["One", "word"], ["A", "longer", "caption", "fits", "here"]):
                p = Path(d)/"caption.png"
                text_png(words,p,170,DEFAULT_CONFIG,active=0)
                with Image.open(p) as im:
                    self.assertEqual(im.size,(1080,170))
                    self.assertEqual(im.mode,"RGBA")

    def test_vtt_srt_and_loop_skip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"input.srt"
            p.write_text("1\n00:00:01,000 --> 00:00:07,000\na bbb cc\n\n2\n00:00:08,000 --> 00:00:12,000\n"+"you know "*8)
            result = subtitles(p)
            self.assertEqual(len(result["words"]),3)
            self.assertEqual(len(result["skipped"]),1)


class EndToEnd(unittest.TestCase):
    def test_two_reels(self):
        with tempfile.TemporaryDirectory(prefix="reel test space '") as temp:
            root = Path(temp)
            video = root/"recording's test.mp4"
            run([ffmpeg(),"-nostdin","-n","-f","lavfi","-i","color=c=red:s=320x180:r=25:d=90",
                 "-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=90", "-c:v","libx264","-preset","ultrafast",
                 "-c:a","aac","-shortest",video])
            original = digest(video)
            vtt = root/"recording's test.vtt"
            def stamp(n):
                return f"00:{n//60:02d}:{n%60:02d}.000"
            vtt.write_text("WEBVTT\n\n"+"\n\n".join(
                f"{stamp(t)} --> {stamp(t+5)}\nThese useful ideas help owners save time and grow steadily."
                for t in range(0,90,5)))
            out = root/"output"
            command = [sys.executable,str(SCRIPTS/"make_reels.py"),"--video",str(video),"--transcript",str(vtt),"--count","2","--out",str(out)]
            # Sine audio cannot pass speech validation; supply recognized words only
            # at that boundary, retaining real extraction/render/verification below.
            with patch("transcribe.recognize", return_value=spread(
                    "These useful ideas help owners save time and grow steadily.", 0, 5)):
                self.assertEqual(main(command[2:]), 2)
            moments = read_json(out/"moments.json")
            moments.update(offer="Synthetic fixture only",transcript_read_in_full=True)
            for i,m in enumerate(moments["candidates"]):
                m.update(first_word=i*10,last_word=i*10+39,headline="Save time with useful ideas",
                         reason="Synthetic timing and layout fixture",complete_sentences=True,
                         selected=i in (0,5),instagram_caption="Useful ideas. Comment INFO and I'll send you the details",cover_text="Useful ideas")
            write_json(out/"moments.json",moments)
            config = read_json(out/"reel-maker.config.json")
            Image.new("RGBA",(100,100),"blue").save(out/"brand.png")
            config.update(cta_text="Learn more",logo_path="brand.png")
            write_json(out/"reel-maker.config.json",config)
            rendered = subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(rendered.returncode,2,rendered.stdout+rendered.stderr)
            job = read_json(job_path(out, "job.json"))
            reports = read_json(job_path(out, "tests.json"))
            self.assertEqual(len(reports),2)
            reviews = {}
            for key,reel in job["reels"].items():
                meta = read_json(out/reel["metadata"])
                self.assertNotIn("drawtext",meta["filter_graph"])
                self.assertNotIn("subtitles=",meta["filter_graph"])
                self.assertTrue(meta["filter_graph"].rsplit("[b]",1)[1].startswith("scale="))
                samples=[]
                for fraction in (.25,.5,.75):
                    t=(meta["moment"]["end"]-meta["moment"]["start"])*fraction
                    event=next(e for e in meta["events"] if e["start"] <= t < e["end"])
                    with Image.open(out/reel["evidence"]/f"still-{int(fraction*100)}.jpg") as image:
                        self.assertEqual(image.size,(1080,1920))
                        r,g,b=image.getpixel((540,meta["layout"]["video_y"]+100))
                        self.assertGreater(r,200)
                        self.assertLess(g,30)
                        self.assertLess(b,30)
                        caption=image.crop((0,meta["layout"]["caption_y"],1080,meta["layout"]["caption_y"]+170))
                        accent=sum(1 for r,g,b in (caption.get_flattened_data() if hasattr(caption,"get_flattened_data") else caption.getdata()) if r>180 and 120<g<240 and b<150)
                        self.assertGreater(accent,100)
                        hook=image.crop((0,meta["layout"]["headline_y"],1080,meta["layout"]["headline_y"]+200))
                        self.assertGreater(sum(1 for r,g,b in (hook.get_flattened_data() if hasattr(hook,"get_flattened_data") else hook.getdata()) if min(r,g,b)>210),100)
                        for x in (1,1078):
                            self.assertGreater(image.getpixel((x,meta["layout"]["video_y"]+100))[0],200)
                    samples.append({"fraction":fraction,"offset_seconds":0,
                                    "heard":"Synthetic sine tone; scripted word schedule, no speech",
                                    "visible":" ".join(event["words"])})
                reviews[key]={"sha256":digest(out/reel["file"])}
                for test in ("T3","T4","T5","T6","T7"):
                    reviews[key][test]={"pass":True,"note":"Synthetic fixture: pixel/geometry checks and known timing; no people or spoken speech. Does not validate natural speech."}
                reviews[key]["T5"]["samples"]=samples
            self.assertEqual(digest(video),original)
            self.assertTrue((out/"contact-sheet.jpg").exists())
            self.assertTrue(any(c["status"]=="NEEDS_REVIEW" for r in reports for c in r["checks"].values()))
            write_json(job_path(out, "reviews.json"),reviews)
            verified=verify_job(out)
            self.assertTrue(all(r["checks"][key]["status"]=="PASS" for r in verified
                                for key in ("T1", "T2", "T3", "T4", "T7", "T8", "T9", "T10")))
            self.assertTrue(all(r["checks"]["T5"]["status"] != "PASS" for r in verified))
            before = read_json(job_path(out, "job.json"))["reels"]
            number = next(iter(before))
            rerendered = subprocess.run(command+["--rerender",number],capture_output=True,text=True)
            self.assertEqual(rerendered.returncode,2,rerendered.stdout+rerendered.stderr)
            after = read_json(job_path(out, "job.json"))["reels"]
            self.assertNotEqual(before[number]["metadata"],after[number]["metadata"])
            for key in before:
                if key != number:
                    self.assertEqual(before[key],after[key])
            self.assertTrue((out/before[number]["file"]).exists())
            self.assertEqual(len(list((out/"working files"/"superseded").glob("*.mp4"))), 1)
            self.assertFalse((out/"job.json").exists())
            self.assertTrue(after[number]["file"].startswith(f"Reel {number} - "))
            reviews[next(iter(reviews))]["sha256"]="stale"
            write_json(job_path(out, "reviews.json"),reviews)
            self.assertTrue(any(c["status"]=="NEEDS_REVIEW" for r in verify_job(out) for c in r["checks"].values()))


if __name__ == "__main__":
    unittest.main()
