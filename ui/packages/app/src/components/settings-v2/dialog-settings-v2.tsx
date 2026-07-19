import { Component, createSignal, startTransition } from "solid-js"
import { Dialog } from "@opencode-ai/ui/v2/dialog-v2"
import { TabsV2 } from "@opencode-ai/ui/v2/tabs-v2"
import { Icon } from "@opencode-ai/ui/icon"
import { useLanguage } from "@/context/language"
import { usePlatform } from "@/context/platform"
import { SettingsGeneralV2 } from "./general"
import { SettingsKeybinds } from "../settings-keybinds"
import { SettingsKozaV2 } from "./koza-engine"
import { SettingsCronV2 } from "./cron"
import { SettingsMcpV2 } from "./mcp"
import { SettingsNotificationsV2 } from "./notifications"
import { SettingsVoiceSyncV2 } from "./voice-sync"
import { SettingsMaintenanceV2 } from "./maintenance"
import "./settings-v2.css"

export const DialogSettings: Component<{
  sessionID?: string
  defaultValue?: string
}> = (props) => {
  const language = useLanguage()
  const platform = usePlatform()
  const [tab, setTab] = createSignal(props.defaultValue ?? "general")

  return (
    <Dialog size="x-large" variant="settings" class="settings-v2-dialog">
      <TabsV2
        orientation="vertical"
        variant="settings"
        value={tab()}
        onChange={(value) => void startTransition(() => setTab(value))}
        class="settings-v2"
      >
        <TabsV2.List>
          <div class="flex flex-col justify-between h-full w-full">
            <div class="flex flex-col gap-3 w-full">
              <div class="flex flex-col gap-3">
                <div class="flex flex-col gap-1.5">
                  <TabsV2.SectionTitle>{language.t("settings.section.desktop")}</TabsV2.SectionTitle>
                  <div class="flex flex-col gap-1.5 w-full">
                    <TabsV2.Trigger value="general">
                      <Icon name="sliders" />
                      {language.t("settings.tab.general")}
                    </TabsV2.Trigger>
                    <TabsV2.Trigger value="shortcuts">
                      <Icon name="keyboard" />
                      {language.t("settings.tab.shortcuts")}
                    </TabsV2.Trigger>
                  </div>
                </div>

                <div class="flex flex-col gap-1.5">
                  <TabsV2.SectionTitle>Koza Settings</TabsV2.SectionTitle>
                  <div class="flex flex-col gap-1.5 w-full">
                    <TabsV2.Trigger value="koza">
                      <Icon name="sliders" />
                      Koza Engine
                    </TabsV2.Trigger>
                    <TabsV2.Trigger value="cron">
                      <Icon name="clock" />
                      Cron Scheduler
                    </TabsV2.Trigger>
                    <TabsV2.Trigger value="mcp">
                      <Icon name="providers" />
                      MCP Servers
                    </TabsV2.Trigger>
                    <TabsV2.Trigger value="notifications">
                      <Icon name="bell" />
                      Notifications
                    </TabsV2.Trigger>
                    <TabsV2.Trigger value="voice-sync">
                      <Icon name="server" />
                      Voice & Sync
                    </TabsV2.Trigger>
                    <TabsV2.Trigger value="maintenance">
                      <Icon name="trash" />
                      System Maintenance
                    </TabsV2.Trigger>
                  </div>
                </div>
              </div>
            </div>
            <div class="settings-v2-nav-footer">
              <span>{language.t("app.name.desktop")}</span>
              <span>v{platform.version}</span>
            </div>
          </div>
        </TabsV2.List>
        <TabsV2.Content value="general" class="settings-v2-panel">
          <SettingsGeneralV2 sessionID={props.sessionID} />
        </TabsV2.Content>
        <TabsV2.Content value="shortcuts" class="settings-v2-panel">
          <SettingsKeybinds v2 />
        </TabsV2.Content>
        <TabsV2.Content value="koza" class="settings-v2-panel">
          <SettingsKozaV2 />
        </TabsV2.Content>
        <TabsV2.Content value="cron" class="settings-v2-panel">
          <SettingsCronV2 />
        </TabsV2.Content>
        <TabsV2.Content value="mcp" class="settings-v2-panel">
          <SettingsMcpV2 />
        </TabsV2.Content>
        <TabsV2.Content value="notifications" class="settings-v2-panel">
          <SettingsNotificationsV2 />
        </TabsV2.Content>
        <TabsV2.Content value="voice-sync" class="settings-v2-panel">
          <SettingsVoiceSyncV2 />
        </TabsV2.Content>
        <TabsV2.Content value="maintenance" class="settings-v2-panel">
          <SettingsMaintenanceV2 />
        </TabsV2.Content>
      </TabsV2>
    </Dialog>
  )
}
