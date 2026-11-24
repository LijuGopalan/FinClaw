"""
Automated Trade Journal & Performance Review
===========================================
Reviews all signals generated, tracks accuracy, and learns from mistakes.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from skills.financial_skills import get_stock_quote, get_price_history
    from skills.db import get_scan_history, record_signal_observation
except ImportError:
    def get_stock_quote(ticker):
        return {}
    def get_price_history(ticker, **kwargs):
        return None
    def get_scan_history(**kwargs):
        return []
    def record_signal_observation(*args, **kwargs):
        return None

from skills.llm import ask

logger = logging.getLogger("finclaw.journal")


def get_todays_scans():
    """Get all opportunity scans from today"""
    try:
        scans = get_scan_history(days=1, limit=100)
        return scans
    except Exception as e:
        logger.error(f"Failed to load scan history: {e}")
        return []


def analyze_signal_performance(scan_data: dict):
    """
    Analyze how well a signal performed
    """
    opportunities = scan_data.get('opportunities', [])
    scan_time = scan_data.get('generated_at', datetime.now().isoformat())
    
    results = []
    
    for opp in opportunities:
        ticker = opp.get('ticker')
        entry_low = opp.get('entry_low', 0)
        entry_high = opp.get('entry_high', 0)
        target = opp.get('target_price', 0)
        stop = opp.get('stop_loss', 0)
        action = opp.get('action', '')
        score = opp.get('score', 0)
        
        # Get current price
        try:
            quote = get_stock_quote(ticker)
            current_price = quote.get('price', 0)
            
            if not current_price:
                continue
            
            # Calculate entry midpoint
            entry_mid = (entry_low + entry_high) / 2 if entry_low and entry_high else entry_high or entry_low
            
            if not entry_mid:
                continue
            
            # Calculate performance
            price_change_pct = ((current_price - entry_mid) / entry_mid) * 100
            
            # A quote is only a mark-to-market observation; without a recorded fill,
            # it must not be reported as a realized win or loss.
            outcome = "open"
            if 'buy' in action.lower():
                if target and current_price >= target:
                    outcome = "price_above_target"
                elif stop and current_price <= stop:
                    outcome = "price_below_stop"
            
            results.append({
                "signal_id": opp.get("signal_id"),
                "ticker": ticker,
                "action": action,
                "score": score,
                "entry": entry_mid,
                "current": current_price,
                "change_pct": round(price_change_pct, 2),
                "target": target,
                "stop": stop,
                "outcome": outcome,
                "scan_time": scan_time,
                "outcome_method": "mark_to_market_no_fill_data",
                "ml_probability": opp.get("ml_probability"),
                "risk_gate": opp.get("risk_gate"),
                "regime": (scan_data.get("regime_settings") or {}).get("regime"),
            })
            
        except Exception as e:
            logger.warning(f"Failed to analyze {ticker}: {e}")
    
    return results


def generate_daily_journal():
    """
    Daily trade journal (4:30 PM after close)
    """
    logger.info("Generating daily trade journal...")
    
    scans = get_todays_scans()
    
    if not scans:
        return "No scans performed today."
    
    # Analyze all signals from today
    all_results = []
    
    for scan in scans:
        scan_data = scan.get('data', {})
        if isinstance(scan_data, str):
            try:
                scan_data = json.loads(scan_data)
            except:
                continue
        
        results = analyze_signal_performance(scan_data)
        all_results.extend(results)
        for result in results:
            if result.get("signal_id") and result.get("current"):
                try:
                    record_signal_observation(
                        result["signal_id"],
                        result["current"],
                        outcome=result["outcome"],
                        outcome_return_pct=result["change_pct"],
                        outcome_method=result["outcome_method"],
                    )
                except Exception as e:
                    logger.warning("Failed to record signal observation: %s", e)
    
    if not all_results:
        return "No actionable signals to review today."
    
    # Calculate statistics
    outcomes = defaultdict(int)
    for r in all_results:
        outcomes[r['outcome']] += 1
    
    winning = outcomes.get('winning', 0)
    losing = outcomes.get('losing', 0)
    total = winning + losing
    
    win_rate = (winning / total * 100) if total > 0 else None
    win_rate_text = f"{win_rate:.1f}%" if win_rate is not None else "N/A"
    
    # Build context for Qwen
    context = f"""# Daily Trade Journal
{datetime.now().strftime("%Y-%m-%d")}

## Performance Summary
- Signals observed: {len(all_results)}
- Closed trades with recorded fills: {total}
- Realized wins: {winning}
- Realized losses: {losing}
- Open / unfilled observations: {outcomes.get('open', 0) + outcomes.get('price_above_target', 0) + outcomes.get('price_below_stop', 0)}
- Realized win rate: {win_rate_text} (not inferred from price movement alone)

## Individual Signal Performance
"""
    
    # Sort by absolute change
    sorted_results = sorted(all_results, key=lambda x: abs(x['change_pct']), reverse=True)
    
    for r in sorted_results[:15]:  # Top 15 signals
        emoji = "🟢" if r['change_pct'] > 0 else "🔴"
        context += f"\n{emoji} **${r['ticker']}** (Score: {r['score']})\n"
        context += f"   Action: {r['action']}\n"
        context += f"   Entry: ${r['entry']:.2f} → Current: ${r['current']:.2f}\n"
        context += f"   Change: {r['change_pct']:+.2f}%\n"
        context += f"   Outcome: {r['outcome'].replace('_', ' ').title()}\n"
        context += f"   Method: {r['outcome_method']}\n"
        if r.get("ml_probability") is not None:
            context += f"   Calibrated 1-hour probability: {r['ml_probability']:.1%}\n"
        context += f"   Regime: {r.get('regime') or 'Unknown'}\n"
    
    # Ask Qwen to analyze
    prompt = f"""{context}

YOUR TASK:
Review today's trading signals and provide:

Separate **Observed Evidence**, **Inference**, and **Recommendations**. Do not treat
unfilled signal observations as realized trades or claim statistical relationships
from this single-day sample.

1. **What Worked**
   - Which signals had the best performance?
   - What patterns/setups succeeded?
   - Only report scoring-factor correlations when there are enough resolved trades with recorded fills; otherwise state that evidence is insufficient.

2. **What Failed**
   - Which signals underperformed?
   - Common characteristics of losing trades?
   - Were stops too tight? Targets too aggressive?

3. **Key Lessons**
   - What should we do differently tomorrow?
   - Any false positives to watch out for?
   - Scoring model adjustments needed?

4. **Tomorrow's Strategy**
   - Based on today, what should we focus on?
   - Risk management adjustments?
   - Setup types to prioritize or avoid?

Keep it under 400 words. Be honest about failures and specific about improvements."""

    try:
        analysis = ask(prompt, max_tokens=2048, task="journal")
        
        # Save journal entry
        journal_dir = os.path.join(os.path.dirname(__file__), "..", "data", "trade_journal")
        os.makedirs(journal_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d")
        journal_file = os.path.join(journal_dir, f"journal_{timestamp}.json")
        
        journal_data = {
            "date": timestamp,
            "timestamp": datetime.now().isoformat(),
            "total_signals": len(all_results),
            "winning": winning,
            "losing": losing,
            "win_rate": win_rate,
            "results": all_results,
            "analysis": analysis
        }
        
        with open(journal_file, 'w') as f:
            json.dump(journal_data, f, indent=2)
        
        logger.info(f"Journal entry saved to {journal_file}")
        
        return analysis
        
    except Exception as e:
        logger.error(f"Failed to generate journal analysis: {e}")
        return context


def generate_weekly_performance_review():
    """
    Weekly performance review (Sunday 4:00 PM)
    """
    logger.info("Generating weekly performance review...")
    
    # Get all scans from past 7 days
    try:
        scans = get_scan_history(days=7, limit=1000)
    except:
        return "Failed to load scan history."
    
    # Analyze all signals from the week
    all_results = []
    
    for scan in scans:
        scan_data = scan.get('data', {})
        if isinstance(scan_data, str):
            try:
                scan_data = json.loads(scan_data)
            except:
                continue
        
        results = analyze_signal_performance(scan_data)
        all_results.extend(results)
    
    if not all_results:
        return "No signals to review this week."
    
    # Calculate weekly statistics
    outcomes = defaultdict(int)
    by_action = defaultdict(list)
    by_score_range = defaultdict(list)
    
    for r in all_results:
        outcomes[r['outcome']] += 1
        by_action[r['action']].append(r)
        
        # Group by score ranges
        score = r['score']
        if score >= 80:
            by_score_range['80-100'].append(r)
        elif score >= 60:
            by_score_range['60-79'].append(r)
        elif score >= 40:
            by_score_range['40-59'].append(r)
        else:
            by_score_range['0-39'].append(r)
    
    # Calculate win rates by category
    def calc_win_rate(signals):
        winning = sum(1 for s in signals if s['outcome'] in ['winning', 'target_hit'])
        losing = sum(1 for s in signals if s['outcome'] in ['losing', 'stopped_out'])
        total = winning + losing
        return (winning / total * 100) if total > 0 else 0
    
    context = f"""# Weekly Performance Review
Week of {datetime.now().strftime("%B %d, %Y")}

## Overall Statistics
- Total Signals: {len(all_results)}
- Wins: {outcomes.get('winning', 0) + outcomes.get('target_hit', 0)}
- Losses: {outcomes.get('losing', 0) + outcomes.get('stopped_out', 0)}
- Pending: {outcomes.get('pending', 0)}
- Win Rate: {calc_win_rate(all_results):.1f}%

## Win Rate by Score Range
"""
    
    for score_range, signals in sorted(by_score_range.items()):
        wr = calc_win_rate(signals)
        context += f"- {score_range}: {wr:.1f}% ({len(signals)} signals)\n"
    
    context += "\n## Win Rate by Action Type\n"
    
    for action, signals in by_action.items():
        wr = calc_win_rate(signals)
        context += f"- {action}: {wr:.1f}% ({len(signals)} signals)\n"
    
    context += "\n## Best Performers\n"
    
    sorted_results = sorted(all_results, key=lambda x: x['change_pct'], reverse=True)
    for r in sorted_results[:5]:
        context += f"- ${r['ticker']}: {r['change_pct']:+.2f}% (Score: {r['score']})\n"
    
    context += "\n## Worst Performers\n"
    
    for r in sorted_results[-5:]:
        context += f"- ${r['ticker']}: {r['change_pct']:+.2f}% (Score: {r['score']})\n"
    
    # Ask Qwen for deep analysis
    prompt = f"""{context}

YOUR TASK:
Comprehensive weekly performance analysis:

1. **Scoring Model Accuracy**
   - Are high scores (80+) really better performers?
   - Should we adjust score thresholds?
   - Which features should be weighted more/less?

2. **Strategy Effectiveness**
   - Which scan types (scalp/swing/long) performed best?
   - Optimal holding periods?
   - Entry/exit timing patterns?

3. **Pattern Recognition**
   - Common traits of winning trades?
   - Common traits of losing trades?
   - Any setup types to avoid entirely?

4. **Model Improvements**
   - Specific scoring adjustments to make?
   - New factors to incorporate?
   - False positive patterns to filter out?

5. **Next Week's Plan**
   - What should we change?
   - Risk management updates?
   - Position sizing adjustments?

Keep it under 600 words. Be data-driven and actionable."""

    try:
        analysis = ask(prompt, max_tokens=3072, task="journal")
        
        # Save weekly review
        reviews_dir = os.path.join(os.path.dirname(__file__), "..", "data", "weekly_reviews")
        os.makedirs(reviews_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d")
        review_file = os.path.join(reviews_dir, f"weekly_review_{timestamp}.json")
        
        review_data = {
            "week_ending": timestamp,
            "timestamp": datetime.now().isoformat(),
            "total_signals": len(all_results),
            "overall_win_rate": calc_win_rate(all_results),
            "by_score_range": {k: calc_win_rate(v) for k, v in by_score_range.items()},
            "by_action": {k: calc_win_rate(v) for k, v in by_action.items()},
            "analysis": analysis
        }
        
        with open(review_file, 'w') as f:
            json.dump(review_data, f, indent=2)
        
        logger.info(f"Weekly review saved to {review_file}")
        
        return analysis
        
    except Exception as e:
        logger.error(f"Failed to generate weekly review: {e}")
        return context


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("="*60)
    print("DAILY TRADE JOURNAL TEST")
    print("="*60)
    print(generate_daily_journal())
    
    print("\n" + "="*60)
    print("WEEKLY PERFORMANCE REVIEW TEST")
    print("="*60)
    print(generate_weekly_performance_review())
