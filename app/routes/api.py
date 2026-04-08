from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

from main import get_db, get_stats

router = APIRouter(prefix="/api/v1")


@router.get("/tenders")
async def api_tenders(
    req: Request,
    secteur: str = "",
    region: str = "",
    q: str = "",
    limit: int = 20,
    offset: int = 0,
):
    db = get_db()
    where, params = ["statut='actif'"], []
    if secteur:
        where.append("secteur=?")
        params.append(secteur)
    if region:
        where.append("region=?")
        params.append(region)
    if q:
        where.append("(objet LIKE ? OR acheteur LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    wh = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM tenders WHERE {wh}", params).fetchone()[0]
    rows = [dict(r) for r in db.execute(
        f"SELECT id,objet,acheteur,secteur,region,montant,date_limite,url,scraped_at"
        f" FROM tenders WHERE {wh} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
        params + [min(limit, 100), offset]
    ).fetchall()]
    db.close()
    return {"ok": True, "total": total, "results": rows}


@router.get("/tenders/{tid}")
async def api_tender_detail(tid: str):
    db = get_db()
    t = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    db.close()
    if not t:
        return JSONResponse({"ok": False, "msg": "Introuvable"}, 404)
    return {"ok": True, "tender": dict(t)}


@router.get("/stats")
async def api_stats():
    return {"ok": True, **get_stats()}


@router.get("/me")
async def api_me(api_key: str = "", x_api_key: str | None = Header(None, alias="X-API-Key")):
    token = api_key or x_api_key or ""
    if not token:
        return JSONResponse({"ok": False, "msg": "api_key requis"}, 401)
    db = get_db()
    m = db.execute("SELECT * FROM members WHERE api_key=? AND actif=1", (token,)).fetchone()
    db.close()
    if not m:
        return JSONResponse({"ok": False, "msg": "Clé API invalide"}, 401)
    return {
        "ok": True,
        "member": {
            "email": m["email"],
            "plan": m["plan"],
            "email_verified": bool(m["email_verified"]),
            "notif_email": bool(m["notif_email"]),
            "notif_tg": bool(m["notif_tg"]),
            "api_key": m["api_key"],
        }
    }


@router.get("/secteurs")
async def api_secteurs():
    db = get_db()
    data = [dict(r) for r in db.execute(
        "SELECT secteur, COUNT(*) cnt FROM tenders WHERE statut='actif' GROUP BY secteur ORDER BY cnt DESC"
    ).fetchall()]
    db.close()
    return {"ok": True, "secteurs": data}
