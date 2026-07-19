interface ImportMetaEnv {
  readonly KOZA_CHANNEL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module "virtual:koza-server" {
  export namespace Server {
    export const listen: typeof import("../../../koza/dist/types/src/node").Server.listen
    export type Listener = import("../../../koza/dist/types/src/node").Server.Listener
  }
  export namespace Config {
    export const get: typeof import("../../../koza/dist/types/src/node").Config.get
    export type Info = import("../../../koza/dist/types/src/node").Config.Info
  }
  export const bootstrap: typeof import("../../../koza/dist/types/src/node").bootstrap
}
