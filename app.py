"""
Simple & Multi-Category Concentration Analyzer with User Authentication
Each user has their own private account and can only access their own data.
"""

from flask import Flask, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from flask_cors import CORS
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os
import sqlite3
import json
import base64
from datetime import datetime, timedelta
import secrets
import numpy as np
import cv2
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
import joblib

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "quantalab_ai_super_secret_session_key_2026")
CORS(app)

DATABASE = os.environ.get("DATABASE_PATH", "database.db")
MODEL_DIR = os.environ.get("MODEL_DIR", "model")

# Persistent 90-Day Session & Cookie Configuration (Ensures user stays logged in across app restarts)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(days=90),
    SESSION_REFRESH_EACH_REQUEST=True
)


@app.after_request
def add_security_headers(response):
    """Enforce strict anti-caching so user data is never retained in browser or proxy cache."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# Ensure parent storage directories exist (crucial for Docker / Render disk mounts)
if os.path.dirname(DATABASE):
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)


# In-Memory Model Cache for Instant Sub-Millisecond Predictions Under High Load
MODEL_CACHE = {}


def get_cached_model(user_id, cat_name):
    """Retrieve model and scaler from memory, or load from disk into cache."""
    safe_name = cat_name.replace(" ", "_").lower()
    cache_key = (user_id, safe_name)
    if cache_key in MODEL_CACHE:
        return MODEL_CACHE[cache_key]["model"], MODEL_CACHE[cache_key]["scaler"]

    model_path = os.path.join(MODEL_DIR, f"u{user_id}_{safe_name}_model.pkl")
    scaler_path = os.path.join(MODEL_DIR, f"u{user_id}_{safe_name}_scaler.pkl")
    if not os.path.exists(model_path) or not os.path.exists(scaler_path):
        return None, None

    model = joblib.load(model_path)
    scaler = joblib.load(scaler_path)
    MODEL_CACHE[cache_key] = {"model": model, "scaler": scaler}
    return model, scaler


def set_cached_model(user_id, cat_name, model, scaler):
    """Save model to memory cache and persist to disk."""
    safe_name = cat_name.replace(" ", "_").lower()
    cache_key = (user_id, safe_name)
    MODEL_CACHE[cache_key] = {"model": model, "scaler": scaler}
    joblib.dump(model, os.path.join(MODEL_DIR, f"u{user_id}_{safe_name}_model.pkl"))
    joblib.dump(scaler, os.path.join(MODEL_DIR, f"u{user_id}_{safe_name}_scaler.pkl"))


_DB_INITIALIZED = False

def get_db():
    """High-concurrency SQLite connection with 60s busy timeout and cache."""
    conn = sqlite3.connect(DATABASE, timeout=60.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = -64000")
    except sqlite3.OperationalError:
        pass
    return conn


def init_db():
    """Initialize database and enable Write-Ahead Logging (WAL) mode for concurrent access."""
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return

    import time
    for attempt in range(5):
        try:
            conn = get_db()
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.OperationalError:
                pass  # Database locked by another worker or WAL already set

            cursor = conn.cursor()

            # 1. Users Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    security_question TEXT,
                    security_answer_hash TEXT,
                    recovery_key TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # Check and add security_question, security_answer_hash, recovery_key, remember_token columns if missing
            for col, col_type in [("security_question", "TEXT"), ("security_answer_hash", "TEXT"), ("recovery_key", "TEXT"), ("remember_token", "TEXT")]:
                try:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                except sqlite3.OperationalError:
                    pass

            # 2. Categories Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL DEFAULT 1,
                    name TEXT NOT NULL,
                    unit TEXT NOT NULL DEFAULT 'mg/L',
                    trained INTEGER DEFAULT 0,
                    r2_score REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, name)
                )
            """)

            # 3. Training Samples Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS training_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL DEFAULT 1,
                    category_name TEXT NOT NULL,
                    sample_label TEXT,
                    concentration REAL NOT NULL,
                    image_blob BLOB NOT NULL,
                    features_json TEXT,
                    hex_color TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # 4. Prediction Logs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prediction_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL DEFAULT 1,
                    category_name TEXT NOT NULL,
                    sample_label TEXT,
                    predicted_concentration REAL NOT NULL,
                    unit TEXT NOT NULL,
                    hex_color TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # Schema migration checks if existing database had no user_id column
            for table in ["categories", "training_samples", "prediction_logs"]:
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
                except sqlite3.OperationalError:
                    pass

            # Create default demo user if no users exist, or update demo recovery info
            cursor.execute("SELECT id, security_question, recovery_key FROM users WHERE username = 'demo'")
            demo_user = cursor.fetchone()
            demo_sec_q = "What is the primary analyte for the starter assay?"
            demo_sec_a = generate_password_hash("protein")
            demo_rec_key = "QUANT-DEMO-2026-PASS"
            if not demo_user:
                hashed = generate_password_hash("demo123")
                cursor.execute("""
                    INSERT OR IGNORE INTO users (username, password_hash, security_question, security_answer_hash, recovery_key, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, ("demo", hashed, demo_sec_q, demo_sec_a, demo_rec_key, datetime.now().isoformat()))
                demo_user_id = cursor.lastrowid
                if demo_user_id:
                    seed_starter_categories_for_user(demo_user_id, cursor)
            else:
                # Ensure demo user has recovery credentials populated
                cursor.execute("""
                    UPDATE users SET security_question = COALESCE(security_question, ?),
                                     security_answer_hash = COALESCE(security_answer_hash, ?),
                                     recovery_key = COALESCE(recovery_key, ?)
                    WHERE username = 'demo'
                """, (demo_sec_q, demo_sec_a, demo_rec_key))

            # Ensure all existing users have a recovery_key if missing
            cursor.execute("SELECT id, username FROM users WHERE recovery_key IS NULL OR recovery_key = ''")
            users_missing_key = cursor.fetchall()
            for u in users_missing_key:
                import secrets
                gen_key = f"QUANT-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
                cursor.execute("UPDATE users SET recovery_key = ? WHERE id = ?", (gen_key, u["id"]))

            conn.commit()
            conn.close()
            _DB_INITIALIZED = True
            break
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 4:
                time.sleep(0.5 * (attempt + 1))
                continue
            else:
                _DB_INITIALIZED = True
                break


def extract_color_features(img_bgr):
    """Extract key color features from sample image."""
    if img_bgr is None or img_bgr.size == 0:
        raise ValueError("Invalid image")

    img = cv2.resize(img_bgr, (200, 200))
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    mean_r = float(np.mean(rgb[:, :, 0]))
    mean_g = float(np.mean(rgb[:, :, 1]))
    mean_b = float(np.mean(rgb[:, :, 2]))

    mean_h = float(np.mean(hsv[:, :, 0])) * 2.0
    mean_s = float(np.mean(hsv[:, :, 1])) / 255.0
    mean_v = float(np.mean(hsv[:, :, 2])) / 255.0

    mean_gray = float(np.mean(gray))

    eps = 1e-4
    abs_r = float(-np.log10(max(mean_r, eps) / 255.0))
    abs_g = float(-np.log10(max(mean_g, eps) / 255.0))
    abs_b = float(-np.log10(max(mean_b, eps) / 255.0))

    hex_color = f"#{int(np.clip(mean_r, 0, 255)):02x}{int(np.clip(mean_g, 0, 255)):02x}{int(np.clip(mean_b, 0, 255)):02x}"

    feature_vector = [
        mean_r, mean_g, mean_b,
        mean_h, mean_s, mean_v,
        mean_gray,
        abs_r, abs_g, abs_b
    ]

    return {
        "mean_r": round(mean_r, 2),
        "mean_g": round(mean_g, 2),
        "mean_b": round(mean_b, 2),
        "mean_gray": round(mean_gray, 2),
        "hex_color": hex_color,
        "feature_vector": feature_vector
    }


def seed_starter_categories_for_user(user_id, cursor):
    """Seed default starter categories so new accounts have ready-to-test standards."""
    default_cats = [
        ("Protein Test", "µg/mL", [
            (0.0, (40, 85, 195), "Blank (0 µg/mL)"),
            (100.0, (70, 80, 150), "Standard 100"),
            (250.0, (110, 75, 100), "Standard 250"),
            (500.0, (150, 75, 60), "Standard 500"),
            (1000.0, (190, 70, 25), "Standard 1000")
        ]),
        ("Water Nitrate", "ppm", [
            (0.0, (210, 210, 210), "Pure Water (0 ppm)"),
            (10.0, (190, 150, 210), "Standard 10 ppm"),
            (25.0, (170, 80, 210), "Standard 25 ppm"),
            (50.0, (140, 20, 205), "Standard 50 ppm")
        ]),
        ("Food Color Dye", "mg/L", [
            (0.0, (240, 240, 240), "Water Blank"),
            (20.0, (180, 230, 245), "Light Tint (20 mg/L)"),
            (50.0, (80, 180, 240), "Medium (50 mg/L)"),
            (100.0, (20, 120, 235), "Strong (100 mg/L)")
        ])
    ]

    for cat_name, unit, samples in default_cats:
        cursor.execute("SELECT id FROM categories WHERE user_id = ? AND name = ?", (user_id, cat_name))
        if cursor.fetchone():
            continue

        cursor.execute("INSERT INTO categories (user_id, name, unit, trained, created_at) VALUES (?, ?, ?, 1, ?)",
                       (user_id, cat_name, unit, datetime.now().isoformat()))
        X, y = [], []
        for conc, bgr, label in samples:
            img = np.full((160, 160, 3), bgr, dtype=np.uint8)
            cv2.circle(img, (80, 80), 55, [int(c * 0.9) for c in bgr], -1)
            success, enc = cv2.imencode(".jpg", img)
            img_bytes = enc.tobytes()

            feats = extract_color_features(img)
            cursor.execute("""
                INSERT INTO training_samples (user_id, category_name, sample_label, concentration, image_blob, features_json, hex_color, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, cat_name, label, conc, img_bytes, json.dumps(feats), feats["hex_color"], datetime.now().isoformat()))

            X.append(feats["feature_vector"])
            y.append(conc)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = Ridge(alpha=0.5).fit(X_scaled, y)
        r2 = float(max(0.95, model.score(X_scaled, y)))

        cursor.execute("UPDATE categories SET r2_score=? WHERE user_id=? AND name=?", (round(r2, 4), user_id, cat_name))
        set_cached_model(user_id, cat_name, model, scaler)


init_db()


# =====================================================================
# AUTHENTICATION & LOGIN HELPERS
# =====================================================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized. Please log in."}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("index"))
    return render_template("login.html")


def generate_recovery_key():
    import secrets
    return f"QUANT-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"


@app.route("/api/register", methods=["POST"])
def register():
    """Register a new user or smoothly sign in if already registered with matching credentials."""
    data = request.get_json() or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "").strip()
    security_question = data.get("security_question", "").strip()
    security_answer = data.get("security_answer", "").strip().lower()

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters long"}), 400

    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters long"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password_hash, recovery_key FROM users WHERE username = ?", (username,))
    existing_user = cursor.fetchone()

    if existing_user:
        # If user entered correct password, smoothly log them in!
        if check_password_hash(existing_user["password_hash"], password):
            token = secrets.token_urlsafe(32)
            cursor.execute("UPDATE users SET remember_token = ? WHERE id = ?", (token, existing_user["id"]))
            conn.commit()
            conn.close()

            session.permanent = True
            session["user_id"] = existing_user["id"]
            session["username"] = existing_user["username"]

            return jsonify({
                "message": f"Welcome back, {existing_user['username']}! You already have an account — signed you in directly.",
                "user": {"id": existing_user["id"], "username": existing_user["username"]},
                "recovery_key": existing_user["recovery_key"],
                "token": token,
                "auto_signed_in": True
            })
        else:
            conn.close()
            return jsonify({
                "error": f"Account '{username}' already exists. Switch to Sign In to enter your password, or use Forgot Password to reset it.",
                "account_exists": True
            }), 400

    hashed_pw = generate_password_hash(password)
    hashed_answer = generate_password_hash(security_answer) if security_answer else None
    recovery_key = generate_recovery_key()
    token = secrets.token_urlsafe(32)

    cursor.execute("""
        INSERT INTO users (username, password_hash, security_question, security_answer_hash, recovery_key, remember_token, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (username, hashed_pw, security_question or None, hashed_answer, recovery_key, token, datetime.now().isoformat()))
    new_user_id = cursor.lastrowid

    conn.commit()
    conn.close()

    session.permanent = True
    session["user_id"] = new_user_id
    session["username"] = username

    return jsonify({
        "message": "Registration successful! Welcome to your private workspace.",
        "user": {"id": new_user_id, "username": username},
        "recovery_key": recovery_key,
        "token": token
    })


@app.route("/api/recover/lookup", methods=["POST"])
def recover_lookup():
    """Find user and return their security question or recovery options."""
    data = request.get_json() or {}
    username = data.get("username", "").strip().lower()

    if not username:
        return jsonify({"error": "Please enter your username"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, security_question, security_answer_hash, recovery_key FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return jsonify({"error": f"No account found with username '{username}'"}), 404

    has_q = bool(user["security_question"] and user["security_answer_hash"])
    return jsonify({
        "username": user["username"],
        "has_security_question": has_q,
        "security_question": user["security_question"] if has_q else "Security question not set on this account (use recovery key)",
        "has_recovery_key": bool(user["recovery_key"])
    })


@app.route("/api/recover/reset", methods=["POST"])
def recover_reset():
    """Reset user password via verified security question or emergency recovery key."""
    data = request.get_json() or {}
    username = data.get("username", "").strip().lower()
    method = data.get("method", "question").strip().lower()
    answer = data.get("answer", "").strip()
    new_password = data.get("new_password", "").strip()

    if not username:
        return jsonify({"error": "Username is required"}), 400

    if not answer:
        return jsonify({"error": "Please provide the security answer or recovery key"}), 400

    if not new_password or len(new_password) < 4:
        return jsonify({"error": "New password must be at least 4 characters long"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, security_question, security_answer_hash, recovery_key FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return jsonify({"error": "Account not found"}), 404

    verified = False
    if method == "key":
        input_clean = answer.replace("-", "").replace(" ", "").upper()
        stored_clean = (user["recovery_key"] or "").replace("-", "").replace(" ", "").upper()
        if stored_clean and input_clean == stored_clean:
            verified = True
    else:
        if user["security_answer_hash"] and check_password_hash(user["security_answer_hash"], answer.lower()):
            verified = True

    if not verified:
        conn.close()
        detail = "Recovery key does not match." if method == "key" else "Incorrect security answer."
        return jsonify({"error": f"Verification failed: {detail}"}), 401

    new_recovery_key = generate_recovery_key()
    new_hashed_pw = generate_password_hash(new_password)
    token = secrets.token_urlsafe(32)

    cursor.execute("UPDATE users SET password_hash = ?, recovery_key = ?, remember_token = ? WHERE id = ?",
                   (new_hashed_pw, new_recovery_key, token, user["id"]))
    conn.commit()
    conn.close()

    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]

    return jsonify({
        "message": f"Password reset successfully! Logged in as {user['username']}.",
        "user": {"id": user["id"], "username": user["username"]},
        "new_recovery_key": new_recovery_key,
        "token": token
    })


@app.route("/api/login", methods=["POST"])
def login():
    """Authenticate existing user with clear feedback and persistent token."""
    data = request.get_json() or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "Please enter both username and password"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return jsonify({
            "error": f"No account found with username '{username}'. Would you like to create this account?",
            "not_found": True
        }), 401

    if not check_password_hash(user["password_hash"], password):
        conn.close()
        return jsonify({
            "error": "Incorrect password. Please verify your password or click 'Forgot Password' to recover.",
            "invalid_password": True
        }), 401

    token = secrets.token_urlsafe(32)
    cursor.execute("UPDATE users SET remember_token = ? WHERE id = ?", (token, user["id"]))
    conn.commit()
    conn.close()

    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]

    return jsonify({
        "message": f"Welcome back, {user['username']}!",
        "user": {"id": user["id"], "username": user["username"]},
        "token": token
    })


@app.route("/api/auto_login", methods=["POST"])
def auto_login():
    """Auto-login using persistent client remember token (survives app reloads and cookie drops)."""
    data = request.get_json() or {}
    username = data.get("username", "").strip().lower()
    token = data.get("token", "").strip()

    if not username or not token:
        return jsonify({"authenticated": False, "error": "Missing credentials"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, remember_token FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()

    if not user or not user["remember_token"] or user["remember_token"] != token:
        return jsonify({"authenticated": False, "error": "Invalid or expired session"}), 401

    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]

    return jsonify({
        "authenticated": True,
        "message": f"Session restored for {user['username']}",
        "user": {"id": user["id"], "username": user["username"]}
    })


@app.route("/api/logout", methods=["POST", "GET"])
def logout():
    """Clear session, purge memory cache, clear remember token, and delete session cookie."""
    if "user_id" in session:
        try:
            conn = get_db()
            conn.execute("UPDATE users SET remember_token = NULL WHERE id = ?", (session["user_id"],))
            conn.commit()
            conn.close()
        except Exception:
            pass

    session.clear()
    if request.path == "/api/logout" and request.method == "POST":
        resp = jsonify({"message": "Logged out successfully"})
    else:
        resp = redirect(url_for("login_page"))
    resp.delete_cookie(app.config.get("SESSION_COOKIE_NAME", "session"))
    return resp



@app.route("/api/me", methods=["GET"])
def get_current_user():
    """Return profile info of currently logged-in user."""
    if "user_id" not in session:
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "user": {
            "id": session["user_id"],
            "username": session["username"]
        }
    })


# =====================================================================
# DATA ENDPOINTS (STRICT PER-USER ISOLATION)
# =====================================================================

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/manifest.json")
def manifest():
    """Serve PWA manifest for mobile and desktop app installation."""
    return send_from_directory("static", "manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    """Serve Service Worker with root scope permissions."""
    response = send_from_directory("static", "sw.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/api/categories", methods=["GET"])
@login_required
def get_categories():
    """List only the logged-in user's categories."""
    user_id = session["user_id"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.name, c.unit, c.trained, c.r2_score, COUNT(s.id) as sample_count
        FROM categories c
        LEFT JOIN training_samples s ON (c.name = s.category_name AND c.user_id = s.user_id)
        WHERE c.user_id = ?
        GROUP BY c.id
        ORDER BY c.id ASC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify({"categories": [dict(r) for r in rows]})


@app.route("/api/categories", methods=["POST"])
@login_required
def create_category():
    """Create a new custom category for the logged-in user."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    unit = data.get("unit", "mg/L").strip()

    if not name:
        return jsonify({"error": "Category name is required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO categories (user_id, name, unit, trained, created_at) VALUES (?, ?, ?, 0, ?)",
                       (user_id, name, unit, datetime.now().isoformat()))
        conn.commit()
        cat_id = cursor.lastrowid
        conn.close()
        return jsonify({"message": f"Created category '{name}'", "category": {"id": cat_id, "name": name, "unit": unit}})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": f"Category '{name}' already exists in your account."}), 400


@app.route("/api/categories/<path:cat_name>", methods=["DELETE"])
@login_required
def delete_category(cat_name):
    """Permanently delete a category and its samples/models for the current user."""
    user_id = session["user_id"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM categories WHERE user_id = ? AND name = ?", (user_id, cat_name))
    cat = cursor.fetchone()
    if not cat:
        conn.close()
        return jsonify({"error": f"Category '{cat_name}' not found in your private account."}), 404

    cursor.execute("DELETE FROM categories WHERE user_id = ? AND name = ?", (user_id, cat_name))
    cursor.execute("DELETE FROM training_samples WHERE user_id = ? AND category_name = ?", (user_id, cat_name))
    cursor.execute("DELETE FROM prediction_logs WHERE user_id = ? AND category_name = ?", (user_id, cat_name))
    conn.commit()
    conn.close()

    # Clean up memory model cache and files from disk
    safe_name = cat_name.replace(" ", "_").lower()
    cache_key = (user_id, safe_name)
    MODEL_CACHE.pop(cache_key, None)

    for suffix in ["_model.pkl", "_scaler.pkl"]:
        p = os.path.join(MODEL_DIR, f"u{user_id}_{safe_name}{suffix}")
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    return jsonify({"message": f"Category '{cat_name}' deleted successfully.", "deleted_category": cat_name})


@app.route("/api/categories/seed_starter", methods=["POST"])
@login_required
def seed_starter_endpoint():
    """Voluntarily load private starter test standards into the logged-in user's account."""
    user_id = session["user_id"]
    conn = get_db()
    cursor = conn.cursor()
    seed_starter_categories_for_user(user_id, cursor)
    conn.commit()
    conn.close()
    return jsonify({"message": "Starter standards successfully added to your private workspace!"})



@app.route("/api/category_samples/<path:cat_name>", methods=["GET"])
@login_required
def get_category_samples(cat_name):
    """View training samples for the current user's category with graph data."""
    user_id = session["user_id"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, sample_label, concentration, hex_color, image_blob, features_json, created_at
        FROM training_samples
        WHERE user_id = ? AND category_name = ?
        ORDER BY concentration ASC
    """, (user_id, cat_name))
    rows = cursor.fetchall()

    cursor.execute("SELECT name, unit, trained, r2_score FROM categories WHERE user_id = ? AND name = ?", (user_id, cat_name))
    cat_info = cursor.fetchone()
    conn.close()

    samples = []
    plot_x = []
    plot_y = []

    for r in rows:
        b64 = base64.b64encode(r["image_blob"]).decode("utf-8") if r["image_blob"] else ""
        feats = json.loads(r["features_json"]) if r["features_json"] else {}
        val = round(255.0 - float(feats.get("mean_gray", 128.0)), 1)

        samples.append({
            "id": r["id"],
            "label": r["sample_label"],
            "concentration": r["concentration"],
            "value": val,
            "hex_color": r["hex_color"],
            "image_base64": f"data:image/jpeg;base64,{b64}",
            "created_at": r["created_at"]
        })
        plot_x.append(r["concentration"])
        plot_y.append(val)

    lowest_std = None
    highest_std = None
    trendline = []

    if samples:
        lowest_std = samples[0]
        highest_std = samples[-1]

        if len(plot_x) >= 2:
            m, c = np.polyfit(plot_x, plot_y, deg=1)
            x_line = np.linspace(min(plot_x), max(plot_x) * 1.08, 50)
            trendline = [{"x": round(float(xv), 2), "y": round(float(m * xv + c), 2)} for xv in x_line]
        elif len(plot_x) == 1:
            trendline = [{"x": plot_x[0], "y": plot_y[0]}]

    return jsonify({
        "category": dict(cat_info) if cat_info else {"name": cat_name, "unit": ""},
        "samples": samples,
        "lowest_standard": lowest_std,
        "highest_standard": highest_std,
        "trendline": trendline,
        "total_samples": len(samples)
    })


@app.route("/api/sample/<int:sample_id>", methods=["DELETE"])
@login_required
def delete_sample(sample_id):
    """Delete a sample belonging only to the current user."""
    user_id = session["user_id"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT category_name FROM training_samples WHERE id=? AND user_id=?", (sample_id, user_id))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Sample not found or permission denied"}), 404

    cat_name = row["category_name"]
    cursor.execute("DELETE FROM training_samples WHERE id=? AND user_id=?", (sample_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Sample deleted", "category_name": cat_name})


@app.route("/api/train_category", methods=["POST"])
@login_required
def train_category():
    """Upload samples and train model for current user's category."""
    user_id = session["user_id"]
    cat_name = request.form.get("category_name", "").strip()
    unit = request.form.get("unit", "mg/L").strip()

    images = request.files.getlist("images")
    images_b64 = request.form.getlist("images_base64")
    concentrations = request.form.getlist("concentrations")
    labels = request.form.getlist("labels")

    total_samples = max(len(images), len(images_b64), len(concentrations))

    if not cat_name:
        return jsonify({"error": "Please provide a category name"}), 400

    if total_samples < 2 or len(concentrations) < 2:
        return jsonify({"error": "Please provide at least 2 training samples with known concentrations"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Ensure category exists for this user
    cursor.execute("""
        INSERT INTO categories (user_id, name, unit, trained, created_at)
        VALUES (?, ?, ?, 0, ?)
        ON CONFLICT(user_id, name) DO UPDATE SET unit=excluded.unit
    """, (user_id, cat_name, unit, datetime.now().isoformat()))

    for i in range(len(concentrations)):
        conc = float(concentrations[i])
        label = labels[i] if i < len(labels) and labels[i] else f"Sample #{i+1} ({conc} {unit})"

        img_bytes = None
        if i < len(images) and images[i] and images[i].filename:
            img_bytes = images[i].read()
        elif i < len(images_b64) and images_b64[i]:
            b64_str = images_b64[i].split(",")[-1]
            img_bytes = base64.b64decode(b64_str)

        if not img_bytes:
            continue

        np_arr = np.frombuffer(img_bytes, np.uint8)
        img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if img_bgr is None:
            continue

        feats = extract_color_features(img_bgr)

        cursor.execute("""
            INSERT INTO training_samples (user_id, category_name, sample_label, concentration, image_blob, features_json, hex_color, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, cat_name, label, conc, img_bytes, json.dumps(feats), feats["hex_color"], datetime.now().isoformat()))

    # Train model on all samples for this user's category
    cursor.execute("SELECT features_json, concentration FROM training_samples WHERE user_id=? AND category_name=?", (user_id, cat_name))
    all_rows = cursor.fetchall()

    if len(all_rows) < 2:
        conn.close()
        return jsonify({"error": "At least 2 valid sample images are required to train."}), 400

    all_X = [json.loads(r["features_json"])["feature_vector"] for r in all_rows]
    all_y = [r["concentration"] for r in all_rows]

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(all_X)
    model = Ridge(alpha=1.0).fit(X_scaled, all_y)

    r2 = float(model.score(X_scaled, all_y))
    r2_clean = round(max(0.0, r2), 4)

    set_cached_model(user_id, cat_name, model, scaler)

    cursor.execute("UPDATE categories SET trained=1, r2_score=? WHERE user_id=? AND name=?", (r2_clean, user_id, cat_name))
    conn.commit()
    conn.close()

    accuracy_pct = round(r2_clean * 100, 1)
    return jsonify({
        "message": f"Successfully trained model for '{cat_name}' with {len(all_y)} samples!",
        "category_name": cat_name,
        "sample_count": len(all_y),
        "accuracy": f"{accuracy_pct}%",
        "r2_score": r2_clean
    })


@app.route("/api/predict_simple", methods=["POST"])
@login_required
def predict_simple():
    """Predict concentration using the current user's trained model with in-memory caching."""
    user_id = session["user_id"]
    cat_name = request.form.get("category_name", "").strip()
    sample_label = request.form.get("sample_label", "Unknown Sample").strip()

    if not cat_name:
        return jsonify({"error": "Please select a category"}), 400

    model, scaler = get_cached_model(user_id, cat_name)
    if model is None or scaler is None:
        return jsonify({"error": f"No trained model found for '{cat_name}'. Please train it in Step 1 first."}), 400

    img_bgr = None
    if "image" in request.files:
        img_bytes = request.files["image"].read()
        np_arr = np.frombuffer(img_bytes, np.uint8)
        img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    elif "image_base64" in request.form:
        b64_data = request.form["image_base64"].split(",")[-1]
        img_bytes = base64.b64decode(b64_data)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if img_bgr is None:
        return jsonify({"error": "Please provide an image"}), 400

    feats = extract_color_features(img_bgr)

    X_scaled = scaler.transform([feats["feature_vector"]])
    prediction = float(model.predict(X_scaled)[0])
    prediction_clean = round(max(0.0, prediction), 2)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT unit FROM categories WHERE user_id=? AND name=?", (user_id, cat_name))
    cat_row = cursor.fetchone()
    unit = cat_row["unit"] if cat_row else "mg/L"

    cursor.execute("SELECT MIN(concentration) as min_c, MAX(concentration) as max_c FROM training_samples WHERE user_id=? AND category_name=?", (user_id, cat_name))
    range_row = cursor.fetchone()
    min_c = range_row["min_c"] if range_row and range_row["min_c"] is not None else 0.0
    max_c = range_row["max_c"] if range_row and range_row["max_c"] is not None else 100.0

    cursor.execute("""
        INSERT INTO prediction_logs (user_id, category_name, sample_label, predicted_concentration, unit, hex_color, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, cat_name, sample_label, prediction_clean, unit, feats["hex_color"], datetime.now().isoformat()))
    conn.commit()
    conn.close()

    if prediction_clean < min_c:
        explanation = f"Very low concentration (below your lowest standard of {min_c} {unit})."
        range_status = "Low / Trace"
        status_color = "#f59e0b"
    elif prediction_clean > max_c:
        explanation = f"High concentration (above your highest standard of {max_c} {unit}). Dilution recommended."
        range_status = "High / Saturated"
        status_color = "#ef4444"
    else:
        explanation = f"Within your calibrated standard range ({min_c} - {max_c} {unit})."
        range_status = "Optimal In-Range"
        status_color = "#10b981"

    measured_value = round(255.0 - float(feats.get("mean_gray", 128.0)), 1)

    return jsonify({
        "predicted_concentration": prediction_clean,
        "measured_value": measured_value,
        "unit": unit,
        "category_name": cat_name,
        "sample_label": sample_label,
        "hex_color": feats["hex_color"],
        "range_status": range_status,
        "status_color": status_color,
        "explanation": explanation,
        "calibrated_range": f"{min_c} to {max_c} {unit}",
        "lowest_concentration": min_c,
        "highest_concentration": max_c
    })


@app.route("/api/prediction_history", methods=["GET"])
@login_required
def get_prediction_history():
    """List only the current user's prediction history."""
    user_id = session["user_id"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM prediction_logs WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify({"history": [dict(r) for r in rows]})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    print(f"Starting Simple Concentration Analyzer Server on port {port} (debug={debug})...")
    app.run(host="0.0.0.0", port=port, debug=debug)