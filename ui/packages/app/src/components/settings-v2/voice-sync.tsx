import { Component, createSignal, onMount, Show, onCleanup } from "solid-js"
import { ButtonV2 } from "@koza-ai/ui/v2/button-v2"
import { TextInputV2 } from "@koza-ai/ui/v2/text-input-v2"
import { SettingsListV2 } from "./parts/list"
import { SettingsRowV2 } from "./parts/row"
import "./settings-v2.css"

export const SettingsVoiceSyncV2: Component = () => {
  // Voice signals
  const [voiceEnabled, setVoiceEnabled] = createSignal(false)
  const [sttProvider, setSttProvider] = createSignal("local_whisper")
  const [sttModel, setSttModel] = createSignal("base")
  const [sttLang, setSttLang] = createSignal("")
  const [ttsProvider, setTtsProvider] = createSignal("system")
  const [ttsVoice, setTtsVoice] = createSignal("af_sky")

  // Multi-host signals
  const [syncMode, setSyncMode] = createSignal("single")
  const [syncPort, setSyncPort] = createSignal(7420)
  const [syncToken, setSyncToken] = createSignal("")
  const [hostName, setHostName] = createSignal("")
  const [masterUrl, setMasterUrl] = createSignal("")
  const [syncOnStartup, setSyncOnStartup] = createSignal(true)
  const [syncOnExit, setSyncOnExit] = createSignal(true)
  const [syncInterval, setSyncInterval] = createSignal(5)

  // Git installer signals
  const [gitInstalled, setGitInstalled] = createSignal(false)
  const [gitStatus, setGitStatus] = createSignal("idle")
  const [gitPercent, setGitPercent] = createSignal(0)
  const [gitError, setGitError] = createSignal("")

  const [saving, setSaving] = createSignal(false)
  const [message, setMessage] = createSignal("")

  let pollInterval: any

  const loadConfig = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/config")
      const cfg = await res.json()

      const voice = cfg.voice || {}
      setVoiceEnabled(!!voice.enabled)
      setSttProvider(voice.stt?.provider || "local_whisper")
      setSttModel(voice.stt?.model || "base")
      setSttLang(voice.stt?.language || "")
      setTtsProvider(voice.tts?.provider || "system")
      setTtsVoice(voice.tts?.voice || "af_sky")

      const sync = cfg.multi_host || {}
      setSyncMode(sync.mode || "single")
      setSyncPort(sync.sync_port || 7420)
      setSyncToken(sync.sync_token || "")
      setHostName(sync.host_name || "")
      setMasterUrl(sync.master_url || "")
      setSyncOnStartup(sync.sync_on_startup !== false)
      setSyncOnExit(sync.sync_on_exit !== false)
      setSyncInterval(sync.sync_interval !== undefined ? sync.sync_interval : 5)
    } catch (e) {
      console.error("Failed to load Voice/Sync config:", e)
    }
  }

  const checkGitStatus = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/git/status")
      const data = await res.json()
      setGitInstalled(data.installed)
      setGitStatus(data.progress.status)
      setGitPercent(data.progress.percent)
      setGitError(data.progress.error || "")
    } catch (e) {
      console.error("Failed to fetch git status:", e)
    }
  }

  onMount(() => {
    loadConfig()
    checkGitStatus()
    pollInterval = setInterval(checkGitStatus, 2000)
  })

  onCleanup(() => {
    clearInterval(pollInterval)
  })

  const saveConfig = async () => {
    setSaving(true)
    setMessage("")
    try {
      const payload = {
        voice: {
          enabled: voiceEnabled(),
          stt: {
            provider: sttProvider(),
            model: sttModel(),
            language: sttLang()
          },
          tts: {
            provider: ttsProvider(),
            model: ttsProvider() === "openai" ? "tts-1" : "",
            voice: ttsVoice()
          }
        },
        multi_host: {
          mode: syncMode(),
          sync_port: Number(syncPort()),
          sync_token: syncToken() || null,
          host_name: hostName() || null,
          master_url: masterUrl() || null,
          sync_on_startup: syncOnStartup(),
          sync_on_exit: syncOnExit(),
          sync_interval: Number(syncInterval())
        }
      }
      await fetch("http://localhost:8000/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })
      setMessage("✓ Voice & Sync settings saved successfully!")
    } catch (e) {
      setMessage("✗ Failed to save configurations.")
    } finally {
      setSaving(false)
    }
  }

  const installGit = async () => {
    try {
      await fetch("http://localhost:8000/api/git/install", { method: "POST" })
      checkGitStatus()
    } catch (e) {
      console.error("Failed to trigger MinGit download:", e)
    }
  }

  const generateToken = () => {
    const arr = new Uint8Array(20)
    crypto.getRandomValues(arr)
    const hex = Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('')
    setSyncToken(hex)
  }

  return (
    <div class="settings-v2-panel">
      <div class="settings-v2-tab-header">
        <h2 class="settings-v2-tab-title">Voice & Environment Settings</h2>
      </div>
      <div class="settings-v2-tab-body">

        {/* Voice Mode Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">🎙 Always-On Voice Mode</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Enable Voice Interaction" description="Talk to Koza using your microphone.">
              <input 
                type="checkbox" 
                class="accent-v2-border-border-accent size-4 rounded cursor-pointer"
                checked={voiceEnabled()} 
                onChange={(e) => setVoiceEnabled(e.currentTarget.checked)} 
              />
            </SettingsRowV2>
            <Show when={voiceEnabled()}>
              <SettingsRowV2 title="Speech-to-Text (STT)" description="Choose Speech-to-Text translation engine.">
                <select 
                  class="bg-transparent border border-v2-border-border-base rounded px-2 py-1 text-[13px] text-v2-text-text-base focus:outline-none"
                  value={sttProvider()} 
                  onChange={(e) => setSttProvider(e.currentTarget.value)}
                >
                  <option value="local_whisper">Local Whisper (faster-whisper)</option>
                  <option value="openai">OpenAI transcription</option>
                  <option value="gemini">Gemini transcription</option>
                  <option value="deepgram">Deepgram transcription</option>
                </select>
              </SettingsRowV2>
              <SettingsRowV2 title="STT Model" description="Specify active transcription model ID.">
                <TextInputV2 value={sttModel()} onChange={setSttModel} placeholder="e.g. base, whisper-1, nova-2" />
              </SettingsRowV2>
              <SettingsRowV2 title="Language" description="Auto-detect or lock transcription to a specific language.">
                <select 
                  class="bg-transparent border border-v2-border-border-base rounded px-2 py-1 text-[13px] text-v2-text-text-base focus:outline-none"
                  value={sttLang()} 
                  onChange={(e) => setSttLang(e.currentTarget.value)}
                >
                  <option value="">Auto-detect</option>
                  <option value="tr">Turkish (tr)</option>
                  <option value="en">English (en)</option>
                  <option value="de">German (de)</option>
                  <option value="fr">French (fr)</option>
                  <option value="es">Spanish (es)</option>
                </select>
              </SettingsRowV2>
              <SettingsRowV2 title="Text-to-Speech (TTS)" description="Choose voice output synthesizer.">
                <select 
                  class="bg-transparent border border-v2-border-border-base rounded px-2 py-1 text-[13px] text-v2-text-text-base focus:outline-none"
                  value={ttsProvider()} 
                  onChange={(e) => setTtsProvider(e.currentTarget.value)}
                >
                  <option value="system">System Default (pyttsx3)</option>
                  <option value="kokoro">Kokoro ONNX (Local)</option>
                  <option value="openai">OpenAI TTS</option>
                  <option value="gemini">Gemini TTS</option>
                </select>
              </SettingsRowV2>
              <SettingsRowV2 title="Voice Name" description="Synthesizer speaker preset.">
                <TextInputV2 value={ttsVoice()} onChange={setTtsVoice} placeholder="e.g. af_sky, alloy, echo" />
              </SettingsRowV2>
            </Show>
          </SettingsListV2>
        </div>

        {/* Multi-Host Sync Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">🔗 Multi-Host Synchronization</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Synchronization Mode" description="Configure how this machine participates in multi-host sync.">
              <select 
                class="bg-transparent border border-v2-border-border-base rounded px-2 py-1 text-[13px] text-v2-text-text-base focus:outline-none"
                value={syncMode()} 
                onChange={(e) => setSyncMode(e.currentTarget.value)}
              >
                <option value="single">Single Host (No Sync)</option>
                <option value="master">Sync Host (Server/Master)</option>
                <option value="client">Sync Client (Node)</option>
              </select>
            </SettingsRowV2>
            
            <Show when={syncMode() === "master"}>
              <SettingsRowV2 title="Sync Port" description="Port clients will connect to (default 7420).">
                <TextInputV2 value={String(syncPort())} onChange={(val) => setSyncPort(Number(val) || 7420)} placeholder="7420" />
              </SettingsRowV2>
              <SettingsRowV2 title="Sync Token" description="Security token required for clients to access this master.">
                <div class="flex gap-2 w-full">
                  <TextInputV2 value={syncToken()} onChange={setSyncToken} type="password" placeholder="Generate or paste security token" />
                  <ButtonV2 variant="secondary" onClick={generateToken}>Generate</ButtonV2>
                </div>
              </SettingsRowV2>
              <SettingsRowV2 title="Host Name" description="Friendly name of this host (optional).">
                <TextInputV2 value={hostName()} onChange={setHostName} placeholder="e.g. home-pc" />
              </SettingsRowV2>
            </Show>

            <Show when={syncMode() === "client"}>
              <SettingsRowV2 title="Master Server URL" description="Target synchronization master server URL.">
                <TextInputV2 value={masterUrl()} onChange={setMasterUrl} placeholder="e.g. http://192.168.1.10:7420" />
              </SettingsRowV2>
              <SettingsRowV2 title="Sync Token" description="Security authorization token from master.">
                <TextInputV2 value={syncToken()} onChange={setSyncToken} type="password" placeholder="Paste master's security token" />
              </SettingsRowV2>
              <SettingsRowV2 title="Sync on Startup" description="Pull latest database updates when launching Koza.">
                <input 
                  type="checkbox" 
                  class="accent-v2-border-border-accent size-4 rounded cursor-pointer"
                  checked={syncOnStartup()} 
                  onChange={(e) => setSyncOnStartup(e.currentTarget.checked)} 
                />
              </SettingsRowV2>
              <SettingsRowV2 title="Sync on Exit" description="Push local database updates when stopping Koza.">
                <input 
                  type="checkbox" 
                  class="accent-v2-border-border-accent size-4 rounded cursor-pointer"
                  checked={syncOnExit()} 
                  onChange={(e) => setSyncOnExit(e.currentTarget.checked)} 
                />
              </SettingsRowV2>
              <SettingsRowV2 title="Auto-Sync Interval" description="Interval to sync in minutes (0 = disabled).">
                <TextInputV2 value={String(syncInterval())} onChange={(val) => setSyncInterval(Number(val) || 0)} placeholder="5" />
              </SettingsRowV2>
            </Show>
          </SettingsListV2>
        </div>

        {/* MinGit Installer Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">🖥️ Shell Environment (MinGit)</h3>
          <SettingsListV2>
            <div data-component="settings-v2-row" class="flex flex-row justify-between items-center py-4">
              <div class="flex flex-col gap-1.5 flex-1 min-w-0 pr-4">
                <span class="text-[13px] font-bold text-v2-text-text-base">Portable MinGit</span>
                <span class="text-[12px] text-v2-text-text-muted">
                  Used on Windows to isolate commands inside a local UNIX bash shell.
                </span>
                <Show when={gitError()}>
                  <span class="text-[12px] text-v2-text-text-danger">Error: {gitError()}</span>
                </Show>
              </div>
              <div class="shrink-0 flex items-center gap-3">
                <Show when={gitInstalled()}>
                  <span class="text-[13px] font-medium text-v2-text-text-accent">✓ Installed & Active</span>
                </Show>
                <Show when={!gitInstalled()}>
                  <Show when={gitStatus() === "downloading"}>
                    <span class="text-[12px] text-v2-text-text-muted">Downloading ({gitPercent()}%)</span>
                  </Show>
                  <Show when={gitStatus() === "extracting"}>
                    <span class="text-[12px] text-v2-text-text-muted">Extracting files...</span>
                  </Show>
                  <Show when={gitStatus() === "completed"}>
                    <span class="text-[12px] text-v2-text-text-accent">✓ Installation completed</span>
                  </Show>
                  <Show when={gitStatus() !== "downloading" && gitStatus() !== "extracting"}>
                    <ButtonV2 variant="secondary" onClick={installGit}>Download MinGit (~45MB)</ButtonV2>
                  </Show>
                </Show>
              </div>
            </div>
          </SettingsListV2>
        </div>

        <div class="flex flex-col gap-2 items-end pt-4">
          <Show when={message()}>
            <span class="text-[13px] font-medium text-v2-text-text-accent">{message()}</span>
          </Show>
          <ButtonV2 variant="primary" onClick={saveConfig} disabled={saving()}>
            {saving() ? "Saving..." : "Save Settings"}
          </ButtonV2>
        </div>

      </div>
    </div>
  )
}
