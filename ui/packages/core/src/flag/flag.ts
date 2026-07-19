import { Config } from "effect"

export function truthy(key: string) {
  const value = process.env[key]?.toLowerCase()
  return value === "true" || value === "1"
}

const copy = process.env["KOZA_EXPERIMENTAL_DISABLE_COPY_ON_SELECT"]
const fff = process.env["KOZA_DISABLE_FFF"]

function enabledByExperimental(key: string) {
  return process.env[key] === undefined ? truthy("KOZA_EXPERIMENTAL") : truthy(key)
}

export const Flag = {
  OTEL_EXPORTER_OTLP_ENDPOINT: process.env["OTEL_EXPORTER_OTLP_ENDPOINT"],
  OTEL_EXPORTER_OTLP_HEADERS: process.env["OTEL_EXPORTER_OTLP_HEADERS"],

  KOZA_AUTO_HEAP_SNAPSHOT: truthy("KOZA_AUTO_HEAP_SNAPSHOT"),
  KOZA_GIT_BASH_PATH: process.env["KOZA_GIT_BASH_PATH"],
  KOZA_CONFIG: process.env["KOZA_CONFIG"],
  KOZA_CONFIG_CONTENT: process.env["KOZA_CONFIG_CONTENT"],
  KOZA_DISABLE_AUTOUPDATE: truthy("KOZA_DISABLE_AUTOUPDATE"),
  KOZA_ALWAYS_NOTIFY_UPDATE: truthy("KOZA_ALWAYS_NOTIFY_UPDATE"),
  KOZA_DISABLE_PRUNE: truthy("KOZA_DISABLE_PRUNE"),
  KOZA_DISABLE_TERMINAL_TITLE: truthy("KOZA_DISABLE_TERMINAL_TITLE"),
  KOZA_SHOW_TTFD: truthy("KOZA_SHOW_TTFD"),
  KOZA_DISABLE_AUTOCOMPACT: truthy("KOZA_DISABLE_AUTOCOMPACT"),
  KOZA_DISABLE_MODELS_FETCH: truthy("KOZA_DISABLE_MODELS_FETCH"),
  KOZA_DISABLE_MOUSE: truthy("KOZA_DISABLE_MOUSE"),
  KOZA_FAKE_VCS: process.env["KOZA_FAKE_VCS"],
  KOZA_SERVER_PASSWORD: process.env["KOZA_SERVER_PASSWORD"],
  KOZA_SERVER_USERNAME: process.env["KOZA_SERVER_USERNAME"],
  KOZA_DISABLE_FFF: fff === undefined ? process.platform === "win32" : truthy("KOZA_DISABLE_FFF"),

  // Experimental
  KOZA_EXPERIMENTAL_FILEWATCHER: Config.boolean("KOZA_EXPERIMENTAL_FILEWATCHER").pipe(
    Config.withDefault(false),
  ),
  KOZA_EXPERIMENTAL_DISABLE_FILEWATCHER: Config.boolean("KOZA_EXPERIMENTAL_DISABLE_FILEWATCHER").pipe(
    Config.withDefault(false),
  ),
  KOZA_EXPERIMENTAL_DISABLE_COPY_ON_SELECT:
    copy === undefined ? process.platform === "win32" : truthy("KOZA_EXPERIMENTAL_DISABLE_COPY_ON_SELECT"),
  KOZA_MODELS_URL: process.env["KOZA_MODELS_URL"],
  KOZA_MODELS_PATH: process.env["KOZA_MODELS_PATH"],
  KOZA_DB: process.env["KOZA_DB"],

  KOZA_WORKSPACE_ID: process.env["KOZA_WORKSPACE_ID"],
  KOZA_EXPERIMENTAL_WORKSPACES: enabledByExperimental("KOZA_EXPERIMENTAL_WORKSPACES"),

  // Evaluated at access time (not module load) because tests, the CLI, and
  // external tooling set these env vars at runtime.
  get KOZA_DISABLE_PROJECT_CONFIG() {
    return truthy("KOZA_DISABLE_PROJECT_CONFIG")
  },
  get KOZA_EXPERIMENTAL_REFERENCES() {
    return enabledByExperimental("KOZA_EXPERIMENTAL_REFERENCES")
  },
  get KOZA_TUI_CONFIG() {
    return process.env["KOZA_TUI_CONFIG"]
  },
  get KOZA_CONFIG_DIR() {
    return process.env["KOZA_CONFIG_DIR"]
  },
  get KOZA_PURE() {
    return truthy("KOZA_PURE")
  },
  get KOZA_PERMISSION() {
    return process.env["KOZA_PERMISSION"]
  },
  get KOZA_PLUGIN_META_FILE() {
    return process.env["KOZA_PLUGIN_META_FILE"]
  },
  get KOZA_CLIENT() {
    return process.env["KOZA_CLIENT"] ?? "cli"
  },
}
