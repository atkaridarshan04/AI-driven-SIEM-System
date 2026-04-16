import os
import sys
import json
import time
import threading
from collections import deque
from pathlib import Path

from fastapi import FastAPI
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
from confluent_kafka import Consumer, Producer
from elasticsearch import Elasticsearch

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.logAnomalyDetection.LSTM_AE.severity    import EnhancedSeverityManager
from src.logAnomalyDetection.LSTM_AE.classifier  import LabeledLDAClassifier
from src.logAnomalyDetection.LSTM_AE.autoencoder import SequentialLSTMAutoencoder
from src.logAnomalyDetection.LSTM_AE.detector    import EnsembleDetector
from src.logAnomalyDetection.LSTM_AE.preprocessor import DataPreprocessor
from src.logAnomalyDetection.pipeline import AnomalyDetectionPipeline
from src.utils.config_loader import load_config

# ── Config ────────────────────────────────────────────────────────────────────
KAFKA_HOST      = os.getenv("KAFKA_HOST", "localhost")
ES_HOST         = os.getenv("ES_HOST", "http://elasticsearch:9200")
ES_USER         = os.getenv("ES_USER", "elastic")
ES_PASS         = os.getenv("ELASTIC_PASSWORD", "")
ARTIFACTS_PATH  = os.getenv("MODEL_ARTIFACTS_PATH", "artifacts/")
SEQ_LEN         = int(os.getenv("SEQ_LEN", "8"))

# ── Prometheus metrics ────────────────────────────────────────────────────────
ANOMALIES_TOTAL   = Counter("siem_anomalies_total", "Total anomalies detected", ["severity"])
INFERENCE_LATENCY = Histogram("siem_inference_seconds", "Inference latency per window")
LOGS_CONSUMED     = Counter("siem_logs_consumed_total", "Total log lines consumed from Kafka")
PIPELINE_UP       = Gauge("siem_pipeline_up", "1 if pipeline is running")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="SIEM Model API")

config   = load_config(str(Path(__file__).parent.parent / "configs/log-anomaly-detection.yml"))
pipeline = AnomalyDetectionPipeline(config.get("detection", {}))
es       = Elasticsearch(ES_HOST, basic_auth=(ES_USER, ES_PASS))

@app.on_event("startup")
def startup():
    if not pipeline.load():
        raise RuntimeError("Failed to load model artifacts")
    thread = threading.Thread(target=_kafka_consumer_loop, daemon=True)
    thread.start()

@app.get("/health")
def health():
    return {"status": "ok", "pipeline_ready": pipeline._ready}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# ── Kafka streaming consumer ──────────────────────────────────────────────────
def _kafka_consumer_loop():
    consumer = Consumer({
        "bootstrap.servers": f"{KAFKA_HOST}:9092",
        "group.id": "siem-model",
        "auto.offset.reset": "latest",
    })
    consumer.subscribe(["raw-logs"])
    PIPELINE_UP.set(1)

    buffer = deque()  # rolling window of raw log dicts

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue

            LOGS_CONSUMED.inc()
            try:
                record = json.loads(msg.value().decode("utf-8"))
            except Exception:
                continue

            buffer.append(record)

            if len(buffer) >= SEQ_LEN:
                window = list(buffer)
                buffer.clear()
                _process_window(window)

    finally:
        PIPELINE_UP.set(0)
        consumer.close()


def _process_window(window: list):
    import pandas as pd

    df = pd.DataFrame([{
        "Content":       r.get("message", ""),
        "EventTemplate": r.get("message", ""),
        "Level":         r.get("level", ""),
        "Component":     r.get("hostname", ""),
        "Time":          r.get("@timestamp", ""),
        "LineId":        str(i),
    } for i, r in enumerate(window)])

    start = time.time()
    try:
        results = pipeline.run(df)
    except Exception as e:
        print(f"[model] inference error: {e}")
        return
    INFERENCE_LATENCY.observe(time.time() - start)

    for anomaly in results.get("anomalies", []):
        ANOMALIES_TOTAL.labels(severity=anomaly["severity"]).inc()
        _index_anomaly(anomaly)


def _index_anomaly(anomaly: dict):
    from datetime import datetime
    doc = {**anomaly, "indexed_at": datetime.utcnow().isoformat()}
    try:
        es.index(index=f"anomalies-{datetime.utcnow().strftime('%Y.%m.%d')}", document=doc)
    except Exception as e:
        print(f"[es] index error: {e}")
