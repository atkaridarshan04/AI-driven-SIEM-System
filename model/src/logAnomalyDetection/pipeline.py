import json
import pickle
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from .LSTM_AE.dataset      import LogDataset
from .LSTM_AE.detector     import EnsembleDetector
from .LSTM_AE.preprocessor import DataPreprocessor
from .LSTM_AE.severity     import EnhancedSeverityManager
from .LSTM_AE.classifier   import LabeledLDAClassifier


def _to_serializable(obj):
    """Recursively convert numpy scalars/arrays to native Python types."""
    if isinstance(obj, dict):
        return {_to_serializable(k): _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_serializable(i) for i in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _log_row(row, idx) -> dict:
    return {
        'line_id':        str(row.get('LineId', idx)),
        'timestamp':      str(row.get('Time', '')),
        'level':          row.get('Level', ''),
        'component':      row.get('Component', ''),
        'event_template': row.get('EventTemplate', ''),
        'content':        row.get('Content', ''),
    }


class AnomalyDetectionPipeline:
    """
    V1.5 sequential inference pipeline.

    Stages:
      1. load()       — load artifacts + model weights
      2. run(df)      — preprocess → detect → classify → return results
      3. save(results)— persist JSON to reports dir
    """

    def __init__(self, config: dict):
        self.config       = config
        self.model_path   = config.get('model_path', 'artifacts/')
        self.output_path  = config.get('output_path', 'reports/logAnomalyDetection/')
        self.seq_len      = config.get('seq_len', 8)
        self.stride       = config.get('stride', 8)
        self.batch_size   = config.get('batch_size', 32)
        self.threshold_pct= config.get('thresholds', {}).get('anomaly_percentile', 95)

        self.preprocessor  = DataPreprocessor()
        self.detector      = EnsembleDetector()
        self.severity      = EnhancedSeverityManager()
        self.classifier    = LabeledLDAClassifier()
        self._ready        = False

    # ------------------------------------------------------------------
    # 1. Initialisation
    # ------------------------------------------------------------------

    def load(self) -> bool:
        artifacts_path = f"{self.model_path}/hybrid_ensemble_artifacts.pkl"

        if not self.preprocessor.load(artifacts_path):
            return False
        if not self.detector.load(artifacts_path, self.model_path):
            return False

        self.severity.load_thresholds(self.preprocessor.artifacts)
        self._ready = True
        print("✅ Pipeline ready")
        return True

    # ------------------------------------------------------------------
    # 2. Inference
    # ------------------------------------------------------------------

    def run(self, input_data) -> dict:
        if not self._ready:
            raise RuntimeError("Call load() before run()")

        df = pd.read_csv(input_data) if isinstance(input_data, str) else input_data.copy()
        print(f"📊 Processing {len(df)} log entries...")

        processed, original_df = self.preprocessor.preprocess(df)
        print(f"   • Features: {processed.shape[1]}")

        dataset    = LogDataset(processed, self.seq_len, self.stride)
        dataloader = DataLoader(dataset, batch_size=self.batch_size, shuffle=False)

        errors    = self.detector.predict(dataloader)
        threshold = np.percentile(errors, self.threshold_pct)

        anomalies = self._build_anomalies(errors, threshold, original_df)
        print(f"   • Anomalies detected: {len(anomalies)}")

        return {
            'metadata': {
                'timestamp':            datetime.now().isoformat(),
                'total_logs':           len(df),
                'pipeline_version':     '1.5',
                'threshold':            float(threshold),
                'threshold_percentile': self.threshold_pct,
            },
            'anomalies': anomalies,
        }

    def _build_anomalies(self, errors, threshold, original_df) -> list:
        results = []
        for seq_idx, error in enumerate(errors):
            if error <= threshold:
                continue

            start = seq_idx * self.stride
            seq_logs = []
            seq_types = []

            for offset in range(self.seq_len):
                log_idx = start + offset
                if log_idx >= len(original_df):
                    break
                row = original_df.iloc[log_idx]
                clf = self.classifier.classify_log(
                    row.get('EventTemplate', ''), row.get('Content', '')
                )
                seq_types.append(clf['log_type'])
                seq_logs.append(_log_row(row, log_idx))

            non_normal = [t for t in seq_types if t != 'normal']
            if not non_normal:
                continue

            severity, confidence = self.severity.classify_with_confidence(float(error))
            dominant_type = Counter(non_normal).most_common(1)[0][0]

            results.append({
                'anomaly_type':  dominant_type,
                'severity':      severity,
                'confidence':    confidence,
                'anomaly_score': float(error),
                'timestamp':     seq_logs[0]['timestamp'] if seq_logs else '',
                'logs':          seq_logs,
            })

        return results

    # ------------------------------------------------------------------
    # 3. Persistence
    # ------------------------------------------------------------------

    def save(self, results: dict) -> str:
        out_dir = Path(self.output_path)
        out_dir.mkdir(parents=True, exist_ok=True)

        out_file = out_dir / 'anomaly_detection_results.json'
        with open(out_file, 'w') as f:
            json.dump(_to_serializable(results), f, indent=2)

        print(f"📁 Results saved to {out_file}")
        return str(out_dir)

