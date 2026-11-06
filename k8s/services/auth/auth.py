import os
import uuid
import datetime as dt
import psycopg2
import requests
from flask import Flask, request, redirect, make_response, render_template
from werkzeug.security import generate_password_hash, check_password_hash

LOGIN_TITLE = os.getenv("LOGIN_TITLE")
REGISTER_TITLE = os.getenv("REGISTER_TITLE")
WELCOME_MESSAGE = os.getenv("WELCOME_MESSAGE")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

NOTIFICATION_URL = os.getenv("NOTIFICATION_URL")
PROFILE_PUBLIC_URL = os.getenv("PROFILE_PUBLIC_URL")

SESSION_COOKIE = "session_token"

def db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )

def init_db():
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '3 hours')
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL
        );
        """)
        conn.commit()

def is_db_ready() -> bool:
    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        return True
    except Exception:
        return False

def create_session(username: str) -> str:
    token = str(uuid.uuid4())
    expires = dt.datetime.utcnow() + dt.timedelta(days=1)
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sessions(token, username, expires_at) VALUES (%s, %s, %s)",
            (token, username, expires),
        )
        conn.commit()
    return token

def validate_session_token(token: str):
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

def send_notification(username: str, message: str, notify_type: str = "info"):
    try:
        requests.post(
            f"{NOTIFICATION_URL.rstrip('/')}/api/notify/create",
            json={
                "username": username,
                "message": message,
                "type": notify_type
            },
            timeout=2
        )
    except Exception as e:
        print(f"Failed to send notification: {e}")

app = Flask(__name__)


@app.before_request
def _startup_once():
    if not getattr(app, "_db_inited", False):
        init_db()
        app._db_inited = True

@app.get("/")
def home():
    return render_template(
        "home.html",
        welcome=WELCOME_MESSAGE,
        login=LOGIN_TITLE,
        register=REGISTER_TITLE,
        profile_url=PROFILE_PUBLIC_URL.rstrip("/"),
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", title=LOGIN_TITLE, error=None)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT password_hash, status FROM users WHERE username=%s", (username,))
        row = cur.fetchone()

    if not row:
        return render_template("login.html", title=LOGIN_TITLE, error="Пользователь не найден")

    password_hash, status = row
    if status == "blocked":
        return render_template("login.html", title=LOGIN_TITLE, error="Пользователь заблокирован")
    if not check_password_hash(password_hash, password):
        return render_template("login.html", title=LOGIN_TITLE, error="Неверный пароль")

    token = create_session(username)

    send_notification(username, "Вы совершили вход в систему.", "login")

    resp = make_response(redirect(PROFILE_PUBLIC_URL.rstrip("/") + "/profile"))
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax")
    return resp

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html", title=REGISTER_TITLE, error=None)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    status = "active"

    if not username or not password:
        return render_template("register.html", title=REGISTER_TITLE, error="Заполните поля")

    password_hash = generate_password_hash(password)

    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users(username, password_hash, status) VALUES (%s, %s, %s)",
                (username, password_hash, status),
            )
            conn.commit()
    except Exception:
        return render_template("register.html", title=REGISTER_TITLE, error="Такой логин уже существует")

    send_notification(username, "Вы успешно зарегистрировались.", "registration")

    return redirect("/login")

@app.get("/logout")
def logout():
    resp = make_response(redirect("/"))
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.get("/health/live")
def health_live():
    return {"status": "alive"}, 200

@app.get("/health/ready")
def health_ready():
    return ({"status": "ready"}, 200) if is_db_ready() else ({"status": "not_ready"}, 503)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
