"""
ATLAS PRO — Global-Marches.com Scraper
=======================================
Scrape des appels d'offres PRIVÉS via login membre.

⚙️  Variables Railway à configurer:
    GM_USERNAME = votre email global-marches.com
    GM_PASSWORD = votre mot de passe

Usage:
    from app.services.global_marches import scrape_global_marches_auth
    tenders = scrape_global_marches_auth(known_ids, log_fn)
"""
import os, re, hashlib, logging, time
from datetime import datetime, date
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("atlas.global_marches")

# ── Credentials (Railway Variables) ───────────────────────
GM_BASE     = "https://global-marches.com"
GM_USER     = os.getenv("GM_USERNAME", "")
GM_PASS     = os.getenv("GM_PASSWORD", "")

# ── Date parsing ──────────────────────────────────────────
DATE_RE   = re.compile(r'(\d{2}[\/\-]\d{2}[\/\-]\d{4}|\d{4}-\d{2}-\d{2})')
DATE_FMTS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]

def _parse_date(s: str) -> Optional[date]:
    s = s.strip().split()[0]
    for fmt in DATE_FMTS:
        try: return datetime.strptime(s, fmt).date()
        except: pass
    return None

def _extract_date(text: str) -> str:
    if not text: return ""
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d.strftime("%d/%m/%Y")
    return ""

def _is_expired(text: str) -> bool:
    d = _extract_date(text)
    if not d: return False
    parsed = _parse_date(d)
    return bool(parsed and parsed < date.today())

def _make_id(ref: str, objet: str) -> str:
    raw = f"gm_{ref}_{objet[:40]}"
    return "gm_" + hashlib.md5(raw.encode()).hexdigest()[:12]

# ── Session ───────────────────────────────────────────────
def _create_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer":         GM_BASE + "/",
    })
    s.verify = False
    return s

# ── Login ─────────────────────────────────────────────────
def _login(s: requests.Session, log=print) -> bool:
    """Se connecte à global-marches.com avec les credentials."""
    if not GM_USER or not GM_PASS:
        log("⚠ GM_USERNAME ou GM_PASSWORD non défini dans Railway Variables")
        return False
    try:
        # Step 1: GET homepage to get cookies + CSRF token
        r = s.get(GM_BASE + "/", timeout=20)
        if r.status_code != 200:
            log(f"⚠ Global-Marches homepage: HTTP {r.status_code}")
            return False

        soup = BeautifulSoup(r.text, "lxml")
        time.sleep(0.5)

        # Step 2: Find login form
        # Try multiple possible login form locations
        login_endpoints = [
            "/login",
            "/membre/connexion",
            "/connexion",
            "/espace-membre",
            "/index.php/login",
        ]
        
        login_url = None
        csrf_token = None
        
        # Check if login form is on homepage
        forms = soup.find_all("form")
        for form in forms:
            inputs = form.find_all("input")
            input_names = [i.get("name","").lower() for i in inputs]
            if any(k in " ".join(input_names) for k in ["pass","password","mdp","mot_de_passe","pwd"]):
                action = form.get("action","")
                login_url = (GM_BASE + action) if action.startswith("/") else (action or GM_BASE + "/")
                # Get CSRF if present
                for inp in inputs:
                    if inp.get("type") == "hidden":
                        csrf_token = inp.get("value","")
                break

        # If not found on homepage, try dedicated login pages
        if not login_url:
            for endpoint in login_endpoints:
                try:
                    r2 = s.get(GM_BASE + endpoint, timeout=10)
                    if r2.status_code == 200:
                        soup2 = BeautifulSoup(r2.text, "lxml")
                        form = soup2.find("form")
                        if form:
                            action = form.get("action","")
                            login_url = (GM_BASE + action) if action.startswith("/") else (GM_BASE + endpoint)
                            for inp in form.find_all("input"):
                                if inp.get("type") == "hidden":
                                    csrf_token = inp.get("value","")
                            break
                except: continue

        if not login_url:
            log("⚠ Global-Marches: formulaire de login introuvable")
            return False

        # Step 3: POST login
        payload = {
            "email":       GM_USER,
            "login":       GM_USER,
            "username":    GM_USER,
            "password":    GM_PASS,
            "pass":        GM_PASS,
            "mdp":         GM_PASS,
            "mot_de_passe":GM_PASS,
            "remember":    "1",
            "submit":      "Connexion",
        }
        if csrf_token:
            payload["_token"] = csrf_token
            payload["csrf_token"] = csrf_token

        headers_post = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": login_url,
            "Origin":  GM_BASE,
        }
        r3 = s.post(login_url, data=payload, headers=headers_post, timeout=20, allow_redirects=True)

        # Check if logged in
        if r3.status_code in (200, 302):
            content = r3.text.lower()
            # Success indicators
            if any(k in content for k in ["déconnexion","logout","mon compte","espace membre","tableau de bord","bienvenue"]):
                log("✅ Global-Marches: connecté!")
                return True
            # Check cookies
            if any("session" in c.lower() or "auth" in c.lower() or "member" in c.lower() 
                   for c in s.cookies.keys()):
                log("✅ Global-Marches: session cookie trouvé")
                return True
            # Check redirect to member area
            if "/membre" in r3.url or "/dashboard" in r3.url or "/accueil" in r3.url:
                log("✅ Global-Marches: redirigé vers espace membre")
                return True

        log(f"⚠ Global-Marches: login échoué (HTTP {r3.status_code})")
        log(f"  URL finale: {r3.url}")
        return False

    except Exception as e:
        log(f"❌ Global-Marches login error: {e}")
        logger.error(f"[GM login] {e}", exc_info=True)
        return False

# ── Parse a tender row ────────────────────────────────────
def _parse_row(el, source_type: str, base_url: str) -> Optional[dict]:
    """Extrait un marché depuis un élément HTML."""
    text = el.get_text(" ", strip=True)
    if len(text) < 15: return None

    # Skip navigation/menu items
    skip = ["accueil","connexion","contact","navigation","menu","footer","copyright","abonnement"]
    if any(s in text.lower() for s in skip): return None

    # Find link
    link = el.find("a") if el.name != "a" else el
    href = ""
    if link:
        href = link.get("href","")
        if href and not href.startswith("http"):
            href = base_url + href if href.startswith("/") else base_url + "/" + href

    # Find date limite
    date_limite = ""
    date_m = DATE_RE.search(text)
    if date_m:
        d = _parse_date(date_m.group(1))
        if d and d >= date.today():
            date_limite = d.strftime("%d/%m/%Y")
        elif d and d < date.today():
            return None  # Expired

    # Extract organisme (usually in a separate element)
    acheteur = ""
    spans = el.find_all(["span","td","div","p"])
    for sp in spans:
        t = sp.get_text(strip=True)
        if 10 < len(t) < 100 and t != text[:len(t)]:
            acheteur = t[:80]; break

    # Objet = main title text
    title_el = el.find(["h2","h3","h4","strong","b","a"])
    objet = title_el.get_text(strip=True) if title_el else text[:200]

    if len(objet) < 10: return None

    # Make ID
    tender_id = _make_id(href or objet, objet)

    return {
        "id":               tender_id,
        "objet":            objet[:300],
        "acheteur":         acheteur[:150],
        "secteur":          "Privé — Global-Marchés",
        "region":           "",
        "montant":          "",
        "date_publication": datetime.now().strftime("%d/%m/%Y"),
        "date_limite":      date_limite,
        "description":      text[:500],
        "url":              href or f"{GM_BASE}/aoprive",
        "statut":           "actif",
        "scraped_at":       datetime.now().isoformat(),
        "source":           f"Global-Marchés ({source_type})",
    }

# ── Scrape a section ─────────────────────────────────────
def _scrape_section(s: requests.Session, path: str, section_name: str,
                    log=print) -> list:
    """Scrape une section après login."""
    results = []
    page = 1
    seen = set()

    while page <= 5:  # Max 5 pages
        url = f"{GM_BASE}{path}" + (f"/{page}" if page > 1 else "")
        try:
            r = s.get(url, timeout=20)
            if r.status_code != 200:
                if r.status_code == 403:
                    log(f"⚠ {section_name} page {page}: accès refusé (login requis?)")
                break

            soup = BeautifulSoup(r.text, "lxml")

            # Multiple selector strategies for different page layouts
            items = (
                soup.select("table.table tr") or
                soup.select(".tender-item, .ao-item, .offre-item, .annonce-item") or
                soup.select("article, .card, .item") or
                soup.select("tr[class], li.item, div.row") or
                soup.find_all("tr")[1:] or  # Skip header row
                []
            )

            new_on_page = 0
            for item in items:
                t = _parse_row(item, section_name, GM_BASE)
                if t and t["id"] not in seen:
                    seen.add(t["id"])
                    results.append(t)
                    new_on_page += 1

            log(f"  {section_name} page {page}: {new_on_page} trouvés")

            # Stop if no more results
            if new_on_page == 0: break

            # Check for next page
            next_link = soup.find("a", string=re.compile(r'suivant|next|→|>>', re.I))
            if not next_link: break

            page += 1
            time.sleep(1.2)

        except Exception as e:
            log(f"⚠ {section_name} page {page}: {e}")
            break

    return results

# ── MAIN FUNCTION ─────────────────────────────────────────
def scrape_global_marches_auth(known_ids: set, log=print) -> list:
    """
    Point d'entrée principal.
    Scrape les 4 sections de global-marches.com après authentification.
    
    Sections:
      - /aopublic    — Appels d'offres publics
      - /aoprive     — Appels d'offres PRIVÉS ← valeur principale
      - /aoprevisionnel — Prévisionnels
      - /aoresultat  — Résultats adjudications
    """
    if not GM_USER or not GM_PASS:
        log("⚠ Global-Marches: GM_USERNAME/GM_PASSWORD non configurés — skip")
        return []

    s = _create_session()
    found = []

    log("─" * 48)
    log("  Global-Marches.com — Connexion...")

    if not _login(s, log):
        log("⚠ Global-Marches: impossible de se connecter")
        return []

    time.sleep(1)

    sections = [
        ("/aoprive",        "Privé"),
        ("/aopublic",       "Public"),
        ("/aoprevisionnel", "Prévisionnel"),
        ("/aoresultat",     "Résultats"),
    ]

    for path, name in sections:
        try:
            items = _scrape_section(s, path, name, log)
            new = [t for t in items if t["id"] not in known_ids]
            found.extend(new)
            log(f"  ✅ {name}: {len(new)} nouveaux / {len(items)} total")
        except Exception as e:
            log(f"  ⚠ {name}: {e}")
        time.sleep(1)

    log(f"  Global-Marches total: {len(found)} nouveaux marchés")
    return found


# ── PUBLIC fallback (sans login) ─────────────────────────
def scrape_global_marches_public(known_ids: set, log=print) -> list:
    """
    Version sans login — scrape uniquement les aperçus publics.
    Retourne les titres visibles sans compte (limité).
    """
    s = _create_session()
    found = []

    try:
        r = s.get(GM_BASE + "/", timeout=20)
        if r.status_code != 200: return []

        soup = BeautifulSoup(r.text, "lxml")

        # Recent tenders sometimes shown on homepage
        for sel in ["a[href*='/ao/']", "a[href*='/annonce/']", "a[href*='/offre/']",
                    ".recent-tenders li", ".last-tenders li", ".home-tenders li"]:
            items = soup.select(sel)
            for item in items:
                t = _parse_row(item, "Public Preview", GM_BASE)
                if t and t["id"] not in known_ids:
                    found.append(t)

        # Latest news on homepage that mention appels d'offres
        for a in soup.find_all("a", href=True):
            href = a.get("href","")
            text = a.get_text(strip=True)
            if (len(text) > 20 and
                any(k in text.lower() for k in ["appel","offre","marché","consultation"]) and
                any(k in href for k in ["/ao","/offre","/annonce","/marche"])):
                t = _parse_row(a, "Aperçu public", GM_BASE)
                if t and t["id"] not in known_ids:
                    found.append(t)

        log(f"  Global-Marches (public): {len(found)} aperçus")
    except Exception as e:
        log(f"  ⚠ Global-Marches public: {e}")

    return found[:20]  # Limit public preview


# ── TEST local ────────────────────────────────────────────
if __name__ == "__main__":
    import os
    # Set test credentials
    os.environ["GM_USERNAME"] = "votre_email@test.ma"
    os.environ["GM_PASSWORD"] = "votre_mot_de_passe"
    
    results = scrape_global_marches_auth(set(), print)
    print(f"\nTotal: {len(results)}")
    for r in results[:5]:
        print(f"  [{r['source']}] {r['objet'][:80]}")
        print(f"    Acheteur: {r['acheteur']}")
        print(f"    Deadline: {r['date_limite']}")
        print(f"    URL: {r['url']}")
        print()
