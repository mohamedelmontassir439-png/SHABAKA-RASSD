"""
Modern Business — Routes: Auth (login/register)
"""
from fastapi import Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, Response
from fastapi.routing import APIRouter
from app.core.config   import cfg
from app.core.database import get_db
from app.core.dates    import is_expired, format_deadline
import re, json, csv, io, secrets, logging
from datetime import datetime, date
from typing import Optional
logger = logging.getLogger(__name__)
router = APIRouter()

from app.core.config import cfg
SITE_URL      = cfg.SITE_URL
ADMIN_PASS    = cfg.ADMIN_PASS
TELEGRAM_BOT  = cfg.TELEGRAM_BOT
ANTHROPIC_KEY = cfg.ANTHROPIC_KEY
PLAN_LIMITS   = cfg.PLAN_LIMITS

from app.utils.helpers import (
    templates, get_member, render, hash_pw,
    check_token, verify_pw
)

@router.get("/register", response_class=HTMLResponse)
async def reg_get(req: Request):
    if get_member(req): return RedirectResponse("/dashboard",302)
    return render(req,"register.html",{"error":""})


@router.post("/register")
async def reg_post(req: Request, nom:str=Form(""), entreprise:str=Form(""),
    email:str=Form(""), phone:str=Form(""), secteur:str=Form(""),
    ville:str=Form(""), password:str=Form("")):
    rl(req,"register",8,3600)
    error=""
    if not all([nom,email,password]): error="Champs * obligatoires"
    elif len(password)<8: error="Mot de passe: minimum 8 caractères"
    elif not re.match(r'^[^@]+@[^@]+\.[^@]+$',email): error="Email invalide"
    else:
        db=get_db()
        try:
            if db.execute("SELECT 1 FROM members WHERE email=?",(email.lower(),)).fetchone():
                error="Email déjà utilisé"
            else:
                db.execute("INSERT INTO members (nom,entreprise,email,phone,secteur,ville,pw_hash,actif,notif_email,notif_tg,created_at) VALUES (?,?,?,?,?,?,?,1,1,1,?)",
                           (nom.strip(),entreprise.strip(),email.lower().strip(),phone.strip(),secteur,ville.strip(),hash_pw(password),now_str()))
                db.commit()
                uid=db.execute("SELECT id FROM members WHERE email=?",(email.lower(),)).fetchone()[0]
                db.close()
                counter("registrations")
                # Send verification email
                send_verify_email(uid, email, nom.strip())
                # Welcome email
                welcome_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="background:#080808;padding:20px">
<div style="font-family:Georgia,serif;background:#0d0d0d;color:#fff;padding:28px;max-width:500px;margin:0 auto;border-radius:10px">
  <div style="font-size:18px;font-weight:700;color:#c9a84c;margin-bottom:14px">◆ Modern Business</div>
  <h2 style="margin-bottom:10px">Bienvenue, {nom}! 🎉</h2>
  <p style="color:#aaa;font-size:13px;margin-bottom:20px">Votre compte est activé. Recevez les marchés de votre secteur sur Telegram dès publication.</p>
  <a href="{SITE_URL}/dashboard" style="display:inline-block;padding:10px 22px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none">Accéder →</a>
  <p style="color:#555;font-size:11px;margin-top:16px">Pour activer Telegram: envoyez /link {email.lower()} à @MarchesMarocBot</p>
</div></body></html>"""
                NotifyAgent.enqueue(uid,"email",email,f"Bienvenue sur {BRAND}!",welcome_html)
                resp=RedirectResponse("/dashboard",302)
                session_create(resp,uid); return resp
        except Exception as e: error=f"Erreur: {e}"
        finally:
            try: db.close()
            except: pass
    return render(req,"register.html",{"error":error})


@router.get("/login", response_class=HTMLResponse)
async def login_get(req: Request):
    if get_member(req): return RedirectResponse("/dashboard",302)
    return render(req,"login.html",{"error":"","reset":req.query_params.get("reset","")})


@router.post("/login")
async def login_post(req: Request, email:str=Form(""), password:str=Form("")):
    rl(req,f"login:{get_ip(req)}",5,300)
    db=get_db()
    try:
        row=db.execute("SELECT * FROM members WHERE email=? AND actif=1",(email.lower().strip(),)).fetchone()
        if not row or not check_pw(password,dict(row).get("pw_hash","")):
            return render(req,"login.html",{"error":"Email ou mot de passe incorrect","reset":""})
        m=dict(row)
        db.execute("UPDATE members SET last_login=? WHERE id=?",(now_str(),m["id"])); db.commit()
    finally: db.close()
    counter("logins")
    resp=RedirectResponse("/dashboard",302)
    session_create(resp,m["id"]); return resp


@router.get("/logout")
async def logout():
    resp=RedirectResponse("/",302)
    session_delete(resp); return resp


@router.get("/forgot", response_class=HTMLResponse)
async def forgot_get(req: Request):
    return render(req,"forgot.html",{"sent":False,"error":""})


@router.post("/forgot")
async def forgot_post(req: Request, email:str=Form("")):
    rl(req,"forgot",3,3600)
    db=get_db()
    try: row=db.execute("SELECT id,nom FROM members WHERE email=? AND actif=1",(email.lower().strip(),)).fetchone()
    finally: db.close()
    if row:
        token=secrets.token_urlsafe(32)
        RESET_TOKENS[token]={"email":email.lower().strip(),"expires":datetime.now()+timedelta(hours=2)}
        reset_url=f"{SITE_URL}/reset?token={token}"
        NotifyAgent.enqueue(None,"email",email,f"Réinitialisation mot de passe — {BRAND}",
            f'<div style="font-family:Georgia;background:#0d0d0d;color:#fff;padding:28px;border-radius:10px"><div style="font-size:18px;font-weight:700;color:#c9a84c;margin-bottom:14px">◆ Modern Business</div><p>Cliquez pour réinitialiser votre mot de passe (valide 2h):</p><a href="{reset_url}" style="display:inline-block;margin-top:14px;padding:10px 22px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none">Réinitialiser →</a></div>')
        db=get_db()
        try:
            tg=db.execute("SELECT telegram FROM members WHERE email=?",(email.lower(),)).fetchone()
            if tg and tg["telegram"]:
                NotifyAgent.enqueue(None,"telegram",tg["telegram"],"",
                    f"🔑 <b>Réinitialisation mot de passe</b>\n\nLien (2h):\n{reset_url}")
        finally: db.close()
    return render(req,"forgot.html",{"sent":True,"error":""})


@router.get("/reset", response_class=HTMLResponse)
async def reset_get(req: Request, token:str=""):
    data=RESET_TOKENS.get(token)
    if not data or datetime.now()>data["expires"]:
        return render(req,"forgot.html",{"sent":False,"error":"Lien expiré ou invalide. Recommencez."})
    return render(req,"reset.html",{"token":token,"error":""})


@router.post("/reset")
async def reset_post(req: Request, token:str=Form(""), password:str=Form(""), password2:str=Form("")):
    data=RESET_TOKENS.get(token)
    if not data or datetime.now()>data["expires"]:
        return render(req,"forgot.html",{"sent":False,"error":"Lien expiré. Recommencez."})
    if len(password)<8: return render(req,"reset.html",{"token":token,"error":"Minimum 8 caractères"})
    if password!=password2: return render(req,"reset.html",{"token":token,"error":"Mots de passe différents"})
    db=get_db()
    try: db.execute("UPDATE members SET pw_hash=? WHERE email=?",(hash_pw(password),data["email"])); db.commit()
    finally: db.close()
    del RESET_TOKENS[token]
    return RedirectResponse("/login?reset=1",302)

# ── DASHBOARD ──

@router.get("/verify", response_class=HTMLResponse)
async def verify_email(req: Request, token: str = ""):
    data = VERIFY_TOKENS.get(token)
    if not data or datetime.now() > data["expires"]:
        return render(req, "login.html", {"error": "Lien expiré. Connectez-vous pour en recevoir un nouveau.", "reset": ""})
    db = get_db()
    try:
        db.execute("UPDATE members SET verified=1 WHERE id=?", (data["uid"],))
        db.commit()
    finally: db.close()
    try: del VERIFY_TOKENS[token]
    except: pass
    return RedirectResponse("/dashboard?verified=1", 302)
