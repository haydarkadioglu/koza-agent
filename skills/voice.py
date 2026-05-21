"""Voice module — always-on VAD loop, STT (faster-whisper), TTS (pyttsx3 / Kokoro).

Design:
- No Enter-to-speak: mic is always open, VAD detects speech automatically.
- TTS: pyttsx3 (system, zero-download) as default; Kokoro ONNX as optional upgrade.
- All heavy imports are lazy — nothing loads unless voice is actually used.
"""
import os
import sys
import tempfile
from pathlib import Path

VOICE_MODELS_DIR = Path.home() / ".Koza" / "voice_models"
SAMPLE_RATE   = 16000
CHUNK_DUR     = 0.05          # 50 ms chunks for snappy VAD response
SPEECH_THRESH = 0.018         # RMS to start recording
SILENCE_THRESH = 0.010        # RMS to consider silence
SILENCE_SECS  = 1.2           # seconds of silence before cut-off
PRE_ROLL_CHUNKS = 4           # chunks to keep before speech starts (80 ms)

_stt_model = None
_tts_engine = None            # pyttsx3 instance (reused across calls)


# ── Feature flag ──────────────────────────────────────────────────────────────

def is_voice_enabled(cfg: dict) -> bool:
    return cfg.get("voice", {}).get("enabled", False)


# ── Dependency installer ──────────────────────────────────────────────────────

def ensure_deps() -> None:
    _DEPS = [
        ("faster_whisper", "faster-whisper"),
        ("sounddevice",    "sounddevice"),
        ("soundfile",      "soundfile"),
        ("numpy",          "numpy"),
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


# ── STT model ─────────────────────────────────────────────────────────────────

def _get_stt_model():
    global _stt_model
    if _stt_model is None:
        from faster_whisper import WhisperModel
        sys.stdout.write("  🔄  Loading Whisper base (~74 MB first run)…")
        sys.stdout.flush()
        _stt_model = WhisperModel("base", device="cpu", compute_type="int8")
        sys.stdout.write("\r  ✓  STT ready.                              \n")
        sys.stdout.flush()
    return _stt_model


# ── TTS ───────────────────────────────────────────────────────────────────────

def _try_kokoro_install() -> bool:
    """Try to install kokoro-onnx + download models. Returns True on success."""
    try:
        import subprocess
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "kokoro-onnx",
             "huggingface-hub", "--quiet"],
            check=True,
        )
        # Find actual files in the repo
        from huggingface_hub import list_repo_files, hf_hub_download
        VOICE_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        files = list(list_repo_files("hexgrad/Kokoro-82M"))
        onnx_file   = next((f for f in files if f.endswith(".onnx")), None)
        voices_file = next((f for f in files if f.endswith(".bin")), None)
        if not onnx_file or not voices_file:
            return False
        hf_hub_download("hexgrad/Kokoro-82M", onnx_file,
                        local_dir=str(VOICE_MODELS_DIR))
        hf_hub_download("hexgrad/Kokoro-82M", voices_file,
                        local_dir=str(VOICE_MODELS_DIR))
        return True
    except Exception as e:
        print(f"\n  ⚠  Kokoro install failed: {e}")
        return False


def tts_speak(text: str, voice: str = "af_sky", output_device=None,
              use_kokoro: bool = False) -> None:
    """Speak text. Uses pyttsx3 (system, always works) by default.
    Set use_kokoro=True to attempt Kokoro ONNX (higher quality).
    """
    if use_kokoro:
        try:
            import sounddevice as sd
            from kokoro_onnx import Kokoro
            VOICE_MODELS_DIR.mkdir(parents=True, exist_ok=True)
            # Find downloaded onnx/bin files
            onnx_files = list(VOICE_MODELS_DIR.glob("*.onnx"))
            bin_files  = list(VOICE_MODELS_DIR.glob("*.bin"))
            if onnx_files and bin_files:
                kok = Kokoro(str(onnx_files[0]), str(bin_files[0]))
                samples, sr = kok.create(text, voice=voice, speed=1.0, lang="en-us")
                sd.play(samples, sr, device=output_device)
                sd.wait()
                return
        except Exception as e:
            sys.stdout.write(f"\r  ⚠  Kokoro TTS: {e} — using system TTS\n")

    # pyttsx3 — system TTS, no download, works on Windows/Linux/macOS
    global _tts_engine
    try:
        import pyttsx3
        if _tts_engine is None:
            _tts_engine = pyttsx3.init()
        _tts_engine.say(text)
        _tts_engine.runAndWait()
    except Exception:
        pass


# ── VAD helpers ───────────────────────────────────────────────────────────────

def _vu_bar(amp: float, width: int = 16) -> str:
    bars = min(width, int(amp / 0.003))
    return "█" * bars + "░" * (width - bars)


def _transcribe(audio_chunks, language=None) -> str:
    import numpy as np
    import soundfile as sf
    audio = np.concatenate(audio_chunks, axis=0).squeeze()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    sf.write(tmp.name, audio, SAMPLE_RATE)
    try:
        model = _get_stt_model()
        kw = {"beam_size": 5}
        if language:
            kw["language"] = language
        segments, _ = model.transcribe(tmp.name, **kw)
        return " ".join(s.text.strip() for s in segments).strip()
    finally:
        os.unlink(tmp.name)


# ── Always-on VAD listen loop (generator) ────────────────────────────────────

def vad_listen_loop(
    input_device=None,
    language: str | None = None,
    stop_event=None,       # threading.Event — set to break the loop
):
    """
    Generator that continuously listens and yields transcribed utterances.

    Yields str (transcribed text) whenever speech is detected and ends.
    Caller can display real-time status via the _status dict yielded between
    utterances (yield type is dict with key 'status').
    """
    import numpy as np
    import sounddevice as sd

    chunk_size    = int(SAMPLE_RATE * CHUNK_DUR)
    silent_needed = int(SILENCE_SECS / CHUNK_DUR)

    state         = "idle"     # idle | recording | silence
    chunks: list  = []
    pre_roll: list = []        # ring-buffer of last PRE_ROLL_CHUNKS chunks
    silent_count  = 0

    def _show(msg: str):
        sys.stdout.write(f"\r  {msg:<70}")
        sys.stdout.flush()

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        device=input_device) as stream:
        while not (stop_event and stop_event.is_set()):
            data, _ = stream.read(chunk_size)
            amp = float(np.abs(data).mean())

            if state == "idle":
                # Keep a small pre-roll buffer
                pre_roll.append(data.copy())
                if len(pre_roll) > PRE_ROLL_CHUNKS:
                    pre_roll.pop(0)
                _show(f"🟢  Listening…  [{_vu_bar(amp)}]")

                if amp > SPEECH_THRESH:
                    state = "recording"
                    chunks = list(pre_roll)   # include pre-roll
                    silent_count = 0

            elif state == "recording":
                chunks.append(data.copy())
                if amp > SILENCE_THRESH:
                    silent_count = 0
                    _show(f"🔴  Recording   [{_vu_bar(amp)}]")
                else:
                    silent_count += 1
                    remaining = (silent_needed - silent_count) * CHUNK_DUR
                    _show(f"⏸   Silence…    [{_vu_bar(amp)}]  cut in {remaining:.1f}s")
                    if silent_count >= silent_needed:
                        state = "idle"
                        pre_roll.clear()
                        sys.stdout.write("\r" + " " * 72 + "\r")
                        sys.stdout.flush()
                        _show("⚙   Transcribing…")
                        sys.stdout.flush()
                        text = _transcribe(chunks, language=language)
                        chunks = []
                        sys.stdout.write("\r" + " " * 72 + "\r")
                        sys.stdout.flush()
                        if text:
                            yield text

