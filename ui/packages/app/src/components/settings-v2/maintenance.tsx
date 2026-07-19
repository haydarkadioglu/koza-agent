import { Component, createSignal, onMount, Show } from "solid-js"
import { ButtonV2 } from "@opencode-ai/ui/v2/button-v2"
import { SettingsListV2 } from "./parts/list"
import { SettingsRowV2 } from "./parts/row"
import "./settings-v2.css"

export const SettingsMaintenanceV2: Component = () => {
  const [logs, setLogs] = createSignal<string[]>([])
  const [limit, setLimit] = createSignal(100)
  const [loadingLogs, setLoadingLogs] = createSignal(false)
  const [actionMessage, setActionMessage] = createSignal("")
  const [resetConfirmOpen, setResetConfirmOpen] = createSignal(false)

  // Version signals
  const [currentVer, setCurrentVer] = createSignal("")
  const [latestVer, setLatestVer] = createSignal("")
  const [updateAvail, setUpdateAvail] = createSignal(false)
  const [checkingVer, setCheckingVer] = createSignal(false)
  const [updatingVer, setUpdatingVer] = createSignal(false)

  const fetchLogs = async () => {
    setLoadingLogs(true)
    try {
      const res = await fetch(`http://localhost:8000/api/logs?limit=${limit()}`)
      const data = await res.json()
      setLogs(data.logs || [])
    } catch (e) {
      console.error("Failed to load logs:", e)
      setLogs(["✗ Failed to connect to Koza daemon to retrieve logs."])
    } finally {
      setLoadingLogs(false)
    }
  }

  const checkVersion = async () => {
    setCheckingVer(true)
    try {
      const res = await fetch("http://localhost:8000/api/version")
      const data = await res.json()
      setCurrentVer(data.current || "Unknown")
      setLatestVer(data.latest || "Unknown")
      setUpdateAvail(!!data.update_available)
    } catch (e) {
      console.error("Failed to fetch engine version:", e)
    } finally {
      setCheckingVer(false)
    }
  }

  onMount(() => {
    fetchLogs()
    checkVersion()
  })

  const copyLogs = () => {
    const text = logs().join("\n")
    navigator.clipboard.writeText(text)
    setActionMessage("✓ Logs copied to clipboard!")
    setTimeout(() => setActionMessage(""), 3000)
  }

  const triggerUpdate = async () => {
    setUpdatingVer(true)
    setActionMessage("Self-update triggered in background...")
    try {
      await fetch("http://localhost:8000/api/version/update", { method: "POST" })
      setTimeout(fetchLogs, 2000)
    } catch (e) {
      setActionMessage("✗ Failed to trigger update.")
    } finally {
      setUpdatingVer(false)
    }
  }

  const factoryReset = async () => {
    setActionMessage("Performing factory reset...")
    try {
      const res = await fetch("http://localhost:8000/api/clean", { method: "POST" })
      const data = await res.json()
      if (data.status === "ok") {
        setActionMessage("✓ Koza reset to factory defaults successfully. Please restart the app.")
        setResetConfirmOpen(false)
      } else {
        setActionMessage("✗ Reset failed.")
      }
    } catch (e) {
      setActionMessage("✗ Reset request failed.")
    }
  }

  return (
    <div class="settings-v2-panel">
      <div class="settings-v2-tab-header">
        <h2 class="settings-v2-tab-title">System Maintenance</h2>
      </div>
      <div class="settings-v2-tab-body">

        {/* Engine Version & Updates Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">📦 Koza Engine Update</h3>
          <SettingsListV2>
            <div data-component="settings-v2-row" class="flex flex-row justify-between items-center py-4">
              <div class="flex flex-col gap-1 flex-1 min-w-0 pr-4">
                <span class="text-[13px] font-bold text-v2-text-text-base">Version Status</span>
                <span class="text-[12px] text-v2-text-text-muted">
                  Current: <strong class="text-v2-text-text-accent">v{currentVer() || "..."}</strong> 
                  <Show when={latestVer()}>
                    {" · Latest: "}<strong>v{latestVer()}</strong>
                  </Show>
                </span>
                <Show when={updateAvail()}>
                  <span class="text-[12px] font-semibold text-yellow-500">🆕 A new engine update is available.</span>
                </Show>
              </div>
              <div class="shrink-0 flex items-center gap-2">
                <ButtonV2 variant="secondary" onClick={checkVersion} disabled={checkingVer()}>
                  {checkingVer() ? "Checking..." : "Check Now"}
                </ButtonV2>
                <Show when={updateAvail()}>
                  <ButtonV2 variant="primary" onClick={triggerUpdate} disabled={updatingVer()}>
                    {updatingVer() ? "Updating..." : "Update Engine"}
                  </ButtonV2>
                </Show>
              </div>
            </div>
          </SettingsListV2>
        </div>

        {/* Daemon Logs Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">🖥️ Koza Daemon Logs</h3>
          <div class="flex justify-between items-center mb-2">
            <span class="text-[12px] text-v2-text-text-muted">Real-time status logs of the background server:</span>
            <div class="flex items-center gap-2">
              <select 
                class="bg-transparent border border-v2-border-border-base rounded px-1 py-0.5 text-[11px] text-v2-text-text-base focus:outline-none"
                value={limit()}
                onChange={(e) => {
                  setLimit(Number(e.currentTarget.value))
                  fetchLogs()
                }}
              >
                <option value="50">50 lines</option>
                <option value="100">100 lines</option>
                <option value="200">200 lines</option>
                <option value="500">500 lines</option>
              </select>
              <ButtonV2 variant="secondary" size="small" onClick={fetchLogs} disabled={loadingLogs()}>
                {loadingLogs() ? "Refreshing..." : "Refresh"}
              </ButtonV2>
              <ButtonV2 variant="secondary" size="small" onClick={copyLogs} disabled={logs().length === 0}>
                Copy Logs
              </ButtonV2>
            </div>
          </div>
          <div class="bg-v2-background-bg-dark border border-v2-border-border-base rounded-md p-3 font-mono text-[11px] leading-relaxed text-[#a9b1d6] h-[250px] overflow-y-auto whitespace-pre-wrap select-text">
            {logs().map(line => <div>{line}</div>)}
          </div>
        </div>

        {/* Factory Reset Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title text-v2-text-text-danger">⚠️ Danger Zone</h3>
          <SettingsListV2>
            <div class="flex flex-row justify-between items-center py-4">
              <div class="flex flex-col gap-1.5 flex-1 min-w-0 pr-4">
                <span class="text-[13px] font-bold text-v2-text-text-danger">Factory Reset Koza</span>
                <span class="text-[12px] text-v2-text-text-muted">
                  Permanently deletes your configuration keys, conversation history database, and logs. This cannot be undone.
                </span>
              </div>
              <div class="shrink-0">
                <Show when={!resetConfirmOpen()}>
                  <ButtonV2 variant="danger" onClick={() => setResetConfirmOpen(true)}>Reset Defaults</ButtonV2>
                </Show>
                <Show when={resetConfirmOpen()}>
                  <div class="flex items-center gap-2">
                    <ButtonV2 variant="secondary" onClick={() => setResetConfirmOpen(false)}>Cancel</ButtonV2>
                    <ButtonV2 variant="danger" onClick={factoryReset}>Confirm Reset</ButtonV2>
                  </div>
                </Show>
              </div>
            </div>
          </SettingsListV2>
        </div>

        <div class="flex flex-col gap-2 items-end pt-4">
          <Show when={actionMessage()}>
            <span class="text-[13px] font-medium text-v2-text-text-accent">{actionMessage()}</span>
          </Show>
        </div>

      </div>
    </div>
  )
}
