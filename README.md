# 🔐 AI-Driven SIEM System

<div align="center">

**Real-time security monitoring with AI-powered anomaly detection — log collection, MITRE ATT&CK enrichment, ML-based threat detection, and full visualization in a single Docker stack.**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![PyTorch](https://img.shields.io/badge/PyTorch-1.9+-red.svg)](https://pytorch.org)
[![Kafka](https://img.shields.io/badge/Apache%20Kafka-7.6-orange.svg)](https://kafka.apache.org)
[![Elasticsearch](https://img.shields.io/badge/Elasticsearch-8.13-green.svg)](https://elastic.co)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## Architecture

```
/var/log/auth.log
/var/log/syslog
       │
       ▼
  Fluent Bit          tails host logs → ships JSON to Kafka
       │
       ▼
  Apache Kafka        topic: raw-logs  (KRaft, no Zookeeper)
       │
       ├─────────────────────────────────────┐
       ▼                                     ▼
  Logstash                            AI Model (offline)
  MITRE ATT&CK tagging                Hybrid Attention LSTM Autoencoder
  timestamp fix, field cleanup        unsupervised anomaly detection
       │                              severity scoring + log classification
       ▼                                     │
  Elasticsearch ◄──────────────────────────┘
  index: logs-YYYY.MM.dd              index: anomalies-YYYY.MM.dd
       │
       ▼
  Grafana             SIEM Overview dashboard + Explore
```

**Prometheus** scrapes host metrics (node-exporter) and Kafka metrics (kafka-exporter) for infrastructure visibility.

---

## What This System Does

### Real-Time Pipeline
Every log line written to `/var/log/auth.log` or `/var/log/syslog` on the host is:
1. Picked up by **Fluent Bit** within 5 seconds
2. Published to **Kafka** as JSON
3. Consumed by **Logstash**, tagged with a **MITRE ATT&CK tactic** based on content
4. Indexed in **Elasticsearch** with fields: `message`, `mitre_tactic`, `mitre_id`, `hostname`, `@timestamp`
5. Visible in **Grafana** on the SIEM Overview dashboard

### AI Anomaly Detection (Offline Mode)
The ML model runs on raw log files and detects anomalous sequences:
- **Model:** Weighted ensemble of 3 Bi-LSTM Autoencoders with Multi-Head Self-Attention
- **Method:** Unsupervised — trained on normal logs, flags sequences with high reconstruction error
- **Output:** Anomaly type, severity (Low / Medium / High / Critical), confidence score, and the exact log lines that triggered it
- **Performance:** 94.2% precision, 91.8% recall on Linux logs

---

## MITRE ATT&CK Detection

Logstash tags every log line in real-time:

| Tactic | Technique | Triggered by |
|---|---|---|
| Credential Access | T1110 | Failed password, authentication failure, invalid user |
| Privilege Escalation | T1078 | sudo, su, privilege escalation |
| Lateral Movement | T1021 | SSH accepted, sshd connect |
| Persistence | T1053 | cron, systemd, scheduled task |

---

## Quick Start

### Prerequisites
- Docker & Docker Compose v2
- Linux host
- 4 GB RAM

### Start

```bash
git clone https://github.com/AK11105/AI-driven-SIEM-System.git
cd AI-driven-SIEM-System

cp .env.example .env
docker compose up -d
```

Wait ~60 seconds for Elasticsearch to initialize.

### Generate Security Events

```bash
# Brute force (Credential Access - T1110)
for i in {1..10}; do logger -p auth.info "Failed password for invalid user admin from 10.0.0.$i port 22 ssh2"; done

# Privilege escalation (T1078)
sudo ls /root

# Persistence (T1053)
logger "CRON[9999]: (root) CMD (/bin/bash /tmp/backdoor.sh)"

# Lateral movement (T1021)
logger -p auth.info "Accepted password for ubuntu from 192.168.1.100 port 54321 ssh2"
```

### Access

| Service | URL | Credentials |
|---|---|---|
| **Grafana SIEM Dashboard** | http://localhost:3000/d/siem-overview/siem-overview | admin / admin |
| Kafka UI | http://localhost:8080 | — |
| Elasticsearch | http://localhost:9200 | elastic / changeme |
| Prometheus | http://localhost:9090 | — |

---

## AI Log Anomaly Detection (Offline Mode)

Run the ML model on any log file:

```bash
cd model
pip install -r requirements.txt

# Full pipeline: parse + detect
python src/logAnomalyDetection/run.py --input data/logs/raw/Linux_test.log

# Hybrid mode (recommended)
python src/logAnomalyDetection/run.py --processing-mode both --input Linux_test.log
```

**Output:** JSON report in `reports/logAnomalyDetection/` with each anomaly's type, severity, confidence score, and the exact log lines that caused it.

**Anomaly types detected:** `memory_error`, `authentication_error`, `filesystem_error`, `network_error`, `permission_error`, `system_critical`

See [docs/ai-model.md](docs/ai-model.md) for model architecture, training, and all CLI flags.

---

## Verify the Pipeline

```bash
# All containers running
docker compose ps

# Elasticsearch document count
curl -s -u elastic:changeme "http://localhost:9200/logs-*/_count?pretty"

# MITRE tactic breakdown
curl -s -u elastic:changeme "http://localhost:9200/logs-*/_search?size=0" \
  -H "Content-Type: application/json" \
  -d '{"aggs":{"tactics":{"terms":{"field":"mitre_tactic.keyword"}}}}'
```

---

## Documentation

| Doc | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Full architecture, data flows, port reference, known quirks |
| [docs/deployment.md](docs/deployment.md) | Setup, start/stop, scaling |
| [docs/testing.md](docs/testing.md) | Component verification, log simulation, end-to-end smoke test |
| [docs/log-collection.md](docs/log-collection.md) | Fluent Bit config, Kafka, Logstash MITRE enrichment |
| [docs/grafana.md](docs/grafana.md) | Dashboard panels, Explore queries, alerting |
| [docs/configuration.md](docs/configuration.md) | All config files and env vars |
| [docs/ai-model.md](docs/ai-model.md) | Model architecture, training, inference pipeline |

---

## License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

*Built by [Atharva Kulkarni](https://github.com/AK11105) & [Darshan Atkari](https://github.com/atkaridarshan04)*

</div>
