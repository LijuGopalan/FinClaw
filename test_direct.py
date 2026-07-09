import os, json, requests
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent?key={api_key}"
payload = {
  "contents": [{"parts": [{"text": "Write a 100 word story about a cat."}]}],
  "generationConfig": {"maxOutputTokens": 500}
}
resp = requests.post(url, json=payload)
print(resp.status_code)
print(resp.json())
