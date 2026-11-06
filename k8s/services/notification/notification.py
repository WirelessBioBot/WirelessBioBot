import os
import psycopg2
from flask import Flask, request, jsonify

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")


def db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )


def init_db():
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '3 hours'),
            is_read BOOLEAN NOT NULL DEFAULT FALSE,
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE
        );
        """)
        conn.commit()


app = Flask(__name__)

init_db()


@app.post("/api/notify/create")
def create_notification():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    message = data.get("message")
    notify_type = data.get("type", "info")

    if not username or not message:
        return {"error": "Missing username or message"}, 400

    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notifications (username, message, type) VALUES (%s, %s, %s)",
                (username, message, notify_type)
            )
            conn.commit()
        return {"ok": True, "id": cur.lastrowid}, 201
    except Exception as e:
        return {"error": str(e)}, 500


@app.get("/api/notify/<username>")
def get_notifications(username):
    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, message, type, created_at 
                FROM notifications 
                WHERE username = %s AND is_deleted = FALSE
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (username,)
            )
            notifications = []
            for row in cur.fetchall():
                notifications.append({
                    "id": row[0],
                    "message": row[1],
                    "type": row[2],
                    "created_at": row[3].strftime("%Y-%m-%d %H:%M:%S")
                })
            return {"notifications": notifications}, 200
    except Exception as e:
        return {"error": str(e)}, 500


@app.post("/api/notify/<int:notification_id>/delete")
def delete_notification(notification_id):
    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE notifications SET is_deleted = TRUE WHERE id = %s",
                (notification_id,)
            )
            conn.commit()
            return {"ok": True}, 200
    except Exception as e:
        return {"error": str(e)}, 500


@app.post("/api/notify/<username>/mark-read")
def mark_all_read(username):
    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE notifications SET is_read = TRUE WHERE username = %s AND is_deleted = FALSE",
                (username,)
            )
            conn.commit()
            return {"ok": True}, 200
    except Exception as e:
        return {"error": str(e)}, 500


@app.get("/health/live")
def health_live():
    return {"status": "alive"}, 200


@app.get("/health/ready")
def health_ready():
    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1;")
        return {"status": "ready"}, 200
    except:
        return {"status": "not_ready"}, 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)