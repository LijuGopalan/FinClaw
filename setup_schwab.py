import os
import sys
import json
import time
import subprocess
import webbrowser
from dotenv import load_dotenv

def make_update_token_func(token_path):
    def update_token(t, *args, **kwargs):
        with open(token_path, "w") as f:
            json.dump(t, f)
    return update_token

def main():
    load_dotenv()

    try:
        import schwab
        from schwab.auth import get_auth_context, client_from_received_url
    except ImportError:
        print("ERROR: 'schwab-py' library is not installed.")
        print("Please run: pip install schwab-py")
        sys.exit(1)

    app_key = os.getenv("SCHWAB_APP_KEY")
    app_secret = os.getenv("SCHWAB_APP_SECRET")
    callback_url = os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
    token_path = os.path.join(os.path.dirname(__file__), "schwab_token.json")

    if not app_key or not app_secret:
        print("ERROR: SCHWAB_APP_KEY and SCHWAB_APP_SECRET must be set in your .env file.")
        print("Please edit the .env file and add your credentials.")
        sys.exit(1)

    print("=" * 66)
    print("  Charles Schwab API — Interactive Authentication Flow")
    print("=" * 66)
    print(f"App Key:      {app_key[:8]}...{app_key[-4:] if len(app_key) > 12 else ''}")
    print(f"Callback URL: {callback_url}")
    print(f"Token File:   {token_path}")
    print("-" * 66)

    try:
        # Check if an existing refresh token is present in .env
        refresh_token = os.getenv("SCHWAB_REFRESH_TOKEN")
        validated = False

        if refresh_token and not refresh_token.startswith("#"):
            print("\nFound SCHWAB_REFRESH_TOKEN in .env. Testing validity with Schwab API...")
            token_data = {
                "creation_timestamp": time.time(),
                "token": {
                    "access_token": "expired_dummy_token",
                    "refresh_token": refresh_token,
                    "token_type": "Bearer",
                    "expires_in": 1800,
                    "expires_at": time.time() - 1000
                }
            }
            with open(token_path, "w") as f:
                json.dump(token_data, f)

            try:
                client = schwab.auth.client_from_token_file(token_path, app_key, app_secret)
                resp = client.get_quote("AAPL")
                if resp.status_code == 200:
                    validated = True
                    print("✅ Existing refresh token in .env is valid and active!")
                    print(f"Token successfully synchronized: {token_path}")
            except Exception:
                print("⚠️  Existing refresh token in .env is expired/revoked.")

        if not validated:
            print("\nGenerating fresh OAuth authorization session...")
            auth_context = get_auth_context(app_key, callback_url)

            print("\n" + "=" * 66)
            print("  STEP 1: Log in to Charles Schwab")
            print("=" * 66)
            print("Opening your browser automatically. If it doesn't open, visit:")
            print(f"\n{auth_context.authorization_url}\n")
            print("Instructions:")
            print("  1. Log in with your Charles Schwab username/password & 2FA.")
            print("  2. Select your account and click 'Allow' / 'Approve'.")
            print("  3. Your browser will redirect to https://127.0.0.1/?code=...")
            print("     (It will show 'Connection Refused' / 'Site can't be reached' — THAT IS NORMAL!)")
            print("\n⚠️  CRITICAL TIMING NOTICE:")
            print("  Schwab authorization codes EXPIRE IN 30 SECONDS from the redirect!")
            print("  As soon as you see the redirect:")
            print("    • Press Cmd+L to select the browser address bar, then Cmd+C to copy.")
            print("    • Switch back to this terminal and press [ENTER] (it will auto-read clipboard)!")
            print("=" * 66 + "\n")

            # Try to open the browser automatically
            try:
                webbrowser.open(auth_context.authorization_url)
            except Exception:
                pass

            raw_url = input("Paste Redirect URL (or press [Enter] to auto-read clipboard)> ").strip()

            if not raw_url:
                try:
                    cb = subprocess.check_output(["pbpaste"], text=True).strip()
                    if "code=" in cb:
                        raw_url = cb
                        print("📋 Auto-detected redirect URL from clipboard!")
                    else:
                        print("⚠️ Clipboard does not contain a redirect URL with 'code='.")
                except Exception:
                    pass

            raw_url = raw_url.strip().strip("'\"")

            if not raw_url or "code=" not in raw_url:
                print("\n❌ Error: No valid redirect URL with 'code=' provided.")
                print("Please re-run this script and paste the URL as soon as Schwab redirects.")
                sys.exit(1)

            print("\nExchanging authorization code with Schwab token server...")
            client = client_from_received_url(
                api_key=app_key,
                app_secret=app_secret,
                auth_context=auth_context,
                received_url=raw_url,
                token_write_func=make_update_token_func(token_path)
            )

            print("✅ Successfully authenticated with Charles Schwab API!")
            print(f"Token saved to: {token_path}")

        # Live verification call
        print("\nTesting live market data connectivity...")
        try:
            resp = client.get_quote("AAPL")
            if resp.status_code == 200:
                data = resp.json().get("AAPL", {}).get("quote", {})
                last_price = data.get("lastPrice")
                print(f"🎉 SUCCESS! Live market data retrieved: AAPL is ${last_price}")
            else:
                print(f"⚠️ Quote probe returned status {resp.status_code}: {resp.text[:200]}")
        except Exception as q_err:
            print(f"⚠️ Quote probe error: {q_err}")

        # Update .env with fresh refresh token
        try:
            with open(token_path) as tf:
                tdata = json.load(tf)
            fresh_refresh = tdata.get("token", {}).get("refresh_token")
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            if fresh_refresh and os.path.exists(env_path):
                with open(env_path, "r") as ef:
                    content = ef.read()
                import re
                if "SCHWAB_REFRESH_TOKEN=" in content:
                    content = re.sub(r"#?\s*SCHWAB_REFRESH_TOKEN=.*", f"SCHWAB_REFRESH_TOKEN={fresh_refresh}", content)
                else:
                    content += f"\nSCHWAB_REFRESH_TOKEN={fresh_refresh}\n"
                with open(env_path, "w") as ef:
                    ef.write(content)
                print("✅ Synchronized fresh SCHWAB_REFRESH_TOKEN into .env")
        except Exception:
            pass

        print("\nAll done! FinClaw is ready to stream Charles Schwab live data.")

    except Exception as e:
        err_msg = str(e)
        print(f"\n❌ Authentication failed: {err_msg}")
        if "Authorization code is invalid, expired or revoked" in err_msg:
            print("\n💡 Reason: Schwab authorization codes expire in only 30 SECONDS or are single-use.")
            print("   Solution: Run './venv/bin/python setup_schwab.py' again. When the browser redirects,")
            print("   immediately press Cmd+L then Cmd+C, switch to terminal, and hit Enter!")
        elif "invalid_grant" in err_msg:
            print("\n💡 Please check that your SCHWAB_CALLBACK_URL in .env matches the Schwab Developer Portal exactly.")

if __name__ == "__main__":
    main()
