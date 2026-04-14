import pickle

import numpy as np
import torch
from torch.utils.data import DataLoader

from .autoencoder import SequentialLSTMAutoencoder


class EnsembleDetector:
    """
    Weighted ensemble of SequentialLSTMAutoencoders.
    Weights are performance-based (F1) and stored in the artifacts file.
    """

    _CONFIGS = [
        {'hidden_dim': 16, 'dropout': 0.3},
        {'hidden_dim': 24, 'dropout': 0.4},
        {'hidden_dim': 32, 'dropout': 0.2},
    ]

    def __init__(self):
        self.models:    list  = []
        self.weights:   list  = []
        self.input_dim: int   = None
        self.is_loaded: bool  = False

    def load(self, artifacts_path: str, model_path: str) -> bool:
        """Load weights from artifacts_path and model file from model_path."""
        try:
            with open(artifacts_path, 'rb') as f:
                artifacts = pickle.load(f)

            self.input_dim  = artifacts['input_dim']
            raw_weights     = artifacts.get('ensemble_weights', [1.0] * len(self._CONFIGS))

            model_file  = f"{model_path}/final_lstm_sequential.pth"
            state       = torch.load(model_file, map_location='cpu')
            state_dicts = state if isinstance(state, list) else [state] * len(self._CONFIGS)

            self.models, self.weights = [], []
            for i, cfg in enumerate(self._CONFIGS):
                m = SequentialLSTMAutoencoder(self.input_dim, **cfg)
                m.load_state_dict(state_dicts[i] if i < len(state_dicts) else state_dicts[-1])
                m.eval()
                self.models.append(m)
                self.weights.append(raw_weights[i] if i < len(raw_weights) else 1.0)

            self.is_loaded = True
            print(f"✅ Loaded {len(self.models)} models from {model_file}")
            return True

        except Exception as e:
            print(f"❌ Failed to load models: {e}")
            return False

    def predict(self, dataloader: DataLoader) -> np.ndarray:
        """Returns weighted-ensemble MSE reconstruction errors, shape (n_sequences,)."""
        if not self.is_loaded:
            raise RuntimeError("Call load() before predict()")
        per_model = [self._eval(m, dataloader) for m in self.models]
        w = np.array(self.weights, dtype=float)
        return np.average(per_model, axis=0, weights=w / w.sum())

    def _eval(self, model, dataloader: DataLoader) -> np.ndarray:
        errors = []
        with torch.no_grad():
            for batch in dataloader:
                recon, _ = model(batch)
                errors.extend(torch.mean((batch - recon) ** 2, dim=(1, 2)).numpy())
        return np.array(errors)

    def update_weights(self, val_losses: list):
        """Recompute ensemble weights: lower val loss → higher weight."""
        inv = np.array([1.0 / (v + 1e-8) for v in val_losses])
        self.weights = (inv / inv.sum()).tolist()
        print(f"✅ Ensemble weights: {[round(w, 4) for w in self.weights]}")


# Legacy alias
HybridEnsembleDetector = EnsembleDetector
