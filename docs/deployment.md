# Deployment Guide

## Requirements

- Docker + Docker Compose v2
- Linux host (Fluent Bit mounts `/var/log` from the host)
- 4 GB RAM minimum (Elasticsearch needs at least 512 MB heap)

---

## First-Time Setup

### 1. Environment variables
```bash
cp .env.example .env
```

`.env` contents:
```env
KAFKA_HOST=kafka          # must be 'kafka' — container name on the Docker network
HOSTNAME=siem-host        # any name; added to every log record by Fluent Bit
ELASTIC_PASSWORD=changeme # Elasticsearch password
GRAFANA_PASSWORD=admin    # Grafana admin password
```

> `KAFKA_HOST` must be `kafka` (the container name), not `localhost`.
> Inside Docker, containers reach each other by service name, not by `localhost`.

### 2. Start the stack
```bash
docker compose up -d
```

Elasticsearch takes ~45–60 seconds to become healthy. Other services wait for it
automatically via `depends_on` health checks.

### 3. Verify everything is running
```bash
docker compose ps
```
All services should show `running` or `running (healthy)`.

---

## Service URLs

| Service | URL | Credentials |
|---|---|---|
| Grafana | http://localhost:3000 | admin / admin |
| Kafka UI | http://localhost:8080 | none |
| Elasticsearch | http://localhost:9200 | elastic / changeme |
| Prometheus | http://localhost:9090 | none |

---

## Starting / Stopping

```bash
# start
docker compose up -d

# stop (keeps data volumes — logs and ES data preserved)
docker compose down

# full reset — wipes all data
docker compose down -v
```

---

## Recreating a Single Service

After changing a config file, recreate only the affected container:

```bash
# after editing fluent-bit.conf or .env
docker compose up -d --force-recreate fluent-bit

# after editing logstash/pipeline.conf
docker compose restart logstash

# after editing grafana datasources or dashboards
docker compose restart grafana
```

---

## Verifying the Pipeline is Live

```bash
# 1. Generate a test log
logger -p auth.info "Failed password for invalid user testuser from 10.0.0.1 port 22 ssh2"

# 2. Check it arrived in Kafka (wait ~5s for Fluent Bit flush)
sleep 8 && docker exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic raw-logs --from-beginning \
  --max-messages 1 --timeout-ms 5000 2>/dev/null | grep testuser

# 3. Check it was indexed in Elasticsearch (wait ~5s more for Logstash)
sleep 8 && curl -s -u elastic:changeme \
  "http://localhost:9200/logs-*/_search?pretty&size=1" \
  -H "Content-Type: application/json" \
  -d '{"query":{"match":{"message":"testuser"}},"_source":["message","mitre_tactic","mitre_id"]}'
```

**Expected:** document with `mitre_tactic: "Credential Access"` and `mitre_id: "T1110"`.

---

## Scaling (production)

```bash
# run 2 Logstash instances
docker compose up -d --scale logstash=2
```

For Elasticsearch, replace the single-node service with a multi-node cluster config
and set `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR` accordingly.
