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
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup as BS

from app.core.config import cfg
from app.services.scraper import make_session, _extract_date, is_expired
from app.core.sectors import classify
from app.core.objets import sans_repetition

logger = logging.getLogger("atlas.ao")

RACINE = "https://www.marchespublics.gov.ma"
URL_RECHERCHE = f"{RACINE}/index.php?page=entreprise.EntrepriseAdvancedSearch&AllCons"
CIBLE_TAILLE_PAGE = "ctl0$CONTENU_PAGE$resultSearch$listePageSizeTop"
CIBLE_PAGE_SUIVANTE = "ctl0$CONTENU_PAGE$resultSearch$PagerTop$ctl3"
# Depuis sa remise en service (26/10/2026), le portail présente les
# consultations en cartes et non plus en tableau, triées par date limite. La
# recherche avancée « en cours » filtre par date de mise en ligne: on ne
# demande que ce qui a paru depuis quelques jours, au lieu de parcourir les
# cent mille consultations de la liste complète.
URL_EN_COURS = f"{RACINE}/index.php?page=entreprise.EntrepriseAdvancedSearch&AllCons&EnCours&searchAnnCons"
# Le formulaire de cette page poste vers une autre adresse que la sienne:
# poster sur URL_EN_COURS renvoie le formulaire vide, sans rien chercher.
URL_ACTION = f"{RACINE}/index.php?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons"
CHAMP = "ctl0$CONTENU_PAGE$AdvancedSearch$"
CIBLE_LANCER = CHAMP + "lancerRecherche"
CIBLE_SUIVANTE_CARTES = "ctl0$CONTENU_PAGE$resultSearch$PagerTop$ctl2"
_MOIS = {"jan": 1, "janv": 1, "feb": 2, "fev": 2, "fév": 2, "févr": 2, "mar": 3, "mars": 3,
         "apr": 4, "avr": 4, "may": 5, "mai": 5, "jun": 6, "juin": 6, "jul": 7, "juil": 7,
         "aug": 8, "aou": 8, "aoû": 8, "août": 8, "sep": 9, "sept": 9, "oct": 10,
         "nov": 11, "dec": 12, "déc": 12}
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


def _postback(session, soup, cible: str, valeur: str = "", parametre: str = "",
              url: str = "", champs: dict = None):
    """Déclenche une action PRADO (changer la taille de page, page suivante)."""
    url = url or URL_RECHERCHE
    data = _champs_formulaire(soup)
    data.update(champs or {})
    if valeur:
        data[cible] = valeur
    data["PRADO_POSTBACK_TARGET"] = cible
    data["PRADO_POSTBACK_PARAMETER"] = parametre
    r = session.post(url, data=data, timeout=90, headers={"Referer": url})
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
    # L'heure limite précède « Référence »: on la reprend avant de couper,
    # sinon la fiche ne connaît que le jour — et un pli se refuse à la minute.
    limite = re.search(r"Date et heure limite de remise des plis\s*:\s*"
                       r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", txt)
    depart = txt.find("Référence")
    if depart > 0:
        txt = txt[depart:]
    if limite and "Date et heure limite" not in txt:
        txt = f"Date et heure limite de remise des plis : {limite.group(1)} {txt}"

    montant = ""
    m = re.search(r"Estimation\s*\(en Dhs[^)]*\)\s*\*?\s*:\s*([\d\s.,]+)", txt)
    if m:
        chiffre = m.group(1).strip(" .,")
        # « 0,00 » signifie « non communiquée »: mieux vaut ne rien afficher
        # qu'un budget nul qui ferait renoncer une entreprise.
        if re.search(r"[1-9]", chiffre):
            montant = f"{chiffre} MAD"
    # L'étiquette figure sur toutes les fiches: c'est sa valeur qui compte.
    reserve = bool(re.search(r"Réservé à la TPE et PME[^:]{0,140}:\s*\*?\s*Oui", txt, re.I))
    return {"montant": montant[:80], "reserve_pme": reserve,
            "description": txt[:3000]}


def _date_carte(texte: str) -> str:
    """« Mar 29 Dec 2026 10:30 » → « 29/12/2026 »."""
    m = re.search(r"(\d{1,2})\s+([A-Za-zéûÉ]{3,5})\.?\s+(\d{4})", texte or "")
    if not m:
        return _extract_date(texte)
    mois = _MOIS.get(m.group(2).lower())
    if not mois:
        return ""
    try:
        return date(int(m.group(3)), mois, int(m.group(1))).strftime("%d/%m/%Y")
    except ValueError:
        return ""


def parse_carte(carte) -> dict:
    """Une carte de résultats (présentation du 26/10/2026) → les champs du marché."""
    ref, org = _reference_et_organisme(carte.get("onclick", ""))
    if not ref:
        return {}
    # La partie masquée (« Détail ») répète l'objet en entier: on l'écarte.
    for cache in carte.find_all("div", style=re.compile(r"display:\s*none")):
        cache.decompose()
    texte = _texte(carte)
    procedure = ""
    vertical = carte.find("span", class_="verticalText")
    if vertical:
        titre = vertical.find("span", title=True)
        procedure = (titre.get("title") if titre else _texte(vertical)).strip()
    reference = ""
    m = carte.find("span", id=re.compile(r"_referencem$"))
    if m:
        reference = _texte(m)
    objet = ""
    bloc = carte.find("div", class_="p-objet")
    if bloc:
        objet = re.sub(r"^\s*Objet\s*:\s*", "", _texte(bloc)).strip(" .…-")
    acheteur = ""
    m = re.search(r"Acheteur public\s*:\s*(.+?)\s+Date limite", texte)
    if m:
        acheteur = m.group(1).strip(" .…")
    limite = ""
    m = re.search(r"Date limite de remise des plis\s+(.{6,30}?)\s+(?:Lieu d|$)", texte)
    if m:
        limite = _date_carte(m.group(1))
    lieu = ""
    m = re.search(r"Lieu d'exécution\s+(.+)$", texte)
    if m:
        lieu = _lieu(m.group(1))
    categorie = ""
    m = re.search(r"\b(Travaux|Fournitures|Services)\b", texte)
    if m:
        categorie = m.group(1)
    return {
        "ref": ref, "org": org, "reference": reference[:80],
        "objet": objet[:400], "acheteur": acheteur[:200], "region": lieu[:100],
        "date_limite": limite, "procedure": procedure[:80], "categorie": categorie,
        "date_publication": "",
    }


def _cartes(soup) -> list:
    return [d for d in soup.find_all("div", class_="contentColumn")
            if "refConsultation" in (d.get("onclick") or "")]


def _lister_cartes(session, jours: int, log_fn, pages_max: int = 20) -> list:
    """Les consultations en cours mises en ligne depuis `jours` jours."""
    r = session.get(URL_EN_COURS, timeout=60)
    r.raise_for_status()
    soup = BS(r.text, "html.parser")
    depuis = (date.today() - timedelta(days=jours)).strftime("%d/%m/%Y")
    champs = {CHAMP + "dateMiseEnLigneCalculeStart": depuis,
              CHAMP + "dateMiseEnLigneCalculeEnd": date.today().strftime("%d/%m/%Y"),
              CIBLE_LANCER: "Lancer la recherche"}
    soup = _postback(session, soup, CIBLE_LANCER, url=URL_ACTION, champs=champs)
    soup = _postback(session, soup, CIBLE_TAILLE_PAGE, "500", url=URL_ACTION)
    total = soup.find(id=re.compile(r"resultSearch_nombreElement$"))
    log_fn(f"  consultations en cours mises en ligne depuis le {depuis}: "
           f"{_texte(total) if total else '?'}")
    lignes, vues = [], set()
    for numero in range(1, pages_max + 1):
        trouvees = 0
        cartes = _cartes(soup)
        for carte in cartes:
            fiche = parse_carte(carte)
            if fiche and fiche["ref"] not in vues:
                vues.add(fiche["ref"])
                lignes.append(fiche)
                trouvees += 1
        log_fn(f"  page {numero}: {trouvees} consultation(s)")
        # On s'arrête sur une page incomplète du portail, pas sur une page
        # dont on a écarté un doublon: le 27/10/2026, « 499 » sur une page
        # pleine arrêtait la lecture à la moitié des 4 880 consultations.
        if len(cartes) < 500:
            break
        time.sleep(DELAI)
        soup = _postback(session, soup, CIBLE_SUIVANTE_CARTES, url=URL_ACTION)
    return lignes


def _lister(session, pages: int, log_fn) -> list:
    """Parcourt les pages de résultats et renvoie les lignes analysées."""
    r = session.get(URL_RECHERCHE, timeout=60)
    r.raise_for_status()
    soup = BS(r.text, "html.parser")
    soup = _postback(session, soup, CIBLE_TAILLE_PAGE, "100")

    lignes, vues = [], set()
    for numero in range(1, pages + 1):
        trouvees = 0
        # Une ligne sur deux porte la classe « on », l'autre n'a aucune classe:
        # se fier aux classes faisait perdre la moitié des résultats. On retient
        # donc toute ligne qui contient un lien de consultation.
        for tr in soup.find_all("tr"):
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


def run(known_ids: set, log_fn=print, pages: int = 3, par_lot=None, taille_lot: int = 50) -> list:
    """Collecte les appels d'offres ouverts; ne renvoie que les nouveaux.

    `pages` garde son sens d'origine pour l'ancienne présentation; pour la
    nouvelle, il dit sur combien de jours de mise en ligne regarder en
    arrière: 3 en temps normal, 40 pour rattraper une interruption.
    """
    session = make_session()
    marches = []
    try:
        lignes = _lister_cartes(session, max(3, pages), log_fn)
        if not lignes:
            # Ancienne présentation en tableau, si le portail y revenait.
            lignes = _lister(session, pages, log_fn)
        if not lignes:
            raise ConnectionError("aucune consultation lisible sur le portail")
    except Exception as e:
        log_fn(f"  ⚠ liste des appels d'offres indisponible: {str(e)[:100]}")
        # Une liste qu'on n'a pas pu lire n'est pas une liste vide: l'erreur
        # remonte pour que la collecte soit notée en échec, pas en succès à zéro.
        raise ConnectionError(f"liste des appels d'offres indisponible: {str(e)[:160]}") from e

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
        # catégorie. Le reste de la fiche ajoute surtout du bruit. L'objet
        # passe en premier argument: il pèse trois fois la catégorie.
        texte_classement = ligne["categorie"]
        marches.append({
            "id": tid,
            "objet": sans_repetition(ligne["objet"]),
            "acheteur": ligne["acheteur"],
            "region": ligne["region"],
            "date_publication": ligne["date_publication"],
            "date_limite": ligne["date_limite"],
            "montant": detail.get("montant", ""),
            "secteur": classify(ligne["objet"], texte_classement),
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
        # Rattrapage long: chaque fiche coûte une requête. On livre par lots
        # pour qu'une coupure en cours de route ne fasse pas tout reperdre.
        if par_lot and len(marches) >= taille_lot:
            par_lot(marches)
            marches = []
    log_fn(f"  {len(marches)} nouvel(aux) appel(s) d'offres")
    return marches
