"""
train.py — V1.5 training script for the sequential LSTM ensemble.

Produces (in artifacts_dir/):
  • final_lstm_sequential.pth          — list of 3 state_dicts
  • hybrid_ensemble_artifacts.pkl      — preprocessing objects + severity thresholds
                                         + ensemble weights

Usage (from model/ directory):
    python src/logAnomalyDetection/LSTM_AE/train.py \
        --data  data/logs/processed/all_logs_combined.csv \
        --out   artifacts/

All hyper-parameters can be overridden via CLI flags (see --help).
"""

import argparse
import pickle
import sys
from pathlib import Path

from tqdm import tqdm

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from torch.utils.data import DataLoader

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.logAnomalyDetection.LSTM_AE.autoencoder import SequentialLSTMAutoencoder
from src.logAnomalyDetection.LSTM_AE.dataset      import LogDataset
from src.logAnomalyDetection.LSTM_AE.severity     import EnhancedSeverityManager


# ---------------------------------------------------------------------------
# Hyper-parameters (overridable via CLI)
# ---------------------------------------------------------------------------

ENSEMBLE_CONFIGS = [
    {'hidden_dim': 16, 'dropout': 0.3},
    {'hidden_dim': 24, 'dropout': 0.4},
    {'hidden_dim': 32, 'dropout': 0.2},
]

DEFAULTS = dict(
    seq_len=8, stride=8, batch_size=32,
    epochs=50, lr=1e-3,
    val_split=0.15, early_stopping=5,
    max_tfidf=50,
)


# ---------------------------------------------------------------------------
# Feature engineering  (fits transformers, returns scaled array + artifacts)
# ---------------------------------------------------------------------------

def build_features(df: pd.DataFrame, max_tfidf: int) -> tuple[np.ndarray, dict]:
    df = df.drop(columns=[c for c in ['LineId', 'Time', 'Date', 'PID', 'Month'] if c in df.columns])

    cat_cols = [c for c in ['Level', 'Component', 'EventId'] if c in df.columns]

    # EventTemplate: TF-IDF if high-cardinality, else OHE
    tfidf = other_ohe = None
    if 'EventTemplate' in df.columns:
        if df['EventTemplate'].nunique() >= 1000:
            tfidf = TfidfVectorizer(max_features=max_tfidf)
            tmpl_features = tfidf.fit_transform(df['EventTemplate'].astype(str)).toarray()
            df = df.drop(columns=['EventTemplate'])
        else:
            cat_cols.append('EventTemplate')
            tmpl_features = None
    else:
        tmpl_features = None

    if 'Content' in df.columns:
        c = df['Content']
        df['content_length']            = c.str.len()
        df['content_word_count']        = c.str.split().str.len()
        df['content_has_error']         = c.str.contains(r'\b(?:error|fail|exception|crash|abort|fault)\b',       case=False, na=False).astype(int)
        df['content_has_warning']       = c.str.contains(r'\b(?:warn|alert|caution)\b',                           case=False, na=False).astype(int)
        df['content_has_large_numbers'] = c.str.contains(r'\b\d{4,}\b',                                         na=False).astype(int)
        df['content_has_critical']      = c.str.contains(r'\b(?:critical|fatal|panic|segfault|timeout|killed)\b', case=False, na=False).astype(int)
        df['content_has_network']       = c.str.contains(r'\b(?:connection|socket|port|network|tcp|udp)\b',       case=False, na=False).astype(int)
        df['content_has_memory']        = c.str.contains(r'\b(?:memory|malloc|free|leak|oom|out of memory)\b',    case=False, na=False).astype(int)
        df = df.drop(columns=['Content'])

    cat_cols = [c for c in cat_cols if c in df.columns]
    if cat_cols:
        other_ohe = OneHotEncoder(handle_unknown='ignore', sparse_output=False)
        cat_features = other_ohe.fit_transform(df[cat_cols].astype(str))
        df = df.drop(columns=cat_cols)
    else:
        cat_features = np.empty((len(df), 0))

    if tmpl_features is not None:
        cat_features = np.hstack([tmpl_features, cat_features]) if cat_features.shape[1] else tmpl_features

    num_cols = list(df.columns)
    if num_cols:
        imputer = SimpleImputer(strategy='median')
        num_features = imputer.fit_transform(df[num_cols].apply(pd.to_numeric, errors='coerce'))
    else:
        imputer = SimpleImputer(strategy='median')
        num_features = np.empty((len(df), 0))

    parts = [p for p in [cat_features, num_features] if p.shape[1] > 0]
    if not parts:
        raise ValueError("No features produced — check input CSV columns")
    combined = np.hstack(parts)

    scaler = StandardScaler()
    scaled = scaler.fit_transform(combined)

    ohe_artifact = (tfidf, other_ohe) if tfidf is not None else other_ohe
    artifacts = {
        'ohe':      ohe_artifact,
        'imputer':  imputer,
        'scaler':   scaler,
        'input_dim': scaled.shape[1],
    }
    return scaled, artifacts


# ---------------------------------------------------------------------------
# Training one autoencoder
# ---------------------------------------------------------------------------

def train_model(
    model: SequentialLSTMAutoencoder,
    train_loader: DataLoader,
    val_loader:   DataLoader,
    epochs: int, lr: float, patience: int,
    device: torch.device,
) -> list[float]:
    """Train model, return per-epoch validation losses."""
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.MSELoss()

    best_val, no_improve, best_state = float('inf'), 0, None
    val_losses = []

    epoch_bar = tqdm(range(1, epochs + 1), desc='Epochs', unit='ep')
    for epoch in epoch_bar:
        model.train()
        train_loss = 0.0
        for batch in tqdm(train_loader, desc=f'  Train', leave=False, unit='batch'):
            batch = batch.to(device)
            recon, _ = model(batch)
            loss = criterion(recon, batch)
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item()
        train_loss /= len(train_loader)

        # Validation
        model.eval()
        v_loss = 0.0
        with torch.no_grad():
            for batch in tqdm(val_loader, desc=f'  Val  ', leave=False, unit='batch'):
                batch = batch.to(device)
                recon, _ = model(batch)
                v_loss += criterion(recon, batch).item()
        v_loss /= len(val_loader)
        val_losses.append(v_loss)

        epoch_bar.set_postfix(train=f'{train_loss:.5f}', val=f'{v_loss:.5f}', best=f'{best_val:.5f}')

        if v_loss < best_val - 1e-6:
            best_val, no_improve = v_loss, 0
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            no_improve += 1
            if no_improve >= patience:
                epoch_bar.write(f'   ⏹ Early stopping at epoch {epoch}')
                break

    if best_state:
        model.load_state_dict(best_state)
    model.to('cpu')
    return val_losses


# ---------------------------------------------------------------------------
# Per-model validation loss (used for ensemble weighting)
# ---------------------------------------------------------------------------

def val_loss(model: SequentialLSTMAutoencoder, val_loader: DataLoader) -> float:
    """Mean MSE reconstruction error on the validation set."""
    criterion = nn.MSELoss()
    total = 0.0
    model.eval()
    with torch.no_grad():
        for batch in val_loader:
            recon, _ = model(batch)
            total += criterion(recon, batch).item()
    return total / len(val_loader)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='Train V1.5 sequential LSTM ensemble')
    ap.add_argument('--data',     required=True, help='Path to structured training CSV')
    ap.add_argument('--out',      default='artifacts/', help='Output directory for artifacts')
    ap.add_argument('--seq-len',  type=int,   default=DEFAULTS['seq_len'])
    ap.add_argument('--stride',   type=int,   default=DEFAULTS['stride'])
    ap.add_argument('--batch',    type=int,   default=DEFAULTS['batch_size'])
    ap.add_argument('--epochs',   type=int,   default=DEFAULTS['epochs'])
    ap.add_argument('--lr',       type=float, default=DEFAULTS['lr'])
    ap.add_argument('--val-split',type=float, default=DEFAULTS['val_split'])
    ap.add_argument('--patience', type=int,   default=DEFAULTS['early_stopping'])
    ap.add_argument('--max-tfidf',type=int,   default=DEFAULTS['max_tfidf'])
    ap.add_argument('--severity-percentiles', nargs='+', type=int, default=[85, 95, 99])
    args = ap.parse_args()

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"🖥️  Device: {device}")

    # ---- Load & preprocess ----
    print(f"\n📂 Loading data: {args.data}")
    df = pd.read_csv(args.data)
    print(f"   • {len(df)} rows, {len(df.columns)} columns")

    print("\n⚙️  Building features...")
    scaled, artifacts = build_features(df, args.max_tfidf)
    input_dim = artifacts['input_dim']
    print(f"   • Input dim: {input_dim}")

    # ---- Train/val split ----
    idx = np.arange(len(scaled))
    train_idx, val_idx = train_test_split(idx, test_size=args.val_split, shuffle=False)

    train_ds = LogDataset(scaled[train_idx], args.seq_len, args.stride)
    val_ds   = LogDataset(scaled[val_idx],   args.seq_len, args.stride)
    train_dl = DataLoader(train_ds, batch_size=args.batch, shuffle=True,  drop_last=True)
    val_dl   = DataLoader(val_ds,   batch_size=args.batch, shuffle=False)

    print(f"   • Train sequences: {len(train_ds)}  |  Val sequences: {len(val_ds)}")

    # ---- Train ensemble ----
    state_dicts, f1_scores = [], []

    for i, cfg in enumerate(tqdm(ENSEMBLE_CONFIGS, desc='Ensemble models', unit='model')):
        tqdm.write(f"\n🧠 Model {i+1}/{len(ENSEMBLE_CONFIGS)}  {cfg}")
        model = SequentialLSTMAutoencoder(input_dim, **cfg)
        train_model(model, train_dl, val_dl, args.epochs, args.lr, args.patience, device)
        state_dicts.append(model.state_dict())
        score = val_loss(model, val_dl)
        f1_scores.append(score)
        tqdm.write(f"   • Val loss: {score:.6f}")
    # ---- Ensemble weights: lower val loss → higher weight ----
    f1 = np.array(f1_scores)
    inv = 1.0 / (f1 + 1e-8)
    ensemble_weights = (inv / inv.sum()).tolist()
    print(f"\n⚖️  Val losses: {[round(s, 6) for s in f1_scores]}")
    print(f"⚖️  Ensemble weights: {[round(w, 4) for w in ensemble_weights]}")

    # ---- Severity thresholds from full training errors ----
    print("\n📊 Learning severity thresholds...")
    full_ds = LogDataset(scaled, args.seq_len, args.stride)
    full_dl = DataLoader(full_ds, batch_size=args.batch, shuffle=False)

    # Weighted ensemble errors on training data
    all_errors = []
    for i, (state, w) in enumerate(tqdm(zip(state_dicts, ensemble_weights), total=len(state_dicts), desc='Severity errors', unit='model')):
        m = SequentialLSTMAutoencoder(input_dim, **ENSEMBLE_CONFIGS[i])
        m.load_state_dict(state)
        m.eval()
        errs = []
        with torch.no_grad():
            for batch in full_dl:
                recon, _ = m(batch)
                errs.extend(torch.mean((batch - recon) ** 2, dim=(1, 2)).numpy())
        all_errors.append(np.array(errs) * w)

    ensemble_errors = np.sum(all_errors, axis=0)
    severity_manager = EnhancedSeverityManager(percentiles=args.severity_percentiles)
    severity_manager.learn_thresholds(ensemble_errors)

    # ---- Save ----
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    model_path = out_dir / 'final_lstm_sequential.pth'
    torch.save(state_dicts, model_path)
    print(f"\n💾 Saved model weights → {model_path}")

    artifacts['ensemble_weights'] = ensemble_weights
    artifacts['severity_manager'] = severity_manager

    artifacts_path = out_dir / 'hybrid_ensemble_artifacts.pkl'
    with open(artifacts_path, 'wb') as f:
        pickle.dump(artifacts, f)
    print(f"💾 Saved artifacts     → {artifacts_path}")

    print("\n✅ Training complete — V1.5 artifacts ready for inference.")


if __name__ == '__main__':
    main()
