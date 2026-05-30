"""DL 架构注册表（纯 torch 自实现）。

加一个 DL 模型 = 加一个 nn.Module + 注册一行。训练循环在 trainer.py 共用。
本模块只在隔离子进程里被 import（torch 在此 OK）。

约定：每个网络 forward 输入 (B, lookback, F)，输出 (B, n_outputs)。
n_outputs = 1（回归）或 n_classes（分类）。
"""

from __future__ import annotations

from typing import Any

import torch
from torch import nn


class LSTMNet(nn.Module):
    def __init__(self, n_features: int, n_outputs: int, *, hidden_size: int = 32, num_layers: int = 1, dropout: float = 0.1, **_: Any) -> None:
        super().__init__()
        self.lstm = nn.LSTM(n_features, hidden_size, num_layers, batch_first=True, dropout=dropout if num_layers > 1 else 0.0)
        self.head = nn.Linear(hidden_size, n_outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :])


class GRUNet(nn.Module):
    def __init__(self, n_features: int, n_outputs: int, *, hidden_size: int = 32, num_layers: int = 1, dropout: float = 0.1, **_: Any) -> None:
        super().__init__()
        self.gru = nn.GRU(n_features, hidden_size, num_layers, batch_first=True, dropout=dropout if num_layers > 1 else 0.0)
        self.head = nn.Linear(hidden_size, n_outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.gru(x)
        return self.head(out[:, -1, :])


class ALSTMNet(nn.Module):
    """Attention-LSTM（qlib 风）：LSTM 输出按时间步注意力加权汇聚后再预测。"""

    def __init__(self, n_features: int, n_outputs: int, *, hidden_size: int = 32, num_layers: int = 1, dropout: float = 0.1, **_: Any) -> None:
        super().__init__()
        self.lstm = nn.LSTM(n_features, hidden_size, num_layers, batch_first=True, dropout=dropout if num_layers > 1 else 0.0)
        self.attn = nn.Sequential(nn.Linear(hidden_size, hidden_size), nn.Tanh(), nn.Linear(hidden_size, 1))
        self.head = nn.Linear(hidden_size, n_outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)  # (B, T, H)
        weights = torch.softmax(self.attn(out).squeeze(-1), dim=1)  # (B, T)
        context = (out * weights.unsqueeze(-1)).sum(dim=1)  # (B, H)
        return self.head(context)


class MLPNet(nn.Module):
    """把 lookback×F 摊平喂 MLP（不建模时序顺序，作为 DL 基线）。"""

    def __init__(self, n_features: int, n_outputs: int, *, lookback: int = 20, hidden_size: int = 64, dropout: float = 0.1, **_: Any) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(n_features * lookback, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, n_outputs),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class _Chomp(nn.Module):
    def __init__(self, chomp: int) -> None:
        super().__init__()
        self.chomp = chomp

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x[:, :, : -self.chomp] if self.chomp > 0 else x


class TCNNet(nn.Module):
    """因果膨胀卷积 TCN：堆叠 dilation=1,2,4… 的 Conv1d。"""

    def __init__(self, n_features: int, n_outputs: int, *, hidden_size: int = 32, num_layers: int = 2, kernel_size: int = 3, dropout: float = 0.1, **_: Any) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        in_ch = n_features
        for i in range(num_layers):
            dilation = 2**i
            pad = (kernel_size - 1) * dilation
            layers += [
                nn.Conv1d(in_ch, hidden_size, kernel_size, padding=pad, dilation=dilation),
                _Chomp(pad),
                nn.ReLU(),
                nn.Dropout(dropout),
            ]
            in_ch = hidden_size
        self.tcn = nn.Sequential(*layers)
        self.head = nn.Linear(hidden_size, n_outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.tcn(x.transpose(1, 2))  # (B, C, T)
        return self.head(y[:, :, -1])


class TransformerNet(nn.Module):
    """Transformer encoder：线性投影 + 位置编码 + 自注意力，末步预测。"""

    def __init__(self, n_features: int, n_outputs: int, *, hidden_size: int = 32, num_layers: int = 2, n_heads: int = 4, dropout: float = 0.1, lookback: int = 20, **_: Any) -> None:
        super().__init__()
        # n_heads 必须整除 hidden_size，否则 MultiheadAttention 构造即崩 → 自动收缩到可整除值
        heads = max(1, int(n_heads))
        while heads > 1 and hidden_size % heads != 0:
            heads -= 1
        self.proj = nn.Linear(n_features, hidden_size)
        self.pos = nn.Parameter(torch.zeros(1, lookback, hidden_size))
        enc = nn.TransformerEncoderLayer(hidden_size, heads, hidden_size * 2, dropout, batch_first=True)
        self.encoder = nn.TransformerEncoder(enc, num_layers)
        self.head = nn.Linear(hidden_size, n_outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.proj(x) + self.pos[:, : x.size(1), :]
        h = self.encoder(h)
        return self.head(h[:, -1, :])


class _GLU(nn.Module):
    """门控线性单元（TFT 的门控残差用）。"""

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.fc = nn.Linear(dim, dim * 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a, b = self.fc(x).chunk(2, dim=-1)
        return a * torch.sigmoid(b)


class TFTNet(nn.Module):
    """Temporal Fusion Transformer（简化纯 torch 实现）。

    变量选择(逐特征 softmax 门控) → 输入投影 → LSTM 编码 → 多头自注意力 →
    门控残差 + LayerNorm → 末步预测。抓住 TFT 的核心机制（变量选择 + 可解释注意力）。
    """

    def __init__(
        self, n_features: int, n_outputs: int, *, hidden_size: int = 32, lstm_layers: int = 1,
        attention_head_size: int = 4, dropout: float = 0.1, **_: Any,
    ) -> None:
        super().__init__()
        # 注意力头数须整除 hidden_size
        heads = attention_head_size
        while heads > 1 and hidden_size % heads != 0:
            heads -= 1
        self.var_select = nn.Sequential(nn.Linear(n_features, n_features), nn.Tanh(), nn.Linear(n_features, n_features))
        self.input_proj = nn.Linear(n_features, hidden_size)
        self.lstm = nn.LSTM(hidden_size, hidden_size, lstm_layers, batch_first=True, dropout=dropout if lstm_layers > 1 else 0.0)
        self.attn = nn.MultiheadAttention(hidden_size, heads, dropout=dropout, batch_first=True)
        self.glu = _GLU(hidden_size)
        self.norm = nn.LayerNorm(hidden_size)
        self.head = nn.Linear(hidden_size, n_outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        w = torch.softmax(self.var_select(x), dim=-1)  # (B,T,F) 变量选择权重
        h = self.input_proj(x * w)  # (B,T,H)
        lstm_out, _ = self.lstm(h)
        attn_out, _ = self.attn(lstm_out, lstm_out, lstm_out)
        z = self.norm(lstm_out + self.glu(attn_out))  # 门控残差
        return self.head(z[:, -1, :])


class _NBeatsBlock(nn.Module):
    def __init__(self, in_dim: int, out_dim: int, hidden: int) -> None:
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(in_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
        )
        self.backcast = nn.Linear(hidden, in_dim)
        self.forecast = nn.Linear(hidden, out_dim)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.mlp(x)
        return self.backcast(h), self.forecast(h)


class NBeatsNet(nn.Module):
    """N-BEATS（纯前馈残差堆叠）。摊平回看窗，逐块 backcast 残差 + forecast 累加。"""

    def __init__(
        self, n_features: int, n_outputs: int, *, lookback: int = 20, hidden_size: int = 64,
        num_blocks: int = 3, **_: Any,
    ) -> None:
        super().__init__()
        in_dim = n_features * lookback
        self.blocks = nn.ModuleList([_NBeatsBlock(in_dim, n_outputs, hidden_size) for _ in range(num_blocks)])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        resid = x.flatten(1)  # (B, T*F)
        forecast = torch.zeros(x.size(0), self.blocks[0].forecast.out_features, device=x.device)
        for blk in self.blocks:
            bc, fc = blk(resid)
            resid = resid - bc
            forecast = forecast + fc
        return forecast


class _NHitsBlock(nn.Module):
    def __init__(self, n_features: int, lookback: int, out_dim: int, hidden: int, pool_kernel: int) -> None:
        super().__init__()
        self.pool = nn.AvgPool1d(pool_kernel, ceil_mode=True)
        pooled_len = -(-lookback // pool_kernel)  # ceil
        in_dim = n_features * pooled_len
        full_dim = n_features * lookback
        self.mlp = nn.Sequential(nn.Linear(in_dim, hidden), nn.ReLU(), nn.Linear(hidden, hidden), nn.ReLU())
        self.backcast = nn.Linear(hidden, full_dim)
        self.forecast = nn.Linear(hidden, out_dim)

    def forward(self, resid_full: torch.Tensor, seq_shape: tuple[int, int, int]) -> tuple[torch.Tensor, torch.Tensor]:
        b, t, f = seq_shape
        seq = resid_full.view(b, t, f).transpose(1, 2)  # (B,F,T)
        pooled = self.pool(seq).flatten(1)  # (B, F*T')
        h = self.mlp(pooled)
        return self.backcast(h), self.forecast(h)


class NHitsNet(nn.Module):
    """N-HiTS（多尺度分层）。各块按不同 pool kernel 下采样输入，捕捉多频率成分。"""

    def __init__(
        self, n_features: int, n_outputs: int, *, lookback: int = 20, hidden_size: int = 64, **_: Any,
    ) -> None:
        super().__init__()
        kernels = [k for k in (1, 2, 4) if k <= lookback] or [1]
        self.lookback, self.n_features = lookback, n_features
        self.blocks = nn.ModuleList([_NHitsBlock(n_features, lookback, n_outputs, hidden_size, k) for k in kernels])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, t, f = x.shape
        resid = x.flatten(1)
        forecast = torch.zeros(b, self.blocks[0].forecast.out_features, device=x.device)
        for blk in self.blocks:
            bc, fc = blk(resid, (b, t, f))
            resid = resid - bc
            forecast = forecast + fc
        return forecast


class DeepARNet(nn.Module):
    """DeepAR（自回归 RNN 概率预测）。LSTM 输出 μ/σ；点预测用 μ，σ 头保留(供未来区间预测)。"""

    def __init__(
        self, n_features: int, n_outputs: int, *, hidden_size: int = 32, num_layers: int = 1, dropout: float = 0.1, **_: Any,
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(n_features, hidden_size, num_layers, batch_first=True, dropout=dropout if num_layers > 1 else 0.0)
        self.mu = nn.Linear(hidden_size, n_outputs)
        self.sigma = nn.Linear(hidden_size, n_outputs)  # softplus 后为正；点预测 harness 用 μ

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        last = out[:, -1, :]
        return self.mu(last)


_ARCH = {
    "lstm": LSTMNet,
    "gru": GRUNet,
    "alstm": ALSTMNet,
    "mlp": MLPNet,
    "tcn": TCNNet,
    "transformer": TransformerNet,
    "tft": TFTNet,
    "nbeats": NBeatsNet,
    "nhits": NHitsNet,
    "deepar": DeepARNet,
}


def build_network(arch: str, n_features: int, n_outputs: int, **hp: Any) -> nn.Module:
    if arch not in _ARCH:
        raise ValueError(f"未注册的 DL 架构: {arch}（可用: {sorted(_ARCH)}）")
    return _ARCH[arch](n_features, n_outputs, **hp)


def available_architectures() -> list[str]:
    return sorted(_ARCH)


__all__ = ["available_architectures", "build_network"]
