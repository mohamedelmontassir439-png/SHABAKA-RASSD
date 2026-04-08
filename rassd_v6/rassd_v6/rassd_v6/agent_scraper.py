"""
RASSD — AI Scraping Agent v2.0 — Simple & Robust
"""
import re, time, logging, ssl, random, os
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("rassd.agent")

BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"
API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

DATE_RE  = re.compile(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})')
DATE_FMT = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"]

DATE_LABELS = [
    "date et heure limite de remise des devis",
    "date et heure limite de remise des offres",
    "date limite de remise des offres","date limite de remise des devis",
    "date limite de réception des offres","date limite de réception des devis",
    "date de remise des offres","date de clôture","heure limite","date limite",
]
SKIP_H2 = ["accueil","connexion","liste des avis","résultats","invité",
           "retour à","se connecter","portail national"]


def _parse_date(s):
    s = str(s).strip().split()[0]
    for fmt in DATE_FMT:
        try: return datetime.strptime(s, fmt).date()
        except: pass
    return None


def is_expired(text):
    if not text or str(text).strip() in ("","N/A","—","-"): return False
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d < date.today()
    return False


def _extract_date(text):
    if not text: return ""
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d.strftime("%d/%m/%Y")
    return ""


def _detect_secteur(text):
    t = text.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","génie civil","route","béton"]): return "Travaux BTP"
    if any(k in t for k in ["informatique","logiciel","système","réseau","serveur","cloud"]): return "IT & Télécoms"
    if any(k in t for k in ["médical","médicament","hôpital","santé","clinique","laboratoire"]): return "Santé & Médical"
    if any(k in t for k in ["véhicule","automobile","voiture","camion","transport"]): return "Transport & Véhicules"
    if any(k in t for k in ["nettoyage","entretien","maintenance","gardiennage","sécurité"]): return "Services Généraux"
    if any(k in t for k in ["étude","mission","audit","conseil","expertise","ingénierie"]): return "Études & Conseil"
    if any(k in t for k in ["formation","enseignement","éducation","stage"]): return "Formation"
    if any(k in t for k in ["restauration","hôtellerie","alimentation","repas"]): return "Restauration"
    if any(k in t for k in ["communication","publicité","impression","média"]): return "Communication"
    if any(k in t for k in ["électricité","éclairage","énergie","photovoltaïque"]): return "Énergie"
    if any(k in t for k in ["hydraulique","eau potable","assainissement"]): return "Hydraulique"
    if any(k in t for k in ["papeterie","cartouche","toner","fournitures de bureau"]): return "Fournitures Bureau"
    if any(k in t for k in ["mobilier","meuble","aménagement"]): return "Mobilier"
    return "Autres Fournitures"


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


def _make_session():
    import requests, urllib3
    from requests.adapters import HTTPAdapter
    urllib3.disable_warnings()
    class TLSAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            ctx = ssl.create_default_context()
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl_context"] = ctx
            return super().init_poolmanager(*args, **kwargs)
    s = requests.Session()
    s.mount("https://", TLSAdapter())
    s.verify = False
    s.headers.update({
        "User-Agent": random.choice(UA),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Referer": "https://www.marchespublics.gov.ma/",
    })
    return s


def parse_page(html, tid, log_fn=None):
    """
    Parse une page marchespublics. Retourne dict ou None.
    Log chaque étape si log_fn fourni.
    """
    try:
        from bs4 import BeautifulSoup as BS
        soup = BS(html, "html.parser")
        full = soup.get_text(" ", strip=True)

        # ── OBJET ──
        objet = ""

        # Essai 1: tableau <tr>
        for labels in [["objet du marché","objet de la consultation","objet",
                        "intitulé","désignation","nature des travaux",
                        "nature des fournitures","nature des prestations"]]:
            objet = _cell(soup, *labels)
            if objet: break

        # Essai 2: <h1>/<h2>/<h3>
        if not objet:
            for tag in soup.find_all(["h1","h2","h3"])[:10]:
                t = tag.get_text(strip=True)
                if len(t) < 8 or len(t) > 500: continue
                if any(s in t.lower() for s in SKIP_H2): continue
                objet = t
                break

        # Essai 3: titre dans le texte
        if not objet:
            parts = full.split("avis d'achat")
            if len(parts) > 1:
                after = parts[-1].strip()
                # Enlever le numéro de référence
                after = re.sub(r'^\s*#?[\w/\.\-]+\s*', "", after, count=1).strip()
                # Prendre jusqu'au premier texte de nav
                for stop in ["Accueil","Se connecter","Retour","Invité","Si vous"]:
                    if stop in after:
                        after = after[:after.index(stop)].strip()
                if len(after) > 8:
                    objet = after[:200]

        if not objet:
            if log_fn: log_fn(f"  [#{tid}] ❌ Aucun objet trouvé")
            return None

        objet = re.sub(r'\s+', ' ', objet).strip()
        if objet.lower().startswith("détails de"): return None
        if len(objet) < 5: return None

        # ── DATE LIMITE ──
        date_lim = ""
        # Tableau
        raw = _cell(soup, *DATE_LABELS)
        if raw: date_lim = _extract_date(raw)
        # Texte
        if not date_lim:
            fl = full.lower()
            for lbl in DATE_LABELS:
                idx = fl.find(lbl)
                if idx >= 0:
                    date_lim = _extract_date(full[idx:idx+200])
                    if date_lim: break
        # Toutes les dates futures
        if not date_lim:
            today = date.today()
            for ds in DATE_RE.findall(full):
                d = _parse_date(ds)
                if d and d >= today:
                    date_lim = d.strftime("%d/%m/%Y")
                    break

        if date_lim and is_expired(date_lim):
            if log_fn: log_fn(f"  [#{tid}] ❌ Expiré: {date_lim}")
            return None

        if any(w in full.lower() for w in ["annulé","annulée","sans suite","infructueux"]):
            if log_fn: log_fn(f"  [#{tid}] ❌ Annulé")
            return None

        # ── AUTRES ──
        acheteur = _cell(soup, "maître d'ouvrage","maître d ouvrage",
                         "organisme acheteur","administration","organisme").strip()
        montant = _cell(soup, "montant estimé","montant","budget") or ""
        if not montant:
            m2 = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
            if m2: montant = m2.group(0)[:80]

        if log_fn:
            log_fn(f"  [#{tid}] ✅ objet={objet[:50]} dl={date_lim or '?'}") 

        return {
            "id": f"bdc_{tid}",
            "objet": objet[:400],
            "acheteur": acheteur[:200],
            "date_publication": _extract_date(_cell(soup,"date de publication","publication")),
            "date_limite": date_lim,
            "montant": montant[:80],
            "secteur": _detect_secteur(objet + " " + full[:400]),
            "url": f"{BASE}/show/{tid}",
            "source": "marchespublics",
            "statut": "actif",
            "description": full[:3000],
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        if log_fn: log_fn(f"  [#{tid}] ❌ Exception: {e}")
        logger.error(f"[parse #{tid}] {e}")
        return None


def run(known_ids: set, log_fn=print) -> list:
    """Point d'entrée principal — compatible main.py"""
    import urllib3
    urllib3.disable_warnings()

    # Calculer plage
    max_id = 312000
    for kid in known_ids:
        if kid.startswith("bdc_"):
            try:
                n = int(kid[4:])
                if n > max_id: max_id = n
            except: pass
    if max_id <= 312000:
        # DB vide — scanner les IDs récents (avril 2026 ≈ 313000+)
        start_id, end_id = 313000, 314000
    else:
        start_id = max(max_id - 20, 310000)
        end_id   = max_id + 600

    scan_ids = [str(i) for i in range(start_id, end_id+1)
                if f"bdc_{i}" not in known_ids]

    log_fn(f"╔══════════════════════════════════════╗")
    log_fn(f"║  AI Scraping Agent v2.0              ║")
    log_fn(f"║  Plage: #{start_id} → #{end_id}    ║")
    log_fn(f"╚══════════════════════════════════════╝")

    s = _make_session()
    results = []; errors = 0; consec_empty = 0
    debug_done = False

    for i, tid in enumerate(scan_ids):
        if i % 100 == 0 and i > 0:
            s.headers["User-Agent"] = random.choice(UA)

        try:
            r = s.get(f"{BASE}/show/{tid}", timeout=20)
            if r.status_code == 404:
                consec_empty += 1; continue
            if r.status_code != 200 or len(r.text) < 1500:
                consec_empty += 1; continue

            consec_empty = 0

            # Debug: montrer structure première page valide
            if not debug_done:
                debug_done = True
                from bs4 import BeautifulSoup as _BS
                _soup = _BS(r.text, "html.parser")
                _h2s = [h.get_text(strip=True)[:60] for h in _soup.find_all("h2")[:6]]
                _txt  = _soup.get_text(" ", strip=True)[:400]
                log_fn(f"[DEBUG #{tid}] h2={_h2s}")
                log_fn(f"[DEBUG #{tid}] texte={_txt[:300]}")

            # Parser avec log pour les 5 premiers
            _log = log_fn if len(results) < 5 and errors == 0 else None
            tender = parse_page(r.text, tid, log_fn=_log)

            if not tender:
                if not debug_done or len(results) == 0 and errors < 3:
                    pass  # already logged in parse_page
                continue

            results.append(tender)
            log_fn(f"✓ #{tid} │ {tender['secteur'][:16]:16} │ {tender['objet'][:45]} │ ⏰{tender['date_limite'] or '?'}")
            time.sleep(0.3)

        except Exception as e:
            errors += 1
            if errors <= 3:
                log_fn(f"⚠ #{tid}: {str(e)[:60]}")
            consec_empty += 1
            if consec_empty > 15 and errors > 10:
                log_fn("❌ Trop d'erreurs, arrêt")
                break

    log_fn(f"═══ Terminé: {len(results)} marchés | {errors} erreurs ═══")
    return results
