# Log Collection — Fluent Bit + Kafka

## Overview

Fluent Bit runs as a Docker container, mounts `/var/log` from the host,
and ships every log line to the Kafka `raw-logs` topic as JSON.
Logstash and the Model API both consume from this topic independently.

---

## What Gets Collected

| Log file | Content |
|---|---|
| `/var/log/auth.log` | SSH logins, sudo, PAM authentication |
| `/var/log/syslog` | General system events, cron, kernel, systemd |

Add more paths in `logs-collection/fluent-bit.conf` under `[INPUT] Path` (comma-separated).

---

## Fluent Bit Config (`logs-collection/fluent-bit.conf`)

```ini
[SERVICE]
    Flush        5        # send to Kafka every 5 seconds
    Daemon       Off
    Log_Level    warn

[INPUT]
    Name              tail
    Path              /var/log/auth.log,/var/log/syslog
    Tag               system.logs
    Refresh_Interval  5
    Skip_Long_Lines   On

[FILTER]
    Name   grep
    Match  system.logs
    Exclude log .*fluent-bit.*    # prevent feedback loop

[FILTER]
    Name         record_modifier
    Match        system.logs
    Record       hostname ${HOSTNAME}    # adds hostname field to every record

[OUTPUT]
    Name        kafka
    Match       system.logs
    Brokers     ${KAFKA_HOST}:9092       # must be 'kafka' inside Docker
    Topics      raw-logs
    Timestamp_Key @timestamp
    Retry_Limit 3
```

### Important: env var syntax

Fluent Bit uses `${VAR}` for env substitution. It does **not** support the shell
`${VAR:-default}` fallback syntax — using it causes the variable to silently fail
and resolve to `localhost`. Always set the variable explicitly in `.env`:

```env
KAFKA_HOST=kafka
HOSTNAME=siem-host
```

---

## Message Shape in Kafka

Each message published to `raw-logs` looks like:

```json
{
  "@timestamp": 1776338162.218,
  "log": "2026-04-16T16:46:02+05:30 hostname sshd[1234]: Failed password for root",
  "hostname": "siem-host"
}
```

The `log` field contains the raw syslog line. Logstash renames it to `message`
and applies enrichment before writing to Elasticsearch.

---

## Kafka Topic: raw-logs

Both Logstash and the Model API consume from this topic in separate consumer groups,
so each gets every message independently:

| Consumer | Group ID | Purpose |
|---|---|---|
| Logstash | `logstash-consumer` | Enriches + stores all logs in ES `logs-*` |
| Model API | `siem-model` | Buffers into windows, runs ML inference |

---

## Kafka (KRaft Mode)

Runs without Zookeeper. Single broker for development.

| Setting | Value |
|---|---|
| Internal broker address | `kafka:9092` (used by containers) |
| External broker address | `localhost:9092` (used from host) |
| Topic | `raw-logs` |
| Replication factor | 1 |
| UI | http://localhost:8080 |

### Useful commands

```bash
# list topics
docker exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# watch messages live (use --from-beginning to see existing messages)
docker exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic raw-logs \
  --from-beginning \
  --max-messages 10 \
  --timeout-ms 10000

# check consumer group lag
docker exec kafka kafka-consumer-groups \
  --bootstrap-server localhost:9092 \
  --describe --group logstash-consumer
```

---

## Logstash Enrichment (`infrastructure/logstash/pipeline.conf`)

Logstash consumes `raw-logs` and applies:

1. **Timestamp fix** — converts Fluent Bit's Unix float `@timestamp` to ISO format
2. **Field rename** — `log` → `message`
3. **MITRE ATT&CK tagging** — regex matches on message content:

| Pattern matched | `mitre_tactic` | `mitre_id` |
|---|---|---|
| `failed password`, `authentication failure`, `invalid user` | Credential Access | T1110 |
| `sudo`, `privilege`, `escalat` | Privilege Escalation | T1078 |
| `sshd`, `accepted password`, `ssh.*connect` | Lateral Movement | T1021 |
| `cron`, `systemd`, `scheduled task` | Persistence | T1053 |

4. **Cleanup** — removes `event`, `@version` fields to keep documents clean

### Final document shape in Elasticsearch (`logs-*`)

```json
{
  "@timestamp": "2026-04-16T16:55:49.000Z",
  "ingest_time": "2026-04-16T16:55:50.123Z",
  "message": "2026-04-16T16:55:49+05:30 host ubuntu: Failed password for invalid user admin from 10.0.0.3 port 22 ssh2",
  "hostname": "siem-host",
  "mitre_tactic": "Credential Access",
  "mitre_id": "T1110"
}
```

---

## Adding a New Log Source

1. Add the path to `fluent-bit.conf`:
```ini
[INPUT]
    Name  tail
    Path  /var/log/auth.log,/var/log/syslog,/var/log/myapp/app.log
    Tag   system.logs
```

2. Add MITRE tagging rules in `infrastructure/logstash/pipeline.conf` if needed.

3. Recreate Fluent Bit to pick up the config change:
```bash
docker compose up -d --force-recreate fluent-bit
```
