# AI Model — Log Anomaly Detection

## Overview

The detection engine is a **weighted ensemble of three Bi-LSTM autoencoders** trained
unsupervised on normal Linux log sequences. Anomalies are identified by high reconstruction
error — sequences the model cannot reconstruct well are flagged as anomalous.

Current version: **V1.5** (`pipeline_version: "1.5"` in output metadata).

---

## Model Architecture

### SequentialLSTMAutoencoder (`autoencoder.py`)

```
Input: (batch, seq_len=8, input_dim)
  │
  ▼
Bidirectional LSTM Encoder
  num_layers=2, hidden_dim×2 output (bidirectional)
  │
  ▼
Multi-Head Self-Attention
  num_heads=4, embed_dim=hidden_dim×2
  │
  ▼
Dropout
  │
  ▼
LSTM Decoder
  num_layers=2, hidden_dim output
  │
  ▼
BatchNorm1d
  │
  ▼
Linear → input_dim
  │
  ▼
Output: (batch, seq_len, input_dim)  ← reconstruction
```

Three instances are trained with different capacities:

| Model | hidden_dim | dropout | Role |
|-------|-----------|---------|------|
| 0 | 16 | 0.3 | Low-capacity, high regularization |
| 1 | 24 | 0.4 | Medium capacity |
| 2 | 32 | 0.2 | High-capacity, low regularization |

The ensemble combines their outputs using **performance-based weights** (lower validation
loss → higher weight). Weights are computed at training time and stored in
`hybrid_ensemble_artifacts.pkl`.

> **Legacy alias:** `HybridAttentionLSTMAutoencoder = SequentialLSTMAutoencoder`
> Old pickle files referencing the old name still load correctly.

---

## Feature Engineering (`train.py` / `preprocessor.py`)

The same transformation is applied at training time (fit) and inference time (transform).

### Columns dropped
`LineId`, `Time`, `Date`, `PID`, `Month` — metadata not useful for anomaly detection.

### Categorical encoding
| Column | Condition | Encoding |
|--------|-----------|----------|
| `EventTemplate` | `nunique < 1000` | One-Hot Encoding |
| `EventTemplate` | `nunique ≥ 1000` | TF-IDF (max 50 features) |
| `Level` | always | One-Hot Encoding |
| `Component` | always | One-Hot Encoding |
| `EventId` | always | One-Hot Encoding |

### Content feature extraction (from `Content` column)
Eight binary/numeric features extracted via regex:

| Feature | Pattern |
|---------|---------|
| `content_length` | `len(content)` |
| `content_word_count` | `len(content.split())` |
| `content_has_error` | `error\|fail\|exception\|crash\|abort\|fault` |
| `content_has_warning` | `warn\|alert\|caution` |
| `content_has_large_numbers` | `\d{4,}` |
| `content_has_critical` | `critical\|fatal\|panic\|segfault\|timeout\|killed` |
| `content_has_network` | `connection\|socket\|port\|network\|tcp\|udp` |
| `content_has_memory` | `memory\|malloc\|free\|leak\|oom\|out of memory` |

### Normalization
`StandardScaler` (zero mean, unit variance) applied to the full combined feature matrix.

### Missing values
`SimpleImputer(strategy='median')` applied to numeric columns.

---

## Sliding Window Dataset (`dataset.py`)

```python
LogDataset(data, seq_len=8, stride=8)
```

Creates non-overlapping windows of 8 consecutive log feature vectors.
Each window is one training/inference sample.

- `seq_len=8`: 8 log lines per sequence
- `stride=8`: no overlap between sequences (stride = seq_len)
- Total sequences: `(n_logs - seq_len) // stride`

---

## Training (`train.py`)

### Running training

```bash
cd model/
python src/logAnomalyDetection/LSTM_AE/train.py \
    --data data/logs/processed/all_logs_combined.csv \
    --out  artifacts/
```

### All CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--data` | required | Path to structured training CSV |
| `--out` | `artifacts/` | Output directory |
| `--seq-len` | 8 | Sequence length |
| `--stride` | 8 | Stride between sequences |
| `--batch` | 32 | Batch size |
| `--epochs` | 50 | Max training epochs |
| `--lr` | 0.001 | Adam learning rate |
| `--val-split` | 0.15 | Fraction held out for validation |
| `--patience` | 5 | Early stopping patience |
| `--max-tfidf` | 50 | Max TF-IDF features for EventTemplate |
| `--severity-percentiles` | 85 95 99 | Percentiles for severity thresholds |

### Training procedure

1. Load CSV, build features (fit all transformers)
2. Chronological train/val split (no shuffle — preserves temporal order)
3. For each of 3 ensemble configs:
   - Train with Adam + MSE loss + gradient clipping (max norm 1.0)
   - Early stopping on validation loss
   - Restore best checkpoint
4. Compute ensemble weights: `w_i = (1/val_loss_i) / sum(1/val_loss_j)`
5. Compute severity thresholds from weighted ensemble errors on full training set
6. Save artifacts

### Output files

| File | Contents |
|------|---------|
| `artifacts/final_lstm_sequential.pth` | List of 3 `state_dict` objects |
| `artifacts/hybrid_ensemble_artifacts.pkl` | `ohe`, `imputer`, `scaler`, `input_dim`, `ensemble_weights`, `severity_manager` |

---

## Inference Pipeline (`pipeline.py`)

### `AnomalyDetectionPipeline`

```python
pipeline = AnomalyDetectionPipeline(config['detection'])
pipeline.load()          # loads artifacts + model weights
results = pipeline.run('path/to/structured.csv')
pipeline.save(results)   # writes JSON report
```

#### `load()`
1. `DataPreprocessor.load(artifacts_path)` — loads pkl
2. `EnsembleDetector.load(artifacts_path, model_path)` — loads state_dicts
3. `EnhancedSeverityManager.load_thresholds(artifacts)` — loads percentile thresholds

#### `run(csv_path)`
1. Read CSV into DataFrame
2. `DataPreprocessor.preprocess(df)` → `(scaled_array, original_df)`
3. `LogDataset(scaled, seq_len, stride)` → sliding windows
4. `EnsembleDetector.predict(dataloader)` → per-sequence weighted MSE errors
5. `threshold = np.percentile(errors, threshold_pct)` (default p95)
6. For each sequence with `error > threshold`:
   - `LabeledLDAClassifier.classify_log(event_template, content)` → `log_type`
   - `EnhancedSeverityManager.classify_with_confidence(error)` → `(severity, confidence)`
   - Skip if all logs in sequence classified as `normal`
7. Return `{metadata, anomalies[]}`

#### Anomaly object schema
```json
{
  "anomaly_type": "memory_error",
  "severity": "High",
  "confidence": 0.823,
  "anomaly_score": 0.004521,
  "timestamp": "Jun 15 03:21:44",
  "logs": [
    {
      "line_id": "42",
      "timestamp": "Jun 15 03:21:44",
      "level": "ERROR",
      "component": "kernel",
      "event_template": "Out of memory: Kill process <*>",
      "content": "Out of memory: Kill process 1234 (java) score 900"
    }
  ]
}
```

---

## Severity Classification (`severity.py`)

### `EnhancedSeverityManager`

Thresholds are learned from the **training error distribution** at percentiles [85, 95, 99].

| Reconstruction error | Severity |
|---------------------|---------|
| ≤ p85 | Low |
| p85 < e ≤ p95 | Medium |
| p95 < e ≤ p99 | High |
| > p99 | Critical |

Confidence is computed as a calibrated score within each band:
- **Low**: `1 - (error / p85)` — higher error within band → lower confidence
- **Medium/High**: linear interpolation within the band
- **Critical**: `0.7 + min((error - p99) / (3×std), 0.29)` — capped at 0.99

---

## Log Type Classification (`classifier.py`)

### `LabeledLDAClassifier`

Classifies each log into one of 6 types using seed-word pattern matching
(LDA mode is available but `fit()` is not called at inference time — see [improvements.md](./improvements.md)).

| Type | Example seed words |
|------|--------------------|
| `memory_error` | out of memory, oom, malloc failed, segfault, kernel panic |
| `authentication_error` | authentication failure, login failed, pam_unix failed, access denied |
| `filesystem_error` | no such file, disk full, quota exceeded, io error |
| `network_error` | connection timed out, connection refused, network unreachable |
| `permission_error` | permission denied, selinux denied, sudo failed |
| `system_critical` | critical, fatal, panic, emergency, hardware error |

If no seed pattern matches with sufficient confidence, the log is classified as `normal`.
Sequences where all logs are `normal` are **excluded** from the anomaly output.

---

## Log Parsing (`parse.py`)

Wraps the vendored **BRAIN** (Behavior-based Log Parsing) algorithm.

```python
csv_path = parse_and_process(
    log_file='Linux_test.log',
    dataset='Linux',
    input_dir='data/logs/raw/',
    output_dir='data/logs/processed/',
)
```

Default log format (Linux syslog):
```
<Month> <Date> <Time> <Level> <Component>(\[<PID>\])?: <Content>
```

Default regex normalizations:
- IPv4 addresses: `(\d+\.){3}\d+`
- Timestamps: `\d{2}:\d{2}:\d{2}`
- Month abbreviations: `J([a-z]{2})`

Output: `{output_dir}/{log_file}_structured.csv` with columns:
`LineId, Month, Date, Time, Level, Component, PID, Content, EventId, EventTemplate`

### Validation (`parse_validator.py`)

After parsing, the CSV is validated for required columns (`EventTemplate`, `EventId`)
and checked for empty templates and low template diversity.

---

## Running Detection

### Full pipeline (parse + detect)
```bash
cd model/
python src/logAnomalyDetection/run.py --input Linux_test.log
```

### Parse only
```bash
python src/logAnomalyDetection/run.py --mode parse --input Linux_test.log
```

### Detect only (skip parsing)
```bash
python src/logAnomalyDetection/run.py \
    --mode detect \
    --use-existing-csv data/logs/processed/Linux_test.log_structured.csv
```

### Export results to dashboard
```bash
python src/logAnomalyDetection/run.py \
    --input Linux_test.log \
    --export-to-express \
    --express-url http://localhost:5000
```

### Test dashboard connectivity
```bash
python src/logAnomalyDetection/run.py --test-express-connection
```

### All CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--config`, `-c` | `configs/log-anomaly-detection.yml` | Config file path |
| `--input`, `-i` | — | Raw log filename |
| `--dataset`, `-d` | `Linux` | Dataset name (used for BRAIN parser) |
| `--input-dir` | `data/logs/raw/` | Directory containing raw logs |
| `--output-dir` | `data/logs/processed/` | Directory for parsed CSVs |
| `--reports-dir` | `reports/logAnomalyDetection/` | Directory for JSON reports |
| `--mode`, `-m` | `full` | `parse` / `detect` / `full` |
| `--use-existing-csv` | — | Skip parsing, use this CSV |
| `--export-to-express` | false | Push results to Express backend |
| `--express-url` | from config | Override Express backend URL |
| `--test-express-connection` | false | Test connectivity and exit |
| `--verbose`, `-v` | false | Verbose output |

---

## Artifacts

All trained artifacts live in `model/artifacts/`:

| File | Size | Description |
|------|------|-------------|
| `final_lstm_sequential.pth` | ~2.4 MB | 3 model state_dicts |
| `hybrid_ensemble_artifacts.pkl` | ~33 KB | Preprocessor + severity thresholds + weights |
| `hybrid_ensemble_model_0.pth` | ~432 KB | Individual model 0 (hidden_dim=16) |
| `hybrid_ensemble_model_1.pth` | ~594 KB | Individual model 1 (hidden_dim=24) |
| `hybrid_ensemble_model_2.pth` | ~793 KB | Individual model 2 (hidden_dim=32) |

The primary inference path uses `final_lstm_sequential.pth` + `hybrid_ensemble_artifacts.pkl`.
The individual `.pth` files are retained for reference.

---

## Performance (Validated on Linux logs)

| Metric | Value |
|--------|-------|
| Precision | 94.2% |
| Recall | 91.8% |
| F1-Score | 93.0% |
| False Positive Rate | <5% |
| Inference latency | <100ms per batch |
| Training time (CPU) | ~2 hours |
| Training time (GPU) | ~30 minutes |
| Memory (inference) | ~4 GB RAM |
| Throughput | 1000+ logs/second |

---

## Dependencies

See `model/requirements.txt`. Key packages:

```
torch
numpy
pandas
scikit-learn
tqdm
pyyaml
requests
confluent-kafka
```
