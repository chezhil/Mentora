"""Authentication and User Persistence Module for Mentora Web.

Handles:
- User creation, password hashing with PBKDF2-HMAC-SHA256 and cryptographic salts
- Authentication / credential verification
- Password reset token generation and verification
- In-memory session tracking for web sessions
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "mentora.db"

# In-memory session store: session_token -> user dict
SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_EXPIRY_SECONDS = 86400 * 7  # 7 days


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db() -> None:
    """Initialize the users table in mentora.db if not already present."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            created_at TEXT NOT NULL,
            reset_token TEXT,
            reset_token_expiry REAL
        )
        """)
        conn.commit()

        # Seed default test accounts if users table is empty
        cur.execute("SELECT COUNT(*) as count FROM users")
        row = cur.fetchone()
        if row and row["count"] == 0:
            _seed_defaults(conn)
    finally:
        conn.close()


def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hashes a password using PBKDF2-HMAC-SHA256 with 100,000 iterations."""
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return dk.hex(), salt


def _verify_password(password: str, salt: str, expected_hash: str) -> bool:
    dk, _ = _hash_password(password, salt)
    return hmac.compare_digest(dk, expected_hash)


def _seed_defaults(conn: sqlite3.Connection) -> None:
    """Creates default student and teacher accounts for demo/testing."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()

    # Default student: student@mentora.ai / mentora123
    s_hash, s_salt = _hash_password("mentora123")
    cur.execute("""
    INSERT OR IGNORE INTO users (email, username, password_hash, salt, role, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, ("student@mentora.ai", "student", s_hash, s_salt, "student", now))

    # Default teacher: teacher@mentora.ai / teacher123
    t_hash, t_salt = _hash_password("teacher123")
    cur.execute("""
    INSERT OR IGNORE INTO users (email, username, password_hash, salt, role, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, ("teacher@mentora.ai", "teacher", t_hash, t_salt, "teacher", now))

    conn.commit()


def create_user(email: str, username: str, password: str, role: str = "student") -> dict:
    """Register a new user account. Raises ValueError on duplicate or invalid input."""
    email = email.strip().lower()
    username = username.strip()
    role = role.strip().lower()
    if role not in ("student", "teacher"):
        role = "student"

    if not email or "@" not in email:
        raise ValueError("A valid email address is required.")
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters long.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")

    pw_hash, salt = _hash_password(password)
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO users (email, username, password_hash, salt, role, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (email, username, pw_hash, salt, role, now))
        conn.commit()
        user_id = cur.lastrowid
        return {
            "id": user_id,
            "email": email,
            "username": username,
            "role": role,
            "created_at": now,
        }
    except sqlite3.IntegrityError as e:
        err_msg = str(e).lower()
        if "email" in err_msg:
            raise ValueError("An account with this email already exists.")
        if "username" in err_msg:
            raise ValueError("An account with this username already exists.")
        raise ValueError("User already exists.")
    finally:
        conn.close()


def authenticate_user(login_identifier: str, password: str) -> Optional[dict]:
    """Authenticates by email or username. Returns user dict on success, None on failure."""
    login_identifier = login_identifier.strip().lower()
    if not login_identifier or not password:
        return None

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
        SELECT id, email, username, password_hash, salt, role, created_at
        FROM users
        WHERE email = ? OR username = ?
        """, (login_identifier, login_identifier))
        row = cur.fetchone()
        if not row:
            return None

        if _verify_password(password, row["salt"], row["password_hash"]):
            return {
                "id": row["id"],
                "email": row["email"],
                "username": row["username"],
                "role": row["role"],
                "created_at": row["created_at"],
            }
        return None
    finally:
        conn.close()


MAX_SESSIONS = 5000


def _purge_sessions() -> None:
    """Drop expired tokens, and cap the table.

    Sessions are only ever removed when someone logs out or when an expired
    token is presented again -- a token nobody touches again sits in memory
    until the process restarts, so the dict grows with every login for the
    life of the server. Expiry is cheap to enforce here.
    """
    now = time.time()
    for token in [t for t, s in SESSIONS.items() if now > s["expires_at"]]:
        SESSIONS.pop(token, None)
    if len(SESSIONS) > MAX_SESSIONS:
        oldest = sorted(SESSIONS.items(), key=lambda kv: kv[1]["created_at"])
        for token, _ in oldest[:len(SESSIONS) - MAX_SESSIONS]:
            SESSIONS.pop(token, None)


def create_session(user: dict) -> str:
    """Creates a session token for the user."""
    _purge_sessions()
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {
        "user": user,
        "created_at": time.time(),
        "expires_at": time.time() + SESSION_EXPIRY_SECONDS,
    }
    return token


def get_session_user(token: Optional[str]) -> Optional[dict]:
    """Returns the user dict associated with a valid session token."""
    if not token or token not in SESSIONS:
        return None
    sess = SESSIONS[token]
    if time.time() > sess["expires_at"]:
        SESSIONS.pop(token, None)
        return None
    return sess["user"]


def revoke_session(token: Optional[str]) -> None:
    """Removes a session token."""
    if token:
        SESSIONS.pop(token, None)


def generate_reset_token(email: str) -> Optional[str]:
    """Generates a password reset token for the given email, valid for 1 hour."""
    email = email.strip().lower()
    token = secrets.token_hex(4).upper()  # 8-character easy recovery code e.g. 7F3A29B1
    expiry = time.time() + 3600  # 1 hour

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        if not cur.fetchone():
            return None

        cur.execute("""
        UPDATE users
        SET reset_token = ?, reset_token_expiry = ?
        WHERE email = ?
        """, (token, expiry, email))
        conn.commit()
        return token
    finally:
        conn.close()


def reset_password(email: str, token: str, new_password: str) -> bool:
    """Resets password if token is valid and not expired."""
    email = email.strip().lower()
    token = token.strip().upper()
    if len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters long.")

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
        SELECT id, reset_token, reset_token_expiry
        FROM users
        WHERE email = ?
        """, (email,))
        row = cur.fetchone()
        if not row or not row["reset_token"]:
            return False

        if row["reset_token"] != token:
            return False

        if time.time() > (row["reset_token_expiry"] or 0):
            return False

        pw_hash, salt = _hash_password(new_password)
        cur.execute("""
        UPDATE users
        SET password_hash = ?, salt = ?, reset_token = NULL, reset_token_expiry = NULL
        WHERE email = ?
        """, (pw_hash, salt, email))
        conn.commit()
        return True
    finally:
        conn.close()
