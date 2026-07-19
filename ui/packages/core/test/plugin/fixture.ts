import { AgentV2 } from "@koza-ai/core/agent"
import { AISDK } from "@koza-ai/core/aisdk"
import { Catalog } from "@koza-ai/core/catalog"
import { CommandV2 } from "@koza-ai/core/command"
import { Credential } from "@koza-ai/core/credential"
import { AppNodeBuilder } from "@koza-ai/core/effect/app-node-builder"
import { LayerNodePlatform } from "@koza-ai/core/effect/app-node-platform"
import { LayerNode } from "@koza-ai/core/effect/layer-node"
import { EventV2 } from "@koza-ai/core/event"
import { FileSystem } from "@koza-ai/core/filesystem"
import { FSUtil } from "@koza-ai/core/fs-util"
import { Integration } from "@koza-ai/core/integration"
import { Location } from "@koza-ai/core/location"
import { Npm } from "@koza-ai/core/npm"
import { PluginV2 } from "@koza-ai/core/plugin"
import { Reference } from "@koza-ai/core/reference"
import { SkillV2 } from "@koza-ai/core/skill"
import { Effect, Layer } from "effect"
import { tempLocationLayer } from "../fixture/location"

const npmLayer = Layer.succeed(
  Npm.Service,
  Npm.Service.of({
    add: () => Effect.succeed({ directory: "", entrypoint: undefined }),
    install: () => Effect.void,
    which: () => Effect.succeed(undefined),
  }),
)

export const PluginTestLayer = AppNodeBuilder.build(
  LayerNode.group([
    FileSystem.node,
    FSUtil.node,
    Location.node,
    Npm.node,
    Credential.node,
    EventV2.node,
    LayerNodePlatform.httpClient,
    PluginV2.node,
    AgentV2.node,
    AISDK.node,
    Catalog.node,
    CommandV2.node,
    Integration.node,
    Reference.node,
    SkillV2.node,
  ]),
  [
    [Location.node, tempLocationLayer],
    [Npm.node, npmLayer],
  ],
)
