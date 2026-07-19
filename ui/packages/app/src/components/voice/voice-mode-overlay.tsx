import { createSignal, createEffect, Show, Component } from "solid-js"
import { Portal } from "solid-js/web"
import { IconButton } from "@opencode-ai/ui/icon-button"

export const VoiceModeOverlay: Component<{
  active: boolean
  onClose: () => void
  onTranscript: (text: string) => void
  isProcessing: boolean
  lastAgentMessage?: string
}> = (props) => {
  const [listening, setListening] = createSignal(false)
  const [transcript, setTranscript] = createSignal("")
  const [speaking, setSpeaking] = createSignal(false)

  let recognition: any

  createEffect(() => {
    if (!props.active) {
      if (recognition) recognition.stop()
      window.speechSynthesis.cancel()
      return
    }

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (SpeechRecognition && !recognition) {
      recognition = new SpeechRecognition()
      recognition.continuous = false
      recognition.interimResults = true
      recognition.lang = "tr-TR" // Varsayılan Türkçe

      recognition.onstart = () => {
        setListening(true)
        setTranscript("")
      }
      
      recognition.onend = () => {
        setListening(false)
        if (props.active && !props.isProcessing && !speaking()) {
          try { recognition.start() } catch (e) {}
        }
      }
      
      recognition.onresult = (event: any) => {
        let interim = ""
        let final = ""
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
        } else {
          setTranscript(interim)
        }
      }
    }

    if (props.active && !props.isProcessing && !speaking()) {
      try { recognition?.start() } catch (e) {}
    } else {
      try { recognition?.stop() } catch (e) {}
    }
  })

  let lastSpokenMessage = ""
  createEffect(() => {
    if (!props.active) return
    const msg = props.lastAgentMessage
    if (msg && !props.isProcessing && msg !== lastSpokenMessage) {
      lastSpokenMessage = msg
      window.speechSynthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(msg)
      utterance.lang = "tr-TR"
      utterance.onstart = () => {
        setSpeaking(true)
        try { recognition?.stop() } catch (e) {}
      }
      utterance.onend = () => {
        setSpeaking(false)
        if (props.active && !props.isProcessing) {
          try { recognition?.start() } catch (e) {}
        }
      }
      window.speechSynthesis.speak(utterance)
    }
  })

  return (
    <Show when={props.active}>
      <Portal>
        <div class="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-background-base/90 backdrop-blur-md transition-all duration-300">
          <div class="absolute top-6 right-6">
            <IconButton icon="close" size="large" variant="ghost" onClick={props.onClose} aria-label="Close Voice Mode" />
          </div>
          
          <div class="flex-1 flex flex-col items-center justify-center gap-12 max-w-3xl w-full px-8 text-center">
            {/* Dynamic Orb Visualizer */}
            <div class="relative flex items-center justify-center size-56">
              <Show when={listening() && !props.isProcessing && !speaking()}>
                <div class="absolute inset-0 rounded-full bg-surface-interactive-base/20 animate-ping" />
                <div class="absolute inset-4 rounded-full bg-surface-interactive-base/40 animate-pulse" />
              </Show>
              <Show when={props.isProcessing}>
                <div class="absolute inset-0 rounded-full border-t-4 border-surface-interactive-base animate-spin" />
                <div class="absolute inset-4 rounded-full bg-surface-warning-base/20 animate-pulse" />
              </Show>
              <Show when={speaking()}>
                <div class="absolute inset-0 rounded-full bg-surface-success-base/30 animate-pulse scale-125" />
                <div class="absolute inset-4 rounded-full bg-surface-success-base/50 animate-pulse scale-110" />
              </Show>
              
              <div 
                class="relative z-10 size-32 rounded-full flex items-center justify-center shadow-[0_0_40px_rgba(0,0,0,0.2)] transition-colors duration-500"
                classList={{
                  "bg-surface-interactive-base": listening() && !props.isProcessing && !speaking(),
                  "bg-surface-warning-base": props.isProcessing,
                  "bg-surface-success-base": speaking()
                }}
              >
                <span class="text-text-inverted-base text-5xl">
                  {speaking() ? "🗣️" : props.isProcessing ? "🤔" : "🎙️"}
                </span>
              </div>
            </div>

            <div class="text-3xl font-medium min-h-[6rem] transition-opacity w-full">
              <Show when={props.isProcessing}>
                <span class="text-text-weak animate-pulse">Koza düşünüyor...</span>
              </Show>
              <Show when={speaking()}>
                <span class="text-text-success-base line-clamp-3 leading-relaxed">{props.lastAgentMessage}</span>
              </Show>
              <Show when={listening() && !props.isProcessing && !speaking()}>
                <span class="text-text-strong opacity-80">{transcript() || "Sizi dinliyorum..."}</span>
              </Show>
            </div>
          </div>
        </div>
      </Portal>
    </Show>
  )
}
