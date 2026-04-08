from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from datetime import datetime
import json

from main import render, get_db, get_member, get_stats, cfg, State

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(req: Request):
    db = get_db()
    stats = get_stats()
    recent = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE statut='actif' ORDER BY scraped_at DESC LIMIT 9"
    ).fetchall()]
    sectors = [dict(r) for r in db.execute(
        "SELECT secteur, COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC LIMIT 12"
    ).fetchall()]
    db.close()
    return render(req, "landing.html", {
        "stats": stats,
        "recent": recent,
        "sectors": sectors,
    })


@router.get("/tenders", response_class=HTMLResponse)
async def tenders_page(req: Request,
    q: str = "", s: str = "", r: str = "",
    page: int = 1, sort: str = "recent"
):
    db = get_db()
    per = 25
    page = max(1, page)
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

    wh = " AND ".join(where)
    order = "scraped_at DESC" if sort == "recent" else "date_limite ASC"
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
    rows = [dict(row) for row in db.execute(
        f"SELECT * FROM tenders WHERE {wh} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [per, (page - 1) * per]
    ).fetchall()]

    member = get_member(req)
    favs = set()
    if member:
        favs = {row[0] for row in db.execute(
            "SELECT tender_id FROM favorites WHERE member_id=?", (member["id"],)
        ).fetchall()}
    db.close()

    pages = max(1, (total + per - 1) // per)
    return render(req, "tenders.html", {
        "tenders": rows,
        "total": total,
        "page": page,
        "pages": pages,
        "q": q,
        "sf": s,
        "rf": r,
        "sort": sort,
        "favs": favs,
    })


@router.get("/tenders/{tid}", response_class=HTMLResponse)
async def tender_detail(req: Request, tid: str):
    db = get_db()
    t = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    if not t:
        db.close()
        return HTMLResponse("Marché introuvable", 404)

    db.execute("UPDATE tenders SET views=views+1 WHERE id=?", (tid,))
    related = [dict(r) for r in db.execute(
        "SELECT * FROM tenders WHERE secteur=? AND id!=? AND statut='actif' ORDER BY scraped_at DESC LIMIT 4",
        (t["secteur"], tid)
    ).fetchall()]

    member = get_member(req)
    is_fav = False
    if member:
        is_fav = bool(db.execute(
            "SELECT id FROM favorites WHERE member_id=? AND tender_id=?",
            (member["id"], tid)
        ).fetchone())
    db.commit()
    db.close()
    return render(req, "detail.html", {
        "t": dict(t),
        "related": related,
        "is_fav": is_fav,
    })


@router.post("/tenders/{tid}/favorite")
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
            db.execute("DELETE FROM favorites WHERE member_id=? AND tender_id=?", (member["id"], tid))
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


@router.get("/tarifs", response_class=HTMLResponse)
async def tarifs(req: Request):
    return render(req, "tarifs.html", {})


@router.get("/health")
async def health():
    db = get_db()
    act = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
    db.close()
    return {
        "status": "ok",
        "version": cfg.APP_VERSION,
        "brand": cfg.APP_NAME,
        "active": act,
        "running": State.running,
        "last_run": State.last_run,
    }


@router.get("/sitemap.xml")
async def sitemap():
    db = get_db()
    ids = [r[0] for r in db.execute(
        "SELECT id FROM tenders WHERE statut='actif' LIMIT 2000"
    ).fetchall()]
    db.close()
    urls = "\n".join(
        f"  <url><loc>{cfg.SITE_URL}/tenders/{tid}</loc></url>"
        for tid in ids
    )
    xml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">
  <url><loc>{cfg.SITE_URL}/</loc></url>
  <url><loc>{cfg.SITE_URL}/tenders</loc></url>
  <url><loc>{cfg.SITE_URL}/tarifs</loc></url>
{urls}
</urlset>"""
    return Response(xml, media_type="application/xml")


@router.get("/robots.txt")
async def robots():
    return Response(
        f"User-agent: *\nAllow: /\nSitemap: {cfg.SITE_URL}/sitemap.xml\n",
        media_type="text/plain"
    )
