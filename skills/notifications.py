"""
FinClaw Notifications — Telegram, Email, Slack Senders
=======================================================
Implements the actual message delivery for alerts configured
in openclaw.config.yml.
"""

import os
import logging
import requests

logger = logging.getLogger("finclaw.notifications")


# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(message: str, parse_mode: str = "HTML") -> dict:
    """
    Send a message via Telegram Bot API.
    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        return {"error": "Telegram not configured"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            logger.info("Telegram message sent (chat_id=%s)", chat_id)
            return {"status": "sent", "message_id": data["result"]["message_id"]}
        else:
            logger.error("Telegram API error: %s", data.get("description"))
            return {"error": data.get("description", "Unknown error")}
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return {"error": str(e)}


# ============================================================
# SLACK
# ============================================================
def send_slack(message: str) -> dict:
    """
    Send a message via Slack incoming webhook.
    Requires SLACK_WEBHOOK_URL in .env.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    if not webhook_url:
        logger.warning("Slack not configured — set SLACK_WEBHOOK_URL in .env")
        return {"error": "Slack not configured"}

    try:
        resp = requests.post(webhook_url, json={"text": message}, timeout=10)
        resp.raise_for_status()
        logger.info("Slack message sent")
        return {"status": "sent"}
    except Exception as e:
        logger.error("Slack send failed: %s", e)
        return {"error": str(e)}


# ============================================================
# EMAIL (via SMTP)
# ============================================================
def send_email(subject: str, body: str) -> dict:
    """
    Send an email via SMTP.
    Requires EMAIL_FROM, EMAIL_TO, EMAIL_PASSWORD in .env.
    """
    import smtplib
    from email.mime.text import MIMEText

    from_addr = os.getenv("EMAIL_FROM")
    to_addr = os.getenv("EMAIL_TO")
    password = os.getenv("EMAIL_PASSWORD")
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not all([from_addr, to_addr, password]):
        logger.warning("Email not configured — set EMAIL_FROM, EMAIL_TO, EMAIL_PASSWORD in .env")
        return {"error": "Email not configured"}

    try:
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(from_addr, password)
            server.send_message(msg)

        logger.info("Email sent to %s", to_addr)
        return {"status": "sent"}
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return {"error": str(e)}


# ============================================================
# UNIFIED ALERT SENDER
# ============================================================
def send_alert(title: str, message: str, channels: list = None) -> dict:
    """
    Send an alert through all configured notification channels.
    channels: list of ["telegram", "slack", "email"] or None for all enabled.
    """
    results = {}

    # Default: try all channels
    if channels is None:
        channels = []
        if os.getenv("TELEGRAM_BOT_TOKEN"):
            channels.append("telegram")
        if os.getenv("SLACK_WEBHOOK_URL"):
            channels.append("slack")
        if os.getenv("EMAIL_FROM"):
            channels.append("email")

    formatted = f"🦾 <b>FinClaw Alert</b>\n\n<b>{title}</b>\n{message}"

    for ch in channels:
        if ch == "telegram":
            results["telegram"] = send_telegram(formatted)
        elif ch == "slack":
            results["slack"] = send_slack(f"🦾 *FinClaw Alert*\n\n*{title}*\n{message}")
        elif ch == "email":
            results["email"] = send_email(f"FinClaw: {title}", formatted)

    if not channels:
        logger.info("No notification channels configured — alert logged only: %s", title)
        results["logged"] = True

    return results
