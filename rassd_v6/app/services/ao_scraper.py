"""Appels d'offres du portail national (marchespublics.gov.ma).

Le scraper existant (scraper.py) ne couvre que la section « avis d'achat sur
bon de commande ». Les appels d'offres — les marchés que cherchent les
entreprises qui veulent grandir — vivent dans une autre section, bâtie sur
PRADO: la liste ne s'obtient qu'en rejouant l'état du formulaire de
recherche, et l'estimation budgétaire n'apparaît que sur la fiche détaillée.

Stratégie en deux temps, pour ne pas marteler le portail:
  1. la page de résultats donne 100 consultations d'un coup (référence,
     objet, acheteur, lieu, date limite, procédure, catégorie);
  2. la fiche détaillée n'est chargée que pour les consultations inconnues,
     afin d'y lire l'estimation en dirhams et la mention « réservé TPE/PME ».
"""
import logging
import re
import time
from datetime import datetime

from bs4 import BeautifulSoup as BS

from app.core.config import cfg
from app.services.scraper import make_session, _extract_date, is_expired
from app.core.sectors import classify

logger = logging.getLogger("atlas.ao")

RACINE = "https://www.marchespublics.gov.ma"
URL_RECHERCHE = f"{RACINE}/index.php?page=entreprise.EntrepriseAdvancedSearch&AllCons"
CIBLE_TAILLE_PAGE = "ctl0$CONTENU_PAGE$resultSearch$listePageSizeTop"
CIBLE_PAGE_SUIVANTE = "ctl0$CONTENU_PAGE$resultSearch$PagerTop$ctl3"
DELAI = 1.2  # secondes entre deux requêtes: rythme volontairement lent


def _texte(element) -> str:
    return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()


def _champs_formulaire(soup) -> dict:
    """Rejoue l'état courant du formulaire: PRADO rejette un POST incomplet."""
    data = {}
    for inp in soup.find_all("input"):
        nom = inp.get("name")
        typ = (inp.get("type") or "text").lower()
        if not nom or typ in ("submit", "image", "button"):
            continue
        if typ in ("checkbox", "radio") and not inp.has_attr("checked"):
            continue
        data[nom] = inp.get("value", "")
    for sel in soup.find_all("select"):
        nom = sel.get("name")
        if not nom:
            continue
        opt = sel.find("option", selected=True) or sel.find("option")
        data[nom] = opt.get("value", "") if opt else ""
    return data


def _postback(session, soup, cible: str, valeur: str = "", parametre: str = ""):
    """Déclenche une action PRADO (changer la taille de page, page suivante)."""
    data = _champs_formulaire(soup)
    if valeur:
        data[cible] = valeur
    data["PRADO_POSTBACK_TARGET"] = cible
    data["PRADO_POSTBACK_PARAMETER"] = parametre
    r = session.post(URL_RECHERCHE, data=data, timeout=90,
                     headers={"Referer": URL_RECHERCHE})
    r.raise_for_status()
    return BS(r.text, "html.parser")


def _lieu(brut: str) -> str:
    """« - FAHS-ANJRA ... MAROC, FAHS-ANJRA ... » → « Fahs-Anjra ».

    La cellule répète le lieu sous deux formes séparées par des points de
    suspension, parfois préfixées du pays: on garde la ville, une seule fois.
    """
    morceaux = [m.strip(" -,.") for m in re.split(r"\.{2,}", brut or "")]
    morceaux = [m for m in morceaux if m]
    if not morceaux:
        return ""
    ville = morceaux[-1]
    if "," in ville:
        ville = ville.split(",")[-1].strip()
    if ville.upper() == "MAROC" and len(morceaux) > 1:
        ville = morceaux[0].split(",")[-1].strip()
    return ville.title() if ville.isupper() else ville


def _reference_et_organisme(href: str):
    ref = re.search(r"refConsultation=(\d+)", href or "")
    org = re.search(r"orgAcronyme=([\w\-]+)", href or "")
    return (ref.group(1) if ref else ""), (org.group(1) if org else "")


def parse_ligne(ligne) -> dict:
    """Une ligne de résultats → les champs affichables du marché."""
    tds = ligne.find_all("td")
    if len(tds) < 5:
        return {}
    lien = ligne.find("a", href=re.compile("DetailsConsultation"))
    ref, org = _reference_et_organisme(lien.get("href") if lien else "")
    if not ref:
        return {}

    entete = _texte(tds[1])          # procédure, catégorie, date de publication
    corps = _texte(tds[2])           # référence, objet, acheteur
    lieu = _texte(tds[3]).strip(" -.")
    limite = _extract_date(_texte(tds[4]))

    procedure = ""
    m = re.search(r"(Appel d'offres[^A-Z]*|Concours|Consultation architecturale)", entete)
    if m:
        procedure = m.group(1).strip(" .")
    categorie = ""
    m = re.search(r"\b(Travaux|Fournitures|Services)\b", entete)
    if m:
        categorie = m.group(1)

    objet = ""
    m = re.search(r"Objet\s*:\s*(.+?)(?:\s+Acheteur public\s*:|$)", corps)
    if m:
        objet = m.group(1).strip(" .…")
    acheteur = ""
    m = re.search(r"Acheteur public\s*:\s*(.+)$", corps)
    if m:
        acheteur = m.group(1).strip(" .…")
    reference = corps.split(" - ")[0].strip() if " - " in corps else ""

    lieu = _lieu(lieu)

    return {
        "ref": ref, "org": org, "reference": reference[:80],
        "objet": objet[:400], "acheteur": acheteur[:200],
        "region": lieu[:100],
        "date_limite": limite, "procedure": procedure[:80], "categorie": categorie,
        "date_publication": _extract_date(entete),
    }


def parse_fiche(html: str) -> dict:
    """Fiche détaillée: estimation en dirhams et réservation TPE/PME."""
    soup = BS(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    txt = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    # La fiche commence par les menus du portail. Les garder polluerait la
    # description et, surtout, la classification sectorielle: « Aller au menu »
    # suffisait à faire passer un marché d'assainissement pour de la menuiserie.
    depart = txt.find("Référence")
    if depart > 0:
        txt = txt[depart:]

    montant = ""
    m = re.search(r"Estimation\s*\(en Dhs[^)]*\)\s*\*?\s*:\s*([\d\s.,]+)", txt)
    if m:
        chiffre = m.group(1).strip(" .,")
        # « 0,00 » signifie « non communiquée »: mieux vaut ne rien afficher
        # qu'un budget nul qui ferait renoncer une entreprise.
        if re.search(r"[1-9]", chiffre):
            montant = f"{chiffre} MAD"
    reserve = bool(re.search(r"Réservé à la TPE et PME", txt, re.I))
    return {"montant": montant[:80], "reserve_pme": reserve,
            "description": txt[:3000]}


def _lister(session, pages: int, log_fn) -> list:
    """Parcourt les pages de résultats et renvoie les lignes analysées."""
    r = session.get(URL_RECHERCHE, timeout=60)
    r.raise_for_status()
    soup = BS(r.text, "html.parser")
    soup = _postback(session, soup, CIBLE_TAILLE_PAGE, "100")

    lignes, vues = [], set()
    for numero in range(1, pages + 1):
        trouvees = 0
        for tr in soup.select("tr.on, tr.off"):
            fiche = parse_ligne(tr)
            if fiche and fiche["ref"] not in vues:
                vues.add(fiche["ref"])
                lignes.append(fiche)
                trouvees += 1
        log_fn(f"  page {numero}: {trouvees} consultation(s)")
        if trouvees == 0 or numero == pages:
            break
        time.sleep(DELAI)
        try:
            soup = _postback(session, soup, CIBLE_PAGE_SUIVANTE)
        except Exception as e:
            log_fn(f"  pagination interrompue: {str(e)[:80]}")
            break
    return lignes


def run(known_ids: set, log_fn=print, pages: int = 3) -> list:
    """Collecte les appels d'offres ouverts; ne renvoie que les nouveaux."""
    session = make_session()
    marches = []
    try:
        lignes = _lister(session, pages, log_fn)
    except Exception as e:
        log_fn(f"  ⚠ liste des appels d'offres indisponible: {str(e)[:100]}")
        return []

    log_fn(f"  {len(lignes)} consultation(s) listée(s)")
    for ligne in lignes:
        tid = f"ao_{ligne['ref']}"
        if tid in known_ids:
            continue
        if not ligne["objet"] or (ligne["date_limite"] and is_expired(ligne["date_limite"])):
            continue

        detail = {}
        url = (f"{RACINE}/?page=entreprise.EntrepriseDetailsConsultation"
               f"&refConsultation={ligne['ref']}&orgAcronyme={ligne['org']}")
        try:
            rep = session.get(url, timeout=45, headers={"Referer": URL_RECHERCHE})
            if rep.status_code == 200:
                detail = parse_fiche(rep.text)
        except Exception as e:
            logger.warning(f"[ao {tid}] fiche indisponible: {str(e)[:80]}")
        time.sleep(DELAI)

        # Classement sur le seul signal fiable: l'objet du marché et sa
        # catégorie. Le reste de la fiche ajoute surtout du bruit.
        texte_classement = f"{ligne['objet']} {ligne['categorie']}"
        marches.append({
            "id": tid,
            "objet": ligne["objet"],
            "acheteur": ligne["acheteur"],
            "region": ligne["region"],
            "date_publication": ligne["date_publication"],
            "date_limite": ligne["date_limite"],
            "montant": detail.get("montant", ""),
            "secteur": classify(texte_classement),
            "url": url,
            "source": "marchespublics",
            "statut": "actif",
            "description": detail.get("description", ligne["objet"])[:3000],
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type_offre": "Public",
            # Ici, ce sont bien des marchés (appels d'offres), pas des bons
            # de commande: les deux pages du site restent distinctes.
            "type_procedure": "marche",
        })
    log_fn(f"  {len(marches)} nouvel(aux) appel(s) d'offres")
    return marches
