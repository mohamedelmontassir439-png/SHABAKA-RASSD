import bcrypt, hashlib, secrets, re, smtplib
from datetime import datetime, date, timedelta
from typing import Optional
from email.mime.text import MIMEText
from fastapi import Request
from app.core.config import cfg
from app.core.database import get_db

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_pw(pw: str, hashed: str) -> bool:
    try: return bcrypt.checkpw(pw.encode(), hashed.encode())
    except: return False

def make_token(length: int = 40) -> str:
    return secrets.token_urlsafe(length)

def make_sig(val: str, salt: str = "") -> str:
    key = cfg.SECRET_KEY or "source_fallback_2026"
    return hashlib.sha256(f"{val}{salt}{key}".encode()).hexdigest()[:40]

def get_member(req: Request) -> Optional[dict]:
    token = req.cookies.get("_session","")
    if not token or len(token) < 10: return None
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM members WHERE actif=1 AND session_token=?", (token,)
        ).fetchone()
        return dict(row) if row else None
    except: return None
    finally: db.close()

def is_admin(req: Request) -> bool:
    return req.cookies.get("_admin","") == make_sig("admin", cfg.ADMIN_PASS)

def validate_email(e: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', e))

def validate_password(pw: str) -> tuple:
    if len(pw) < 8: return False, "Au moins 8 caractères"
    return True, ""

def days_left(dl: str) -> tuple:
    if not dl or str(dl).strip() in ("","N/A","—","-"): return 999, ""
    m = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', str(dl))
    if not m: return 999, ""
    try:
        fmt = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
        d = datetime.strptime(m.group(1), fmt).date()
        delta = (d - date.today()).days
        if delta < 0:  return delta, "Expiré"
        if delta == 0: return 0,     "Aujourd'hui!"
        if delta == 1: return 1,     "Demain"
        if delta <= 3: return delta, f"{delta}j 🔥"
        if delta <= 7: return delta, f"{delta}j ⏳"
        return delta, f"{delta} jours"
    except: return 999, ""

def is_plan_ok(member: dict, feature: str) -> bool:
    p = cfg.PLANS.get(member.get("plan","free"), cfg.PLANS["free"])
    if feature == "unlimited": return p.get("limit",10) == 0
    if feature == "telegram":  return p.get("telegram", False)
    if feature == "api":       return p.get("api", False)
    return False

def send_reset_email(email: str, token: str) -> bool:
    link = f"{cfg.SITE_URL}/reset?token={token}"
    body = f"""Bonjour,

Cliquez sur ce lien pour réinitialiser votre mot de passe SOURCE:
{link}

Ce lien expire dans 2 heures.
Si vous n'avez pas demandé cette réinitialisation, ignorez cet email.

SOURCE — Marchés Publics Maroc"""
    try:
        if cfg.GMAIL_USER and cfg.GMAIL_PASS:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = "Réinitialisation mot de passe SOURCE"
            msg["From"]    = cfg.GMAIL_USER
            msg["To"]      = email
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(cfg.GMAIL_USER, cfg.GMAIL_PASS)
                s.send_message(msg)
            return True
        if cfg.BREVO_KEY:
            import requests as rq
            rq.post("https://api.brevo.com/v3/smtp/email",
                headers={"api-key":cfg.BREVO_KEY,"Content-Type":"application/json"},
                json={"sender":{"name":"SOURCE","email":cfg.FROM_EMAIL},
                      "to":[{"email":email}],
                      "subject":"Réinitialisation mot de passe SOURCE",
                      "textContent":body}, timeout=15)
            return True
    except: pass
    return False

def compute_relevance_score(tender: dict, member_codes: list, member_regions: list) -> int:
    """Score de pertinence 1-5 étoiles basé sur le profil du membre"""
    score = 1
    if not member_codes and not member_regions:
        return 3  # score neutre si pas de profil

    # +2 si code STX10 correspond exactement
    if tender.get("stx10_code","") in member_codes:
        score += 2
    # +1 si même famille de code (T1xx)
    elif member_codes:
        tc = tender.get("stx10_code","")
        if any(tc[:2] == mc[:2] for mc in member_codes):
            score += 1

    # +1 si région correspond
    if member_regions and tender.get("region",""):
        if any(r.lower() in tender.get("region","").lower() for r in member_regions):
            score += 1

    # +1 si délai raisonnable (> 7 jours)
    n, _ = days_left(tender.get("date_limite",""))
    if 7 < n < 60:
        score += 1

    return min(5, max(1, score))
