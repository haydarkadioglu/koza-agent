declare global {
  const KOZA_VERSION: string
  const KOZA_CHANNEL: string
}

export const InstallationVersion = typeof KOZA_VERSION === "string" ? KOZA_VERSION : "local"
export const InstallationChannel = typeof KOZA_CHANNEL === "string" ? KOZA_CHANNEL : "local"
export const InstallationLocal = InstallationChannel === "local"
