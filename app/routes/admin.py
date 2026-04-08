from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
import asyncio
import json

from main import (
    render, get_db, get_member, make_token, cfg,
    get_stats, State, do_scrape, expire_tenders, _is_admin
)

router = APIRouter()


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_get(req: Request):
    if _is_admin(req):
        return RedirectResponse("/admin", 302)
    return render(req, "admin_login.html", {})


@router.post("/admin/login")
async def admin_login_post(req: Request, pwd: str = Form("")):
    if pwd != cfg.ADMIN_PASS:
        return render(req, "admin_login.html", {"err": "Mot de passe incorrect"})
    r = RedirectResponse("/admin", 302)
    r.set_cookie(
        "_admin", make_token("admin", cfg.ADMIN_PASS),
        httponly=True, max_age=86400 * 7, samesite="lax"
    )
    return r


@router.get("/admin/logout")
async def admin_logout():
    r = RedirectResponse("/", 302)
    r.delete_cookie("_admin")
    return r


@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(req: Request):
    if not _is_admin(req):
        return RedirectResponse("/admin/login", 302)
    db = get_db()
    stats = get_stats()
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
    return render(req, "admin.html", {
        "stats": stats,
        "sectors": sectors,
        "members": members,
        "scrapes": scrapes,
        "logs": State.logs[-100:],
        "running": State.running,
        "last_run": State.last_run,
        "cfg": cfg,
    })


@router.get("/admin/scrape")
async def admin_scrape(req: Request):
    if not _is_admin(req):
        return JSONResponse({"ok": False, "msg": "Non autorisé"}, 401)
    if State.running:
        return JSONResponse({"ok": False, "msg": "Scan déjà en cours"})
    asyncio.create_task(do_scrape())
    return JSONResponse({"ok": True, "msg": "Scan lancé"})


@router.get("/admin/scrape_stream")
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
                        "log": log,
                        "running": State.running,
                        "saved": State.saved,
                        "found": State.found,
                    })
                    yield f"data: {data}\n\n"
                last = len(logs)
            if not State.running and last > 0:
                yield f"data: {json.dumps({'done': True, 'saved': State.saved, 'found': State.found})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/admin/expire")
async def admin_expire(req: Request):
    if not _is_admin(req):
        return JSONResponse({"ok": False}, 401)
    expired, active = expire_tenders()
    return JSONResponse({"ok": True, "expired": expired, "active": active})


@router.post("/admin/member/{mid}/plan")
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


@router.post("/admin/member/{mid}/toggle")
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


@router.get("/admin/clear")
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
