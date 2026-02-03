from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import secrets
from datetime import date

def init_db():
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

app = Flask(__name__)
app.secret_key = "supersecretkey"  # required for sessions

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
        cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        cur.execute("INSERT INTO api_keys (user, api_key) VALUES (?, ?)",(username, api_key))
        conn.commit()
        conn.close()

        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/auto-reply", methods=["GET", "POST"])
def auto_reply():
    # If not logged in and trying to open page → go to login
    if "user" not in session and request.method == "GET":
        return redirect(url_for("login"))

    # Show page in browser
    if request.method == "GET":
        return render_template("auto_reply.html")

    # API request (POST)
    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        return {"error": "API key missing"}, 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user, plan FROM api_keys WHERE api_key=?",
        (api_key,)
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        return {"error": "Invalid API key"}, 401

    user, plan = row

    from datetime import date
    today = date.today().isoformat()
    DAILY_LIMIT = 50 if plan == "FREE" else 1000

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

    return {
        "reply": f"Hello {user}, your message was received ✅",
        "plan": plan
    }

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


if __name__ == "__main__":
    app.run(debug=True)