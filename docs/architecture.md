# System Architecture — V2.0

## Overview

The V2.0 system is a production-grade SIEM built around a single streaming pipeline
that flows from host logs through Kafka into Elasticsearch, visualized via Grafana.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  Host Machine                                                        │
│  /var/log/auth.log   /var/log/syslog                                │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ volume mount (read-only)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Fluent Bit (Docker)                                                  │
│  - tails /var/log/auth.log and /var/log/syslog via inotify           │
│  - filters out its own log lines (grep filter)                       │
│  - adds hostname field (record_modifier filter)                      │
│  - encodes each line as JSON                                         │
│  - flushes to Kafka every 5 seconds                                  │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ topic: raw-logs
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Apache Kafka — KRaft mode (no Zookeeper)                            │
│  Single broker  |  topic: raw-logs  |  UI at :8080                  │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ consumer group: logstash-consumer
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Logstash                                                             │
│  - fixes @timestamp (Fluent Bit sends Unix float → ISO)              │
│  - renames 'log' field → 'message'                                   │
│  - tags MITRE ATT&CK tactic + technique ID via regex                 │
│  - removes noisy fields (event, @version)                            │
│  - writes to Elasticsearch index: logs-YYYY.MM.dd                   │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Elasticsearch (single-node, X-Pack security enabled)                │
│  Index: logs-YYYY.MM.dd  — all logs, enriched with MITRE fields     │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
┌─────────────────────┐    ┌────────────────────────────────────────────┐
│  Grafana             │    │  Prometheus                                │
│  Datasource: ES      │    │  Scrapes:                                 │
│  - SIEM Overview     │    │  - node-exporter :9100 (CPU/mem/disk)    │
│    dashboard         │    │  - kafka-exporter :9308 (lag/throughput) │
│  - Explore (ad-hoc)  │    │                                            │
│  - Alerting rules    │◄───│  Grafana datasource: Prometheus           │
└──────────────────────┘    └────────────────────────────────────────────┘
```

---

## Component Responsibilities

### Fluent Bit
- Sole log collector — reads from host `/var/log/*` via mounted volume
- Stateless, minimal footprint (~5 MB RAM)
- Does no parsing or enrichment — just gets lines into Kafka reliably
- Uses inotify to detect new lines instantly; flushes every 5 seconds

### Kafka (KRaft)
- Decouples log producers from consumers
- Allows multiple consumers (Logstash, future Model API) to read independently
- Acts as a buffer — if Logstash is slow, logs queue rather than being dropped
- KRaft mode: no Zookeeper dependency

### Logstash
- Consumes every log line from `raw-logs` (group: `logstash-consumer`)
- Applies deterministic enrichment:
  - Timestamp normalization (Unix float → ISO 8601)
  - MITRE ATT&CK tactic tagging via regex on message content
  - Field cleanup
- Writes all logs to `logs-*` Elasticsearch index

### Elasticsearch
- Single index pattern `logs-*` (one index per day: `logs-2026.04.16`)
- X-Pack security enabled — all access requires `elastic` credentials
- Source of truth for log search, exploration, and Grafana dashboards

### Prometheus + node-exporter + kafka-exporter
- Prometheus scrapes host metrics (CPU, memory, disk) and Kafka metrics (consumer lag)
- Available as a Grafana datasource for infrastructure dashboards

### Grafana
- Pre-built SIEM Overview dashboard loaded from `infrastructure/grafana/dashboards/`
- Datasources auto-provisioned on startup from `infrastructure/grafana/provisioning/`
- Explore tab for ad-hoc Elasticsearch queries

---

## Data Flow: Normal Log Line

```
1. systemd writes to syslog: "Apr 16 10:00:01 host CRON[1234]: session opened"
2. Fluent Bit reads it → JSON encodes → publishes to raw-logs
3. Logstash consumes → matches /cron/ → tags Persistence/T1053 → writes to logs-*
4. Grafana SIEM dashboard shows it in "Recent Security Events" panel
```

## Data Flow: Brute Force Attack

```
1. 15 SSH failures written to /var/log/auth.log
2. Fluent Bit reads each → publishes 15 messages to raw-logs
3. Logstash: each matches /failed password/ → tags Credential Access/T1110
4. All 15 indexed in logs-* with mitre_tactic="Credential Access"
5. Grafana stat panel "Credential Access Events" count increases
6. Alert rule fires if count > threshold in last 5 minutes
```

---

## Port Reference

| Service | Port | Purpose |
|---|---|---|
| Kafka | 9092 | Broker (producers + consumers) |
| Kafka UI | 8080 | Web management interface |
| Elasticsearch | 9200 | REST API + Grafana datasource |
| Prometheus | 9090 | Metrics store + UI |
| node-exporter | 9100 | Host metrics (scraped by Prometheus) |
| kafka-exporter | 9308 | Kafka metrics (scraped by Prometheus) |
| Grafana | 3000 | Dashboards + alerting UI |

---

## Known Quirks

| Quirk | Explanation |
|---|---|
| Logstash shows 401 errors in logs | The `licensechecker` background thread doesn't use pipeline credentials. Safe to ignore — the pipeline itself works fine. |
| Fluent Bit `${VAR:-default}` doesn't work | Fluent Bit only supports `${VAR}` syntax. Use explicit env vars in `.env`. |
| Grafana datasource uses literal password | Grafana provisioning doesn't resolve Docker env vars in `secureJsonData`. Password must be hardcoded in `datasources.yml`. |
| Kafka consumer shows 0 messages without `--from-beginning` | The console consumer starts at the latest offset by default. Always pass `--from-beginning` to read existing messages. |
