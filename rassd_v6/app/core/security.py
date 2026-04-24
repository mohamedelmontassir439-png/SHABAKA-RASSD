import bcrypt, hashlib, secrets, re
from datetime import datetime, date, timedelta
from typing import Optional
from fastapi import Request, HTTPException
from app.core.config import cfg
from app.core.database import get_db

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_pw(pw: str, hashed: str) -> bool:
    try: return bcrypt.checkpw(pw.encode(), hashed.encode())
    except: return False

def make_token(val: str, salt: str = "") -> str:
    """Token stable — SECRET_KEY doit être fixé dans Railway Variables"""
    key = cfg.SECRET_KEY
    if not key or len(key) < 20:
        import logging
        logging.getLogger("atlas.security").critical(
            "⚠️ SECRET_KEY non défini ou trop court! Définissez-le dans Railway Variables.")
        key = "atlas_pro_emergency_" + hashlib.sha256(b"atlas2026").hexdigest()[:20]
    return hashlib.sha256(f"{val}{salt}{key}".encode()).hexdigest()[:40]

def make_random_token() -> str:
    return secrets.token_urlsafe(32)

def make_session_token() -> str:
    """Token aléatoire stocké en DB — indépendant du SECRET_KEY"""
    return secrets.token_urlsafe(40)

def get_member(req: Request) -> Optional[dict]:
    token = req.cookies.get("_session", "")
    if not token or len(token) < 10: return None
    db = get_db()
    try:
        # Method 1: Direct DB token lookup (fast, no SECRET_KEY dependency)
        row = db.execute(
            "SELECT * FROM members WHERE actif=1 AND session_token=?",
            (token,)
        ).fetchone()
        if row:
            return dict(row)
        # Method 2: Fallback - computed token (backward compat)
        rows = db.execute("SELECT * FROM members WHERE actif=1").fetchall()
        for row in rows:
            if make_token(row["email"], row["created_at"]) == token:
                # Migrate: store token in DB
                db.execute("UPDATE members SET session_token=? WHERE id=?",
                          (token, row["id"]))
                db.commit()
                return dict(row)
    except Exception as e:
        import logging
        logging.getLogger("atlas.security").error(f"[get_member] {e}")
    finally:
        db.close()
    return None

def require_member(req: Request) -> dict:
    m = get_member(req)
    if not m:
        from fastapi.responses import RedirectResponse
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return m

def require_admin(req: Request):
    cookie = req.cookies.get("_admin", "")
    if cookie != make_token("admin", cfg.ADMIN_PASS):
        from fastapi.responses import RedirectResponse
        raise HTTPException(status_code=307, headers={"Location": "/admin/login"})

def validate_email(email: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email))

def validate_password(pw: str) -> tuple[bool, str]:
    if len(pw) < 8: return False, "Au moins 8 caractères"
    return True, ""

def is_plan_allowed(member: dict, feature: str) -> bool:
    plan = member.get("plan", "free")
    plans = cfg.PLANS
    p = plans.get(plan, plans["free"])
    if feature == "telegram": return p.get("telegram", False)
    if feature == "api":      return p.get("api", False)
    if feature == "tenders":
        limit = p.get("tenders_day", 15)
        return limit == 0  # 0 = unlimited
    return False

def days_left(dl: str):
    """Retourne (nb_jours: int, label: str)"""
    if not dl or str(dl).strip() in ("", "N/A", "—", "-"):
        return 999, ""
    import re as _re
    m = _re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', str(dl))
    if not m:
        return 999, ""
    try:
        fmt   = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
        d     = datetime.strptime(m.group(1), fmt).date()
        delta = (d - date.today()).days
        if delta < 0:   return delta, "Expiré"
        if delta == 0:  return 0,     "Aujourd'hui !"
        if delta == 1:  return 1,     "Demain"
        if delta <= 3:  return delta, f"{delta}j 🔥"
        if delta <= 7:  return delta, f"{delta}j ⏳"
        return delta, f"{delta} jours"
    except Exception:
        return 999, ""
