// All settings come from environment variables (see .env.example); these are the defaults.
export const config = {
  port: Number(process.env.PORT ?? 3000),
  kafkaBrokers: (process.env.KAFKA_BROKERS ?? "localhost:9092").split(","),
  topic: process.env.KAFKA_TOPIC ?? "clicks",
  druidUrl: process.env.DRUID_URL ?? "http://localhost:8888",
  dataSource: "clickstream",
};
