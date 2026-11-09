"""
TTS synthesis to a file — the engine behind the ``speak_text`` tool.

``skills.voice`` plays audio on the local output device and returns nothing; a tool
needs a deliverable the model can hand on, so every provider here writes an audio
file and reports its path. Config resolution is shared with ``skills.voice``
(``normalize_voice_config``). Optional dependencies (pyttsx3, kokoro_onnx,
soundfile) are imported lazily and never installed at runtime — a missing one is
reported with the install command instead.
"""
import base64
import logging
import os
import re
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from skills.voice import VOICE_MODELS_DIR, normalize_voice_config

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 4096                       # default, overridable by voice.tts.max_chars
DEFAULT_OUTPUT_DIR = Path.home() / ".Koza" / "audio"   # overridable by voice.tts.output_dir
HTTP_TIMEOUT = 120
MAX_RESPONSE_BYTES = 50 * 1024 * 1024

PROVIDERS = ("system", "kokoro", "openai", "gemini", "elevenlabs")
PROVIDER_FORMATS = {"system": "wav", "kokoro": "wav", "openai": "mp3",
                    "gemini": "wav", "elevenlabs": "wav"}
_DEFAULT_VOICES = {"system": "", "kokoro": "af_sky", "openai": "alloy",
                   "gemini": "Kore", "elevenlabs": "21m00Tcm4TlvDq8ikWAM"}
_DEFAULT_MODELS = {"system": "", "kokoro": "", "openai": "tts-1",
                   "gemini": "gemini-2.5-flash-preview-tts",
                   "elevenlabs": "eleven_multilingual_v2"}
# The shipped voice.tts.voice default is a Kokoro voice id; other providers reject it.
_KOKORO_DEFAULT_VOICE = "af_sky"
_AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus", ".aac"}


class TTSError(RuntimeError):
    """Synthesis failed; the message is safe to show to the model."""


@dataclass(frozen=True)
class SynthSettings:
    provider: str      # system | kokoro | openai | gemini | elevenlabs | skip
    voice: str
    model: str
    output_dir: Path


@dataclass(frozen=True)
class SynthResult:
    path: str
    provider: str
    voice: str
    format: str        # "wav" | "mp3"
    bytes: int


# ─── Settings & validation ────────────────────────────────────────────────────

def _tts_config(cfg: dict | None) -> dict:
    return normalize_voice_config(cfg or {}).get("tts", {}) or {}


def resolve_settings(cfg: dict | None = None, *, provider=None, voice=None, model=None,
                     output_dir=None) -> SynthSettings:
    """Explicit arguments beat ``voice.tts.*``, which beats the legacy flat keys."""
    tts = _tts_config(cfg)
    configured = str(tts.get("provider") or "system").strip().lower()
    chosen = str(provider or "").strip().lower() or configured
    same_provider = chosen == configured

    # A configured voice/model belongs to the configured provider; an explicit
    # provider override starts from that provider's own defaults.
    cfg_voice = str(tts.get("voice") or "") if same_provider else ""
    if cfg_voice == _KOKORO_DEFAULT_VOICE and chosen not in ("kokoro",):
        cfg_voice = ""
    cfg_model = str(tts.get("model") or "") if same_provider else ""

    resolved_voice = str(voice or "").strip() or cfg_voice or _DEFAULT_VOICES.get(chosen, "")
    resolved_model = str(model or "").strip() or cfg_model or _DEFAULT_MODELS.get(chosen, "")

    out = output_dir or tts.get("output_dir") or DEFAULT_OUTPUT_DIR
    return SynthSettings(
        provider=chosen,
        voice=resolved_voice,
        model=resolved_model,
        output_dir=Path(out).expanduser(),
    )


def _max_chars(cfg: dict | None) -> int:
    raw = _tts_config(cfg).get("max_chars")
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return MAX_TEXT_CHARS
    return limit if limit > 0 else MAX_TEXT_CHARS


def prepare_text(text, cfg: dict | None = None) -> str:
    """Return the text to synthesize; never truncates — too long is an error."""
    cleaned = str(text if text is not None else "").strip()
    if not cleaned:
        raise TTSError("Text is empty; nothing to synthesize.")
    limit = _max_chars(cfg)
    if len(cleaned) > limit:
        raise TTSError(
            f"Text is {len(cleaned)} characters; the limit for one speak_text call is "
            f"{limit} — split it into shorter calls."
        )
    return cleaned


def _format_for(provider: str) -> str:
    return PROVIDER_FORMATS.get(provider, "wav")


def output_path(text, settings: SynthSettings, save_to=None) -> Path:
    """Where the audio goes. The suffix always matches the provider's real format."""
    suffix = "." + _format_for(settings.provider)
    if save_to:
        path = Path(str(save_to)).expanduser()
        current = path.suffix.lower()
        if current != suffix:
            if current in _AUDIO_SUFFIXES:
                path = path.with_suffix(suffix)
            else:
                path = path.with_name(path.name + suffix)
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = settings.output_dir / f"speech-{stamp}-{uuid4().hex[:4]}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _provider_cfg(cfg: dict | None, provider: str) -> dict:
    return ((cfg or {}).get("providers", {}) or {}).get(provider, {}) or {}


def _api_key(cfg: dict | None, provider: str) -> str:
    return str(_provider_cfg(cfg, provider).get("api_key", "") or "").strip()


def _post(label: str, url: str, **kwargs):
    import requests
    try:
        resp = requests.post(url, timeout=HTTP_TIMEOUT, **kwargs)
    except requests.RequestException as e:
        raise TTSError(f"{label} TTS request failed: {e}") from e
    status = int(getattr(resp, "status_code", 0) or 0)
    if not 200 <= status < 300:
        body = getattr(resp, "text", None)
        if not isinstance(body, str):
            body = bytes(getattr(resp, "content", b"") or b"").decode("utf-8", "replace")
        raise TTSError(f"{label} TTS failed: {status} {body[:300]}")
    try:
        declared = int((getattr(resp, "headers", None) or {}).get("Content-Length") or 0)
    except (TypeError, ValueError):
        declared = 0
    content = getattr(resp, "content", b"") or b""
    if declared > MAX_RESPONSE_BYTES or len(content) > MAX_RESPONSE_BYTES:
        limit_mb = MAX_RESPONSE_BYTES // (1024 * 1024)
        raise TTSError(f"{label} TTS response is larger than {limit_mb} MB; refusing it.")
    return resp


def _write_pcm16_wav(path: Path, pcm: bytes, sample_rate: int = 24000) -> int:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return path.stat().st_size


# ─── Providers: (text, settings, path) -> bytes written ───────────────────────

def _synth_system(text: str, settings: SynthSettings, path: Path,
                  cfg: dict | None = None) -> int:
    try:
        import pyttsx3
    except ImportError as e:
        raise TTSError("pyttsx3 is not installed. Install it with: pip install pyttsx3") from e
    try:
        engine = pyttsx3.init()
        if settings.voice:
            try:
                engine.setProperty("voice", settings.voice)
            except Exception as e:  # noqa: BLE001 - an unknown voice falls back to the default
                log.debug("pyttsx3 rejected voice %r: %s", settings.voice, e)
        engine.save_to_file(text, str(path))
        engine.runAndWait()
    except TTSError:
        raise
    except Exception as e:
        raise TTSError(f"The system speech engine failed: {e}") from e
    if not path.exists() or path.stat().st_size == 0:
        raise TTSError(
            "The system speech engine produced no audio (no speech driver available on this host)."
        )
    return path.stat().st_size


def _synth_kokoro(text: str, settings: SynthSettings, path: Path,
                  cfg: dict | None = None) -> int:
    try:
        import soundfile as sf
        from kokoro_onnx import Kokoro
    except ImportError as e:
        raise TTSError(
            "Kokoro TTS needs kokoro-onnx and soundfile. Install them with: "
            "pip install kokoro-onnx soundfile"
        ) from e
    onnx_files = sorted(VOICE_MODELS_DIR.glob("*.onnx")) if VOICE_MODELS_DIR.is_dir() else []
    bin_files = sorted(VOICE_MODELS_DIR.glob("*.bin")) if VOICE_MODELS_DIR.is_dir() else []
    if not onnx_files or not bin_files:
        raise TTSError(
            f"Kokoro model files (*.onnx and *.bin) are missing from {VOICE_MODELS_DIR}. "
            "Download them with: koza voice setup"
        )
    try:
        kok = Kokoro(str(onnx_files[0]), str(bin_files[0]))
        samples, sr = kok.create(text, voice=settings.voice or "af_sky", speed=1.0, lang="en-us")
        sf.write(str(path), samples, sr, format="WAV")
    except Exception as e:
        raise TTSError(f"Kokoro TTS failed: {e}") from e
    return path.stat().st_size


def _synth_openai(text: str, settings: SynthSettings, path: Path,
                  cfg: dict | None = None) -> int:
    key = _api_key(cfg, "openai")
    if not key:
        raise TTSError("OpenAI TTS requires providers.openai.api_key. Run: koza setup")
    base_url = (_provider_cfg(cfg, "openai").get("base_url")
                or "https://api.openai.com/v1").rstrip("/")
    resp = _post(
        "OpenAI",
        base_url + "/audio/speech",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": settings.model or "tts-1",
            "voice": settings.voice or "alloy",
            "input": text,
            "response_format": "mp3",
        },
    )
    path.write_bytes(resp.content)
    return path.stat().st_size


def _synth_gemini(text: str, settings: SynthSettings, path: Path,
                  cfg: dict | None = None) -> int:
    key = _api_key(cfg, "gemini")
    if not key:
        raise TTSError("Gemini TTS requires providers.gemini.api_key. Run: koza setup")
    model = settings.model or "gemini-2.5-flash-preview-tts"
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": settings.voice or "Kore"}
                }
            },
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    resp = _post("Gemini", url, params={"key": key}, json=body)
    try:
        data = resp.json()
    except Exception as e:
        raise TTSError(f"Gemini TTS returned an unreadable response: {e}") from e
    for candidate in data.get("candidates", []) or []:
        for part in (candidate.get("content") or {}).get("parts", []) or []:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            audio_b64 = inline.get("data")
            if not audio_b64:
                continue
            try:
                audio = base64.b64decode(audio_b64)
            except Exception as e:
                raise TTSError(f"Gemini TTS returned invalid base64 audio: {e}") from e
            mime = (inline.get("mimeType") or inline.get("mime_type")
                    or "audio/L16;rate=24000").lower()
            if "wav" in mime or "wave" in mime:
                path.write_bytes(audio)
                return path.stat().st_size
            match = re.search(r"rate=(\d+)", mime)
            return _write_pcm16_wav(path, audio, int(match.group(1)) if match else 24000)
    raise TTSError("Gemini TTS returned no audio.")


def _synth_elevenlabs(text: str, settings: SynthSettings, path: Path,
                      cfg: dict | None = None) -> int:
    key = _api_key(cfg, "elevenlabs")
    if not key:
        raise TTSError(
            "ElevenLabs TTS requires providers.elevenlabs.api_key. "
            "Set ELEVENLABS_API_KEY or run: koza setup"
        )
    voice_id = settings.voice or "21m00Tcm4TlvDq8ikWAM"
    resp = _post(
        "ElevenLabs",
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_24000",
        headers={
            "xi-api-key": key,
            "Accept": "application/octet-stream",
            "Content-Type": "application/json",
        },
        json={"text": text, "model_id": settings.model or "eleven_multilingual_v2"},
    )
    return _write_pcm16_wav(path, resp.content, 24000)


_SYNTHESIZERS = {
    "system": _synth_system,
    "kokoro": _synth_kokoro,
    "openai": _synth_openai,
    "gemini": _synth_gemini,
    "elevenlabs": _synth_elevenlabs,
}


# ─── Entry point ──────────────────────────────────────────────────────────────

def _check_provider(provider: str) -> None:
    if provider == "skip":
        raise TTSError("TTS is disabled (voice.tts.provider is 'skip').")
    if provider not in _SYNTHESIZERS:
        raise TTSError(
            f"Unknown TTS provider '{provider}'. Valid providers: {', '.join(PROVIDERS)}."
        )


def synthesize(text, cfg: dict | None = None, *, save_to=None, provider=None, voice=None,
               model=None) -> SynthResult:
    """Synthesize ``text`` to an audio file and describe it. Raises ``TTSError``."""
    cleaned = prepare_text(text, cfg)
    settings = resolve_settings(cfg, provider=provider, voice=voice, model=model)
    _check_provider(settings.provider)
    target = output_path(cleaned, settings, save_to)

    # Write next to the target and rename on success: a failure never leaves a
    # partial file behind, nor destroys a file that already sat at save_to.
    partial = target.with_name(f".{target.stem}.{uuid4().hex[:8]}.partial{target.suffix}")
    try:
        _SYNTHESIZERS[settings.provider](cleaned, settings, partial, cfg)
        if not partial.exists() or partial.stat().st_size == 0:
            raise TTSError(f"{settings.provider} TTS produced no audio.")
        os.replace(partial, target)
    except TTSError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as e:
        partial.unlink(missing_ok=True)
        raise TTSError(f"{settings.provider} TTS failed: {e}") from e

    return SynthResult(
        path=str(target.absolute()),
        provider=settings.provider,
        voice=settings.voice,
        format=_format_for(settings.provider),
        bytes=target.stat().st_size,
    )
