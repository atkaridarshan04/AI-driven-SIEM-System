# Configuration Reference

## Model Configuration (`model/configs/log-anomaly-detection.yml`)

This is the primary configuration file for the AI detection engine.
Pass it with `--config` or `-c` to `run.py`.

---

### `data_paths`

```yaml
data_paths:
  input_dir: "data/logs/raw/"        # Directory containing raw log files
  output_dir: "data/logs/processed/" # Directory for BRAIN parser output CSVs
  reports_dir: "reports/logAnomalyDetection/"  # Directory for JSON reports
```

---

### `parsing`

Controls the BRAIN log parser.

```yaml
parsing:
  algorithm: "Brain"
  dataset: "Linux"
  log_format: '<Month> <Date> <Time> <Level> <Component>(\[<PID>\])?: <Content>'
  parameters:
    threshold: 4        # BRAIN similarity threshold (lower = more templates)
    depth: 4            # Parse tree depth
    st: 0.4             # Similarity threshold for merging
    maxChild: 100       # Max children per node
    mergeThreshold: 0.9 # Merge threshold
    regex:
      - '(\d+\.){3}\d+'         # Normalize IPv4 addresses
      - '\d{2}:\d{2}:\d{2}'     # Normalize timestamps
      - 'J([a-z]{2})'           # Normalize month abbreviations
    delimeter: [""]
  validation:
    required_columns: ["EventTemplate", "EventId"]
    optional_columns: ["Content", "Level", "Component", "Date", "Time"]
    validate_output: true
```

**Log format tokens:**
- `<Month>`, `<Date>`, `<Time>` — timestamp components
- `<Level>` — log level (INFO, ERROR, WARN, etc.)
- `<Component>` — process/service name
- `<PID>` — optional process ID in brackets
- `<Content>` — log message body

---

### `detection`

Controls the anomaly detection pipeline.

```yaml
detection:
  model_path: "artifacts/"
  output_path: "reports/logAnomalyDetection/"
  seq_len: 8          # Sequence length (log lines per window)
  stride: 8           # Stride between windows (= seq_len → no overlap)
  batch_size: 32      # DataLoader batch size

  ensemble:
    num_models: 3
    model_configs:
      - hidden_dim: 16, dropout: 0.3
      - hidden_dim: 24, dropout: 0.4
      - hidden_dim: 32, dropout: 0.2

  thresholds:
    anomaly_percentile: 95   # Sequences above this percentile are anomalous

  severity:
    percentiles: [85, 95, 99]
    labels: ["Low", "Medium", "High", "Critical"]

  preprocessing:
    max_tfidf_features: 50
    cardinality_threshold: 1000   # EventTemplate: TF-IDF if nunique >= this
```

---

### `execution`

```yaml
execution:
  enable_gpu: false       # Set true to use CUDA if available
  device: "cpu"
  continue_on_errors: true
  max_retries: 3
  early_stopping_patience: 5
```

---

### `express_backend`

```yaml
express_backend:
  enabled: true                      # Set false to disable export
  base_url: "http://localhost:5000"  # Express server URL
  timeout: 30                        # HTTP request timeout (seconds)
  retry_attempts: 3                  # Retries on failure
```

---

### `alerting`

Not yet implemented — reserved for future alerting integration.

```yaml
alerting:
  critical_anomaly_threshold: 1
  high_anomaly_threshold: 5
  anomaly_rate_threshold: 10.0
  enable_email_alerts: false
  enable_webhook_alerts: false
```

---

### `logging`

```yaml
logging:
  level: "INFO"
  file_logging: false
  log_file: "logs/pipeline.log"
  enable_progress_bars: true
```

---

## Express Backend Environment (`.env`)

**File:** `dashboard/backend/.env`

```env
PORT=5000
MONGO_URI=mongodb://localhost:27017/siem   # Required — not currently set
```

> The `MONGO_URI` variable is not read from `.env` in the current `server.js`.
> The URI is hardcoded as an empty string. See [improvements.md](./improvements.md).

---

## Kafka / Docker Compose (`logs-collection/docker-compose.yml`)

```yaml
services:
  zookeeper:
    image: confluentinc/cp-zookeeper:7.4.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
    ports: ["2181:2181"]

  kafka:
    image: confluentinc/cp-kafka:7.4.0
    ports: ["9092:9092"]
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://192.168.37.132:9092  # ← change this
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1

  kafka-ui:
    image: provectuslabs/kafka-ui:latest
    ports: ["8080:8080"]
    environment:
      KAFKA_CLUSTERS_0_NAME: local
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka:9092
```

**Required change before use:**
Replace `192.168.37.132` with your host machine's IP address in:
- `KAFKA_ADVERTISED_LISTENERS` in `docker-compose.yml`
- `hosts` in `filebeat.yml`
- `bootstrap.servers` in `log_consumer.py`

---

## Filebeat (`logs-collection/filebeat.yml`)

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

output.kafka:
  enabled: true
  hosts: ["192.168.37.132:9092"]   # ← change this
  topic: "server-logs"
  required_acks: 1
  codec.json:
    pretty: false
```

---

## Frontend Configuration

The frontend has no `.env` file. The backend URL is hardcoded in three places:

| File | Hardcoded value |
|------|----------------|
| `app/page.js` | `http://localhost:5000` (fetch + socket) |
| `app/pages/logs/page.js` | `http://localhost:5000` (fetch + socket) |
| `app/pages/threats/page.js` | `http://localhost:5000` (fetch) |

To change the backend URL, update all three files.

---

## Training Hyperparameters

Defaults are defined in `model/src/logAnomalyDetection/LSTM_AE/train.py`:

```python
DEFAULTS = dict(
    seq_len=8,
    stride=8,
    batch_size=32,
    epochs=50,
    lr=1e-3,
    val_split=0.15,
    early_stopping=5,
    max_tfidf=50,
)

ENSEMBLE_CONFIGS = [
    {'hidden_dim': 16, 'dropout': 0.3},
    {'hidden_dim': 24, 'dropout': 0.4},
    {'hidden_dim': 32, 'dropout': 0.2},
]
```

All defaults can be overridden via CLI flags. See [ai-model.md](./ai-model.md) for the
full flag reference.
