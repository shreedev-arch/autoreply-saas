from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import secrets
from datetime import date
import os
import razorpay
import hmac
import hashlib
import json

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")

razorpay_client = razorpay.Client(auth=(
    os.getenv("RAZORPAY_KEY_ID"),
    os.getenv("RAZORPAY_KEY_SECRET")
))

# ---------------- DB ----------------
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

# ---------------- AUTH ----------------
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
            return redirect(url_for("dashboard"))

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        api_key = secrets.token_hex(16)

        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )
            cur.execute(
                "INSERT INTO api_keys (user, api_key) VALUES (?, ?)",
                (username, api_key)
            )
            conn.commit()
        except:
            conn.close()
            return "User already exists"

        conn.close()
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT api_keys.api_key, users.plan FROM users JOIN api_keys ON users.username = api_keys.user WHERE users.username=?",
        (session["user"],)
    )
    api_key, plan = cur.fetchone()

    cur.execute(
        "SELECT message, reply FROM messages WHERE user=? ORDER BY id DESC LIMIT 10",
        (session["user"],)
    )
    history = cur.fetchall()

    conn.close()

    return render_template(
        "auto_reply.html",
        api_key=api_key,
        plan=plan,
        history=history,
        razorpay_key_id=os.getenv("RAZORPAY_KEY_ID")
    )

# ---------------- API AUTO REPLY ----------------
@app.route("/api/auto-reply", methods=["POST"])
def api_auto_reply():

    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        return {"error": "API key missing"}, 401

    conn = get_db()
    cur = conn.cursor()

    # Get user + plan
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
    today = date.today().isoformat()

    # ===== PLAN LIMIT CONTROL =====
    # FREE → 50/day
    # PRO → 1000/day
    DAILY_LIMIT = 50 if plan == "FREE" else 1000

    # Check usage
    cur.execute(
        "SELECT count FROM api_usage WHERE api_key=? AND date=?",
        (api_key, today)
    )
    usage = cur.fetchone()

    if usage and usage[0] >= DAILY_LIMIT:
        conn.close()
        return {
            "error": "Daily limit reached. Upgrade to PRO 🚀"
        }, 429

    # Update usage
    if usage:
        cur.execute(
            "UPDATE api_usage SET count = count + 1 WHERE api_key=? AND date=?",
            (api_key, today)
        )
    else:
        cur.execute(
            "INSERT INTO api_usage VALUES (NULL, ?, ?, 1)",
            (api_key, today)
        )

    # Get message
    data = request.get_json()
    message = data.get("message", "").strip()

    if not message:
        conn.close()
        return {"error": "Empty message"}, 400

    # Bot reply
    reply = f"Hello {user}, message received ✅"

    # Save message + reply
    cur.execute(
        "INSERT INTO messages VALUES (NULL, ?, ?, ?, ?)",
        (user, message, reply, today)
    )

    conn.commit()
    conn.close()

    return {
        "reply": reply,
        "plan": plan,
        "daily_limit": DAILY_LIMIT
    }

# ---------------- RAZORPAY ORDER ----------------
@app.route("/create-order", methods=["POST"])
def create_order():
    if "user" not in session:
        return {"error": "Unauthorized"}, 401

    order = razorpay_client.order.create({
        "amount": 100,  # ₹1
        "currency": "INR",
        "payment_capture": 1,
        "notes": {
            "username": session["user"]
        }
    })

    return jsonify(order)

# ---------------- WEBHOOK ----------------
@app.route("/razorpay-webhook", methods=["POST"])
def razorpay_webhook():
    payload = request.data
    received_signature = request.headers.get("X-Razorpay-Signature")
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")

    expected_signature = hmac.new(
        bytes(secret, "utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, received_signature):
        return "Invalid signature", 400

    data = json.loads(payload)

    if data.get("event") == "payment.captured":
        username = (
            data.get("payload", {})
                .get("payment", {})
                .get("entity", {})
                .get("notes", {})
                .get("username")
        )

        if username:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET plan='PRO' WHERE username=?",
                (username,)
            )
            conn.commit()
            conn.close()

    return "OK", 200  
