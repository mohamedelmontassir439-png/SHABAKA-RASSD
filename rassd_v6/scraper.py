"""
RASSD — Scraper marchespublics.gov.ma
Règle absolue: date_limite < aujourd'hui → ignorer
"""
import re, time, logging, requests, urllib3
from datetime import datetime, date
from typing import Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("rassd.scraper")

BASE = "https://marchespublics.gov.ma/bdc/entreprise/consultation"
UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]
OBJET_LABELS = [
    "objet du marché","objet de la consultation","objet de l'appel d'offres",
    "objet","intitulé","désignation","nature des travaux",
    "nature des fournitures","nature des prestations","libellé du marché",
]
DATE_LABELS = [
    "date et heure limite de remise des devis",
    "date et heure limite de remise des offres",
    "date et heure limite de dépôt des offres",
    "date limite de remise des offres","date limite de remise des devis",
    "date limite de réception des offres","date limite de réception des devis",
    "date de remise des offres","date de clôture","heure limite","date limite",
]
ACHETEUR_LABELS = [
    "maître d'ouvrage","maître d ouvrage","organisme acheteur",
    "administration","entité acheteuse","organisme",
]
NOT_OBJET = [
    "date","heure","limite","remise","réception","soumission",
    "dépôt","publication","montant","maître","organisme","budget",
]
DATE_RE  = re.compile(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})')
DATE_FMT = ["%d/%m/%Y","%Y-%m-%d","%d-%m-%Y","%d.%m.%Y"]


def _parse_date(s):
    s = str(s).strip().split()[0]
    for fmt in DATE_FMT:
        try: return datetime.strptime(s, fmt).date()
        except: pass
    return None


def is_expired(text):
    if not text: return False
    text = str(text).strip()
    if text in ("","N/A","—","-"): return False
    m = DATE_RE.search(text)
    if m:
        d = _parse_date(m.group(1))
        if d: return d < date.today()
    return False


def _cell(soup, *labels):
    for row in soup.find_all("tr"):
        cells = row.find_all(["td","th"])
        if len(cells) < 2: continue
        lbl = cells[0].get_text(strip=True).lower()
        for label in labels:
            if label.lower() in lbl:
                val = " ".join(c.get_text(strip=True) for c in cells[1:]).strip()
                if val and len(val) > 1: return val[:500]
    return ""


def _extract_date(text):
    if not text: return ""
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d.strftime("%d/%m/%Y")
    return ""


def _detect_secteur(text):
    t = text.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","génie civil","route","voirie","béton"]): return "Travaux BTP"
    if any(k in t for k in ["informatique","logiciel","système","application","réseau","serveur","cloud"]): return "IT & Télécoms"
    if any(k in t for k in ["médical","médicament","hôpital","santé","clinique","laboratoire","pharmacie"]): return "Santé & Médical"
    if any(k in t for k in ["véhicule","automobile","voiture","camion","transport","flotte"]): return "Transport & Véhicules"
    if any(k in t for k in ["nettoyage","entretien","maintenance","hygiène","gardiennage","sécurité"]): return "Services Généraux"
    if any(k in t for k in ["étude","mission","audit","conseil","expertise","ingénierie","architecture"]): return "Études & Conseil"
    if any(k in t for k in ["formation","enseignement","éducation","stage","séminaire"]): return "Formation"
    if any(k in t for k in ["restauration","hôtellerie","alimentation","repas","traiteur"]): return "Restauration"
    if any(k in t for k in ["communication","publicité","impression","média","graphique"]): return "Communication"
    if any(k in t for k in ["électricité","éclairage","énergie","photovoltaïque","solaire"]): return "Énergie"
    if any(k in t for k in ["hydraulique","eau","assainissement","traitement eau"]): return "Hydraulique"
    if any(k in t for k in ["papeterie","cartouche","toner","fournitures de bureau"]): return "Fournitures Bureau"
    if any(k in t for k in ["mobilier","meuble","aménagement intérieur"]): return "Mobilier"
    return "Autres Fournitures"


def parse_page(html, tid):
    try:
        from bs4 import BeautifulSoup as BS
        soup = BS(html, "html.parser")
        full = soup.get_text(" ", strip=True)

        # ── OBJET ──
        objet = _cell(soup, *OBJET_LABELS)
        if not objet:
            for sel in [".consultation-objet",".objet-marche","[class*='objet']","h1","h2"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(strip=True)
                    if 10 < len(t) < 600 and not any(n in t.lower() for n in NOT_OBJET):
                        objet = t; break
        if not objet: return None
        if any(x in objet.lower() for x in ["date et heure","date limite","remise des","heure limite"]):
            return None
        objet = re.sub(r'\s+', ' ', objet).strip()
        if len(objet) < 8: return None

        # ── DATE LIMITE ──
        date_lim = ""
        raw = _cell(soup, *DATE_LABELS)
        if raw: date_lim = _extract_date(raw)
        if not date_lim:
            fl = full.lower()
            for lbl in DATE_LABELS:
                idx = fl.find(lbl)
                if idx < 0: continue
                date_lim = _extract_date(full[idx:idx+150])
                if date_lim: break

        if date_lim and is_expired(date_lim): return None
        if any(w in full.lower() for w in ["annulé","annulée","sans suite","infructueux"]): return None

        acheteur = _cell(soup, *ACHETEUR_LABELS).strip()
        date_pub  = _extract_date(_cell(soup,"date de publication","date d'ouverture","publication"))
        montant   = _cell(soup,"montant estimé","montant","budget","estimation") or ""
        if not montant:
            m2 = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
            if m2: montant = m2.group(0)[:80]

        return {
            "id":               f"bdc_{tid}",
            "objet":            objet[:400],
            "acheteur":         acheteur[:200],
            "date_publication": date_pub,
            "date_limite":      date_lim,
            "montant":          montant[:80],
            "secteur":          _detect_secteur(objet + " " + full[:500]),
            "url":              f"{BASE}/show/{tid}",
            "source":           "marchespublics",
            "statut":           "actif",
            "description":      full[:3000],
            "scraped_at":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        logger.error(f"[parse #{tid}] {e}")
        return None


def run(known_ids: set, log_fn=print) -> list:
    import random
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent": random.choice(UA),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
        "Connection": "keep-alive",
    })

    max_id = 312000
    for kid in known_ids:
        if kid.startswith("bdc_"):
            try:
                n = int(kid[4:])
                if n > max_id: max_id = n
            except: pass
    if max_id < 311000: max_id = 312500

    start_id = max(max_id - 20, 310000)
    end_id   = max_id + 600
    scan_ids = [str(i) for i in range(start_id, end_id+1)
                if f"bdc_{i}" not in known_ids]

    log_fn(f"Plage: #{start_id}→#{end_id} ({len(scan_ids)} IDs)")

    results = []; errors = 0; consec_empty = 0; first_err = None

    for i, tid in enumerate(scan_ids):
        if i % 80 == 0 and i > 0:
            s.headers["User-Agent"] = random.choice(UA)
        try:
            r = s.get(f"{BASE}/show/{tid}", timeout=20)
            if r.status_code == 404:
                consec_empty += 1; continue
            if r.status_code != 200 or len(r.text) < 1500:
                consec_empty += 1; continue
            if consec_empty > 80 and len(results) == 0:
                log_fn("80 IDs vides consécutifs, arrêt"); break
            consec_empty = 0
            t = parse_page(r.text, tid)
            if not t: continue
            results.append(t)
            log_fn(f"✓ {tid} │ {t['secteur'][:18]:18} │ {t['objet'][:45]} │ ⏰{t['date_limite'] or '?'}")
            time.sleep(0.3)
        except requests.exceptions.SSLError as e:
            errors += 1
            if not first_err:
                first_err = f"SSL: {e}"
                log_fn(f"⚠ SSL error (s.verify=False normalement suffisant): {str(e)[:60]}")
            consec_empty += 1
        except requests.exceptions.ConnectionError as e:
            errors += 1
            if not first_err:
                first_err = f"Connection: {e}"
                log_fn(f"⚠ Connexion impossible: {str(e)[:80]}")
            consec_empty += 1
            if consec_empty > 5:
                log_fn("❌ Serveur inaccessible depuis Railway — vérifier l'accès réseau")
                break
        except Exception as e:
            errors += 1
            if not first_err:
                first_err = str(e)
                log_fn(f"⚠ Erreur [{tid}]: {str(e)[:80]}")
            consec_empty += 1

    if errors > 0 and first_err:
        log_fn(f"Total erreurs: {errors} | Première: {first_err[:60]}")

    log_fn(f"Terminé: {len(results)} marchés actifs | {errors} erreurs")
    return results
