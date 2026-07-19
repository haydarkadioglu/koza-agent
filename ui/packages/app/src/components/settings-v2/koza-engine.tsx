import { Component, createSignal, onMount, Show } from "solid-js"
import { ButtonV2 } from "@opencode-ai/ui/v2/button-v2"
import { TextInputV2 } from "@opencode-ai/ui/v2/text-input-v2"
import { SettingsListV2 } from "./parts/list"
import { SettingsRowV2 } from "./parts/row"
import "./settings-v2.css"

export const SettingsKozaV2: Component = () => {
  const [provider, setProvider] = createSignal("gemini")
  const [model, setModel] = createSignal("")
  const [fallbackProvider, setFallbackProvider] = createSignal("")
  const [fallbackModel, setFallbackModel] = createSignal("")
  const [mediaProvider, setMediaProvider] = createSignal("")
  
  const [toolApproval, setToolApproval] = createSignal(true)
  const [allowedTools, setAllowedTools] = createSignal<string[]>([])

  const [geminiKey, setGeminiKey] = createSignal("")
  const [openaiKey, setOpenaiKey] = createSignal("")
  const [openaiBaseUrl, setOpenaiBaseUrl] = createSignal("")
  const [anthropicKey, setAnthropicKey] = createSignal("")
  const [anthropicBaseUrl, setAnthropicBaseUrl] = createSignal("")
  const [deepseekKey, setDeepseekKey] = createSignal("")
  const [deepseekBaseUrl, setDeepseekBaseUrl] = createSignal("")
  const [githubToken, setGithubToken] = createSignal("")
  
  const [telegramToken, setTelegramToken] = createSignal("")
  const [telegramChatId, setTelegramChatId] = createSignal("")
  
  const [whatsappSid, setWhatsappSid] = createSignal("")
  const [whatsappToken, setWhatsappToken] = createSignal("")
  const [whatsappFrom, setWhatsappFrom] = createSignal("")
  const [whatsappTo, setWhatsappTo] = createSignal("")

  const [discordToken, setDiscordToken] = createSignal("")

  const [emailUsername, setEmailUsername] = createSignal("")
  const [emailPassword, setEmailPassword] = createSignal("")
  const [emailSmtpHost, setEmailSmtpHost] = createSignal("")
  const [emailSmtpPort, setEmailSmtpPort] = createSignal("")
  const [emailImapHost, setEmailImapHost] = createSignal("")

  const [saving, setSaving] = createSignal(false)
  const [message, setMessage] = createSignal("")

  const loadConfig = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/config")
      const cfg = await res.json()
      setProvider(cfg.provider || "gemini")
      setModel(cfg.model || "")
      setFallbackProvider(cfg.fallback_provider || "")
      setFallbackModel(cfg.fallback_model || "")
      setMediaProvider(cfg.media_provider || "")
      setToolApproval(cfg.tool_approval !== false)
      setAllowedTools(cfg.allowed_tools || [])
      
      const provs = cfg.providers || {}
      setGeminiKey(provs.gemini?.api_key || "")
      setOpenaiKey(provs.openai?.api_key || "")
      setOpenaiBaseUrl(provs.openai?.base_url || "")
      setAnthropicKey(provs.anthropic?.api_key || "")
      setAnthropicBaseUrl(provs.anthropic?.base_url || "")
      setDeepseekKey(provs.deepseek?.api_key || "")
      setDeepseekBaseUrl(provs.deepseek?.base_url || "")
      setDeepseekBaseUrl(provs.deepseek?.base_url || "")
      setGithubToken(provs.github?.token || "")

      const messaging = cfg.messaging || {}
      setTelegramToken(messaging.telegram?.token || "")
      setTelegramChatId(messaging.telegram?.chat_id || "")
      setWhatsappSid(messaging.whatsapp?.account_sid || "")
      setWhatsappToken(messaging.whatsapp?.auth_token || "")
      setWhatsappFrom(messaging.whatsapp?.from || "")
      setWhatsappTo(messaging.whatsapp?.to || "")
      setDiscordToken(messaging.discord?.token || "")

      const email = cfg.email || {}
      setEmailUsername(email.username || "")
      setEmailPassword(email.password || "")
      setEmailSmtpHost(email.smtp_host || "")
      setEmailSmtpPort(email.smtp_port || "")
      setEmailImapHost(email.imap_host || "")
    } catch (e) {
      console.error("Failed to load Koza config:", e)
    }
  }

  onMount(loadConfig)

  const saveConfig = async () => {
    setSaving(true)
    setMessage("")
    try {
      const payload = {
        provider: provider(),
        model: model(),
        fallback_provider: fallbackProvider() || null,
        fallback_model: fallbackModel() || null,
        media_provider: mediaProvider() || null,
        tool_approval: toolApproval(),
        allowed_tools: allowedTools(),
        providers: {
          gemini: { api_key: geminiKey() },
          openai: { api_key: openaiKey(), base_url: openaiBaseUrl() || null },
          anthropic: { api_key: anthropicKey(), base_url: anthropicBaseUrl() || null },
          deepseek: { api_key: deepseekKey(), base_url: deepseekBaseUrl() || null },
          github: { token: githubToken() }
        },
        messaging: {
          telegram: { token: telegramToken(), chat_id: telegramChatId() },
          whatsapp: { 
            account_sid: whatsappSid(), 
            auth_token: whatsappToken(), 
            from: whatsappFrom(), 
            to: whatsappTo() 
          },
          discord: { token: discordToken() }
        },
        email: {
          username: emailUsername(),
          password: emailPassword(),
          smtp_host: emailSmtpHost(),
          smtp_port: emailSmtpPort(),
          imap_host: emailImapHost()
        }
      }
      await fetch("http://localhost:8000/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })
      setMessage("✓ Configuration saved and Koza engine reloaded successfully!")
    } catch (e) {
      setMessage("✗ Failed to save configuration.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div class="settings-v2-panel">
      <div class="settings-v2-tab-header">
        <h2 class="settings-v2-tab-title">Koza Engine Settings</h2>
      </div>
      <div class="settings-v2-tab-body">
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Model Configuration</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Active Provider" description="Choose the active LLM provider for Koza.">
              <select 
                class="bg-transparent border border-v2-border-border-base rounded px-2 py-1 text-[13px] text-v2-text-text-base focus:outline-none"
                value={provider()} 
                onChange={(e) => setProvider(e.currentTarget.value)}
              >
                <option value="gemini">Google Gemini</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic Claude</option>
                <option value="deepseek">DeepSeek</option>
                <option value="github">GitHub Models</option>
                <option value="ollama">Ollama (Local)</option>
              </select>
            </SettingsRowV2>
            <SettingsRowV2 title="Active Model ID" description="Enter specific model ID (e.g. gemini-2.0-flash, gpt-4o). Leave empty to use Koza default.">
              <TextInputV2 
                value={model()} 
                onChange={setModel}
                placeholder="e.g. gemini-2.0-flash" 
              />
            </SettingsRowV2>
          </SettingsListV2>
        </div>

        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Fallback & Media Settings</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Fallback Provider" description="Used automatically if primary provider fails.">
              <select 
                class="bg-transparent border border-v2-border-border-base rounded px-2 py-1 text-[13px] text-v2-text-text-base focus:outline-none"
                value={fallbackProvider()} 
                onChange={(e) => setFallbackProvider(e.currentTarget.value)}
              >
                <option value="">None (Disabled)</option>
                <option value="gemini">Google Gemini</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic Claude</option>
                <option value="deepseek">DeepSeek</option>
                <option value="github">GitHub Models</option>
                <option value="ollama">Ollama (Local)</option>
              </select>
            </SettingsRowV2>
            <SettingsRowV2 title="Fallback Model ID" description="Model ID to use when primary fails.">
              <TextInputV2 
                value={fallbackModel()} 
                onChange={setFallbackModel}
                placeholder="e.g. gemini-1.5-flash" 
              />
            </SettingsRowV2>
            <SettingsRowV2 title="Media Provider" description="Used for image and video generation features.">
              <select 
                class="bg-transparent border border-v2-border-border-base rounded px-2 py-1 text-[13px] text-v2-text-text-base focus:outline-none"
                value={mediaProvider()} 
                onChange={(e) => setMediaProvider(e.currentTarget.value)}
              >
                <option value="">Same as main chat provider</option>
                <option value="gemini">Google Gemini (Imagen 3)</option>
                <option value="openai">OpenAI (DALL-E 3)</option>
              </select>
            </SettingsRowV2>
          </SettingsListV2>
        </div>

        {/* Tool Security Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Tool Security & Permissions</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Enable Tool Approval Prompts" description="Confirm actions before execution of system modifying tools.">
              <input 
                type="checkbox" 
                class="accent-v2-border-border-accent size-4 rounded cursor-pointer"
                checked={toolApproval()} 
                onChange={(e) => setToolApproval(e.currentTarget.checked)} 
              />
            </SettingsRowV2>
            <Show when={allowedTools().length > 0}>
              <SettingsRowV2 title="Allowed Tools" description="List of permanently approved tools.">
                <div class="flex flex-col gap-2 items-end w-full">
                  <div class="flex flex-wrap gap-1 max-h-[80px] overflow-y-auto border border-v2-border-border-base rounded p-1.5 w-full bg-v2-background-bg-dark font-mono text-[11px] text-v2-text-text-muted">
                    {allowedTools().map((t) => <span class="bg-[#1e1e2e] border border-[#313244] px-1.5 py-0.5 rounded text-[10px]">{t}</span>)}
                  </div>
                  <ButtonV2 variant="secondary" size="small" onClick={() => setAllowedTools([])}>Clear Approved Tools</ButtonV2>
                </div>
              </SettingsRowV2>
            </Show>
          </SettingsListV2>
        </div>

        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Provider API Keys</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Gemini API Key" description="Google AI Studio Gemini API Key.">
              <TextInputV2 
                value={geminiKey()} 
                onChange={setGeminiKey} 
                type="password"
                placeholder="AIzaSy..." 
              />
            </SettingsRowV2>
            <SettingsRowV2 title="OpenAI API Key" description="Standard OpenAI platform API Key.">
              <div class="flex flex-col gap-2 w-full">
                <TextInputV2 
                  value={openaiKey()} 
                  onChange={setOpenaiKey} 
                  type="password"
                  placeholder="sk-proj-..." 
                />
                <TextInputV2 
                  value={openaiBaseUrl()} 
                  onChange={setOpenaiBaseUrl} 
                  placeholder="Base URL (e.g. https://api.openai.com/v1)" 
                />
              </div>
            </SettingsRowV2>
            <SettingsRowV2 title="Anthropic API Key" description="Anthropic Console API Key.">
              <div class="flex flex-col gap-2 w-full">
                <TextInputV2 
                  value={anthropicKey()} 
                  onChange={setAnthropicKey} 
                  type="password"
                  placeholder="sk-ant-..." 
                />
                <TextInputV2 
                  value={anthropicBaseUrl()} 
                  onChange={setAnthropicBaseUrl} 
                  placeholder="Base URL" 
                />
              </div>
            </SettingsRowV2>
            <SettingsRowV2 title="DeepSeek API Key" description="DeepSeek platform API Key.">
              <div class="flex flex-col gap-2 w-full">
                <TextInputV2 
                  value={deepseekKey()} 
                  onChange={setDeepseekKey} 
                  type="password"
                  placeholder="sk-..." 
                />
                <TextInputV2 
                  value={deepseekBaseUrl()} 
                  onChange={setDeepseekBaseUrl} 
                  placeholder="Base URL" 
                />
              </div>
            </SettingsRowV2>
            <SettingsRowV2 title="GitHub Token" description="Personal Access Token for GitHub Models.">
              <TextInputV2 
                value={githubToken()} 
                onChange={setGithubToken} 
                type="password"
                placeholder="ghp_..." 
              />
            </SettingsRowV2>
          </SettingsListV2>
        </div>

        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Messaging Integrations</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Telegram Bot" description="Telegram Bot Token and User Chat ID.">
              <div class="flex flex-col gap-2 w-full">
                <TextInputV2 
                  value={telegramToken()} 
                  onChange={setTelegramToken} 
                  type="password"
                  placeholder="Bot Token (e.g. 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11)" 
                />
                <TextInputV2 
                  value={telegramChatId()} 
                  onChange={setTelegramChatId} 
                  placeholder="Your Chat ID (optional, will auto-detect when you text the bot)" 
                />
              </div>
            </SettingsRowV2>
            <SettingsRowV2 title="WhatsApp (Twilio)" description="Twilio Account SID, Auth Token, From and To Numbers.">
              <div class="flex flex-col gap-2 w-full">
                <TextInputV2 
                  value={whatsappSid()} 
                  onChange={setWhatsappSid} 
                  type="password"
                  placeholder="Account SID" 
                />
                <TextInputV2 
                  value={whatsappToken()} 
                  onChange={setWhatsappToken} 
                  type="password"
                  placeholder="Auth Token" 
                />
                <TextInputV2 
                  value={whatsappFrom()} 
                  onChange={setWhatsappFrom} 
                  placeholder="From Number (e.g. whatsapp:+14155238886)" 
                />
                <TextInputV2 
                  value={whatsappTo()} 
                  onChange={setWhatsappTo} 
                  placeholder="Default To Number (e.g. whatsapp:+90555...)" 
                />
              </div>
            </SettingsRowV2>
            <SettingsRowV2 title="Discord Bot" description="Discord Bot Token.">
              <TextInputV2 
                value={discordToken()} 
                onChange={setDiscordToken} 
                type="password"
                placeholder="Discord Bot Token (MTA...)" 
              />
            </SettingsRowV2>
          </SettingsListV2>
        </div>

        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Email Integration</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Email Credentials" description="Your IMAP/SMTP credentials (use App Passwords for Gmail/Outlook).">
              <div class="flex flex-col gap-2 w-full">
                <TextInputV2 
                  value={emailUsername()} 
                  onChange={setEmailUsername} 
                  placeholder="Email Address (e.g. user@gmail.com)" 
                />
                <TextInputV2 
                  value={emailPassword()} 
                  onChange={setEmailPassword} 
                  type="password"
                  placeholder="App Password" 
                />
              </div>
            </SettingsRowV2>
            <SettingsRowV2 title="Server Configuration" description="SMTP (Sending) and IMAP (Reading) server hostnames and ports.">
              <div class="flex flex-col gap-2 w-full">
                <div class="flex gap-2">
                  <div class="flex-1">
                    <TextInputV2 
                      value={emailSmtpHost()} 
                      onChange={setEmailSmtpHost} 
                      placeholder="SMTP Host (e.g. smtp.gmail.com)" 
                    />
                  </div>
                  <div class="w-24">
                    <TextInputV2 
                      value={emailSmtpPort()} 
                      onChange={setEmailSmtpPort} 
                      placeholder="Port (587)" 
                    />
                  </div>
                </div>
                <TextInputV2 
                  value={emailImapHost()} 
                  onChange={setEmailImapHost} 
                  placeholder="IMAP Host (e.g. imap.gmail.com)" 
                />
              </div>
            </SettingsRowV2>
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
