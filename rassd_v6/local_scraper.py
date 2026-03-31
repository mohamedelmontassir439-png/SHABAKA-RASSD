#!/usr/bin/env python3
"""
Modern Business — Scraper Local v6.0
Analyse la structure de chaque site et extrait UNIQUEMENT les nouvelles صفقات

Usage:
  python local_scraper.py           # scrape normal
  python local_scraper.py --debug   # voir structure des sites
  python local_scraper.py --test    # tester le moteur de dates

pip install requests beautifulsoup4 lxml schedule
"""

import sys, requests, re, time, hashlib, schedule, warnings, json
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup as BS
from urllib.parse import urljoin, urlparse

warnings.filterwarnings("ignore")

RAILWAY  = "https://web-production-b4ae4.up.railway.app"
PWD      = "rassd2026"
EVERY_H  = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.6261.112 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
    "Connection": "keep-alive",
}

TODAY = date.today()

# ══════════════════════════════════════════════════
# DATE ENGINE — extrait la date limite depuis
# n'importe quel texte ou structure HTML
# ══════════════════════════════════════════════════

DATE_PATTERNS = [
    re.compile(r'(\d{2}/\d{2}/\d{4})'),   # DD/MM/YYYY
    re.compile(r'(\d{4}-\d{2}-\d{2})'),   # YYYY-MM-DD
    re.compile(r'(\d{2}-\d{2}-\d{4})'),   # DD-MM-YYYY
    re.compile(r'(\d{2}\.\d{2}\.\d{4})'), # DD.MM.YYYY
]

DATE_FMTS = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"]

DEADLINE_LABELS = [
    # Français
    "date limite", "date de clôture", "date de remise",
    "date de dépôt", "date de réception",
    "réception des offres", "réception des devis",
    "remise des offres", "remise des plis",
    "dépôt des offres", "soumission",
    "avant le", "au plus tard", "clôture",
    "heure limite", "échéance",
    # Anglais
    "deadline", "closing date", "submission date",
    # Arabe
    "آخر أجل", "الأجل", "تاريخ الإيداع",
]

def parse_date(s):
    if not s: return None
    s = str(s).strip()
    for fmt in DATE_FMTS:
        try: return datetime.strptime(s, fmt).date()
        except: pass
    # Format court DD/MM/YY
    m = re.match(r'(\d{2})/(\d{2})/(\d{2})$', s)
    if m:
        d, mo, y = m.groups()
        try: return datetime.strptime(f"{d}/{mo}/20{y}", "%d/%m/%Y").date()
        except: pass
    return None

def find_all_dates(text):
    """Trouve toutes les dates dans un texte avec leur position"""
    text = str(text)
    results = []
    for pat, fmt in zip(DATE_PATTERNS, DATE_FMTS):
        for m in pat.finditer(text):
            d = parse_date(m.group(1))
            if d and date(2025, 1, 1) <= d <= date(2028, 12, 31):
                results.append((m.start(), d, m.group(1)))
    return sorted(set((p, d, s) for p, d, s in results), key=lambda x: x[0])

def extract_deadline(text):
    """
    Extrait la date limite depuis un texte.
    Priorité: mot-clé deadline → date future la plus proche → dernière date
    """
    if not text: return None
    text = str(text)
    tl   = text.lower()
    all_dates = find_all_dates(text)
    if not all_dates: return None

    # Priorité 1: cherche après un label deadline
    for label in DEADLINE_LABELS:
        idx = tl.find(label)
        if idx < 0: continue
        nearby = [(p, d, s) for p, d, s in all_dates
                  if idx <= p <= idx + 200]
        if nearby:
            return min(nearby, key=lambda x: x[0])[1]

    # Priorité 2: date future la plus proche d'aujourd'hui
    future = [(p, d, s) for p, d, s in all_dates if d >= TODAY]
    if future:
        return min(future, key=lambda x: abs((x[1] - TODAY).days))[1]

    # Priorité 3: dernière date
    return all_dates[-1][1]

def is_valid_tender(deadline_text):
    """
    True = garder la صفقة
    False = ignorer (date passée)
    Si aucune date → True (on garde par défaut)
    """
    if not deadline_text: return True
    text = str(deadline_text).strip()
    if text in ("", "N/A", "—", "-", "null", "Non précisée"): return True
    dl = extract_deadline(text)
    if dl is None: return True       # Pas de date parseable → garder
    return dl >= TODAY               # ✅ future / aujourd'hui → garder

def fmt_dl(text):
    dl = extract_deadline(str(text)) if text else None
    return dl.strftime("%d/%m/%Y") if dl else ""


# ══════════════════════════════════════════════════
# DÉTECTION APPEL D'OFFRES
# ══════════════════════════════════════════════════

AO_KEYWORDS = [
    "appel d'offres", "appel d offres", "appel d'offre",
    "appel à la concurrence", "appel de candidatures",
    "marché public", "marchés publics",
    "cahier des charges", "cahier de charges",
    "avis d'appel", "dossier d'appel",
    "consultation", "soumission d'offres",
    "fourniture de ", "acquisition de ", "travaux de ",
    "prestation de service", "mission d'", "étude de ",
    "ao n°", "ao n ", "aac ", "ami ",
    "appel à projets", "appel à manifestation",
]

NOT_AO = [
    "offre d'emploi", "offres d'emploi", "recrutement",
    "offre de stage", "offre de bourse",
    "marchés financiers", "marchés boursiers",
    "marchés de capitaux", "cours des marchés",
    "offre commerciale", "promotion ",
]

def is_ao(title, extra=""):
    text = (str(title) + " " + str(extra)).lower()
    for n in NOT_AO:
        if n in text: return False
    for k in AO_KEYWORDS:
        if k in text: return True
    return False


# ══════════════════════════════════════════════════
# HTTP
# ══════════════════════════════════════════════════

def new_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False
    return s

def fetch(s, url, timeout=20):
    try:
        r = s.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200: return r
        if r.status_code != 200:
            print(f"    HTTP {r.status_code}: {url[:50]}")
    except requests.exceptions.ConnectionError:
        print(f"    ✗ Connexion refusée: {url[:50]}")
    except requests.exceptions.Timeout:
        print(f"    ✗ Timeout: {url[:50]}")
    except Exception as e:
        print(f"    ✗ {type(e).__name__}: {url[:50]}")
    return None

def mkid(src, title, url=""):
    h = hashlib.md5(f"{title[:80]}{url[-20:]}".encode()).hexdigest()[:10]
    return f"{src}_{h}"

def build(src, url, title, dl="", acheteur=""):
    return {
        "id":          mkid(src, title, url),
        "objet":       title[:300].strip(),
        "source":      src,
        "source_url":  url,
        "acheteur":    acheteur[:200],
        "region":      "Maroc",
        "date_limite": fmt_dl(dl) if dl else "",
        "statut":      "actif",
        "description": "",
    }


# ══════════════════════════════════════════════════
# SCRAPERS — adaptés à la structure réelle de chaque site
# ══════════════════════════════════════════════════

def scrape_leconomiste():
    """
    L'Économiste structure:
    - URL: /appels-offres (page Drupal)
    - Articles: div.views-row ou div.node
    - Titre: h3.node-title ou h2 > a
    - Date: dans le corps de l'article
    """
    s = new_session(); results = []; seen = set(); skip = 0

    for url in ["https://www.leconomiste.com/appels-offres",
                "https://www.leconomiste.com/appels-offres?page=1",
                "https://www.leconomiste.com/appels-offres?page=2"]:
        r = fetch(s, url)
        if not r: continue
        soup = BS(r.text, "html.parser")

        # Structure Drupal: div.views-row contient chaque article
        rows = soup.find_all("div", class_=re.compile(r'views-row|node-teaser|view-row', re.I))
        if not rows:
            # Fallback: chercher tous les liens vers articles
            rows = soup.find_all(["article", "div"],
                                  class_=re.compile(r'node|article|post', re.I))

        for row in rows:
            a = row.find("a", href=True)
            if not a: continue
            href = urljoin("https://www.leconomiste.com", a["href"])
            if href in seen or "leconomiste.com" not in href: continue
            seen.add(href)

            # Titre
            h = row.find(["h2","h3","h4"]) or a
            title = h.get_text(strip=True)
            if len(title) < 10: continue
            if not is_ao(title, row.get_text()): continue

            # Date limite depuis le listing
            row_text = row.get_text(" ", strip=True)
            if not is_valid_tender(row_text): skip += 1; continue

            results.append(build("leconomiste", href, title, row_text))
            time.sleep(0.3)

    print(f"  [leconomiste]   ✅ {len(results)} | ❌ {skip} expirés")
    return results


def scrape_lematin():
    """
    Le Matin Annonces structure:
    - Catégories: /annonces/appels-offres/, /annonces/marches-publics/
    - Liens: <a href="/annonce/SLUG">Titre</a>
    - Page annonce: h1 = titre, corps = texte avec date
    """
    s = new_session(); results = []; seen = set(); skip = 0
    base = "https://annonces.lematin.ma"

    categories = [
        f"{base}/annonces/appels-offres/",
        f"{base}/annonces/marches-publics/",
        f"{base}/annonces/appels-a-la-concurrence/",
        f"{base}/annonces/avis-d-appel-d-offres/",
        f"{base}/annonces/avis-de-consultation/",
    ]

    for cat_url in categories:
        r = fetch(s, cat_url)
        if not r: continue
        soup = BS(r.text, "html.parser")

        # Le Matin: liens /annonce/ ou /annonces/
        links = soup.find_all("a", href=re.compile(r'/annonce', re.I))

        # Si pas trouvé, chercher tous liens internes significatifs
        if not links:
            links = [a for a in soup.find_all("a", href=True)
                     if base in urljoin(base, a["href"])
                     and len(a.get_text(strip=True)) > 20]

        for a in links[:50]:
            href = urljoin(base, a["href"])
            if href in seen or base not in href: continue
            seen.add(href)

            # Fetch page détail
            r2 = fetch(s, href, 15)
            if not r2: continue
            soup2 = BS(r2.text, "html.parser")

            # Titre depuis la page
            h1 = soup2.find("h1") or soup2.find("h2")
            title = h1.get_text(strip=True) if h1 else a.get_text(strip=True)
            if len(title) < 10: continue
            if not is_ao(title, r2.text[:300]): continue

            # Date limite depuis la page complète
            page_text = r2.text[:3000]
            if not is_valid_tender(page_text): skip += 1; continue

            results.append(build("lematin", href, title, page_text))
            time.sleep(0.8)

    print(f"  [lematin]       ✅ {len(results)} | ❌ {skip} expirés")
    return results


def scrape_flasheconomie():
    """
    Flash Économie structure (WordPress):
    - Catégories: /category/appels-offres/
    - Articles: <article> avec <h2><a href>Titre</a></h2>
    - Date: dans article ou page détail
    """
    s = new_session(); results = []; seen = set(); skip = 0

    cats = [
        "https://flasheconomie.com/category/appels-offres/",
        "https://flasheconomie.com/category/consulter-les-annonces-legales/",
        "https://flasheconomie.com/category/marches-publics/",
    ]

    for cat_url in cats:
        r = fetch(s, cat_url)
        if not r: continue
        soup = BS(r.text, "html.parser")

        # WordPress: chaque post est dans <article>
        for art in soup.find_all("article"):
            a = art.find("a", href=True)
            if not a: continue
            href = a["href"]
            if href in seen: continue
            seen.add(href)

            h = art.find(["h2","h3","h1"])
            title = h.get_text(strip=True) if h else a.get_text(strip=True)
            if len(title) < 10: continue
            ctx = art.get_text(" ", strip=True)
            if not is_ao(title, ctx): continue

            # Fetch page pour date
            r2 = fetch(s, href, 12)
            page_text = r2.text[:3000] if r2 else ctx
            if not is_valid_tender(page_text): skip += 1; continue

            results.append(build("flasheconomie", href, title, page_text))
            time.sleep(0.6)

    print(f"  [flasheconomie] ✅ {len(results)} | ❌ {skip} expirés")
    return results


def scrape_marocao():
    """
    marocao.com structure:
    - Section publique: /appels-offres (liste sans login)
    - Liens vers détails d'annonces
    """
    s = new_session(); results = []; seen = set(); skip = 0
    base = "https://marocao.com"

    r = fetch(s, f"{base}/appels-offres")
    if r:
        soup = BS(r.text, "html.parser")
        # Chercher les liens qui ressemblent à des annonces
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            if len(title) < 20: continue
            if not is_ao(title): continue
            href = urljoin(base, a["href"])
            if href in seen: continue
            seen.add(href)
            # Fetch détail
            r2 = fetch(s, href, 12)
            page_text = r2.text[:3000] if r2 else ""
            if page_text and not is_valid_tender(page_text):
                skip += 1; continue
            results.append(build("marocao", href, title, page_text))
            time.sleep(0.8)

    print(f"  [marocao]       ✅ {len(results)} | ❌ {skip} expirés")
    return results


# ══════════════════════════════════════════════════
# PUSH
# ══════════════════════════════════════════════════

def push(tenders):
    if not tenders: print("  → Rien à envoyer"); return 0
    seen = set()
    unique = [t for t in tenders
              if t["id"] not in seen
              and not seen.add(t["id"])
              and len(t["objet"]) > 10]
    try:
        r = requests.post(f"{RAILWAY}/api/v1/ingest",
                          json={"tenders": unique, "pwd": PWD}, timeout=30)
        if r.status_code == 200:
            d = r.json()
            print(f"  ✅ Railway: {d.get('saved',0)}/{len(unique)} sauvegardés")
            return d.get("saved", 0)
        print(f"  ❌ HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"  ❌ Push: {e}")
    return 0


# ══════════════════════════════════════════════════
# DEBUG: analyser la structure réelle des sites
# ══════════════════════════════════════════════════

def mode_debug():
    print(f"\n{'═'*56}")
    print(f"  DEBUG — Analyse structure des sites ({TODAY})")
    print(f"{'═'*56}\n")
    s = new_session()

    sites = [
        ("leconomiste", "https://www.leconomiste.com/appels-offres"),
        ("lematin",     "https://annonces.lematin.ma/annonces/appels-offres/"),
        ("flash",       "https://flasheconomie.com/category/appels-offres/"),
        ("marocao",     "https://marocao.com/appels-offres"),
    ]

    for name, url in sites:
        print(f"── {name} ──")
        r = fetch(s, url)
        if not r:
            print(f"  ❌ Pas de réponse\n"); continue

        soup = BS(r.text, "html.parser")

        # Analyser la structure
        articles = soup.find_all("article")
        divs_node= soup.find_all("div", class_=re.compile(r'node|views-row|view-row|post', re.I))
        all_links= soup.find_all("a", href=True)
        ao_links = [a for a in all_links if is_ao(a.get_text(strip=True))]
        dates_in_page = find_all_dates(r.text)

        print(f"  HTTP 200 ✅")
        print(f"  <article>: {len(articles)}")
        print(f"  div.node/views-row: {len(divs_node)}")
        print(f"  Liens totaux: {len(all_links)}")
        print(f"  Liens AO: {len(ao_links)}")
        print(f"  Dates dans la page: {[str(d) for _,d,_ in dates_in_page[:5]]}")
        if ao_links:
            print(f"  Top 5 AO links:")
            for a in ao_links[:5]:
                print(f"    → '{a.get_text(strip=True)[:60]}'")
                print(f"       {a['href'][:60]}")
        print()

    sys.exit(0)


# ══════════════════════════════════════════════════
# TEST: vérifier le moteur de dates
# ══════════════════════════════════════════════════

def mode_test():
    print(f"\n{'═'*56}")
    print(f"  TEST DATE ENGINE — Aujourd'hui: {TODAY}")
    print(f"{'═'*56}\n")

    tests = [
        # (texte, attendu_valide)
        ("Date limite de réception des devis05/03/2026 12:00", False),
        ("Date limite de réception des devis15/04/2026 12:00", True),
        ("Remise des offres avant le 25/04/2026 à 10h00",      True),
        ("Date limite : 2026-02-28",                            False),
        ("Date de clôture: 2026-05-01",                         True),
        ("Publication: 01/03/2026. Limite: 20/04/2026",         True),
        ("Texte sans aucune date",                               True),
        ("",                                                     True),
        ("N/A",                                                  True),
    ]

    ok = 0
    for text, expect in tests:
        dl  = extract_deadline(text)
        got = is_valid_tender(text)
        ico = "✅" if got == expect else "❌"
        if got == expect: ok += 1
        print(f"  {ico} '{text[:55]:55}' dl={str(dl):12} valid={got}")

    print(f"\n  Résultat: {ok}/{len(tests)} tests passés\n")
    sys.exit(0)


# ══════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════

def run():
    global TODAY
    TODAY = date.today()
    print(f"\n{'═'*56}")
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] Scraping — filtre: >= {TODAY}")
    print(f"{'═'*56}")

    all_results = []
    for fn in [scrape_leconomiste, scrape_lematin,
               scrape_flasheconomie, scrape_marocao]:
        try:
            all_results.extend(fn())
        except Exception as e:
            print(f"  ✗ {fn.__name__}: {e}")

    print(f"\n  Total valides: {len(all_results)} AO")
    push(all_results)
    print(f"  Prochain run dans {EVERY_H}h\n")


if __name__ == "__main__":
    if "--debug" in sys.argv: mode_debug()
    if "--test"  in sys.argv: mode_test()

    print("═" * 56)
    print("  Modern Business — Scraper Local v6.0")
    print(f"  Règle absolue: date_limite >= {date.today()}")
    print(f"  Railway: {RAILWAY}")
    print("═" * 56 + "\n")

    run()
    schedule.every(EVERY_H).hours.do(run)
    print("En cours... (Ctrl+C pour arrêter)")
    while True:
        schedule.run_pending()
        time.sleep(60)
