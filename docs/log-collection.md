# Log Collection — Kafka + Filebeat Pipeline

## Overview

The log collection subsystem streams live system logs from a host machine into Apache Kafka
using Filebeat as the log shipper. A Python consumer (`log_consumer.py`) reads from Kafka
for debugging and inspection.

**Current status:** This pipeline is operational as a standalone streaming system.
It is **not yet connected** to the AI detection engine — the consumer prints parsed logs
to stdout only. Integration with the model is planned for V2.0.

---

## Infrastructure

All components run via Docker Compose (`logs-collection/docker-compose.yml`).

### Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| Zookeeper | `confluentinc/cp-zookeeper:7.4.0` | 2181 | Kafka coordination |
| Kafka | `confluentinc/cp-kafka:7.4.0` | 9092 | Message broker |
| Kafka-UI | `provectuslabs/kafka-ui:latest` | 8080 | Web management UI |

All three services share a Docker bridge network `kafka-net`.

### Starting the stack

```bash
cd logs-collection/
docker-compose up -d
```

### Stopping

```bash
docker-compose down
```

---

## Kafka Configuration

### Broker settings (current)

| Setting | Value |
|---------|-------|
| Broker ID | 1 |
| Advertised listener | `PLAINTEXT://192.168.37.132:9092` |
| Zookeeper connect | `zookeeper:2181` |
| Replication factor | 1 |
| Log directory | `/var/lib/kafka/data` |
| Confluent metrics | disabled |

> **Known issue:** The advertised listener IP `192.168.37.132` is hardcoded.
> This must be changed to match the host machine's IP before use.
> See [improvements.md](./improvements.md) for the fix.

### Topic

| Topic | Producer | Consumer |
|-------|----------|---------|
| `server-logs` | Filebeat | `log_consumer.py` |

### Kafka-UI

Access at `http://localhost:8080` after starting the stack.
Provides topic inspection, consumer group monitoring, and message browsing.

---

## Filebeat Configuration (`filebeat.yml`)

Filebeat runs on the **host machine** (not in Docker) and ships logs to Kafka.

### Monitored log files

```yaml
filebeat.inputs:
  - type: filestream
    paths:
      - /var/log/auth.log
      - /var/log/syslog
      - /var/log/nginx/access.log
      - /var/log/nginx/error.log
    exclude_lines: ['filebeat\[[0-9]+\]:']
    tags: ["serverlogs"]
```

Filebeat logs are excluded to prevent feedback loops.

### Output

```yaml
output.kafka:
  hosts: ["192.168.37.132:9092"]
  topic: "server-logs"
  partition.round_robin:
    reachable_only: false
  required_acks: 1
  codec.json:
    pretty: false
```

Each log line is encoded as a JSON object with fields:
- `message` — raw log line
- `log.file.path` — source file path
- `host.hostname` — source hostname
- `@timestamp` — ingestion timestamp

### Installing Filebeat

```bash
# Ubuntu/Debian
curl -L -O https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-8.x.x-amd64.deb
sudo dpkg -i filebeat-8.x.x-amd64.deb

# Copy config
sudo cp logs-collection/filebeat.yml /etc/filebeat/filebeat.yml

# Start
sudo systemctl enable filebeat
sudo systemctl start filebeat
sudo systemctl status filebeat
```

> **Important:** Update the Kafka host IP in `filebeat.yml` before starting.

---

## Kafka Consumer (`log_consumer.py`)

A Python script that consumes from the `server-logs` topic, parses log messages,
and prints formatted output to stdout.

### Running

```bash
cd logs-collection/
pip install confluent-kafka
python log_consumer.py
```

### Consumer configuration

```python
Consumer({
    'bootstrap.servers': '192.168.37.132:9092',
    'group.id': 'log-consumer-group',
    'auto.offset.reset': 'latest'
})
```

`auto.offset.reset: latest` — only processes new messages after startup.
Change to `earliest` to replay all messages from the beginning.

### Log parsing

The consumer handles three log formats:

| Format | Regex pattern | Example |
|--------|--------------|---------|
| Auth log | `timestamp hostname process[pid]: message` | `Jun 15 03:21:44 server sshd[1234]: Failed password` |
| Syslog | `MMM DD HH:MM:SS hostname program[pid]: message` | `Jun 15 03:21:44 server kernel: OOM killer` |
| Kernel | `MMM DD HH:MM:SS hostname kernel: [uptime] message` | `Jun 15 03:21:44 server kernel: [12345.6] segfault` |

For JSON-encoded messages (from Filebeat), the consumer extracts the `message` field
and applies the same parsers.

### Filtering

Logs from `filebeat` process/program are silently dropped to prevent noise.
Logs containing `"monitoring"` in the message are also dropped.

### Output format

```
Jun 15 03:21:44 server sshd[1234]: Failed password for root from 10.0.0.1 port 22 ssh2
```

---

## Verifying the Pipeline

### Check Kafka is receiving messages

```bash
# Access Kafka container
docker exec -it <kafka_container_name> bash

# List topics
kafka-topics --bootstrap-server localhost:9092 --list

# Consume messages directly
kafka-console-consumer \
    --bootstrap-server localhost:9092 \
    --topic server-logs \
    --from-beginning
```

### Check consumer group lag

```bash
docker exec -it <kafka_container_name> \
    kafka-consumer-groups \
    --bootstrap-server localhost:9092 \
    --describe \
    --group log-consumer-group
```

### Reset consumer offset (replay all messages)

```bash
docker exec -it <kafka_container_name> \
    kafka-consumer-groups \
    --bootstrap-server localhost:9092 \
    --group log-consumer-group \
    --reset-offsets \
    --to-earliest \
    --all-topics \
    --execute
```

---

## Current Limitations

1. **Hardcoded IP** — `192.168.37.132` appears in both `docker-compose.yml` and `filebeat.yml`.
   Must be updated manually for each deployment.

2. **No authentication** — Kafka accepts plaintext connections with no SASL/TLS.

3. **No schema enforcement** — Filebeat JSON structure is not validated.
   If Filebeat changes its output format, the consumer silently misparses messages.

4. **Consumer is a dev tool** — `log_consumer.py` prints to stdout only.
   It is not connected to the AI model, the Express backend, or any storage.

5. **Zookeeper-based Kafka** — Zookeeper is deprecated since Kafka 3.3 (KRaft mode available).

6. **Single broker, replication factor 1** — no fault tolerance.

See [improvements.md](./improvements.md) for the planned fixes.
