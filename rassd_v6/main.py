"""
RASSD v3.1 — SaaS Veille Marchés Publics Maroc
Production-ready · Fully audited
"""
import os, re, json, asyncio, logging
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import (HTMLResponse, RedirectResponse,
                               JSONResponse, StreamingResponse, Response)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config   import cfg
from app.core.database import get_db, init_db
from app.core.security import (hash_pw, verify_pw, make_token,
                                get_member, validate_email,
                                validate_password, days_left)
from app.services.notifications import dispatch_notifications, tg_admin, test_notifications
try:
    from app.services.multi_scraper import run_all as multi_scrape_run
    MULTI_SCRAPER_OK = True
except ImportError:
    MULTI_SCRAPER_OK = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-18s │ %(levelname)s │ %(message)s"
)
logger = logging.getLogger("rassd")

# ══════════════════════════════════════════════════════════
# SCRAPER STATE
# ══════════════════════════════════════════════════════════
class State:
    running  = False
    saved    = 0
    found    = 0
    errors   = 0
    last_run = ""
    logs: list = []

    @classmethod
    def log(cls, msg: str):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        cls.logs.append(entry)
        logger.info(msg)
        if len(cls.logs) > 700:
            cls.logs = cls.logs[-500:]


# ══════════════════════════════════════════════════════════
# SCRAPER ENGINE
# ══════════════════════════════════════════════════════════
async def do_scrape():
    if State.running:
        return
    State.running = True
    State.saved = State.found = State.errors = 0
    t0_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        from app.services.scraper import run
        if MULTI_SCRAPER_OK:
            try:
                from app.services.multi_scraper import run_all as multi_scrape_run
            except: pass
    except ImportError as e:
        State.log(f"❌ Import scraper: {e}")
        State.running = False
        return

    try:
        db = get_db()
        known = {r[0] for r in db.execute("SELECT id FROM tenders").fetchall()}
        db.close()

        loop = asyncio.get_event_loop()
        tenders = await loop.run_in_executor(None, lambda: run(known, State.log))
        State.found = len(tenders)

        db = get_db()
        new_tenders = []
        for t in tenders:
            try:
                db.execute("""
                    INSERT OR IGNORE INTO tenders
                    (id,objet,acheteur,secteur,region,montant,
                     date_publication,date_limite,description,
                     url,statut,scraped_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    t["id"], t["objet"], t["acheteur"],
                    t.get("secteur",""), t.get("region",""),
                    t.get("montant",""), t.get("date_publication",""),
                    t.get("date_limite",""), t.get("description",""),
                    t["url"], t["statut"],
                    t["scraped_at"], t["scraped_at"],
                ))
                if db.execute("SELECT changes()").fetchone()[0]:
                    State.saved += 1
                    new_tenders.append(t)
            except Exception as e:
                State.errors += 1
                logger.error(f"[save {t.get('id')}] {e}")

        # Log scrape run
        db.execute(
            "INSERT INTO scrape_log(found,saved,errors,run_at) VALUES(?,?,?,?)",
            (State.found, State.saved, State.errors, t0_str)
        )
        db.commit()
        db.close()

        State.last_run = t0_str
        State.log(f"✅ {State.saved} nouveaux marchés sauvegardés")

        # Send notifications async
        if new_tenders:
            await loop.run_in_executor(
                None, lambda: dispatch_notifications(new_tenders)
            )

    except Exception as e:
        State.log(f"❌ Erreur scraper: {e}")
        logger.error(f"[do_scrape] {e}", exc_info=True)
    finally:
        State.running = False


async def scheduler():
    """Background scheduler: scan toutes les N minutes"""
    await asyncio.sleep(20)   # Attendre que l'app soit prête
    while True:
        try:
            await do_scrape()
        except Exception as e:
            logger.error(f"[scheduler] {e}")
        await asyncio.sleep(cfg.SCAN_INTERVAL_MIN * 60)


# ══════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════
class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.update({
            "X-Content-Type-Options":  "nosniff",
            "X-Frame-Options":         "DENY",
            "X-XSS-Protection":        "1; mode=block",
            "Referrer-Policy":         "strict-origin-when-cross-origin",
        })
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    State.log(f"RASSD v{cfg.APP_VERSION} démarré ✅")
    asyncio.create_task(scheduler())
    yield


app = FastAPI(
    lifespan=lifespan,
    title=cfg.APP_NAME,
    version=cfg.APP_VERSION,
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(SecurityMiddleware)

templates = Jinja2Templates(directory="templates")
try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass


# ── Helpers ──────────────────────────────────────────────
def render(req: Request, tpl: str, ctx: dict = None):
    m = get_member(req)
    ctx = ctx or {}
    return templates.TemplateResponse(tpl, {
        "request":   req,
        "member":    m,
        "cfg":       cfg,
        "secteurs":  cfg.SECTEURS,
        "plans":     cfg.PLANS,
        "dl":        days_left,
        "days_left": days_left,
        "now":       datetime.now(),
        **ctx
    })


def get_stats() -> dict:
    db = get_db()
    try:
        return {
            "tenders": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
            "today":   db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND scraped_at>=date('now')").fetchone()[0],
            "members": db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
            "notifs":  db.execute("SELECT COUNT(*) FROM notif_log WHERE sent_at>=date('now','-7 days')").fetchone()[0],
            "expired": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
            "scrapes": db.execute("SELECT COUNT(*) FROM scrape_log").fetchone()[0],
        }
    finally:
        db.close()


def expire_tenders() -> tuple:
    db = get_db()
    today = date.today()
    expired_ids = []
    rows = db.execute(
        "SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''"
    ).fetchall()
    for row in rows:
        m = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', str(row["date_limite"]))
        if not m:
            continue
        try:
            fmt = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
            if datetime.strptime(m.group(1), fmt).date() < today:
                expired_ids.append(row["id"])
        except Exception:
            pass
    if expired_ids:
        ph = ",".join(["?"] * len(expired_ids))
        db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", expired_ids)
        db.commit()
    active = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    db.close()
    return len(expired_ids), active


def clean_secteurs(raw_list: list) -> list:
    """Nettoie la liste des secteurs (enlève vides, déduplique)"""
    return list({s for s in raw_list if s and s.strip()})


def _is_admin(req: Request) -> bool:
    return req.cookies.get("_admin", "") == make_token("admin", cfg.ADMIN_PASS)


# ══════════════════════════════════════════════════════════
# PUBLIC ROUTES
# ══════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def home(req: Request):
    db = get_db()
    stats   = get_stats()
    recent  = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 9"
    ).fetchall()]
    sectors = [dict(r) for r in db.execute(
        "SELECT secteur, COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC LIMIT 12"
    ).fetchall()]
    db.close()
    return render(req, "landing.html", {
        "stats":   stats,
        "recent":  recent,
        "sectors": sectors,
    })


@app.get("/tenders", response_class=HTMLResponse)
async def tenders_page(req: Request,
    q: str = "", s: str = "", r: str = "",
    page: int = 1, sort: str = "recent"):
    db = get_db()
    per   = 25
    page  = max(1, page)
    where, params = ["statut='actif'"], []

    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ? OR description LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if s:
        where.append("secteur=?")
        params.append(s)
    if r:
        where.append("region=?")
        params.append(r)

    wh    = " AND ".join(where)
    order = "scraped_at DESC" if sort == "recent" else "date_limite ASC"
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
    rows  = [dict(row) for row in db.execute(
        f"SELECT * FROM tenders WHERE {wh} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [per, (page - 1) * per]
    ).fetchall()]

    member = get_member(req)
    favs   = set()
    if member:
        favs = {row[0] for row in db.execute(
            "SELECT tender_id FROM favorites WHERE member_id=?", (member["id"],)
        ).fetchall()}
    db.close()

    pages = max(1, (total + per - 1) // per)
    return render(req, "tenders.html", {
        "tenders": rows, "total": total,
        "page": page, "pages": pages,
        "q": q, "sf": s, "rf": r, "sort": sort,
        "favs": favs,
    })


@app.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    db = get_db()
    t = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    if not t:
        db.close()
        return HTMLResponse("Marché introuvable", 404)

    try:
        db.execute("UPDATE tenders SET views=views+1 WHERE id=?", (tid,))
    except Exception:
        pass  # views column might not exist in old DBs
    secteur = t["secteur"] if t["secteur"] else ""
    related = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE secteur=? AND id!=? AND statut='actif' ORDER BY scraped_at DESC LIMIT 4",
        (secteur, tid)
    ).fetchall()] if secteur else []

    member = get_member(req)
    is_fav = False
    if member:
        try:
            is_fav = bool(db.execute(
                "SELECT id FROM favorites WHERE member_id=? AND tender_id=?",
                (member["id"], tid)
            ).fetchone())
        except Exception:
            pass
    try:
        db.commit()
    except Exception:
        pass
    db.close()
    return render(req, "detail.html", {
        "t": dict(t), "related": related, "is_fav": is_fav,
    })


@app.post("/tenders/{tid}/favorite")
async def toggle_fav(req: Request, tid: str):
    member = get_member(req)
    if not member:
        return JSONResponse({"ok": False, "msg": "Non connecté"}, 401)
    db = get_db()
    try:
        exists = db.execute(
            "SELECT id FROM favorites WHERE member_id=? AND tender_id=?",
            (member["id"], tid)
        ).fetchone()
        if exists:
            db.execute("DELETE FROM favorites WHERE member_id=? AND tender_id=?",
                       (member["id"], tid))
            db.commit()
            return JSONResponse({"ok": True, "fav": False})
        db.execute(
            "INSERT OR IGNORE INTO favorites(member_id,tender_id,created_at) VALUES(?,?,?)",
            (member["id"], tid, datetime.now().isoformat())
        )
        db.commit()
        return JSONResponse({"ok": True, "fav": True})
    finally:
        db.close()


@app.get("/favorites", response_class=HTMLResponse)
async def favorites_page(req: Request):
    member = get_member(req)
    if not member:
        return RedirectResponse("/login?next=/favorites", 302)
    db = get_db()
    rows = [dict(r) for r in db.execute(
        """SELECT t.* FROM tenders t
           JOIN favorites f ON f.tender_id = t.id
           WHERE f.member_id=? ORDER BY f.created_at DESC""",
        (member["id"],)
    ).fetchall()]
    db.close()
    return render(req, "favorites.html", {"tenders": rows})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(req: Request):
    member = get_member(req)
    if not member:
        return RedirectResponse("/login?next=/dashboard", 302)
    db = get_db()
    member_sects = clean_secteurs(json.loads(member.get("secteurs", "[]") or "[]"))

    favs   = [dict(r) for r in db.execute(
        """SELECT t.* FROM tenders t JOIN favorites f ON f.tender_id=t.id
           WHERE f.member_id=? AND t.statut='actif' ORDER BY f.created_at DESC LIMIT 6""",
        (member["id"],)
    ).fetchall()]
    notifs = [dict(r) for r in db.execute(
        """SELECT nl.*, t.objet FROM notif_log nl
           JOIN tenders t ON t.id=nl.tender_id
           WHERE nl.member_id=? ORDER BY nl.sent_at DESC LIMIT 10""",
        (member["id"],)
    ).fetchall()]

    if member_sects:
        ph   = ",".join(["?"] * len(member_sects))
        recs = [dict(r) for r in db.execute(
            f"SELECT * FROM tenders WHERE secteur IN ({ph}) AND statut='actif' ORDER BY scraped_at DESC LIMIT 6",
            member_sects
        ).fetchall()]
    else:
        recs = [dict(r) for r in db.execute(
            "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 6"
        ).fetchall()]

    stats = {
        "favs":   db.execute("SELECT COUNT(*) FROM favorites WHERE member_id=?", (member["id"],)).fetchone()[0],
        "notifs": db.execute("SELECT COUNT(*) FROM notif_log WHERE member_id=?",  (member["id"],)).fetchone()[0],
        "active": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
    }
    db.close()
    return render(req, "dashboard.html", {
        "favs": favs, "notifs": notifs, "recs": recs, "stats": stats,
    })


@app.get("/tarifs", response_class=HTMLResponse)
async def tarifs(req: Request):
    return render(req, "tarifs.html", {})


# ══════════════════════════════════════════════════════════
# AUTH ROUTES
# ══════════════════════════════════════════════════════════
@app.get("/register", response_class=HTMLResponse)
async def register_get(req: Request):
    m = get_member(req)
    if m:
        return RedirectResponse("/dashboard", 302)
    return render(req, "register.html", {})


@app.post("/register")
async def register_post(req: Request,
    nom:          str  = Form(""),
    email:        str  = Form(""),
    phone:        str  = Form(""),
    company:      str  = Form(""),
    pw:           str  = Form(""),
    pw2:          str  = Form(""),
    secteurs_sel: list = Form(default=[]),
):
    err  = None
    vals = {"nom": nom, "email": email, "phone": phone, "company": company}

    if not email or not pw:
        err = "Email et mot de passe requis"
    elif not validate_email(email):
        err = "Adresse email invalide"
    elif pw != pw2:
        err = "Les mots de passe ne correspondent pas"
    else:
        ok, msg = validate_password(pw)
        if not ok:
            err = msg

    if err:
        return render(req, "register.html", {"err": err, "vals": vals})

    db = get_db()
    try:
        if db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone():
            return render(req, "register.html", {
                "err":  "Cette adresse email est déjà utilisée",
                "vals": vals,
            })
        sects      = clean_secteurs(secteurs_sel)
        trial_ends = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        created_at = datetime.now().isoformat()
        db.execute(
            """INSERT INTO members
               (nom,email,phone,company,pw_hash,secteurs,plan,created_at,trial_ends)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (nom, email, phone, company, hash_pw(pw),
             json.dumps(sects), "free", created_at, trial_ends)
        )
        db.commit()
        m = db.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone()
    finally:
        db.close()

    resp = RedirectResponse("/dashboard?welcome=1", 302)
    resp.set_cookie(
        "_session", make_token(m["email"], m["created_at"]),
        max_age=86400 * 30, httponly=True, samesite="lax"
    )
    return resp


@app.get("/login", response_class=HTMLResponse)
async def login_get(req: Request, next: str = ""):
    m = get_member(req)
    if m:
        return RedirectResponse(next or "/dashboard", 302)
    return render(req, "login.html", {"next": next})


@app.post("/login")
async def login_post(req: Request,
    email: str = Form(""),
    pw:    str = Form(""),
    next:  str = Form(""),
):
    db = get_db()
    m  = db.execute(
        "SELECT * FROM members WHERE email=? AND actif=1", (email,)
    ).fetchone()
    if not m or not verify_pw(pw, m["pw_hash"]):
        db.close()
        return render(req, "login.html", {
            "err":  "Email ou mot de passe incorrect",
            "vals": {"email": email},
            "next": next,
        })
    db.execute("UPDATE members SET last_login=? WHERE id=?",
               (datetime.now().isoformat(), m["id"]))
    db.commit()
    db.close()

    resp = RedirectResponse(next or "/dashboard", 302)
    resp.set_cookie(
        "_session", make_token(m["email"], m["created_at"]),
        max_age=86400 * 30, httponly=True, samesite="lax"
    )
    return resp


@app.get("/logout")
async def logout():
    r = RedirectResponse("/", 302)
    r.delete_cookie("_session")
    return r


@app.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    member = get_member(req)
    if not member:
        return RedirectResponse("/login?next=/settings", 302)
    ms = clean_secteurs(json.loads(member.get("secteurs", "[]") or "[]"))
    return render(req, "settings.html", {"ms": ms})


@app.post("/settings")
async def settings_post(req: Request,
    nom:          str  = Form(""),
    phone:        str  = Form(""),
    company:      str  = Form(""),
    telegram:     str  = Form(""),
    secteurs_sel: list = Form(default=[]),
):
    member = get_member(req)
    if not member:
        return RedirectResponse("/login", 302)

    # Checkboxes: si non cochée → absente du form → utiliser getlist
    form   = await req.form()
    n_email  = 1 if form.get("notif_email") else 0
    n_tg     = 1 if form.get("notif_tg") else 0
    n_digest = 1 if form.get("notif_digest") else 0
    sects    = clean_secteurs(secteurs_sel)

    db = get_db()
    try:
        db.execute(
            """UPDATE members
               SET nom=?,phone=?,company=?,telegram=?,
                   notif_email=?,notif_tg=?,notif_digest=?,secteurs=?
               WHERE id=?""",
            (nom, phone, company, telegram.strip(),
             n_email, n_tg, n_digest,
             json.dumps(sects), member["id"])
        )
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/settings?ok=1", 302)


# ══════════════════════════════════════════════════════════
# ADMIN ROUTES
# ══════════════════════════════════════════════════════════
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_get(req: Request):
    if _is_admin(req):
        return RedirectResponse("/admin", 302)
    return render(req, "admin_login.html", {})


@app.post("/admin/login")
async def admin_login_post(req: Request, pwd: str = Form("")):
    if pwd != cfg.ADMIN_PASS:
        return render(req, "admin_login.html", {"err": "Mot de passe incorrect"})
    r = RedirectResponse("/admin", 302)
    r.set_cookie(
        "_admin", make_token("admin", cfg.ADMIN_PASS),
        httponly=True, max_age=86400 * 7, samesite="lax"
    )
    return r


@app.get("/admin/logout")
async def admin_logout():
    r = RedirectResponse("/", 302)
    r.delete_cookie("_admin")
    return r


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(req: Request):
    if not _is_admin(req):
        return RedirectResponse("/admin/login", 302)
    db = get_db()
    stats   = get_stats()
    sectors = [dict(r) for r in db.execute(
        "SELECT secteur, COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC"
    ).fetchall()]
    members = [dict(r) for r in db.execute(
        "SELECT id,nom,email,plan,created_at,last_login,actif FROM members ORDER BY created_at DESC LIMIT 30"
    ).fetchall()]
    scrapes = [dict(r) for r in db.execute(
        "SELECT * FROM scrape_log ORDER BY run_at DESC LIMIT 8"
    ).fetchall()]
    db.close()
    return templates.TemplateResponse("admin.html", {
        "request":  req,
        "stats":    stats,
        "sectors":  sectors,
        "members":  members,
        "scrapes":  scrapes,
        "logs":     State.logs[-100:],
        "running":  State.running,
        "last_run": State.last_run,
        "cfg":      cfg,
    })


@app.get("/admin/scrape")
async def admin_scrape(req: Request):
    if not _is_admin(req):
        return JSONResponse({"ok": False, "msg": "Non autorisé"}, 401)
    if State.running:
        return JSONResponse({"ok": False, "msg": "Scan déjà en cours"})
    asyncio.create_task(do_scrape())
    return JSONResponse({"ok": True, "msg": "Scan lancé"})


@app.get("/admin/scrape_stream")
async def admin_stream(req: Request):
    if not _is_admin(req):
        return JSONResponse({"error": "unauthorized"}, 401)

    async def generate():
        last = 0
        while True:
            logs = State.logs
            if len(logs) > last:
                for log in logs[last:]:
                    data = json.dumps({
                        "log":     log,
                        "running": State.running,
                        "saved":   State.saved,
                        "found":   State.found,
                    })
                    yield f"data: {data}\n\n"
                last = len(logs)
            if not State.running and last > 0:
                yield f"data: {json.dumps({'done': True, 'saved': State.saved, 'found': State.found})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/admin/expire")
async def admin_expire(req: Request):
    if not _is_admin(req):
        return JSONResponse({"ok": False}, 401)
    expired, active = expire_tenders()
    return JSONResponse({"ok": True, "expired": expired, "active": active})


@app.post("/admin/member/{mid}/plan")
async def set_member_plan(req: Request, mid: int, plan: str = Form("")):
    if not _is_admin(req):
        return JSONResponse({"ok": False}, 401)
    if plan not in cfg.PLANS:
        return JSONResponse({"ok": False, "msg": "Plan invalide"})
    db = get_db()
    db.execute("UPDATE members SET plan=? WHERE id=?", (plan, mid))
    db.commit()
    db.close()
    return RedirectResponse("/admin", 302)


@app.post("/admin/member/{mid}/toggle")
async def toggle_member(req: Request, mid: int):
    if not _is_admin(req):
        return JSONResponse({"ok": False}, 401)
    db = get_db()
    m = db.execute("SELECT actif FROM members WHERE id=?", (mid,)).fetchone()
    if m:
        db.execute("UPDATE members SET actif=? WHERE id=?", (0 if m["actif"] else 1, mid))
        db.commit()
    db.close()
    return RedirectResponse("/admin", 302)


@app.get("/admin/clear")
async def admin_clear(req: Request, confirm: str = ""):
    if not _is_admin(req):
        return JSONResponse({"ok": False}, 401)
    if confirm != "yes":
        return HTMLResponse(
            '<a href="/admin/clear?confirm=yes" style="color:red">Confirmer la suppression de TOUS les marchés</a>'
        )
    db = get_db()
    n = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    db.execute("DELETE FROM tenders")
    db.execute("DELETE FROM notif_log")
    db.commit()
    db.close()
    State.log(f"🗑 DB vidée ({n} marchés supprimés)")
    return JSONResponse({"ok": True, "deleted": n})


# ══════════════════════════════════════════════════════════
# API v1
# ══════════════════════════════════════════════════════════
@app.get("/api/v1/tenders")
async def api_tenders(
    req:     Request,
    secteur: str = "",
    region:  str = "",
    q:       str = "",
    limit:   int = 20,
    offset:  int = 0,
):
    db = get_db()
    where, params = ["statut='actif'"], []
    if secteur: where.append("secteur=?");  params.append(secteur)
    if region:  where.append("region=?");   params.append(region)
    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    wh    = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
    rows  = [dict(r) for r in db.execute(
        f"""SELECT id,objet,acheteur,secteur,region,montant,
                   date_limite,url,scraped_at
            FROM tenders WHERE {wh}
            ORDER BY scraped_at DESC LIMIT ? OFFSET ?""",
        params + [min(limit, 100), offset]
    ).fetchall()]
    db.close()
    return {"ok": True, "total": total, "results": rows}


@app.get("/api/v1/tenders/{tid}")
async def api_tender_detail(tid: str):
    db = get_db()
    t = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    db.close()
    if not t:
        return JSONResponse({"ok": False, "msg": "Introuvable"}, 404)
    return {"ok": True, "tender": dict(t)}


@app.get("/api/v1/stats")
async def api_stats():
    return {"ok": True, **get_stats()}


@app.get("/api/v1/secteurs")
async def api_secteurs():
    db = get_db()
    data = [dict(r) for r in db.execute(
        "SELECT secteur, COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC"
    ).fetchall()]
    db.close()
    return {"ok": True, "secteurs": data}


# ══════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════
@app.get("/admin/test_notif")
async def admin_test_notif(req: Request, email: str = "", tg: str = ""):
    if not _is_admin(req):
        return JSONResponse({"ok": False}, 401)
    member = get_member(req)
    test_email = email or (member["email"] if member else "")
    test_tg    = tg or ""
    # Use admin chat ID as fallback
    from app.core.config import cfg as _cfg
    if not test_tg and _cfg.ADMIN_CHAT_ID:
        test_tg = _cfg.ADMIN_CHAT_ID
    results = test_notifications(test_email, test_tg)
    return JSONResponse({"ok": True, "results": results,
                         "email_tested": test_email, "tg_tested": test_tg})

@app.get("/api/v1/sources")
async def api_sources():
    """Liste toutes les sources disponibles"""
    sources = [
        {"name": "marchespublics.gov.ma", "type": "public",     "status": "active"},
        {"name": "ONDA",                  "type": "semi-public", "status": "active"},
        {"name": "Le Matin Annonces",     "type": "journal",     "status": "active"},
        {"name": "ONEE",                  "type": "semi-public", "status": "active"},
        {"name": "ONCF",                  "type": "semi-public", "status": "active"},
        {"name": "IAM Maroc Telecom",     "type": "semi-private","status": "active"},
        {"name": "SNRT",                  "type": "semi-public", "status": "active"},
        {"name": "Crédit Agricole",       "type": "private",     "status": "active"},
        {"name": "BCP",                   "type": "private",     "status": "active"},
        {"name": "Équipement",            "type": "public",      "status": "active"},
        {"name": "AMMC",                  "type": "semi-public", "status": "active"},
    ]
    return {"ok": True, "total": len(sources), "sources": sources,
            "multi_scraper": MULTI_SCRAPER_OK}

@app.get("/health")
async def health():
    db  = get_db()
    act = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    db.close()
    return {
        "status":   "ok",
        "version":  cfg.APP_VERSION,
        "brand":    cfg.APP_NAME,
        "active":   act,
        "running":  State.running,
        "last_run": State.last_run,
    }


@app.get("/sitemap.xml")
async def sitemap():
    db  = get_db()
    ids = [r[0] for r in db.execute(
        "SELECT id FROM tenders WHERE statut='actif' LIMIT 2000"
    ).fetchall()]
    db.close()
    urls = "\n".join(
        f"  <url><loc>{cfg.SITE_URL}/tenders/{tid}</loc></url>"
        for tid in ids
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{cfg.SITE_URL}/</loc></url>
  <url><loc>{cfg.SITE_URL}/tenders</loc></url>
  <url><loc>{cfg.SITE_URL}/tarifs</loc></url>
{urls}
</urlset>"""
    return Response(xml, media_type="application/xml")


@app.get("/robots.txt")
async def robots():
    return Response(
        f"User-agent: *\nAllow: /\nSitemap: {cfg.SITE_URL}/sitemap.xml\n",
        media_type="text/plain"
    )
