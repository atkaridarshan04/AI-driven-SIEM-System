# API Reference

## Express Backend — HTTP Endpoints

Base URL: `http://localhost:5000`

---

### GET /api/logs

Returns the most recent 100 log entries from MongoDB, sorted newest first.

**Request**
```
GET /api/logs
```

**Response** `200 OK`
```json
[
  {
    "_id": "6849a1b2c3d4e5f6a7b8c9d0",
    "log": {
      "content": "Out of memory: Kill process 1234 (java) score 900",
      "event_template": "Out of memory: Kill process <*> (<*>) score <*>",
      "level": "ERROR",
      "component": "kernel",
      "line_id": "42"
    },
    "anomaly_type": "memory_error",
    "severity": "Critical",
    "confidence": 0.923,
    "anomaly_score": 0.008741,
    "processing_mode": "sequential",
    "timestamp": "03:21:44"
  }
]
```

**Error** `500 Internal Server Error`
```
Failed to fetch logs
```

---

### POST /api/logs

Accepts an array of anomaly objects, persists them to MongoDB, and broadcasts each
via Socket.IO to all connected clients.

**Request**
```
POST /api/logs
Content-Type: application/json
```

Body must be a JSON **array**:
```json
[
  {
    "log": {
      "content": "Failed password for root from 10.0.0.1 port 22",
      "event_template": "Failed password for <*> from <*> port <*>",
      "level": "ERROR",
      "component": "sshd",
      "line_id": "105"
    },
    "anomaly_type": "authentication_error",
    "severity": "High",
    "confidence": 0.871,
    "anomaly_score": 0.005123,
    "processing_mode": "sequential",
    "timestamp": "03:45:12"
  }
]
```

**Response** `200 OK`
```
Logs received and broadcasted
```

**Error** `400 Bad Request`
```
❌ Request must be an array of logs
```

**Error** `500 Internal Server Error`
```
Failed to save logs
```

**Side effect:** For each saved document, emits `new_log` event via Socket.IO.

---

### GET /api/system-health

Returns live system resource metrics. CPU usage is measured asynchronously
(~100ms delay due to `os-utils` sampling).

**Request**
```
GET /api/system-health
```

**Response** `200 OK`
```json
{
  "cpu": {
    "usage": 23.45
  },
  "memory": {
    "total": 17179869184,
    "free": 8589934592,
    "used": 8589934592,
    "usedPercentage": 50.0
  },
  "disk": {
    "total": 476.84,
    "free": 210.32,
    "used": 266.52,
    "usedPercentage": 55.89
  },
  "system": {
    "hostname": "siem-server",
    "uptime": 86400,
    "platform": "linux",
    "arch": "x64",
    "cores": 8
  }
}
```

Units:
- `cpu.usage` — percentage (0–100)
- `memory.*` — bytes (except `usedPercentage`)
- `disk.*` — gigabytes (except `usedPercentage`)
- `system.uptime` — seconds

**Error** `500 Internal Server Error`
```json
{ "error": "Failed to fetch disk usage" }
```

---

## WebSocket Events (Socket.IO)

Connect to: `ws://localhost:5000`

```javascript
import { io } from 'socket.io-client';
const socket = io('http://localhost:5000');
```

### Event: `new_log`

Emitted by the server after each successful `POST /api/logs` insert.
One event per inserted document.

**Payload:** Full MongoDB document (same schema as `GET /api/logs` response items)

```javascript
socket.on('new_log', (log) => {
  console.log(log.anomaly_type, log.severity, log.confidence);
});
```

---

## Python ExpressExporter

The `ExpressExporter` class (`model/src/utils/express_exporter.py`) handles pushing
detection results from the Python model to the Express backend.

### Configuration (from `log-anomaly-detection.yml`)

```yaml
express_backend:
  enabled: true
  base_url: "http://localhost:5000"
  timeout: 30
  retry_attempts: 3
```

### Methods

#### `test_connection() → bool`

Sends `GET /api/system-health`. Returns `True` if status 200.

```python
exporter = ExpressExporter(config)
if exporter.test_connection():
    print("Backend reachable")
```

#### `export_anomalies(anomalies: list) → bool`

Converts the anomaly list from the pipeline output format to the Express schema
and sends to `POST /api/logs`.

Retry behavior: up to 3 attempts with exponential backoff (1s, 2s, 4s).

```python
exporter.export_anomalies(results['anomalies'])
```

**Format conversion:**
- Sequential anomalies: uses `anomaly['logs'][0]` as the representative log
- Single log anomalies: uses `anomaly['log']` directly

> **Note:** The `processing_mode` field in the anomaly output from the pipeline
> is not currently set by `pipeline.py`. The exporter passes it through as-is,
> which means it will be `None` or missing in the stored document.

---

## Health Check

To verify the full stack is running:

```bash
# Backend health
curl http://localhost:5000/api/system-health

# Recent logs
curl http://localhost:5000/api/logs

# Test from Python
cd model/
python src/logAnomalyDetection/run.py --test-express-connection
```
