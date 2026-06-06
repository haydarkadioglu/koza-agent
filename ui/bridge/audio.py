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
