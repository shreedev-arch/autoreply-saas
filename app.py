from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import secrets
from datetime import date

def ensure_db():
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        plan TEXT DEFAULT 'FREE'
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        api_key TEXT UNIQUE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_key TEXT,
        date TEXT,
        count INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        message TEXT,
        reply TEXT,
        date TEXT
    )
    """)

    conn.commit()
    conn.close()


app = Flask(__name__)
app.secret_key = "supersecretkey"  # required for sessions

ensure_db()

def get_db():
    return sqlite3.connect("database.db")

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=? AND password=?",(username, password))
        user = cur.fetchone()
        conn.close()

        if user:
            session["user"] = username
            return redirect(url_for("auto_reply"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        api_key = secrets.token_hex(16)

        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password, plan) VALUES (?, ?, 'FREE')",(username, password))
        cur.execute("INSERT INTO api_keys (user, api_key) VALUES (?, ?)",(username, api_key))
        conn.commit()
        conn.close()

        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/auto-reply", methods=["GET"])
@app.route("/api/auto-reply", methods=["POST"])
def auto_reply():

    # 🔒 Block access if not logged in (browser)
    if "user" not in session and request.method == "GET":
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

         return render_template(
         "auto_reply.html",
         api_key=api_key,
         history=history
         )

    if request.method == "POST" and "user" in session:
         data = request.get_json(silent=True) or {}
         msg = data.get("message", "").strip()

    if not msg:
         return {"reply": "⚠️ Message cannot be empty"}

         reply = f"You said: {msg}"

         conn = get_db()
         cur = conn.cursor()
         cur.execute(
         "INSERT INTO messages (user, message, reply, date) VALUES (?, ?, ?, ?)",
         (session["user"], msg, reply, date.today().isoformat())
         )
         conn.commit()
         conn.close()

         return {"reply": reply}

    # 🔑 API logic starts ONLY for POST
    else:
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
        return {"error": "API key missing"}, 401

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""SELECT users.username, users.plan FROM api_keys JOIN users ON api_keys.user = users.username
        WHERE api_keys.api_key=?""",(api_key,)
        )
        row = cur.fetchone()

    if not row:
        conn.close()
        return {"error": "Invalid API key"}, 401

    user, plan = row
    DAILY_LIMIT = 50 if plan == "FREE" else 1000

    from datetime import date
    today = date.today().isoformat()

    cur.execute(
        "SELECT count FROM api_usage WHERE api_key=? AND date=?",
        (api_key, today)
    )
    usage = cur.fetchone()

    if usage and usage[0] >= DAILY_LIMIT:
        conn.close()
        return {"error": "Daily limit reached"}, 429

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

    conn.commit()
    conn.close()

    data = request.get_json(silent=True) or {}
    message = data.get("message", "")

    return {
        "reply": f"Hello {user}, your message was received ✅",
        "plan": plan
    }

@app.route("/upgrade-ui", methods=["POST"])
def upgrade_ui():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE users SET plan='PRO' WHERE username=?",
        (session["user"],)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("auto_reply"))

@app.route("/upgrade", methods=["POST"])
def upgrade_plan():
    data = request.get_json()
    api_key = data.get("api_key")

    if not api_key:
        return {"error": "API key missing"}, 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user FROM api_keys WHERE api_key=?",
        (api_key,)
    )
    row = cur.fetchone()

    if not row:
        return {"error": "Invalid API key"}, 401

    user = row[0]

    cur.execute(
        "UPDATE users SET plan='PRO' WHERE username=?",
        (user,)
    )

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "plan": "PRO",
        "message": "Account upgraded successfully 🚀"
    }

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))
