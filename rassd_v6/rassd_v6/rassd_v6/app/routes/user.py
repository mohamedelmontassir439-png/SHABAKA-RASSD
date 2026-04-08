"""
Modern Business — Routes: Dashboard & Profil
"""
from fastapi import Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, Response
from fastapi.routing import APIRouter
from app.core.config   import cfg
from app.core.database import get_db
from app.core.dates    import is_expired, format_deadline
import re, json, secrets, logging
from datetime import datetime, date
from typing import Optional
logger = logging.getLogger(__name__)
router = APIRouter()

SITE_URL      = cfg.SITE_URL
ADMIN_PASS    = cfg.ADMIN_PASS
TELEGRAM_BOT  = cfg.TELEGRAM_BOT
ANTHROPIC_KEY = cfg.ANTHROPIC_KEY
PLAN_LIMITS   = cfg.PLAN_LIMITS
ADMIN_CHAT_ID = cfg.ADMIN_CHAT_ID

from app.utils.helpers import (
    templates, get_member, render, hash_pw,
    check_token, verify_pw, check_pw, now_str,
    counter, rl,
    NotifyAgent, MonitorAgent,
    VERIFY_TOKENS, send_verify_email,
)

@router.get("/marketplace", response_class=HTMLResponse)
async def marketplace(req: Request, type_f="", secteur_f="", region_f="", q="", page:int=1):
    per=16; off=(page-1)*per
    db=get_db()
    try:
        conds=["p.status='actif'"]; params=[]
        if type_f:    conds.append("p.type=?");    params.append(type_f)
        if secteur_f: conds.append("p.secteur=?"); params.append(secteur_f)
        if region_f:  conds.append("p.region=?");  params.append(region_f)
        if q:
            conds.append("(p.titre LIKE ? OR p.description LIKE ?)")
            params+=[f"%{q[:80]}%"]*2
        w=" AND ".join(conds)
        total  = db.execute(f"SELECT COUNT(*) FROM posts p WHERE {w}",params).fetchone()[0]
        posts  = [dict(r) for r in db.execute(
            f"""SELECT p.*,m.nom as m_nom,m.entreprise,m.rating_avg,m.rating_count,m.verified
                FROM posts p JOIN members m ON m.id=p.member_id WHERE {w}
                ORDER BY p.id DESC LIMIT ? OFFSET ?""",
            params+[per,off]).fetchall()]
    finally: db.close()
    counter("pv:marketplace")
    return render(req,"marketplace.html",{
        "posts":posts,"total":total,"page":page,"pages":max(1,(total+per-1)//per),
        "type_f":type_f,"secteur_f":secteur_f,"region_f":region_f,"q":q,
    })


@router.get("/marketplace/new", response_class=HTMLResponse)
async def mp_new_get(req: Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    return render(req,"marketplace_new.html",{"error":""})


@router.post("/marketplace/new")
async def mp_new_post(req: Request, titre:str=Form(""), description:str=Form(""),
    type_p:str=Form("offre"), secteur:str=Form(""), region:str=Form(""),
    budget:str=Form(""), contact:str=Form("")):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    rl(req,"mp_new",5,3600)
    if len(titre.strip())<10: return render(req,"marketplace_new.html",{"error":"Titre trop court (min 10 chars)"})
    db=get_db()
    try:
        db.execute("INSERT INTO posts (member_id,type,titre,description,secteur,region,budget,contact,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (m["id"],type_p,titre.strip()[:200],description.strip()[:3000],secteur,region,budget.strip()[:60],contact.strip()[:100],now_str()))
        db.commit()
    finally: db.close()
    return RedirectResponse("/marketplace",302)


@router.get("/marketplace/post/{pid}", response_class=HTMLResponse)
async def mp_detail(req: Request, pid:int):
    db=get_db()
    try:
        row=db.execute("SELECT p.*,m.nom as m_nom,m.entreprise,m.rating_avg,m.rating_count,m.verified,m.phone,m.email as m_email FROM posts p JOIN members m ON m.id=p.member_id WHERE p.id=? AND p.status='actif'",(pid,)).fetchone()
        if not row: raise HTTPException(404)
        post=dict(row)
        db.execute("UPDATE posts SET views=COALESCE(views,0)+1 WHERE id=?",(pid,)); db.commit()
        ratings=[dict(r) for r in db.execute("SELECT r.*,m.nom as from_nom FROM ratings r JOIN members m ON m.id=r.from_id WHERE r.to_id=? ORDER BY r.id DESC LIMIT 10",(post["member_id"],)).fetchall()]
        cur=get_member(req)
        can_rate=cur and cur["id"]!=post["member_id"]
        already=cur and bool(db.execute("SELECT 1 FROM ratings WHERE from_id=? AND to_id=?",(cur["id"],post["member_id"])).fetchone())
    finally: db.close()
    return render(req,"marketplace_detail.html",{"post":post,"ratings":ratings,"can_rate":can_rate,"already_rated":already})


@router.post("/marketplace/rate/{mid}")
async def mp_rate(req: Request, mid:int, score:int=Form(5), comment:str=Form("")):
    cur=get_member(req)
    if not cur: return RedirectResponse("/login",302)
    if cur["id"]==mid: raise HTTPException(400)
    db=get_db()
    try:
        db.execute("INSERT OR IGNORE INTO ratings (from_id,to_id,score,comment,created_at) VALUES (?,?,?,?,?)",(cur["id"],mid,max(1,min(5,score)),comment.strip()[:300],now_str()))
        db.commit()
        avg=db.execute("SELECT AVG(score),COUNT(*) FROM ratings WHERE to_id=?",(mid,)).fetchone()
        db.execute("UPDATE members SET rating_avg=?,rating_count=? WHERE id=?",(round(avg[0],1),avg[1],mid))
        db.commit()
    finally: db.close()
    return RedirectResponse(req.headers.get("referer","/marketplace"),302)


@router.get("/annuaire", response_class=HTMLResponse)
async def annuaire(req: Request, secteur_f="", q=""):
    db=get_db()
    try:
        conds=["actif=1"]; params=[]
        if secteur_f: conds.append("secteur=?"); params.append(secteur_f)
        if q: conds.append("(nom LIKE ? OR entreprise LIKE ? OR ville LIKE ?)"); params+=[f"%{q}%"]*3
        members=[dict(r) for r in db.execute(f"SELECT * FROM members WHERE {' AND '.join(conds)} ORDER BY rating_avg DESC,id DESC LIMIT 60",params).fetchall()]
    finally: db.close()
    return render(req,"annuaire.html",{"members":members,"secteur_f":secteur_f,"q":q})


@router.get("/filters", response_class=HTMLResponse)
async def filters_get(req: Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    db=get_db()
    try: my_filters=[dict(r) for r in db.execute("SELECT * FROM member_filters WHERE member_id=? ORDER BY type,value",(m["id"],)).fetchall()]
    finally: db.close()
    return render(req,"filters.html",{"m":m,"my_filters":my_filters})


@router.post("/filters/add")
async def filters_add(req: Request, ftype:str=Form(""), value:str=Form("")):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    if ftype in ["secteur","region","keyword"] and value.strip():
        db=get_db()
        try:
            db.execute("INSERT OR IGNORE INTO member_filters (member_id,type,value,created_at) VALUES (?,?,?,?)",(m["id"],ftype,value.strip()[:80],now_str()))
            db.commit()
        finally: db.close()
    return RedirectResponse("/filters",302)


@router.post("/filters/delete")
async def filters_delete(req: Request, fid:int=Form(0)):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    db=get_db()
    try: db.execute("DELETE FROM member_filters WHERE id=? AND member_id=?",(fid,m["id"])); db.commit()
    finally: db.close()
    return RedirectResponse("/filters",302)

# ── AUTH ──

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(req: Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    db=get_db()
    try:
        my_posts=[dict(r) for r in db.execute("SELECT * FROM posts WHERE member_id=? ORDER BY id DESC LIMIT 5",(m["id"],)).fetchall()]
        my_ratings=[dict(r) for r in db.execute("SELECT r.*,mem.nom as from_nom FROM ratings r JOIN members mem ON mem.id=r.from_id WHERE r.to_id=? ORDER BY r.id DESC LIMIT 5",(m["id"],)).fetchall()]
        stats=MonitorAgent.get_stats()
    finally: db.close()
    counter("pv:dashboard")
    return render(req,"dashboard.html",{"m":m,"my_posts":my_posts,"my_ratings":my_ratings,"stats":stats})


@router.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    return render(req,"settings.html",{"m":m,"success":"","error":""})


@router.post("/settings")
async def settings_post(req: Request, nom:str=Form(""), entreprise:str=Form(""),
    phone:str=Form(""), secteur:str=Form(""), ville:str=Form(""),
    notif_email:str=Form(""), notif_tg:str=Form(""),
    password:str=Form(""), password_new:str=Form("")):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    error=""
    db=get_db()
    try:
        db.execute("UPDATE members SET nom=?,entreprise=?,phone=?,secteur=?,ville=?,notif_email=?,notif_tg=? WHERE id=?",
                   (nom.strip() or m["nom"],entreprise.strip(),phone.strip(),secteur,ville.strip(),
                    1 if notif_email else 0,1 if notif_tg else 0,m["id"]))
        if password and password_new:
            if not check_pw(password,m.get("pw_hash","")): error="Mot de passe actuel incorrect"
            elif len(password_new)<8: error="Nouveau mot de passe trop court"
            else: db.execute("UPDATE members SET pw_hash=? WHERE id=?",(hash_pw(password_new),m["id"]))
        db.commit()
    finally: db.close()
    m=get_member(req)
    return render(req,"settings.html",{"m":m,"success":"Sauvegardé ✓" if not error else "","error":error})


@router.get("/contact", response_class=HTMLResponse)
async def contact(req: Request): return render(req,"contact.html",{})


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(req: Request): return render(req,"privacy.html",{})


@router.get("/tarifs", response_class=HTMLResponse)
async def tarifs(req: Request):
    db = get_db()
    try:
        stats = MonitorAgent.get_stats()
    finally: db.close()
    return render(req, "tarifs.html", {"stats": stats})


@router.get("/conditions", response_class=HTMLResponse)
async def conditions(req: Request):
    return render(req, "conditions.html", {})

# ── EMAIL VERIFICATION ──
VERIFY_TOKENS: dict = {}  # token -> {uid, expires}

def send_verify_email(uid: int, email: str, nom: str):
    """Queue verification email"""
    token = secrets.token_urlsafe(32)
    VERIFY_TOKENS[token] = {"uid": uid, "expires": datetime.now() + timedelta(hours=24)}
    url = f"{SITE_URL}/verify?token={token}"
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="background:#080808;padding:20px">
<div style="font-family:Georgia,serif;background:#0d0d0d;color:#fff;padding:28px;max-width:500px;margin:0 auto;border-radius:10px">
  <div style="font-size:18px;font-weight:700;color:#c9a84c;margin-bottom:14px">◆ Modern Business</div>
  <h2 style="margin-bottom:10px">Confirmez votre email</h2>
  <p style="color:#aaa;font-size:13px;margin-bottom:20px">Bonjour {nom}, cliquez pour activer votre compte:</p>
  <a href="{url}" style="display:inline-block;padding:10px 22px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none">Activer mon compte →</a>
  <p style="color:#555;font-size:11px;margin-top:16px">Lien valide 24h. Ignorez si vous n'avez pas créé de compte.</p>
</div></body></html>"""
    NotifyAgent.enqueue(uid, "email", email, f"Activez votre compte {BRAND}", html)


@router.post("/contact", response_class=HTMLResponse)
async def contact_post_handler(req: Request, nom:str=Form(""), email:str=Form(""),
                                sujet:str=Form(""), message:str=Form("")):
    m = get_member(req)
    if not nom or not email or not message:
        return render(req, "contact.html", {"error": "Tous les champs sont requis", "member": m})
    try:
        if TELEGRAM_BOT and ADMIN_CHAT_ID:
            import requests as _r
            _r.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id": ADMIN_CHAT_ID,
                      "text": f"📩 Contact\n<b>{nom}</b> ({email})\n<b>{sujet}</b>\n{message[:500]}",
                      "parse_mode": "HTML"},
                timeout=5
            )
    except Exception as e:
        logger.error(f"[contact] {e}")
    return render(req, "contact.html", {"ok": "Message envoyé. Réponse sous 24h ✓", "member": m})


# ═══════════════════════════════════════════════════
# BACKUP DB
# ═══════════════════════════════════════════════════