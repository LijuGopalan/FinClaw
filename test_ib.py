from flask import Flask, jsonify
import ib_async as iba

app = Flask(__name__)
ib = iba.IB()

@app.route("/")
def index():
    try:
        if not ib.isConnected():
            ib.connect('127.0.0.1', 4001, clientId=3)
        return jsonify({"status": "connected"})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run(port=5060)
