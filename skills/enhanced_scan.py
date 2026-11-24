"""
FinClaw Enhanced Scan Engine
============================
Integrates opportunity scanning with automatic deep analysis and red team validation.
Only sends alerts for confirmed buy signals that pass both analysis and red team review.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

logger = logging.getLogger("finclaw.enhanced_scan")

try:
    from skills.opportunity_engine import get_opportunities
    from skills.deep_analysis import generate_institutional_report, red_team_validate
    from skills.notifications import send_telegram
except ImportError:
    from opportunity_engine import get_opportunities
    from deep_analysis import generate_institutional_report, red_team_validate
    from notifications import send_telegram


def analyze_opportunity(opp: dict) -> dict:
    """
    Run both /analyze and /redteam on a single opportunity.
    Returns enriched opportunity with analysis results.
    """
    ticker = opp.get("ticker")
    logger.info(f"[{ticker}] Running deep analysis and red team validation...")
    
    try:
        # Run analysis and red team in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_analysis = executor.submit(generate_institutional_report, ticker)
            future_redteam = executor.submit(red_team_validate, ticker, opp)
            
            analysis = future_analysis.result(timeout=120)
            redteam = future_redteam.result(timeout=120)
        
        # Enrich opportunity with analysis results
        opp["analysis"] = analysis.get("memo", "")
        opp["analysis_full"] = analysis
        opp["redteam"] = redteam
        opp["redteam_verdict"] = redteam.get("verdict", "CAUTION")
        opp["redteam_risk_score"] = redteam.get("risk_score", 5)
        
        logger.info(f"[{ticker}] Analysis complete: RedTeam={redteam.get('verdict')}, Risk={redteam.get('risk_score')}/10")
        
        return opp
        
    except Exception as e:
        logger.error(f"[{ticker}] Analysis failed: {e}")
        opp["analysis_error"] = str(e)
        opp["redteam_verdict"] = "ERROR"
        return opp


def is_confirmed_buy(opp: dict) -> bool:
    """
    Determine if an opportunity is a confirmed buy signal.
    
    Criteria:
    1. Action is BUY or BUY WATCH
    2. Red Team verdict is PASS or CAUTION (not REJECT)
    3. Red Team risk score <= 7
    4. Score >= 60
    """
    action = opp.get("action", "").upper()
    redteam_verdict = opp.get("redteam_verdict", "REJECT").upper()
    redteam_risk = opp.get("redteam_risk_score", 10)
    score = opp.get("score", 0)
    risk_gate = opp.get("risk_gate")

    if not isinstance(risk_gate, dict) or risk_gate.get("passed") is not True:
        logger.debug(f"[{opp.get('ticker')}] Filtered: Deterministic risk gate failed or missing")
        return False
    
    # Must be a buy action
    if "BUY" not in action:
        logger.debug(f"[{opp.get('ticker')}] Filtered: Not a buy action ({action})")
        return False
    
    # Must not be rejected by red team
    if redteam_verdict == "REJECT":
        logger.debug(f"[{opp.get('ticker')}] Filtered: Red team rejected")
        return False
    
    # Risk score must be acceptable
    if redteam_risk > 7:
        logger.debug(f"[{opp.get('ticker')}] Filtered: Risk too high ({redteam_risk}/10)")
        return False
    
    # Score threshold
    if score < 60:
        logger.debug(f"[{opp.get('ticker')}] Filtered: Score too low ({score})")
        return False
    
    logger.info(f"[{opp.get('ticker')}] ✅ CONFIRMED BUY: Score={score}, RedTeam={redteam_verdict}, Risk={redteam_risk}/10")
    return True


def build_enhanced_alert(opp: dict) -> str:
    """
    Build a rich alert message with analysis and red team insights.
    """
    ticker = opp.get("ticker", "")
    price = opp.get("price", 0)
    score = opp.get("score", 0)
    action = opp.get("action", "BUY")
    
    entry_low = opp.get("entry_low", 0)
    entry_high = opp.get("entry_high", 0)
    target = opp.get("target_price", 0)
    stop = opp.get("stop_loss", 0)
    rr = opp.get("risk_reward")
    
    thesis = opp.get("thesis", "")
    
    # Red Team results
    redteam_verdict = opp.get("redteam_verdict", "N/A")
    redteam_risk = opp.get("redteam_risk_score", "N/A")
    redteam = opp.get("redteam", {})
    failure_modes = redteam.get("failure_modes", [])
    invalidation = redteam.get("key_invalidation", "Monitor stop loss")
    
    # Visual emoji for verdict
    verdict_emoji = {
        "PASS": "🟢",
        "CAUTION": "🟡",
        "REJECT": "🔴",
        "ERROR": "⚠️"
    }.get(redteam_verdict, "⚪")
    
    score_emoji = "🔥" if score >= 80 else ("⚡" if score >= 60 else "📊")
    
    lines = [
        f"🎯 <b>FinClaw Confirmed Buy Alert</b>",
        f"",
        f"📈 <b>${ticker}</b> • Score: <b>{score}</b> {score_emoji}",
        f"💵 Current Price: <b>${price}</b>",
        f"",
        f"<b>📊 TRADE SETUP:</b>",
        f"• Entry Zone: <b>${entry_low} - ${entry_high}</b>",
        f"• Target: <b>${target}</b>",
        f"• Stop Loss: <b>${stop}</b>",
    ]
    
    if rr:
        lines.append(f"• Risk/Reward: <b>{rr}:1</b>")
    
    lines.extend([
        f"",
        f"<b>🤖 AI THESIS:</b>",
        f"<i>{thesis[:200]}</i>",
        f"",
        f"<b>🛡️ RED TEAM VALIDATION:</b>",
        f"{verdict_emoji} Verdict: <b>{redteam_verdict}</b> (Risk Score: {redteam_risk}/10)",
    ])
    
    if failure_modes:
        lines.append(f"<b>⚠️ Key Risks:</b>")
        for i, mode in enumerate(failure_modes[:2], 1):
            lines.append(f"  {i}. {mode}")
    
    if invalidation:
        lines.append(f"<b>🚫 Invalidation:</b> {invalidation}")
    
    # Analysis excerpt (if available)
    analysis = opp.get("analysis", "")
    if analysis and len(analysis) > 100:
        # Extract executive verdict if present
        import re
        exec_match = re.search(r"EXECUTIVE VERDICT.*?(?=\n\n|\n[🏛📊🏢🛡🎯]|$)", analysis, re.DOTALL | re.IGNORECASE)
        if exec_match:
            excerpt = exec_match.group(0).strip()[:300]
            lines.append(f"")
            lines.append(f"<b>🏛️ ANALYST VERDICT:</b>")
            lines.append(f"<i>{excerpt}...</i>")
    
    lines.extend([
        f"",
        f"──────────────────────",
        f"<i>⚠️ Not financial advice. This alert passed both algorithmic scoring AND adversarial red team review. Verify all data before entering.</i>",
        f"<i>📊 Real-time data: Charles Schwab • AI: Qwen 2.5 (local)</i>"
    ])
    
    return "\n".join(lines)


def enhanced_scan(
    session="auto",
    horizon="auto",
    max_workers=3,
    notify=True,
    alert_threshold=65
):
    """
    Run enhanced opportunity scan with integrated deep analysis.
    
    Parameters:
        session: Market session (auto, premarket, regular, postmarket)
        horizon: Time horizon (auto, scalp, day, swing, long)
        max_workers: Max parallel analysis threads
        notify: Send Telegram alerts
        alert_threshold: Minimum score to trigger analysis
    
    Returns:
        dict with scan results and confirmed buy opportunities
    """
    logger.info(f"🚀 Enhanced scan started: session={session}, horizon={horizon}")
    
    # Step 1: Run standard opportunity scan
    scan_result = get_opportunities(
        session=session,
        horizon=horizon,
        limit=15,
        universe_limit=75,
        min_score=0,
        include_options=True,
    )
    
    opportunities = scan_result.get("opportunities", [])
    logger.info(f"📊 Found {len(opportunities)} opportunities from initial scan")
    
    # Step 2: Filter high-score opportunities for deep analysis
    candidates = [
        opp for opp in opportunities
        if opp.get("score", 0) >= alert_threshold and "BUY" in opp.get("action", "").upper()
    ]
    
    logger.info(f"🔍 {len(candidates)} candidates qualify for deep analysis (score >= {alert_threshold}, buy action)")
    
    if not candidates:
        logger.info("No candidates qualify for deep analysis. Scan complete.")
        return {
            "status": "completed",
            "scan_result": scan_result,
            "analyzed_count": 0,
            "confirmed_buys": [],
            "timestamp": datetime.utcnow().isoformat()
        }
    
    # Step 3: Analyze candidates in parallel
    analyzed_opps = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_opp = {
            executor.submit(analyze_opportunity, opp): opp
            for opp in candidates[:10]  # Limit to top 10 to avoid overwhelming
        }
        
        for future in as_completed(future_to_opp):
            try:
                result = future.result(timeout=180)
                analyzed_opps.append(result)
            except Exception as e:
                opp = future_to_opp[future]
                logger.error(f"[{opp.get('ticker')}] Analysis exception: {e}")
    
    logger.info(f"✅ Completed analysis on {len(analyzed_opps)} opportunities")
    
    # Step 4: Filter for confirmed buys
    confirmed_buys = [opp for opp in analyzed_opps if is_confirmed_buy(opp)]
    
    logger.info(f"🎯 {len(confirmed_buys)} confirmed buy signals after red team validation")
    
    # Step 5: Send alerts for confirmed buys
    alerts_sent = 0
    if notify and confirmed_buys:
        for opp in confirmed_buys:
            try:
                alert_msg = build_enhanced_alert(opp)
                send_telegram(alert_msg, parse_mode="HTML")
                alerts_sent += 1
                logger.info(f"📱 Alert sent for {opp.get('ticker')}")
            except Exception as e:
                logger.error(f"Failed to send alert for {opp.get('ticker')}: {e}")
    
    result = {
        "status": "completed",
        "scan_result": scan_result,
        "total_opportunities": len(opportunities),
        "candidates_analyzed": len(analyzed_opps),
        "confirmed_buys": len(confirmed_buys),
        "alerts_sent": alerts_sent,
        "buy_signals": confirmed_buys,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    logger.info(f"🏁 Enhanced scan complete: {len(confirmed_buys)} confirmed buys, {alerts_sent} alerts sent")
    
    return result


def enhanced_scan_brief(result: dict) -> str:
    """Generate a text summary of the enhanced scan results."""
    total = result.get("total_opportunities", 0)
    analyzed = result.get("candidates_analyzed", 0)
    confirmed = result.get("confirmed_buys", 0)
    
    lines = [
        f"🔍 <b>Enhanced Scan Complete</b>",
        f"",
        f"📊 Initial Opportunities: {total}",
        f"🧠 Deep Analysis Performed: {analyzed}",
        f"✅ Confirmed Buy Signals: {confirmed}",
    ]
    
    if confirmed == 0:
        lines.append("")
        lines.append("<i>No opportunities passed red team validation at this time.</i>")
    
    return "\n".join(lines)
