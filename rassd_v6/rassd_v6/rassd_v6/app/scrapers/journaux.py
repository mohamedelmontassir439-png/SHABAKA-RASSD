"""
Modern Business — Scrapers journaux légaux marocains
Sources: leconomiste, lematin, flasheconomie

Utiliser depuis IP Maroc ou via playwright_scraper.py
"""
import re, time, hashlib, requests
from bs4 import BeautifulSoup as BS
from urllib.parse import urljoin
from app.core.dates import is_expired, format_deadline, extract_deadline

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0"

AO_REQUIRED = [
    "appel d'offres", "appel d offres", "appel d'offre",
    "appel à la concurrence", "marché public",
    "cahier des charges", "avis d'appel", "consultation",
    "fourniture de ", "acquisition de ", "travaux de ",
    "ao n°", "ao ", "aac ", "ami ",
]
AO_EXCLUDED = [
    "offre d'emploi", "offres d'emploi", "recrutement",
    "marchés financiers", "marchés boursiers", "marchés de capitaux",
    "offre commerciale", "offre de stage",
]


def _sess():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"})
    s.verify = False
    return s


def _get(s, url, timeout=20):
    try:
        r = s.get(url, timeout=timeout, allow_redirects=True)
        return r if r.status_code == 200 else None
    except: return None


def _is_ao(title, ctx=""):
    text = (str(title) + " " + str(ctx)).lower()
    if any(e in text for e in AO_EXCLUDED): return False
    return any(k in text for k in AO_REQUIRED)


def _mkid(src, title, url=""):
    return f"{src}_" + hashlib.md5(f"{title[:80]}{url[-20:]}".encode()).hexdigest()[:10]


def _build(src, url, title, dl_text=""):
    return {
        "id":          _mkid(src, title, url),
        "objet":       title[:300].strip(),
        "source":      src,
        "source_url":  url,
        "acheteur":    "",
        "region":      "Maroc",
        "date_limite": format_deadline(dl_text),
        "statut":      "actif",
        "description": "",
    }


def scrape_leconomiste(log_fn=print) -> list:
    s = _sess(); results = []; seen = set(); skip = 0
    for url in [
        "https://www.leconomiste.com/appels-offres",
        "https://www.leconomiste.com/appels-offres?page=1",
        "https://www.leconomiste.com/appels-offres?page=2",
    ]:
        r = _get(s, url)
        if not r: continue
        soup = BS(r.text, "html.parser")
        for el in soup.find_all("div", class_=re.compile(r'views-row|node-teaser', re.I)):
            a = el.find("a", href=True)
            if not a: continue
            href = urljoin("https://www.leconomiste.com", a["href"])
            if href in seen or "leconomiste" not in href: continue
            seen.add(href)
            title = (el.find(["h2","h3","h4"]) or a).get_text(strip=True)
            ctx   = el.get_text()
            if not _is_ao(title, ctx): continue
            if is_expired(ctx): skip += 1; continue
            results.append(_build("leconomiste", href, title, ctx))
            time.sleep(0.3)
    log_fn(f"leconomiste: {len(results)} valides, {skip} expirés")
    return results


def scrape_lematin(log_fn=print) -> list:
    s = _sess(); results = []; seen = set(); skip = 0
    base = "https://annonces.lematin.ma"
    for cat in ["/annonces/appels-offres/", "/annonces/marches-publics/",
                "/annonces/appels-a-la-concurrence/", "/annonces/avis-de-consultation/",
                "/annonces/avis-d-appel-d-offres/"]:
        r = _get(s, base + cat)
        if not r: continue
        soup = BS(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(base, a["href"])
            if href in seen or base not in href: continue
            title = a.get_text(strip=True)
            if len(title) < 20 or not _is_ao(title): continue
            seen.add(href)
            r2 = _get(s, href, 15)
            if not r2: continue
            soup2 = BS(r2.text, "html.parser")
            h1 = soup2.find("h1") or soup2.find("h2")
            real_title = h1.get_text(strip=True) if h1 else title
            page = r2.text[:2000]
            if is_expired(page): skip += 1; continue
            results.append(_build("lematin", href, real_title, page))
            time.sleep(0.7)
    log_fn(f"lematin: {len(results)} valides, {skip} expirés")
    return results


def scrape_flasheconomie(log_fn=print) -> list:
    s = _sess(); results = []; seen = set(); skip = 0
    NOT_FLASH = ["emploi", "recrutement", "stage", "bourse", "immobilier"]
    for url in [
        "https://flasheconomie.com/category/appels-offres/",
        "https://flasheconomie.com/category/consulter-les-annonces-legales/",
        "https://flasheconomie.com/category/marches-publics/",
    ]:
        r = _get(s, url)
        if not r: continue
        soup = BS(r.text, "html.parser")
        for art in soup.find_all("article"):
            h = art.find(["h1","h2","h3"])
            a = (h.find("a", href=True) if h else None) or art.find("a", href=True)
            if not a: continue
            href = a["href"]
            if href in seen: continue
            seen.add(href)
            title = h.get_text(strip=True) if h else a.get_text(strip=True)
            if len(title) < 10 or any(n in title.lower() for n in NOT_FLASH): continue
            r2 = _get(s, href, 12)
            page = r2.text[:2000] if r2 else art.get_text()
            if is_expired(page): skip += 1; continue
            results.append(_build("flasheconomie", href, title, page))
            time.sleep(0.6)
    log_fn(f"flasheconomie: {len(results)} valides, {skip} expirés")
    return results


def run_all(log_fn=print) -> list:
    """Lance tous les scrapers journaux"""
    all_t = []
    for fn in [scrape_leconomiste, scrape_lematin, scrape_flasheconomie]:
        try:
            all_t.extend(fn(log_fn))
        except Exception as e:
            log_fn(f"✗ {fn.__name__}: {e}")
    log_fn(f"Journaux total: {len(all_t)} AO")
    return all_t
