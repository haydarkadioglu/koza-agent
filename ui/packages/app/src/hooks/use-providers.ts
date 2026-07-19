import { useServerSync } from "@/context/server-sync"
import { decode64 } from "@/utils/base64"
import { useParams } from "@solidjs/router"
import { Iterable, pipe } from "effect"
import type { Accessor } from "solid-js"
import { selectProviderCatalog } from "./provider-catalog"

export const popularProviders = [
  "koza",
  "anthropic",
  "openai",
  "google",
  "deepseek",
  "ollama",
  "openrouter",
  "groq",
]
const popularProviderSet = new Set(popularProviders)

const KOZA_SUPPORTED_PROVIDERS = new Set([
  "koza",
  "openai",
  "anthropic",
  "anthropic-oauth",
  "deepseek",
  "google",
  "ollama",
  "antigravity",
  "github",
  "kimi",
  "minimax",
  "zai",
  "groq",
  "openrouter",
  "lm_studio",
  "portal"
])

export function useProviders(directory?: Accessor<string | undefined>) {
  const serverSync = useServerSync()
  const params = useParams()
  const dir = () => (directory ? directory() : decode64(params.dir))
  const providers = () => {
    const value = dir()
    const projectStore = value ? serverSync().child(value)[0] : undefined
    const raw = directory
      ? selectProviderCatalog({
          explicit: true,
          directory: value,
          catalog: projectStore && { ready: projectStore.provider_ready, providers: projectStore.provider },
        })
      : selectProviderCatalog({
          explicit: false,
          directory: value,
          catalog: projectStore && { ready: projectStore.provider_ready, providers: projectStore.provider },
          global: serverSync().data.provider,
        })

    const filteredAll = new Map()
    for (const [id, provider] of raw.all.entries()) {
      if (KOZA_SUPPORTED_PROVIDERS.has(id)) {
        filteredAll.set(id, provider)
      }
    }
    
    return {
      all: filteredAll,
      connected: raw.connected.filter(id => KOZA_SUPPORTED_PROVIDERS.has(id)),
      default: raw.default
    }
  }
  return {
    all: () => providers().all,
    default: () => providers().default,
    popular: () =>
      pipe(
        providers().all,
        Iterable.map(([, p]) => p),
        Iterable.filter((p) => popularProviderSet.has(p.id)),
        (v) => Array.from(v),
      ),
    connected: () => {
      const connected = new Set(providers().connected)
      return pipe(
        providers().all,
        Iterable.map(([, p]) => p),
        Iterable.filter((p) => connected.has(p.id)),
        (v) => Array.from(v),
      )
    },
    paid: () => {
      const connected = new Set(providers().connected)
      return [
        ...Iterable.filter(
          providers().all,
          ([id]) =>
            connected.has(id) &&
            (id !== "koza" || Object.values(providers().all.get(id)?.models ?? {}).some((m) => m.cost?.input)),
        ),
      ]
    },
  }
}
