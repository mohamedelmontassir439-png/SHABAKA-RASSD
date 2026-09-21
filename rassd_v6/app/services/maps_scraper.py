"""
Maroc Entrepreneuriat — Collecte d'entreprises depuis Google Maps

Pilote un vrai navigateur (Playwright/Chromium) sur les pages publiques de
Google Maps et lit les fiches d'établissement affichées.

À savoir avant de l'utiliser:
  · Google interdit cette collecte dans ses conditions d'utilisation. Le
    risque (blocage de l'IP, compte) est assumé par l'exploitant du serveur.
  · Si Google affiche une vérification anti-robot, la collecte S'ARRÊTE et le
    signale. Aucun contournement de CAPTCHA n'est tenté ni fourni.
  · Le rythme est volontairement lent (pauses entre chaque fiche): une
    collecte rapide se fait bloquer en quelques minutes et ne ramène rien.

L'alternative stable reste l'API Places officielle (places_scraper.py).
"""
import logging
import random
import re
import time
from urllib.parse import quote_plus

from app.core.config import cfg
from app.services.sector_queries import requete_secteur  # noqa: F401

logger = logging.getLogger("atlas.maps")

BASE = "https://www.google.com/maps/search/"

VILLES = [
    "Casablanca", "Rabat", "Marrakech", "Tanger", "Fès", "Agadir", "Meknès",
    "Oujda", "Kénitra", "Tétouan", "Safi", "El Jadida", "Béni Mellal",
    "Nador", "Mohammedia", "Khouribga", "Settat", "Laâyoune", "Errachidia",
    "Essaouira",
]


# Marqueurs d'une page de vérification anti-robot: on s'arrête si l'un
# d'eux apparaît, on ne cherche pas à passer outre.
_MARQUEURS_BLOCAGE = (
    "unusual traffic", "trafic inhabituel", "/sorry/", "recaptcha",
    "notre système a détecté", "systèmes ont détecté",
)

_TEL_RE = re.compile(r"(?:\+212|0)\s?[\d\s\-.]{8,14}")


class BlocageGoogle(RuntimeError):
    """Google a présenté une vérification anti-robot: la collecte s'arrête."""




def _pause(base_ms: int):
    """Pause légèrement irrégulière — un rythme de métronome est le premier
    signal qui distingue un automate d'un visiteur."""
    time.sleep((base_ms + random.randint(0, base_ms // 2)) / 1000)


def _verifier_blocage(page):
    contenu = (page.url + " " + (page.content()[:4000] if page.content else "")).lower()
    for m in _MARQUEURS_BLOCAGE:
        if m in contenu:
            raise BlocageGoogle(
                "Google affiche une vérification anti-robot. Collecte interrompue — "
                "attendez plusieurs heures, ou utilisez l'API Places officielle."
            )


def _accepter_consentement(page):
    """Ferme la bannière de consentement cookies (comportement d'un visiteur)."""
    for sel in ('button[aria-label*="Tout accepter"]', 'button[aria-label*="Accept all"]',
                'form[action*="consent"] button', 'button:has-text("Tout accepter")'):
        try:
            bouton = page.locator(sel).first
            if bouton.is_visible(timeout=1500):
                bouton.click()
                page.wait_for_timeout(1200)
                return
        except Exception:
            continue


def lire_carte(texte: str) -> dict:
    """Extrait catégorie, adresse et téléphone du texte d'une carte de résultat.

    Structure observée sur les résultats marocains (08/09/2026):
        [0] Nom
        [1] Nom (répété)
        [2] 4,3                      ← note
        [3] Catégorie · Adresse      ← parfois un segment vide au milieu
        [4] Fermé · Ouvre à 08:30 · 05 22 23 68 50

    Le repérage se fait par contenu et non par numéro de ligne: Google
    n'affiche pas toujours la note ni les horaires, et les indices glissent.
    """
    infos = {"subsector": "", "address": "", "phone": ""}
    for ligne in [l.strip() for l in (texte or "").split("\n") if l.strip()]:
        if not infos["phone"]:
            m = _TEL_RE.search(ligne)
            if m:
                infos["phone"] = m.group(0).strip()
                # Une ligne d'horaires ne porte ni catégorie ni adresse.
                continue
        if not infos["address"] and "·" in ligne:
            parts = [p.strip() for p in ligne.split("·") if p.strip()]
            if len(parts) >= 2 and not _TEL_RE.search(ligne):
                infos["subsector"] = parts[0][:80]
                infos["address"] = parts[-1][:250]
    return infos


def collecter_requete(page, requete: str, ville: str, secteur: str,
                      max_fiches: int, log_fn) -> list:
    """Collecte les établissements d'une recherche Maps."""
    page.goto(BASE + quote_plus(f"{requete} {ville} Maroc"),
              wait_until="domcontentloaded", timeout=45000)
    _accepter_consentement(page)
    _verifier_blocage(page)

    try:
        page.wait_for_selector('div[role="feed"]', timeout=20000)
    except Exception:
        log_fn(f"⚠ {requete} · {ville}: aucun résultat affiché")
        return []

    feed = page.locator('div[role="feed"]')
    vus, fiches, sans_progres = set(), [], 0

    # Les cartes de résultats portent déjà nom, catégorie, adresse, téléphone
    # et lien du site: on les lit directement, sans ouvrir chaque fiche. C'est
    # nettement plus rapide et cela évite des dizaines de clics par recherche,
    # ce qui est aussi ce qui attire l'attention côté Google.
    while len(fiches) < max_fiches and sans_progres < 3:
        cartes = page.locator('div[role="feed"] > div:has(a[href*="/maps/place/"])')
        total, nouveau = cartes.count(), False

        for i in range(total):
            if len(fiches) >= max_fiches:
                break
            carte = cartes.nth(i)
            try:
                lien = carte.locator('a[href*="/maps/place/"]').first
                href = lien.get_attribute("href") or ""
                nom  = (lien.get_attribute("aria-label") or "").strip()
            except Exception:
                continue
            if not href or href in vus or not nom:
                continue
            vus.add(href)
            nouveau = True

            fiche = {"legal_name": nom, "sector": secteur, "city": ville,
                     "source": "google-maps", "source_type": "annuaire",
                     "source_url": href[:400]}
            try:
                fiche.update(lire_carte(carte.inner_text()))
            except Exception as e:
                logger.debug(f"[maps] texte de carte illisible: {e}")
            try:
                site = carte.locator('a[aria-label^="Visiter le site"], a[data-value="Site Web"]').first
                if site.count():
                    fiche["website"] = site.get_attribute("href") or ""
            except Exception:
                pass

            fiches.append(fiche)
            log_fn(f"  · {nom[:42]} — {fiche.get('phone') or 'sans tél.'}")

        if nouveau:
            sans_progres = 0
        else:
            sans_progres += 1
        try:
            feed.hover()
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1500)
            _verifier_blocage(page)
        except BlocageGoogle:
            raise
        except Exception:
            break
        _pause(cfg.MAPS_DELAY_MS)

    return fiches


def collecter(secteurs: list, villes: list, log_fn=print, avec_email: bool = True,
              max_par_requete: int = 0, headless: bool = True) -> dict:
    """Collecte Google Maps pour des secteurs et villes donnés."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log_fn("❌ Playwright n'est pas installé sur ce serveur "
               "(pip install playwright && playwright install chromium)")
        return {"erreurs": 1, "trouvees": 0, "creees": 0, "fusionnees": 0,
                "rejetees": 0, "emails": 0, "requetes": 0}

    from app.core.database import get_db
    from app.services.companies import upsert_company
    from app.services.email_finder import find_email

    max_par_requete = max_par_requete or cfg.MAPS_MAX_PER_QUERY
    stats = {"requetes": 0, "trouvees": 0, "creees": 0, "fusionnees": 0,
             "rejetees": 0, "emails": 0, "erreurs": 0}
    db = get_db()
    try:
        with sync_playwright() as p:
            navigateur = p.chromium.launch(headless=headless, args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox", "--disable-dev-shm-usage",
            ])
            contexte = navigateur.new_context(
                locale="fr-FR", timezone_id="Africa/Casablanca",
                viewport={"width": 1360, "height": 900},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
            )
            page = contexte.new_page()
            try:
                for code in secteurs:
                    terme = requete_secteur(code)
                    if not terme:
                        continue
                    for ville in villes:
                        stats["requetes"] += 1
                        log_fn(f"▸ {code} · {ville}")
                        try:
                            fiches = collecter_requete(page, terme, ville, code,
                                                       max_par_requete, log_fn)
                        except BlocageGoogle as e:
                            log_fn(f"⛔ {e}")
                            stats["erreurs"] += 1
                            db.commit()
                            return stats
                        except Exception as e:
                            log_fn(f"⚠ {code} · {ville}: {str(e)[:120]}")
                            stats["erreurs"] += 1
                            continue

                        for fiche in fiches:
                            stats["trouvees"] += 1
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
                        log_fn(f"✓ {code} · {ville} — {len(fiches)} fiche(s)")
                        _pause(cfg.MAPS_DELAY_MS * 3)
            finally:
                contexte.close()
                navigateur.close()
        db.commit()
    finally:
        db.close()
    log_fn(f"═══ {stats['creees']} créées · {stats['fusionnees']} fusionnées · "
           f"{stats['emails']} emails ═══")
    return stats
