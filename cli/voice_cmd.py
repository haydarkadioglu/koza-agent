"""CLI command: koza voice — voice interaction loop.

Commands:
  koza voice           — start voice chat loop (mic in, TTS out)
  koza voice setup     — install deps + download models + configure
  koza voice devices   — list audio devices and set input/output
  koza voice off       — disable voice feature
"""
from cli.ui import _C, _hr, _print_error


def _list_and_pick_devices() -> tuple[int | None, int | None]:
    """Print sounddevice device list and let user pick input + output IDs."""
    import sounddevice as sd
    from cli.ui import _select_menu

    devices = sd.query_devices()
    default_in  = sd.default.device[0]
    default_out = sd.default.device[1]

    _hr("·", "grey")
    print(_C("  Available Audio Devices\n", "cyan", "bold"))
    print(f"  {'ID':<4} {'Type':<6} {'Name'}", )
    print(_C("  " + "─" * 60, "grey"))

    input_devices  = []   # (label, device_index)
    output_devices = []

    for i, d in enumerate(devices):
        ins  = d.get("max_input_channels",  0)
        outs = d.get("max_output_channels", 0)
        dtype = "in+out" if ins > 0 and outs > 0 else ("in" if ins > 0 else "out")
        marker = ""
        if i == default_in:  marker += " ◀in"
        if i == default_out: marker += " ▶out"
        color = "white" if ins > 0 or outs > 0 else "grey"
        print(_C(f"  {i:<4} {dtype:<6} {d['name']}{marker}", color))
        if ins > 0:
            input_devices.append((f"{i}: {d['name']}", i))
        if outs > 0:
            output_devices.append((f"{i}: {d['name']}", i))

    print()

    # Input device
    in_labels = [lbl for lbl, _ in input_devices]
    try:
        chosen_in_lbl = _select_menu("Select INPUT device (microphone)", in_labels,
                                     default_idx=next((n for n, (_, i) in enumerate(input_devices)
                                                       if i == default_in), 0))
        chosen_in = dict(input_devices)[chosen_in_lbl]
    except (KeyboardInterrupt, EOFError):
        return None, None

    # Output device
    out_labels = [lbl for lbl, _ in output_devices]
    try:
        chosen_out_lbl = _select_menu("Select OUTPUT device (speakers)", out_labels,
                                      default_idx=next((n for n, (_, i) in enumerate(output_devices)
                                                        if i == default_out), 0))
        chosen_out = dict(output_devices)[chosen_out_lbl]
    except (KeyboardInterrupt, EOFError):
        return None, None

    return chosen_in, chosen_out


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

    # Device selection
    print(_C("\n  Step 4 — Audio device selection\n", "grey"))
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
        "language":      language,
        "input_device":  input_device,   # None = system default
        "output_device": output_device,
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

    if args and args[0] == "devices":
        # Standalone device picker — saves to config without full setup
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
        from skills.voice import stt_listen, tts_speak
    except ImportError as e:
        print(_C(f"  ✗  Voice deps missing: {e}\n  Run:  koza voice setup\n", "red"))
        return

    from core import Agent
    from providers.factory import get_provider

    provider = get_provider(cfg)
    agent    = Agent(provider, cfg["db_path"], cfg)

    voice_cfg    = cfg.get("voice", {})
    tts_voice    = voice_cfg.get("tts_voice", "af_sky")
    language     = voice_cfg.get("language") or None
    input_device = voice_cfg.get("input_device")    # None = system default
    output_device= voice_cfg.get("output_device")

    _hr()
    print(_C("\n  🎙  Koza Voice Mode\n", "bold", "cyan"))
    # Show active devices
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        in_name  = devs[input_device]["name"]  if input_device  is not None else sd.query_devices(kind="input")["name"]
        out_name = devs[output_device]["name"] if output_device is not None else sd.query_devices(kind="output")["name"]
        print(_C(f"  🎤  Input:   {in_name}", "grey"))
        print(_C(f"  🔊  Output:  {out_name}", "grey"))
        print(_C("  ─  koza voice devices  to change\n", "grey"))
    except Exception:
        pass
    print(_C("  Press Enter → speak → pause to send  |  Ctrl+C to exit\n", "grey"))
    _hr()

    while True:
        try:
            input(_C("\n  ●  Press Enter to speak › ", "yellow", "bold"))
        except (EOFError, KeyboardInterrupt):
            break

        print()  # blank line before VU meter
        try:
            text = stt_listen(max_seconds=15, language=language, input_device=input_device)
        except Exception as e:
            print(_C(f"\n  ✗  Mic error: {e}", "red"))
            continue

        if not text:
            print(_C("  (nothing heard — try again)", "grey"))
            continue

        print(_C("\n  You  › ", "cyan", "bold") + _C(text, "white"))
        print(_C("  ⚙   Thinking…", "grey"), end="", flush=True)

        full_response = ""
        try:
            for event in agent.stream_chat(text):
                if isinstance(event, dict) and event.get("type") == "text":
                    tok = event.get("token", "")
                    if not full_response:
                        # Clear "Thinking…" line on first token
                        import sys; sys.stdout.write("\r" + " " * 40 + "\r")
                    full_response += tok
        except KeyboardInterrupt:
            agent.interrupt()
            continue
        except Exception as exc:
            _print_error(exc)
            continue

        if full_response.strip():
            print(_C("  Koza › ", "yellow", "bold") + full_response.strip())
            print(_C("  🔊  Speaking…", "grey"))
            try:
                tts_speak(full_response.strip(), voice=tts_voice, output_device=output_device)
            except Exception:
                pass  # text already shown — TTS failure is non-fatal

        _hr("·", "grey")

    print(_C("\n  Voice session ended. 👋\n", "yellow"))
    _hr()
