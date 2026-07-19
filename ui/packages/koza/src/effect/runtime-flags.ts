import { Config, ConfigProvider, Context, Effect, Layer, Option } from "effect"
import { ConfigService } from "@/effect/config-service"

const bool = (name: string) => Config.boolean(name).pipe(Config.withDefault(false))
const positiveInteger = (name: string) =>
  Config.number(name).pipe(
    Config.map((value) => (Number.isInteger(value) && value > 0 ? value : undefined)),
    Config.orElse(() => Config.succeed(undefined)),
  )
const experimental = bool("KOZA_EXPERIMENTAL")
const enabledByExperimental = (name: string) =>
  Config.all({ experimental, enabled: Config.boolean(name).pipe(Config.option) }).pipe(
    Config.map((flags) => Option.getOrElse(flags.enabled, () => flags.experimental)),
  )

export class Service extends ConfigService.Service<Service>()("@koza/RuntimeFlags", {
  autoShare: bool("KOZA_AUTO_SHARE"),
  pure: bool("KOZA_PURE"),
  disableDefaultPlugins: bool("KOZA_DISABLE_DEFAULT_PLUGINS"),
  disableEmbeddedWebUi: bool("KOZA_DISABLE_EMBEDDED_WEB_UI"),
  disableExternalSkills: bool("KOZA_DISABLE_EXTERNAL_SKILLS"),
  disableLspDownload: bool("KOZA_DISABLE_LSP_DOWNLOAD"),
  disableClaudeCodePrompt: Config.all({
    broad: bool("KOZA_DISABLE_CLAUDE_CODE"),
    direct: bool("KOZA_DISABLE_CLAUDE_CODE_PROMPT"),
  }).pipe(Config.map((flags) => flags.broad || flags.direct)),
  disableClaudeCodeSkills: Config.all({
    broad: bool("KOZA_DISABLE_CLAUDE_CODE"),
    direct: bool("KOZA_DISABLE_CLAUDE_CODE_SKILLS"),
  }).pipe(Config.map((flags) => flags.broad || flags.direct)),
  enableExa: Config.all({
    experimental,
    enabled: bool("KOZA_ENABLE_EXA"),
    legacy: bool("KOZA_EXPERIMENTAL_EXA"),
  }).pipe(Config.map((flags) => flags.experimental || flags.enabled || flags.legacy)),
  enableParallel: Config.all({
    enabled: bool("KOZA_ENABLE_PARALLEL"),
    legacy: bool("KOZA_EXPERIMENTAL_PARALLEL"),
  }).pipe(Config.map((flags) => flags.enabled || flags.legacy)),
  enableExperimentalModels: bool("KOZA_ENABLE_EXPERIMENTAL_MODELS"),
  enableQuestionTool: bool("KOZA_ENABLE_QUESTION_TOOL"),
  experimentalReferences: enabledByExperimental("KOZA_EXPERIMENTAL_REFERENCES"),
  experimentalBackgroundSubagents: enabledByExperimental("KOZA_EXPERIMENTAL_BACKGROUND_SUBAGENTS"),
  experimentalLspTy: bool("KOZA_EXPERIMENTAL_LSP_TY"),
  experimentalLspTool: enabledByExperimental("KOZA_EXPERIMENTAL_LSP_TOOL"),
  experimentalOxfmt: enabledByExperimental("KOZA_EXPERIMENTAL_OXFMT"),
  experimentalPlanMode: enabledByExperimental("KOZA_EXPERIMENTAL_PLAN_MODE"),
  experimentalCodeMode: enabledByExperimental("KOZA_EXPERIMENTAL_CODE_MODE"),
  experimentalEventSystem: enabledByExperimental("KOZA_EXPERIMENTAL_EVENT_SYSTEM"),
  experimentalWorkspaces: enabledByExperimental("KOZA_EXPERIMENTAL_WORKSPACES"),
  experimentalIconDiscovery: enabledByExperimental("KOZA_EXPERIMENTAL_ICON_DISCOVERY"),
  outputTokenMax: positiveInteger("KOZA_EXPERIMENTAL_OUTPUT_TOKEN_MAX"),
  bashDefaultTimeoutMs: positiveInteger("KOZA_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS"),
  experimentalNativeLlm: bool("KOZA_EXPERIMENTAL_NATIVE_LLM"),
  experimentalWebSockets: bool("KOZA_EXPERIMENTAL_WEBSOCKETS"),
  client: Config.string("KOZA_CLIENT").pipe(Config.withDefault("cli")),
}) {}

export type Info = Context.Service.Shape<typeof Service>

const emptyConfigLayer = Service.layer.pipe(
  Layer.provide(ConfigProvider.layer(ConfigProvider.fromUnknown({}))),
  Layer.orDie,
)

export const layer = (overrides: Partial<Info> = {}) =>
  Layer.effect(
    Service,
    Effect.gen(function* () {
      const flags = yield* Service
      return Service.of({ ...flags, ...overrides })
    }),
  ).pipe(Layer.provide(emptyConfigLayer))

export const node = LayerNode.make({ service: Service, layer: Service.layer.pipe(Layer.orDie), deps: [] })

export * as RuntimeFlags from "./runtime-flags"
import { LayerNode } from "@koza-ai/core/effect/layer-node"
