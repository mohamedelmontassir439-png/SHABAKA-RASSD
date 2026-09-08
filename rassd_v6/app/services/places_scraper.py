"""
Maroc Entrepreneuriat — Annuaire d'entreprises via Google Places API

Pourquoi l'API officielle et non un scraping de Google Maps:
le scraping direct des pages Maps viole les conditions d'utilisation de
Google, déclenche des CAPTCHA au bout de quelques dizaines de requêtes et
fait bannir l'IP du serveur. L'API Places (New) renvoie exactement les mêmes
informations d'établissement (nom, adresse, téléphone, site web) de façon
autorisée, stable et paginée.

Ce que l'API ne fournit pas: l'adresse email. Google ne l'expose dans aucune
de ses interfaces. Elle est donc recherchée séparément sur le site web de
l'entreprise (voir email_finder.py).
"""
import logging
import re
import time
from datetime import datetime

import requests

from app.core.config import cfg
from app.core.sectors import SECTORS

logger = logging.getLogger("atlas.places")

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Champs demandés — le masque conditionne directement la facturation Google,
# on ne demande donc que ce qui sert à remplir une fiche entreprise.
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.businessStatus",
    "places.primaryTypeDisplayName",
    "places.addressComponents",
    "nextPageToken",
])

# Principales villes économiques marocaines. Google Places raisonne par
# zone: interroger « secteur + ville » couvre bien mieux le territoire
# qu'une requête nationale unique, qui sature sur Casablanca.
VILLES = [
    "Casablanca", "Rabat", "Marrakech", "Tanger", "Fès", "Agadir", "Meknès",
    "Oujda", "Kénitra", "Tétouan", "Safi", "El Jadida", "Béni Mellal",
    "Nador", "Mohammedia", "Khouribga", "Settat", "Laâyoune", "Errachidia",
    "Essaouira",
]

# Termes de recherche plus efficaces que le libellé officiel pour les
# secteurs les plus demandés. Les autres retombent sur le libellé nettoyé.
REQUETES_SECTEUR = {
    "T101": "entreprise de construction bâtiment",
    "T102": "entreprise de terrassement travaux publics",
    "T103": "menuiserie métallerie charpente",
    "T104": "plomberie chauffage climatisation",
    "T105": "entreprise de peinture vitrerie",
    "T106": "étanchéité isolation bâtiment",
    "S931": "société développement logiciel informatique",
    "S922": "laboratoire d'analyses médicales",
    "S923": "laboratoire d'analyses BTP",
}


def _requete_secteur(code: str) -> str:
    """Construit un terme de recherche exploitable à partir d'un code secteur."""
    if code in REQUETES_SECTEUR:
        return REQUETES_SECTEUR[code]
    libelle = SECTORS.get(code, "")
    # « Menuiserie – Métallerie – Charpente » -> « Menuiserie Métallerie »
    parties = [p.strip() for p in re.split(r"[–\-,&/]", libelle) if p.strip()]
    return " ".join(parties[:2]) if parties else libelle


def _composant(place: dict, *types_recherches) -> str:
    """Lit un composant d'adresse (ville, région) renvoyé par l'API."""
    for comp in place.get("addressComponents", []) or []:
        for t in comp.get("types", []) or []:
            if t in types_recherches:
                return comp.get("longText") or comp.get("shortText") or ""
    return ""


def place_vers_entreprise(place: dict, secteur: str, requete: str) -> dict:
    """Convertit une fiche Places en fiche entreprise de notre modèle."""
    nom = (place.get("displayName") or {}).get("text", "").strip()
    if not nom:
        return {}
    return {
        "legal_name":  nom,
        "sector":      secteur,
        "subsector":   (place.get("primaryTypeDisplayName") or {}).get("text", ""),
        "city":        _composant(place, "locality", "postal_town"),
        "region":      _composant(place, "administrative_area_level_1"),
        "address":     place.get("formattedAddress", ""),
        "phone":       place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber") or "",
        "website":     place.get("websiteUri", ""),
        "source":      "google-places",
        "source_type": "annuaire",
        "source_url":  f"https://www.google.com/maps/place/?q=place_id:{place.get('id','')}",
    }


def recherche_texte(requete: str, page_token: str = "") -> tuple:
    """Un appel Text Search. Retourne (liste_de_places, page_token_suivant).

    Lève RuntimeError sur une clé absente ou refusée: mieux vaut interrompre
    la collecte avec un message clair que d'enchaîner des appels facturés
    qui échouent tous.
    """
    if not cfg.GOOGLE_PLACES_API_KEY:
        raise RuntimeError("GOOGLE_PLACES_API_KEY non configurée")
    corps = {"textQuery": requete, "regionCode": "MA", "languageCode": "fr", "pageSize": 20}
    if page_token:
        corps["pageToken"] = page_token
    r = requests.post(
        SEARCH_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": cfg.GOOGLE_PLACES_API_KEY,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        json=corps, timeout=25)
    if r.status_code in (401, 403):
        raise RuntimeError(f"clé Google refusée ({r.status_code}) — vérifiez la clé et l'activation de Places API")
    if r.status_code == 429:
        raise RuntimeError("quota Google dépassé (429)")
    if r.status_code != 200:
        raise RuntimeError(f"Places API {r.status_code}: {r.text[:160]}")
    data = r.json()
    return data.get("places", []) or [], data.get("nextPageToken", "") or ""


def collecter(secteurs: list, villes: list, log_fn=print,
              avec_email: bool = True, max_par_requete: int = 0) -> dict:
    """Collecte les entreprises pour des secteurs et des villes donnés.

    Chaque fiche passe par upsert_company: la normalisation des noms et la
    déduplication déjà en place s'appliquent, donc relancer une collecte
    enrichit les fiches existantes au lieu de les dupliquer.
    """
    from app.core.database import get_db
    from app.services.companies import upsert_company
    from app.services.email_finder import find_email

    max_par_requete = max_par_requete or cfg.PLACES_MAX_PER_QUERY
    stats = {"requetes": 0, "trouvees": 0, "creees": 0, "fusionnees": 0,
             "rejetees": 0, "emails": 0, "erreurs": 0}
    db = get_db()
    try:
        for code in secteurs:
            terme = _requete_secteur(code)
            if not terme:
                continue
            for ville in villes:
                requete = f"{terme} {ville} Maroc"
                stats["requetes"] += 1
                collectees, token = 0, ""
                while collectees < max_par_requete:
                    try:
                        places, token = recherche_texte(requete, token)
                    except RuntimeError as e:
                        log_fn(f"❌ {e}")
                        stats["erreurs"] += 1
                        db.commit()
                        return stats          # clé/quota: inutile d'insister
                    except Exception as e:
                        log_fn(f"⚠ {requete}: {e}")
                        stats["erreurs"] += 1
                        break
                    if not places:
                        break
                    for place in places:
                        fiche = place_vers_entreprise(place, code, requete)
                        if not fiche:
                            continue
                        stats["trouvees"] += 1
                        collectees += 1
                        if avec_email and fiche.get("website"):
                            email = find_email(fiche["website"])
                            if email:
                                fiche["email"] = email
                                stats["emails"] += 1
                        _cid, action = upsert_company(db, fiche)
                        if action == "created":
                            stats["creees"] += 1
                        elif action == "rejected":
                            stats["rejetees"] += 1
                        else:
                            stats["fusionnees"] += 1
                    db.commit()
                    if not token:
                        break
                    time.sleep(cfg.PLACES_DELAY_MS / 1000)
                log_fn(f"✓ {code} · {ville} — {collectees} établissement(s)")
                time.sleep(cfg.PLACES_DELAY_MS / 1000)
        db.commit()
    finally:
        db.close()
    log_fn(f"═══ {stats['creees']} créées · {stats['fusionnees']} fusionnées · "
           f"{stats['emails']} emails · {stats['rejetees']} rejetées ═══")
    return stats
