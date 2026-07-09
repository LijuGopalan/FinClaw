"""
ml_pipeline/train_model_mlx.py
===============================
Train a binary MLP classifier using Apple's MLX framework,
targeting the Mac Mini's GPU and Neural Engine instead of the CPU.

This is a DROP-IN COMPANION to ml_pipeline/train_model.py (XGBoost).
It trains on the SAME dataset and features, so you can compare results directly.

Hardware utilization note
--------------------------
MLX uses Apple's Metal GPU backend and the ANE (Apple Neural Engine) via a
lazy evaluation model:
  - Array operations (mx.matmul, mx.softmax, etc.) → GPU / ANE
  - mx.eval() materialises the lazy graph, flushing work to Metal
  - Gradient computation via nn.value_and_grad → GPU
  - The Mac Mini M4's 10-core GPU + 38-TOPS ANE handle these efficiently

XGBoost, by contrast, uses n_jobs=-1 to spread work across CPU cores only.
MLX shines especially at batched inference over large watchlists.

Usage
------
  python ml_pipeline/build_dataset.py   # generate data/ml_dataset.csv first
  python ml_pipeline/train_model_mlx.py

Output
------
  models/finclaw_mlx.npz           <- trained weights (load with mx.load)
  models/finclaw_mlx_config.json   <- architecture metadata for inference
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, classification_report

# ── MLX guard: Apple Silicon only ────────────────────────────────────────────
try:
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
except ImportError:
    sys.exit(
        "\n❌  MLX not installed. Install it with:\n"
        "       pip install mlx\n"
        "   Note: MLX is Apple Silicon (M-series) only.\n"
    )

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH    = os.path.join(BASE_DIR, "data",   "ml_dataset.csv")
MODEL_DIR    = os.path.join(BASE_DIR, "models")
WEIGHTS_PATH = os.path.join(MODEL_DIR, "finclaw_mlx.npz")
CONFIG_PATH  = os.path.join(MODEL_DIR, "finclaw_mlx_config.json")

# ── Hyperparameters ───────────────────────────────────────────────────────────
FEATURES     = ["rsi", "macd_hist", "atr_pct", "rvol", "vwap_dist"]
HIDDEN_DIMS  = [32, 16]       # layer widths
DROPOUT_P    = 0.2
BATCH_SIZE   = 256
EPOCHS       = 50
LR           = 1e-3
WEIGHT_DECAY = 1e-4
SEED         = 42


# =============================================================================
# Model Definition
# =============================================================================

class FinClawMLP(nn.Module):
    """
    3-layer MLP for binary classification of intraday breakout probability.

    Architecture:
        Linear(5->32) -> ReLU -> Dropout(0.2)
        Linear(32->16) -> ReLU
        Linear(16->1)  <- logits (sigmoid applied at inference)

    Logits are used during training so we can call binary_cross_entropy
    directly without numeric instability from explicit sigmoid.
    """

    def __init__(self, input_dim: int, hidden_dims: list, dropout_p: float = 0.2):
        super().__init__()
        layers = []
        prev_dim = input_dim
        for i, h in enumerate(hidden_dims):
            layers.append(nn.Linear(prev_dim, h))   # dispatched to GPU via Metal
            layers.append(nn.ReLU())
            if i == 0:
                layers.append(nn.Dropout(p=dropout_p))  # regularisation
            prev_dim = h
        layers.append(nn.Linear(prev_dim, 1))        # output logit
        self.layers = layers

    def __call__(self, x):
        for layer in self.layers:
            x = layer(x)
        return x  # raw logit, shape (B, 1)


# =============================================================================
# Loss Function — weighted BCE for class imbalance
# =============================================================================

def weighted_bce_loss(model, x, y, pos_weight):
    """
    Binary cross-entropy with positive-class weighting.

    Mirrors XGBoost's scale_pos_weight = neg_count / pos_count.
    The weight tensor is broadcast over the batch — this op runs on GPU.
    """
    logits = model(x).squeeze(-1)          # (B,)
    # MLX BCE expects (logits, targets, weights)
    weights = mx.where(y == 1, pos_weight, 1.0)
    loss = nn.losses.binary_cross_entropy(
        logits, y, weights=weights, reduction="mean"
    )
    return loss


# =============================================================================
# Mini-batch generator (CPU side — numpy -> mx.array)
# =============================================================================

def batch_iter(X, y, batch_size, shuffle=True):
    """
    Yield (x_batch, y_batch) as mlx arrays.
    Data prep is CPU-side; the mx.array constructor copies to unified memory,
    making it accessible by both CPU and GPU without an explicit transfer step.
    """
    n = len(X)
    idx = np.random.permutation(n) if shuffle else np.arange(n)
    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)
        batch_idx = idx[start:end]
        yield (
            mx.array(X[batch_idx], dtype=mx.float32),   # -> unified memory
            mx.array(y[batch_idx], dtype=mx.float32),
        )


# =============================================================================
# Gradient-based feature sensitivity (proxy for feature importance)
# =============================================================================

def compute_input_sensitivity(model, X_test):
    """
    Compute mean |d_output/d_input| across the test set as a feature importance
    proxy.  XGBoost gives this natively; for MLX MLPs we use autograd instead.

    Dispatched entirely to GPU — gradients flow through Metal.
    """
    model.eval()  # disable dropout
    x = mx.array(X_test[:512], dtype=mx.float32)  # sample 512 rows

    # grad w.r.t. input (not weights)
    def forward(x_in):
        return model(x_in).squeeze(-1).sum()

    grad_fn = mx.grad(forward)
    grads = grad_fn(x)
    mx.eval(grads)  # materialise

    sensitivity = np.abs(np.array(grads)).mean(axis=0)  # (5,)
    return dict(zip(FEATURES, sensitivity.tolist()))


# =============================================================================
# Training entrypoint
# =============================================================================

def train():
    np.random.seed(SEED)

    # ── 1. Load dataset ───────────────────────────────────────────────────────
    if not os.path.exists(DATA_PATH):
        sys.exit(
            f"\n❌  Dataset not found at {DATA_PATH}\n"
            "   Run:  python ml_pipeline/build_dataset.py\n"
        )

    print("🚀 Loading dataset...")
    df = pd.read_csv(DATA_PATH).dropna(subset=FEATURES + ["target"])

    X = df[FEATURES].values.astype(np.float32)
    y = df["target"].values.astype(np.float32)

    # ── 2. Normalise features (z-score, CPU side) ─────────────────────────────
    # MLX linear layers don't include built-in BatchNorm, so we normalise manually.
    # Stats computed on full dataset then applied to train/test.
    mean = X.mean(axis=0)
    std  = X.std(axis=0) + 1e-8
    X_norm = (X - mean) / std

    # ── 3. Train/test split (same params as train_model.py) ───────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X_norm, y, test_size=0.2, random_state=SEED, stratify=y
    )
    print(f"📊 Train: {len(X_train):,} | Test: {len(X_test):,}")

    # ── 4. Class imbalance weight (mirrors XGBoost scale_pos_weight) ──────────
    n_neg = int((y_train == 0).sum())
    n_pos = int((y_train == 1).sum())
    pos_weight = float(n_neg) / float(n_pos) if n_pos > 0 else 1.0
    print(f"⚖️  Class ratio — neg: {n_neg:,}, pos: {n_pos:,} → pos_weight: {pos_weight:.2f}")

    # ── 5. Build model & optimizer ────────────────────────────────────────────
    model = FinClawMLP(
        input_dim   = len(FEATURES),
        hidden_dims = HIDDEN_DIMS,
        dropout_p   = DROPOUT_P,
    )

    # AdamW — parameter updates run on GPU
    optimizer = optim.AdamW(learning_rate=LR, weight_decay=WEIGHT_DECAY)

    # Bind loss + grad into a single fused GPU call
    loss_and_grad_fn = nn.value_and_grad(model, weighted_bce_loss)

    # ── 6. Training loop ──────────────────────────────────────────────────────
    print(f"\n🧠 Training MLX MLP for {EPOCHS} epochs on Apple Silicon GPU...")
    t0 = time.time()

    for epoch in range(1, EPOCHS + 1):
        model.train()  # enable dropout
        epoch_losses = []

        for x_batch, y_batch in batch_iter(X_train, y_train, BATCH_SIZE):
            loss, grads = loss_and_grad_fn(model, x_batch, y_batch, pos_weight)
            optimizer.update(model, grads)
            # mx.eval() is the MLX "flush" — materialises the lazy computation
            # graph and dispatches pending ops to the GPU/ANE.  Without this,
            # MLX would defer all work until a value is actually read.
            mx.eval(model.parameters(), optimizer.state)
            epoch_losses.append(float(loss))

        if epoch % 10 == 0 or epoch == 1:
            # Quick validation accuracy (threshold at 0.5)
            model.eval()
            x_val = mx.array(X_test, dtype=mx.float32)
            logits_val = model(x_val).squeeze(-1)
            mx.eval(logits_val)
            probs_val = 1 / (1 + np.exp(-np.array(logits_val)))  # sigmoid
            preds_val = (probs_val >= 0.5).astype(int)
            val_acc   = accuracy_score(y_test, preds_val)
            avg_loss  = np.mean(epoch_losses)
            print(f"  Epoch {epoch:3d}/{EPOCHS} — loss: {avg_loss:.4f} | val_acc: {val_acc:.2%}")

    elapsed = time.time() - t0
    print(f"\n⏱️  Training complete in {elapsed:.1f}s")

    # ── 7. Final evaluation ───────────────────────────────────────────────────
    print("\n🧪 Evaluating model on held-out test set...")
    model.eval()
    x_test_mx   = mx.array(X_test, dtype=mx.float32)
    logits_test = model(x_test_mx).squeeze(-1)
    mx.eval(logits_test)

    probs = 1 / (1 + np.exp(-np.array(logits_test)))   # sigmoid CPU-side
    preds = (probs >= 0.5).astype(int)

    acc  = accuracy_score(y_test, preds)
    prec = precision_score(y_test, preds, zero_division=0)

    print("\n=== Model Performance (MLX MLP) ===")
    print(f"Accuracy:  {acc:.2%}")
    print(f"Precision: {prec:.2%} (When model says BUY, it's right {prec:.2%} of the time)")
    print("\nClassification Report:")
    print(classification_report(y_test, preds, zero_division=0))

    # ── 8. Feature sensitivity (gradient-based importance proxy) ──────────────
    print("\n=== Feature Sensitivity (gradient |d_output/d_input|) ===")
    sensitivity = compute_input_sensitivity(model, X_test)
    sens_df = pd.DataFrame(
        list(sensitivity.items()), columns=["feature", "sensitivity"]
    ).sort_values("sensitivity", ascending=False)
    print(sens_df.to_string(index=False))
    print("\n(Higher = the model relies on this feature more for its output)")

    # ── 9. Save weights + config ──────────────────────────────────────────────
    os.makedirs(MODEL_DIR, exist_ok=True)

    # Weights: MLX native format (.npz)
    # At inference: model.load_weights("models/finclaw_mlx.npz")
    model.save_weights(WEIGHTS_PATH)
    print(f"\n💾 Weights saved → {WEIGHTS_PATH}")

    # Config: architecture + normalisation stats (needed to reconstruct model)
    config = {
        "input_dim":  len(FEATURES),
        "hidden_dims": HIDDEN_DIMS,
        "dropout_p":  DROPOUT_P,
        "features":   FEATURES,
        "norm_mean":  mean.tolist(),
        "norm_std":   std.tolist(),
        "pos_weight": pos_weight,
        "accuracy":   round(acc,  4),
        "precision":  round(prec, 4),
    }
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    print(f"💾 Config saved  → {CONFIG_PATH}")

    # ── 10. Inference usage hint ──────────────────────────────────────────────
    print("""
┌─────────────────────────────────────────────────────────────────────────────┐
│  HOW TO USE THIS MODEL FOR INFERENCE (Option B wiring)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  import mlx.core as mx, mlx.nn as nn, json, numpy as np                    │
│  from ml_pipeline.train_model_mlx import FinClawMLP                        │
│                                                                             │
│  cfg   = json.load(open("models/finclaw_mlx_config.json"))                 │
│  model = FinClawMLP(cfg["input_dim"], cfg["hidden_dims"], cfg["dropout_p"])│
│  model.load_weights("models/finclaw_mlx.npz")                              │
│  model.eval()                                                               │
│                                                                             │
│  x_raw = np.array([[rsi, macd_hist, atr_pct, rvol, vwap_dist]], np.float32)│
│  mean, std = np.array(cfg["norm_mean"]), np.array(cfg["norm_std"])         │
│  x     = mx.array((x_raw - mean) / std)                                    │
│  logit = model(x).squeeze(-1)                                               │
│  mx.eval(logit)                                                             │
│  prob  = float(1 / (1 + np.exp(-np.array(logit))))  # sigmoid              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
""")


if __name__ == "__main__":
    train()
