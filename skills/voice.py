"""Voice module — STT (faster-whisper / whisper-base) + TTS (kokoro-onnx).

All imports are lazy; nothing is loaded unless voice is actually used.
Models are downloaded once to ~/.Koza/voice_models/ and cached.
"""
import os
import sys
import tempfile
from pathlib import Path

VOICE_MODELS_DIR = Path.home() / ".Koza" / "voice_models"
SAMPLE_RATE      = 16000
SILENCE_THRESH   = 0.015   # RMS amplitude threshold
SILENCE_SECS     = 1.5     # seconds of silence before recording stops

_stt_model = None
_tts_model = None


# ── Feature flag ──────────────────────────────────────────────────────────────

def is_voice_enabled(cfg: dict) -> bool:
    return cfg.get("voice", {}).get("enabled", False)


# ── Dependency installer ──────────────────────────────────────────────────────

def ensure_deps() -> None:
    """pip-install all voice-related packages if not already present."""
    _DEPS = [
        ("faster_whisper",  "faster-whisper"),
        ("kokoro_onnx",     "kokoro-onnx"),
        ("sounddevice",     "sounddevice"),
        ("soundfile",       "soundfile"),
        ("numpy",           "numpy"),
        ("huggingface_hub", "huggingface-hub"),
    ]
    for mod, pkg in _DEPS:
        try:
            __import__(mod)
        except ImportError:
            print(f"  Installing {pkg}…")
            import subprocess
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                check=True,
            )


# ── Model loaders (lazy singletons) ──────────────────────────────────────────

def _get_stt_model():
    global _stt_model
    if _stt_model is None:
        from faster_whisper import WhisperModel
        print("  🔄  Loading Whisper base model (first run downloads ~74 MB)…")
        _stt_model = WhisperModel("base", device="cpu", compute_type="int8")
        print("  ✓  STT model ready.")
    return _stt_model


def _get_tts_model():
    """Load Kokoro ONNX model. Downloads files on first run (~82 MB total)."""
    global _tts_model
    if _tts_model is None:
        VOICE_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        onnx_path   = VOICE_MODELS_DIR / "kokoro-v0_19.onnx"
        voices_path = VOICE_MODELS_DIR / "voices.bin"

        if not onnx_path.exists() or not voices_path.exists():
            print("  🔄  Downloading Kokoro TTS models (~82 MB, one-time)…")
            try:
                from huggingface_hub import hf_hub_download
                onnx_path = Path(hf_hub_download(
                    "hexgrad/Kokoro-82M", "kokoro-v0_19.onnx",
                    local_dir=str(VOICE_MODELS_DIR),
                ))
                voices_path = Path(hf_hub_download(
                    "hexgrad/Kokoro-82M", "voices.bin",
                    local_dir=str(VOICE_MODELS_DIR),
                ))
                print("  ✓  TTS models downloaded.")
            except Exception as e:
                print(f"  ⚠  Could not download Kokoro models: {e}")
                return None

        from kokoro_onnx import Kokoro
        _tts_model = Kokoro(str(onnx_path), str(voices_path))
        print("  ✓  TTS model ready.")
    return _tts_model


# ── STT ───────────────────────────────────────────────────────────────────────

def stt_listen(max_seconds: int = 15, language: str | None = None) -> str:
    """Record from microphone until silence, return transcribed text.

    Silence detection: stops after SILENCE_SECS of audio below SILENCE_THRESH.
    """
    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    chunk_dur  = 0.1
    chunk_size = int(SAMPLE_RATE * chunk_dur)
    silent_needed = int(SILENCE_SECS / chunk_dur)
    max_chunks    = int(max_seconds / chunk_dur)

    chunks: list = []
    silent_count  = 0
    speaking      = False

    print("  🎤  Listening… (speak now, silence stops recording)")

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
        for _ in range(max_chunks):
            data, _ = stream.read(chunk_size)
            amplitude = float(np.abs(data).mean())
            chunks.append(data.copy())

            if amplitude > SILENCE_THRESH:
                speaking = True
                silent_count = 0
            elif speaking:
                silent_count += 1
                if silent_count >= silent_needed:
                    break

    if not chunks or not speaking:
        return ""

    audio = np.concatenate(chunks, axis=0).squeeze()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    sf.write(tmp.name, audio, SAMPLE_RATE)

    try:
        model  = _get_stt_model()
        kwargs = {"beam_size": 5}
        if language:
            kwargs["language"] = language
        segments, _ = model.transcribe(tmp.name, **kwargs)
        text = " ".join(s.text.strip() for s in segments)
    finally:
        os.unlink(tmp.name)

    return text.strip()


# ── TTS ───────────────────────────────────────────────────────────────────────

def tts_speak(text: str, voice: str = "af_sky") -> None:
    """Synthesize speech and play via sounddevice. Falls back to pyttsx3."""
    import sounddevice as sd

    kokoro = _get_tts_model()
    if kokoro is not None:
        try:
            samples, sample_rate = kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
            sd.play(samples, sample_rate)
            sd.wait()
            return
        except Exception as e:
            print(f"  ⚠  Kokoro TTS error: {e} — falling back to system TTS")

    # Fallback: system TTS via pyttsx3
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    except Exception:
        pass  # text is already displayed — silent fail is acceptable
