# -*- coding: utf-8 -*-
"""Les portails d'achats d'entreprises publiques bâtis sur le même logiciel
que le portail national (PRADO / Atexo).

Certaines entreprises publiques ne publient pas sur marchespublics.gov.ma
mais sur leur propre portail — Masen sur etendering.masen.ma. Ces portails
présentent les consultations en cours dans les mêmes cartes que le portail
national: on réutilise sa lecture (app/services/ao_scraper.py). Leur liste
est courte — quelques dizaines d'avis —, une page suffit.

Ajouter un portail: une ligne dans PORTAILS, si sa page « consultations en
cours » répond avec les cartes « contentColumn ».
"""
import logging
import time
from datetime import datetime

from bs4 import BeautifulSoup as BS

from app.core.objets import sans_repetition
from app.core.sectors import classify
from app.services import ao_scraper as ao
from app.services.scraper import is_expired, make_session

logger = logging.getLogger("atlas.prado")

# (code, racine, nom de l'acheteur à défaut de celui de la carte)
PORTAILS = (
    ("masen", "https://etendering.masen.ma", "Masen"),
)


def _en_cours(racine: str) -> str:
    return f"{racine}/index.php?page=entreprise.EntrepriseAdvancedSearch&AllCons&EnCours&searchAnnCons"


def lire_portail(code: str, racine: str, nom: str, known_ids: set, log_fn=print,
                 session=None) -> list:
    """Les consultations en cours d'un portail, nouvelles seulement."""
    s = session or make_session()
    try:
        r = s.get(_en_cours(racine), timeout=60)
        r.raise_for_status()
    except Exception as e:
        log_fn(f"⚠ {nom}: portail injoignable — {str(e)[:120]}")
        return []
    soup = BS(r.text, "html.parser")
    fiches = [f for f in (ao.parse_carte(c) for c in ao._cartes(soup)) if f]
    sortie = []
    for f in fiches:
        tid = f"{code}_{f['ref']}"
        if tid in known_ids or not f["objet"] or (f["date_limite"] and is_expired(f["date_limite"])):
            continue
        url = (f"{racine}/?page=entreprise.EntrepriseDetailsConsultation"
               f"&refConsultation={f['ref']}&orgAcronyme={f['org']}")
        detail = {}
        try:
            rep = s.get(url, timeout=45)
            if rep.status_code == 200:
                detail = ao.parse_fiche(rep.text)
        except Exception as e:
            logger.warning(f"[{code} {tid}] fiche indisponible: {str(e)[:80]}")
        time.sleep(ao.DELAI)
        objet = sans_repetition(f["objet"])
        acheteur = f["acheteur"] or nom
        sortie.append({
            "id": tid, "objet": objet, "acheteur": acheteur, "region": f["region"],
            "date_publication": "", "date_limite": f["date_limite"],
            "montant": detail.get("montant", ""), "secteur": classify(objet, f["categorie"]),
            "url": url, "source": code, "statut": "actif",
            "type_offre": "Public", "type_procedure": "marche",
            "description": detail.get("description", ""),
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        log_fn(f"✓ {tid} │ {objet[:50]}")
    log_fn(f"  {nom}: {len(fiches)} consultation(s) en cours, {len(sortie)} nouvelle(s)")
    return sortie


def run(known_ids: set, log_fn=print) -> list:
    """Tous les portails, l'un après l'autre; un portail en panne n'arrête pas les autres."""
    tout = []
    for code, racine, nom in PORTAILS:
        tout += lire_portail(code, racine, nom, known_ids, log_fn)
    return tout
