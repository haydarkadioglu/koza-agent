import { Component, createSignal, onMount, Show } from "solid-js"
import { ButtonV2 } from "@opencode-ai/ui/v2/button-v2"
import { TextInputV2 } from "@opencode-ai/ui/v2/text-input-v2"
import { SettingsListV2 } from "./parts/list"
import { SettingsRowV2 } from "./parts/row"
import "./settings-v2.css"

export const SettingsNotificationsV2: Component = () => {
  const [tgToken, setTgToken] = createSignal("")
  const [tgChatId, setTgChatId] = createSignal("")
  
  const [discordWebhook, setDiscordWebhook] = createSignal("")
  const [discordToken, setDiscordToken] = createSignal("")
  const [discordChannel, setDiscordChannel] = createSignal("")
  
  const [twilioSid, setTwilioSid] = createSignal("")
  const [twilioToken, setTwilioToken] = createSignal("")
  const [twilioFrom, setTwilioFrom] = createSignal("")
  const [twilioWaFrom, setTwilioWaFrom] = createSignal("")
  const [twilioWaTo, setTwilioWaTo] = createSignal("")
  
  const [smtpHost, setSmtpHost] = createSignal("")
  const [smtpPort, setSmtpPort] = createSignal("")
  const [emailUser, setEmailUser] = createSignal("")
  const [emailPass, setEmailPass] = createSignal("")
  
  const [saving, setSaving] = createSignal(false)
  const [message, setMessage] = createSignal("")

  const loadConfig = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/config")
      const cfg = await res.json()
      
      const tg = cfg.messaging?.telegram || {}
      setTgToken(tg.token || "")
      setTgChatId(tg.chat_id || "")
      
      const disc = cfg.messaging?.discord || {}
      setDiscordWebhook(disc.webhook_url || "")
      setDiscordToken(disc.token || "")
      setDiscordChannel(disc.channel_id || "")
      
      const tw = cfg.messaging?.twilio || {}
      setTwilioSid(tw.account_sid || "")
      setTwilioToken(tw.auth_token || "")
      setTwilioFrom(tw.from_number || "")
      setTwilioWaFrom(tw.wa_from || "")
      setTwilioWaTo(tw.wa_to || "")
      
      const email = cfg.email || {}
      setSmtpHost(email.smtp_host || "")
      setSmtpPort(email.smtp_port ? String(email.smtp_port) : "")
      setEmailUser(email.username || "")
      setEmailPass(email.password || "")
    } catch (e) {
      console.error("Failed to load notifications config:", e)
    }
  }

  onMount(loadConfig)

  const saveConfig = async () => {
    setSaving(true)
    setMessage("")
    try {
      const payload = {
        messaging: {
          telegram: { token: tgToken(), chat_id: tgChatId() },
          discord: { webhook_url: discordWebhook(), token: discordToken(), channel_id: discordChannel() },
          twilio: {
            account_sid: twilioSid() || null,
            auth_token: twilioToken() || null,
            from_number: twilioFrom() || null,
            wa_from: twilioWaFrom() || null,
            wa_to: twilioWaTo() || null
          }
        },
        email: {
          smtp_host: smtpHost(),
          smtp_port: smtpPort() ? Number(smtpPort()) : null,
          username: emailUser(),
          password: emailPass()
        }
      }
      await fetch("http://localhost:8000/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })
      setMessage("✓ Notification & messaging configurations saved successfully!")
    } catch (e) {
      setMessage("✗ Failed to save configurations.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div class="settings-v2-panel">
      <div class="settings-v2-tab-header">
        <h2 class="settings-v2-tab-title">Notifications & Channel Settings</h2>
      </div>
      <div class="settings-v2-tab-body">
        
        {/* Telegram Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Telegram Alerts</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Bot Token" description="HTTP API bot token from @BotFather.">
              <TextInputV2 value={tgToken()} onChange={setTgToken} type="password" placeholder="e.g. 123456:ABC-DEF..." />
            </SettingsRowV2>
            <SettingsRowV2 title="Chat ID" description="Telegram target chat/user ID for notifications.">
              <TextInputV2 value={tgChatId()} onChange={setTgChatId} placeholder="e.g. 987654321" />
            </SettingsRowV2>
          </SettingsListV2>
        </div>

        {/* Discord Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Discord Alerts</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Webhook URL" description="Target Discord server channel webhook integration URL.">
              <TextInputV2 value={discordWebhook()} onChange={setDiscordWebhook} type="password" placeholder="https://discord.com/api/webhooks/..." />
            </SettingsRowV2>
            <SettingsRowV2 title="Bot Token (Optional)" description="Discord developer application bot token.">
              <TextInputV2 value={discordToken()} onChange={setDiscordToken} type="password" placeholder="MTc..." />
            </SettingsRowV2>
            <SettingsRowV2 title="Channel ID (Optional)" description="Specific channel ID to send messages.">
              <TextInputV2 value={discordChannel()} onChange={setDiscordChannel} placeholder="e.g. 1122334455..." />
            </SettingsRowV2>
          </SettingsListV2>
        </div>

        {/* Twilio Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Twilio Integration (SMS & WhatsApp)</h3>
          <SettingsListV2>
            <SettingsRowV2 title="Account SID" description="Twilio Account SID (starts with AC).">
              <TextInputV2 value={twilioSid()} onChange={setTwilioSid} placeholder="e.g. ACxxxxxxxxxxxxxxxxxxxxxxxx" />
            </SettingsRowV2>
            <SettingsRowV2 title="Auth Token" description="Twilio Authentication Token.">
              <TextInputV2 value={twilioToken()} onChange={setTwilioToken} type="password" placeholder="••••••••••••••••••••••••••••••••" />
            </SettingsRowV2>
            <SettingsRowV2 title="Twilio Phone Number" description="Phone number for outgoing SMS or calls (e.g. +14155552671).">
              <TextInputV2 value={twilioFrom()} onChange={setTwilioFrom} placeholder="e.g. +14155552671" />
            </SettingsRowV2>
            <SettingsRowV2 title="WhatsApp Sender" description="Twilio WhatsApp sender number.">
              <TextInputV2 value={twilioWaFrom()} onChange={setTwilioWaFrom} placeholder="e.g. +14155238886" />
            </SettingsRowV2>
            <SettingsRowV2 title="Default WA Recipient" description="Default WhatsApp recipient number for notifications.">
              <TextInputV2 value={twilioWaTo()} onChange={setTwilioWaTo} placeholder="e.g. +905551234567" />
            </SettingsRowV2>
          </SettingsListV2>
        </div>

        {/* Email SMTP Section */}
        <div class="settings-v2-section">
          <h3 class="settings-v2-section-title">Email (SMTP) Client</h3>
          <SettingsListV2>
            <SettingsRowV2 title="SMTP Server Host" description="Outgoing mail server address.">
              <TextInputV2 value={smtpHost()} onChange={setSmtpHost} placeholder="e.g. smtp.gmail.com" />
            </SettingsRowV2>
            <SettingsRowV2 title="SMTP Port" description="SMTP mail server port (usually 587 or 465).">
              <TextInputV2 value={smtpPort()} onChange={setSmtpPort} placeholder="e.g. 587" />
            </SettingsRowV2>
            <SettingsRowV2 title="Username" description="Email address for authentication.">
              <TextInputV2 value={emailUser()} onChange={setEmailUser} placeholder="e.g. user@gmail.com" />
            </SettingsRowV2>
            <SettingsRowV2 title="Password" description="SMTP account password or App-specific password.">
              <TextInputV2 value={emailPass()} onChange={setEmailPass} type="password" placeholder="••••••••••••••••" />
            </SettingsRowV2>
          </SettingsListV2>
        </div>

        <div class="flex flex-col gap-2 items-end pt-4">
          <Show when={message()}>
            <span class="text-[13px] font-medium text-v2-text-text-accent">{message()}</span>
          </Show>
          <ButtonV2 variant="primary" onClick={saveConfig} disabled={saving()}>
            {saving() ? "Saving..." : "Save Config"}
          </ButtonV2>
        </div>

      </div>
    </div>
  )
}
