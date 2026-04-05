"""
Modern Business — Routes: Marchés Publics
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
        "q": "", "code_f": "", "region_f": "", "easy": "", "source_f": "",
        "sort": "score", "type_f": "",
        "regions_list": [], "sources_list": [],
        "page_title": "★ Mes Favoris",
        "SECTEURS_LIST": SECTEURS_LIST, "REGIONS": REGIONS,
    })


# ═══════════════════════════════════════════════════
# CONTACT POST
# ═══════════════════════════════════════════════════