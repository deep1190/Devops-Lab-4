import os
import random
import sqlite3
from flask import Flask, jsonify, request

APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
APP_COLOR = os.getenv("APP_COLOR", "blue")
DB_PATH = os.getenv("DB_PATH", "/data/notes.db")
# Secret is injected at runtime (Vault / env), never hard-coded
API_TOKEN = os.getenv("API_TOKEN", "")


def get_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL)")
    return conn


def create_app():
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/version")
    def version():
        return jsonify(version=APP_VERSION, color=APP_COLOR)

    @app.get("/notes")
    def list_notes():
        # FAIL_RATE lets us simulate a faulty release for canary/rollback demos
        if random.random() < float(os.getenv("FAIL_RATE", "0")):
            return jsonify(error="simulated failure"), 500
        conn = get_db()
        rows = conn.execute("SELECT id, text FROM notes").fetchall()
        conn.close()
        return jsonify([{"id": r[0], "text": r[1]} for r in rows])

    @app.post("/notes")
    def add_note():
        if API_TOKEN and request.headers.get("X-API-Token") != API_TOKEN:
            return jsonify(error="unauthorized"), 401
        data = request.get_json(silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify(error="text required"), 400
        conn = get_db()
        cur = conn.execute("INSERT INTO notes (text) VALUES (?)", (text,))
        conn.commit()
        note_id = cur.lastrowid
        conn.close()
        return jsonify(id=note_id, text=text), 201

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
