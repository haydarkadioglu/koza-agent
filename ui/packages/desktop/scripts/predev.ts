import { $ } from "bun"

await $`bun ./scripts/copy-icons.ts ${process.env.KOZA_CHANNEL ?? "dev"}`

await $`cd ../koza && bun script/build-node.ts`
