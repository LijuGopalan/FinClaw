import os
import sys
from dotenv import load_dotenv

def main():
    load_dotenv()

    # Make sure schwab library is installed
    try:
        import schwab
    except ImportError:
        print("ERROR: 'schwab-py' library is not installed.")
        print("Please run: pip install schwab-py")
        sys.exit(1)

    app_key = os.getenv("SCHWAB_APP_KEY")
    app_secret = os.getenv("SCHWAB_APP_SECRET")
    callback_url = os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8080")
    token_path = os.path.join(os.path.dirname(__file__), "schwab_token.json")

    if not app_key or not app_secret:
        print("ERROR: SCHWAB_APP_KEY and SCHWAB_APP_SECRET must be set in your .env file.")
        print("Please edit the .env file and add your credentials.")
        sys.exit(1)

    print("=" * 60)
    print("Charles Schwab API — Interactive Authentication Flow")
    print("=" * 60)
    print(f"App Key:      {app_key[:5]}...{app_key[-5:] if len(app_key) > 10 else ''}")
    print(f"Callback URL: {callback_url}")
    print(f"Token File:   {token_path}")
    print("-" * 60)
    
    try:
        refresh_token = os.getenv("SCHWAB_REFRESH_TOKEN")
        
        if refresh_token:
            print("\nFound SCHWAB_REFRESH_TOKEN in .env!")
            print("Building token file programmatically...")
            
            import json
            import time
            token_data = {
                "creation_timestamp": time.time(),
                "token": {
                    "access_token": "expired_dummy_token",
                    "refresh_token": refresh_token,
                    "token_type": "Bearer",
                    "expires_in": 1800,
                    "expires_at": time.time() - 1000  # Expired so it forces a refresh
                }
            }
            with open(token_path, "w") as f:
                json.dump(token_data, f)
                
            # Verify the client can be built from it (this will trigger a refresh)
            client = schwab.auth.client_from_token_file(
                token_path, app_key, app_secret
            )
            print("\n✅ Successfully validated refresh token with Charles Schwab API!")
            print(f"Token fully synchronized and saved to: {token_path}")
            print("You can now safely restart the FinClaw daemon.")
            
        else:
            print("\nStarting manual authentication flow...")
            print("A browser window will open (or you will be provided a link).")
            print("Log in to your Charles Schwab account, accept the terms, and you will be redirected.")
            print("The browser will show an error (e.g., 'Connection Refused')—that is normal!")
            print("Copy the ENTIRE URL from the browser's address bar and paste it below.\n")
            
            # This function handles the manual flow, prompts the user, and saves the token
            client = schwab.auth.client_from_manual_flow(
                app_key,
                app_secret,
                callback_url,
                token_path
            )
            
            print("\n✅ Successfully authenticated with Charles Schwab API!")
            print(f"Token successfully saved to: {token_path}")
            print("You can now safely restart the FinClaw daemon.")
            
    except Exception as e:
        print(f"\n❌ Error during authentication: {e}")

if __name__ == "__main__":
    main()
