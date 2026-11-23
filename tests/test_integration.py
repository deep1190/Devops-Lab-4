"""Integration tests: app + real SQLite database together. Gate 2 of the pipeline."""
import sqlite3


def test_note_round_trip(client):
    created = client.post("/notes", json={"text": "hello"})
    assert created.status_code == 201
    notes = client.get("/notes").get_json()
    assert notes == [{"id": created.get_json()["id"], "text": "hello"}]


def test_notes_persist_in_database_file(client, tmp_path):
    client.post("/notes", json={"text": "persisted"})
    conn = sqlite3.connect(tmp_path / "test.db")
    rows = conn.execute("SELECT text FROM notes").fetchall()
    conn.close()
    assert rows == [("persisted",)]


def test_multiple_notes_ordered(client):
    for t in ["a", "b", "c"]:
        client.post("/notes", json={"text": t})
    assert [n["text"] for n in client.get("/notes").get_json()] == ["a", "b", "c"]
