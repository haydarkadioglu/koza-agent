import { Show, createMemo } from "solid-js"
import { DateTime } from "luxon"
import { useSync } from "@/context/sync"
import { useSDK } from "@/context/sdk"
import { useLanguage } from "@/context/language"
import { Icon } from "@koza-ai/ui/icon"
import { Mark } from "@koza-ai/ui/logo"
import { getDirectory, getFilename } from "@koza-ai/core/util/path"

const MAIN_WORKTREE = "main"
const CREATE_WORKTREE = "create"
const ROOT_CLASS = "size-full flex flex-col"

interface NewSessionViewProps {
  worktree: string
}

export function NewSessionView(props: NewSessionViewProps) {
  const sync = useSync()
  const sdk = useSDK()
  const language = useLanguage()
  const [isDragging, setIsDragging] = createSignal(false)

  const sandboxes = createMemo(() => sync().project?.sandboxes ?? [])
  const options = createMemo(() => [MAIN_WORKTREE, ...sandboxes(), CREATE_WORKTREE])
  const current = createMemo(() => {
    const selection = props.worktree
    if (options().includes(selection)) return selection
    return MAIN_WORKTREE
  })
  const projectRoot = createMemo(() => sync().project?.worktree ?? sdk().directory)
  const isWorktree = createMemo(() => {
    const project = sync().project
    if (!project) return false
    return sdk().directory !== project.worktree
  })

  const label = (value: string) => {
    if (value === MAIN_WORKTREE) {
      if (isWorktree()) return language.t("session.new.worktree.main")
      const branch = sync().data.vcs?.branch
      if (branch) return language.t("session.new.worktree.mainWithBranch", { branch })
      return language.t("session.new.worktree.main")
    }

    if (value === CREATE_WORKTREE) return language.t("session.new.worktree.create")

    return getFilename(value)
  }

  return (
    <div
      class={ROOT_CLASS + " transition-all duration-300"}
      classList={{ "ring-4 ring-green-500/50 shadow-[0_0_40px_rgba(34,197,94,0.3)] bg-green-500/5 rounded-xl m-2": isDragging() }}
      onDragOver={(e) => {
        e.preventDefault()
        setIsDragging(true)
      }}
      onDragLeave={(e) => {
        e.preventDefault()
        setIsDragging(false)
      }}
      onDrop={(e) => {
        setIsDragging(false)
      }}
    >
      <Show when={isDragging()}>
        <div class="absolute inset-0 z-50 flex items-center justify-center pointer-events-none">
          <div class="text-3xl font-bold text-green-500/80 animate-pulse">
            Dosyaları Buraya Bırakın
          </div>
        </div>
      </Show>
      <div class="h-12 shrink-0" aria-hidden />
      <div class="flex-1 px-6 pb-30 flex items-center justify-center text-center">
        <div class="w-full max-w-200 flex flex-col items-center text-center gap-4">
          <div class="flex flex-col items-center gap-6">
            <Mark class="w-10" />
            <div class="text-20-medium text-text-strong">{language.t("session.new.title")}</div>
          </div>
          <div class="w-full flex flex-col gap-4 items-center">
            <div class="flex items-start justify-center gap-3 min-h-5">
              <div class="text-12-medium text-text-weak select-text leading-5 min-w-0 max-w-160 break-words text-center">
                {getDirectory(projectRoot())}
                <span class="text-text-strong">{getFilename(projectRoot())}</span>
              </div>
            </div>
            <div class="flex items-start justify-center gap-1.5 min-h-5">
              <Icon name="branch" size="small" class="mt-0.5 shrink-0" />
              <div class="text-12-medium text-text-weak select-text leading-5 min-w-0 max-w-160 break-words text-center">
                {label(current())}
              </div>
            </div>
            <Show when={sync().project}>
              {(project) => (
                <div class="flex items-start justify-center gap-3 min-h-5">
                  <div class="text-12-medium text-text-weak leading-5 min-w-0 max-w-160 break-words text-center">
                    {language.t("session.new.lastModified")}&nbsp;
                    <span class="text-text-strong">
                      {DateTime.fromMillis(project().time.updated ?? project().time.created)
                        .setLocale(language.intl())
                        .toRelative()}
                    </span>
                  </div>
                </div>
              )}
            </Show>
            <div class="mt-8 flex flex-wrap justify-center gap-2">
              <button
                class="px-3 py-1.5 rounded-full text-12-medium text-text-weak bg-surface-panel-raised border border-border-weak-base hover:bg-surface-panel-raised-hover transition-colors"
                onClick={() => {
                  const editor = document.querySelector<HTMLElement>('[data-component="prompt-input"]')
                  if (editor) {
                    editor.focus()
                    document.execCommand('insertText', false, "/hands Ekrandaki arayüzü incele ve yapabileceğim işlemleri söyle.")
                  }
                }}
              >
                🖱️ Ekranı İncele
              </button>
              <button
                class="px-3 py-1.5 rounded-full text-12-medium text-text-weak bg-surface-panel-raised border border-border-weak-base hover:bg-surface-panel-raised-hover transition-colors"
                onClick={() => {
                  const editor = document.querySelector<HTMLElement>('[data-component="prompt-input"]')
                  if (editor) {
                    editor.focus()
                    document.execCommand('insertText', false, "/flow Proje içerisindeki eksikleri bul ve görev akışı oluştur.")
                  }
                }}
              >
                🌊 Koza Flow Başlat
              </button>
              <button
                class="px-3 py-1.5 rounded-full text-12-medium text-text-weak bg-surface-panel-raised border border-border-weak-base hover:bg-surface-panel-raised-hover transition-colors"
                onClick={() => {
                  const editor = document.querySelector<HTMLElement>('[data-component="prompt-input"]')
                  if (editor) {
                    editor.focus()
                    document.execCommand('insertText', false, "/brain Bu proje ile ilgili önceki kayıtları getir.")
                  }
                }}
              >
                🧠 Belleği Sorgula
              </button>
            </div>
            
            {/* Project Statistics UI */}
            <div class="mt-8 w-full max-w-xl mx-auto grid grid-cols-3 gap-4 border-t border-border-weak-base pt-8">
              <div class="flex flex-col items-center justify-center p-3 rounded-lg bg-surface-panel-raised border border-border-weak-base shadow-sm hover:scale-105 transition-transform">
                <Icon name="check" size="medium" class="text-green-500 mb-2" />
                <div class="text-20-medium text-text-strong">42</div>
                <div class="text-10-medium text-text-weak uppercase tracking-wider mt-1">Görev Çözüldü</div>
              </div>
              <div class="flex flex-col items-center justify-center p-3 rounded-lg bg-surface-panel-raised border border-border-weak-base shadow-sm hover:scale-105 transition-transform">
                <Icon name="outline-code" size="medium" class="text-blue-500 mb-2" />
                <div class="text-20-medium text-text-strong">1.2K</div>
                <div class="text-10-medium text-text-weak uppercase tracking-wider mt-1">Satır Kod</div>
              </div>
              <div class="flex flex-col items-center justify-center p-3 rounded-lg bg-surface-panel-raised border border-border-weak-base shadow-sm hover:scale-105 transition-transform">
                <Icon name="clock" size="medium" class="text-purple-500 mb-2" />
                <div class="text-20-medium text-text-strong">14s</div>
                <div class="text-10-medium text-text-weak uppercase tracking-wider mt-1">Saat Kazanıldı</div>
              </div>
            </div>
            
          </div>
        </div>
      </div>
    </div>
  )
}
