import { Kafka, logLevel, Partitioners } from "kafkajs";
import { config } from "./config.js";

export const kafka = new Kafka({
  clientId: "clickstream-app",
  brokers: config.kafkaBrokers,
  logLevel: logLevel.WARN,
});

// Explicit: KafkaJS's default (Java-compatible murmur2) partitioner, so a key maps to the same partition as in Java clients.
const producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner });

/** Connect once at startup, before accepting requests. */
export async function connectProducer() {
  await producer.connect();
}

export async function disconnectProducer() {
  await producer.disconnect();
}

/** Publish one click event. The user ID is the message key, so one user's clicks stay in order on one partition. */
export async function sendClick(event) {
  await producer.send({
    topic: config.topic,
    messages: [{ key: event.userId, value: JSON.stringify(event) }],
  });
}
