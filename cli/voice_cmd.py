"""CLI command: koza voice — always-on voice interaction loop.

Commands:
  koza voice           — start always-on voice chat (no Enter needed)
  koza voice setup     — install deps, pick devices, configure
  koza voice devices   — update audio device selection
  koza voice off       — disable voice feature
"""
from cli.ui import _C, _hr, _print_error

_DEVICE_SKIP = object()

def _list_and_pick_devices(allow_skip: bool = False):
    """Show only unique real devices + System Default, let user pick input/output."""
    import sounddevice as sd
    from cli.ui import _select_menu

    devices = sd.query_devices()
    default_in  = sd.default.device[0]
    default_out = sd.default.device[1]

    def _default_name(idx):
        try:
            return devices[idx]["name"]
        except Exception:
            return "?"

    # Build de-duplicated lists: keep first occurrence of each name
    seen_in, seen_out = set(), set()
    input_opts  = [("System Default", None)]   # (label, device_idx)
    output_opts = [("System Default", None)]

    for i, d in enumerate(devices):
        name = d.get("name", "")
        if d.get("max_input_channels", 0) > 0 and name not in seen_in:
            seen_in.add(name)
            marker = " ★" if i == default_in else ""
            input_opts.append((f"{name}{marker}", i))
        if d.get("max_output_channels", 0) > 0 and name not in seen_out:
            seen_out.add(name)
            marker = " ★" if i == default_out else ""
            output_opts.append((f"{name}{marker}", i))

    if allow_skip:
        input_opts.append(("Skip — keep current", _DEVICE_SKIP))
        output_opts.append(("Skip — keep current", _DEVICE_SKIP))

    _hr("·", "grey")
    print(_C(f"  System default input : {_default_name(default_in)}", "grey"))
    print(_C(f"  System default output: {_default_name(default_out)}\n", "grey"))

    try:
        in_lbl  = _select_menu("Microphone (input)", [l for l, _ in input_opts], default_idx=0)
        chosen_in  = dict(input_opts)[in_lbl]
    except (KeyboardInterrupt, EOFError):
        return None, None

    try:
        out_lbl = _select_menu("Speakers (output)", [l for l, _ in output_opts], default_idx=0)
        chosen_out = dict(output_opts)[out_lbl]
    except (KeyboardInterrupt, EOFError):
        return None, None

    return chosen_in, chosen_out


def _do_setup(args: list) -> None:
    from config import load_config

    cfg = load_config()
    configure_voice(cfg, save=True)


def _voice_status(cfg: dict) -> str:
    from skills.voice import normalize_voice_config
    voice = normalize_voice_config(cfg)
    if not voice.get("enabled"):
        return "disabled"
    stt = voice.get("stt", {})
    tts = voice.get("tts", {})
    return f"STT:{stt.get('provider')} / {stt.get('model')}  TTS:{tts.get('provider')} / {tts.get('voice')}"


def configure_voice(cfg: dict, save: bool = False) -> None:
    """Shared voice setup used by `koza setup` and `koza voice setup`."""
    from config import save_config
    from cli.ui import _select_menu
    from skills.voice import ensure_audio_deps, ensure_local_stt_deps, _get_stt_model, _try_kokoro_install, normalize_voice_config

    voice = normalize_voice_config(cfg)
    _hr()
    print(_C("\n  🎙  Voice / STT / TTS Setup\n", "bold", "cyan"))
    print(_C(f"  Current: {_voice_status(cfg)}\n", "grey"))

    try:
        action = _select_menu(
            "Voice mode",
            ["Enable / reconfigure",
             "Disable voice mode",
             "Skip — keep current / configure later"],
            default_idx=2,
        )
    except (KeyboardInterrupt, EOFError):
        return

    if action.startswith("Skip"):
        return
    if action.startswith("Disable"):
        cfg.setdefault("voice", {})["enabled"] = False
        if save:
            save_config(cfg)
        print(_C("  ✓  Voice disabled.\n", "green"))
        return

    cfg["voice"] = voice
    voice["enabled"] = True

    stt_choice = _select_menu(
        "Speech-to-Text Provider",
        ["Local Whisper (faster-whisper)",
         "OpenAI transcription",
         "Gemini transcription",
         "Deepgram transcription",
         "Skip — keep current / configure later"],
        default_idx=0,
    )
    if stt_choice.startswith("Local"):
        model_choice = _select_menu(
            "Local Whisper model",
            ["tiny", "base", "small", "Skip — keep current / configure later"],
            default_idx=1,
        )
        if not model_choice.startswith("Skip"):
            voice["stt"] = {"provider": "local_whisper", "model": model_choice, "language": voice.get("stt", {}).get("language", "")}
            try:
                print(_C("  Installing/checking local STT deps…", "grey"))
                ensure_local_stt_deps()
                _get_stt_model(model_choice)
            except Exception as e:
                print(_C(f"  ⚠  Local STT setup issue: {e}\n", "yellow"))
    elif stt_choice.startswith("OpenAI"):
        model_choice = _select_menu(
            "OpenAI STT model",
            ["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe", "Skip — keep current / configure later"],
            default_idx=0,
        )
        if not model_choice.startswith("Skip"):
            voice["stt"] = {"provider": "openai", "model": model_choice, "language": voice.get("stt", {}).get("language", "")}
    elif stt_choice.startswith("Gemini"):
        model_choice = _select_menu(
            "Gemini STT model",
            ["gemini-2.0-flash", "gemini-1.5-flash", "Skip — keep current / configure later"],
            default_idx=0,
        )
        if not model_choice.startswith("Skip"):
            voice["stt"] = {"provider": "gemini", "model": model_choice, "language": voice.get("stt", {}).get("language", "")}
    elif stt_choice.startswith("Deepgram"):
        model_choice = _select_menu(
            "Deepgram STT model",
            ["nova-3", "nova-2", "base", "Skip — keep current / configure later"],
            default_idx=0,
        )
        if not model_choice.startswith("Skip"):
            voice["stt"] = {"provider": "deepgram", "model": model_choice, "language": voice.get("stt", {}).get("language", "")}

    lang_choice = _select_menu(
        "STT language",
        ["auto-detect", "tr", "en", "de", "fr", "es", "Skip — keep current / configure later"],
        default_idx=0,
    )
    if not lang_choice.startswith("Skip"):
        voice.setdefault("stt", {}).setdefault("provider", "local_whisper")
        voice["stt"]["language"] = "" if lang_choice == "auto-detect" else lang_choice

    tts_choice = _select_menu(
        "Text-to-Speech Provider",
        ["System pyttsx3",
         "Kokoro ONNX",
         "OpenAI speech",
         "Gemini speech",
         "ElevenLabs speech",
         "Skip — keep current / configure later"],
        default_idx=0,
    )
    if tts_choice.startswith("System"):
        voice["tts"] = {"provider": "system", "model": "", "voice": voice.get("tts", {}).get("voice", "af_sky")}
    elif tts_choice.startswith("Kokoro"):
        kokoro_voice = _select_menu(
            "Kokoro voice",
            ["af_sky", "af_bella", "am_adam", "Skip — keep current / configure later"],
            default_idx=0,
        )
        if not kokoro_voice.startswith("Skip"):
            voice["tts"] = {"provider": "kokoro", "model": "", "voice": kokoro_voice}
            print(_C("\n  Downloading/checking Kokoro models…\n", "grey"))
            if not _try_kokoro_install():
                print(_C("  ⚠  Kokoro setup failed; config saved but runtime may fail until dependencies are fixed.\n", "yellow"))
    elif tts_choice.startswith("OpenAI"):
        model_choice = _select_menu(
            "OpenAI TTS model",
            ["tts-1", "gpt-4o-mini-tts", "Skip — keep current / configure later"],
            default_idx=0,
        )
        voice_choice = _select_menu(
            "OpenAI voice",
            ["alloy", "nova", "shimmer", "echo", "fable", "onyx", "Skip — keep current / configure later"],
            default_idx=0,
        )
        if not model_choice.startswith("Skip") and not voice_choice.startswith("Skip"):
            voice["tts"] = {"provider": "openai", "model": model_choice, "voice": voice_choice}
    elif tts_choice.startswith("Gemini"):
        model_choice = _select_menu(
            "Gemini TTS model",
            ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts", "Skip — keep current / configure later"],
            default_idx=0,
        )
        voice_choice = _select_menu(
            "Gemini voice",
            ["Kore", "Puck", "Charon", "Fenrir", "Aoede", "Skip — keep current / configure later"],
            default_idx=0,
        )
        if not model_choice.startswith("Skip") and not voice_choice.startswith("Skip"):
            voice["tts"] = {"provider": "gemini", "model": model_choice, "voice": voice_choice}
    elif tts_choice.startswith("ElevenLabs"):
        model_choice = _select_menu(
            "ElevenLabs TTS model",
            ["eleven_multilingual_v2", "eleven_turbo_v2_5", "Skip — keep current / configure later"],
            default_idx=0,
        )
        voice_choice = _select_menu(
            "ElevenLabs voice",
            ["Rachel — 21m00Tcm4TlvDq8ikWAM",
             "Adam — pNInz6obpgDQGcFmaJgB",
             "Bella — EXAVITQu4vr4xnSDxMaL",
             "Skip — keep current / configure later"],
            default_idx=0,
        )
        if not model_choice.startswith("Skip") and not voice_choice.startswith("Skip"):
            voice_id = voice_choice.split(" — ", 1)[1] if " — " in voice_choice else voice_choice
            voice["tts"] = {"provider": "elevenlabs", "model": model_choice, "voice": voice_id}

    device_choice = _select_menu(
        "Audio Devices",
        ["Configure input/output devices",
         "Skip — keep current / configure later"],
        default_idx=1,
    )
    if not device_choice.startswith("Skip"):
        try:
            ensure_audio_deps()
            input_device, output_device = _list_and_pick_devices(allow_skip=True)
            if input_device is not _DEVICE_SKIP:
                voice["input_device"] = input_device
            if output_device is not _DEVICE_SKIP:
                voice["output_device"] = output_device
        except Exception as e:
            print(_C(f"  ⚠  Audio device setup issue: {e}\n", "yellow"))

    cfg["voice"] = voice
    if save:
        save_config(cfg)

    action_word = "saved" if save else "updated"
    print(_C(f"\n  ✅  Voice config {action_word}. Run  koza voice  to start talking.\n", "green"))
    _hr()


def cmd_voice(args: list) -> None:
    """koza voice — always-on voice interaction (no Enter needed)."""
    from config import load_config, save_config, config_exists

    if args and args[0] == "setup":
        _do_setup(args[1:])
        return

    if args and args[0] == "devices":
        if not config_exists():
            print(_C("  ✗  No config found. Run:  koza setup\n", "red"))
            return
        try:
            from skills.voice import ensure_audio_deps
            ensure_audio_deps()
        except Exception:
            pass
        _hr()
        print(_C("\n  🔊  Audio Device Selection\n", "bold", "cyan"))
        in_dev, out_dev = _list_and_pick_devices()
        cfg = load_config()
        cfg.setdefault("voice", {}).update({
            "input_device":  in_dev,
            "output_device": out_dev,
        })
        save_config(cfg)
        print(_C(f"\n  ✅  Saved  input={in_dev}  output={out_dev}\n", "green"))
        _hr()
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
        from skills.voice import vad_listen_loop, tts_speak_configured, normalize_voice_config
    except ImportError as e:
        print(_C(f"  ✗  Voice deps missing: {e}\n  Run:  koza voice setup\n", "red"))
        return

    from core import Agent
    from providers.factory import get_provider
    import threading

    provider  = get_provider(cfg)
    agent     = Agent(provider, cfg["db_path"], cfg)
    voice_cfg = normalize_voice_config(cfg)
    language     = voice_cfg.get("stt", {}).get("language") or None
    input_device = voice_cfg.get("input_device")
    output_device= voice_cfg.get("output_device")

    _hr()
    print(_C("\n  🎙  Koza Voice Mode  — Always Listening\n", "bold", "cyan"))
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        in_name  = devs[input_device]["name"]  if input_device  is not None else sd.query_devices(kind="input")["name"]
        out_name = devs[output_device]["name"] if output_device is not None else sd.query_devices(kind="output")["name"]
        print(_C(f"  🎤  Input:   {in_name}", "grey"))
        print(_C(f"  🔊  Output:  {out_name}", "grey"))
    except Exception:
        pass
    print(_C("  Just speak — Koza listens automatically.", "grey"))
    print(_C("  Ctrl+C to exit\n", "grey"))
    _hr()

    stop_event = threading.Event()

    try:
        for text in vad_listen_loop(
            input_device=input_device,
            language=language,
            stop_event=stop_event,
            cfg=cfg,
        ):
            if not text:
                continue

            import sys
            sys.stdout.write("\r" + " " * 72 + "\r")
            print(_C("  You  › ", "cyan", "bold") + _C(text, "white"))
            sys.stdout.write(_C("  ⚙   Thinking…", "grey"))
            sys.stdout.flush()

            full_response = ""
            try:
                for event in agent.stream_chat(text):
                    if isinstance(event, dict) and event.get("type") == "text":
                        tok = event.get("token", "")
                        if not full_response:
                            sys.stdout.write("\r" + " " * 40 + "\r")
                        full_response += tok
            except KeyboardInterrupt:
                agent.interrupt()
                continue
            except Exception as exc:
                _print_error(exc)
                continue

            if full_response.strip():
                print(_C("  Koza › ", "yellow", "bold") + full_response.strip())
                sys.stdout.write(_C("  🔊  Speaking…\n", "grey"))
                sys.stdout.flush()
                try:
                    tts_speak_configured(full_response.strip(), cfg, output_device=output_device)
                except Exception:
                    print(_C("  ⚠  TTS failed. Run: koza voice setup\n", "yellow"))

            _hr("·", "grey")

    except KeyboardInterrupt:
        stop_event.set()

    print(_C("\n  Voice session ended. 👋\n", "yellow"))
    _hr()
