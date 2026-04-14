import torch
from torch.utils.data import Dataset


class LogDataset(Dataset):
    """Sliding-window dataset over preprocessed log feature matrix."""

    def __init__(self, data, seq_len: int = 8, stride: int = 8):
        self.samples = [data[i:i + seq_len] for i in range(0, len(data) - seq_len, stride)]
        self.indices = list(range(0, len(data) - seq_len, stride))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        return torch.tensor(self.samples[idx], dtype=torch.float)
