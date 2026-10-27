# -*- coding: utf-8 -*-
"""Relais local: collecte le portail des marchés publics depuis un poste au
Maroc et dépose les résultats sur le site.

Depuis le 20/10/2026 marchespublics.gov.ma refuse les connexions venues de
l'étranger, dont celles du serveur du site. Ce programme tourne sur un poste
au Maroc, avec le même code de collecte que le serveur, et envoie ce qu'il
trouve à https://marocentrepreneuriat.com/api/relais/depot.

Rien ne se perd:
- au démarrage et à chaque cycle, il demande au site le dernier avis qu'il
  connaît et repart de là — un poste éteint une nuit rattrape la nuit;
- un dépôt qui échoue (connexion coupée, site injoignable) est gardé dans
  relais/attente/ et renvoyé au cycle suivant, avant toute nouvelle collecte;
- après une interruption, le site lui demande de relire 40 pages d'appels
  d'offres au lieu de 3.

Lancement: py relais\\relais_portail.py   (une fois: --une-fois; rattrapage: --jours=40)
Configuration: relais\\config.json  {"site": "...", "jeton": "..."}
Journal: relais\\relais.log
"""
import json
import logging
import os
import socket
import sys
import time
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler

import requests

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
sys.path.insert(0, RACINE)

ATTENTE = os.path.join(ICI, "attente")
INTERVALLE = 10 * 60          # un cycle toutes les dix minutes
PORT_VERROU = 47613           # un seul relais à la fois sur le poste
# « --jours=40 » force un rattrapage des appels d'offres sur 40 jours de mise
# en ligne, au premier lancement par exemple.
JOURS_FORCES = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--jours=")), 0)

os.makedirs(ATTENTE, exist_ok=True)
journal = logging.getLogger("relais")
journal.setLevel(logging.INFO)
_f = RotatingFileHandler(os.path.join(ICI, "relais.log"), maxBytes=1_000_000,
                         backupCount=3, encoding="utf-8")
_f.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
journal.addHandler(_f)
if sys.stdout:
    journal.addHandler(logging.StreamHandler(sys.stdout))


def log(message: str):
    journal.info(message)


def config() -> dict:
    with open(os.path.join(ICI, "config.json"), encoding="utf-8") as f:
        c = json.load(f)
    c["site"] = c["site"].rstrip("/")
    return c


def entetes(c: dict) -> dict:
    return {"X-Relais-Jeton": c["jeton"], "User-Agent": "relais-maroc-entrepreneuriat/1"}


# ── File d'attente ──────────────────────────────────────────────────────────

def mettre_en_attente(lot: dict):
    nom = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.json"
    with open(os.path.join(ATTENTE, nom), "w", encoding="utf-8") as f:
        json.dump(lot, f, ensure_ascii=False)
    log(f"  ⏸ dépôt gardé en attente ({len(lot['marches'])} marché(s)): {nom}")


def ids_en_attente() -> set:
    ids = set()
    for nom in os.listdir(ATTENTE):
        try:
            with open(os.path.join(ATTENTE, nom), encoding="utf-8") as f:
                ids.update(t.get("id") for t in json.load(f).get("marches", []))
        except Exception:
            continue
    return ids


def envoyer(c: dict, lot: dict) -> bool:
    try:
        r = requests.post(f"{c['site']}/api/relais/depot", json=lot,
                          headers=entetes(c), timeout=120)
        if r.status_code == 200 and r.json().get("ok"):
            log(f"  ↑ {lot['source']}: {r.json().get('enregistres')} nouveau(x) "
                f"sur {len(lot['marches'])} envoyé(s)")
            return True
        log(f"  ⚠ dépôt refusé ({r.status_code}): {r.text[:160]}")
    except Exception as e:
        log(f"  ⚠ site injoignable: {str(e)[:160]}")
    return False


def vider_attente(c: dict) -> bool:
    """Renvoie les dépôts en attente, du plus ancien au plus récent."""
    for nom in sorted(os.listdir(ATTENTE)):
        chemin = os.path.join(ATTENTE, nom)
        try:
            with open(chemin, encoding="utf-8") as f:
                lot = json.load(f)
        except Exception:
            os.replace(chemin, chemin + ".illisible")
            continue
        if not envoyer(c, lot):
            return False
        os.remove(chemin)
        log(f"  ✓ dépôt en attente livré: {nom}")
    return True


def deposer(c: dict, source: str, marches: list, debut: datetime):
    lot = {"source": source, "marches": marches, "debut": debut.isoformat(timespec="seconds")}
    if not envoyer(c, lot):
        mettre_en_attente(lot)


# ── Un cycle ────────────────────────────────────────────────────────────────

def cycle(c: dict):
    from app.services import ao_scraper, scraper

    log("═══ Cycle du relais ═══")
    if not vider_attente(c):
        log("  Site injoignable: nouvelle tentative au prochain cycle.")
        return
    try:
        r = requests.get(f"{c['site']}/api/relais/etat", headers=entetes(c), timeout=60)
        r.raise_for_status()
        etat = r.json()
    except Exception as e:
        log(f"  ⚠ état du site illisible: {str(e)[:160]}")
        return
    deja = ids_en_attente()
    log(f"  Site: dernier bon de commande #{etat['bdc_max']}, "
        f"{len(etat['ao_connus'])} appel(s) d'offres connus, {etat['pages_ao']} page(s) à lire")

    # Bons de commande: le scraper repart du plus haut identifiant connu.
    debut = datetime.now()
    try:
        connus = {f"bdc_{n}" for n in etat["bdc_connus"]} | deja
        bdc = scraper.run(connus, lambda m: log("  " + m))
        deposer(c, "marchespublics", bdc, debut)
    except ConnectionError as e:
        log(f"  ⚠ portail injoignable (bons de commande): {str(e)[:160]}")
    except Exception as e:
        log(f"  ⚠ erreur bons de commande: {e!r}")

    # Appels d'offres.
    debut = datetime.now()
    try:
        ao = ao_scraper.run(set(etat["ao_connus"]) | deja, lambda m: log("  " + m),
                            pages=JOURS_FORCES or int(etat.get("pages_ao") or 3),
                            par_lot=lambda lot: deposer(c, "marchespublics-ao", list(lot), debut))
        deposer(c, "marchespublics-ao", ao, debut)
    except ConnectionError as e:
        log(f"  ⚠ portail injoignable (appels d'offres): {str(e)[:160]}")
    except Exception as e:
        log(f"  ⚠ erreur appels d'offres: {e!r}")


def completer_fiches(c: dict, maximum: int = 200):
    """Relit sur le portail les fiches que le site signale incomplètes."""
    from app.services import ao_scraper
    try:
        r = requests.get(f"{c['site']}/api/relais/a-completer", params={"limite": maximum},
                         headers=entetes(c), timeout=60)
        r.raise_for_status()
        a_faire = r.json()
    except Exception as e:
        log(f"  ⚠ liste des fiches à compléter illisible: {str(e)[:160]}")
        return
    if not a_faire.get("fiches"):
        return
    log(f"  Fiches à compléter: {a_faire['reste']} (lot de {len(a_faire['fiches'])})")
    session, lot = ao_scraper.make_session(), []

    def livrer():
        try:
            rep = requests.post(f"{c['site']}/api/relais/fiches", json={"fiches": lot},
                                headers=entetes(c), timeout=120)
            log(f"  ↑ fiches complétées: {rep.json().get('corriges')} sur {len(lot)}")
        except Exception as e:
            log(f"  ⚠ fiches non livrées: {str(e)[:160]}")
        lot.clear()

    for f in a_faire["fiches"]:
        if not f.get("url", "").startswith("https://www.marchespublics.gov.ma"):
            continue
        try:
            rep = session.get(f["url"], timeout=45)
            fiche = ao_scraper.parse_fiche(rep.text) if rep.status_code == 200 else {}
        except Exception as e:
            log(f"  ⚠ portail injoignable (fiches): {str(e)[:120]}")
            break
        if fiche.get("description", "").startswith("Date et heure limite"):
            lot.append({"id": f["id"], "description": fiche["description"],
                        "montant": fiche.get("montant", "")})
        if len(lot) >= 50:
            livrer()
        time.sleep(ao_scraper.DELAI)
    if lot:
        livrer()


def main():
    try:
        verrou = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        verrou.bind(("127.0.0.1", PORT_VERROU))
    except OSError:
        log("Un relais tourne déjà sur ce poste: arrêt.")
        return
    c = config()
    une_fois = "--une-fois" in sys.argv
    log(f"Relais démarré — site {c['site']}, un cycle toutes les {INTERVALLE // 60} min")
    while True:
        t0 = time.time()
        try:
            cycle(c)
            completer_fiches(c)
        except Exception as e:
            log(f"⚠ cycle interrompu: {e!r}")
        # Le rattrapage forcé ne vaut que pour le premier cycle; ensuite c'est
        # le site qui dit s'il faut relire plus loin (après une coupure).
        global JOURS_FORCES
        JOURS_FORCES = 0
        if une_fois:
            break
        # Attente découpée: après une mise en veille, le cycle repart dès le réveil.
        while time.time() - t0 < INTERVALLE:
            time.sleep(15)


if __name__ == "__main__":
    main()
