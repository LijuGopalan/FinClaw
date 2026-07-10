import json
import schwab
from schwab.auth import client_from_token_file

# Create a dummy token file
token_data = {
    "creation_timestamp": 1700000000.0,
    "token": {
        "access_token": "dummy",
        "refresh_token": "dummy_refresh",
        "token_type": "Bearer",
        "expires_in": 1800,
        "expires_at": 1700000000.0
    }
}
with open("test_token.json", "w") as f:
    json.dump(token_data, f)

try:
    c = client_from_token_file("test_token.json", "dummy_key", "dummy_secret")
    print("Successfully loaded client from token file!")
except Exception as e:
    print("Error:", e)
