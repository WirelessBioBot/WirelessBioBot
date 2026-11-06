import os
import psycopg2
import requests
import datetime as dt
from flask import Flask, request, redirect, render_template

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

NOTIFICATION_URL = os.getenv("NOTIFICATION_URL")
AUTH_URL = os.getenv("AUTH_URL")
AUTH_PUBLIC_URL = os.getenv("AUTH_PUBLIC_URL")  # для редиректа на страницу логина

WELCOME_MESSAGE = os.getenv("WELCOME_MESSAGE")
SESSION_COOKIE = "session_token"

def db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )

def is_db_ready() -> bool:
    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        return True
    except Exception:
        return False

def get_user(username: str):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT username, status, created_at FROM users WHERE username=%s", (username,))
        return cur.fetchone()

def validate_session_db(token: str):
    if not token:
        return None
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT username, expires_at FROM sessions WHERE token=%s", (token,))
        row = cur.fetchone()
    if not row:
        return None
    username, expires_at = row
    if expires_at < dt.datetime.utcnow():
        return None
    return username


def update_user_status(username: str, new_status: str) -> bool:
    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM users WHERE username = %s", (username,))
            old_status_row = cur.fetchone()
            old_status = old_status_row[0] if old_status_row else "unknown"

            cur.execute(
                "UPDATE users SET status = %s WHERE username = %s",
                (new_status, username)
            )
            conn.commit()

            try:
                requests.post(
                    f"{NOTIFICATION_URL.rstrip('/')}/api/notify/create",
                    json={
                        "username": username,
                        "message": f"Вы сменили статус на '{new_status}'.",
                        "type": "status_change"
                    },
                    timeout=2
                )
            except:
                pass

            return cur.rowcount > 0
    except Exception as e:
        print(f"Ошибка обновления статуса: {e}")
        return False

def get_user_notifications(username: str):
    try:
        response = requests.get(
            f"{NOTIFICATION_URL.rstrip('/')}/api/notify/{username}",
            timeout=3
        )
        if response.status_code == 200:
            return response.json().get("notifications", [])
    except:
        pass
    return []

def delete_notification(notification_id: int):
    try:
        requests.post(
            f"{NOTIFICATION_URL.rstrip('/')}/api/notify/{notification_id}/delete",
            timeout=2
        )
    except:
        pass

app = Flask(__name__)


@app.post("/profile/notifications/<int:notification_id>/delete")
def delete_notification_route(notification_id):
    token = request.cookies.get(SESSION_COOKIE)
    username = validate_session_db(token)
    if not username:
        return redirect(AUTH_PUBLIC_URL.rstrip("/") + "/login")

    delete_notification(notification_id)
    return redirect("/profile")


@app.route("/profile/update-status", methods=["POST"])
def update_status():
    token = request.cookies.get(SESSION_COOKIE)
    username = validate_session_db(token)
    if not username:
        return redirect(AUTH_PUBLIC_URL.rstrip("/") + "/login")

    new_status = request.form.get("new_status")
    if new_status not in ["active", "blocked"]:
        return redirect("/profile")

    if update_user_status(username, new_status):
        return redirect("/profile")
    else:
        return "Ошибка обновления статуса", 500

@app.get("/profile")
def profile():
    token = request.cookies.get(SESSION_COOKIE)
    username = validate_session_db(token)
    if not username:
        return redirect(AUTH_PUBLIC_URL.rstrip("/") + "/login")

    u = get_user(username)
    if not u:
        return redirect(AUTH_PUBLIC_URL.rstrip("/") + "/login")

    username, status, created_at = u
    formatted_created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")

    notifications = get_user_notifications(username)
    return render_template(
        "profile.html",
        username=username,
        status=status,
        created_at=str(formatted_created_at),
        auth_public=AUTH_PUBLIC_URL.rstrip("/"),
        notifications=notifications,
    )

@app.get("/health/live")
def health_live():
    return {"status": "alive"}, 200

@app.get("/health/ready")
def health_ready():
    return ({"status": "ready"}, 200) if is_db_ready() else ({"status": "not_ready"}, 503)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
