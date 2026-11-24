import os
import json
import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, precision_score, classification_report

from calibration import apply_platt_scaling, fit_platt_scaling, sha256_file, temporal_split

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "ml_dataset.csv")
MODEL_DIR = os.path.join(BASE_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "finclaw_xgb.json")
CALIBRATION_PATH = os.path.join(MODEL_DIR, "finclaw_xgb_calibration.json")

def train():
    print("🚀 Loading dataset...")
    df = pd.read_csv(DATA_PATH).dropna(subset=["timestamp", "target"])
    
    # Features and Target
    features = ['rsi', 'macd_hist', 'atr_pct', 'rvol', 'vwap_dist']
    df = df.dropna(subset=features)
    train_df, calibration_df, test_df = temporal_split(df)
    if any(part["target"].nunique() != 2 for part in (train_df, calibration_df, test_df)):
        raise ValueError("Train, calibration, and test periods must each contain both target classes")

    X_train, y_train = train_df[features], train_df["target"].astype(int)
    X_calibration, y_calibration = calibration_df[features], calibration_df["target"].astype(int)
    X_test, y_test = test_df[features], test_df["target"].astype(int)
    
    print(f"🧠 Training XGBoost model on {len(X_train)} samples...")
    
    # Scale pos_weight because dataset is imbalanced (~14% positives)
    pos_weight = (len(y_train) - sum(y_train)) / sum(y_train)
    
    model = xgb.XGBClassifier(
        n_estimators=100,
        learning_rate=0.1,
        max_depth=5,
        scale_pos_weight=pos_weight,
        use_label_encoder=False,
        eval_metric='logloss',
        n_jobs=-1  # Use all M4 cores
    )
    
    model.fit(X_train, y_train)
    
    print("🧪 Evaluating model...")
    raw_prob = model.predict_proba(X_test)[:, 1]
    calibration = fit_platt_scaling(
        model.predict_proba(X_calibration)[:, 1],
        y_calibration,
    )
    y_prob = [apply_platt_scaling(p, calibration) for p in raw_prob]
    if any(p is None for p in y_prob):
        raise ValueError("Failed to calibrate one or more test probabilities")
    y_pred = (pd.Series(y_prob).values >= 0.5).astype(int)
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, zero_division=0)
    
    print("\n=== Model Performance ===")
    print(f"Accuracy:  {acc:.2%}")
    print(f"Precision: {prec:.2%} (When model says BUY, it's right {prec:.2%} of the time)")
    print(f"Raw Brier score:        {brier_score_loss(y_test, raw_prob):.4f}")
    print(f"Calibrated Brier score: {brier_score_loss(y_test, y_prob):.4f}")
    print(f"Calibrated log loss:    {log_loss(y_test, y_prob):.4f}")
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred))
    
    print("\n=== Feature Importance ===")
    importance = pd.DataFrame({'feature': features, 'importance': model.feature_importances_})
    importance = importance.sort_values('importance', ascending=False)
    print(importance.to_string(index=False))
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    model.save_model(MODEL_PATH)
    print(f"\n💾 Model saved to {MODEL_PATH}")
    calibration.update({
        "model_kind": "xgboost",
        "model_sha256": sha256_file(MODEL_PATH),
        "feature_names": features,
        "test_brier_raw": float(brier_score_loss(y_test, raw_prob)),
        "test_brier_calibrated": float(brier_score_loss(y_test, y_prob)),
    })
    with open(CALIBRATION_PATH, "w") as f:
        json.dump(calibration, f, indent=2)
    print(f"💾 Calibration saved to {CALIBRATION_PATH}")

if __name__ == "__main__":
    train()
