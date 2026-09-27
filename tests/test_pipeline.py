"""Regression coverage for local alignment, resumable cleanup and active-picture fitting."""
from array import array
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"reel-maker"/"scripts"))
from align import align_moment, energy_frames, silence_start, whisper_words
from common import clean_output, ffmpeg, job_path, read_json, run, write_json
from render import cleaned, detect_active_picture
from transcribe import find_transcript, indexed_transcript, spread, subtitles
from verify import machine_listen
from make_reels import validate_moments


def audio_fixture(path):
    # A preceding fragment, silence, then the chosen utterance.
    samples = array("h", (5000 if .2 <= n/16000 < .5 or 1.1 <= n/16000 < 1.8 else 0
                          for n in range(3*16000)))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(samples.tobytes())


class Pipeline(unittest.TestCase):
    def test_alignment_fallback_and_matched_times(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio_fixture(root/"source.wav")
            words = spread("hello lovely world", 1, 2)
            original = [dict(w) for w in words]
            moment = {"id": 1, "first_word": 0, "last_word": 2, "start": 1, "end": 2, "first_word_start": 1}
            def unavailable(*args):
                raise RuntimeError("Whisper unavailable offline")
            report = align_moment(root/"source.wav", words, moment, 3, root/"work", aligner=unavailable)
            self.assertEqual(report["status"], "NEEDS_REVIEW")
            self.assertIn("unavailable", report["reason"])
            self.assertEqual(words, original)
            def fake(*args):
                return [{"text": "Hello", "start": 1.1, "end": 1.3},
                        {"text": "world", "start": 1.6, "end": 1.8}]
            report = align_moment(root/"source.wav", words, moment, 3, root/"work", aligner=fake)
            self.assertAlmostEqual(report["matched_share"], 2/3)
            self.assertAlmostEqual(words[0]["start"], 1.1)
            self.assertAlmostEqual(words[2]["end"], 1.8)
            self.assertAlmostEqual(words[1]["start"], 1.3)
            self.assertAlmostEqual(words[1]["end"], 1.6)
            self.assertGreater(report["max_drift"], 0)
            self.assertGreater(moment["start"], .5)
            self.assertLess(moment["start"], 1.1)
            self.assertAlmostEqual(moment["end"], 1.95)
            self.assertEqual(words[0]["text"], "hello")

    def test_silence_detection_does_not_include_previous_fragment(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"audio.wav"
            audio_fixture(path)
            boundary, found = silence_start(energy_frames(path), 1.1)
            self.assertTrue(found)
            self.assertAlmostEqual(boundary, 1.08)

    def test_transcript_discovery_and_indexed_cues(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root/"meeting.mp4"
            p = root/"MEETING transcript.srt"
            p.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello world\n\n2\n00:00:01,000 --> 00:00:03,000\nnext sentence\n")
            self.assertEqual(find_transcript(video), p)
            self.assertEqual(indexed_transcript(subtitles(p)), "[0.000-1.000] #0 hello world\n[1.000-3.000] #2 next sentence\n")
            q = root/"meeting translated.vtt"
            q.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:09.000\nhello world\n")
            with patch("transcribe.duration", return_value=10):
                self.assertEqual(find_transcript(video), q)
            (root/"unrelated.vtt").write_text("ignored")
            with patch("transcribe.duration", return_value=2):
                self.assertEqual(find_transcript(video), p)

    def test_cleanup_is_resumable_and_preserves_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            keep = {"Reel 1 - hello.mp4", "contact-sheet.jpg", "tests.md", "moments.json",
                    "clips-and-captions.txt", "reel-maker.config.json", "working files"}
            for name in keep-{"working files", "reel-maker.config.json"}:
                (out/name).write_text("fixture")
            for name in ("clip-old.mp4", "words.json", "transcript.txt", "brand.png"):
                (out/name).write_text("retained")
            job = {"reels": {"1": {"file": "Reel 1 - hello.mp4"}}}
            write_json(out/"job.json", job)
            (out/"assets").mkdir()
            (out/"assets"/"font.ttf").write_text("font fixture")
            write_json(out/"reel-maker.config.json", {"logo_path": "brand.png", "font_path": "assets/font.ttf"})
            clean_output(out, job)
            self.assertEqual({p.name for p in out.iterdir()}, keep)
            self.assertEqual(read_json(job_path(out, "job.json")), job)
            self.assertEqual((out/"working files"/"clip-old.mp4").read_text(), "retained")
            self.assertEqual(read_json(out/"reel-maker.config.json")["logo_path"], "working files/brand.png")
            self.assertEqual(read_json(out/"reel-maker.config.json")["font_path"], "working files/assets/font.ttf")
            clean_output(out, job)
            self.assertEqual({p.name for p in out.iterdir()}, keep)

    def test_cropdetect_letterboxed_video(self):
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp)/"letterboxed.mp4"
            run([ffmpeg(), "-nostdin", "-n", "-f", "lavfi", "-i", "color=white:s=80x140:d=2:r=10",
                 "-vf", "pad=320:180:120:20:black", "-c:v", "libx264", video])
            box = detect_active_picture(video, 320, 180)
            self.assertEqual(box, {"width": 80, "height": 140, "x": 120, "y": 20})
            target = Path(temp)/"active.png"
            run([ffmpeg(), "-nostdin", "-n", "-i", video, "-vf",
                 f"crop={box['width']}:{box['height']}:{box['x']}:{box['y']}", "-frames:v", "1", target])
            from PIL import Image
            with Image.open(target) as image:
                self.assertEqual(image.size, (80, 140))
                self.assertGreater(min(image.getpixel((0,0))), 240)

    def test_machine_sync_thresholds_and_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio_fixture(root/"source.wav")
            events = [{"words": ["hello", "world"], "active": i%2, "start": .1+i*.2, "end": .25+i*.2}
                      for i in range(10)]
            metadata = {"events": events, "moment": {"start": 0, "end": 3}}
            heard = [{"text": e["words"][e["active"]], "start": e["start"], "end": e["end"]} for e in events]
            report = machine_listen(root/"source.wav", metadata, root, aligner=lambda *args: heard)
            self.assertEqual(report["T5"]["status"], "PASS")
            self.assertEqual(report["T6"]["status"], "PASS")
            self.assertEqual(len(report["T5"]["samples"]), 3)
            # An unrecognized prior fragment must not pass merely because frame zero is quiet.
            shifted = [{**w, "start": w["start"]+.1, "end": w["end"]+.1} for w in heard]
            with patch("verify.energy_frames", return_value=[(0, 0), (.04, .1), (.16, 0), (.2, .1)]):
                noisy = machine_listen(root/"source.wav", metadata, root, aligner=lambda *args: shifted)
            self.assertEqual(noisy["T6"]["status"], "NEEDS_REVIEW")
            self.assertTrue(noisy["T6"]["preword_noise"])
            bad = [{**w, "start": w["start"]+1.1, "end": w["end"]+1.1} for w in heard]
            report = machine_listen(root/"source.wav", metadata, root, aligner=lambda *args: bad)
            self.assertEqual(report["T5"]["status"], "FAIL")
            with patch("verify.whisper_words", side_effect=RuntimeError("Whisper unavailable")):
                report = machine_listen(root/"source.wav", metadata, root)
            self.assertEqual(report["T5"]["status"], "NEEDS_REVIEW")
            self.assertIn("unavailable", report["T5"]["evidence"])

    def test_transcript_longer_than_video_remains_usable(self):
        words = spread(" ".join(["word"]*100), 0, 100)
        data = {"offer": "Fixture", "transcript_read_in_full": True, "candidates": [
            {"id": i+1, "first_word": i*5, "last_word": i*5+20, "headline": "Useful fixture",
             "reason": "Regression", "scores": {"hook": 3, "clarity": 3, "proof": 3, "offer_fit": 3},
             "complete_sentences": True, "selected": i in (0,5), "instagram_caption": "Fixture caption",
             "cover_text": "Fixture"} for i in range(10)]}
        with patch("builtins.print") as warning:
            self.assertEqual(len(validate_moments(data, words, 90, 2)), 2)
            self.assertTrue(warning.called)
        data["candidates"][0].update(first_word=75, last_word=95)
        with self.assertRaisesRegex(ValueError, "after the video"):
            validate_moments(data, words, 90, 2)

    def test_missing_backend_is_graceful_without_model_download(self):
        with patch("align.local_model", side_effect=ImportError("fixture missing backend")), \
             patch.dict(sys.modules, {"mlx_whisper": None}):
            with self.assertRaisesRegex(RuntimeError, "Local Whisper unavailable"):
                whisper_words(Path("unused.wav"))

    def test_empty_display_and_capital_i(self):
        words = spread("oh my god! and i use OpenAI.", 0, 8)
        words[3]["display"] = ""
        self.assertEqual([w["text"] for w in cleaned(words)], ["Oh", "my", "god!", "I", "use", "OpenAI."])
