"""Mesure d'audience, sans script tiers ni cookie de suivi.

La plateforme n'avait aucun compteur: impossible de savoir si quelqu'un
venait, d'où, et jusqu'où il allait avant de partir. Un outil externe aurait
demandé d'ouvrir la politique de sécurité (CSP) à un domaine tiers et de
déposer un cookie soumis à consentement. Le serveur voit déjà passer chaque
page: il suffit de la compter.

Ce qui est gardé: le jour, le chemin, un identifiant de visiteur valable un
jour (empreinte de l'adresse, du navigateur, du jour et de la clé secrète —
irréversible, et différente chaque jour), le site d'où l'on vient, le canal
de campagne, et les événements qui comptent (inscription, clic WhatsApp).
Rien qui permette de retrouver une personne.
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from app.core.config import cfg
from app.core.database import get_db

logger = logging.getLogger("atlas.visites")

SCHEMA = """CREATE TABLE IF NOT EXISTS visites(
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    jour      TEXT NOT NULL,
    instant   TEXT NOT NULL,
    chemin    TEXT NOT NULL,
    visiteur  TEXT NOT NULL,
    referent  TEXT NOT NULL DEFAULT '',
    canal     TEXT NOT NULL DEFAULT '',
    membre    INTEGER NOT NULL DEFAULT 0,
    evenement TEXT NOT NULL DEFAULT ''
)"""
INDEX = ("CREATE INDEX IF NOT EXISTS idx_vis_jour ON visites(jour)",
         "CREATE INDEX IF NOT EXISTS idx_vis_evt ON visites(evenement, jour)")

# Ce qui n'est pas une page lue par une personne.
IGNORER = ("/static", "/video", "/admin", "/api", "/icon-", "/webhooks", "/health",
           "/sw.js", "/manifest.json", "/robots.txt", "/sitemap.xml", "/favicon", "/aller/")
_ROBOT = re.compile(r"bot|crawl|spider|slurp|facebookexternalhit|preview|monitor|curl|wget|"
                    r"python-requests|httpx|headless|lighthouse|pingdom|uptime", re.I)

# Événements comptés à part des pages vues.
INSCRIPTION = "inscription"
WHATSAPP = "whatsapp"

def assurer_table(db) -> None:
    """La table se crée à la première mesure (CREATE IF NOT EXISTS, immédiat
    quand elle existe): pas de migration à jouer, et une base de test neuve
    la reçoit comme les autres."""
    db.execute(SCHEMA)
    for sql in INDEX:
        db.execute(sql)
    db.commit()


def robot(user_agent: str) -> bool:
    """Un robot d'indexation ou un outil, pas un visiteur."""
    return not user_agent or bool(_ROBOT.search(user_agent))


def empreinte(ip: str, user_agent: str, jour: str) -> str:
    """Identifiant du visiteur pour la journée: irréversible, et différent
    chaque jour — on compte des visiteurs, on ne suit personne."""
    brut = f"{ip}|{user_agent[:200]}|{jour}|{cfg.SECRET_KEY}"
    return hashlib.sha256(brut.encode("utf-8", "ignore")).hexdigest()[:16]


def referent_externe(referer: str, hote: str) -> str:
    """Le site d'où l'on vient, quand ce n'est pas le nôtre."""
    if not referer:
        return ""
    try:
        domaine = (urlsplit(referer).netloc or "").lower().split(":")[0]
    except ValueError:
        return ""
    if not domaine or domaine == (hote or "").lower().split(":")[0]:
        return ""
    if domaine.startswith("www."):
        domaine = domaine[4:]
    return domaine[:80]


def enregistrer(chemin: str, visiteur: str, referent: str = "", canal: str = "",
                membre: int = 0, evenement: str = "") -> None:
    """Une ligne par page vue ou par événement. N'échoue jamais: une mesure
    qui casserait la page qu'elle mesure ne vaut rien."""
    try:
        maintenant = datetime.now()
        db = get_db()
        try:
            assurer_table(db)
            db.execute("INSERT INTO visites(jour,instant,chemin,visiteur,referent,canal,membre,evenement)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (maintenant.strftime("%Y-%m-%d"), maintenant.isoformat(timespec="seconds"),
                        chemin[:200], visiteur, referent[:80], canal[:40], 1 if membre else 0,
                        evenement[:40]))
            db.commit()
        finally:
            db.close()
    except Exception as e:  # pragma: no cover - journal seulement
        logger.warning(f"[visites] {e}")


def tableau(jours: int = 30) -> dict:
    """Les trente derniers jours, lisibles d'un coup d'œil."""
    depuis = (datetime.now() - timedelta(days=jours - 1)).strftime("%Y-%m-%d")
    db = get_db()
    try:
        assurer_table(db)
        par_jour = {}
        for r in db.execute("""SELECT jour,
                                      SUM(evenement='') AS pages,
                                      COUNT(DISTINCT CASE WHEN evenement='' THEN visiteur END) AS visiteurs,
                                      SUM(evenement=?) AS inscriptions,
                                      SUM(evenement=?) AS whatsapp
                               FROM visites WHERE jour>=? GROUP BY jour""",
                            (INSCRIPTION, WHATSAPP, depuis)):
            par_jour[r["jour"]] = dict(r)
        serie = []
        for i in range(jours):
            j = (datetime.strptime(depuis, "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d")
            serie.append(par_jour.get(j, {"jour": j, "pages": 0, "visiteurs": 0,
                                          "inscriptions": 0, "whatsapp": 0}))
        pages = [dict(r) for r in db.execute(
            """SELECT chemin, COUNT(*) n, COUNT(DISTINCT visiteur) visiteurs FROM visites
               WHERE jour>=? AND evenement='' GROUP BY chemin ORDER BY n DESC LIMIT 12""", (depuis,))]
        referents = [dict(r) for r in db.execute(
            """SELECT referent, COUNT(DISTINCT visiteur) visiteurs FROM visites
               WHERE jour>=? AND referent!='' GROUP BY referent ORDER BY visiteurs DESC LIMIT 10""", (depuis,))]
        canaux = [dict(r) for r in db.execute(
            """SELECT canal, COUNT(DISTINCT visiteur) visiteurs,
                      SUM(evenement=?) inscriptions, SUM(evenement=?) whatsapp
               FROM visites WHERE jour>=? AND canal!='' GROUP BY canal ORDER BY visiteurs DESC LIMIT 10""",
            (INSCRIPTION, WHATSAPP, depuis))]
        totaux = {
            "pages": sum(j["pages"] for j in serie),
            "visiteurs": db.execute("SELECT COUNT(DISTINCT visiteur||jour) FROM visites WHERE jour>=? AND evenement=''",
                                    (depuis,)).fetchone()[0],
            "inscriptions": sum(j["inscriptions"] for j in serie),
            "whatsapp": sum(j["whatsapp"] for j in serie),
        }
        tarifs = db.execute("SELECT COUNT(DISTINCT visiteur||jour) FROM visites WHERE jour>=? AND chemin='/tarifs'",
                            (depuis,)).fetchone()[0]
        totaux["tarifs"] = tarifs
        totaux["taux_whatsapp"] = round(100 * totaux["whatsapp"] / tarifs, 1) if tarifs else 0.0
        return {"jours": jours, "depuis": depuis, "serie": serie, "pages": pages,
                "referents": referents, "canaux": canaux, "totaux": totaux}
    finally:
        db.close()
