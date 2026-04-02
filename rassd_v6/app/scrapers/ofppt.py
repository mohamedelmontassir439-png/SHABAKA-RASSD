"""
Modern Business — Scraper OFPPT
ofppt.ma — mises à jour fréquentes
"""
import re, time, requests
from bs4 import BeautifulSoup as BS
from app.core.dates import is_expired

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0"
CURRENT_YEAR = "2026"

def run(log_fn=print) -> list:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.verify = False
    results = []; seen = set()

    for url in [
        "https://www.ofppt.ma/fr/appels-d-offres",
        "https://www.ofppt.ma/fr/appels-d-offres?page=1",
    ]:
        try:
            r = s.get(url, timeout=20)
            if r.status_code != 200: continue
            soup = BS(r.text, "html.parser")
            for item in soup.find_all(["li","div","tr"],
                                       class_=re.compile(r'item|row|appel|offre', re.I)):
                a = item.find("a", href=True)
                if not a: continue
                title = item.get_text(strip=True)
                if not title or len(title) < 10: continue
                # Filtrer années passées
                if any(y in title for y in ["/2024", "/2023", "/2022", "2024/", "2023/"]): continue
                href = a["href"]
                if not href.startswith("http"):
                    href = "https://www.ofppt.ma" + href
                if href in seen: continue
                seen.add(href)
                if is_expired(title): continue
                results.append({
                    "id":          f"ofppt_{re.sub(r'[^a-z0-9]', '', title.lower())[:20]}",
                    "objet":       title[:300],
                    "source":      "ofppt",
                    "source_url":  href,
                    "acheteur":    "OFPPT — Formation Professionnelle",
                    "region":      "Maroc",
                    "date_limite": "",
                    "statut":      "actif",
                    "description": "",
                })
        except Exception as e:
            log_fn(f"✗ OFPPT: {e}")

    log_fn(f"ofppt: {len(results)} AO 2026")
    return results
