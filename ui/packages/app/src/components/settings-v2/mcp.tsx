import { Component, createSignal, onMount, Show, For } from "solid-js"
import { ButtonV2 } from "@koza-ai/ui/v2/button-v2"
import { TextInputV2 } from "@koza-ai/ui/v2/text-input-v2"
import { SettingsListV2 } from "./parts/list"
import { SettingsRowV2 } from "./parts/row"
import "./settings-v2.css"

interface MCPServer {
  name: string
  url?: string
  command?: string
  args?: string[]
}

export const SettingsMcpV2: Component = () => {
  const [servers, setServers] = createSignal<[string, MCPServer][]>([])
  const [name, setName] = createSignal("")
  const [mcpType, setMcpType] = createSignal("stdio")
  const [commandOrUrl, setCommandOrUrl] = createSignal("")
  const [argsStr, setArgsStr] = createSignal("")
  const [message, setMessage] = createSignal("")

  const loadServers = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/mcp")
      const data = await res.json()
      if (data && typeof data === "object") {
        setServers(Object.entries(data))
      }
    } catch (e) {
      console.error("Failed to load MCP servers:", e)
    }
  }

  onMount(loadServers)

  const addServer = async () => {
    if (!name() || !commandOrUrl()) {
      setMessage("⚠️ Server name and command/URL are required.")
      return
    }
    
    try {
      const payload: any = { name: name() }
      if (mcpType() === "http") {
        payload.url = commandOrUrl()
      } else {
        payload.command = commandOrUrl()
        if (argsStr()) {
          payload.args = argsStr().split(" ").filter(Boolean)
        }
      }
      
      const res = await fetch("http://localhost:8000/api/mcp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })
      const data = await res.json()
      if (data.status === "ok") {
        setName("")
        setCommandOrUrl("")
        setArgsStr("")
        setMessage("✓ MCP Server added and reloaded successfully!")
        loadServers()
      } else {
        setMessage(`✗ Error: ${data.error || "Failed to add server"}`)
      }
    } catch (e) {
      setMessage("✗ Failed to contact API server.")
    }
  }

  const deleteServer = async (serverName: string) => {
    try {
      await fetch(`http://localhost:8000/api/mcp/${encodeURIComponent(serverName)}`, {
        method: "DELETE"
      })
      loadServers()
    } catch (e) {
      console.error("Failed to delete MCP server:", e)
    }
  }

  return (
    <div class="settings-v2-panel">
      <div class="settings-v2-tab-header">
        <h2 class="settings-v2-tab-title">Model Context Protocol (MCP) Tools</h2>
      </div>
      <div class="settings-v2-tab-body">

        {/* Add Server Form */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Add New MCP Server</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Server Name" description="Unique identifier for this MCP server.">
              <TextInputV2 value={name()} onChange={setName} placeholder="e.g. sqlite-server" />
            </SettingsRowV2>
            <SettingsRowV2 title="Connection Type" description="Select standard Stdio process or HTTP url.">
              <select 
                class="bg-transparent border border-v2-border-border-base rounded px-2 py-1 text-[13px] text-v2-text-text-base focus:outline-none"
                value={mcpType()} 
                onChange={(e) => setMcpType(e.currentTarget.value)}
              >
                <option value="stdio">Local Stdio Subprocess</option>
                <option value="http">Remote HTTP Endpoint</option>
              </select>
            </SettingsRowV2>
            <SettingsRowV2 
              title={mcpType() === "http" ? "Server URL" : "Executable / Command"} 
              description={mcpType() === "http" ? "Fully qualified URL of the server." : "Command executable in PATH (e.g. npx, node, python)."}
            >
              <TextInputV2 value={commandOrUrl()} onChange={setCommandOrUrl} placeholder={mcpType() === "http" ? "https://..." : "npx"} />
            </SettingsRowV2>
            <Show when={mcpType() === "stdio"}>
              <SettingsRowV2 title="Command Arguments" description="Space-separated list of arguments.">
                <TextInputV2 value={argsStr()} onChange={setArgsStr} placeholder="e.g. -y @modelcontextprotocol/server-sqlite --db /path/to/db.sqlite" />
              </SettingsRowV2>
            </Show>
          </SettingsListV2>
          <div class="flex justify-between items-center mt-2">
            <span class="text-[13px] font-medium text-v2-text-text-accent">{message()}</span>
            <ButtonV2 variant="primary" onClick={addServer}>Connect MCP Server</ButtonV2>
          </div>
        </div>

        {/* Servers List */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Connected MCP Servers</h3>
          <Show when={servers().length === 0} fallback={
            <SettingsListV2>
              <For each={servers()}>{([sName, sCfg]) => (
                <div data-component="settings-v2-row" class="flex flex-row justify-between items-center py-4 border-b border-v2-border-border-base last:border-0">
                  <div class="flex flex-col gap-1 flex-1 min-w-0 pr-4">
                    <div class="flex flex-row gap-2 items-center">
                      <span class="text-[13px] font-bold text-v2-text-text-base">{sName}</span>
                      <span class="text-[10px] font-medium px-1.5 py-0.5 rounded bg-v2-background-bg-layer-02 text-v2-text-text-muted border border-v2-border-border-muted uppercase">
                        {sCfg.url ? "http" : "stdio"}
                      </span>
                    </div>
                    <code class="text-[12px] text-v2-text-text-muted truncate select-text bg-transparent p-0 w-full max-w-full">
                      {sCfg.url || `${sCfg.command} ${(sCfg.args || []).join(" ")}`}
                    </code>
                  </div>
                  <div class="shrink-0">
                    <ButtonV2 variant="secondary" class="!text-v2-text-text-danger" onClick={() => deleteServer(sName)}>Disconnect</ButtonV2>
                  </div>
                </div>
              )}</For>
            </SettingsListV2>
          }>
            <div class="text-center py-8 text-v2-text-text-muted text-[13px] border border-dashed border-v2-border-border-muted rounded-lg">
              No active MCP servers connected. Add one using the form above.
            </div>
          </Show>
        </div>

      </div>
    </div>
  )
}
