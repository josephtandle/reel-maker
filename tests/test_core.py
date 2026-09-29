"""Fast regression checks for offline operation and editorial boundaries."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"reel-maker"/"scripts"))
import rm_env
import rm_moments
import rm_transcribe
import reelmaker


class CoreTests(unittest.TestCase):
    def test_unpunctuated_sentences_are_bounded_and_lossless(self):
        words = [{"text": "word"+str(i), "start": i*.5, "end": i*.5+.3} for i in range(100)]
        words[22]["start"] += .19
        groups = rm_transcribe.sentences(words)
        self.assertEqual(groups[0]["last_word"], 21)
        self.assertTrue(all(g["last_word"]-g["first_word"]+1 <= 35 for g in groups))
        self.assertEqual(" ".join(g["text"] for g in groups), " ".join(w["text"] for w in words))

    def test_sentence_hard_cap_uses_largest_gap(self):
        words = [{"text": str(i), "start": i*.3, "end": i*.3+.2} for i in range(36)]
        words[12]["start"] += .09
        groups = rm_transcribe.sentences(words)
        self.assertEqual(groups[0]["last_word"], 11)
        self.assertEqual(groups[-1]["last_word"], 35)

    def test_auto_headlines_end_cleanly_and_mark_one_word(self):
        for hook in ("Well, you saved 12 hours because the process was wrong.",
                     "The reason why we do this is", "You can stop guessing and measure the results in 3 days."):
            title, cover = rm_moments.auto_headline(hook)
            self.assertEqual(title.count("*"), 2)
            self.assertLessEqual(len(title.split()), 7)
            self.assertNotIn(title.replace("*", "").split()[-1].lower(), rm_moments.STOPWORDS)
            self.assertLessEqual(len(cover.split()), 5)
            self.assertNotIn("*", cover)
        self.assertIn("*12*", rm_moments.auto_headline("You saved 12 hours because it works")[0])
        self.assertEqual(rm_moments.slug("Save *12* hours"), "save-12-hours")

    def test_find_leaves_slug_automatic(self):
        words = [{"text": t, "start": i, "end": i+.8}
                 for i, t in enumerate("You saved 12 hours. Your clients finally saw results.".split())]
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            rm_env.write_json(job/"working"/"transcript.json", {"words": words})
            rm_env.write_json(job/"working"/"source.json", {"duration": 10})
            with patch("rm_moments.load", return_value={}), patch("rm_moments.cta", return_value="Follow"):
                result = rm_moments.find(job, count=1, minimum=2, maximum=10)
            self.assertTrue(result["moments"])
            self.assertTrue(all(m["slug"] == "" for m in result["moments"]))

    def test_render_names_and_missing_editorial_fields(self):
        import rm_render
        headline = "You're making your website *work* now"
        cases = [({}, "youre-making-your-website-work-now"),
                 ({"slug": ""}, "youre-making-your-website-work-now"),
                 ({"slug": 42}, "youre-making-your-website-work-now"),
                 ({"slug": "You're *Custom*"}, "youre-custom")]
        for extra, expected in cases:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root/"source.mp4"
                source.write_bytes(b"source")
                job = root/"job"
                moment = {"id": 1, "selected": True, "headline": headline,
                          "start": 0, "end": 4, **extra}
                words = [{"text": t, "start": i*.5, "end": i*.5+.4}
                         for i, t in enumerate("Make it work! Then measure results.".split())]
                rm_env.write_json(job/"moments.json", {"source": {"path": str(source),
                    "duration": 4, **rm_env.fingerprint(source)}, "moments": [moment]})
                rm_env.write_json(job/"working"/"transcript.json", {"words": words})
                def compose(clip, work, output, crop, edited, *args):
                    self.assertEqual(edited["hook_line"], "Make it work!")
                    self.assertEqual(edited["post_caption"], headline)
                    self.assertEqual(edited["cover_text"], "You're making your website work")
                    output.write_bytes(b"render")
                    return {}
                with patch("rm_render.load", return_value={}), \
                     patch("rm_render.cut", return_value=source), \
                     patch("rm_render.plan", return_value={}), \
                     patch("rm_render.compose", side_effect=compose), \
                     patch("rm_render.finalize_audio", return_value={}), \
                     patch("rm_render.contact_sheet"), patch("rm_verify.verify", return_value={}):
                    rm_render.render(job)
                reel = rm_env.read_json(job/"working"/"renders.json")["reels"][0]
                self.assertEqual(reel["file"], "Reel 1 - " + expected + ".mp4")
                self.assertTrue((job/reel["file"]).is_file())
                self.assertIn("Make it work!", (job/"captions.txt").read_text())

    def test_premium_uses_standard_stem_or_current_slug(self):
        import premium
        cases = [
            ({"slug": "stale"}, {"reels": [
                {"number": 2, "file": "Reel 2 - wrong.mp4"},
                {"number": 1, "file": "Reel 1 - edited standard.mp4"}]}, "edited standard"),
            ({}, None, "youre-making-it-work"),
            ({"slug": ""}, {"reels": [{"number": 2, "file": "wrong.mp4"}]}, "youre-making-it-work"),
            ({"slug": 42}, None, "youre-making-it-work"),
            ({"slug": "You’re *Custom*"}, None, "youre-custom"),
        ]
        for extra, manifest, expected in cases:
            with self.subTest(extra=extra, manifest=manifest), tempfile.TemporaryDirectory() as tmp:
                job = Path(tmp)
                work = job/"working"/"reel-1"
                work.mkdir(parents=True)
                (work/"clip.mp4").write_bytes(b"clip")
                rm_env.write_json(work/"crop.json", {"source_w": 1280, "source_h": 720})
                if manifest is not None:
                    rm_env.write_json(job/"working"/"renders.json", manifest)
                def encode(command, **kwargs):
                    Path(command[6]).write_bytes(b"premium")
                with patch("premium.duration", return_value=4), \
                     patch("premium.run", side_effect=encode), \
                     patch("premium.normalize_audio", side_effect=lambda path, ffmpeg: path):
                    output = premium.render_reel(1, {"headline": "You're making it *work*", **extra},
                        job, {}, job, argparse.Namespace(eyebrow=None, concurrency=1), "npx", "ffmpeg")
                self.assertEqual(Path(output).name, "Reel 1 - " + expected + " (premium).mp4")
                self.assertEqual(Path(output).read_bytes(), b"premium")

    def test_broken_face_detection_falls_back_once(self):
        import rm_crop
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            with patch("rm_crop.probe", return_value={"width":1280,"height":720,"duration":2,"has_video":True}), \
                 patch("rm_crop.run", return_value=SimpleNamespace(stderr="")), \
                 patch("rm_crop.ffmpeg", return_value="ffmpeg"), \
                 patch.dict(sys.modules, {"cv2": SimpleNamespace()}), \
                 patch.dict(os.environ, {"REEL_MAKER_NO_FACES":"0"}), \
                 patch("rm_crop.log") as warning:
                crop = rm_crop.plan("clip.mp4", tmp, "fill")
            self.assertEqual(crop["faces_found"], 0)
            self.assertEqual(crop["segments"][0]["crop"]["x"], 438)
            warning.assert_called_once()

    def test_caption_pages_and_visible_margins(self):
        from rm_graphics import caption_track
        from PIL import Image
        words = [{"text":t,"start":i*.4,"end":i*.4+.3} for i,t in enumerate("FUNCTION OF YOUR reason why this".split())]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, events = caption_track(words, 3, root, {"accent":"#ffcc00"}, "bold")
            self.assertEqual(len(events), 6)
            for event in events:
                with Image.open(root/event["file"]) as image:
                    box = image.getbbox()
                    self.assertGreaterEqual(box[0], 90)
                    self.assertLessEqual(box[2], 990)
                    self.assertEqual(image.size, (1080,220))

    def test_audio_postcheck_copies_video_and_remeasures(self):
        import rm_render
        measurement = {"input_i":"-15.05", "input_tp":"-3", "input_lra":"1",
                       "input_thresh":"-25", "target_offset":"0"}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/"pending.mp4"
            source.write_bytes(b"original")
            def encode(args):
                Path(args[-1]).write_bytes(b"corrected")
                self.assertEqual(args[args.index("-c:v")+1], "copy")
                self.assertIn("linear=true", args[args.index("-af")+1])
            with patch("rm_render.loudness", side_effect=[measurement, {**measurement,"input_i":"-14.02"}]) as measure, \
                 patch("rm_render.run", side_effect=encode), patch("rm_render.ffmpeg", return_value="ffmpeg"):
                final = rm_render.finalize_audio(source)
            self.assertEqual(final["input_i"], "-14.02")
            self.assertEqual(measure.call_count, 2)
            self.assertEqual(source.read_bytes(), b"corrected")

    def test_peak_limited_audio_keeps_best_without_raising(self):
        import rm_render
        original = {"input_i":"-15.26", "input_tp":"-1.49", "input_lra":"1",
                    "input_thresh":"-25", "target_offset":"0"}
        linear = {**original, "input_i":"-14.56"}
        limited = {**original, "input_i":"-14.10", "input_tp":"-0.9"}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/"pending.mp4"
            source.write_bytes(b"original")
            unrelated = Path(tmp)/"pending-normalized.mp4"
            unrelated.write_bytes(b"unrelated")
            calls = []
            def encode(args):
                self.assertEqual(Path(args[args.index("-i")+1]).read_bytes(), b"original")
                self.assertEqual(args[args.index("-c:v")+1], "copy")
                calls.append(args)
                Path(args[-1]).write_bytes(str(len(calls)).encode())
            with patch("rm_render.loudness", side_effect=[original, linear, limited]), \
                 patch("rm_render.run", side_effect=encode), patch("rm_render.ffmpeg", return_value="ffmpeg"), \
                 patch("rm_render.log") as log:
                self.assertEqual(rm_render.finalize_audio(source), linear)
            self.assertEqual(len(calls), 2)
            audio = calls[1][calls[1].index("-af")+1]
            self.assertAlmostEqual(float(audio.split("dB")[0].split("=")[1]), 1.26)
            self.assertIn("alimiter=limit=0.79:level=false:asc=1,aresample=48000", audio)
            self.assertEqual(source.read_bytes(), b"1")
            self.assertEqual(unrelated.read_bytes(), b"unrelated")
            self.assertEqual(set(Path(tmp).iterdir()), {source, unrelated})
            log.assert_called_once()
            self.assertIn("-14.56 LUFS", log.call_args[0][0])

    def test_choose_audio_candidate(self):
        from rm_render import choose_audio_candidate
        cases = [
            ([(-15.26, -1.49), (-14.56, -1.49), (-14.1, -.9)], 1),
            ([(-14.6, -1.1), (-15, -1.2), (-14.8, -1.3)], 0),
            ([(-15.26, -1.49), (-14.56, -1.49), (-14.1, -1)], 2),
            ([(-15, -.9), (-14.2, -.5), (-14.5, -.8)], 1),
            ([(float("-inf"), float("-inf")), (-14.2, -1.2)], 1),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                measurements = [{"input_i": str(i), "input_tp": str(tp)} for i, tp in values]
                self.assertEqual(choose_audio_candidate(measurements), expected)

    def test_verify_loudness_thresholds(self):
        import rm_verify
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/"source.mp4"
            source.write_bytes(b"source")
            data = {"source": {"path": str(source), "size": 6, "sha256": "test"}}
            manifest = {"reels": [{"file": "reel.mp4", "duration": 20, "work": "work"}]}
            info = {"duration": 20, "width": 1080, "height": 1920, "has_audio": True}
            for integrated, expected in [(-14.56, "PASS"), (-15, "PASS"), (-13, "PASS"),
                                         (-15.01, "WARN"), (-12.99, "WARN"), (-16, "WARN"),
                                         (-12, "WARN"), (-16.01, "FAIL"), (-11.99, "FAIL"),
                                         (float("-inf"), "WARN")]:
                with self.subTest(integrated=integrated), \
                     patch("rm_verify.read_json", side_effect=[data, manifest]), \
                     patch("rm_verify.fingerprint", return_value={"size": 6, "sha256": "test"}), \
                     patch("rm_verify.probe", return_value=info), \
                     patch("rm_render.loudness", return_value={"input_i": str(integrated)}), \
                     patch("rm_verify.run", return_value=SimpleNamespace(returncode=0, stderr="")), \
                     patch("rm_verify.ffmpeg", return_value="ffmpeg"), patch("rm_verify.log"):
                    report = rm_verify.verify(root)
                    row = next(r for r in report["checks"] if r["check"] == "V4")
                    self.assertEqual(row["status"], expected)

    def test_doctor_rejects_incomplete_cv2(self):
        import contextlib
        import io
        from types import SimpleNamespace
        output = io.StringIO()
        with patch.dict(sys.modules, {"cv2":SimpleNamespace()}), contextlib.redirect_stdout(output):
            reelmaker.doctor(True)
        report = json.loads(output.getvalue())
        self.assertEqual(report["face_detection"], {"available":False,"fix":"re-run setup --yes"})
        self.assertIn("opencv-python-headless<5", reelmaker.installation_plan("none")["packages"])

    def test_normalize_preserves_display_and_monotonicity(self):
        words = rm_transcribe.normalize([
            {"word":" Hello ","start":-.5,"end":.2,"display":""},
            {"word":"there","start":.1,"end":1.8},
            {"word":" ","start":1.8,"end":2},
            {"word":"end","start":2,"end":3}],2.5)
        self.assertEqual(words[0]["display"],"")
        self.assertEqual([w["i"] for w in words],[0,1,2])
        self.assertEqual(words[1]["start"],.2)
        self.assertEqual(words[-1]["end"],2.5)

    def test_repetition_loop_is_collapsed(self):
        words = [{"word":token,"start":i*.4,"end":i*.4+.3}
                 for i,token in enumerate(("one two three "*4+"finished.").split())]
        normalized = rm_transcribe.normalize(words,10)
        self.assertEqual([w["text"] for w in normalized],["one","two","three","finished."])

    def test_word_edits_override_stale_timestamps(self):
        words = [{"text":"a","start":0,"end":.3},{"text":"b","start":.35,"end":.6},
                 {"text":"c","start":.7,"end":1}]
        self.assertEqual(rm_moments.bounds({"first_word":1,"last_word":1,"start":99,"end":100},words,1),(.3,.7))

    def test_hidden_words_and_edge_fillers(self):
        from rm_render import relative_words
        words = [{"text":"um","start":0,"end":.2},{"text":"secret","display":"","start":.2,"end":.4},
                 {"text":"hello","display":"Hello","start":.4,"end":.7},{"text":"uh","start":.8,"end":1}]
        self.assertEqual(relative_words(words,{"first_word":0,"last_word":3},0,1),
                         [{"text":"Hello","start":.4,"end":.7}])

    def test_srt_never_exceeds_two_lines_or_42_columns(self):
        from rm_render import write_srt
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/"captions.srt"
            words = [{"text":"a"*n,"start":i,"end":i+.8} for i,n in enumerate((24,24,24,100))]
            write_srt(words,target)
            for cue in target.read_text().strip().split("\n\n"):
                lines = cue.splitlines()[2:]
                self.assertLessEqual(len(lines),2)
                self.assertTrue(all(len(line)<=42 for line in lines))

    def test_import_srt_and_vtt(self):
        with tempfile.TemporaryDirectory() as tmp:
            for suffix,body in ((".srt","1\n00:00:01,000 --> 00:00:03,000\nHello world!"),
                                 (".vtt","WEBVTT\n\n00:01.000 --> 00:03.000 align:start\n<b>Hello</b> world!")):
                path = Path(tmp)/("captions"+suffix)
                path.write_text(body,encoding="utf-8")
                words,_ = rm_transcribe.imported(path)
                self.assertEqual([w["text"] for w in words],["Hello","world!"])
                self.assertEqual(words[0]["start"],1)
                self.assertEqual(words[-1]["end"],3)

    def test_existing_moments_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"moments.json"
            content = '{"moments":[{"locked":true,"headline":"Edited"}]}\n'
            path.write_text(content)
            rm_moments.find(tmp)
            self.assertEqual(path.read_text(),content)

    def test_consent_plan_does_not_create_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/"not-created"
            with patch.dict(os.environ,{"REEL_MAKER_HOME":str(target)}):
                code = reelmaker.main(["setup","--backend","none","--no-faces"])
                self.assertEqual(code,3)
                self.assertFalse(target.exists())

    def test_doctor_without_site_packages(self):
        cli = Path(reelmaker.__file__)
        env = dict(os.environ,REEL_MAKER_NO_REEXEC="1",PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable,"-S",str(cli),"doctor","--json"],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["dependencies"]["Pillow"])

    def test_cli_reexecutes_in_existing_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_home = Path(tmp)/"home"
            created = subprocess.run([sys.executable,"-m","venv","--without-pip",str(local_home/"venv")],capture_output=True,text=True)
            self.assertEqual(created.returncode,0,created.stderr)
            env = dict(os.environ,REEL_MAKER_HOME=str(local_home),PYTHONDONTWRITEBYTECODE="1")
            env.pop("REEL_MAKER_NO_REEXEC",None)
            result = subprocess.run([sys.executable,str(Path(reelmaker.__file__)),"doctor","--json"],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(result.stdout)["venv_active"])

    def test_fallback_probe_reads_real_media(self):
        try:
            ffmpeg = rm_env.ffmpeg()
        except rm_env.NeedsInput:
            self.skipTest("ffmpeg missing")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"space ' ü.mp4"
            rm_env.run([ffmpeg,"-nostdin","-y","-v","error","-f","lavfi","-i","color=s=160x90:r=15",
                        "-f","lavfi","-i","sine=frequency=440","-t","1",*rm_env.encoder_args(),
                        "-c:a","aac",path])
            with patch("rm_env.ffprobe",return_value=None):
                info = rm_env.probe(path)
            self.assertEqual((info["width"],info["height"]),(160,90))
            self.assertTrue(info["has_audio"])
            self.assertAlmostEqual(info["duration"],1,delta=.1)

    def test_python39_syntax_and_no_heavy_top_level_imports(self):
        import ast
        scripts = Path(reelmaker.__file__).parent
        heavy = {"PIL","numpy","cv2","mlx_whisper","faster_whisper","whisper"}
        for path in scripts.glob("*.py"):
            tree = ast.parse(path.read_text(),feature_version=(3,9))
            for node in tree.body:
                if isinstance(node,ast.Import):
                    self.assertFalse({a.name.split(".")[0] for a in node.names} & heavy,path)
                elif isinstance(node,ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0],heavy,path)


if __name__ == "__main__":
    unittest.main()
