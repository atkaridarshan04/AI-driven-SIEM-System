import torch
import torch.nn as nn


class SequentialLSTMAutoencoder(nn.Module):
    """Bi-LSTM encoder → Multi-head Attention → LSTM decoder."""

    def __init__(self, input_dim: int, hidden_dim: int = 16, dropout: float = 0.4):
        super().__init__()
        self.encoder    = nn.LSTM(input_dim, hidden_dim, batch_first=True,
                                  num_layers=2, dropout=dropout, bidirectional=True)
        self.attention  = nn.MultiheadAttention(hidden_dim * 2, num_heads=4,
                                                dropout=dropout, batch_first=True)
        self.decoder    = nn.LSTM(hidden_dim * 2, hidden_dim, batch_first=True,
                                  num_layers=2, dropout=dropout)
        self.batch_norm = nn.BatchNorm1d(hidden_dim)
        self.output     = nn.Linear(hidden_dim, input_dim)
        self.dropout    = nn.Dropout(dropout)

    def forward(self, x):
        enc_out, _      = self.encoder(x)
        attn_out, attn  = self.attention(enc_out, enc_out, enc_out)
        dec_out, _      = self.decoder(self.dropout(attn_out))
        dec_out         = self.batch_norm(dec_out.transpose(1, 2)).transpose(1, 2)
        return self.output(dec_out), attn


