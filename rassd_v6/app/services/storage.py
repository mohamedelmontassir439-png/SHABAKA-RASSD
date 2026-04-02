"""
Modern Business — Service de stockage des صفقات
Insert, dedup, expire, cleanup
"""
import re
from datetime import datetime, date
from app.core.database import get_db
from app.core.dates import is_expired
from app.services.classifier import classify


def save_tender(t: dict) -> bool:
    """Sauvegarde un tender. Retourne True si nouveau."""
    if not t.get("id") or not t.get("objet"): return False

    # Skip expired
    dl = str(t.get("date_limite", "")).strip()
    if dl and is_expired(dl): return False

    # Classify
    t = classify(t)

    db = get_db()
    try:
        # Dedup par objet[:60]
        obj_key = t["objet"][:60].strip().lower()
        if len(obj_key) > 10:
            dup = db.execute(
                "SELECT id FROM tenders WHERE LOWER(SUBSTR(objet,1,60))=? "
                "AND date_extraction >= date('now','-1 day')",
                (obj_key,)
            ).fetchone()
            if dup: return False

        db.execute("""INSERT OR IGNORE INTO tenders
            (id,objet,acheteur,region,domaine,type_marche,montant,
             budget_min,budget_max,date_publication,date_limite,
             description,statut,url,source,contact,
             ai_score,ai_category,ai_reason,date_extraction)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            str(t.get("id",""))[:80],
            str(t.get("objet",""))[:400],
            str(t.get("acheteur",""))[:200],
            str(t.get("region","Maroc"))[:100],
            str(t.get("domaine",""))[:80],
            str(t.get("type_marche",""))[:40],
            str(t.get("montant",""))[:80],
            float(t.get("budget_min", 0) or 0),
            float(t.get("budget_max", 0) or 0),
            str(t.get("date_publication",""))[:20],
            str(t.get("date_limite",""))[:20],
            str(t.get("description",""))[:2000],
            str(t.get("statut","actif")),
            str(t.get("url", t.get("source_url","")))[:400],
            str(t.get("source",""))[:80],
            str(t.get("contact",""))[:200],
            int(t.get("ai_score", 50) or 50),
            str(t.get("ai_category",""))[:80],
            str(t.get("ai_reason",""))[:200],
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ))
        changed = db.execute("SELECT changes()").fetchone()[0]
        db.commit()
        return changed > 0
    except Exception as e:
        return False
    finally:
        db.close()


def save_many(tenders: list) -> int:
    """Sauvegarde une liste. Retourne le nombre de nouveaux."""
    return sum(1 for t in tenders if save_tender(t))


def expire_old() -> int:
    """Marque comme expirées les صفقات dont la date est passée."""
    db = get_db()
    today_dt = date.today()
    count = 0
    try:
        # Format ISO
        db.execute(
            "UPDATE tenders SET statut='expire' WHERE statut='actif' "
            "AND date_limite!='' AND date_limite NOT LIKE '%/%' "
            "AND date_limite < date('now') AND date_limite NOT IN ('N/A','—','-')"
        )
        # Format DD/MM/YYYY
        rows = db.execute(
            "SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite LIKE '%/%'"
        ).fetchall()
        exp = []
        for row in rows:
            dl = str(row["date_limite"]).strip()
            m = re.search(r'(\d{2}/\d{2}/\d{4})', dl)
            if m:
                try:
                    if datetime.strptime(m.group(1), "%d/%m/%Y").date() < today_dt:
                        exp.append(row["id"])
                except: pass
        if exp:
            ph = ",".join(["?"] * len(exp))
            db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", exp)
        db.commit()
        count = len(exp)
    finally:
        db.close()
    return count


def get_known_ids() -> set:
    """Retourne tous les IDs en DB."""
    db = get_db()
    try:
        rows = db.execute("SELECT id FROM tenders").fetchall()
        return {r["id"] for r in rows}
    finally:
        db.close()
