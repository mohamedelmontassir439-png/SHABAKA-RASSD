"""
Modern Business — Routes: Administration
"""
import asyncio, re, json, csv, io, secrets, logging, os
from fastapi import Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, Response
from fastapi.routing import APIRouter
from app.core.config   import cfg
from app.core.database import get_db
from app.core.dates    import is_expired, format_deadline
from datetime import datetime, date, timedelta
from typing import Optional
logger = logging.getLogger(__name__)
router = APIRouter()

from app.core.config import cfg
SITE_URL      = cfg.SITE_URL
ADMIN_PASS    = cfg.ADMIN_PASS
TELEGRAM_BOT  = cfg.TELEGRAM_BOT
ANTHROPIC_KEY = cfg.ANTHROPIC_KEY
PLAN_LIMITS   = cfg.PLAN_LIMITS
ADMIN_CHAT_ID = cfg.ADMIN_CHAT_ID

from app.utils.helpers import (
    templates, get_member, render, hash_pw,
    check_token, verify_pw,
    BREVO_KEY, RESEND_KEY, GMAIL_USER, DB_PATH,
    NotifyAgent, MonitorAgent, ScraperAgent, SState, SLog,
    SelfHealingAgent, AIClassifier, HAS_MULTI, MULTI_SRC,
    counter,
)

# chk(): vérifie le mot de passe admin ou lève une exception
def chk(pwd: str):
    from fastapi import HTTPException
    if not check_token(pwd):
        raise HTTPException(403, "Non autorisé")

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
