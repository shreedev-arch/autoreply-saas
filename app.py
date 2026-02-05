from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import secrets
from datetime import date

app = Flask(__name__)
app.secret_key = "supersecretkey"

def get_db():
    return sqlite3.connect("database.db")

def ensure_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        plan TEXT DEFAULT 'FREE'
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        api_key TEXT UNIQUE
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        message TEXT,
        reply TEXT,
        date TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_key TEXT,
        date TEXT,
        count INTEGER
    )""")

    conn.commit()
    conn.close()

ensure_db()

# ---------------- LOGIN ----------------
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (request.form["username"], request.form["password"])
        )
        user = cur.fetchone()
        conn.close()

        if user:
            session["user"] = request.form["username"]
            return redirect(url_for("auto_reply"))

    return render_template("login.html")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        api_key = secrets.token_hex(16)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password) VALUES (?,?)",
            (request.form["username"], request.form["password"])
        )
        cur.execute(
            "INSERT INTO api_keys (user, api_key) VALUES (?,?)",
            (request.form["username"], api_key)
        )
        conn.commit()
        conn.close()
        return redirect(url_for("login"))

    return render_template("register.html")

# ---------------- UI AUTO REPLY ----------------
@app.route("/auto-reply", methods=["GET", "POST"])
def auto_reply():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "GET":
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT api_key FROM api_keys WHERE user=?", (session["user"],))
        api_key = cur.fetchone()[0]

        cur.execute(
            "SELECT message, reply FROM messages WHERE user=? ORDER BY id DESC LIMIT 10",
            (session["user"],)
        )
        history = cur.fetchall()
        conn.close()

        return render_template("auto_reply.html", api_key=api_key, history=history)

    data = request.get_json()
    msg = data.get("message", "").strip()
    if not msg:
        return {"reply": "⚠️ Message cannot be empty"}

    reply = f"You said: {msg}"

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages VALUES (NULL, ?, ?, ?, ?)",
        (session["user"], msg, reply, date.today().isoformat())
    )
    conn.commit()
    conn.close()

    return {"reply": reply}

# ---------------- API AUTO REPLY ----------------
@app.route("/api/auto-reply", methods=["POST"])
def api_auto_reply():
    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        return {"error": "API key missing"}, 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT users.username, users.plan
        FROM api_keys JOIN users ON api_keys.user = users.username
        WHERE api_keys.api_key=?
    """, (api_key,))
    row = cur.fetchone()

    if not row:
        return {"error": "Invalid API key"}, 401

    user, plan = row
    msg = request.json.get("message", "")

    reply = f"Hello {user}, message received ✅"

    cur.execute(
        "INSERT INTO messages VALUES (NULL, ?, ?, ?, ?)",
        (user, msg, reply, date.today().isoformat())
    )
    conn.commit()
    conn.close()

    return {"reply": reply, "plan": plan}

# ---------------- UPGRADE ----------------
@app.route("/upgrade-ui", methods=["POST"])
def upgrade_ui():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET plan='PRO' WHERE username=?", (session["user"],))
    conn.commit()
    conn.close()

    return redirect(url_for("auto_reply"))

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
