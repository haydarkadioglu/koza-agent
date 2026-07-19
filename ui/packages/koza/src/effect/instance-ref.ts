import { Context } from "effect"
import type { InstanceContext } from "@/project/instance-context"
import type { WorkspaceV2 } from "@koza-ai/core/workspace"

export const InstanceRef = Context.Reference<InstanceContext | undefined>("~koza/InstanceRef", {
  defaultValue: () => undefined,
})

export const WorkspaceRef = Context.Reference<WorkspaceV2.ID | undefined>("~koza/WorkspaceRef", {
  defaultValue: () => undefined,
})
