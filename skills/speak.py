"""
Speak — synthesize text to an audio file with the configured TTS provider (``speak_text``).

The synthesis lives in ``skills.tts_synth``; this module only exposes the tool and
the optional local playback of the written file.
"""
import json

from skills.tts_synth import MAX_TEXT_CHARS, PROVIDERS, synthesize


def _play_file(path: str) -> None:
    import sounddevice as sd
    import soundfile as sf
    samples, sr = sf.read(path, dtype="float32")
    sd.play(samples, sr)
    sd.wait()


def speak_text(text: str, save_to: str = "", play: bool = False,
               provider: str = "", voice: str = "") -> str:
    """Synthesize ``text`` to an audio file; optionally play it (JSON result)."""
    try:
        from config import load_config
        cfg = load_config()
    except Exception:  # noqa: BLE001 - a broken config falls back to defaults
        cfg = {}
    try:
        result = synthesize(text, cfg, save_to=save_to or None,
                            provider=provider or None, voice=voice or None)
    except Exception as e:  # noqa: BLE001 - the tool reports errors as JSON, never raises
        return json.dumps({"status": "error", "error": str(e) or e.__class__.__name__})

    payload = {
        "status": "ok",
        "path": result.path,
        "provider": result.provider,
        "voice": result.voice,
        "format": result.format,
        "bytes": result.bytes,
        "chars": len(str(text).strip()),
        "played": False,
    }
    if play:
        try:
            _play_file(result.path)
            payload["played"] = True
        except Exception as e:  # noqa: BLE001 - the file is the deliverable; playback is optional
            payload["play_error"] = f"{e.__class__.__name__}: {e}"
    return json.dumps(payload)


# ─── Registry ─────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "speak_text",
        "description": (
            "Turn text into speech with the configured TTS provider and save it as an audio "
            "file (wav, or mp3 for OpenAI). The result is JSON: {status, path, provider, voice, "
            "format, bytes, chars, played, play_error?} or {status: \"error\", error}. The file "
            "at `path` is the deliverable — attach or send it when the user wants audio. `play` "
            "also plays it on this machine's speakers; it needs a local audio device, so leave it "
            "false on servers and headless hosts. `provider` and `voice` are optional overrides "
            "of the configured ones. Text is limited per call (voice.tts.max_chars, default "
            f"{MAX_TEXT_CHARS} characters) and is never truncated — split longer text into several "
            "calls. Never installs missing dependencies; the error names what to install. Cloud "
            "providers (openai, gemini, elevenlabs) are billed per character."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to speak."},
                "save_to": {
                    "type": "string",
                    "description": "Optional output file path. Default: an auto-generated name in "
                                   "the configured audio directory (~/.Koza/audio).",
                },
                "play": {"type": "boolean", "default": False,
                         "description": "Also play the file on the local audio device."},
                "provider": {"type": "string", "enum": list(PROVIDERS),
                             "description": "Optional TTS provider override."},
                "voice": {"type": "string",
                          "description": "Optional provider-specific voice id/name override."},
            },
            "required": ["text"],
        },
    },
]

HANDLERS = {
    "speak_text": speak_text,
}
