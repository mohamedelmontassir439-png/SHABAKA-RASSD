import bcrypt, hashlib, secrets, re
from datetime import datetime, date
from typing import Optional
from fastapi import Request
from app.core.config import cfg
from app.core.database import get_db

def hash_pw(pw): return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()
def verify_pw(pw, h):
    try: return bcrypt.checkpw(pw.encode(), h.encode())
    except: return False
def make_token(): return secrets.token_urlsafe(40)
def sign(val, salt=""):
    key = cfg.SECRET_KEY or "source_dev_key_2026"
    return hashlib.sha256(f"{val}{salt}{key}".encode()).hexdigest()[:40]

def get_member(req: Request) -> Optional[dict]:
    tok = req.cookies.get("_s","")
    if not tok or len(tok)<10: return None
    db = get_db()
    try:
        r = db.execute("SELECT * FROM members WHERE actif=1 AND session_token=?",(tok,)).fetchone()
        return dict(r) if r else None
    except: return None
    finally: db.close()

def is_admin(req: Request):
    return req.cookies.get("_a","") == sign("admin", cfg.ADMIN_PASS)

def valid_email(e): return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$',e))
def valid_pw(p): return (len(p)>=8, "8 caractères minimum" if len(p)<8 else "")

def days_left(dl):
    if not dl or str(dl).strip() in ("","N/A","—","-"): return 999,""
    m = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})',str(dl))
    if not m: return 999,""
    try:
        fmt = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
        d = datetime.strptime(m.group(1),fmt).date()
        n = (d-date.today()).days
        if n<0: return n,"Expiré"
        if n==0: return 0,"Aujourd'hui!"
        if n==1: return 1,"Demain"
        if n<=3: return n,f"{n}j 🔥"
        if n<=7: return n,f"{n}j ⏳"
        return n,f"{n} jours"
    except: return 999,""

def plan_ok(m, feat):
    p = cfg.PLANS.get(m.get("plan","free"), cfg.PLANS["free"])
    if feat=="unlimited": return p.get("limit",10)==0
    if feat=="tg": return p.get("tg",False)
    return False
