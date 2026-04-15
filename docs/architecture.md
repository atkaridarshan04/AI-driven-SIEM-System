# System Architecture

## Overview

The AI-Driven SIEM System is composed of four independent subsystems that communicate through HTTP and WebSocket interfaces. There is no shared process or shared memory between them — each runs as a separate service.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Log Sources                              │
│          /var/log/auth.log  /var/log/syslog  nginx logs         │
└──────────────────────────┬──────────────────────────────────────┘
                           │ filestream
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Filebeat (host agent)                         │
│  Reads log files → encodes as JSON → publishes to Kafka topic    │
└──────────────────────────┬───────────────────────────────────────┘
                           │ Kafka topic: server-logs
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│              Apache Kafka + Zookeeper (Docker)                   │
│  Broker: 192.168.37.132:9092   Kafka-UI: :8080                  │
└──────────────────────────┬───────────────────────────────────────┘
                           │ confluent-kafka consumer
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                  log_consumer.py (Python)                        │
│  Parses raw/JSON log messages, normalizes, prints to stdout      │
│  (dev/debug tool — not wired to the AI model)                   │
└──────────────────────────────────────────────────────────────────┘

                    ── Separate offline pipeline ──

┌──────────────────────────────────────────────────────────────────┐
│                  AI Detection Engine (Python)                    │
│                                                                  │
│  run.py ──► parse.py (BRAIN parser)                             │
│         └──► pipeline.py (AnomalyDetectionPipeline)             │
│               ├── DataPreprocessor   (feature engineering)       │
│               ├── EnsembleDetector   (3× Bi-LSTM autoencoders)  │
│               ├── EnhancedSeverityManager (percentile thresholds)│
│               └── LabeledLDAClassifier   (log type labeling)    │
│                                                                  │
│  Output: anomaly_detection_results.json                         │
│  Optional: POST /api/logs → Express backend                     │
└──────────────────────────┬───────────────────────────────────────┘
                           │ HTTP POST /api/logs (JSON array)
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│              Express Backend (Node.js :5000)                     │
│  POST /api/logs  → MongoDB insert → Socket.IO broadcast         │
│  GET  /api/logs  → MongoDB query (last 100)                     │
│  GET  /api/system-health → live CPU/mem/disk metrics            │
└──────────────────────────┬───────────────────────────────────────┘
                           │ Socket.IO  +  REST fetch
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│              Next.js Frontend (React :3000)                      │
│  Home:          recent logs, pie chart, line chart               │
│  /pages/logs:   full log table with filters                      │
│  /pages/threats: system health gauges (CPU/mem/disk)            │
└──────────────────────────────────────────────────────────────────┘
```

---

## Component Responsibilities

### AI Detection Engine
- Sole owner of all ML logic
- Reads raw log files from disk, writes structured CSVs and JSON reports to disk
- Optionally pushes results to the Express backend via HTTP
- Stateless between runs — all state is in artifact files (`artifacts/`)

### Express Backend
- Stateful store for anomaly results (MongoDB)
- Real-time push to connected browser clients via Socket.IO
- System health polling (CPU, memory, disk) via `os` and `os-utils`
- No authentication currently — all endpoints are open

### Next.js Frontend
- Pure display layer — no business logic
- Fetches historical logs from Express on mount
- Subscribes to `new_log` Socket.IO events for real-time updates
- Three pages: Home (overview), Logs (table), Threats (system health)

### Kafka + Filebeat
- Separate streaming pipeline for live log ingestion
- Currently **not connected** to the AI detection engine
- `log_consumer.py` is a standalone debug consumer that prints parsed logs to stdout

---

## Data Flow: Offline Detection (Primary Path)

```
1. User runs:
   python src/logAnomalyDetection/run.py --input Linux_test.log

2. BRAIN parser reads data/logs/raw/Linux_test.log
   → writes data/logs/processed/Linux_test.log_structured.csv

3. AnomalyDetectionPipeline.load()
   → loads hybrid_ensemble_artifacts.pkl  (preprocessor, severity, weights)
   → loads final_lstm_sequential.pth      (3 model state_dicts)

4. AnomalyDetectionPipeline.run(csv_path)
   → DataPreprocessor.preprocess(df)      → scaled numpy array
   → LogDataset(scaled, seq_len=8, stride=8)  → sliding windows
   → EnsembleDetector.predict(dataloader) → per-sequence MSE errors
   → threshold = np.percentile(errors, 95)
   → for each error > threshold:
       LabeledLDAClassifier.classify_log() → log_type
       EnhancedSeverityManager.classify_with_confidence() → severity, confidence
   → returns dict {metadata, anomalies[]}

5. Results saved to reports/logAnomalyDetection/anomaly_detection_results.json

6. If --export-to-express:
   ExpressExporter.export_anomalies() → POST http://localhost:5000/api/logs
```

## Data Flow: Real-Time Streaming (Secondary Path)

```
1. Filebeat reads /var/log/* on host machine
2. Encodes each log line as JSON, publishes to Kafka topic "server-logs"
3. log_consumer.py polls Kafka, parses messages, prints to stdout
   (no further processing — this path ends here in V1.5)
```

---

## Directory Structure

```
AI-driven-SIEM-System/
├── model/                          # AI detection engine
│   ├── src/
│   │   ├── logAnomalyDetection/
│   │   │   ├── run.py              # CLI entry point
│   │   │   ├── pipeline.py         # AnomalyDetectionPipeline
│   │   │   ├── parse.py            # BRAIN parser wrapper
│   │   │   ├── parse_validator.py  # CSV validation
│   │   │   └── LSTM_AE/
│   │   │       ├── autoencoder.py  # SequentialLSTMAutoencoder
│   │   │       ├── train.py        # Training script
│   │   │       ├── detector.py     # EnsembleDetector
│   │   │       ├── preprocessor.py # DataPreprocessor
│   │   │       ├── severity.py     # EnhancedSeverityManager
│   │   │       ├── classifier.py   # LabeledLDAClassifier
│   │   │       ├── dataset.py      # LogDataset (PyTorch)
│   │   │       ├── model.py        # Re-export shim
│   │   │       └── severity_classifier.py  # Re-export shim
│   │   └── utils/
│   │       ├── config_loader.py    # YAML config loader
│   │       └── express_exporter.py # HTTP push to Express
│   │   └── Brain/                  # BRAIN log parser (vendored)
│   ├── configs/
│   │   └── log-anomaly-detection.yml
│   ├── artifacts/                  # Trained model weights + pkl
│   ├── data/logs/
│   │   ├── raw/                    # Input log files
│   │   └── processed/              # BRAIN output CSVs
│   ├── reports/logAnomalyDetection/ # JSON detection results
│   └── requirements.txt
│
├── dashboard/
│   ├── backend/
│   │   ├── server.js               # Express + Socket.IO + MongoDB
│   │   ├── package.json
│   │   └── .env                    # PORT (mongoURI missing)
│   └── frontend/
│       ├── app/
│       │   ├── page.js             # Home page
│       │   ├── layout.js
│       │   ├── globals.css
│       │   ├── components/
│       │   │   └── navbar.js
│       │   └── pages/
│       │       ├── logs/page.js    # Log table page
│       │       └── threats/page.js # System health page
│       └── package.json
│
├── logs-collection/
│   ├── docker-compose.yml          # Zookeeper + Kafka + Kafka-UI
│   ├── filebeat.yml                # Filebeat config (hardcoded IP)
│   └── log_consumer.py             # Debug Kafka consumer
│
└── docs/                           # This documentation
```

---

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| AI framework | PyTorch | ≥1.9 |
| Log parsing | BRAIN algorithm | vendored |
| Feature engineering | scikit-learn (TF-IDF, OHE, StandardScaler) | — |
| Log type classification | LDA (seed-pattern mode) | — |
| Backend runtime | Node.js | ≥14 |
| Backend framework | Express | 5.x |
| Database | MongoDB (via Mongoose) | 8.x client |
| Real-time transport | Socket.IO | 4.x |
| Frontend framework | Next.js | 15.3 |
| Frontend UI | React | 19 |
| Charts | Chart.js + react-chartjs-2 | 4.x |
| CSS | Tailwind CSS | 4.x |
| Message broker | Apache Kafka (Confluent) | 7.4.0 |
| Log shipper | Filebeat | — |
| Coordination | Zookeeper | 7.4.0 |
