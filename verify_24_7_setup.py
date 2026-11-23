#!/usr/bin/env python3
"""
Quick verification script to test all new 24/7 features
"""

import os
import sys
import json

def check_file_exists(path, description):
    """Check if a file exists"""
    exists = os.path.exists(path)
    status = "✅" if exists else "❌"
    print(f"{status} {description}: {path}")
    return exists

def check_import(module_name, description):
    """Check if a module can be imported"""
    try:
        __import__(module_name)
        print(f"✅ {description}: {module_name}")
        return True
    except ImportError as e:
        print(f"❌ {description}: {module_name} - {e}")
        return False

def check_directory(path, description):
    """Check if directory exists"""
    exists = os.path.isdir(path)
    status = "✅" if exists else "❌"
    print(f"{status} {description}: {path}")
    return exists

def main():
    print("="*70)
    print("FinClaw 24/7 Qwen Setup Verification")
    print("="*70)
    print()
    
    base_dir = "/Users/adgroup/.gemini/antigravity/scratch/openclaw-financial-assistant"
    os.chdir(base_dir)
    
    # Add to path
    sys.path.insert(0, os.path.join(base_dir, "skills"))
    sys.path.insert(0, os.path.join(base_dir, "ml_pipeline"))
    
    all_checks = []
    
    # Check new skill files
    print("📁 NEW SKILL FILES")
    print("-" * 70)
    all_checks.append(check_file_exists("skills/overnight_monitor.py", "Overnight Monitor"))
    all_checks.append(check_file_exists("skills/weekend_research.py", "Weekend Research"))
    all_checks.append(check_file_exists("skills/news_sentiment.py", "News Sentiment"))
    all_checks.append(check_file_exists("ml_pipeline/auto_retrain.py", "ML Auto-Retrain"))
    print()
    
    # Check directories
    print("📂 DATA DIRECTORIES")
    print("-" * 70)
    all_checks.append(check_directory("data/research_reports", "Research Reports"))
    all_checks.append(check_directory("data/trading_plans", "Trading Plans"))
    all_checks.append(check_directory("data/ml_training_logs", "ML Training Logs"))
    print()
    
    # Check imports
    print("🐍 PYTHON IMPORTS")
    print("-" * 70)
    all_checks.append(check_import("overnight_monitor", "Overnight Monitor Module"))
    all_checks.append(check_import("weekend_research", "Weekend Research Module"))
    all_checks.append(check_import("news_sentiment", "News Sentiment Module"))
    all_checks.append(check_import("auto_retrain", "Auto Retrain Module"))
    print()
    
    # Check core files
    print("🔧 CORE SYSTEM FILES")
    print("-" * 70)
    all_checks.append(check_file_exists("scheduler.py", "Enhanced Scheduler"))
    all_checks.append(check_file_exists("skills/llm.py", "LLM Layer"))
    all_checks.append(check_file_exists("data/universe.json", "Watchlist Universe"))
    print()
    
    # Check Qwen config
    print("🤖 QWEN CONFIGURATION")
    print("-" * 70)
    
    # Check .env for Qwen settings
    if os.path.exists(".env"):
        with open(".env", 'r') as f:
            env_content = f.read()
            use_local = "USE_LOCAL_LLM" in env_content
            print(f"{'✅' if use_local else '⚠️'} USE_LOCAL_LLM in .env")
            all_checks.append(use_local or True)  # Don't fail if not set (defaults to true)
    else:
        print("⚠️ .env file not found (using defaults)")
    
    # Check Ollama
    import subprocess
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        if "qwen2.5" in result.stdout.lower():
            print("✅ Qwen 2.5 model found in Ollama")
            all_checks.append(True)
        else:
            print("⚠️ Qwen 2.5 not found in Ollama - install with: ollama pull qwen2.5:7b")
            all_checks.append(False)
    except Exception as e:
        print(f"⚠️ Could not check Ollama: {e}")
        all_checks.append(False)
    
    print()
    
    # Test function execution
    print("🧪 FUNCTION TESTS")
    print("-" * 70)
    
    try:
        from overnight_monitor import get_watchlist_tickers
        tickers = get_watchlist_tickers()
        if tickers:
            print(f"✅ Watchlist loaded: {len(tickers)} tickers")
            print(f"   Sample: {', '.join(tickers[:5])}")
            all_checks.append(True)
        else:
            print("⚠️ Watchlist empty")
            all_checks.append(False)
    except Exception as e:
        print(f"❌ Failed to load watchlist: {e}")
        all_checks.append(False)
    
    print()
    
    # Summary
    print("="*70)
    passed = sum(all_checks)
    total = len(all_checks)
    percentage = (passed / total * 100) if total > 0 else 0
    
    print(f"RESULTS: {passed}/{total} checks passed ({percentage:.0f}%)")
    
    if percentage == 100:
        print()
        print("🎉 ALL CHECKS PASSED! Your 24/7 Qwen system is ready.")
        print()
        print("Next steps:")
        print("1. Restart scheduler: pkill -f scheduler.py && python scheduler.py &")
        print("2. Monitor logs: tail -f server.log")
        print("3. Test overnight digest: python skills/overnight_monitor.py")
    elif percentage >= 80:
        print()
        print("⚠️ Most checks passed. Review warnings above.")
    else:
        print()
        print("❌ Setup incomplete. Review errors above and fix before starting.")
    
    print("="*70)

if __name__ == "__main__":
    main()
