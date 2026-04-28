"""
SOURCE v2.1 — Security Utilities
=================================
✅ bcrypt for password hashing
✅ secrets for token generation
✅ HMAC for admin signature
✅ Input validation
"""
import re
import secrets
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Tuple, Optional

import bcrypt
from fastapi import Request
from sqlalchemy import text

from app.core.config import cfg

# === Password Hashing ===
def hash_pw(password: str) -> str:
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_pw(password: str, hashed: str) -> bool:
    """Verify password against bcrypt hash"""
    return bcrypt.checkpw(password.encode(), hashed.encode())

# === Token Generation ===
def make_token(length: int = 32) -> str:
    """Generate cryptographically secure random token"""
    return secrets.token_urlsafe(length)

def make_sig(subject: str, secret: str) -> str:
    """Generate HMAC signature for admin"""
    return hmac.new(
        cfg.SECRET_KEY.encode(),
        f"{subject}:{secret}".encode(),
        hashlib.sha256
    ).hexdigest()

def verify_sig(subject: str, secret: str, sig: str) -> bool:
    """Verify HMAC signature"""
    return hmac.compare_digest(make_sig(subject, secret), sig)

# === Input Validation ===
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

def validate_email(email: str) -> bool:
    """Validate email format"""
    return bool(email and EMAIL_REGEX.match(email.strip().lower()))

def validate_password(password: str) -> Tuple[bool, str]:
    """Validate password strength"""
    if len(password) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères."
    if not re.search(r'[A-Z]', password):
        return False, "Le mot de passe doit contenir au moins une majuscule."
    if not re.search(r'[a-z]', password):
        return False, "Le mot de passe doit contenir au moins une minuscule."
    if not re.search(r'\d', password):
        return False, "Le mot de passe doit contenir au moins un chiffre."
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Le mot de passe doit contenir au moins un caractère spécial."
    return True, ""

# === Member Helpers ===
def get_member(req: Request) -> Optional[dict]:
    """Get current member from session cookie"""
    token = req.cookies.get("_session", "")
    if not token:
        return None

    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT * FROM members WHERE session_token=:token AND actif=1"),
            {"token": token}
        ).fetchone()
        return dict(row) if row else None
    finally:
        db.close()

def is_admin(req: Request) -> bool:
    """Check if request is from admin"""
    sig = req.cookies.get("_admin", "")
    if not sig or not cfg.ADMIN_PASS:
        return False
    return verify_sig("admin", cfg.ADMIN_PASS, sig)

def days_left(date_str: str) -> Tuple[int, str]:
    """Calculate days left until deadline"""
    if not date_str:
        return (999, "—")
    try:
        dl = datetime.strptime(date_str, "%Y-%m-%d")
        delta = (dl - datetime.now()).days
        if delta < 0:
            return (delta, "Expiré")
        elif delta <= 3:
            return (delta, f"{delta}j — Urgent")
        elif delta <= 7:
            return (delta, f"{delta}j")
        else:
            return (delta, f"{delta}j")
    except ValueError:
        return (999, "—")

def is_plan_ok(member: dict, required: str) -> bool:
    """Check if member plan meets requirement"""
    if not member:
        return False
    plan = member.get("plan", "free")
    hierarchy = {"free": 0, "essentiel": 1, "pro": 2, "unlimited": 3}
    req_level = {"free": 0, "essentiel": 1, "pro": 2, "unlimited": 3, "api": 2}
    return hierarchy.get(plan, 0) >= req_level.get(required, 0)

def compute_relevance_score(tender: dict, member_codes: list, member_regions: list) -> int:
    """Compute relevance score for a tender"""
    score = 0
    if tender.get("stx10_code") in member_codes:
        score += 50
    if any(r in (tender.get("region", "") or "") for r in member_regions):
        score += 30
    dl = days_left(tender.get("date_limite", ""))[0]
    if 0 <= dl <= 7:
        score += 20
    return min(score, 100)

def send_reset_email(email: str, token: str) -> bool:
    """Send password reset email"""
    import smtplib
    from email.mime.text import MIMEText

    if not all([cfg.SMTP_HOST, cfg.SMTP_USER, cfg.SMTP_PASS]):
        return False

    try:
        reset_url = f"{cfg.SITE_URL}/reset?token={token}"
        msg = MIMEText(f"""
Bonjour,

Cliquez sur ce lien pour réinitialiser votre mot de passe SOURCE :
{reset_url}

Ce lien expire dans 2 heures.

SOURCE — Marchés Publics Maroc
        """, "plain", "utf-8")
        msg["Subject"] = "Réinitialisation de mot de passe SOURCE"
        msg["From"] = cfg.SMTP_FROM
        msg["To"] = email

        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT) as server:
            server.starttls()
            server.login(cfg.SMTP_USER, cfg.SMTP_PASS)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[send_reset_email] {e}")
        return False
