# Configuration Reference

## Root `.env`

```env
# Kafka — must be 'kafka' (container name) when running inside Docker
KAFKA_HOST=kafka

# Added to every log record by Fluent Bit's record_modifier filter
HOSTNAME=siem-host

# Elasticsearch
ELASTIC_PASSWORD=changeme

# Grafana
GRAFANA_PASSWORD=admin

# Model serving (offline batch mode)
MODEL_ARTIFACTS_PATH=artifacts/
SEQ_LEN=8
```

> `KAFKA_HOST` must be `kafka`, not `localhost`. Fluent Bit and Logstash run inside
> Docker and resolve Kafka by container name on the `siem-net` bridge network.

> Fluent Bit uses `${VAR}` syntax only — `${VAR:-default}` shell fallback syntax is
> not supported and silently fails. Always set variables explicitly in `.env`.

---

## Fluent Bit (`logs-collection/fluent-bit.conf`)

```ini
[SERVICE]
    Flush        5        # flush to Kafka every 5 seconds
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
    Exclude log .*fluent-bit.*

[FILTER]
    Name         record_modifier
    Match        system.logs
    Record       hostname ${HOSTNAME}

[OUTPUT]
    Name        kafka
    Match       system.logs
    Brokers     ${KAFKA_HOST}:9092
    Topics      raw-logs
    Timestamp_Key @timestamp
    Retry_Limit 3
```

---

## Logstash Pipeline (`infrastructure/logstash/pipeline.conf`)

```ruby
input {
  kafka {
    bootstrap_servers => "${KAFKA_HOST:kafka}:9092"
    topics => ["raw-logs"]
    group_id => "logstash-consumer"
    codec => json
  }
}

filter {
  # Fix @timestamp: Fluent Bit sends Unix float, convert to ISO
  if [_@timestamp] {
    ruby {
      code => "event.set('@timestamp', LogStash::Timestamp.at(event.get('_@timestamp').to_f))"
    }
    mutate { remove_field => ["_@timestamp"] }
  }

  # Rename Fluent Bit's 'log' field to 'message'
  if [log] {
    mutate { rename => { "log" => "message" } }
  }

  # MITRE ATT&CK tactic tagging
  if [message] =~ /(?i)(failed password|authentication failure|invalid user|login failed)/ {
    mutate { add_field => { "mitre_tactic" => "Credential Access"    "mitre_id" => "T1110" } }
  } else if [message] =~ /(?i)(sudo|su -|privilege|escalat)/ {
    mutate { add_field => { "mitre_tactic" => "Privilege Escalation" "mitre_id" => "T1078" } }
  } else if [message] =~ /(?i)(sshd|ssh.*connect|accepted password)/ {
    mutate { add_field => { "mitre_tactic" => "Lateral Movement"     "mitre_id" => "T1021" } }
  } else if [message] =~ /(?i)(cron|at |scheduled task|systemd)/ {
    mutate { add_field => { "mitre_tactic" => "Persistence"          "mitre_id" => "T1053" } }
  }

  mutate {
    add_field    => { "ingest_time" => "%{@timestamp}" }
    remove_field => ["event", "@version"]
  }
}

output {
  elasticsearch {
    hosts    => ["http://elasticsearch:9200"]
    index    => "logs-%{+YYYY.MM.dd}"
    user     => "elastic"
    password => "${ELASTIC_PASSWORD}"
  }
}
```

---

## Grafana Datasources (`infrastructure/grafana/provisioning/datasources/datasources.yml`)

```yaml
apiVersion: 1

datasources:
  - name: Elasticsearch
    type: elasticsearch
    url: http://elasticsearch:9200
    access: proxy
    basicAuth: true
    basicAuthUser: elastic
    secureJsonData:
      basicAuthPassword: changeme    # literal value — env vars not resolved here
    jsonData:
      index: "logs-*"
      timeField: "@timestamp"
      esVersion: "8.0.0"

  - name: Elasticsearch-Anomalies
    type: elasticsearch
    url: http://elasticsearch:9200
    access: proxy
    basicAuth: true
    basicAuthUser: elastic
    secureJsonData:
      basicAuthPassword: changeme
    jsonData:
      index: "anomalies-*"
      timeField: "timestamp"
      esVersion: "8.0.0"

  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    access: proxy
```

> If you change `ELASTIC_PASSWORD` in `.env`, update the literal value here too
> and restart Grafana.

---

## Docker Compose (`docker-compose.yml`) — Key Settings

| Service | Key env vars | Notes |
|---|---|---|
| `fluent-bit` | `KAFKA_HOST`, `HOSTNAME` | Read from `.env` |
| `kafka` | `KAFKA_ADVERTISED_LISTENERS` | Uses `${KAFKA_HOST:-localhost}:9092` for external access |
| `elasticsearch` | `ELASTIC_PASSWORD`, `ES_JAVA_OPTS` | Increase heap for production |
| `logstash` | `KAFKA_HOST`, `ELASTIC_PASSWORD` | Read from `.env` |
| `grafana` | `GF_SECURITY_ADMIN_PASSWORD` | `GF_INSTALL_PLUGINS` must be empty — elasticsearch plugin is built-in |

---

## Model Configuration (`model/configs/log-anomaly-detection.yml`)

Used by the offline batch detection CLI (`run.py`). Key sections:

```yaml
detection:
  seq_len: 8           # log lines per sliding window
  stride: 8            # step between windows
  batch_size: 32

  thresholds:
    anomaly_percentile: 95   # sequences above this are flagged

  severity:
    percentiles: [85, 95, 99]
    labels: ["Low", "Medium", "High", "Critical"]

express_backend:
  enabled: true
  base_url: "http://localhost:5000"
```
