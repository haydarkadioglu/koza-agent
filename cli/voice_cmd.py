"""CLI command: koza voice — voice interaction loop.

Commands:
  koza voice          — start voice chat loop (mic in, TTS out)
  koza voice setup    — install deps + download models + configure
  koza voice off      — disable voice feature
"""
from cli.ui import _C, _hr, _print_error


def _do_setup(args: list) -> None:
    from config import load_config, save_config
    from cli.ui import _select_menu
    from skills.voice import ensure_deps, _get_stt_model, _get_tts_model

    _hr()
    print(_C("\n  🎙  Voice Setup\n", "bold", "cyan"))
    print(_C("  Step 1 — Installing dependencies…\n", "grey"))
    ensure_deps()
    print(_C("  ✓  All packages installed.\n", "green"))

    print(_C("  Step 2 — Pre-loading STT model (whisper-base)…\n", "grey"))
    try:
        _get_stt_model()
    except Exception as e:
        print(_C(f"  ✗  STT model error: {e}\n", "red"))

    print(_C("\n  Step 3 — Pre-loading TTS model (Kokoro)…\n", "grey"))
    try:
        _get_tts_model()
    except Exception as e:
        print(_C(f"  ✗  TTS model error: {e}\n", "red"))

    lang_choice = _select_menu(
        "STT language (Whisper auto-detects, or force a language)",
        ["auto-detect", "tr", "en", "de", "fr", "es"],
        default_idx=0,
    )
    language = "" if lang_choice == "auto-detect" else lang_choice

    cfg = load_config()
    cfg.setdefault("voice", {}).update({
        "enabled":   True,
        "stt_model": "base",
        "tts_voice": "af_sky",
        "language":  language,
    })
    save_config(cfg)

    print(_C("\n  ✅  Voice enabled!  Run  koza voice  to start talking.\n", "green"))
    _hr()


def cmd_voice(args: list) -> None:
    """koza voice — voice interaction loop."""
    from config import load_config, save_config, config_exists

    if args and args[0] == "setup":
        _do_setup(args[1:])
        return

    if args and args[0] == "off":
        if config_exists():
            cfg = load_config()
            cfg.setdefault("voice", {})["enabled"] = False
            save_config(cfg)
            print(_C("  ✓  Voice disabled.\n", "green"))
        return

    if not config_exists():
        print(_C("  ✗  No config found. Run:  koza setup\n", "red"))
        return

    cfg = load_config()
    if not cfg.get("voice", {}).get("enabled"):
        print(_C("  ⚠  Voice is not enabled.\n  Run:  koza voice setup\n", "yellow"))
        return

    try:
        from skills.voice import stt_listen, tts_speak
    except ImportError as e:
        print(_C(f"  ✗  Voice deps missing: {e}\n  Run:  koza voice setup\n", "red"))
        return

    from core import Agent
    from providers.factory import get_provider

    provider = get_provider(cfg)
    agent    = Agent(provider, cfg["db_path"], cfg)

    voice_cfg  = cfg.get("voice", {})
    tts_voice  = voice_cfg.get("tts_voice", "af_sky")
    language   = voice_cfg.get("language") or None

    _hr()
    print(_C("\n  🎙  Koza Voice Mode\n", "bold", "cyan"))
    print(_C("  Press Enter to speak — pause after speaking to send.", "grey"))
    print(_C("  Press Ctrl+C to exit.\n", "grey"))
    _hr()

    while True:
        try:
            input(_C("\n  ●  Press Enter to speak › ", "yellow", "bold"))
        except (EOFError, KeyboardInterrupt):
            break

        try:
            text = stt_listen(max_seconds=15, language=language)
        except Exception as e:
            print(_C(f"  ✗  Mic error: {e}", "red"))
            continue

        if not text:
            print(_C("  (nothing heard — try again)", "grey"))
            continue

        print(_C("  You › ", "cyan", "bold") + _C(text, "white"))

        full_response = ""
        try:
            for event in agent.stream_chat(text):
                if isinstance(event, dict) and event.get("type") == "text":
                    full_response += event.get("token", "")
        except KeyboardInterrupt:
            agent.interrupt()
            continue
        except Exception as exc:
            _print_error(exc)
            continue

        if full_response.strip():
            print(_C("  Koza › ", "yellow", "bold") + full_response.strip())
            try:
                tts_speak(full_response.strip(), voice=tts_voice)
            except Exception:
                pass  # text already shown — TTS failure is non-fatal

        _hr("·", "grey")

    print(_C("\n  Voice session ended. 👋\n", "yellow"))
    _hr()
