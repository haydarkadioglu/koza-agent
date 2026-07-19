const stage = process.env.SST_STAGE || "dev"

export default {
  url: stage === "production" ? "https://koza.ai" : `https://${stage}.koza.ai`,
  console: stage === "production" ? "https://koza.ai/auth" : `https://${stage}.koza.ai/auth`,
  email: "help@anoma.ly",
  socialCard: "https://social-cards.sst.dev",
  github: "https://github.com/anomalyco/koza",
  discord: "https://koza.ai/discord",
  headerLinks: [
    { name: "app.header.home", url: "/" },
    { name: "app.header.docs", url: "/docs/" },
  ],
}
