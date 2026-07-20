import { createSignal, createEffect, onCleanup } from "solid-js"
import { Icon } from "@koza-ai/ui/icon"

export type VoiceState = "idle" | "listening" | "thinking" | "speaking"

export function VoiceModeOverlay(props: {
  onClose: () => void
  onTranscript: (text: string) => void
  isSimulatingResponse?: boolean
}) {
  const [state, setState] = createSignal<VoiceState>("idle")
  const [transcript, setTranscript] = createSignal("")
  const [amplitude, setAmplitude] = createSignal(0)
  
  let recognition: any = null
  let audioContext: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let microphone: MediaStreamAudioSourceNode | null = null
  let animationFrameId: number

  const initAudio = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
      analyser = audioContext.createAnalyser()
      microphone = audioContext.createMediaStreamSource(stream)
      microphone.connect(analyser)
      analyser.fftSize = 256

      const dataArray = new Uint8Array(analyser.frequencyBinCount)

      const updateAmplitude = () => {
        if (!analyser) return
        analyser.getByteFrequencyData(dataArray)
        const sum = dataArray.reduce((a, b) => a + b, 0)
        const avg = sum / dataArray.length
        setAmplitude(avg)
        animationFrameId = requestAnimationFrame(updateAmplitude)
      }
      
      updateAmplitude()
    } catch (err) {
      console.error("Audio setup error:", err)
    }
  }

  const startListening = () => {
    if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
      return
    }

    // @ts-ignore
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    recognition = new SpeechRecognition()
    recognition.lang = "tr-TR"
    recognition.continuous = true
    recognition.interimResults = true

    recognition.onstart = () => {
      setState("listening")
      initAudio()
    }

    recognition.onresult = (event: any) => {
      // Barge-in: Stop TTS if Koza was speaking
      if (state() === "speaking" && window.speechSynthesis) {
        window.speechSynthesis.cancel()
        setState("listening")
      }

      let final = ""
      let interim = ""
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          final += event.results[i][0].transcript
        } else {
          interim += event.results[i][0].transcript
        }
      }
      
      if (final) {
        setTranscript(final)
        props.onTranscript(final)
        setState("thinking") 
      } else {
        setTranscript(interim)
      }
    }

    recognition.onerror = (e: any) => {
      console.error("Voice Error", e)
      setState("idle")
    }

    recognition.onend = () => {
      if (state() === "listening") {
        setState("idle")
      }
    }

    try {
      recognition.start()
    } catch(e) {}
  }

  const stopEverything = () => {
    if (recognition) recognition.stop()
    if (window.speechSynthesis) window.speechSynthesis.cancel()
    if (animationFrameId) cancelAnimationFrame(animationFrameId)
    if (audioContext && audioContext.state !== 'closed') audioContext.close()
    setState("idle")
  }

  createEffect(() => {
    startListening()
  })
  
  createEffect(() => {
    if (props.isSimulatingResponse) {
        setState("speaking")
        const utter = new SpeechSynthesisUtterance("Elbette, sizi dinliyorum ve işlemi yapıyorum.")
        utter.lang = "tr-TR"
        utter.onend = () => {
            setState("listening")
        }
        window.speechSynthesis?.speak(utter)
    }
  })

  onCleanup(() => {
    stopEverything()
  })

  const scale = () => {
    if (state() === "thinking") return 0.8
    if (state() === "speaking") return 1.1 + Math.sin(Date.now() / 200) * 0.1
    return 1 + (amplitude() / 255) * 0.5
  }

  const pulseColor = () => {
    if (state() === "speaking") return "rgba(168, 85, 247, 0.7)" 
    if (state() === "thinking") return "rgba(59, 130, 246, 0.5)" 
    if (state() === "listening") return "rgba(34, 197, 94, 0.5)" 
    return "rgba(100, 100, 100, 0.3)"
  }

  return (
    <div class="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-surface-base/80 backdrop-blur-xl transition-all duration-500">
      <div class="absolute top-6 right-6">
        <button 
          onClick={() => {
            stopEverything()
            props.onClose()
          }}
          class="p-3 rounded-full bg-surface-panel-raised border border-border-weak-base hover:bg-surface-panel-raised-hover hover:scale-105 transition-all text-text-weak"
        >
          <Icon name="x" size="large" />
        </button>
      </div>

      <div class="flex-1 flex flex-col items-center justify-center gap-12 w-full max-w-2xl px-8">
        
        <div class="relative w-48 h-48 flex items-center justify-center">
          <div 
            class="absolute inset-0 rounded-full blur-2xl transition-all duration-75"
            style={{
              "background-color": pulseColor(),
              transform: `scale(${scale()})`
            }}
          />
          <div 
            class="relative w-32 h-32 rounded-full border-2 border-white/20 flex items-center justify-center bg-surface-panel shadow-2xl transition-all duration-200"
            style={{
              transform: `scale(${state() === "thinking" ? 0.9 : 1})`,
              "box-shadow": `0 0 40px ${pulseColor()}`
            }}
          >
            <Icon 
              name={state() === "listening" ? "mic" : state() === "speaking" ? "speaker" : "dots"} 
              class="w-12 h-12 text-white/80" 
              classList={{ "animate-pulse": state() === "thinking" }}
            />
          </div>
        </div>

        <div class="text-center space-y-4">
          <div class="text-14-medium uppercase tracking-widest text-text-weaker animate-pulse">
            {state() === "listening" ? "Dinliyor..." : state() === "thinking" ? "Düşünüyor..." : state() === "speaking" ? "Konuşuyor..." : "Bekliyor"}
          </div>
          <div class="text-24-medium text-text-strong min-h-[4rem] px-4 transition-all">
            {transcript() || "Merhaba, nasıl yardımcı olabilirim?"}
          </div>
        </div>

      </div>
    </div>
  )
}
