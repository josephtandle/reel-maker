"""Offline regression fixtures for alignment and changing camera layouts."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"reel-maker"/"scripts"))
from align import align_moment, energy_frames, extract_audio, silence_start
from transcribe import spread
import render
from common import ffmpeg, run
from PIL import Image
from verify import machine_listen, verify_job
from common import job_path, write_json


class LayoutRegressions(unittest.TestCase):
    def test_dark_portrait_top_is_picture(self):
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp)/"dark.mkv"
            run([ffmpeg(), "-nostdin", "-n", "-f", "lavfi", "-i",
                 "color=white:s=80x180:d=2:r=10,drawbox=x=0:y=0:w=80:h=54:color=0x080808:t=fill,pad=320:180:120:0:black",
                 "-c:v", "ffv1", video])
            segments = render.detect_layout_segments(video, 320, 180, 2)
            for segment in segments:
                self.assertEqual(segment["crop"], {"x":120, "y":0, "width":80, "height":180})

    def test_vertical_borders_require_ninety_percent_full_width_black(self):
        for black_frames, expected_y in ((9, 2), (8, 0)):
            with self.subTest(black_frames=black_frames):
                frames = []
                for index in range(10):
                    image = Image.new("RGB", (8, 10), "black")
                    image.paste("white", (2, 2, 6, 8))
                    if index >= black_frames:
                        # A pixel outside cropdetect's columns still disqualifies a row.
                        image.putpixel((0, 0), (1, 1, 1))
                        image.putpixel((0, 9), (1, 1, 1))
                    frames.append(image.tobytes())
                def decode(*args, **kwargs):
                    kwargs["stdout"].write(b"".join(frames))
                    return type("Result", (), {"returncode":0})()
                segments = [{"start":0, "end":5, "crop":{"x":2, "y":2, "width":4, "height":6}}]
                with patch("render.subprocess.run", side_effect=decode):
                    render.widen_vertical_crops("fixture", 8, 10, segments)
                self.assertEqual(segments[0]["crop"]["y"], expected_y)
                self.assertEqual(segments[0]["crop"]["height"], 10-2*expected_y)

    def test_segmented_render_applies_audio_fade(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root/"source.mp4"
            run([ffmpeg(), "-nostdin", "-n", "-f", "lavfi", "-i",
                 "color=white:s=80x140:d=10:r=25,pad=320:180:120:20:black",
                 "-f", "lavfi", "-i", "color=yellow:s=320x180:d=10:r=25",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
                 "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                 "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-c:a", "aac", video])
            words = spread("Useful words across changing layouts", .08, 19.8)
            moment = {"start":0, "end":20, "first_word":0, "last_word":4,
                      "first_word_start":.08, "headline":"Useful words", "audio_fade_in":.12}
            output = root/"reel.mp4"
            meta = render.render(video, moment, words, render.DEFAULT_CONFIG, output, root/"work")
            self.assertEqual(len(meta["layout_segments"]), 2)
            self.assertIn("afade=t=in:st=0:d=0.12", meta["render_command"])
            extract_audio(output, root/"audio.wav")
            frames = energy_frames(root/"audio.wav")
            self.assertLess(frames[0][1], frames[10][1]*.25)
            self.assertGreater(frames[10][1], .01)
            for index, t in enumerate((1, 11)):
                png = root/f"render-{index}.png"
                run([ffmpeg(), "-nostdin", "-n", "-ss", str(t), "-i", output, "-frames:v", "1", png])
                geo = meta["layout_segments"][index]["layout"]
                with Image.open(png) as image:
                    for x in (geo["x"]+2, geo["x"]+geo["width"]-3):
                        self.assertGreater(min(image.getpixel((x, geo["video_y"]+geo["height"]//2))[:2]), 220)

    def test_short_layouts_merge_without_losing_picture(self):
        narrow = {"width":80,"height":140,"x":120,"y":20}
        full = {"width":320,"height":180,"x":0,"y":0}
        for samples in ([(0,narrow),(.5,full)], [(0,full),(2,narrow)],
                        [(0,narrow),(1,full),(1.5,narrow)]):
            segments = render.group_layout_samples(samples, 2.5)
            self.assertTrue(all(s["end"]-s["start"] >= 1 for s in segments))
            self.assertEqual(segments[0]["start"], 0)
            self.assertEqual(segments[-1]["end"], 2.5)
            self.assertIn(full, [s["crop"] for s in segments])

    def test_portrait_to_full_frame(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root/"switch.mp4"
            run([ffmpeg(), "-nostdin", "-n", "-f", "lavfi", "-i",
                 "color=white:s=80x140:d=2:r=10,pad=320:180:120:20:black",
                 "-f", "lavfi", "-i", "color=yellow:s=320x180:d=2:r=10",
                 "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                 "-c:v", "libx264", video])
            detector = getattr(render, "detect_layout_segments", None)
            self.assertTrue(callable(detector), "Per-segment layout detection is missing")
            segments = detector(video, 320, 180, 4)
            self.assertEqual(len(segments), 2)
            box = segments[0]["crop"]
            self.assertEqual((box["x"], box["width"]), (120, 80))
            # Lossy border ringing is not pure black: retain it conservatively.
            self.assertLessEqual(box["y"], 20)
            self.assertGreaterEqual(box["y"]+box["height"], 160)
            self.assertEqual(segments[1]["crop"], {"width":320,"height":180,"x":0,"y":0})
            self.assertAlmostEqual(segments[1]["start"], 2)
            graph = render.picture_graph(segments, 0, 1, "boxblur=30:5", "")
            target = root/"picture.mp4"
            run([ffmpeg(), "-nostdin", "-n", "-filter_complex_threads", "1", "-i", video,
                 "-filter_complex", ";".join(graph), "-map", "[v0]", "-an", "-c:v", "libx264",
                 "-preset", "ultrafast", target])
            for index, t in enumerate((1, 3)):
                png = root/f"frame-{index}.png"
                run([ffmpeg(), "-nostdin", "-n", "-ss", str(t), "-i", target, "-frames:v", "1", png])
                geo = segments[index]["layout"]
                with Image.open(png) as image:
                    for x in (geo["x"]+2, geo["x"]+geo["width"]-3):
                        rgb = image.getpixel((x, geo["video_y"]+geo["height"]//2))
                        self.assertGreater(min(rgb[:2]), 220)


class AlignmentRegressions(unittest.TestCase):
    def test_t5_excludes_fillers_and_unmatched_words(self):
        tokens = ["hello", "um", "missing", "uh", "world", "er", "ah"]
        events = [{"words":tokens, "active":i, "start":i*.3, "end":i*.3+.2}
                  for i in range(len(tokens))]
        heard = [{"text":"hello", "start":0, "end":.2},
                 {"text":"um", "start":4, "end":4.2},
                 {"text":"world", "start":1.2, "end":1.4}]
        metadata = {"events":events, "moment":{"start":0, "end":3,
                    "alignment":{"status":"NEEDS_REVIEW", "matched_share":.5,
                                 "start_strategy":"quiet_gap", "reason":"Low match share"}}}
        with tempfile.TemporaryDirectory() as temp, patch("verify.extract_audio"), \
             patch("verify.energy_frames", return_value=[(0, 0)]):
            result = machine_listen("fixture", metadata, Path(temp), aligner=lambda *a: heard)["T5"]
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["within_half_second_share"], 1)
        self.assertAlmostEqual(result["max_offset"], 0)
        self.assertAlmostEqual(result["matched_share"], 3/7)
        self.assertEqual([w["text"] for w in result["unmatched_words"]], ["missing"])
        self.assertEqual([w["text"] for w in result["filler_words"]], ["um", "uh", "er", "ah"])
        self.assertEqual(len(result["word_offsets"]), 2)


    def test_alignment_warning_in_markdown_does_not_fail_t5(self):
        report = {"file":"reel.mp4", "sha256":"fixture", "stills":[],
                  "checks":{f"T{i}":{"status":"PASS", "label":"fixture", "evidence":"fixture"}
                            for i in range(1, 11)},
                  "machine_audio":{"T5":{"matched_share":.8,
                      "unmatched_words":[{"index":2,"text":"missing"}],
                      "filler_words":[{"index":1,"text":"um"}]}}, "alignment":None}
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            job_path(out, "job.json").parent.mkdir(parents=True)
            write_json(job_path(out, "job.json"), {"video":"fixture", "baseline":{},
                       "reels":{"1":{"metadata":"metadata.json", "file":"reel.mp4", "evidence":"evidence"}}})
            write_json(out/"metadata.json", {})
            with patch("verify.verify_reel", return_value=report):
                reports = verify_job(out)
            markdown = (out/"tests.md").read_text()
        self.assertIn("WARNING: Caption alignment share below 0.90", markdown)
        self.assertIn("look at the listed unmatched words: #2 missing", markdown)
        self.assertIn("Excluded fillers: #1 um", markdown)
        self.assertEqual(reports[0]["checks"]["T5"]["status"], "PASS")

    def test_no_matched_nonfillers_cannot_pass_sync(self):
        metadata = {"events":[{"words":["um", "missing"], "active":i, "start":i, "end":i+.2}
                               for i in range(2)], "moment":{"start":0, "end":2}}
        with tempfile.TemporaryDirectory() as temp, patch("verify.extract_audio"), \
             patch("verify.energy_frames", return_value=[]):
            result = machine_listen("fixture", metadata, Path(temp), aligner=lambda *a: [])["T5"]
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertIsNone(result["max_offset"])

    def test_only_display_skip_removes_repetitions(self):
        words = spread("um under under water", 0, 2)
        self.assertEqual(len(render.cleaned(words)), 4)
        words[2]["display"] = ""
        self.assertEqual(len(render.cleaned(words)), 3)
        self.assertEqual(words[2]["text"], "under")

    def test_t6_rejects_silent_first_second(self):
        metadata = {"events":[{"words":["hello", "world"], "active":0, "start":.08, "end":.4}],
                    "moment":{"start":0, "end":2}}
        with tempfile.TemporaryDirectory() as temp, patch("verify.extract_audio"), \
             patch("verify.energy_frames", return_value=[(i*.02, 0) for i in range(60)]):
            report = machine_listen("fixture", metadata, Path(temp), aligner=lambda *a: [
                {"text":"hello", "start":.08, "end":.4}])
        self.assertEqual(report["T6"]["status"], "NEEDS_REVIEW")
        self.assertFalse(report["T6"]["speech_in_first_second"])

    def test_t6_records_continuous_speech_fallback(self):
        metadata = {"events": [{"words": ["hello", "world"], "active": 0, "start": .08, "end": .4},
                               {"words": ["hello", "world"], "active": 1, "start": .4, "end": 1}],
                    "audio_fade_in": .12,
                    "moment": {"start": .92, "end": 2, "first_word_start": 1,
                               "first_word_text": "hello", "audio_fade_in": .12,
                               "alignment": {"status": "PASS", "start_strategy": "continuous_speech"}}}
        heard = [{"text":"hello", "start":.08, "end":.4}, {"text":"world", "start":.4, "end":1}]
        with tempfile.TemporaryDirectory() as temp, patch("verify.extract_audio"), \
             patch("verify.energy_frames", return_value=[(i*.02, .1) for i in range(60)]):
            report = machine_listen("fixture", metadata, Path(temp), aligner=lambda *a: heard)
        self.assertEqual(report["T6"]["status"], "PASS", report)
        self.assertEqual(report["T6"]["audio_fade_in"], .12)
        self.assertTrue(report["T6"]["continuous_speech_fallback"])
        self.assertTrue(report["T6"]["speech_in_first_second"])

    def test_continuous_speech_uses_preroll_and_fade(self):
        words, moment, report = self.align("hello world", [
            {"text": "hello", "start": 1, "end": 1.4},
            {"text": "world", "start": 1.4, "end": 2}])
        self.assertEqual(report["status"], "PASS")
        self.assertAlmostEqual(moment["start"], .92)
        self.assertAlmostEqual(moment["audio_fade_in"], .12)
        self.assertEqual(report["start_strategy"], "continuous_speech")

    def test_short_quiet_gap_and_energy_snapping(self):
        frames = [(i*.02, 0 if 46 <= i < 50 else .1) for i in range(250)]
        boundary, found = silence_start(frames, 1)
        self.assertTrue(found)
        self.assertAlmostEqual(boundary, .98)
        words, moment, report = self.align("hello world", [
            {"text": "hello", "start": 1.16, "end": 1.6},
            {"text": "world", "start": 1.6, "end": 2}], frames)
        self.assertEqual(report["status"], "PASS")
        self.assertAlmostEqual(words[0]["start"], 1)
        self.assertAlmostEqual(moment["start"], .98)

    def test_unmatched_word_stays_next_to_nearest_anchor(self):
        words, _, report = self.align("hello missing world", [
            {"text": "hello", "start": .5, "end": 1},
            {"text": "world", "start": 4, "end": 4.5}])
        self.assertIn("silence_gap_found", report)
        self.assertLessEqual(words[1]["end"]-words[1]["start"], .301)
        self.assertAlmostEqual(words[1]["start"], 1)

    def align(self, text, heard, frames=None):
        words = spread(text, 1, 3)
        moment = {"id": 1, "first_word": 0, "last_word": len(words)-1}
        if frames is None:
            frames = [(i*.02, .1) for i in range(250)]
        with tempfile.TemporaryDirectory() as temp, \
             patch("align.extract_audio"), patch("align.energy_frames", return_value=frames):
            report = align_moment("fixture", words, moment, 5, Path(temp), aligner=lambda *a: heard)
        return words, moment, report

    def test_unheard_word_between_touching_anchors(self):
        for text in ("hello um world", "hello under under world"):
            heard = [{"text": "hello", "start": 1, "end": 1.4}]
            if "under" in text:
                heard.append({"text": "under", "start": 1.4, "end": 1.8})
            heard.append({"text": "world", "start": heard[-1]["end"], "end": 2.5})
            words, moment, report = self.align(text, heard)
            self.assertIn("silence_gap_found", report, report)
            filler = words[-2]
            self.assertAlmostEqual(filler["end"]-filler["start"], .02)
            self.assertTrue(all(a["end"] <= b["start"]+.001 for a,b in zip(words, words[1:])))


if __name__ == "__main__":
    unittest.main()
