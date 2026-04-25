"""SOURCE v2.0 — Marchés Publics Maroc"""
import asyncio, json, logging, os, urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime
from collections import defaultdict
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from app.core.config import cfg
from app.core.database import get_db, init_db
from app.core.security import hash_pw, verify_pw, make_token, sign, get_member, is_admin, valid_email, valid_pw, days_left, plan_ok
from app.core.stx10 import classify, STX10, top3
from app.services.notifications import tg_admin, tg_send, test_notif, dispatch

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s %(message)s",datefmt="%H:%M:%S")
logger=logging.getLogger("source")

_rl=defaultdict(list)
def rate_ok(ip,limit=60,win=60):
    now=datetime.now().timestamp()
    _rl[ip]=[t for t in _rl[ip] if now-t<win]
    if len(_rl[ip])>=limit: return False
    _rl[ip].append(now); return True
def get_ip(req): return req.headers.get("x-forwarded-for",req.client.host or "?").split(",")[0].strip()

class St:
    scanning=False; last_scan="—"; max_id=0

async def _scheduler():
    await asyncio.sleep(20)
    while True:
        try:
            St.scanning=True
            from app.services.scraper import scrape_new
            db=get_db(); new=scrape_new(db,St.max_id)
            if new: dispatch(new,db)
            db.close(); St.last_scan=datetime.now().strftime("%H:%M")
        except Exception as e: logger.error(f"[Sched] {e}")
        finally: St.scanning=False
        await asyncio.sleep(cfg.SCAN_INTERVAL_MIN*60)

@asynccontextmanager
async def lifespan(app):
    init_db()
    logger.info(f"SOURCE v{cfg.APP_VERSION} | TG:{'✅' if cfg.TELEGRAM_BOT else '❌'} | AI:{'✅' if cfg.GROQ_API_KEY else '❌'}")
    try: tg_admin(f"🚀 SOURCE v{cfg.APP_VERSION}\n{cfg.SITE_URL}")
    except: pass
    asyncio.create_task(_scheduler())
    yield

app=FastAPI(title="SOURCE",version=cfg.APP_VERSION,lifespan=lifespan,docs_url=None,redoc_url=None)
templates=Jinja2Templates(directory="templates")
os.makedirs("static",exist_ok=True)
app.mount("/static",StaticFiles(directory="static"),name="static")

# Custom filters
def _from_json(s):
    try: return json.loads(s or "[]")
    except: return []
templates.env.filters["from_json"]=_from_json
templates.env.filters["urlencode"]=urllib.parse.quote

def render(req,tpl,ctx=None,status=200):
    ctx=ctx or {}
    ctx.setdefault("request",req)
    ctx.setdefault("member",get_member(req))
    ctx.setdefault("cfg",cfg)
    ctx.setdefault("now",datetime.now())
    ctx.setdefault("days_left",days_left)
    ctx.setdefault("STX10",STX10)
    return templates.TemplateResponse(tpl,ctx,status_code=status)

def stats():
    db=get_db()
    try:
        tot=db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        tod=db.execute("SELECT COUNT(*) FROM tenders WHERE DATE(scraped_at)=DATE('now')").fetchone()[0]
        mem=db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0]
        return {"tenders":tot,"today":tod,"members":mem}
    finally: db.close()

# ═══ LANDING ═══
@app.get("/",response_class=HTMLResponse)
async def landing(req:Request):
    if get_member(req): return RedirectResponse("/dashboard",302)
    return render(req,"landing.html",{"stats":stats()})

# ═══ AUTH ═══
@app.get("/register",response_class=HTMLResponse)
async def reg_page(req:Request):
    if get_member(req): return RedirectResponse("/dashboard",302)
    return render(req,"register.html",{"error":"","lang":"fr"})

@app.post("/register",response_class=HTMLResponse)
async def reg_post(req:Request,nom:str=Form(""),email:str=Form(""),
                   password:str=Form(""),confirm:str=Form(""),lang:str=Form("fr")):
    nom=nom.strip(); email=email.strip().lower(); err=""
    if not nom or len(nom)<2: err="Nom trop court." if lang=="fr" else "الاسم قصير جداً."
    elif not valid_email(email): err="Email invalide." if lang=="fr" else "البريد غير صالح."
    elif password!=confirm: err="Mots de passe différents." if lang=="fr" else "كلمات المرور غير متطابقة."
    else:
        ok,msg=valid_pw(password)
        if not ok: err=msg
    if err: return render(req,"register.html",{"error":err,"lang":lang})
    db=get_db()
    try:
        if db.execute("SELECT id FROM members WHERE email=?",(email,)).fetchone():
            return render(req,"register.html",{"error":"Email déjà utilisé." if lang=="fr" else "البريد مستخدم.","lang":lang})
        tok=make_token()
        db.execute("INSERT INTO members(nom,email,password_hash,plan,actif,session_token,created_at,lang,onboarded) VALUES(?,?,?,'free',1,?,?,?,0)",
                   (nom,email,hash_pw(password),tok,datetime.now().isoformat(),lang))
        db.commit()
        try: tg_admin(f"👤 Nouveau: <b>{nom}</b>\n📧 {email}")
        except: pass
        resp=RedirectResponse("/onboarding",302)
        resp.set_cookie("_s",tok,max_age=60*60*24*30,httponly=True,samesite="lax")
        return resp
    except Exception as e:
        logger.error(f"[register] {e}")
        return render(req,"register.html",{"error":"Erreur serveur.","lang":lang})
    finally: db.close()

@app.get("/login",response_class=HTMLResponse)
async def login_page(req:Request,next:str="/dashboard"):
    if get_member(req): return RedirectResponse(next or "/dashboard",302)
    return render(req,"login.html",{"error":"","next":next})

@app.post("/login",response_class=HTMLResponse)
async def login_post(req:Request,email:str=Form(""),password:str=Form(""),
                     next_url:str=Form("/dashboard"),lang:str=Form("fr")):
    if not rate_ok(get_ip(req),10,60):
        return render(req,"login.html",{"error":"Trop de tentatives.","next":next_url})
    email=email.strip().lower()
    db=get_db()
    try:
        row=db.execute("SELECT * FROM members WHERE email=? AND actif=1",(email,)).fetchone()
        if not row or not verify_pw(password,row["password_hash"]):
            return render(req,"login.html",{"error":"Email ou mot de passe incorrect." if lang=="fr" else "بيانات غير صحيحة.","next":next_url})
        tok=make_token()
        db.execute("UPDATE members SET session_token=? WHERE id=?",(tok,row["id"])); db.commit()
        resp=RedirectResponse(next_url or "/dashboard",302)
        resp.set_cookie("_s",tok,max_age=60*60*24*30,httponly=True,samesite="lax"); return resp
    finally: db.close()

@app.get("/logout")
async def logout(req:Request):
    m=get_member(req)
    if m:
        db=get_db(); db.execute("UPDATE members SET session_token='' WHERE id=?",(m["id"],)); db.commit(); db.close()
    resp=RedirectResponse("/",302); resp.delete_cookie("_s"); return resp

# ═══ ONBOARDING ═══
@app.get("/onboarding",response_class=HTMLResponse)
async def onboarding_page(req:Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    if m.get("onboarded"): return RedirectResponse("/dashboard",302)
    return render(req,"onboarding.html",{"lang":m.get("lang","fr")})

@app.post("/onboarding")
async def onboarding_post(req:Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    form=await req.form()
    codes=list(set(c for c in form.getlist("stx10_codes") if c in STX10))
    regions=list(set(r for r in form.getlist("regions") if r))
    lang=form.get("lang",m.get("lang","fr"))
    db=get_db()
    try:
        db.execute("UPDATE members SET stx10_codes=?,regions=?,onboarded=1,lang=? WHERE id=?",
                   (json.dumps(codes),json.dumps(regions),lang,m["id"])); db.commit()
    finally: db.close()
    return RedirectResponse("/dashboard",302)

# ═══ DASHBOARD ═══
@app.get("/dashboard",response_class=HTMLResponse)
async def dashboard(req:Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login?next=/dashboard",302)
    if not m.get("onboarded"): return RedirectResponse("/onboarding",302)
    db=get_db()
    try:
        st=stats()
        codes=json.loads(m.get("stx10_codes","[]") or "[]")
        alerts=0
        if codes:
            ph=",".join("?"*len(codes))
            alerts=db.execute(f"SELECT COUNT(*) FROM tenders WHERE statut='actif' AND stx10_code IN ({ph})",codes).fetchone()[0]
        favs=db.execute("SELECT COUNT(*) FROM favorites WHERE member_id=?",(m["id"],)).fetchone()[0]
        # Échéances proches
        soon_rows=db.execute("SELECT date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall()
        soon=sum(1 for r in soon_rows if 0<=days_left(r[0])[0]<=7)
        top_stx10=db.execute("SELECT stx10_code,stx10_label,COUNT(*) cnt FROM tenders WHERE statut='actif' AND stx10_code!='' GROUP BY stx10_code ORDER BY cnt DESC LIMIT 6").fetchall()
        recent=db.execute("SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 15").fetchall()
        matched=[]
        if codes:
            ph=",".join("?"*len(codes))
            matched=db.execute(f"SELECT * FROM tenders WHERE statut='actif' AND stx10_code IN ({ph}) ORDER BY scraped_at DESC LIMIT 6",codes).fetchall()
        return render(req,"dashboard.html",{
            "stats":st,"alerts":alerts,"favs":favs,"soon":soon,
            "top_stx10":[dict(r) for r in top_stx10],
            "recent":[dict(r) for r in recent],
            "matched":[dict(r) for r in matched],
            "scanning":St.scanning,"last_scan":St.last_scan,
        })
    finally: db.close()

# ═══ TENDERS ═══
@app.get("/tenders",response_class=HTMLResponse)
async def tenders(req:Request,q:str="",stx10:str="",region:str="",page:int=1):
    m=get_member(req)
    if not m: return RedirectResponse("/login?next=/tenders",302)
    PER=20 if plan_ok(m,"unlimited") else 10
    if page>1 and not plan_ok(m,"unlimited"): return RedirectResponse("/tarifs?upgrade=1",302)
    offset=(page-1)*PER
    db=get_db()
    try:
        w,p=["statut='actif'"],[]
        if q: w.append("(objet LIKE ? OR acheteur LIKE ?)"); p+=[f"%{q}%",f"%{q}%"]
        if stx10: w.append("stx10_code=?"); p.append(stx10)
        if region: w.append("region LIKE ?"); p.append(f"%{region}%")
        wh=" AND ".join(w)
        total=db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}",p).fetchone()[0]
        rows=db.execute(f"SELECT * FROM tenders WHERE {wh} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",p+[PER,offset]).fetchall()
        regs=db.execute("SELECT DISTINCT region FROM tenders WHERE statut='actif' AND region!='' ORDER BY region").fetchall()
        stx_db=db.execute("SELECT DISTINCT stx10_code FROM tenders WHERE statut='actif' AND stx10_code!=''").fetchall()
        return render(req,"tenders.html",{
            "tenders":[dict(r) for r in rows],"total":total,"page":page,"pages":(total+PER-1)//PER,
            "q":q,"stx10":stx10,"region":region,
            "regions":[r[0] for r in regs],"stx_db":[r[0] for r in stx_db],
        })
    finally: db.close()

@app.get("/tenders/{tid}",response_class=HTMLResponse)
async def tender_detail(req:Request,tid:str):
    m=get_member(req)
    if not m: return RedirectResponse(f"/login?next=/tenders/{tid}",302)
    db=get_db()
    try:
        t=db.execute("SELECT * FROM tenders WHERE id=?",(tid,)).fetchone()
        if not t: return render(req,"404.html",{},404)
        t=dict(t); n,dl=days_left(t.get("date_limite",""))
        similar=db.execute("SELECT * FROM tenders WHERE stx10_code=? AND id!=? AND statut='actif' ORDER BY scraped_at DESC LIMIT 4",(t.get("stx10_code",""),tid)).fetchall()
        is_fav=bool(db.execute("SELECT id FROM favorites WHERE member_id=? AND tender_id=?",(m["id"],tid)).fetchone())
        wa=""
        if m.get("whatsapp"): wa=__import__("app.services.notifications",fromlist=["wa_link"]).wa_link(m["whatsapp"],t,m.get("lang","fr"))
        return render(req,"detail.html",{"t":t,"dl":n,"dl_label":dl,"similar":[dict(r) for r in similar],"is_fav":is_fav,"wa":wa})
    finally: db.close()

@app.post("/favorites/{tid}")
async def toggle_fav(req:Request,tid:str):
    m=get_member(req)
    if not m: return JSONResponse({"ok":False},401)
    db=get_db()
    try:
        ex=db.execute("SELECT id FROM favorites WHERE member_id=? AND tender_id=?",(m["id"],tid)).fetchone()
        if ex: db.execute("DELETE FROM favorites WHERE member_id=? AND tender_id=?",(m["id"],tid)); db.commit(); return {"ok":True,"action":"removed"}
        db.execute("INSERT OR IGNORE INTO favorites(member_id,tender_id,added_at) VALUES(?,?,?)",(m["id"],tid,datetime.now().isoformat())); db.commit(); return {"ok":True,"action":"added"}
    finally: db.close()

# ═══ SETTINGS ═══
@app.get("/settings",response_class=HTMLResponse)
async def settings_page(req:Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login?next=/settings",302)
    return render(req,"settings.html",{"member_codes":json.loads(m.get("stx10_codes","[]") or "[]")})

@app.post("/settings")
async def settings_post(req:Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    form=await req.form()
    codes=list(set(c for c in form.getlist("stx10_codes") if c in STX10))
    regions=list(set(r for r in form.getlist("regions") if r))
    db=get_db()
    try:
        db.execute("UPDATE members SET stx10_codes=?,regions=?,telegram=?,whatsapp=?,notif_tg=?,notif_email=?,notif_wa=?,lang=? WHERE id=?",
                   (json.dumps(codes),json.dumps(regions),form.get("telegram","").strip(),
                    form.get("whatsapp","").strip(),1 if form.get("notif_tg") else 0,
                    1 if form.get("notif_email") else 0,1 if form.get("notif_wa") else 0,
                    form.get("lang",m.get("lang","fr")),m["id"])); db.commit()
    finally: db.close()
    return RedirectResponse("/settings?saved=1",302)

# ═══ TARIFS ═══
@app.get("/tarifs",response_class=HTMLResponse)
async def tarifs(req:Request): return render(req,"tarifs.html",{})

@app.post("/tarifs/request")
async def tarifs_req(req:Request,plan:str=Form("pro"),nom:str=Form(""),email:str=Form("")):
    m=get_member(req); name=m.get("nom","") if m else nom; mail=m.get("email","") if m else email
    db=get_db()
    try:
        db.execute("INSERT INTO payments(member_id,plan,nom,email,status,created_at) VALUES(?,?,?,?,?,?)",
                   (m["id"] if m else None,plan,name,mail,"pending",datetime.now().isoformat())); db.commit()
        try: tg_admin(f"💳 Demande {plan.upper()}\n{name} · {mail}")
        except: pass
    finally: db.close()
    msg=f"Bonjour, je veux activer le plan {plan.upper()} SOURCE. Nom: {name} Email: {mail}"
    return RedirectResponse(f"https://wa.me/{cfg.PAYMENT_PHONE}?text={urllib.parse.quote(msg)}",302)

# ═══ AI ═══
@app.get("/ai/chat",response_class=HTMLResponse)
async def ai_page(req:Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login?next=/ai/chat",302)
    return render(req,"ai_chat.html",{"ai_ok":bool(cfg.GROQ_API_KEY)})

@app.get("/api/ai/chat")
async def api_ai(req:Request,q:str=""):
    m=get_member(req)
    if not m: return JSONResponse({"ok":False,"msg":"Auth requise"},401)
    if not q.strip(): return JSONResponse({"ok":False,"msg":"Vide"})
    if not cfg.GROQ_API_KEY: return JSONResponse({"ok":False,"msg":"IA non configurée"})
    try:
        import requests as rq
        st=stats(); lang=m.get("lang","fr")
        sys=f"""Assistant SOURCE expert marchés publics marocains.
Marchés actifs:{st['tenders']} | Plan:{m.get('plan','free')}
{'Réponds en arabe.' if lang=='ar' else 'Réponds en français, concis, max 3 paragraphes.'}"""
        r=rq.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {cfg.GROQ_API_KEY}"},
            json={"model":cfg.AI_MODEL,"max_tokens":400,"temperature":0.5,
                  "messages":[{"role":"system","content":sys},{"role":"user","content":q}]},timeout=15)
        if r.status_code==200: return {"ok":True,"answer":r.json()["choices"][0]["message"]["content"]}
        return JSONResponse({"ok":False,"msg":f"IA {r.status_code}"})
    except Exception as e: return JSONResponse({"ok":False,"msg":str(e)[:80]})

@app.get("/api/ai/summarize/{tid}")
async def api_summarize(req:Request,tid:str):
    m=get_member(req)
    if not m: return JSONResponse({"ok":False},401)
    db=get_db()
    try:
        t=db.execute("SELECT * FROM tenders WHERE id=?",(tid,)).fetchone()
        if not t: return JSONResponse({"ok":False,"msg":"Introuvable"})
        t=dict(t)
        if t.get("ai_summary"): return {"ok":True,"summary":t["ai_summary"]}
        if not cfg.GROQ_API_KEY: return JSONResponse({"ok":False,"msg":"IA non configurée"})
        import requests as rq
        lang=m.get("lang","fr")
        prompt=f"""Résume ce marché public marocain en 3 points {'en arabe' if lang=='ar' else 'en français'}:
1. Objet exact  2. Profil idéal  3. Points d'attention
Marché: {t['objet'][:400]} | Acheteur: {t.get('acheteur','')} | Deadline: {t.get('date_limite','')}
Max 80 mots."""
        r=rq.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {cfg.GROQ_API_KEY}"},
            json={"model":cfg.AI_MODEL,"max_tokens":200,"messages":[{"role":"user","content":prompt}]},timeout=12)
        if r.status_code==200:
            s=r.json()["choices"][0]["message"]["content"]
            db.execute("UPDATE tenders SET ai_summary=? WHERE id=?",(s,tid)); db.commit()
            return {"ok":True,"summary":s}
        return JSONResponse({"ok":False,"msg":"IA indisponible"})
    finally: db.close()

@app.get("/api/stx10/classify")
async def api_classify(req:Request,text:str=""):
    m=get_member(req)
    if not m: return JSONResponse({"ok":False},401)
    if not text.strip(): return JSONResponse({"ok":False})
    return {"ok":True,"primary":classify(text),"top3":top3(text)}

# ═══ API REST ═══
@app.get("/api/v1/tenders")
async def api_tenders(req:Request,q:str="",stx10:str="",limit:int=20,page:int=1):
    if not rate_ok(get_ip(req)): return JSONResponse({"ok":False,"msg":"Rate limit"},429)
    m=get_member(req)
    if not m: return JSONResponse({"ok":False,"msg":"Auth requise"},401)
    if not plan_ok(m,"tg"): return JSONResponse({"ok":False,"msg":"API réservée Pro+"},403)
    db=get_db()
    try:
        w,p=["statut='actif'"],[]
        if q: w.append("objet LIKE ?"); p.append(f"%{q}%")
        if stx10: w.append("stx10_code=?"); p.append(stx10)
        wh=" AND ".join(w); offset=(page-1)*limit
        total=db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}",p).fetchone()[0]
        rows=db.execute(f"SELECT * FROM tenders WHERE {wh} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",p+[min(limit,100),offset]).fetchall()
        return {"ok":True,"total":total,"page":page,"tenders":[dict(r) for r in rows]}
    finally: db.close()

@app.get("/api/v1/stats")
async def api_stats(req:Request):
    m=get_member(req)
    if not m: return JSONResponse({"ok":False},401)
    return {"ok":True,**stats(),"scanning":St.scanning,"last_scan":St.last_scan}

@app.get("/export/csv")
async def export_csv(req:Request):
    m=get_member(req)
    if not m: return RedirectResponse("/login",302)
    if not plan_ok(m,"tg"): return RedirectResponse("/tarifs?upgrade=1",302)
    db=get_db()
    try: rows=db.execute("SELECT objet,acheteur,stx10_code,stx10_label,region,montant,date_publication,date_limite,url FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 2000").fetchall()
    finally: db.close()
    import csv,io; out=io.StringIO(); w=csv.writer(out)
    w.writerow(["Objet","Acheteur","STX10","Libellé","Région","Montant","Publication","Limite","URL"])
    for r in rows: w.writerow(list(r))
    fn=f"source_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(out.getvalue().encode("utf-8-sig"),media_type="text/csv",headers={"Content-Disposition":f"attachment; filename={fn}"})

# ═══ ADMIN ═══
@app.get("/admin/login",response_class=HTMLResponse)
async def admin_login(req:Request): return render(req,"admin_login.html",{"error":""})

@app.post("/admin/login")
async def admin_login_post(req:Request,password:str=Form("")):
    if password==cfg.ADMIN_PASS:
        resp=RedirectResponse("/admin",302); resp.set_cookie("_a",sign("admin",cfg.ADMIN_PASS),max_age=28800,httponly=True); return resp
    return render(req,"admin_login.html",{"error":"Mot de passe incorrect"})

@app.get("/admin",response_class=HTMLResponse)
async def admin_dash(req:Request):
    if not is_admin(req): return RedirectResponse("/admin/login",302)
    db=get_db()
    try:
        members=db.execute("SELECT * FROM members ORDER BY created_at DESC").fetchall()
        logs=db.execute("SELECT * FROM scrape_log ORDER BY ts DESC LIMIT 20").fetchall()
        top=db.execute("SELECT stx10_code,stx10_label,COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY stx10_code ORDER BY cnt DESC LIMIT 10").fetchall()
        pays=db.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT 20").fetchall()
        return render(req,"admin.html",{"members":[dict(m) for m in members],"logs":[dict(l) for l in logs],"stats":stats(),"top_stx10":[dict(r) for r in top],"payments":[dict(p) for p in pays],"scanning":St.scanning,"last_scan":St.last_scan})
    finally: db.close()

@app.get("/admin/scan")
async def admin_scan(req:Request):
    if not is_admin(req): return JSONResponse({"ok":False},401)
    if St.scanning: return JSONResponse({"ok":False,"msg":"Déjà en cours"})
    async def _do():
        St.scanning=True
        try:
            from app.services.scraper import scrape_new
            db=get_db(); new=scrape_new(db,St.max_id)
            if new: dispatch(new,db)
            db.close(); St.last_scan=datetime.now().strftime("%H:%M")
        finally: St.scanning=False
    asyncio.create_task(_do()); return JSONResponse({"ok":True})

@app.get("/admin/test_notif")
async def admin_test(req:Request,email:str="",tg:str=""):
    if not is_admin(req): return JSONResponse({"ok":False},401)
    return JSONResponse({"ok":True,"results":test_notif(email,tg)})

@app.post("/admin/member/{mid}/plan")
async def admin_plan(req:Request,mid:int,plan:str=Form("")):
    if not is_admin(req): return JSONResponse({"ok":False},401)
    if plan not in cfg.PLANS: return JSONResponse({"ok":False})
    db=get_db()
    try: db.execute("UPDATE members SET plan=? WHERE id=?",(plan,mid)); db.commit()
    finally: db.close()
    return RedirectResponse("/admin",302)

@app.post("/admin/member/{mid}/toggle")
async def admin_toggle(req:Request,mid:int):
    if not is_admin(req): return JSONResponse({"ok":False},401)
    db=get_db()
    try:
        row=db.execute("SELECT actif FROM members WHERE id=?",(mid,)).fetchone()
        if row: db.execute("UPDATE members SET actif=? WHERE id=?",(0 if row[0] else 1,mid)); db.commit()
    finally: db.close()
    return RedirectResponse("/admin",302)

@app.exception_handler(404)
async def e404(req,exc): return render(req,"404.html",{},404)
@app.exception_handler(500)
async def e500(req,exc): logger.error(f"500 {req.url}"); return render(req,"404.html",{},500)
