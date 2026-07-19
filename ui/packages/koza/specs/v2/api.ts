// @ts-nocheck

import { Koza } from "@koza-ai/core"
import { ReadTool } from "@koza-ai/core/tools"

const koza = Koza.make({})

koza.tool.add(ReadTool)

koza.tool.add({
  name: "bash",
  schema: {
    type: "object",
    properties: {
      command: {
        type: "string",
        description: "The command to run.",
      },
    },
    required: ["command"],
  },
  execute(input, ctx) {},
})

koza.auth.add({
  provider: "openai",
  type: "api",
  value: process.env.OPENAI_API_KEY,
})

koza.agent.add({
  name: "build",
  permissions: [],
  model: {
    id: "gpt-5-5",
    provider: "openai",
    variant: "xhigh",
  },
})

const sessionID = await koza.session.create({
  agent: "build",
})

koza.subscribe((event) => {
  console.log(event)
})

await koza.session.prompt({
  sessionID,
  text: "hey what is up",
})

await koza.session.prompt({
  sessionID,
  text: "what is up with this",
  files: [
    {
      mime: "image/png",
      uri: "data:image/png;base64,xxxx",
    },
  ],
})

await koza.session.wait()

console.log(await koza.session.messages(sessionID))
