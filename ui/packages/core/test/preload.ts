import path from "path"

process.env.KOZA_DB = ":memory:"
process.env.KOZA_MODELS_PATH = path.join(import.meta.dir, "plugin", "fixtures", "models-dev.json")
process.env.KOZA_DISABLE_MODELS_FETCH = "true"
