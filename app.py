from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import secrets
from datetime import date

app = Flask(__name__)
app.secret_key = "supersecretkey"

def get_db():
    return sqlite3.connect("/var/data/database.db")

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
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()

        # 🔒 Check if user already exists
        cur.execute("SELECT id FROM users WHERE username=?", (username,))
        if cur.fetchone():
            conn.close()
            return "User already exists. Please login."

        api_key = secrets.token_hex(16)

        cur.execute(
            "INSERT INTO users (username, password, plan) VALUES (?, ?, 'FREE')",
            (username, password)
        )
        cur.execute(
            "INSERT INTO api_keys (user, api_key) VALUES (?, ?)",
            (username, api_key)
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
        cur.execute("SELECT plan FROM users WHERE username=?", (session["user"],))
        plan = cur.fetchone()[0]

        cur.execute(
            "SELECT message, reply FROM messages WHERE user=? ORDER BY id DESC LIMIT 10",
            (session["user"],)
        )
        history = cur.fetchall()
        conn.close()

        return render_template("auto_reply.html", api_key=api_key, history=history, plan=plan)

        data = request.get_json(silent=True) or {}
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

    # 🔍 Validate API key + get user + plan
    cur.execute("""
        SELECT users.username, users.plan
        FROM api_keys
        JOIN users ON api_keys.user = users.username
        WHERE api_keys.api_key = ?
    """, (api_key,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return {"error": "Invalid API key"}, 401

    user, plan = row

    # ⚙️ Rate limits
    DAILY_LIMIT = 50 if plan == "FREE" else 1000
    today = date.today().isoformat()

    # 📊 Check usage
    cur.execute(
        "SELECT count FROM api_usage WHERE api_key=? AND date=?",
        (api_key, today)
    )
    usage = cur.fetchone()

    if usage and usage[0] >= DAILY_LIMIT:
        conn.close()
        return {"error": "Daily limit reached"}, 429

    # ➕ Update usage
    if usage:
        cur.execute(
            "UPDATE api_usage SET count = count + 1 WHERE api_key=? AND date=?",
            (api_key, today)
        )
    else:
        cur.execute(
            "INSERT INTO api_usage (api_key, date, count) VALUES (?, ?, 1)",
            (api_key, today)
        )

    # 💬 Message logic
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()

    if not message:
        conn.close()
        return {"error": "Message cannot be empty"}, 400

    reply = f"Hello {user}, message received ✅"

    cur.execute(
        "INSERT INTO messages VALUES (NULL, ?, ?, ?, ?)",
        (user, message, reply, today)
    )

    conn.commit()
    conn.close()

    return {
        "plan": plan,
        "reply": reply
    }

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
