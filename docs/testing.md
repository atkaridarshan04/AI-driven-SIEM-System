# Testing & Verification Guide

Step-by-step verification for every component in the stack.
Run these in order — each layer depends on the one before it.

---

## Prerequisites

```bash
cp .env.example .env
docker compose up -d
```

Wait ~60 seconds for Elasticsearch to fully initialize before proceeding.

---

## 1. Kafka

### Check broker is up
```bash
docker exec kafka kafka-topics --bootstrap-server localhost:9092 --list
```
**Expected:** `raw-logs` and `__consumer_offsets` listed.

### Watch live messages
```bash
docker exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic raw-logs \
  --from-beginning \
  --max-messages 5 \
  --timeout-ms 10000
```
**Expected:** JSON objects like:
```json
{"@timestamp":1776338162.218,"log":"2026-04-16T16:46:02 host sshd[1234]: ...","hostname":"siem-host"}
```

> Note: always use `--from-beginning` — without it the consumer waits at the latest
> offset and times out if no new messages arrive during the timeout window.

### Kafka UI
Open **http://localhost:8080** — Topics → `raw-logs` should show message count > 0.

---

## 2. Fluent Bit

```bash
docker logs fluent-bit --tail 20
```
**Expected (clean startup, no errors):**
```
[info] [input:tail:tail.0] inotify_fs_add(): inode=... name=/var/log/auth.log
[info] [input:tail:tail.0] inotify_fs_add(): inode=... name=/var/log/syslog
[info] [output:kafka:kafka.0] brokers='kafka:9092' topics='raw-logs'
```
**Bad signs:**
- `Connect to ipv4#127.0.0.1:9092 failed` → `KAFKA_HOST` is still `localhost`. Fix: set `KAFKA_HOST=kafka` in `.env` and recreate the container.
- `property 'record' expects 2 values` → `${HOSTNAME}` is unset. Fix: add `HOSTNAME=<any-name>` to `.env`.

---

## 3. Elasticsearch

### Cluster health
```bash
curl -s -u elastic:changeme http://localhost:9200/_cluster/health?pretty
```
**Expected:** `"status": "green"` or `"yellow"` (yellow is normal for single-node).

### Logs index document count
```bash
curl -s -u elastic:changeme "http://localhost:9200/logs-*/_count?pretty"
```
**Expected:** `"count"` > 0 after ~2 minutes of Fluent Bit running.

### Inspect a recent document
```bash
curl -s -u elastic:changeme \
  "http://localhost:9200/logs-*/_search?pretty&size=1" \
  -H "Content-Type: application/json" \
  -d '{"sort":[{"@timestamp":"desc"}],"_source":["@timestamp","message","mitre_tactic","hostname"]}'
```
**Expected document shape:**
```json
{
  "@timestamp": "2026-04-16T16:55:49.000Z",
  "message": "2026-04-16T... host sshd[1234]: ...",
  "hostname": "siem-host"
}
```

---

## 4. Logstash

```bash
docker logs logstash --tail 20 | grep -v licensechecker | grep -v licensereader
```
**Expected:** pipeline started, documents being processed (you'll see JSON output of processed records).

> The `licensechecker` 401 errors in Logstash logs are cosmetic — they come from a
> background license-check thread that doesn't use pipeline credentials. The actual
> pipeline works fine. Ignore them.

### Verify MITRE enrichment
```bash
curl -s -u elastic:changeme \
  "http://localhost:9200/logs-*/_search?pretty&size=0" \
  -H "Content-Type: application/json" \
  -d '{"aggs":{"tactics":{"terms":{"field":"mitre_tactic.keyword"}}}}'
```
**Expected:** buckets showing `Credential Access`, `Privilege Escalation`, `Persistence`, `Lateral Movement` with doc counts.

---

## 5. Log Simulation

Use these commands to generate realistic security events and verify the full pipeline end-to-end.

### Brute force / Credential Access (MITRE T1110)
```bash
for i in {1..15}; do
  logger -p auth.info "Failed password for invalid user admin from 10.0.0.$i port 22 ssh2"
done
```

### Privilege Escalation (MITRE T1078)
```bash
sudo ls /root
logger -p auth.info "sudo: ubuntu : TTY=pts/0 ; USER=root ; COMMAND=/bin/bash"
```

### Lateral Movement / SSH (MITRE T1021)
```bash
logger -p auth.info "Accepted password for ubuntu from 192.168.1.100 port 54321 ssh2"
logger -p auth.info "sshd: Accepted publickey for root from 172.16.0.5 port 443 ssh2"
```

### Persistence / Cron (MITRE T1053)
```bash
logger "CRON[9999]: (root) CMD (/bin/bash /tmp/backdoor.sh)"
logger -p syslog.info "systemd[1]: Started suspicious.service"
```

### Verify the simulated logs reached Elasticsearch
```bash
# wait ~10 seconds after running the above, then:
curl -s -u elastic:changeme \
  "http://localhost:9200/logs-*/_search?pretty&size=5" \
  -H "Content-Type: application/json" \
  -d '{
    "sort": [{"@timestamp": "desc"}],
    "query": {"exists": {"field": "mitre_tactic"}},
    "_source": ["message", "mitre_tactic", "mitre_id", "hostname"]
  }'
```
**Expected:** documents with `mitre_tactic` and `mitre_id` fields populated:
```json
{
  "message": "... Failed password for invalid user admin from 10.0.0.3 ...",
  "mitre_tactic": "Credential Access",
  "mitre_id": "T1110",
  "hostname": "siem-host"
}
```

### Count by tactic
```bash
curl -s -u elastic:changeme \
  "http://localhost:9200/logs-*/_search?pretty&size=0" \
  -H "Content-Type: application/json" \
  -d '{"aggs":{"by_tactic":{"terms":{"field":"mitre_tactic.keyword"}}}}' \
  | python3 -c "
import json, sys
r = json.load(sys.stdin)
for b in r['aggregations']['by_tactic']['buckets']:
    print(f\"{b['key']:30s} {b['doc_count']} events\")
"
```

---

## 6. Prometheus

Open **http://localhost:9090/targets** — all targets should show `UP`:

| Job | Target |
|-----|--------|
| node | node-exporter:9100 |
| kafka | kafka-exporter:9308 |

### Quick queries in Prometheus UI
```
# CPU usage %
100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)

# Kafka consumer lag
kafka_consumergroup_lag
```

---

## 7. Grafana

Open **http://localhost:3000** — login: `admin` / `admin`

### Verify datasource is healthy
```bash
curl -s -u admin:admin \
  "http://localhost:3000/api/datasources/uid/P31C819B24CF3C3C7/health"
```
**Expected:** `{"status":"OK","message":"Elasticsearch data source is healthy."}`

### Open the SIEM dashboard
Navigate to: **http://localhost:3000/d/siem-overview/siem-overview**

Set time range to **Last 24 hours** (top right). You should see:
- Stat panels showing total events, MITRE-tagged count, Credential Access count, Privilege Escalation count
- Log Events Over Time timeseries
- MITRE Tactics Breakdown pie chart
- Recent Security Events log panel at the bottom

### Inspect a specific log entry
In the **Recent Security Events** panel, click any log row — it expands to show all fields:
```
@timestamp      when the event occurred
message         the raw syslog line
mitre_tactic    e.g. Credential Access
mitre_id        e.g. T1110
hostname        siem-host
ingest_time     when Logstash processed it
```

### Explore raw logs
Go to **http://localhost:3000/explore** → select `Elasticsearch` datasource → run queries:
```
# All MITRE-tagged events
mitre_tactic:*

# Only brute force events
mitre_tactic:"Credential Access"

# All logs from a specific host
hostname:"siem-host"

# Search message content
message:"Failed password"
```

---

## 8. End-to-End Smoke Test

Confirms the complete pipeline: host log → Fluent Bit → Kafka → Logstash → Elasticsearch → Grafana.

```bash
# 1. Inject a test event
logger -p auth.warning "Failed password for root from 10.0.0.1 port 22 ssh2"

# 2. Wait for Fluent Bit flush interval (5 seconds), then check Kafka
sleep 8 && docker exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic raw-logs \
  --from-beginning \
  --max-messages 1 \
  --timeout-ms 5000 2>/dev/null | grep "Failed password"

# 3. Wait for Logstash to index it (~5 more seconds), then check Elasticsearch
sleep 8 && curl -s -u elastic:changeme \
  "http://localhost:9200/logs-*/_search?pretty&size=1" \
  -H "Content-Type: application/json" \
  -d '{"sort":[{"@timestamp":"desc"}],"query":{"match":{"message":"Failed password"}},"_source":["message","mitre_tactic","mitre_id"]}'
```

**Expected final output:**
```json
{
  "message": "... Failed password for root from 10.0.0.1 port 22 ssh2",
  "mitre_tactic": "Credential Access",
  "mitre_id": "T1110"
}
```

---

## Common Failures & Fixes

| Symptom | Cause | Fix |
|---|---|---|
| Fluent Bit connects to `localhost:9092` | `KAFKA_HOST` not set or `:-default` syntax used | Set `KAFKA_HOST=kafka` in `.env`, use `${KAFKA_HOST}` (no default) in conf |
| Fluent Bit `record expects 2 values` | `${HOSTNAME}` unset | Add `HOSTNAME=siem-host` to `.env` |
| Grafana datasource 401 | `${ELASTIC_PASSWORD}` not resolved in provisioning YAML | Use literal password in `datasources.yml` |
| Kafka consumer shows 0 messages | Reading from latest offset | Always use `--from-beginning` |
| Logstash 401 errors in logs | License checker background thread (not the pipeline) | Safe to ignore — check pipeline output instead |
| ES `status: red` | Heap too small | Increase `ES_JAVA_OPTS` to `-Xms1g -Xmx1g` in `docker-compose.yml` |
| `curl -u elastic:${ELASTIC_PASSWORD}` fails | Variable not exported in shell | Use literal: `curl -u elastic:changeme` or `export ELASTIC_PASSWORD=changeme` first |
