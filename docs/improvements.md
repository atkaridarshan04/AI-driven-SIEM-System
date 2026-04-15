# Improvements — V1.5 Known Issues & V2.0 Plan

This document tracks confirmed bugs, technical debt, and the planned V2.0 improvements.
Items are ordered by impact.

---

## Confirmed Bugs

### 1. MongoDB URI is empty (backend crashes on startup)

**File:** `dashboard/backend/server.js`

```javascript
const mongoURI = ""; // Replace yourDatabaseName with the actual name
```

The backend will fail to connect to MongoDB and exit on startup.

**Fix:**
```javascript
// server.js
const mongoURI = process.env.MONGO_URI;
```
```env
# dashboard/backend/.env
MONGO_URI=mongodb://localhost:27017/siem
```

---

### 2. Threat type mismatch in frontend

**File:** `dashboard/frontend/app/page.js`

```javascript
const threatClassifications = [
  'system_critical',
  'authentication_error',
  'file_error',        // ← model outputs 'filesystem_error'
  'network_error',
  'permission_error',
  'memory error'       // ← model outputs 'memory_error' (underscore, not space)
];
```

Memory errors are never highlighted as threats. `file_error` never matches.

**Fix:**
```javascript
const threatClassifications = [
  'system_critical',
  'authentication_error',
  'filesystem_error',
  'network_error',
  'permission_error',
  'memory_error'
];
```

---

### 3. `LabeledLDAClassifier.fit()` is never called

**File:** `model/src/logAnomalyDetection/LSTM_AE/classifier.py`

The `fit()` method trains word-topic distributions from actual log data, which would
improve classification accuracy. It is implemented but never called — the classifier
always runs in seed-pattern-only mode.

**Fix:** Call `fit()` in the training script and persist the fitted classifier in
`hybrid_ensemble_artifacts.pkl`:

```python
# In train.py, after building features:
classifier = LabeledLDAClassifier()
classifier.fit(df['Content'].fillna('').tolist())
artifacts['classifier'] = classifier
```

Then load it in `pipeline.py`:
```python
self.classifier = artifacts.get('classifier', LabeledLDAClassifier())
```

---

### 4. Hardcoded IP addresses

**Files:** `logs-collection/docker-compose.yml`, `logs-collection/filebeat.yml`,
`logs-collection/log_consumer.py`

`192.168.37.132` is hardcoded in all three files. The pipeline breaks on any machine
with a different IP.

**Fix:** Use environment variables:
```yaml
# docker-compose.yml
KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://${KAFKA_HOST:-localhost}:9092
```
```yaml
# filebeat.yml
hosts: ["${KAFKA_HOST:-localhost}:9092"]
```
```python
# log_consumer.py
import os
bootstrap = os.getenv('KAFKA_HOST', 'localhost') + ':9092'
```

---

### 5. `processing_mode` field missing from pipeline output

**File:** `model/src/logAnomalyDetection/pipeline.py`

The anomaly objects built in `_build_anomalies()` do not include a `processing_mode` field.
The Express schema expects it. It will be stored as `None` / missing in MongoDB.

**Fix:** Add `'processing_mode': 'sequential'` to the anomaly dict in `_build_anomalies()`.

---

### 6. No authentication on any endpoint

All Express endpoints (`/api/logs`, `/api/system-health`) are publicly accessible.
Any client on the network can read all stored anomalies or post arbitrary data.

**Fix (minimum viable):**
```javascript
// middleware/auth.js
const API_KEY = process.env.API_KEY;
module.exports = (req, res, next) => {
  if (req.headers['x-api-key'] !== API_KEY) return res.status(401).send('Unauthorized');
  next();
};
```

---

### 7. `DataPreprocessor` silently drops `EventTemplate` when `nunique >= 1000`

**File:** `model/src/logAnomalyDetection/LSTM_AE/preprocessor.py`

When `EventTemplate` has high cardinality, the column is dropped entirely instead of
being encoded with TF-IDF. This loses the most informative column for anomaly detection.

**Fix:** Always apply TF-IDF to `EventTemplate`, regardless of cardinality:
```python
# Always TF-IDF EventTemplate
tfidf = self.artifacts['tfidf']
tmpl_features = tfidf.transform(df['EventTemplate'].astype(str)).toarray()
df = df.drop(columns=['EventTemplate'])
```

---

## Technical Debt

### No automated tests

There are no unit tests, integration tests, or CI configuration anywhere in the project.

**Minimum test coverage needed:**
- `parse_validator.py` — validate CSV column detection
- `preprocessor.py` — verify feature shapes match training
- `severity.py` — verify threshold boundaries
- `classifier.py` — verify seed pattern matching

```bash
# Suggested structure
model/tests/
  test_preprocessor.py
  test_severity.py
  test_classifier.py
  test_pipeline.py
```

---

### `server.js` is a monolith

All logic (routes, middleware, DB connection, WebSocket, system health) is in one 150-line file.

**Suggested refactor:**
```
dashboard/backend/
  server.js          ← app setup + listen only
  routes/
    logs.js          ← GET/POST /api/logs
    health.js        ← GET /api/system-health
  middleware/
    auth.js          ← API key check
  db/
    connection.js    ← mongoose connect
    models/Log.js    ← schema
```

---

### No Docker Compose for the full system

Only the Kafka stack is containerized. The AI model, Express backend, and Next.js frontend
must be started manually in separate terminals.

**Needed:** A root-level `docker-compose.yml` that starts all services.

---

### Frontend backend URL is hardcoded in three files

See [configuration.md](./configuration.md). Should be a single `NEXT_PUBLIC_API_URL`
environment variable in `dashboard/frontend/.env.local`.

---

### No input validation on `POST /api/logs`

The endpoint accepts any array without validating field types or required fields.
Malformed data is stored in MongoDB silently.

**Fix:** Add schema validation with `zod` or `joi`.

---

## V2.0 Planned Improvements

### Model

1. **SemanticLogTransformer** — replace the LSTM ensemble with a Transformer autoencoder
   using `sentence-transformers/all-MiniLM-L6-v2` embeddings. Eliminates manual feature
   engineering entirely. Handles heterogeneous log formats without per-source preprocessing.

2. **Windows EVTX support** — add `parse_windows_evtx.py` using `python-evtx`.
   Expose via `--dataset Windows` in `run.py`.

3. **LANL dataset migration** — train on LANL Comprehensive multi-source dataset
   (`auth.txt`, `proc.txt`, `flows.txt`, `dns.txt`) instead of synthetic Linux logs.
   Provides labeled red team activity for proper precision/recall evaluation.

4. **MLflow experiment tracking** — log loss curves, threshold percentiles, F1 per
   severity level. Add model versioning metadata to artifact files.

5. **FastAPI serving layer** — wrap `AnomalyDetectionPipeline` in a FastAPI service
   with `/health`, `/predict`, `/metrics` endpoints. Replace the current push-to-Express
   pattern with a proper ML serving API.

6. **MITRE ATT&CK tactic field** — add `mitre_tactic` to anomaly output schema.

### Infrastructure

1. **Kafka KRaft mode** — drop Zookeeper. Use `KAFKA_PROCESS_ROLES: broker,controller`.

2. **Elasticsearch** — replace MongoDB for log storage. Enables full-text search,
   time-series queries, and native Grafana/Kibana integration.

3. **Logstash enrichment pipeline** — parse EventID → human-readable name, add MITRE
   tactic field, GeoIP on IP fields. Output to both Elasticsearch and `enriched-logs` topic.

4. **Confluent Schema Registry** — enforce Avro schema on Kafka messages. Prevents
   silent data loss when Filebeat JSON structure changes.

5. **Prometheus + node-exporter** — replace the custom `/api/system-health` endpoint
   with standard Prometheus metrics.

### Dashboard

1. **Grafana** — replace custom Chart.js panels with Grafana dashboards. Provides
   built-in alerting, time-series drill-down, and 50+ community SIEM dashboard templates.

2. **Grafana alerting rules:**
   - `anomaly_rate > 10/min` → Slack/PagerDuty
   - `severity=Critical AND count > 0` → immediate notification
   - `kafka_consumer_lag > 1000` → pipeline health warning

3. **JWT authentication** — add to Express backend. All endpoints require a valid token.

4. **Rate limiting** — add `express-rate-limit` to prevent abuse.

### DevOps

1. **`.env.example`** at repo root documenting every required environment variable.

2. **Root `docker-compose.yml`** starting all services (Kafka, Elasticsearch, Logstash,
   Prometheus, Grafana, model API, Express, frontend).

3. **Grafana dashboards as code** — store JSON dashboard definitions in
   `grafana/dashboards/` so they are version-controlled.

4. **Kafka TLS + SASL** — encrypt and authenticate Filebeat → Kafka traffic.

5. **Elasticsearch X-Pack security** — enable free-tier security, set `elastic` user
   password via environment variable.

---

## Phased Execution

### Phase 1 — Fix current bugs (1–2 weeks)
- Fix MongoDB URI (bug #1)
- Fix threat type mismatch (bug #2)
- Wire `LabeledLDAClassifier.fit()` into training (bug #3)
- Replace hardcoded IPs with env vars (bug #4)
- Add `processing_mode` to pipeline output (bug #5)
- Add basic API key auth to Express (bug #6)

### Phase 2 — Infrastructure upgrade (2–4 weeks)
- Migrate Kafka to KRaft mode
- Add Elasticsearch + Logstash to docker-compose
- Add Prometheus + node-exporter + kafka-exporter
- Build initial Grafana dashboards
- Refactor `server.js` into modules

### Phase 3 — V2.0 model (4–8 weeks)
- Implement `SemanticLogTransformer`
- Train on LANL dataset
- Wrap in FastAPI service
- Add MITRE ATT&CK tactic field
- Wire FastAPI → Kafka → Elasticsearch → Grafana

### Phase 4 — Production hardening (2–3 weeks)
- Grafana alerting rules
- Winlogbeat deployment config
- TLS + SASL on Kafka
- Elasticsearch X-Pack security
- End-to-end integration test
