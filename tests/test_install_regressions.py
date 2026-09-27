"""Offline clean-install regression tests; no model downloads."""
import copy
import io
import runpy
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"reel-maker"/"scripts"))
import transcribe
import make_reels
from common import read_json, write_json, job_path
from align import align_moment


class InstallRegressions(unittest.TestCase):
    def test_unrelated_transcript_is_not_discovered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"unrelated transcript.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:20:00.000\nunrelated text\n")
            self.assertIsNone(transcribe.find_transcript(root/"meeting.mp4"))

    def test_mlx_normalizes_empty_zero_reversed_and_source_edges(self):
        raw = [{"word":"hello", "start":-.1, "end":.2},
               {"word":" ", "start":.2, "end":.2},
               {"word":"zero", "start":.2, "end":.2},
               {"word":"back", "start":.5, "end":.4},
               {"word":"end", "start":1, "end":1.1}]
        mlx = types.SimpleNamespace(transcribe=lambda *a, **kw: {"segments":[{"text":"hello zero back end", "words":raw}]})
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {"mlx_whisper":mlx}), \
             patch("transcribe.run"), patch("transcribe.find_transcript", return_value=None), \
             patch("transcribe.duration", return_value=1):
            result = transcribe.transcribe("fixture.mp4", None, Path(temp)/"words.json", "mlx-whisper")
        words = result["words"]
        self.assertEqual([w["text"] for w in words], ["hello", "zero", "back", "end"])
        self.assertTrue(all(0 <= w["start"] < w["end"] <= 1 for w in words))
        self.assertTrue(all(w["end"]-w["start"] >= .019999 for w in words))
        self.assertTrue(all(a["end"] <= b["start"] for a,b in zip(words, words[1:])))

    def test_auto_transcript_must_match_audio(self):
        mlx = types.SimpleNamespace(transcribe=lambda *a, **kw: {"segments":[{
            "text":"actual spoken words", "words":[{"word":"actual", "start":0, "end":1},
                {"word":"spoken", "start":1, "end":2}, {"word":"words", "start":2, "end":3}]}]})
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {"mlx_whisper":mlx}), \
             patch("transcribe.run"), patch("transcribe.duration", return_value=180), patch("sys.stdout", new_callable=io.StringIO) as log:
            root = Path(temp)
            (root/"Meeting-transcript.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:59.000\nwrong unrelated discussion\n")
            result = transcribe.transcribe(root/"meeting.mp4", None, root/"words.json", "mlx-whisper")
            self.assertEqual(result["timing"], "whisper")
            self.assertIn("Ignoring transcript", log.getvalue())

    def test_start_never_crosses_previous_word(self):
        for previous_end in (.99, 1):
            with self.subTest(previous_end=previous_end):
                words = [{"text":"before", "start":.5, "end":previous_end},
                         {"text":"hello", "start":1, "end":1.4},
                         {"text":"world", "start":1.4, "end":2}]
                moment = {"id":2, "first_word":1, "last_word":2}
                frames = [(i*.02, 0 if 45 <= i < 50 else .1) for i in range(250)]
                with tempfile.TemporaryDirectory() as temp, patch("align.extract_audio"), \
                     patch("align.energy_frames", return_value=frames):
                    align_moment("fixture", words, moment, 5, temp,
                                 aligner=lambda *a: copy.deepcopy(words))
                self.assertGreaterEqual(moment["start"], previous_end)
                self.assertEqual(moment["alignment"]["start_strategy"], "continuous_speech")
                self.assertEqual(moment["audio_fade_in"], .12)

    def run_job(self, root):
        video = root/"source.mp4"
        video.write_bytes(b"fixture")
        out = root/"out"
        out.mkdir()
        state = out/"working files"
        state.mkdir()
        words = transcribe.spread("word "*180, 0, 180)
        write_json(state/"words.json", {"words":words})
        write_json(state/"job.json", {"video":str(video.resolve()), "baseline":{
            "duration":180, "sha256":make_reels.digest(video)}, "reels":{}})
        write_json(out/"reel-maker.config.json", {})
        candidates = [{"id":i+1, "first_word":i*5, "last_word":i*5+22,
                       "headline":"Useful idea", "reason":"fixture", "complete_sentences":True,
                       "scores":dict(hook=3, clarity=3, proof=3, offer_fit=3),
                       "selected":i in (2,7), "instagram_caption":"Useful idea", "cover_text":"Useful"}
                      for i in range(10)]
        write_json(out/"moments.json", {"offer":"fixture", "transcript_read_in_full":True, "candidates":candidates})
        calls = []
        def fake_align(video, current, moment, *args):
            first, last = moment["first_word"], moment["last_word"]
            for w in current[first:last+1]:
                w.setdefault("est_start", w["start"])
                w.setdefault("est_end", w["end"])
                w["start"] += .05
                w["end"] += .05
            moment.update(start=current[first]["start"]-.08, end=current[last]["end"]+.15,
                          first_word_start=current[first]["start"], first_word_text=current[first]["text"],
                          audio_fade_in=.12, alignment={"status":"PASS"})
            calls.append(moment["id"])
        rendered = []
        def fake_render(video, moment, current, config, output, work):
            work.mkdir(parents=True)
            output.write_bytes(b"render")
            write_json(work/"render.json", {})
            rendered.append((copy.deepcopy(moment), copy.deepcopy(current)))
        command = ["--video", str(video), "--out", str(out), "--backend", "mlx-whisper"]
        with patch("make_reels.align_moment", side_effect=fake_align), \
             patch("make_reels.render", side_effect=fake_render), \
             patch("make_reels.verify_job", return_value=[]), patch("make_reels.contact_sheet"):
            make_reels.main(command)
            make_reels.main(command+["--rerender", "3"])
        return out, words, calls, rendered

    def test_rerender_preserves_original_words_and_cut(self):
        with tempfile.TemporaryDirectory() as temp:
            out, original, calls, rendered = self.run_job(Path(temp))
            self.assertEqual(read_json(job_path(out, "words.json"))["words"], original)
            self.assertEqual(calls, [3,8])
            self.assertEqual(rendered[0], rendered[2])

    def test_final_names_use_delivery_order_and_keep_candidate_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            out, _, _, _ = self.run_job(Path(temp))
            reels = read_json(job_path(out, "job.json"))["reels"]
            self.assertTrue(reels["3"]["file"].startswith("Reel 1 - "))
            self.assertTrue(reels["8"]["file"].startswith("Reel 2 - "))
            selected = [m for m in read_json(out/"moments.json")["candidates"] if m["selected"]]
            self.assertEqual([(m["id"],m["reel_number"]) for m in selected], [(3,1),(8,2)])

    def test_validator_identifies_bad_word_and_times(self):
        with self.assertRaisesRegex(ValueError, r"word 0.*start=1.*end=1"):
            make_reels.validate_moments({"offer":"fixture", "transcript_read_in_full":True},
                                        [{"text":"bad", "start":1, "end":1}], 180, 2)

    def test_transcript_duration_limits_include_skipped_cues(self):
        for length, last, accepted in ((180,216,True), (180,217,False),
                                       (3600,4201,False)):
            with self.subTest(length=length, last=last), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                end = f"{last//3600:02}:{last%3600//60:02}:{last%60:02}.000"
                (root/"meeting.vtt").write_text(f"WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nhello world\n\n00:00:04.000 --> {end}\n"+"repeat "*6)
                with patch("transcribe.run"), patch("transcribe.duration", return_value=length), \
                     patch("transcribe.recognize", return_value=transcribe.spread("hello world", 0, 3)) as recognize:
                    result = transcribe.transcribe(root/"meeting.mp4", None, root/"words.json", "mlx-whisper")
                self.assertEqual(result["timing"], "character-estimate" if accepted else "whisper")
                self.assertEqual(recognize.call_count, 1)

    def test_audio_overlap_is_time_local_and_threshold_is_inclusive(self):
        for text, accepted in (("one two",True), ("one unrelated",False)):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root/"meeting.vtt").write_text(f"WEBVTT\n\n00:00:00.000 --> 00:00:50.000\n{text}\n\n00:01:10.000 --> 00:02:00.000\none two three four five\n")
                with patch("transcribe.run"), patch("transcribe.duration", return_value=180), \
                     patch("transcribe.recognize", return_value=transcribe.spread("one two three four five", 0, 5)) as recognize:
                    result = transcribe.transcribe(root/"meeting.mp4", None, root/"words.json", "mlx-whisper")
                self.assertEqual(result["timing"], "character-estimate" if accepted else "whisper")
                self.assertEqual(recognize.call_args.args[1], "mlx-whisper")

    def test_force_transcription_skips_discovery_and_supplied_transcript(self):
        with tempfile.TemporaryDirectory() as temp, patch("transcribe.find_transcript") as find, \
             patch("transcribe.subtitles") as subtitles, patch("transcribe.duration", return_value=180), \
             patch("transcribe.run"), patch("transcribe.recognize", return_value=transcribe.spread("hello world", 0, 3)):
            result = transcribe.transcribe("fixture.mp4", "fixture.vtt", Path(temp)/"words.json", no_transcript=True)
        self.assertEqual(result["timing"], "whisper")
        find.assert_not_called()
        subtitles.assert_not_called()

    def test_default_backend_detects_apple_silicon_only(self):
        from common import default_backend
        for system, machine, expected in (("Darwin","arm64","mlx-whisper"),
                                          ("Darwin","x86_64","faster-whisper"),
                                          ("Linux","aarch64","faster-whisper"),
                                          ("Windows","AMD64","faster-whisper")):
            with patch("common.platform.system", return_value=system), \
                 patch("common.platform.machine", return_value=machine):
                self.assertEqual(default_backend(), expected)

    def test_malformed_matching_sibling_does_not_abort_discovery(self):
        with tempfile.TemporaryDirectory() as temp, patch("transcribe.duration", return_value=180):
            root = Path(temp)
            (root/"meeting-bad.vtt").write_text("WEBVTT\n\nbad --> timestamp\ninvalid\n")
            good = root/"meeting.vtt"
            good.write_text("WEBVTT\n\n00:00:00.000 --> 00:03:00.000\nhello\n")
            self.assertEqual(transcribe.find_transcript(root/"meeting.mp4"), good)

    def test_progress_heartbeat_stops_even_on_failure(self):
        from progress import progress
        stopped = types.SimpleNamespace(wait=Mock(side_effect=[False, True]), set=Mock())
        with patch("progress.Event", return_value=stopped), patch("builtins.print") as log:
            with self.assertRaises(ValueError):
                with progress("Transcribing"):
                    raise ValueError("fixture")
        self.assertEqual(stopped.wait.call_args_list, [call(30), call(30)])
        stopped.set.assert_called_once()
        self.assertEqual(log.call_count, 2)

    def test_pip_progress_wrapper_uses_current_venv_and_exit_status(self):
        script = Path(transcribe.__file__).with_name("progress.py")
        with patch.object(sys, "argv", [str(script), "Pillow>=10.1", "mlx-whisper"]), \
             patch("subprocess.run", return_value=types.SimpleNamespace(returncode=7)) as run, \
             patch("builtins.print") as log:
            with self.assertRaises(SystemExit) as exited:
                runpy.run_path(str(script), run_name="__main__")
        self.assertEqual(exited.exception.code, 7)
        run.assert_called_once_with([sys.executable, "-m", "pip", "install", "Pillow>=10.1", "mlx-whisper"])
        self.assertTrue(log.called)
