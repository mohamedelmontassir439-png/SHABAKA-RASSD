# -*- coding: utf-8 -*-
"""Les reports officiels des dates limites.

Le 25/10/2026, le portail des marchés publics affichait un avis de la
Trésorerie Générale du Royaume: portail suspendu à titre préventif après
l'annonce de vulnérabilités critiques de PHP, remise en service le 26/10,
reprise des procédures le 27/10, et report des échéances — dates limites de
réception des offres comprises — « aux horaires initialement fixés »:

    21/10/2026 → 27/10/2026      22/10/2026 → 28/10/2026
    23/10/2026 → 29/10/2026      26 et 27/10/2026 → 30/10/2026

Sur la plateforme, ces marchés gardaient l'ancienne date; ceux du 21 au 23
étaient même passés « clôturés ». Un membre les aurait crus perdus.

On applique donc le report aux avis du portail national (source
« marchespublics », appels d'offres et bons de commande), une fois: la date
d'origine est gardée (`date_limite_initiale`), la date de l'avis réécrite
partout où elle figure, et le marché rouvert s'il avait été clos pour cette
seule raison — pas s'il était un doublon. Les avis des autres sources ne
sont pas touchés: on ne sait pas s'ils se déposent sur le portail; la
fiche le signale.
"""
import logging
import re
import unicodedata
from datetime import date, datetime

from app.core.database import get_db

logger = logging.getLogger("atlas.reports")

REPORTS = [{
    "cle": "tgr-2026-10",
    "source": "Trésorerie Générale du Royaume — avis publié sur marchespublics.gov.ma",
    "motif_fr": "Portail des marchés publics suspendu à titre préventif (vulnérabilités PHP), remis en service le 26/10/2026.",
    "motif_ar": "تعليق بوابة الصفقات العمومية احتياطيًّا (ثغرات PHP)، وإعادة تشغيلها يوم 26/10/2026.",
    "dates": {"21/10/2026": "27/10/2026", "22/10/2026": "28/10/2026", "23/10/2026": "29/10/2026",
              "26/10/2026": "30/10/2026", "27/10/2026": "30/10/2026"},
    # Le bandeau du site reste affiché jusqu'à la dernière nouvelle date.
    "bandeau_jusqu_au": date(2026, 10, 30),
    # Seuls les avis connus avant la remise en service: un avis publié
    # ensuite porte déjà ses vraies dates.
    "collectes_avant": "2026-10-26",
}]


def _empreinte(objet: str) -> str:
    base = unicodedata.normalize("NFD", (objet or "").lower())
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", base).strip()[:110]


def report_actif(aujourdhui: date = None):
    """Le report à annoncer sur le site, s'il y en a un en cours."""
    aujourdhui = aujourdhui or date.today()
    return next((r for r in REPORTS if aujourdhui <= r["bandeau_jusqu_au"]), None)


def appliquer(report: dict = None) -> dict:
    """Applique un report aux avis du portail national. Sans effet la 2e fois."""
    report = report or REPORTS[0]
    dates = report["dates"]
    db = get_db()
    try:
        cibles = [dict(r) for r in db.execute(
            f"""SELECT id, objet, date_limite, description, statut FROM tenders
                WHERE source='marchespublics' AND COALESCE(date_limite_initiale,'')=''
                  AND substr(date_limite,1,10) IN ({','.join('?' * len(dates))})
                  AND scraped_at < ?""",
            [*dates, report["collectes_avant"]]).fetchall()]
        actifs = {(_empreinte(r["objet"]), r["date_limite"]) for r in db.execute(
            "SELECT objet, date_limite FROM tenders WHERE statut='actif'").fetchall()}
        reportes = rouverts = 0
        for t in cibles:
            ancienne = t["date_limite"][:10]
            nouvelle = dates[ancienne]
            desc = (t["description"] or "").replace(ancienne, nouvelle)
            statut = t["statut"]
            if statut == "expire" and (_empreinte(t["objet"]), nouvelle) not in actifs:
                statut = "actif"
                rouverts += 1
            db.execute("""UPDATE tenders SET date_limite=?, date_limite_initiale=?, description=?,
                             statut=?, report_motif=? WHERE id=?""",
                       (nouvelle + t["date_limite"][10:], t["date_limite"], desc, statut,
                        report["cle"], t["id"]))
            actifs.add((_empreinte(t["objet"]), nouvelle))
            reportes += 1
        db.commit()
    finally:
        db.close()
    if reportes:
        logger.info(f"[reports] {report['cle']}: {reportes} dates reportées, {rouverts} marchés rouverts")
    return {"reportes": reportes, "rouverts": rouverts}


def pour_marche(t: dict) -> dict:
    """Ce que la fiche doit dire: report appliqué, ou report possible (autre source)."""
    if t.get("date_limite_initiale"):
        r = next((x for x in REPORTS if x["cle"] == t.get("report_motif")), REPORTS[0])
        return {"etat": "applique", "avant": t["date_limite_initiale"][:10],
                "apres": (t.get("date_limite") or "")[:10], "report": r}
    jour = (t.get("date_limite") or "")[:10]
    for r in REPORTS:
        if jour in r["dates"] and t.get("source") != "marchespublics":
            return {"etat": "possible", "avant": jour, "apres": r["dates"][jour], "report": r}
    return {}
