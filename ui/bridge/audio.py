import threading
import pathlib

VOICE_MODELS_DIR = pathlib.Path.home() / ".Koza" / "voice_models"
HF_CACHE_DIR = pathlib.Path.home() / ".cache" / "huggingface" / "hub"

class AudioMixin:
    def get_audio_devices(self):
        """Retrieve deduplicated list of audio input (mic) and output (speaker) devices."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            default_in  = sd.default.device[0]
            default_out = sd.default.device[1]
            
            seen_in, seen_out = set(), set()
            input_opts = []
            output_opts = []
            
            for i, d in enumerate(devices):
                name = d.get("name", "")
                if d.get("max_input_channels", 0) > 0 and name not in seen_in:
                    seen_in.add(name)
                    input_opts.append({"name": name, "id": i, "is_default": (i == default_in)})
                if d.get("max_output_channels", 0) > 0 and name not in seen_out:
                    seen_out.add(name)
                    output_opts.append({"name": name, "id": i, "is_default": (i == default_out)})
                    
            return {
                "status": "success",
                "input": input_opts,
                "output": output_opts
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def check_voice_model_status(self, category, model_name):
        """Check whether a local STT or TTS model is downloaded.
        
        category: 'stt' | 'tts'
        model_name: e.g. 'base', 'tiny', 'small' (STT) or 'kokoro' (TTS)
        Returns: {"status": "ready" | "missing" | "error", "message": "..."}
        """
        try:
            if category == "tts":
                # Kokoro ONNX: need .onnx and .bin files in VOICE_MODELS_DIR
                onnx_files = list(VOICE_MODELS_DIR.glob("*.onnx"))
                bin_files  = list(VOICE_MODELS_DIR.glob("*.bin"))
                if onnx_files and bin_files:
                    return {"status": "ready", "message": f"Model ready ({onnx_files[0].name})"}
                return {"status": "missing", "message": "Kokoro ONNX model files not found"}

            elif category == "stt":
                # Local Whisper: check HF hub cache for Systran/faster-whisper-{model}
                # Pattern: models--Systran--faster-whisper-{model_name}
                model_dir_name = f"models--Systran--faster-whisper-{model_name}"
                model_path = HF_CACHE_DIR / model_dir_name
                # Also check snapshots subfolder exists and has files
                if model_path.exists():
                    snapshots = model_path / "snapshots"
                    if snapshots.exists():
                        # Check any snapshot has actual model files
                        for snap in snapshots.iterdir():
                            if snap.is_dir() and any(snap.glob("*.bin")):
                                return {"status": "ready", "message": f"Model '{model_name}' ready"}
                        # Snapshots exist but may be incomplete
                        return {"status": "missing", "message": f"Model '{model_name}' incomplete"}
                return {"status": "missing", "message": f"Model '{model_name}' not downloaded"}
            else:
                return {"status": "error", "message": f"Unknown category: {category}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def download_voice_model(self, category, model_name):
        """Download a local STT or TTS model in the background.
        Progress is reported via JS callback onVoiceModelDownloadProgress().
        """
        def _notify(status, message):
            if self.webview_window:
                import json as _json
                payload = _json.dumps({"category": category, "model": model_name,
                                       "status": status, "message": message})
                self.webview_window.evaluate_js(
                    f"onVoiceModelDownloadProgress({payload})"
                )

        def run():
            try:
                _notify("downloading", f"Downloading {model_name}...")
                if category == "tts":
                    from skills.voice import _try_kokoro_install
                    ok = _try_kokoro_install()
                    if ok:
                        _notify("ready", "Kokoro ONNX model downloaded successfully ✓")
                    else:
                        _notify("error", "Kokoro download failed. Check your internet connection.")
                elif category == "stt":
                    from skills.voice import ensure_local_stt_deps, _get_stt_model
                    _notify("downloading", f"Installing faster-whisper dependencies...")
                    ensure_local_stt_deps()
                    _notify("downloading", f"Downloading '{model_name}' model weights...")
                    _get_stt_model(model_name)
                    _notify("ready", f"Model '{model_name}' downloaded successfully ✓")
                else:
                    _notify("error", f"Unknown category: {category}")
            except Exception as e:
                _notify("error", str(e))

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started", "message": f"Download started for {category}/{model_name}"}

    def start_voice_loop(self):
        """Start the conversational Voice Mode loop (VAD → STT → Agent → TTS → repeat).
        Only called when the user explicitly clicks the mic button on the chat page.
        """
        if hasattr(self, "_voice_thread") and self._voice_thread and self._voice_thread.is_alive():
            return {"status": "already_running"}

        self._voice_stop_event = threading.Event()
        self.voice_loop_active = True

        def run():
            try:
                from skills.voice import (
                    vad_listen_loop, normalize_voice_config,
                    ensure_audio_deps, tts_speak_configured
                )
                ensure_audio_deps()

                voice_cfg  = normalize_voice_config(self.cfg)
                language      = voice_cfg.get("stt", {}).get("language") or None
                input_device  = voice_cfg.get("input_device")
                output_device = voice_cfg.get("output_device")

                def _js(code):
                    if self.webview_window:
                        self.webview_window.evaluate_js(code)

                def status_callback(state):
                    _js(f"updateVoiceStatus('{state}')")

                status_callback("listening")

                for text in vad_listen_loop(
                    input_device=input_device,
                    language=language,
                    stop_event=self._voice_stop_event,
                    cfg=self.cfg,
                    status_callback=status_callback,
                ):
                    if not text or self._voice_stop_event.is_set():
                        continue

                    # ── 1. Show user bubble in chat ────────────────────────
                    import json as _json
                    _js(f"appendMessageBubble('user', {_json.dumps(text)}, [])")

                    # ── 2. Show thinking status ────────────────────────────
                    status_callback("transcribing")  # reuse "thinking" style

                    # ── 3. Stream agent response ───────────────────────────
                    full_response = ""
                    try:
                        _js("appendMessageBubble('assistant', '…', [])")
                        for event in self.agent.stream_chat(text):
                            if self._voice_stop_event.is_set():
                                break
                            if isinstance(event, dict) and event.get("type") == "text":
                                tok = event.get("token", "")
                                full_response += tok
                                # Stream token into the last assistant bubble
                                _js(f"updateLastAssistantBubble({_json.dumps(full_response)})")
                    except Exception as agent_err:
                        print(f"[Voice] Agent error: {agent_err}")
                        full_response = str(agent_err)

                    if not full_response.strip():
                        status_callback("listening")
                        continue

                    # ── 4. Speak the response ──────────────────────────────
                    status_callback("speaking")
                    try:
                        tts_speak_configured(
                            full_response.strip(),
                            self.cfg,
                            output_device=output_device,
                        )
                    except Exception as tts_err:
                        print(f"[Voice] TTS error: {tts_err}")

                    # ── 5. Back to listening ───────────────────────────────
                    if not self._voice_stop_event.is_set():
                        status_callback("listening")

            except Exception as e:
                print(f"[Voice] Loop error: {e}")
                if self.webview_window:
                    import json as _json
                    self.webview_window.evaluate_js(
                        f"onVoiceError({_json.dumps(str(e))})"
                    )
            finally:
                self.voice_loop_active = False
                if self.webview_window:
                    self.webview_window.evaluate_js("updateVoiceStatus('off')")

        self._voice_thread = threading.Thread(target=run, daemon=True)
        self._voice_thread.start()
        return {"status": "started"}

    def stop_voice_loop(self):
        """Stop background Voice Mode loop."""
        self.voice_loop_active = False
        if hasattr(self, "_voice_stop_event") and self._voice_stop_event:
            self._voice_stop_event.set()
        return {"status": "stopped"}

    def is_voice_loop_active(self):
        return {"active": getattr(self, "voice_loop_active", False)}

