from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import json

from main import (
    render, get_db, get_member, get_days_left,
    hash_pw, clean_secteurs, cfg
)

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_get(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", 302)

    db = get_db()
    stats = db.execute(
        "SELECT COUNT(*) as total FROM tenders WHERE email=?", (m["email"],)
    ).fetchone()
    db.close()
    days_left = get_days_left(m.get("trial_ends", ""))
    return render(req, "dashboard.html", {
        "m": m,
        "stats": stats,
        "days_left": days_left,
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_get(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", 302)
    return render(req, "settings.html", {
        "m": m,
        "cfg": cfg,
    })


@router.post("/settings")
async def settings_post(req: Request,
    phone:   str = Form(""),
    company: str = Form(""),
    pw:      str = Form(""),
    pw2:     str = Form(""),
    secteurs_sel: list = Form(default=[]),
):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", 302)

    err = None
    if pw and pw != pw2:
        err = "Les mots de passe ne correspondent pas"

    if err:
        return render(req, "settings.html", {
            "err": err,
            "m": m,
        })

    sects = clean_secteurs(secteurs_sel)
    db = get_db()
    if pw:
        db.execute(
            "UPDATE members SET phone=?, company=?, secteurs=?, pw_hash=? WHERE id=?",
            (phone, company, json.dumps(sects), hash_pw(pw), m["id"])
        )
    else:
        db.execute(
            "UPDATE members SET phone=?, company=?, secteurs=? WHERE id=?",
            (phone, company, json.dumps(sects), m["id"])
        )
    db.commit()
    db.close()
    return render(req, "settings.html", {
        "ok": "Paramètres mis à jour.",
        "m": {**m, "phone": phone, "company": company, "secteurs": sects},
        "cfg": cfg,
    })


@router.get("/favorites", response_class=HTMLResponse)
async def favorites_get(req: Request):
    m = get_member(req)
    if not m:
        return RedirectResponse("/login", 302)
    db = get_db()
    rows = [dict(r) for r in db.execute(
        """SELECT t.* FROM tenders t
           JOIN favorites f ON f.tender_id = t.id
           WHERE f.member_id=? ORDER BY f.created_at DESC""",
        (m["id"],)
    ).fetchall()]
    db.close()
    return render(req, "favorites.html", {"m": m, "tenders": rows})
