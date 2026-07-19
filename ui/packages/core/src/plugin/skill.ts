/// <reference path="../markdown.d.ts" />

export * as SkillPlugin from "./skill"

import { define } from "./internal"
import { Effect } from "effect"
import { AbsolutePath } from "../schema"
import { SkillV2 } from "../skill"
import customizeKozaContent from "./skill/customize-koza.md" with { type: "text" }

export const CustomizeKozaContent = customizeKozaContent

export const Plugin = define({
  id: "skill",
  effect: Effect.fn(function* (ctx) {
    yield* ctx.skill.transform((draft) => {
      draft.source(
        SkillV2.EmbeddedSource.make({
          type: "embedded",
          skill: SkillV2.Info.make({
            name: "customize-koza",
            description:
              "Use ONLY when the user is editing or creating koza's own configuration: koza.json, koza.jsonc, files under .koza/, or files under ~/.config/koza/. Also use when creating or fixing koza agents, subagents, commands, skills, plugins, MCP servers, or permission rules. Do not use for the user's own application code, or for any project that is not configuring koza itself.",
            location: AbsolutePath.make("/builtin/customize-koza.md"),
            content: CustomizeKozaContent,
          }),
        }),
      )
    })
  }),
})
