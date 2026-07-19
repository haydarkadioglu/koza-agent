import { run as runTui, type TuiInput } from "@koza-ai/tui"
import { Global } from "@koza-ai/core/global"
import { AppNodeBuilder } from "@koza-ai/core/effect/app-node-builder"
import { Effect } from "effect"

export function run(input: TuiInput) {
  return runTui(input).pipe(Effect.provide(AppNodeBuilder.build(Global.node)))
}
