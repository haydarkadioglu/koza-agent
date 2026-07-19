import path from "path"
import { fileURLToPath } from "url"

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const dir = path.resolve(__dirname, "..")

process.chdir(dir)

const modelsUrl = process.env.KOZA_MODELS_URL || "https://models.dev"
export const modelsData = await (async () => {
  if (process.env.MODELS_DEV_API_JSON) {
    try {
      return await Bun.file(process.env.MODELS_DEV_API_JSON).text()
    } catch (e) {}
  }
  try {
    return await fetch(`${modelsUrl}/api.json`).then((x) => x.text())
  } catch (e) {
    console.warn("Could not fetch models.dev, loading local fixture instead.")
    const fixturePath = path.resolve(__dirname, "../../tool/fixtures/models-api.json")
    try {
      return await Bun.file(fixturePath).text()
    } catch (err) {
      return "{}"
    }
  }
})()
console.log("Loaded models.dev snapshot")
