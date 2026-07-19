export * from "./client.js"
export * from "./server.js"

import { createKozaClient } from "./client.js"
import { createKozaServer } from "./server.js"
import type { ServerOptions } from "./server.js"

export * as data from "./data.js"

export async function createKoza(options?: ServerOptions) {
  const server = await createKozaServer({
    ...options,
  })

  const client = createKozaClient({
    baseUrl: server.url,
  })

  return {
    client,
    server,
  }
}
