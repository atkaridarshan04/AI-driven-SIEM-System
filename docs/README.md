# Documentation Index — AI-Driven SIEM System

This directory contains the complete technical documentation for the AI-Driven SIEM System.
All documents reflect the **current state of the codebase as of April 2026 (V1.5)**.

---

## Documents

| File | What it covers |
|------|---------------|
| [architecture.md](./architecture.md) | System design, component relationships, data flow |
| [ai-model.md](./ai-model.md) | LSTM autoencoder, training, inference pipeline |
| [log-collection.md](./log-collection.md) | Kafka, Filebeat, log consumer |
| [dashboard.md](./dashboard.md) | Next.js frontend, Express backend, MongoDB, Socket.IO |
| [api-reference.md](./api-reference.md) | All HTTP and WebSocket endpoints |
| [configuration.md](./configuration.md) | Every config file and environment variable |
| [improvements.md](./improvements.md) | Known issues and planned V2.0 improvements |
| [future.md](./future.md) | V3.0+ roadmap and research directions |

---

## Current Version: V1.5

**What works end-to-end today:**
- BRAIN log parser → structured CSV
- Ensemble Bi-LSTM autoencoder anomaly detection on Linux logs
- Severity classification (Low / Medium / High / Critical)
- Log type classification (6 categories via LDA seed patterns)
- Express/MongoDB backend receiving anomaly results
- Next.js dashboard with real-time Socket.IO updates
- Kafka + Filebeat log streaming (requires manual IP configuration)

**What is not yet production-ready:**
- Hardcoded IP addresses in Kafka/Filebeat configs
- No authentication on any API endpoint
- MongoDB URI is an empty string in committed code
- `LabeledLDAClassifier.fit()` is never called — classifier runs in seed-pattern-only mode
- No automated tests
- No Docker Compose for the full system (only Kafka stack is containerized)
