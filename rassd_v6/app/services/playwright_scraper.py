"""
SOURCE — Playwright Scraper
Pour les sites nécessitant JavaScript:
  - ONCF (iframe + JS table)
  - BCP Banque Populaire
  - Crédit Agricole
  - IAM Maroc Telecom
"""
import re, hashlib, logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("atlas.playwright")

DATE_RE  = re.compile(r'(\d{2}[/\-]\d{2}[/\-]20\d{2}|\d{4}-\d{2}-\d{2})')
DATE_FMT = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]

_NOISE = ["accueil","connexion","navigation","retour","login","menu",
          "footer","copyright","contact","aide","home","voir plus",
          "lire plus","en savoir","télécharger","imprimer","partager"]

def _parse_date(s: str) -> Optional[date]:
    for fmt in DATE_FMT:
        try: return datetime.strptime(s.strip(), fmt).date()
        except: pass
    return None

def _is_expired(text: str) -> bool:
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d < date.today()
    return False

def _extract_date(text: str) -> str:
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d.strftime("%d/%m/%Y")
    return ""

def _detect_secteur(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["travaux","construction","route","béton","génie civil"]): return "Travaux BTP"
    if any(k in t for k in ["informatique","logiciel","réseau","serveur","digital","it "]): return "IT & Télécoms"
    if any(k in t for k in ["médical","santé","hôpital","laboratoire","pharmacie"]): return "Santé & Médical"
    if any(k in t for k in ["véhicule","automobile","camion","transport","bus"]): return "Transport & Véhicules"
    if any(k in t for k in ["nettoyage","entretien","maintenance","gardiennage","sécurité"]): return "Services Généraux"
    if any(k in t for k in ["étude","audit","conseil","expertise","architecture"]): return "Études & Conseil"
    if any(k in t for k in ["formation","enseignement","stage","séminaire"]): return "Formation"
    if any(k in t for k in ["électricité","énergie","solaire","générateur"]): return "Énergie"
    if any(k in t for k in ["hydraulique","eau potable","assainissement"]): return "Hydraulique"
    return "Autres"

def _make_id(source: str, ref: str, objet: str) -> str:
    key = f"{source}_{ref or objet[:40]}"
    return f"pw_{source.lower()[:4]}_{hashlib.md5(key.encode()).hexdigest()[:10]}"

def _tender(source: str, objet: str, acheteur: str = "", date_limite: str = "",
            url: str = "", ref: str = "") -> Optional[dict]:
    if not objet or len(objet) < 20: return None
    if len(objet.split()) < 3: return None
    if any(w in objet.lower() for w in _NOISE): return None
    if date_limite and _is_expired(date_limite): return None
    if any(w in objet.lower() for w in ["annulé","sans suite","infructueux"]): return None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id":               _make_id(source, ref, objet),
        "objet":            objet[:400],
        "acheteur":         (acheteur or source)[:200],
        "secteur":          _detect_secteur(objet),
        "region":           "",
        "montant":          "",
        "date_publication": date.today().strftime("%d/%m/%Y"),
        "date_limite":      date_limite,
        "description":      f"Source: {source} (Playwright)",
        "url":              url,
        "statut":           "actif",
        "scraped_at":       now,
        "updated_at":       now,
    }

# ── ONCF — JavaScript required ────────────────────────────
def scrape_oncf_pw(page, log) -> list:
    results = []
    try:
        page.goto("https://www.oncf.ma/fr/Entreprise/Fournisseurs/Appels-d-offres",
                  timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)
        # Try to get rows from table
        rows = page.query_selector_all("tr, .appel-item, .tender-row, article")
        seen = set()
        for row in rows:
            text = row.inner_text().strip()
            dl   = _extract_date(text)
            if len(text) > 25 and text[:40] not in seen:
                seen.add(text[:40])
                t = _tender("ONCF", text[:200], "ONCF", dl,
                           "https://www.oncf.ma/fr/Entreprise/Fournisseurs/Appels-d-offres")
                if t: results.append(t)
        log(f"✅ ONCF (Playwright): {len(results)} marchés")
    except Exception as e:
        log(f"⚠ ONCF PW: {e}")
    return results[:20]

# ── BCP Banque Populaire ──────────────────────────────────
def scrape_bcp_pw(page, log) -> list:
    results = []
    try:
        page.goto("https://www.groupebcp.com/fr/appels-doffres",
                  timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)
        rows = page.query_selector_all("article, .card, .appel, tr, .item")
        seen = set()
        for row in rows:
            text = row.inner_text().strip()
            dl   = _extract_date(text)
            if len(text) > 25 and ("offre" in text.lower() or "marché" in text.lower()):
                if text[:40] not in seen:
                    seen.add(text[:40])
                    t = _tender("BCP", text[:200], "Banque Populaire", dl,
                               "https://www.groupebcp.com/fr/appels-doffres")
                    if t: results.append(t)
        log(f"✅ BCP (Playwright): {len(results)} marchés")
    except Exception as e:
        log(f"⚠ BCP PW: {e}")
    return results[:15]

# ── Crédit Agricole ───────────────────────────────────────
def scrape_ca_pw(page, log) -> list:
    results = []
    try:
        page.goto("https://www.creditagricole.ma/fr/appel-offres",
                  timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)
        rows = page.query_selector_all("article, .card, tr, .appel-offre, li")
        seen = set()
        for row in rows:
            text = row.inner_text().strip()
            dl   = _extract_date(text)
            if len(text) > 25 and ("offre" in text.lower() or "marché" in text.lower()):
                if text[:40] not in seen:
                    seen.add(text[:40])
                    t = _tender("Crédit Agricole", text[:200], "Crédit Agricole du Maroc",
                               dl, "https://www.creditagricole.ma/fr/appel-offres")
                    if t: results.append(t)
        log(f"✅ Crédit Agricole (Playwright): {len(results)} marchés")
    except Exception as e:
        log(f"⚠ CA PW: {e}")
    return results[:15]

# ── IAM Maroc Telecom ─────────────────────────────────────
def scrape_iam_pw(page, log) -> list:
    results = []
    try:
        page.goto("https://www.iam.ma/groupe-maroc-telecom/appels-d-offres",
                  timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)
        rows = page.query_selector_all("tr, .appel, article, .item")
        seen = set()
        for row in rows:
            text = row.inner_text().strip()
            ref  = re.search(r'N°\s*([\d/\w]+/(?:ACHATS|MAR|DRM)\S*)', text)
            dl   = _extract_date(text)
            if len(text) > 25 and text[:40] not in seen:
                seen.add(text[:40])
                t = _tender("IAM", text[:200], "Maroc Telecom", dl,
                           "https://www.iam.ma/groupe-maroc-telecom/appels-d-offres",
                           ref.group(1) if ref else "")
                if t: results.append(t)
        log(f"✅ IAM (Playwright): {len(results)} marchés")
    except Exception as e:
        log(f"⚠ IAM PW: {e}")
    return results[:15]

# ── RUNNER PRINCIPAL ──────────────────────────────────────
def run_playwright(known_ids: set, log_fn=print) -> list:
    """Lance tous les scrapers Playwright"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log_fn("⚠ Playwright non installé — skip")
        return []

    results = []
    log_fn("─" * 48)
    log_fn("  Playwright Scraper — Sites JS")
    log_fn("─" * 48)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"]
            )
            ctx  = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="fr-MA",
            )
            page = ctx.new_page()
            page.set_extra_http_headers({"Accept-Language": "fr-MA,fr;q=0.9"})

            scrapers = [
                ("ONCF",            scrape_oncf_pw),
                ("BCP",             scrape_bcp_pw),
                ("Crédit Agricole", scrape_ca_pw),
                ("IAM",             scrape_iam_pw),
            ]

            for name, fn in scrapers:
                try:
                    items = fn(page, log_fn)
                    new   = [i for i in items if i["id"] not in known_ids]
                    results.extend(new)
                except Exception as e:
                    log_fn(f"⚠ {name}: {e}")

            browser.close()

    except Exception as e:
        log_fn(f"❌ Playwright: {e}")

    log_fn(f"✅ Playwright: {len(results)} nouveaux marchés")
    return results
