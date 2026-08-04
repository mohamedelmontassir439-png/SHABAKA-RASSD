import bcrypt, hashlib, secrets, re
from datetime import datetime, date, timedelta
from typing import Optional
from fastapi import Request, HTTPException
from app.core.config import cfg
from app.core.database import get_db

def get_csrf_token(req: Request) -> str:
    """Retourne le jeton CSRF de la requête courante (cookie _csrf), ou une
    chaîne vide si absent — le jeton effectif est (re)généré et posé sur la
    réponse par render()/les routes admin, jamais ici (fonction pure, sans
    effet de bord sur la réponse)."""
    tok = req.cookies.get("_csrf", "")
    return tok if tok and len(tok) >= 20 else ""

def verify_csrf(req: Request, submitted: str) -> bool:
    cookie_tok = req.cookies.get("_csrf", "")
    header_tok = req.headers.get("x-csrf-token", "")
    candidate  = submitted or header_tok
    return bool(cookie_tok) and bool(candidate) and secrets.compare_digest(cookie_tok, candidate)

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_pw(pw: str, hashed: str) -> bool:
    """Vérifie qu'un mot de passe correspond à son hash bcrypt.

    Retourne False en cas d'erreur (hash invalide, encoding, etc.) au lieu de crasher.
    """
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except (ValueError, TypeError) as e:
        # Hash corrompu ou format invalide
        import logging
        logging.getLogger("atlas.security").warning(f"[verify_pw] Hash invalide: {e}")
        return False

def make_token(val: str, salt: str = "") -> str:
    """Token stable basé sur SECRET_KEY (obligatoire, pas de fallback).

    SECRET_KEY DOIT être défini en variable d'environnement en production.
    Sans lui, tous les tokens deviendraient prévisibles = faille de sécurité majeure.
    """
    key = cfg.SECRET_KEY
    if not key or len(key) < 32:
        raise RuntimeError(
            "SECRET_KEY manquant ou trop court (min 32 caractères). "
            "Définis-le dans les variables d'environnement Railway. "
            "Génère-en un avec: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
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

def has_access(member: Optional[dict]) -> bool:
    """Un membre inscrit ne voit les marchés réels qu'une fois son plan
    activé manuellement par l'admin (paiement confirmé). Le plan 'free'
    (par défaut à l'inscription) n'ouvre aucun accès aux données."""
    return bool(member) and member.get("plan") in ("pro", "business")

def require_member(req: Request) -> dict:
    m = get_member(req)
    if not m:
        from fastapi.responses import RedirectResponse
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return m

def require_admin(req: Request):
    """Vérifie que le cookie admin est valide.

    Le cookie contient un token dérivé de ADMIN_PASS + SECRET_KEY.
    ADMIN_PASS doit être défini en variable d'environnement (jamais en clair dans le code).
    """
    if not cfg.ADMIN_PASS or cfg.ADMIN_PASS == "atlas2026":
        # Valeur par défaut détectée = config non sécurisée
        from fastapi.responses import RedirectResponse
        raise HTTPException(
            status_code=503,
            detail="ADMIN_PASS non configuré ou utilise la valeur par défaut. "
                   "Change-le dans les variables d'environnement Railway."
        )
    cookie = req.cookies.get("_admin", "")
    if cookie != make_token("admin", cfg.ADMIN_PASS):
        from fastapi.responses import RedirectResponse
        raise HTTPException(status_code=307, headers={"Location": "/admin/login"})

def validate_email(email: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email))

def validate_password(pw: str, lang: str = "fr") -> tuple[bool, str]:
    """Valide qu'un mot de passe est suffisamment fort.

    Règles:
    - Au moins 8 caractères
    - Au moins 1 chiffre OU 1 caractère spécial (anti-mot-de-passe trivial)
    - Pas dans la liste des mots de passe trop courants
    """
    from app.core.i18n import tr as _tr
    if len(pw) < 8:
        return False, _tr("err_pw_min8", lang)
    if len(pw) > 128:
        return False, _tr("err_pw_too_long", lang)

    # Rejette les mots de passe trop faibles même s'ils font 8+ caractères
    weak = {"password", "12345678", "qwerty12", "admin123", "atlas123",
            "00000000", "11111111", "abcdefgh", "password1"}
    if pw.lower() in weak:
        return False, _tr("err_pw_too_common", lang)

    # Exige au moins 1 chiffre OU 1 caractère spécial
    has_digit = any(c.isdigit() for c in pw)
    has_special = any(not c.isalnum() for c in pw)
    if not (has_digit or has_special):
        return False, _tr("err_pw_need_digit", lang)

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

def days_left(dl: str, lang: str = "fr"):
    """Retourne (nb_jours: int, label: str)"""
    from app.core.i18n import tr as _tr
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
        if delta < 0:   return delta, _tr("dl_expired", lang)
        if delta == 0:  return 0,     _tr("dl_today", lang)
        if delta == 1:  return 1,     _tr("dl_tomorrow", lang)
        if delta <= 3:  return delta, _tr("dl_days_urgent", lang, n=delta)
        if delta <= 7:  return delta, _tr("dl_days_soon", lang, n=delta)
        return delta, _tr("dl_days", lang, n=delta)
    except Exception:
        return 999, ""
