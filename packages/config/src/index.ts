export const siteConfig = {
  name: "Polymeteo",
  description: "Weather Copy Trading Bot for Polymarket",
  url: "https://polymeteo.app",
  keywords: ["polymarket", "copy-trading", "weather", "prediction-market"],
};

export const apiConfig = {
  polymarketApiUrl: "https://clob.polymarket.com",
  graphqlEndpoint: "/graphql",
  wsEndpoint: "wss://ws-subscriptions-clob.polymarket.com/ws",
};

export const tradingConfig = {
  defaultKellyFraction: 0.25,
  maxPositionSize: 5000,
  stopLossPercent: 2.0,
  takeProfitPercent: 5.0,
  signalConfidenceThreshold: 0.7,
};

export const walletWeights = {
  smartBot: 1.5,
  smartTrader: 1.2,
  whale: 0.8,
  regular: 1.0,
};

export const categories = [
  "sports",
  "politics",
  "economics",
  "weather",
  "crypto",
  "other",
] as const;

export type Category = (typeof categories)[number];
