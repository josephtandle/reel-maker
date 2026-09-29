"""Regression coverage for the bounded v2 pre-publish fixes."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"reel-maker"/"scripts"))
import rm_env
import rm_render
import rm_transcribe
import reelmaker
import premium


class ReviewFixTests(unittest.TestCase):
    def test_only_uses_reel_order_and_preserves_premium(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/"source.mp4"
            source.write_bytes(b"source")
            job = root/"job"
            moments = [{"id": i, "selected": True, "headline": "Test reel", "start": 0, "end": 2}
                       for i in [1, 7, 2]]
            rm_env.write_json(job/"moments.json", {"source": {"path": str(source), "duration": 2,
                **rm_env.fingerprint(source)}, "moments": moments})
            rm_env.write_json(job/"working"/"transcript.json", {"words": [{"text": "Hello.", "start": 0, "end": 1}]})
            premium_file = job/"Reel 2 - test-reel (premium).mp4"
            premium_file.write_bytes(b"premium")
            standard = job/"Reel 2 - old.mp4"
            standard.write_bytes(b"old")
            rendered_ids = []
            def compose(clip, work, output, crop, moment, *args):
                rendered_ids.append(moment["id"])
                output.write_bytes(b"render")
                return {}
            with contextlib.ExitStack() as stack:
                for name, kwargs in [("load", {"return_value": {}}), ("cut", {"return_value": source}),
                                     ("plan", {"return_value": {}}), ("compose", {"side_effect": compose}),
                                     ("finalize_audio", {"return_value": {}}), ("contact_sheet", {})]:
                    stack.enter_context(patch("rm_render."+name, **kwargs))
                stack.enter_context(patch("rm_verify.verify", return_value={}))
                rm_render.render(job, only=["2"])
                self.assertEqual(rendered_ids, [7])
                self.assertEqual(premium_file.read_bytes(), b"premium")
                self.assertEqual((job/"working"/"old"/standard.name).read_bytes(), b"old")
                for invalid in (["7"], ["0"], ["x"], ["1", ""], []):
                    with self.subTest(invalid=invalid), self.assertRaisesRegex(rm_env.NeedsInput, "--only takes reel numbers 1..3 as shown in report.md"):
                        rm_render.render(job, only=invalid)
                rm_env.write_json(job/"working"/"renders.json", {"reels": [{"id": 7, "number": 1}]})
                with self.assertRaisesRegex(rm_env.NeedsInput, "order changed"):
                    rm_render.render(job, only=["2"])

    def test_premium_keeps_best_peak_safe_candidate(self):
        base = {"input_i": "-15.2", "input_tp": "-1.5", "input_lra": "1",
                "input_thresh": "-25", "target_offset": "0"}
        cases = [("-14.6", "-14.1", "-0.9", b"1"),
                 ("-15.8", "-16", "-1.5", b"original"),
                 ("-14.6", "-14.1", "-1.0", b"2")]
        for linear, limited, peak, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp)/"render.mp4"
                source.write_bytes(b"original")
                calls = []
                def encode(command):
                    calls.append(command)
                    self.assertEqual(command[command.index("-c:v")+1], "copy")
                    Path(command[-1]).write_bytes(str(len(calls)).encode())
                output = io.StringIO()
                with patch("premium.measure_audio", side_effect=[base, {**base, "input_i": linear},
                         {**base, "input_i": limited, "input_tp": peak}]), \
                     patch("premium.run", side_effect=encode), contextlib.redirect_stdout(output):
                    result = premium.normalize_audio(source, "ffmpeg")
                self.assertEqual(result.read_bytes(), expected)
                self.assertEqual(output.getvalue().count("target -14"), int(expected != b"2"))

    def test_make_forwards_backend_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, job = Path(tmp)/"source.mp4", Path(tmp)/"job"
            with patch("reelmaker.source_job", return_value=job), patch("rm_transcribe.transcribe") as transcribe:
                code = reelmaker.main(["make", str(source), "--out", str(job), "--backend", "faster",
                                       "--model", "medium", "--stop-after", "transcribe"])
            self.assertEqual(code, 0)
            transcribe.assert_called_once_with(source, job, backend="faster", model="medium", transcript=None)

    def test_missing_faster_backend_exits_two_with_fix(self):
        for command in ("make", "transcribe"):
            with self.subTest(command=command):
                self.check_missing_faster_backend(command)

    def check_missing_faster_backend(self, command):
        with tempfile.TemporaryDirectory() as tmp:
            source, job = Path(tmp)/"source.mp4", Path(tmp)/"job"
            source.write_bytes(b"source")
            output = io.StringIO()
            with patch("rm_transcribe.home", return_value=Path(tmp)/"home"), \
                 patch("rm_transcribe.probe", return_value={"has_audio": True}), \
                 patch("rm_transcribe.available", return_value=False), contextlib.redirect_stdout(output):
                code = reelmaker.main([command, str(source), "--out", str(job), "--backend", "faster"])
            self.assertEqual(code, 2)
            self.assertIn("faster-whisper is not installed. Run: setup --yes --backend faster", output.getvalue())

    def test_command_echo_is_only_for_remotion_render(self):
        from types import SimpleNamespace
        for command, echoed in [(["/tools/ffmpeg", "-i", "input.mp4"], False),
                                (["npx", "--no-install", "remotion", "render", "src/index.tsx"], True)]:
            output = io.StringIO()
            process = SimpleNamespace(stdout=io.StringIO(""), wait=lambda: 0)
            with patch("premium.subprocess.Popen", return_value=process), contextlib.redirect_stdout(output):
                premium.run(command)
            self.assertEqual("Running:" in output.getvalue(), echoed)
