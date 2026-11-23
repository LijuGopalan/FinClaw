"""
Automated ML Model Retraining Pipeline
======================================
Runs weekly to keep the MLX model fresh with latest market data.
"""

import os
import sys
import json
import logging
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("finclaw.ml_retrain")


def run_weekly_retrain():
    """
    Saturday 11:00 PM: Rebuild dataset and retrain MLX model
    """
    logger.info("Starting weekly ML model retraining pipeline...")
    
    base_dir = os.path.dirname(os.path.dirname(__file__))
    ml_dir = os.path.join(base_dir, "ml_pipeline")
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "steps": []
    }
    
    # Step 1: Build fresh dataset
    logger.info("Step 1: Building fresh dataset...")
    try:
        result = subprocess.run(
            ["python", os.path.join(ml_dir, "build_dataset.py")],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        
        results["steps"].append({
            "step": "build_dataset",
            "success": result.returncode == 0,
            "output": result.stdout[-500:] if result.stdout else "",
            "error": result.stderr[-500:] if result.stderr else ""
        })
        
        if result.returncode != 0:
            logger.error(f"Dataset build failed: {result.stderr}")
            return results
            
        logger.info("Dataset build complete")
        
    except Exception as e:
        logger.error(f"Dataset build error: {e}")
        results["steps"].append({
            "step": "build_dataset",
            "success": False,
            "error": str(e)
        })
        return results
    
    # Step 2: Train MLX model
    logger.info("Step 2: Training MLX model...")
    try:
        result = subprocess.run(
            ["python", os.path.join(ml_dir, "train_model_mlx.py")],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=900  # 15 minute timeout
        )
        
        results["steps"].append({
            "step": "train_mlx",
            "success": result.returncode == 0,
            "output": result.stdout[-500:] if result.stdout else "",
            "error": result.stderr[-500:] if result.stderr else ""
        })
        
        if result.returncode != 0:
            logger.error(f"MLX training failed: {result.stderr}")
            return results
            
        logger.info("MLX model training complete")
        
    except Exception as e:
        logger.error(f"MLX training error: {e}")
        results["steps"].append({
            "step": "train_mlx",
            "success": False,
            "error": str(e)
        })
        return results
    
    # Step 3: Validate new model
    logger.info("Step 3: Validating new model...")
    try:
        # Check if model files exist
        models_dir = os.path.join(base_dir, "models")
        mlx_weights = os.path.join(models_dir, "finclaw_mlx.npz")
        mlx_config = os.path.join(models_dir, "finclaw_mlx_config.json")
        
        if os.path.exists(mlx_weights) and os.path.exists(mlx_config):
            # Load config to check metrics
            with open(mlx_config, 'r') as f:
                config = json.load(f)
            
            results["steps"].append({
                "step": "validation",
                "success": True,
                "metrics": {
                    "test_accuracy": config.get("test_accuracy", "N/A"),
                    "test_auc": config.get("test_auc", "N/A")
                }
            })
            
            logger.info(f"Model validation complete - Accuracy: {config.get('test_accuracy')}, AUC: {config.get('test_auc')}")
        else:
            results["steps"].append({
                "step": "validation",
                "success": False,
                "error": "Model files not found"
            })
            
    except Exception as e:
        logger.error(f"Validation error: {e}")
        results["steps"].append({
            "step": "validation",
            "success": False,
            "error": str(e)
        })
    
    # Save results
    results_dir = os.path.join(base_dir, "data", "ml_training_logs")
    os.makedirs(results_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = os.path.join(results_dir, f"retrain_{timestamp}.json")
    
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f"Retraining results saved to {results_file}")
    
    return results


def generate_retrain_report(results: dict) -> str:
    """
    Generate human-readable report of retraining results
    """
    report = f"""🤖 <b>ML Model Weekly Retraining Complete</b>

<b>Timestamp:</b> {results['timestamp']}

<b>Pipeline Results:</b>
"""
    
    for step in results.get('steps', []):
        step_name = step['step'].replace('_', ' ').title()
        status = "✅" if step['success'] else "❌"
        report += f"\n{status} <b>{step_name}</b>"
        
        if step.get('metrics'):
            metrics = step['metrics']
            report += f"\n   Accuracy: {metrics.get('test_accuracy', 'N/A')}"
            report += f"\n   AUC: {metrics.get('test_auc', 'N/A')}"
        
        if not step['success'] and step.get('error'):
            report += f"\n   Error: {step['error'][:100]}"
    
    # Overall status
    all_success = all(step['success'] for step in results.get('steps', []))
    
    if all_success:
        report += "\n\n✅ <b>Model is ready for production use</b>"
    else:
        report += "\n\n⚠️ <b>Retraining encountered issues - review logs</b>"
    
    report += f"\n\n<i>Next retraining: Next Saturday 11:00 PM CST</i>"
    
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("="*60)
    print("STARTING WEEKLY ML MODEL RETRAINING")
    print("="*60)
    
    results = run_weekly_retrain()
    
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    print(json.dumps(results, indent=2))
    
    print("\n" + "="*60)
    print("REPORT")
    print("="*60)
    print(generate_retrain_report(results))
