"""
FinClaw Skill: Delivery Volume Confluence Filter
Rebuilt to integrate seamlessly with the FinClaw architecture.
"""
import pandas as pd
import logging
from skills.notifications import send_telegram
from skills.opportunity_engine import get_ml_model, _safe_float
from skills.financial_skills import get_technical_analysis, get_price_history

logger = logging.getLogger("finclaw.delivery_volume")

DEFAULT_DELIVERY_THRESHOLD = 30.0
VOLUME_SPIKE_THRESHOLD = 1.5

def estimate_delivery_percentage(ticker: str) -> dict:
    """Estimate delivery percentage based on volume consistency."""
    try:
        hist = get_price_history(ticker, period="10d", interval="1d")
        if hist is None or hist.empty or len(hist) < 5:
            return None
        
        current_price = hist['Close'].iloc[-1]
        current_volume = hist['Volume'].iloc[-1]
        avg_volume = hist['Volume'].iloc[-5:].mean()
        
        recent_vols = hist['Volume'].iloc[-3:].values
        mean_vol = recent_vols.mean()
        if mean_vol > 0:
            vol_consistency = 1.0 - (recent_vols.std() / mean_vol)
        else:
            vol_consistency = 0.0
        
        # Scale consistency to 0-50% proxy
        estimated_delivery_pct = vol_consistency * 50
        
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        price_change_5d = ((current_price - hist['Close'].iloc[-5]) / hist['Close'].iloc[-5]) * 100
        price_change_1d = ((current_price - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
        
        # Fetch technicals for ML
        tech = get_technical_analysis(ticker)
        ml_prob = None
        
        try:
            model = get_ml_model()
            if model and current_price and tech:
                import pandas as pd
                features = pd.DataFrame([{
                    'rsi': _safe_float(tech.get('RSI', 50)),
                    'macd_hist': _safe_float(tech.get('MACD_Hist', 0)),
                    'atr_pct': (_safe_float(tech.get('ATR', 0)) / current_price) * 100 if current_price else 0,
                    'rvol': min(volume_ratio, 5),
                    'vwap_dist': ((current_price - _safe_float(tech.get('VWAP', current_price))) / _safe_float(tech.get('VWAP', current_price))) * 100 if tech.get('VWAP') else 0
                }])
                ml_prob = float(model.predict_proba(features)[0][1])
        except Exception as e:
            logger.error(f"Error calculating ML prob for {ticker}: {e}")
        
        return {
            'ticker': ticker,
            'current_price': round(current_price, 2),
            'price_change_1d': round(price_change_1d, 2),
            'price_change_5d': round(price_change_5d, 2),
            'current_volume': int(current_volume),
            'avg_volume': int(avg_volume),
            'volume_ratio': round(volume_ratio, 2),
            'estimated_delivery_pct': round(estimated_delivery_pct, 1),
            'vol_consistency': round(vol_consistency * 100, 1),
            'ml_prob': ml_prob,
            'bullish_confluence': (
                estimated_delivery_pct > DEFAULT_DELIVERY_THRESHOLD and
                price_change_1d > 0 and
                volume_ratio > VOLUME_SPIKE_THRESHOLD and
                (ml_prob is None or ml_prob > 0.55)
            ),
            'bearish_confluence': (
                estimated_delivery_pct > DEFAULT_DELIVERY_THRESHOLD and
                price_change_1d < -2 and
                volume_ratio > VOLUME_SPIKE_THRESHOLD and
                (ml_prob is None or ml_prob < 0.45)
            )
        }
    except Exception as e:
        logger.error(f"Error analyzing delivery for {ticker}: {e}")
        return None

def check_delivery_volume(ticker: str) -> list:
    """Check ticker and format alerts."""
    data = estimate_delivery_percentage(ticker)
    if not data:
        return []
    
    alerts = []
    
    # Base message format
    def format_msg(title, icon, context):
        ml_str = f"{data['ml_prob']*100:.1f}%" if data['ml_prob'] else "N/A"
        return (
            f"{icon} <b>{title}</b>\n"
            f"<b>Ticker:</b> ${ticker}\n\n"
            f"<b>Delivery Metrics:</b>\n"
            f"• Estimated Delivery: {data['estimated_delivery_pct']}%\n"
            f"• Volume Consistency: {data['vol_consistency']}%\n"
            f"• Current Volume: {data['current_volume']:,}\n"
            f"• Volume Ratio: {data['volume_ratio']}x avg\n\n"
            f"<b>Price Action:</b>\n"
            f"• Current: ${data['current_price']}\n"
            f"• 1D Change: {data['price_change_1d']:+.2f}%\n"
            f"• 5D Change: {data['price_change_5d']:+.2f}%\n\n"
            f"🧠 <b>ML Intelligence:</b>\n"
            f"• Win Probability: {ml_str}\n\n"
            f"💡 <i>{context}</i>"
        )
    
    if data['bullish_confluence']:
        alerts.append(format_msg(
            "Bullish Confluence Detected", 
            "🟢", 
            "Strong institutional buying supported by price action and heavy volume."
        ))
    elif data['bearish_confluence']:
        alerts.append(format_msg(
            "Bearish Confluence Warning", 
            "🔴", 
            "High delivery on a downward move, indicating potential large-scale distribution."
        ))
    elif data['estimated_delivery_pct'] > DEFAULT_DELIVERY_THRESHOLD:
        alerts.append(format_msg(
            "High Delivery Volume Detected", 
            "🎯", 
            "High delivery volume suggests institutional conviction and physical settlement."
        ))
    elif data['volume_ratio'] > VOLUME_SPIKE_THRESHOLD and data['estimated_delivery_pct'] > DEFAULT_DELIVERY_THRESHOLD * 0.7:
        alerts.append(format_msg(
            "Volume Spike + Solid Delivery", 
            "📊", 
            "Sustained elevated volume combined with consistent delivery behavior."
        ))
        
    return alerts

def scan_and_alert_portfolio(tickers: list):
    """Run the scan across a list of tickers and send Telegram alerts."""
    logger.info(f"Starting delivery volume scan for {len(tickers)} tickers")
    alerts_sent = 0
    for ticker in tickers:
        try:
            alerts = check_delivery_volume(ticker)
            # Send only the most relevant (highest priority) alert if multiple match
            if alerts:
                send_telegram(alerts[0], parse_mode="HTML")
                alerts_sent += 1
        except Exception as e:
            logger.error(f"Error checking delivery for {ticker}: {e}")
    
    logger.info(f"Delivery volume scan complete. Sent {alerts_sent} alerts.")
    return alerts_sent
