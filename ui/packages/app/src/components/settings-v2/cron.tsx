import { Component, createSignal, onMount, Show, For } from "solid-js"
import { ButtonV2 } from "@opencode-ai/ui/v2/button-v2"
import { TextInputV2 } from "@opencode-ai/ui/v2/text-input-v2"
import { SettingsListV2 } from "./parts/list"
import { SettingsRowV2 } from "./parts/row"
import "./settings-v2.css"

interface CronJob {
  id: number
  name: string
  command: string
  cron_expr: string
}

export const SettingsCronV2: Component = () => {
  const [jobs, setJobs] = createSignal<CronJob[]>([])
  const [name, setName] = createSignal("")
  const [command, setCommand] = createSignal("")
  const [cronExpr, setCronExpr] = createSignal("*/5 * * * *")
  const [loading, setLoading] = createSignal(false)
  const [message, setMessage] = createSignal("")

  const loadJobs = async () => {
    setLoading(true)
    try {
      const res = await fetch("http://localhost:8000/api/cron")
      const data = await res.json()
      if (Array.isArray(data)) {
        setJobs(data)
      }
    } catch (e) {
      console.error("Failed to load cron jobs:", e)
    } finally {
      setLoading(false)
    }
  }

  onMount(loadJobs)

  const createJob = async () => {
    if (!name() || !command() || !cronExpr()) {
      setMessage("⚠️ Name, command and cron expression are required.")
      return
    }
    try {
      const res = await fetch("http://localhost:8000/api/cron", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name(), command: command(), cron_expr: cronExpr() })
      })
      const data = await res.json()
      if (data.status === "ok") {
        setName("")
        setCommand("")
        setCronExpr("*/5 * * * *")
        setMessage("✓ Scheduled cron job successfully!")
        loadJobs()
      } else {
        setMessage(`✗ Error: ${data.error || "Failed to create job"}`)
      }
    } catch (e) {
      setMessage("✗ Failed to contact API server.")
    }
  }

  const deleteJob = async (id: number) => {
    try {
      await fetch(`http://localhost:8000/api/cron/${id}`, { method: "DELETE" })
      loadJobs()
    } catch (e) {
      console.error("Failed to delete cron job:", e)
    }
  }

  const triggerJob = async (id: number) => {
    try {
      const res = await fetch(`http://localhost:8000/api/cron/trigger/${id}`, { method: "POST" })
      const data = await res.json()
      if (data.status === "ok") {
        setMessage("✓ Job triggered in background!")
      } else {
        setMessage(`✗ Error: ${data.error}`)
      }
    } catch (e) {
      console.error("Failed to trigger job:", e)
    }
  }

  return (
    <div class="settings-v2-panel">
      <div class="settings-v2-tab-header">
        <h2 class="settings-v2-tab-title">Cron Scheduler & Tasks</h2>
      </div>
      <div class="settings-v2-tab-body">
        
        {/* New Job Form */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Schedule New Cron Job</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Job Name" description="Give a friendly name to identify the job.">
              <TextInputV2 value={name()} onChange={setName} placeholder="e.g. Clean workspace logs" />
            </SettingsRowV2>
            <SettingsRowV2 title="Command / Talimat" description="Bash/PowerShell command, or agent script prefixed with @agent:">
              <TextInputV2 value={command()} onChange={setCommand} placeholder="e.g. @agent: check inbox and clean old items" />
            </SettingsRowV2>
            <SettingsRowV2 title="Cron Expression" description="5-field standard cron syntax.">
              <TextInputV2 value={cronExpr()} onChange={setCronExpr} placeholder="e.g. */5 * * * *" />
            </SettingsRowV2>
          </SettingsListV2>
          <div class="flex justify-between items-center mt-2">
            <span class="text-[13px] font-medium text-v2-text-text-accent">{message()}</span>
            <ButtonV2 variant="primary" onClick={createJob}>Schedule Job</ButtonV2>
          </div>
        </div>

        {/* Existing Jobs List */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Active Scheduled Jobs</h3>
          <Show when={jobs().length === 0} fallback={
            <SettingsListV2>
              <For each={jobs()}>{(job) => (
                <div data-component="settings-v2-row" class="flex flex-row justify-between items-center py-4 border-b border-v2-border-border-base last:border-0">
                  <div class="flex flex-col gap-1.5 flex-1 min-w-0 pr-4">
                    <span class="text-[13px] font-bold text-v2-text-text-base">{job.name}</span>
                    <code class="text-[11px] text-v2-text-text-muted bg-v2-background-bg-layer-02 px-1.5 py-0.5 rounded w-max select-text">{job.cron_expr}</code>
                    <span class="text-[12px] text-v2-text-text-muted truncate select-text">{job.command}</span>
                  </div>
                  <div class="flex flex-row gap-2 shrink-0">
                    <ButtonV2 variant="secondary" onClick={() => triggerJob(job.id)}>Run Now</ButtonV2>
                    <ButtonV2 variant="secondary" class="!text-v2-text-text-danger" onClick={() => deleteJob(job.id)}>Delete</ButtonV2>
                  </div>
                </div>
              )}</For>
            </SettingsListV2>
          }>
            <div class="text-center py-8 text-v2-text-text-muted text-[13px] border border-dashed border-v2-border-border-muted rounded-lg">
              No active scheduled cron tasks. Use the form above to add one.
            </div>
          </Show>
        </div>

      </div>
    </div>
  )
}
