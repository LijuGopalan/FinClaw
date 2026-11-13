#!/usr/bin/env python3
"""Live diagnostic for Charles Schwab API connectivity."""
import os, sys, json, time
from dotenv import load_dotenv
load_dotenv()

app_key    = os.getenv("SCHWAB_APP_KEY")
app_secret = os.getenv("SCHWAB_APP_SECRET")
token_path = os.path.join(os.path.dirname(__file__), "schwab_token.json")

print("=" * 60)
print("  Charles Schwab API — Live Diagnostic")
print("=" * 60)

# 1. Check credentials
print("\n[1] Credentials Check")
if not app_key or not app_secret:
    print("  ❌ SCHWAB_APP_KEY or SCHWAB_APP_SECRET not set in .env")
    sys.exit(1)
print(f"  ✅ App Key:    {app_key[:8]}...{app_key[-4:]}")
print(f"  ✅ App Secret: {app_secret[:8]}...{app_secret[-4:]}")

# 2. Check token file
print("\n[2] Token File Check")
if not os.path.exists(token_path):
    print(f"  ❌ Token file not found: {token_path}")
    print("  Run setup_schwab.py to authenticate.")
    sys.exit(1)

with open(token_path) as f:
    token_data = json.load(f)

expires_at = token_data.get("token", {}).get("expires_at", 0)
now = time.time()
if expires_at > now:
    remaining = int(expires_at - now)
    print(f"  ✅ Access token valid for {remaining // 60}m {remaining % 60}s")
else:
    print(f"  ⚠️  Access token expired ({int(now - expires_at)}s ago) — will attempt refresh")

has_refresh = bool(token_data.get("token", {}).get("refresh_token"))
print(f"  {'✅' if has_refresh else '❌'} Refresh token: {'present' if has_refresh else 'MISSING'}")

# 3. Attempt client creation (triggers token refresh if expired)
print("\n[3] Client Authentication (token refresh)")
try:
    import schwab
    client = schwab.auth.client_from_token_file(token_path, app_key, app_secret)
    print("  ✅ Client created successfully (token refreshed if needed)")
except Exception as e:
    print(f"  ❌ Failed to create client: {e}")
    print("  → You may need to re-run setup_schwab.py to get a fresh refresh token.")
    sys.exit(1)

# 4. Test: Get a stock quote
print("\n[4] API Call: Get Quote (AAPL)")
try:
    resp = client.get_quote("AAPL")
    if resp.status_code == 200:
        data = resp.json()
        quote = data.get("AAPL", {}).get("quote", {})
        last = quote.get("lastPrice", "N/A")
        bid  = quote.get("bidPrice", "N/A")
        ask  = quote.get("askPrice", "N/A")
        print(f"  ✅ AAPL — Last: ${last}  Bid: ${bid}  Ask: ${ask}")
    else:
        print(f"  ❌ HTTP {resp.status_code}: {resp.text[:200]}")
except Exception as e:
    print(f"  ❌ Quote request failed: {e}")

# 5. Test: Get accounts
print("\n[5] API Call: Get Linked Accounts")
try:
    resp = client.get_account_numbers()
    if resp.status_code == 200:
        accounts = resp.json()
        print(f"  ✅ Found {len(accounts)} linked account(s):")
        for acct in accounts:
            acct_num = acct.get("accountNumber", "???")
            hash_val = acct.get("hashValue", "???")
            print(f"     • Account: ...{acct_num[-4:]}  (hash: {hash_val[:12]}...)")
    else:
        print(f"  ❌ HTTP {resp.status_code}: {resp.text[:200]}")
except Exception as e:
    print(f"  ❌ Account request failed: {e}")

# 6. Test: Get price history
print("\n[6] API Call: Price History (SPY, 5 days)")
try:
    resp = client.get_price_history_every_day("SPY")
    if resp.status_code == 200:
        candles = resp.json().get("candles", [])
        print(f"  ✅ Received {len(candles)} candle(s)")
        if candles:
            latest = candles[-1]
            print(f"     Latest: O={latest.get('open')} H={latest.get('high')} L={latest.get('low')} C={latest.get('close')}")
    else:
        print(f"  ❌ HTTP {resp.status_code}: {resp.text[:200]}")
except Exception as e:
    print(f"  ❌ Price history request failed: {e}")

# 7. Test: Options chain
print("\n[7] API Call: Options Chain (AAPL)")
try:
    from schwab.client import Client
    resp = client.get_option_chain(
        "AAPL",
        contract_type=Client.Options.ContractType.CALL,
        strike_count=2
    )
    if resp.status_code == 200:
        data = resp.json()
        status = data.get("status", "UNKNOWN")
        num_calls = len(data.get("callExpDateMap", {}))
        print(f"  ✅ Options status: {status}, {num_calls} expiration date(s) returned")
    else:
        print(f"  ❌ HTTP {resp.status_code}: {resp.text[:200]}")
except Exception as e:
    print(f"  ❌ Options chain request failed: {e}")

print("\n" + "=" * 60)
print("  Diagnostic Complete")
print("=" * 60)
