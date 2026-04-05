"""
Modern Business — Routes: API v1 & Utilitaires
"""
from fastapi import Request, Form, HTTPException
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

SITE_URL      = cfg.SITE_URL
ADMIN_PASS    = cfg.ADMIN_PASS
TELEGRAM_BOT  = cfg.TELEGRAM_BOT
ANTHROPIC_KEY = cfg.ANTHROPIC_KEY
PLAN_LIMITS   = cfg.PLAN_LIMITS

from app.utils.helpers import (
    templates, get_member, render, hash_pw,
    check_token, verify_pw, counter,
    SECTEURS_LIST, REGIONS,
)

@router.get("/", response_class=HTMLResponse)
async def home(req: Request):
    db = get_db()
    try:
        stats = {
            "tenders": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "today":   db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND date_extraction>=date('now')").fetchone()[0],
            "members": db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
        }
        recent = [dict(r) for r in db.execute(
            "SELECT id, objet, domaine AS secteur, date_limite, acheteur, montant"
            " FROM tenders WHERE statut='actif'"
            " ORDER BY date_extraction DESC LIMIT 3"
        ).fetchall()]
        sectors = [dict(r) for r in db.execute(
            "SELECT domaine AS secteur, COUNT(*) AS cnt"
            " FROM tenders WHERE statut='actif' AND domaine!=''"
            " GROUP BY domaine ORDER BY cnt DESC LIMIT 16"
        ).fetchall()]
    finally: db.close()
    counter("pv:home")
    return render(req, "landing.html", {"stats": stats, "recent": recent, "sectors": sectors})

# Plan limits


@router.get("/tenders", response_class=HTMLResponse)
async def tenders_page(req: Request, code_f="", region_f="", source_f="", type_f="", easy="", q="", page:int=1, sort:str="score"):
    m = get_member(req)
    # Tenders visibles uniquement pour membres Pro/Enterprise
    if not m:
        return render(req, "tenders_locked.html", {"reason": "login", "member": None,
            "SECTEURS_LIST": SECTEURS_LIST, "REGIONS": REGIONS})
    if m.get("plan","free") == "free":
        return render(req, "tenders_locked.html", {"reason": "upgrade", "member": m,
            "SECTEURS_LIST": SECTEURS_LIST, "REGIONS": REGIONS})
    per=20; off=(page-1)*per
    db = get_db()
    try:
        conds=["statut='actif'"]; params=[]
        if code_f:    conds.append("domaine LIKE ?"); params.append(f"{code_f}%")
        if region_f:  conds.append("region=?");       params.append(region_f)
        if source_f:  conds.append("source=?");        params.append(source_f)
        if type_f:    conds.append("type_marche=?");   params.append(type_f)
        if easy=="1": conds.append("ai_score >= 70")
        if q:
            conds.append("(objet LIKE ? OR acheteur LIKE ? OR description LIKE ?)")
            params += [f"%{q[:80]}%"]*3
        w = " AND ".join(conds)
        total  = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}", params).fetchone()[0]
        rows   = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {w} ORDER BY " + ("date_extraction DESC" if sort=="date" else ("date_limite ASC" if sort=="deadline" else "ai_score DESC, date_extraction DESC")) + " LIMIT ? OFFSET ?",
            params+[per,off]).fetchall()]
        regions_list = [r[0] for r in db.execute("SELECT DISTINCT region FROM tenders WHERE region!='' ORDER BY region").fetchall()]
        sources_list = [r[0] for r in db.execute("SELECT DISTINCT source FROM tenders WHERE source!='' ORDER BY source").fetchall()]
    finally: db.close()
    counter("pv:tenders")
    return render(req,"tenders.html",{
        "tenders":rows,"total":total,"page":page,"pages":max(1,(total+per-1)//per),"sort":sort,
        "code_f":code_f,"region_f":region_f,"source_f":source_f,"type_f":type_f,
        "easy":easy,"q":q,"regions_list":regions_list,"sources_list":sources_list,
    })


@router.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM tenders WHERE id=?",(tid,)).fetchone()
        if not row: raise HTTPException(404)
        t = dict(row)
        db.execute("UPDATE tenders SET views=COALESCE(views,0)+1 WHERE id=?",(tid,)); db.commit()
        related = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE domaine=? AND id!=? AND statut='actif' ORDER BY ai_score DESC, date_extraction DESC LIMIT 5",
            (t["domaine"],tid)).fetchall()]
    finally: db.close()
    counter("pv:tender_detail")
    return render(req,"tender_detail.html",{"t":t,"related":related})


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


@router.get("/a-propos", response_class=HTMLResponse)
async def a_propos(req: Request):
    return render(req, "a_propos.html", {})


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


@router.get("/resend-verify")
async def resend_verify(req: Request):
    m = get_member(req)
    if not m: return RedirectResponse("/login", 302)
    if m.get("verified"): return RedirectResponse("/dashboard", 302)
    send_verify_email(m["id"], m["email"], m["nom"])
    return RedirectResponse("/dashboard?verify_sent=1", 302)

# ── ADMIN PLAN MANAGEMENT ──

@router.get("/admin/set_plan")
async def admin_set_plan(pwd: str="", member_id: int=0, plan: str="free"):
    chk(pwd)
    db = get_db()
    try:
        db.execute("UPDATE members SET plan=?,verified=1 WHERE id=?", (plan, member_id))
        db.commit()
        row = db.execute("SELECT email,nom,telegram FROM members WHERE id=?", (member_id,)).fetchone()
    finally: db.close()
    if row and dict(row).get("telegram"):
        plan_names = {"free":"Gratuit","pro":"Pro 99 DH/mois","enterprise":"Entreprise"}
        asyncio.create_task(NotifyAgent.send_telegram(
            dict(row)["telegram"],
            f"🎉 <b>Votre abonnement a été activé!</b>\n\n"
            f"Plan: <b>{plan_names.get(plan, plan)}</b>\n"
            f"Accédez à votre espace: {SITE_URL}/dashboard"
        ))
    return JSONResponse({"ok": True, "plan": plan, "member_id": member_id})

# ══════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════

@router.post("/api/chat")
async def api_chat(req: Request):
    rl(req,f"chat:{get_ip(req)}",20,60)
    try:
        data=await req.json()
        user_msg=str(data.get("message",""))[:800].strip()
        sess=data.get("session_key",get_ip(req))[:50]
        if not user_msg: return JSONResponse({"error":"Message vide"},400)
        db=get_db()
        try:
            rows=db.execute("SELECT role,content FROM chats WHERE session_key=? ORDER BY id DESC LIMIT 16",(sess,)).fetchall()
            history=[{"role":r["role"],"content":r["content"]} for r in reversed(rows)]
        finally: db.close()
        history.append({"role":"user","content":user_msg})
        response=await ChatAgent.respond(history)
        db=get_db()
        try:
            ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.execute("INSERT INTO chats (session_key,role,content,created_at) VALUES (?,?,?,?)",(sess,"user",user_msg,ts))
            db.execute("INSERT INTO chats (session_key,role,content,created_at) VALUES (?,?,?,?)",(sess,"assistant",response,ts))
            db.execute("DELETE FROM chats WHERE session_key=? AND id NOT IN (SELECT id FROM chats WHERE session_key=? ORDER BY id DESC LIMIT 40)",(sess,sess))
            db.commit()
        finally: db.close()
        counter("chat_messages")
        return JSONResponse({"response":response,"session_key":sess})
    except Exception as e:
        logger.error(f"[api:chat] {e}")
        return JSONResponse({"error":"Erreur serveur"},500)


@router.post("/api/consent")
async def api_consent(): return JSONResponse({"ok":True})


@router.get("/api/stats")
async def api_stats(): return JSONResponse(MonitorAgent.get_stats())


@router.get("/api/v1/tenders")
async def api_v1_tenders(req: Request, source:str="", code:str="", region:str="", type_m:str="",
    q:str="", min_score:int=0, easy:str="", page:int=1, per_page:int=20):
    per_page=min(per_page,100); off=(page-1)*per_page
    db=get_db()
    try:
        conds=["statut='actif'"]; params=[]
        if source:     conds.append("source=?");        params.append(source)
        if code:       conds.append("domaine LIKE ?");  params.append(f"{code}%")
        if region:     conds.append("region LIKE ?");   params.append(f"%{region}%")
        if type_m:     conds.append("type_marche=?");   params.append(type_m)
        if min_score:  conds.append("ai_score >= ?");   params.append(min_score)
        if easy=="1":  conds.append("ai_score >= 70")
        if q:
            conds.append("(objet LIKE ? OR description LIKE ? OR acheteur LIKE ?)")
            params+=[f"%{q}%"]*3
        w=" AND ".join(conds)
        total=db.execute(f"SELECT COUNT(*) FROM tenders WHERE {w}",params).fetchone()[0]
        rows=[dict(r) for r in db.execute(
            f"SELECT id,objet,acheteur,region,domaine,type_marche,montant,date_limite,source,contact,ai_score,ai_category,ai_reason,url,date_extraction FROM tenders WHERE {w} ORDER BY ai_score DESC, date_extraction DESC LIMIT ? OFFSET ?",
            params+[per_page,off]).fetchall()]
    finally: db.close()
    return JSONResponse({"total":total,"page":page,"per_page":per_page,"pages":max(1,(total+per_page-1)//per_page),"tenders":rows})


@router.get("/api/v1/tenders/new")
async def api_v1_new(hours:int=24):
    db=get_db()
    try:
        since=(datetime.now()-timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        rows=[dict(r) for r in db.execute("SELECT id,objet,acheteur,region,domaine,source,ai_score,date_limite,url FROM tenders WHERE date_extraction>=? AND statut='actif' ORDER BY ai_score DESC, date_extraction DESC LIMIT 50",(since,)).fetchall()]
    finally: db.close()
    return JSONResponse({"count":len(rows),"since_hours":hours,"tenders":rows})


@router.get("/api/v1/tenders/easy")
async def api_v1_easy(min_score:int=70, limit:int=20):
    db=get_db()
    try:
        rows=[dict(r) for r in db.execute("SELECT id,objet,acheteur,region,domaine,source,montant,ai_score,ai_reason,date_limite,url FROM tenders WHERE statut='actif' AND ai_score>=? ORDER BY ai_score DESC LIMIT ?",(min_score,limit)).fetchall()]
    finally: db.close()
    return JSONResponse({"count":len(rows),"min_score":min_score,"tenders":rows})


@router.get("/api/v1/tenders/{tid}")
async def api_v1_detail(tid:str):
    db=get_db()
    try:
        row=db.execute("SELECT * FROM tenders WHERE id=?",(tid,)).fetchone()
        if not row: raise HTTPException(404,"Not found")
        t=dict(row); db.execute("UPDATE tenders SET views=COALESCE(views,0)+1 WHERE id=?",(tid,)); db.commit()
    finally: db.close()
    return JSONResponse(t)


@router.get("/api/v1/sources")
async def api_v1_sources():
    db=get_db()
    try:
        rows=[dict(r) for r in db.execute("SELECT source,COUNT(*) as total,SUM(CASE WHEN statut='actif' THEN 1 ELSE 0 END) as active,AVG(ai_score) as avg_score FROM tenders GROUP BY source ORDER BY total DESC").fetchall()]
    finally: db.close()
    return JSONResponse({"sources":rows,"multi_available":HAS_MULTI})


@router.get("/api/v1/stats")
async def api_v1_stats():
    s=MonitorAgent.get_stats()
    db=get_db()
    try:
        s["sources"]=[dict(r) for r in db.execute("SELECT source,COUNT(*) as total,SUM(CASE WHEN statut='actif' THEN 1 ELSE 0 END) as active FROM tenders GROUP BY source ORDER BY total DESC").fetchall()]
        s["avg_score"]=round(db.execute("SELECT AVG(ai_score) FROM tenders WHERE statut='actif'").fetchone()[0] or 50,1)
    finally: db.close()
    return JSONResponse(s)


@router.get("/api/my_filters")
async def api_my_filters(req: Request):
    m=get_member(req)
    if not m: return JSONResponse({"error":"Non connecté"},401)
    db=get_db()
    try: filters=[dict(r) for r in db.execute("SELECT id,type,value FROM member_filters WHERE member_id=?",(m["id"],)).fetchall()]
    finally: db.close()
    return JSONResponse({"filters":filters})

# ══════════════════════════════════════════════════════
# TELEGRAM WEBHOOK
# ══════════════════════════════════════════════════════

@router.post("/telegram/webhook")
async def tg_webhook(req: Request):
    try:
        data=await req.json()
        msg=data.get("message") or data.get("edited_message") or {}
        if not msg: return {"ok":True}
        chat_id=str(msg.get("chat",{}).get("id",""))
        text=(msg.get("text") or "").strip()
        if not chat_id: return {"ok":True}
        async def reply(txt): await NotifyAgent.send_telegram(chat_id,txt)
        # /register shortcut
        if text.lower() in ["/register","/inscription"]:
            await reply(f"📝 Inscrivez-vous:\n{SITE_URL}/register\n\nEnsuite: /link votre@email.com")
            return {"ok":True}
        # /link email
        if text.lower().startswith("/link ") and "@" in text:
            email=text.split()[1].strip().lower()
            db=get_db()
            try:
                row=db.execute("SELECT id,nom FROM members WHERE email=? AND actif=1",(email,)).fetchone()
                if row:
                    db.execute("UPDATE members SET telegram=? WHERE id=?",(chat_id,row["id"])); db.commit()
                    await reply(f"✅ <b>Alertes activées, {row['nom']}!</b>\n\nVous recevrez les marchés de votre secteur.\n\n/secteur — Choisir votre secteur\n🌐 {SITE_URL}")
                else:
                    await reply(f"❌ Email non trouvé.\nInscrivez-vous: {SITE_URL}/register\nPuis: /link votre@email.com")
            finally: db.close()
            return {"ok":True}
        # /secteur
        if text.lower().startswith("/secteur"):
            parts=text.split(None,1)
            if len(parts)>1:
                new_s=parts[1].strip()
                db=get_db()
                try:
                    row=db.execute("SELECT id,nom FROM members WHERE telegram=? AND actif=1",(chat_id,)).fetchone()
                    if row:
                        matched=next((s for s in SECTEURS.keys() if new_s.lower() in s.lower() or s[:4].lower()==new_s[:4].lower()),None)
                        if matched:
                            db.execute("UPDATE members SET secteur=? WHERE id=?",(matched,row["id"])); db.commit()
                            await reply(f"✅ Secteur: <b>{matched}</b>\nVous recevrez uniquement ces marchés.")
                        else:
                            sl="\n".join(f"• {s}" for s in list(SECTEURS.keys())[:12])
                            await reply(f"Secteur non reconnu.\n\nExemples:\n{sl}\n\nEx: /secteur T101")
                    else:
                        await reply(f"Liez d'abord votre compte: /link votre@email.com")
                finally: db.close()
            else:
                db=get_db()
                try: row=db.execute("SELECT nom,secteur FROM members WHERE telegram=? AND actif=1",(chat_id,)).fetchone()
                finally: db.close()
                if row:
                    await reply(f"Votre secteur: <b>{dict(row).get('secteur') or 'Non défini'}</b>\n\nChanger: /secteur [code]\nEx: /secteur T101\n\nSecteurs:\n"+"\n".join(f"• {s}" for s in list(SECTEURS.keys())[:15]))
                else:
                    await reply(f"Liez d'abord: /link votre@email.com")
            return {"ok":True}
        if text in ["/start","start"]:
            db=get_db()
            try: row=db.execute("SELECT nom,secteur FROM members WHERE telegram=? AND actif=1",(chat_id,)).fetchone()
            finally: db.close()
            if row:
                m2=dict(row)
                await reply(f"👋 Bonjour <b>{m2['nom']}</b>!\n\n✅ Compte lié\n🏷 Secteur: <b>{m2['secteur'] or 'Non défini'}</b>\n\n/secteur — Changer secteur\n/tenders — Derniers marchés\n/stats — Statistiques\n\n🌐 {SITE_URL}")
            else:
                await reply(f"🏛 <b>Modern Business</b>\nIntelligence des Marchés Publics Maroc\n\n📱 <b>2 étapes:</b>\n1️⃣ Inscrivez-vous: {SITE_URL}/register\n2️⃣ <code>/link votre@email.com</code>\n\n✅ Recevez les marchés de votre secteur!\n\n🌐 {SITE_URL}")
        elif text=="/tenders":
            db=get_db()
            try: rows=db.execute("SELECT objet,acheteur,region,domaine,date_limite,url FROM tenders WHERE statut='actif' ORDER BY ai_score DESC, date_extraction DESC LIMIT 5").fetchall()
            finally: db.close()
            if rows:
                lines=[f"🏛 <b>5 derniers marchés actifs</b>\n{'━'*28}"]
                for r in rows:
                    b=f"\n📋 <b>{r['objet'][:60]}</b>"
                    if r['acheteur']: b+=f"\n   🏢 {r['acheteur'][:45]}"
                    if r['region']:   b+=f"\n   📍 {r['region']}"
                    if r['domaine']:  b+=f"\n   🏷 {r['domaine'][:25]}"
                    if r['date_limite']: b+=f"\n   ⏰ <b>{r['date_limite']}</b>"
                    if r['url']:      b+=f"\n   🔗 {r['url']}"
                    lines.append(b)
                lines.append(f"\n🌐 {SITE_URL}")
                await reply("\n".join(lines))
            else:
                await reply(f"Aucun marché actif.\n🌐 {SITE_URL}")
        elif text=="/stats":
            st=MonitorAgent.get_stats()
            await reply(f"📊 <b>Modern Business — Stats</b>\n\n✅ Actifs: <b>{st['tenders_active']}</b>\n🏆 Faciles: <b>{st['easy_to_win']}</b>\n📦 Total: <b>{st['tenders_total']}</b>\n🏢 Membres: <b>{st['members']}</b>\n🔔 Abonnés TG: <b>{st['members_tg']}</b>\n\n🌐 {SITE_URL}")
        elif text=="/help":
            await reply(f"ℹ️ <b>Modern Business — Aide</b>\n\n/start — Menu\n/link email — Activer alertes\n/secteur — Choisir secteur\n/tenders — Derniers marchés\n/stats — Statistiques\n\n📩 {SITE_URL}/contact")
        else:
            await reply(f"Envoyez /start pour le menu.\n🌐 {SITE_URL}")
    except Exception as e: logger.error(f"[tg:webhook] {e}")
    return {"ok":True}

# ══════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════
def chk(pwd:str, req=None):
    """Check admin auth: cookie session OR URL pwd"""
    if pwd == ADMIN_PASS: return True
    if req:
        cookie = req.cookies.get("admin_session","")
        if cookie == ADMIN_PASS: return True
    raise HTTPException(403, "Accès refusé")


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(req: Request):
    # If already authenticated via cookie, redirect
    session = req.cookies.get("admin_session","")
    if session == ADMIN_PASS:
        return RedirectResponse("/admin", 302)
    return HTMLResponse("""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin — Modern Business</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#030303;color:#f3eee7;font-family:'DM Sans',system-ui,sans-serif;
  min-height:100dvh;display:flex;align-items:center;justify-content:center}
.box{width:320px;padding:40px 32px;background:#0f0f0f;border:1px solid #222;border-radius:10px;
  box-shadow:0 16px 64px rgba(0,0,0,.8)}
.gem{width:24px;height:24px;background:linear-gradient(135deg,#e8c97a,#a07830);
  clip-path:polygon(50% 0%,100% 38%,82% 100%,18% 100%,0% 38%);margin:0 auto 16px}
h1{font-family:'Playfair Display',Georgia,serif;font-size:22px;font-weight:900;
  text-align:center;margin-bottom:4px;font-style:italic}
p{font-size:11px;color:#655f58;text-align:center;margin-bottom:28px}
label{display:block;font-size:9px;font-weight:700;color:#3c3730;text-transform:uppercase;
  letter-spacing:1.2px;margin-bottom:5px}
input{width:100%;padding:10px 14px;background:#151515;border:1px solid #2c2c2c;
  border-radius:4px;font-size:14px;color:#f3eee7;outline:none;margin-bottom:16px}
input:focus{border-color:#a07830;box-shadow:0 0 0 3px rgba(201,168,76,.07)}
button{width:100%;padding:11px;background:linear-gradient(135deg,#e8c97a,#a07830);
  color:#030303;font-weight:700;font-size:12px;letter-spacing:.07em;text-transform:uppercase;
  border:none;border-radius:4px;cursor:pointer;transition:.15s}
button:hover{filter:brightness(1.1)}
.err{background:rgba(158,74,74,.1);border:1px solid rgba(158,74,74,.2);border-radius:4px;
  padding:9px 13px;font-size:12px;color:#c46060;margin-bottom:14px;text-align:center}
</style></head><body>
<div class="box">
  <div class="gem"></div>
  <h1>Administration</h1>
  <p>Modern Business — Accès sécurisé</p>
  <div id="err" class="err" style="display:none">Mot de passe incorrect</div>
  <form method="post" action="/admin/login">
    <label>Mot de passe admin</label>
    <input type="password" name="pwd" placeholder="••••••••••" autofocus required>
    <button type="submit">Accéder →</button>
  </form>
</div>
<script>
const p=new URLSearchParams(location.search);
if(p.get('err'))document.getElementById('err').style.display='block';
</script>
</body></html>""")



@router.post("/admin/login")
async def admin_login_post(req: Request, pwd: str = Form("")):
    if pwd == ADMIN_PASS:
        resp = RedirectResponse("/admin", 302)
        resp.set_cookie("admin_session", ADMIN_PASS, max_age=86400*7,
                        httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/admin/login?err=1", 302)



@router.get("/admin/logout")
async def admin_logout():
    resp = RedirectResponse("/admin/login", 302)
    resp.delete_cookie("admin_session")
    return resp



@router.get("/admin", response_class=HTMLResponse)
async def admin(req: Request, pwd:str=""):
    # Redirect to login if not authenticated
    cookie = req.cookies.get("admin_session","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return RedirectResponse("/admin/login", 302)
    db=get_db()
    try:
        stats  =MonitorAgent.get_stats()
        tenders=[dict(r) for r in db.execute("SELECT * FROM tenders ORDER BY date_extraction DESC LIMIT 50").fetchall()]
        members=[dict(r) for r in db.execute("SELECT * FROM members ORDER BY id DESC LIMIT 20").fetchall()]
        hist   =[dict(r) for r in db.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 8").fetchall()]
        errors =[dict(r) for r in db.execute("SELECT * FROM agent_errors WHERE resolved=0 ORDER BY last_seen DESC LIMIT 10").fetchall()]
        notifs =[dict(r) for r in db.execute("SELECT * FROM notif_queue ORDER BY id DESC LIMIT 30").fetchall()]
    finally: db.close()
    return render(req,"admin.html",{
        "stats":stats,"tenders":tenders,"members":members,
        "hist":hist,"errors":errors,"notifs":notifs,
        "scrape_state":SState,"scrape_log":SLog.last(80),"pwd":pwd,
        "multi_available":HAS_MULTI,
        "multi_sources":list(MULTI_SRC.keys()) if HAS_MULTI else [],
    })


@router.get("/admin/scrape")
async def admin_scrape(req: Request, pwd:str="", sources:str="all"):
    cookie = req.cookies.get("admin_session","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return JSONResponse({"ok":False,"msg":"Non autorisé"},401)
    if SState.running: return JSONResponse({"ok":False,"msg":"Déjà en cours"})
    src_list=None if sources=="all" else [s.strip() for s in sources.split(",") if s.strip()]
    async def _run():
        all_new=[]
        try:
            if src_list is None or "marchespublics" in src_list:
                loop=asyncio.get_event_loop()
                new=await loop.run_in_executor(None, ScraperAgent.run)
                all_new.extend(new)
            if HAS_MULTI:
                extra=[s for s in (src_list or list(MULTI_SRC.keys())) if s!="marchespublics"]
                if extra:
                    db=get_db()
                    try: known=set(r[0] for r in db.execute("SELECT id FROM tenders").fetchall())
                    finally: db.close()
                    def run_m(): return run_all_scrapers(known,extra,SLog.add)
                    loop=asyncio.get_event_loop()
                    multi=await loop.run_in_executor(None,run_m)
                    if multi and ANTHROPIC_KEY:
                        multi=await AIClassifier.batch_classify(multi,ANTHROPIC_KEY,max_b=8)
                    saved=0
                    for t in multi:
                        td={"id":t.id,"objet":t.objet,"acheteur":t.acheteur,"region":t.region,"domaine":t.domaine,"type_marche":t.type_marche,"montant":t.montant,"date_publication":t.date_publication,"date_limite":t.date_limite,"description":t.description,"statut":t.statut,"url":t.source_url,"source":t.source,"contact":t.contact,"budget_min":t.budget_min,"budget_max":t.budget_max,"ai_score":t.ai_score,"ai_category":t.ai_category,"ai_reason":t.ai_reason}
                        if ScraperAgent._save(td): saved+=1; all_new.append(td) if t.statut=="actif" else None
                    SLog.add(f"Multi-source: {saved}/{len(multi)} sauvegardés")
            if all_new: NotifyAgent.notify_instant(all_new)
        finally: SState.running=False
    asyncio.create_task(_run())
    return JSONResponse({"ok":True,"msg":f"Scraper démarré — {sources}","multi":HAS_MULTI})


@router.get("/admin/scrape_stream")
async def scrape_stream(pwd:str=""):
    chk(pwd)
    async def gen():
        last=0
        while True:
            logs=SLog.entries[last:]
            for log in logs:
                state={"running":SState.running,"found":SState.found,"saved":SState.saved,"errors":SState.errors,"current":SState.current,"total":SState.total}
                yield f"data: {json.dumps({'log':log,'state':state})}\n\n"
            last=len(SLog.entries)
            if not SState.running and last>0:
                yield f"data: {json.dumps({'done':True,'state':{'saved':SState.saved}})}\n\n"; break
            await asyncio.sleep(0.7)
    return StreamingResponse(gen(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@router.get("/admin/test_notify")
async def admin_test(pwd:str="", chat_id:str=""):
    chk(pwd)
    sample=[
        {"objet":"Fourniture matériel informatique — 20 PC HP EliteDesk","acheteur":"Commune Urbaine de Rabat","region":"Rabat-Salé-Kénitra","domaine":"P818 - Informatique","type_marche":"Fournitures","montant":"280 000 DH","date_publication":datetime.now().strftime("%d/%m/%Y"),"date_limite":(datetime.now()+timedelta(days=14)).strftime("%d/%m/%Y"),"url":"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/46205","source":"marchespublics","ai_score":78},
        {"objet":"Travaux entretien voiries — Lot 3 Sud","acheteur":"Ministère de l'Intérieur","region":"Casablanca-Settat","domaine":"T301 - Travaux Routiers","type_marche":"Travaux","montant":"1 200 000 DH","date_publication":datetime.now().strftime("%d/%m/%Y"),"date_limite":(datetime.now()+timedelta(days=21)).strftime("%d/%m/%Y"),"url":"https://www.marchespublics.gov.ma/","source":"marchespublics","ai_score":55},
    ]
    results={}
    html=NotifyAgent.build_email(sample,"🧪 TEST Modern Business Notification Agent")
    ok,err=await NotifyAgent.send_email(GMAIL_USER,"🧪 TEST — Modern Business",html)
    results["email"]=f"✅ envoyé" if ok else f"❌ {err[:100]}"
    if chat_id:
        tg=NotifyAgent.build_telegram(sample,"🧪 TEST Modern Business Notification Agent")
        ok,err=await NotifyAgent.send_telegram(chat_id,tg)
        results["telegram"]=f"✅ envoyé" if ok else f"❌ {err[:80]}"
    db=get_db()
    try:
        results["queue"]={"pending":db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='pending'").fetchone()[0],"sent":db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='sent'").fetchone()[0],"failed":db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='failed'").fetchone()[0]}
        results["members"]={"total":db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],"with_tg":db.execute("SELECT COUNT(*) FROM members WHERE telegram!='' AND actif=1").fetchone()[0]}
    finally: db.close()
    return JSONResponse({"ok":True,"results":results})



@router.get("/admin/set_telegram")
async def admin_set_tg(pwd:str="", email:str="", chat_id:str=""):
    chk(pwd)
    db=get_db()
    try:
        db.execute("UPDATE members SET telegram=? WHERE email=?",(chat_id,email.lower().strip())); db.commit()
        ch=db.execute("SELECT changes()").fetchone()[0]
    finally: db.close()
    if ch and chat_id:
        asyncio.create_task(NotifyAgent.send_telegram(chat_id,f"✅ <b>Alertes Telegram activées!</b>\n\nCompte lié: {email}\n🌐 {SITE_URL}"))
    return JSONResponse({"ok":bool(ch),"updated":ch})


@router.get("/admin/activate")
async def admin_activate(pwd:str="", member_id:int=0, plan:str="pro"):
    chk(pwd); db=get_db()
    try: db.execute("UPDATE members SET plan=?,verified=1 WHERE id=?",(plan,member_id)); db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})


@router.get("/admin/delete_tender")
async def admin_del(pwd:str="", tid:str=""):
    chk(pwd); db=get_db()
    try: db.execute("DELETE FROM tenders WHERE id=?",(tid,)); db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})



@router.get("/admin/expire_now")
async def admin_expire_now(request: Request, pwd: str = ""):
    if pwd != ADMIN_PASS: return JSONResponse({"error":"unauthorized"},401)
    db = get_db()
    try:
        from datetime import date, datetime as _dt
        today = date.today()
        rows = db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall()
        exp = []
        for r in rows:
            dl = (r["date_limite"] or "").strip()
            if not dl or dl in ("N/A","—","-","null"): continue
            for fmt in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y","%d.%m.%Y"):
                try:
                    if _dt.strptime(dl, fmt).date() < today:
                        exp.append(r["id"]); break
                except: pass
        if exp:
            db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({chr(44).join([chr(63)]*len(exp))})", exp)
        db.execute("UPDATE tenders SET statut='expire' WHERE statut='actif' AND date_limite NOT LIKE '%/%' AND date_limite < date('now') AND date_limite!='' AND date_limite!='N/A'")
        db.commit()
        active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        db.close()
        return JSONResponse({"ok":True,"expired_python":len(exp),"active_remaining":active})
    except Exception as e:
        try: db.close()
        except: pass
        return JSONResponse({"error":str(e)},500)


@router.get("/admin/cleanup")
async def admin_cleanup(pwd:str=""):
    chk(pwd); db=get_db()
    try:
        db.execute("DELETE FROM tenders WHERE statut IN ('expire','annule') AND date_extraction < date('now','-60 days')")
        db.execute("DELETE FROM chats WHERE created_at < date('now','-7 days')")
        db.execute("DELETE FROM notif_queue WHERE status='sent' AND sent_at < date('now','-30 days')")
        db.execute("DELETE FROM tenders WHERE length(objet) < 10")
        r=db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        db.commit()
    finally: db.close()
    return JSONResponse({"ok":True,"remaining":r})


@router.get("/admin/cleanup_tenders")
async def admin_cleanup_tenders(pwd:str=""):
    chk(pwd); db=get_db()
    try:
        bad=["Liste des avis d'achat","ConsultationsRésultats","Accueil","Se connecter"]
        deleted=0
        for p in bad:
            db.execute("DELETE FROM tenders WHERE objet LIKE ?",(f"%{p}%",))
            deleted+=db.execute("SELECT changes()").fetchone()[0]
        db.execute("DELETE FROM tenders WHERE length(objet) < 10")
        deleted+=db.execute("SELECT changes()").fetchone()[0]
        db.commit()
    finally: db.close()
    return JSONResponse({"ok":True,"deleted":deleted})


@router.get("/admin/resolve_error")
async def admin_resolve(pwd:str="", eid:int=0):
    chk(pwd); db=get_db()
    try: db.execute("UPDATE agent_errors SET resolved=1 WHERE id=?",(eid,)); db.commit()
    finally: db.close()
    return JSONResponse({"ok":True})


@router.get("/admin/notify_status")
async def admin_notify_status(pwd:str=""):
    chk(pwd); db=get_db()
    try:
        members=[dict(r) for r in db.execute("SELECT id,nom,email,telegram,notif_email,notif_tg,secteur FROM members WHERE actif=1").fetchall()]
        queue  =[dict(r) for r in db.execute("SELECT channel,status,recipient,error,attempts,created_at FROM notif_queue ORDER BY id DESC LIMIT 20").fetchall()]
    finally: db.close()
    return JSONResponse({
        "brevo":      "✅" if BREVO_KEY else "❌ non configuré (recommandé)",
        "resend":     "✅" if RESEND_KEY else "❌",
        "gmail":      "✅" if GMAIL_PASS else "❌",
        "telegram":   "✅" if TELEGRAM_BOT else "❌",
        "anthropic":  "✅" if ANTHROPIC_KEY else "❌",
        "members":    [{"nom":m["nom"],"email":m["email"],"telegram":m["telegram"] or "❌","secteur":m["secteur"] or "—","notif_email":bool(m["notif_email"]),"notif_tg":bool(m["notif_tg"])} for m in members],
        "queue_last": queue,
    })


@router.get("/admin/test_digest")
async def admin_test_digest(pwd:str=""):
    chk(pwd); NotifyAgent.notify_digest()
    return JSONResponse({"ok":True,"msg":"Digest mis en file"})

# ══════════════════════════════════════════════════════
# INFRA
# ══════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════
# ROUTES ARABES /ar/*
# ══════════════════════════════════════════════════════


@router.get("/ar")

@router.get("/ar/")
async def ar_home(req: Request):
    db = get_db()
    try:
        stats = {
            "tenders_total":  db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
            "tenders_active": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "easy_to_win":    db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND ai_score>=70").fetchone()[0],
            "members":        db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "members_tg":     db.execute("SELECT COUNT(*) FROM members WHERE telegram IS NOT NULL AND telegram!=''").fetchone()[0],
        }
        tenders = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE statut='actif' ORDER BY ai_score DESC, date_extraction DESC LIMIT 6"
        ).fetchall()]
        sources = [dict(r) for r in db.execute(
            "SELECT source, COUNT(*) as active FROM tenders WHERE statut='actif' GROUP BY source ORDER BY active DESC"
        ).fetchall()]
    finally:
        db.close()
    return render(req, "landing_ar.html", {
         "stats": stats, "tenders": tenders,
        "sources": sources, "member": get_member(req),
        "SECTEURS_LIST": SECTEURS_LIST,
    })



@router.get("/ar/tenders")
async def ar_tenders(req: Request, q: str = "", code_f: str = "", easy: str = "",
                     region: str = "", page: int = 1):
    db = get_db(); per = 18
    conds = ["statut='actif'"]; params: list = []
    if q:
        conds.append("(objet LIKE ? OR acheteur LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    if code_f:
        conds.append("domaine LIKE ?"); params.append(f"{code_f}%")
    if easy == "1":
        conds.append("ai_score >= 70")
    where = " AND ".join(conds)
    try:
        total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {where}", params).fetchone()[0]
        tenders = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE {where} ORDER BY ai_score DESC, date_extraction DESC LIMIT ? OFFSET ?",
            params + [per, (page-1)*per]
        ).fetchall()]
    finally:
        db.close()
    return render(req, "tenders_ar.html", {
         "tenders": tenders, "total": total,
        "page": page, "pages": max(1, (total+per-1)//per),
        "q": q, "code_f": code_f, "easy": easy,
        "member": get_member(req), "SECTEURS_LIST": SECTEURS_LIST,
    })



@router.get("/ar/register")
async def ar_register_get(req: Request):
    if get_member(req):
        return RedirectResponse("/dashboard", 302)
    return render(req, "register_ar.html", {
         "error": None,
        "member": None, "SECTEURS_LIST": SECTEURS_LIST,
    })



@router.post("/ar/register")
async def ar_register_post(req: Request, nom:str=Form(""), entreprise:str=Form(""),
    email:str=Form(""), phone:str=Form(""), secteur:str=Form(""),
    ville:str=Form(""), password:str=Form("")):
    return await reg_post(req, nom, entreprise, email, phone, secteur, ville, password)



@router.get("/ar/login")
async def ar_login_get(req: Request):
    db = get_db()
    try:
        stats = {
            "tenders_active": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "members": db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
        }
    finally:
        db.close()
    return render(req, "login.html", {
         "error": None, "reset": False,
        "member": None, "stats": stats,
    })




@router.post("/api/v1/ingest")
async def api_ingest(req: Request):
    """Reçoit les marchés du scraper local (IP Maroc) et les sauvegarde"""
    try:
        body = await req.json()
        if body.get("pwd") != ADMIN_PASS:
            return JSONResponse({"error":"unauthorized"}, 401)
        tenders = body.get("tenders", [])
        if not tenders:
            return JSONResponse({"ok":True,"saved":0})
        db = get_db(); saved = 0
        for t in tenders:
            if not t.get("id") or not t.get("objet"): continue
            # Skip expired — check both date_limite field and objet
            dl = str(t.get("date_limite","")).strip()
            if dl and ClassifierAgent.is_expired(dl): continue
            # Also check full objet text for embedded dates
            objet_text = str(t.get("objet",""))
            if ClassifierAgent.is_expired(objet_text): continue
            # Skip near-duplicate objet (first 60 chars)
            obj_key = (t.get("objet","")[:60]).strip().lower()
            if len(obj_key) > 10:
                dup = db.execute(
                    "SELECT id FROM tenders WHERE LOWER(SUBSTR(objet,1,60))=? AND date_extraction >= date(\'now\',\'-1 day\')",
                    (obj_key,)
                ).fetchone()
                if dup: continue  # déjà en DB
            # Classify with AI
            domaine = ClassifierAgent.secteur((t.get("objet","") + " " + t.get("description",""))[:300])
            region  = ClassifierAgent.region((t.get("acheteur","") + " " + t.get("objet",""))[:300])
            score   = 50
            try:
                changed = db.execute("""INSERT OR IGNORE INTO tenders
                    (id,objet,acheteur,region,domaine,type_marche,montant,
                     date_publication,date_limite,description,statut,url,source,
                     ai_score,date_extraction)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    str(t.get("id",""))[:80],
                    str(t.get("objet",""))[:400],
                    str(t.get("acheteur",""))[:200],
                    str(region or t.get("region","Maroc"))[:100],
                    str(domaine or t.get("domaine",""))[:80],
                    str(ClassifierAgent.type_marche(t.get("objet","")))[:40],
                    str(t.get("montant",""))[:80],
                    datetime.now().strftime("%d/%m/%Y"),
                    str(t.get("date_limite",""))[:20],
                    str(t.get("description",""))[:2000],
                    str(t.get("statut","actif")),
                    str(t.get("source_url",""))[:400],
                    str(t.get("source","local"))[:40],
                    score,
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                )).rowcount
                if changed: saved += 1
            except Exception as e:
                logger.error(f"[ingest] {e}")
        db.commit(); db.close()
        SLog.add(f"[Ingest] +{saved}/{len(tenders)} depuis scraper local")
        return JSONResponse({"ok":True,"saved":saved,"total":len(tenders)})
    except Exception as e:
        return JSONResponse({"error":str(e)},500)



# ═══════════════════════════════════════════════════
# EXPORT CSV
# ═══════════════════════════════════════════════════

@router.get("/tenders/export")
async def export_csv(req: Request, q:str="", code_f:str="", region:str="", easy:str=""):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", 302)
    db = get_db()
    conds = ["statut='actif'"]; params = []
    if q:
        conds.append("(objet LIKE ? OR acheteur LIKE ?)"); params += [f"%{q}%",f"%{q}%"]
    if code_f:
        conds.append("domaine LIKE ?"); params.append(f"{code_f}%")
    if region:
        conds.append("region LIKE ?"); params.append(f"%{region}%")
    if easy == "1":
        conds.append("ai_score >= 70")
    where = " AND ".join(conds)
    rows = db.execute(
        f"SELECT objet,acheteur,region,domaine,montant,date_publication,date_limite,source,ai_score,url FROM tenders WHERE {where} ORDER BY ai_score DESC LIMIT 2000",
        params
    ).fetchall()
    db.close()
    import io, csv as csv_mod
    buf = io.StringIO()
    w = csv_mod.writer(buf)
    w.writerow(["Objet","Acheteur","Région","Domaine","Montant","Publication","Limite","Source","Score","URL"])
    for r in rows:
        w.writerow([r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],r[9]])
    buf.seek(0)
    from fastapi.responses import StreamingResponse
    fname = f"marches_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter(['﻿' + buf.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={fname}"}
    )


# ═══════════════════════════════════════════════════
# FAVORIS
# ═══════════════════════════════════════════════════

@router.post("/tenders/{tid}/fav")
async def toggle_fav(req: Request, tid: str):
    m = get_member(req)
    if not m:
        return JSONResponse({"error": "login required"}, 401)
    db = get_db()
    try:
        ex = db.execute(
            "SELECT id FROM favoris WHERE member_id=? AND tender_id=?",
            (m["id"], tid)
        ).fetchone()
        if ex:
            db.execute("DELETE FROM favoris WHERE member_id=? AND tender_id=?", (m["id"], tid))
            db.commit(); db.close()
            return JSONResponse({"fav": False})
        db.execute(
            "INSERT OR IGNORE INTO favoris(member_id,tender_id,created_at) VALUES(?,?,?)",
            (m["id"], tid, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        db.commit(); db.close()
        return JSONResponse({"fav": True})
    except Exception as e:
        try: db.close()
        except: pass
        return JSONResponse({"error": str(e)}, 500)



@router.get("/favoris", response_class=HTMLResponse)
async def favoris_page(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login?next=/favoris", 302)
    db = get_db()
    try:
        fav_rows = db.execute(
            "SELECT tender_id FROM favoris WHERE member_id=? ORDER BY created_at DESC",
            (m["id"],)
        ).fetchall()
        fav_ids = [r["tender_id"] for r in fav_rows]
        tenders = []
        if fav_ids:
            ph = ",".join(["?"]*len(fav_ids))
            tenders = [dict(r) for r in db.execute(
                f"SELECT * FROM tenders WHERE id IN ({ph}) ORDER BY ai_score DESC",
                fav_ids
            ).fetchall()]
    finally:
        db.close()
    return render(req, "tenders.html", {
        "tenders": tenders, "total": len(tenders), "page": 1, "pages": 1,
        "q": "", "code_f": "", "region": "", "easy": "", "source_f": "",
        "member": m, "page_title": "★ Mes Favoris",
        "SECTEURS_LIST": SECTEURS_LIST, "REGIONS": REGIONS,
    })


# ═══════════════════════════════════════════════════
# CONTACT POST
# ═══════════════════════════════════════════════════

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

@router.get("/admin/backup")
async def admin_backup(req: Request, pwd: str = ""):
    cookie = req.cookies.get("admin_session", "")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return RedirectResponse("/admin/login", 302)
    import shutil
    bp = DB_PATH.replace(".db", f"_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db")
    shutil.copy2(DB_PATH, bp)
    from fastapi.responses import FileResponse
    return FileResponse(bp, filename=os.path.basename(bp), media_type="application/octet-stream")



# ══════════════════════════════════════════════════════
# ROUTES ARABES /ar/*
# ══════════════════════════════════════════════════════



@router.get("/admin/clear_db")
async def admin_clear_db(req: Request, pwd: str = "", confirm: str = ""):
    """Vide toutes les tables de tenders"""
    cookie = req.cookies.get("admin_session","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return RedirectResponse("/admin/login",302)
    if confirm != "yes":
        return HTMLResponse("""<html><body style="font-family:monospace;background:#030303;color:#f3eee7;padding:40px">
<h2>⚠️ Confirmer la suppression</h2>
<p>Ceci va supprimer TOUS les marchés de la base de données.</p>
<a href="/admin/clear_db?pwd=""" + pwd + """&confirm=yes" 
   style="background:#c46060;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none"
   onclick="return confirm('SUPPRIMER TOUS LES MARCHÉS?')">
   ✓ Confirmer la suppression
</a>
&nbsp;<a href="/admin?pwd=""" + pwd + """" style="color:#888">Annuler</a>
</body></html>""")
    db = get_db()
    try:
        count = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        for tbl in ["tenders","favoris","notif_queue","scrape_runs","agent_errors","api_keys"]:
            try: db.execute(f"DELETE FROM {tbl}")
            except: pass
        db.commit()
        db.close()
        SLog.add(f"[Admin] Base vidée: {count} marchés supprimés")
        return JSONResponse({"ok":True,"deleted":count,"msg":f"{count} marchés supprimés"})
    except Exception as e:
        try: db.close()
        except: pass
        return JSONResponse({"error":str(e)},500)



@router.get("/admin/healing")
async def admin_healing(req: Request, pwd: str = ""):
    """Rapport du SelfHealingAgent"""
    cookie = req.cookies.get("admin_session","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return RedirectResponse("/admin/login",302)
    report = SelfHealingAgent.get_report()
    return JSONResponse(report)



@router.get("/admin/heal_now")
async def admin_heal_now(req: Request, pwd: str = ""):
    """Force une réparation immédiate"""
    cookie = req.cookies.get("admin_session","")
    if pwd != ADMIN_PASS and cookie != ADMIN_PASS:
        return RedirectResponse("/admin/login",302)
    db = get_db()
    try:
        schema = SelfHealingAgent.repair_schema(db)
        expired = SelfHealingAgent.expire_tenders(db)
        clean = SelfHealingAgent.clean_db(db)
        active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        return JSONResponse({
            "ok": True,
            "schema_repairs": len([r for r in schema if r.startswith("✅")]),
            "expired": expired,
            "dupes_removed": clean.get("dupes_removed",0),
            "active_tenders": active,
        })
    finally:
        db.close()


@router.get("/health")
async def health():
    db=get_db()
    try: active=db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    finally: db.close()
    return JSONResponse({"status":"ok","version":"5.0","brand":BRAND,"active_tenders":active,
        "agents":["ScraperAgent","ClassifierAgent","NotifyAgent","MonitorAgent","ChatAgent"],
        "multi_source":HAS_MULTI})


@router.get("/metrics")
async def metrics(pwd:str=""):
    if pwd!=ADMIN_PASS: raise HTTPException(403)
    return JSONResponse({"counters":dict(COUNTERS),"scraper":{"running":SState.running,"saved":SState.saved}})


@router.get("/sitemap.xml")
async def sitemap():
    xml=f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{SITE_URL}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>
<url><loc>{SITE_URL}/tenders</loc><changefreq>hourly</changefreq><priority>0.95</priority></url>
<url><loc>{SITE_URL}/marketplace</loc><changefreq>hourly</changefreq><priority>0.9</priority></url>
<url><loc>{SITE_URL}/annuaire</loc><changefreq>daily</changefreq><priority>0.7</priority></url>
<url><loc>{SITE_URL}/contact</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>
<url><loc>{SITE_URL}/ar</loc><changefreq>daily</changefreq><priority>0.9</priority></url>
  <url><loc>{SITE_URL}/ar/tenders</loc><changefreq>hourly</changefreq><priority>0.8</priority></url>
  <url><loc>{SITE_URL}/tarifs</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
<url><loc>{SITE_URL}/a-propos</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>
<url><loc>{SITE_URL}/conditions</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>
</urlset>"""
    return Response(xml,media_type="application/xml")


@router.get("/robots.txt")
async def robots():
    return Response(f"User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\nSitemap: {SITE_URL}/sitemap.xml",media_type="text/plain")