import os
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, classification_report
import joblib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "ml_dataset.csv")
MODEL_DIR = os.path.join(BASE_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "finclaw_xgb.json")

def train():
    print("🚀 Loading dataset...")
    df = pd.read_csv(DATA_PATH)
    
    # Features and Target
    features = ['rsi', 'macd_hist', 'atr_pct', 'rvol', 'vwap_dist']
    X = df[features]
    y = df['target']
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
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
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred)
    
    print("\n=== Model Performance ===")
    print(f"Accuracy:  {acc:.2%}")
    print(f"Precision: {prec:.2%} (When model says BUY, it's right {prec:.2%} of the time)")
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred))
    
    print("\n=== Feature Importance ===")
    importance = pd.DataFrame({'feature': features, 'importance': model.feature_importances_})
    importance = importance.sort_values('importance', ascending=False)
    print(importance.to_string(index=False))
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    model.save_model(MODEL_PATH)
    print(f"\n💾 Model saved to {MODEL_PATH}")

if __name__ == "__main__":
    train()
