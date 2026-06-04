"""Voice module — always-on VAD loop, STT and TTS provider dispatch.

Design:
- No Enter-to-speak: mic is always open, VAD detects speech automatically.
- STT: local faster-whisper or OpenAI transcription.
- TTS: pyttsx3 (system), Kokoro ONNX, or OpenAI speech.
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
_stt_model_key = ""
_tts_engine = None            # pyttsx3 instance (reused across calls)


# ── Feature flag ──────────────────────────────────────────────────────────────

def is_voice_enabled(cfg: dict) -> bool:
    return cfg.get("voice", {}).get("enabled", False)


# ── Dependency installer ──────────────────────────────────────────────────────

def _pip_install_deps(deps: list[tuple[str, str]]) -> None:
    for mod, pkg in deps:
        try:
            __import__(mod)
        except ImportError:
            print(f"  Installing {pkg}…")
            import subprocess
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                check=True,
            )


def ensure_audio_deps() -> None:
    _pip_install_deps([
        ("sounddevice", "sounddevice"),
        ("soundfile", "soundfile"),
        ("numpy", "numpy"),
    ])


def ensure_local_stt_deps() -> None:
    ensure_audio_deps()
    _pip_install_deps([("faster_whisper", "faster-whisper")])


def ensure_deps() -> None:
    """Backward-compatible installer for local voice mode."""
    _DEPS = [
        ("faster_whisper", "faster-whisper"),
        ("sounddevice",    "sounddevice"),
        ("soundfile",      "soundfile"),
        ("numpy",          "numpy"),
    ]
    _pip_install_deps(_DEPS)


# ── STT model ─────────────────────────────────────────────────────────────────

def _get_stt_model(model_name: str = "base"):
    global _stt_model, _stt_model_key
    model_name = model_name or "base"
    if _stt_model is None or _stt_model_key != model_name:
        from faster_whisper import WhisperModel
        sys.stdout.write(f"  🔄  Loading Whisper {model_name}…")
        sys.stdout.flush()
        _stt_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        _stt_model_key = model_name
        sys.stdout.write("\r  ✓  STT ready.                              \n")
        sys.stdout.flush()
    return _stt_model


def normalize_voice_config(cfg: dict) -> dict:
    """Return nested voice config while accepting legacy flat keys."""
    voice = dict((cfg or {}).get("voice", {}) or {})
    stt = dict(voice.get("stt") or {})
    tts = dict(voice.get("tts") or {})

    if not stt:
        stt = {
            "provider": "local_whisper",
            "model": voice.get("stt_model", "base"),
            "language": voice.get("language", ""),
        }
    else:
        stt.setdefault("provider", "local_whisper")
        stt.setdefault("model", voice.get("stt_model", "base"))
        stt.setdefault("language", voice.get("language", ""))

    if not tts:
        use_kokoro = bool(voice.get("use_kokoro", False))
        tts = {
            "provider": "kokoro" if use_kokoro else "system",
            "model": "",
            "voice": voice.get("tts_voice", "af_sky"),
        }
    else:
        tts.setdefault("provider", "system")
        tts.setdefault("model", "")
        tts.setdefault("voice", voice.get("tts_voice", "af_sky"))

    voice["stt"] = stt
    voice["tts"] = tts
    voice.setdefault("input_device", None)
    voice.setdefault("output_device", None)
    return voice


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


def _openai_api_key(cfg: dict) -> str:
    return (cfg or {}).get("providers", {}).get("openai", {}).get("api_key", "").strip()


def _transcribe_openai_file(path: str, cfg: dict, stt_cfg: dict) -> str:
    api_key = _openai_api_key(cfg)
    if not api_key:
        raise RuntimeError("OpenAI STT requires providers.openai.api_key. Run: koza setup")
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=cfg.get("providers", {}).get("openai", {}).get("base_url", "https://api.openai.com/v1"))
    kwargs = {"model": stt_cfg.get("model") or "whisper-1"}
    language = stt_cfg.get("language") or ""
    if language:
        kwargs["language"] = language
    with open(path, "rb") as fh:
        result = client.audio.transcriptions.create(file=fh, **kwargs)
    return getattr(result, "text", "") or str(result)


def transcribe_audio_file(path: str, cfg: dict) -> str:
    voice_cfg = normalize_voice_config(cfg)
    stt_cfg = voice_cfg.get("stt", {})
    provider = stt_cfg.get("provider", "local_whisper")
    if provider == "skip":
        raise RuntimeError("STT provider is not configured. Run: koza voice setup")
    if provider == "openai":
        return _transcribe_openai_file(path, cfg, stt_cfg)

    model = _get_stt_model(stt_cfg.get("model", "base"))
    kw = {"beam_size": 5}
    language = stt_cfg.get("language") or ""
    if language:
        kw["language"] = language
    segments, _ = model.transcribe(path, **kw)
    return " ".join(s.text.strip() for s in segments).strip()


def tts_speak_configured(text: str, cfg: dict, output_device=None) -> None:
    voice_cfg = normalize_voice_config(cfg)
    tts_cfg = voice_cfg.get("tts", {})
    provider = tts_cfg.get("provider", "system")
    voice = tts_cfg.get("voice", "af_sky")

    if provider == "skip":
        return
    if provider == "kokoro":
        tts_speak(text, voice=voice, output_device=output_device, use_kokoro=True)
        return
    if provider == "openai":
        api_key = _openai_api_key(cfg)
        if not api_key:
            raise RuntimeError("OpenAI TTS requires providers.openai.api_key. Run: koza setup")
        import sounddevice as sd
        import soundfile as sf
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=cfg.get("providers", {}).get("openai", {}).get("base_url", "https://api.openai.com/v1"))
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            response = client.audio.speech.create(
                model=tts_cfg.get("model") or "tts-1",
                voice=voice or "alloy",
                input=text,
                response_format="wav",
            )
            response.write_to_file(tmp.name)
            samples, sr = sf.read(tmp.name, dtype="float32")
            sd.play(samples, sr, device=output_device)
            sd.wait()
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
        return

    tts_speak(text, voice=voice, output_device=output_device, use_kokoro=False)


# ── VAD helpers ───────────────────────────────────────────────────────────────

def _vu_bar(amp: float, width: int = 16) -> str:
    bars = min(width, int(amp / 0.003))
    return "█" * bars + "░" * (width - bars)


def _transcribe(audio_chunks, language=None, cfg: dict | None = None) -> str:
    import numpy as np
    import soundfile as sf
    audio = np.concatenate(audio_chunks, axis=0).squeeze()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    sf.write(tmp.name, audio, SAMPLE_RATE)
    try:
        if cfg:
            return transcribe_audio_file(tmp.name, cfg)
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
    cfg: dict | None = None,
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
                        text = _transcribe(chunks, language=language, cfg=cfg)
                        chunks = []
                        sys.stdout.write("\r" + " " * 72 + "\r")
                        sys.stdout.flush()
                        if text:
                            yield text

