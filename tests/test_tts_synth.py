"""speak_text: synthesize speech to a file with the configured TTS provider (K-38).

Before this, the TTS engines in skills.voice were reachable only from the CLI voice
loop and only *played* audio, so a model could not say anything out loud and a
headless host had nothing to send. These tests pin the file-producing half
(skills.tts_synth) and the tool wrapper (skills.speak) without network access, an
audio device or any optional dependency: pyttsx3, soundfile and sounddevice are
faked or forced unimportable.
"""
import base64
import json
import os
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills import speak, tts_synth
from skills.tts_synth import (
    MAX_TEXT_CHARS,
    SynthSettings,
    TTSError,
    output_path,
    prepare_text,
    resolve_settings,
    synthesize,
)


def _fake_response(status=200, content=b"", payload=None, text=None):
    resp = types.SimpleNamespace(status_code=status, content=content, headers={})
    resp.text = text if text is not None else content.decode("utf-8", "replace")
    resp.json = lambda: payload
    return resp


def _fake_pyttsx3(write: bytes):
    """A pyttsx3 stand-in whose engine writes ``write`` to the save_to_file path on runAndWait."""
    class Engine:
        def __init__(self):
            self._pending = None

        def setProperty(self, name, value):
            pass

        def save_to_file(self, text, path):
            self._pending = path

        def runAndWait(self):
            if self._pending and write:
                Path(self._pending).write_bytes(write)

    module = types.ModuleType("pyttsx3")
    module.init = lambda *a, **k: Engine()
    return module


class _TmpDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def cfg(self, provider="system", **tts):
        tts = {"provider": provider, "output_dir": str(self.tmp / "audio"), **tts}
        return {
            "voice": {"tts": tts},
            "providers": {
                "openai": {"api_key": "sk-test", "base_url": "https://api.openai.com/v1"},
                "gemini": {"api_key": "g-test"},
                "elevenlabs": {"api_key": "el-test"},
            },
        }

    def leftovers(self):
        return [p.name for p in self.tmp.rglob("*") if p.is_file()]


class PrepareTextTests(unittest.TestCase):
    def test_empty_and_whitespace_rejected(self):
        for text in ("", "   \n\t ", None):
            with self.assertRaises(TTSError):
                prepare_text(text)

    def test_over_limit_names_limit_and_length(self):
        with self.assertRaises(TTSError) as ctx:
            prepare_text("a" * 4097)
        msg = str(ctx.exception)
        self.assertIn("4096", msg)
        self.assertIn("4097", msg)

    def test_exact_limit_accepted_and_stripped(self):
        self.assertEqual(MAX_TEXT_CHARS, 4096)
        self.assertEqual(len(prepare_text("a" * 4096)), 4096)
        self.assertEqual(prepare_text("  hi there \n"), "hi there")

    def test_custom_max_chars(self):
        cfg = {"voice": {"tts": {"provider": "system", "max_chars": 10}}}
        self.assertEqual(prepare_text("a" * 10, cfg), "a" * 10)
        with self.assertRaises(TTSError) as ctx:
            prepare_text("a" * 11, cfg)
        self.assertIn("10", str(ctx.exception))
        self.assertIn("11", str(ctx.exception))


class ResolveSettingsTests(unittest.TestCase):
    def test_nested_config_wins_over_legacy(self):
        cfg = {"voice": {"use_kokoro": True, "tts_voice": "af_bella",
                         "tts": {"provider": "openai", "voice": "nova", "model": "tts-1-hd"}}}
        s = resolve_settings(cfg)
        self.assertEqual((s.provider, s.voice, s.model), ("openai", "nova", "tts-1-hd"))

    def test_legacy_flat_keys_resolve(self):
        s = resolve_settings({"voice": {"use_kokoro": True, "tts_voice": "af_bella"}})
        self.assertEqual((s.provider, s.voice), ("kokoro", "af_bella"))

    def test_explicit_args_beat_config(self):
        cfg = {"voice": {"tts": {"provider": "openai", "voice": "nova"}}}
        s = resolve_settings(cfg, provider="gemini", voice="Puck", model="m1", output_dir="/x/y")
        self.assertEqual((s.provider, s.voice, s.model, s.output_dir),
                         ("gemini", "Puck", "m1", Path("/x/y")))

    def test_provider_override_uses_that_providers_defaults(self):
        cfg = {"voice": {"tts": {"provider": "kokoro", "voice": "af_bella"}}}
        s = resolve_settings(cfg, provider="openai")
        self.assertEqual((s.voice, s.model), ("alloy", "tts-1"))

    def test_kokoro_default_voice_not_sent_to_cloud_provider(self):
        s = resolve_settings({"voice": {"tts": {"provider": "openai", "voice": "af_sky"}}})
        self.assertEqual(s.voice, "alloy")

    def test_default_output_dir(self):
        s = resolve_settings({})
        self.assertEqual(s.output_dir, Path.home() / ".Koza" / "audio")
        self.assertEqual(s.provider, "system")
        s = resolve_settings({"voice": {"tts": {"output_dir": "~/clips"}}})
        self.assertEqual(s.output_dir, Path.home() / "clips")


class OutputPathTests(_TmpDirCase):
    def settings(self, provider):
        return SynthSettings(provider=provider, voice="", model="", output_dir=self.tmp / "audio")

    def test_auto_name_in_output_dir_with_provider_suffix(self):
        p = output_path("hi", self.settings("openai"))
        self.assertEqual(p.parent, self.tmp / "audio")
        self.assertTrue(p.parent.is_dir())
        self.assertRegex(p.name, r"^speech-\d{8}-\d{6}-[0-9a-f]{4}\.mp3$")
        self.assertTrue(output_path("hi", self.settings("gemini")).name.endswith(".wav"))

    def test_same_second_calls_do_not_collide(self):
        names = {output_path("hi", self.settings("system")).name for _ in range(20)}
        self.assertEqual(len(names), 20)

    def test_save_to_without_suffix_gets_provider_suffix_and_parents(self):
        target = self.tmp / "nested" / "deeper" / "clip"
        p = output_path("hi", self.settings("openai"), save_to=str(target))
        self.assertEqual(p, target.with_name("clip.mp3"))
        self.assertTrue(p.parent.is_dir())

    def test_system_forces_wav(self):
        p = output_path("hi", self.settings("system"), save_to=str(self.tmp / "clip.mp3"))
        self.assertEqual(p.suffix, ".wav")

    def test_save_to_expands_user(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            p = output_path("hi", self.settings("system"), save_to="~/out/x.wav")
        self.assertEqual(p, self.tmp / "out" / "x.wav")


class SystemProviderTests(_TmpDirCase):
    def test_writes_wav(self):
        with mock.patch.dict(sys.modules, {"pyttsx3": _fake_pyttsx3(b"RIFF....WAVEfake")}):
            result = synthesize("hello", self.cfg("system"))
        self.assertTrue(Path(result.path).is_file())
        self.assertGreater(result.bytes, 0)
        self.assertEqual(result.format, "wav")
        self.assertTrue(result.path.endswith(".wav"))
        self.assertEqual(self.leftovers(), [Path(result.path).name])

    def test_missing_pyttsx3(self):
        with mock.patch.dict(sys.modules, {"pyttsx3": None}), self.assertRaises(TTSError) as ctx:
            synthesize("hello", self.cfg("system"))
        self.assertIn("pip install pyttsx3", str(ctx.exception))
        self.assertEqual(self.leftovers(), [])

    def test_engine_writes_nothing(self):
        with mock.patch.dict(sys.modules, {"pyttsx3": _fake_pyttsx3(b"")}), self.assertRaises(TTSError) as ctx:
            synthesize("hello", self.cfg("system"))
        self.assertIn("no audio", str(ctx.exception))
        self.assertEqual(self.leftovers(), [])


class OpenAIProviderTests(_TmpDirCase):
    def test_writes_mp3_with_expected_request(self):
        with mock.patch("requests.post", return_value=_fake_response(content=b"ID3fake-mp3")) as post:
            result = synthesize("hello world", self.cfg("openai"))
        self.assertEqual(result.format, "mp3")
        self.assertEqual(Path(result.path).read_bytes(), b"ID3fake-mp3")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.openai.com/v1/audio/speech")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(kwargs["json"]["model"], "tts-1")
        self.assertEqual(kwargs["json"]["voice"], "alloy")
        self.assertEqual(kwargs["json"]["input"], "hello world")
        self.assertEqual(kwargs["json"]["response_format"], "mp3")
        self.assertEqual(kwargs["timeout"], 120)

    def test_http_error_names_status_and_leaves_no_file(self):
        with mock.patch("requests.post", return_value=_fake_response(400, b'{"error":"bad voice"}')), self.assertRaises(TTSError) as ctx:
            synthesize("hello", self.cfg("openai"))
        self.assertIn("400", str(ctx.exception))
        self.assertEqual(self.leftovers(), [])

    def test_missing_api_key(self):
        cfg = self.cfg("openai")
        cfg["providers"]["openai"]["api_key"] = ""
        with mock.patch("requests.post") as post, self.assertRaises(TTSError) as ctx:
            synthesize("hello", cfg)
        post.assert_not_called()
        self.assertIn("providers.openai.api_key", str(ctx.exception))

    def test_oversized_body_refused(self):
        resp = _fake_response(content=b"ID3")
        resp.headers = {"Content-Length": str(60 * 1024 * 1024)}
        with mock.patch("requests.post", return_value=resp), self.assertRaises(TTSError) as ctx:
            synthesize("hello", self.cfg("openai"))
        self.assertIn("50 MB", str(ctx.exception))
        self.assertEqual(self.leftovers(), [])


class PcmProviderTests(_TmpDirCase):
    PCM = b"\x00\x01" * 2400  # 0.1 s of 16-bit mono at 24 kHz

    def assert_wav(self, path, rate=24000):
        with wave.open(path, "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), rate)
            self.assertEqual(wf.readframes(wf.getnframes()), self.PCM)

    def test_gemini_l16_wrapped_in_wav(self):
        payload = {"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "audio/L16;codec=pcm;rate=24000",
            "data": base64.b64encode(self.PCM).decode("ascii"),
        }}]}}]}
        with mock.patch("requests.post", return_value=_fake_response(content=b"{}", payload=payload)) as post:
            result = synthesize("hello", self.cfg("gemini"))
        self.assertEqual(result.format, "wav")
        self.assert_wav(result.path)
        self.assertEqual(post.call_args.kwargs["params"], {"key": "g-test"})
        self.assertEqual(
            post.call_args.kwargs["json"]["generationConfig"]["speechConfig"]["voiceConfig"]
            ["prebuiltVoiceConfig"]["voiceName"], "Kore")

    def test_gemini_without_audio_fails_cleanly(self):
        with mock.patch("requests.post", return_value=_fake_response(content=b"{}", payload={"candidates": []})), self.assertRaises(TTSError):
            synthesize("hello", self.cfg("gemini"))
        self.assertEqual(self.leftovers(), [])

    def test_elevenlabs_pcm_wrapped_in_wav(self):
        with mock.patch("requests.post", return_value=_fake_response(content=self.PCM)) as post:
            result = synthesize("hello", self.cfg("elevenlabs"))
        self.assert_wav(result.path)
        args, kwargs = post.call_args
        self.assertIn("/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM", args[0])
        self.assertIn("output_format=pcm_24000", args[0])
        self.assertEqual(kwargs["headers"]["xi-api-key"], "el-test")
        self.assertEqual(kwargs["json"]["text"], "hello")


class ProviderSelectionTests(_TmpDirCase):
    def test_skip_and_unknown(self):
        with self.assertRaises(TTSError) as ctx:
            synthesize("hello", self.cfg("skip"))
        self.assertIn("disabled", str(ctx.exception))
        with self.assertRaises(TTSError) as ctx:
            synthesize("hello", self.cfg("system"), provider="espeakish")
        self.assertIn("elevenlabs", str(ctx.exception))

    def test_failed_synthesis_keeps_existing_file(self):
        existing = self.tmp / "keep.mp3"
        existing.write_bytes(b"old audio")
        with mock.patch("requests.post", return_value=_fake_response(500, b"boom")), self.assertRaises(TTSError):
            synthesize("hello", self.cfg("openai"), save_to=str(existing))
        self.assertEqual(existing.read_bytes(), b"old audio")
        self.assertEqual(self.leftovers(), ["keep.mp3"])


class SpeakToolTests(_TmpDirCase):
    def fake_result(self):
        audio = self.tmp / "out.wav"
        audio.write_bytes(b"RIFF")
        return tts_synth.SynthResult(path=str(audio), provider="system", voice="",
                                     format="wav", bytes=4)

    def test_ok_payload(self):
        with mock.patch("skills.speak.synthesize", return_value=self.fake_result()) as synth:
            out = json.loads(speak.speak_text("  hello  ", provider="system"))
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["provider"], "system")
        self.assertEqual(out["chars"], 5)
        self.assertFalse(out["played"])
        self.assertNotIn("play_error", out)
        self.assertTrue(out["path"].endswith("out.wav"))
        self.assertEqual(synth.call_args.kwargs["provider"], "system")
        self.assertIsNone(synth.call_args.kwargs["save_to"])

    def test_play_without_audio_libs_still_ok(self):
        with mock.patch("skills.speak.synthesize", return_value=self.fake_result()), \
                mock.patch.dict(sys.modules, {"soundfile": None, "sounddevice": None}):
            out = json.loads(speak.speak_text("hello", play=True))
        self.assertEqual(out["status"], "ok")
        self.assertFalse(out["played"])
        self.assertTrue(out["play_error"])

    def test_play_success(self):
        sd = types.ModuleType("sounddevice")
        sd.play = mock.Mock()
        sd.wait = mock.Mock()
        sf = types.ModuleType("soundfile")
        sf.read = mock.Mock(return_value=([0.0], 24000))
        with mock.patch("skills.speak.synthesize", return_value=self.fake_result()), \
                mock.patch.dict(sys.modules, {"soundfile": sf, "sounddevice": sd}):
            out = json.loads(speak.speak_text("hello", play=True))
        self.assertTrue(out["played"])
        sd.play.assert_called_once()
        sd.wait.assert_called_once()

    def test_errors_are_json(self):
        out = json.loads(speak.speak_text(""))
        self.assertEqual(out["status"], "error")
        self.assertIn("empty", out["error"])
        out = json.loads(speak.speak_text("hello", provider="nope"))
        self.assertEqual(out["status"], "error")
        self.assertIn("Unknown TTS provider", out["error"])

    def test_unexpected_exception_is_json(self):
        with mock.patch("skills.speak.synthesize", side_effect=ValueError("kaboom")):
            out = json.loads(speak.speak_text("hello"))
        self.assertEqual(out, {"status": "error", "error": "kaboom"})


class WiringTests(unittest.TestCase):
    def test_registry(self):
        from tools.registry import ALL_HANDLERS, ALL_TOOLS, STATIC_SKILL_MODULES
        self.assertIs(ALL_HANDLERS["speak_text"], speak.speak_text)
        names = [t["function"]["name"] for t in ALL_TOOLS]
        self.assertEqual(names.count("speak_text"), 1)
        self.assertIs(STATIC_SKILL_MODULES["speak"], speak)

    def test_capabilities(self):
        from tools.capabilities import resolve_capabilities
        self.assertEqual(resolve_capabilities(["voice"]), ["speak_text"])

    def test_permissions_and_label(self):
        from cli import permissions
        from cli.ui._stream_renderer import StreamRenderer
        self.assertIn("speak_text", permissions.SAFE_TOOLS)
        self.assertIn("speak_text", StreamRenderer._TOOL_LABELS)

    def test_not_idempotent(self):
        import core
        self.assertNotIn("speak_text", getattr(core, "IDEMPOTENT_TOOLS", set()))

    def test_reachable_through_dynamic_tool_selection(self):
        import core
        from utils import system_utils
        for groups in (core._TOOL_GROUPS, system_utils._TOOL_GROUPS):
            self.assertIn("speak_text", groups["media"])

    def test_config_defaults_survive_merge(self):
        import config
        for body in ("voice:\n  tts:\n    provider: openai\n",
                     "voice:\n  enabled: true\n"):
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "config.yaml"
                path.write_text(body)
                with mock.patch.object(config, "CONFIG_PATH", path):
                    config.clear_config_cache()
                    try:
                        tts = config.load_config()["voice"]["tts"]
                    finally:
                        config.clear_config_cache()
            self.assertEqual(tts["max_chars"], 4096)
            self.assertEqual(tts["output_dir"], "")


if __name__ == "__main__":
    unittest.main()
