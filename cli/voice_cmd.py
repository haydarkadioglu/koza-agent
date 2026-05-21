"""CLI command: koza voice — always-on voice interaction loop.

Commands:
  koza voice           — start always-on voice chat (no Enter needed)
  koza voice setup     — install deps, pick devices, configure
  koza voice devices   — update audio device selection
  koza voice off       — disable voice feature
"""
from cli.ui import _C, _hr, _print_error


def _list_and_pick_devices() -> tuple[int | None, int | None]:
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
    from config import load_config, save_config
    from cli.ui import _select_menu
    from skills.voice import ensure_deps, _get_stt_model

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

    tts_choice = _select_menu(
        "TTS engine",
        ["pyttsx3 (system — works everywhere, no download)",
         "Kokoro ONNX (higher quality, ~82 MB download)"],
        default_idx=0,
    )
    use_kokoro = "Kokoro" in tts_choice
    if use_kokoro:
        print(_C("\n  Downloading Kokoro models…\n", "grey"))
        from skills.voice import _try_kokoro_install
        ok = _try_kokoro_install()
        if not ok:
            print(_C("  ✗  Kokoro download failed — using pyttsx3 instead.\n", "yellow"))
            use_kokoro = False

    # Device selection
    print(_C("\n  Step 3 — Audio device selection\n", "grey"))
    input_device, output_device = _list_and_pick_devices()

    lang_choice = _select_menu(
        "STT language (Whisper auto-detects, or force a language)",
        ["auto-detect", "tr", "en", "de", "fr", "es"],
        default_idx=0,
    )
    language = "" if lang_choice == "auto-detect" else lang_choice

    cfg = load_config()
    cfg.setdefault("voice", {}).update({
        "enabled":       True,
        "stt_model":     "base",
        "tts_voice":     "af_sky",
        "use_kokoro":    use_kokoro,
        "language":      language,
        "input_device":  input_device,
        "output_device": output_device,
    })
    save_config(cfg)

    print(_C("\n  ✅  Voice enabled!  Run  koza voice  to start talking.\n", "green"))
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
            from skills.voice import ensure_deps
            ensure_deps()
        except Exception:
            pass
        _hr()
        print(_C("\n  🔊  Audio Device Selection\n", "bold", "cyan"))
        in_dev, out_dev = _list_and_pick_devices()
        if in_dev is not None:
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
        from skills.voice import vad_listen_loop, tts_speak
    except ImportError as e:
        print(_C(f"  ✗  Voice deps missing: {e}\n  Run:  koza voice setup\n", "red"))
        return

    from core import Agent
    from providers.factory import get_provider
    import threading

    provider  = get_provider(cfg)
    agent     = Agent(provider, cfg["db_path"], cfg)
    voice_cfg = cfg.get("voice", {})
    tts_voice    = voice_cfg.get("tts_voice", "af_sky")
    language     = voice_cfg.get("language") or None
    input_device = voice_cfg.get("input_device")
    output_device= voice_cfg.get("output_device")
    use_kokoro   = voice_cfg.get("use_kokoro", False)

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
                    tts_speak(full_response.strip(), voice=tts_voice,
                              output_device=output_device, use_kokoro=use_kokoro)
                except Exception:
                    pass

            _hr("·", "grey")

    except KeyboardInterrupt:
        stop_event.set()

    print(_C("\n  Voice session ended. 👋\n", "yellow"))
    _hr()
