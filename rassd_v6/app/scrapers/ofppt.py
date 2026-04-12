"""
Modern Business — Scraper OFPPT
ofppt.ma — mises à jour fréquentes
"""
import re
import ssl
import time
import logging
from datetime import datetime, date

import requests
import urllib3
from bs4 import BeautifulSoup as BS
from requests.adapters import HTTPAdapter

from app.core.dates import is_expired
from app.core.sectors import classify, get_label

urllib3.disable_warnings()
logger = logging.getLogger("atlas.ofppt")

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124.0 Safari/537.36",
]


class TLSAdapter(HTTPAdapter):
    """Adapter SSL permissif."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _current_year() -> str:
    """Année actuelle dynamiquement."""
    return str(date.today().year)


def _old_years() -> list:
    """Années passées à filtrer."""
    y = date.today().year
    return [f"/{y-1}", f"/{y-2}", f"/{y-3}", f"{y-1}/", f"{y-2}/"]

def run(log_fn=print) -> list:
    import random
    retry = urllib3.Retry(
        total=3, backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s = requests.Session()
    s.mount("https://", TLSAdapter(max_retries=retry))
    s.mount("http://", TLSAdapter(max_retries=retry))
    s.headers["User-Agent"] = random.choice(UA_POOL)
    s.verify = False
    results = []
    seen = set()
    old_yrs = _old_years()

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
                if any(y in title for y in old_yrs):
                    continue
                href = a["href"]
                if not href.startswith("http"):
                    href = "https://www.ofppt.ma" + href
                if href in seen: continue
                seen.add(href)
                if is_expired(title): continue
                code = classify(title)
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                results.append({
                    "id":               f"ofppt_{re.sub(r'[^a-z0-9]', '', title.lower())[:20]}",
                    "objet":            title[:300],
                    "source":           "ofppt",
                    "source_url":       href,
                    "url":              href,
                    "acheteur":         "OFPPT \u2014 Formation Professionnelle",
                    "secteur":          f"{code} \u2013 {get_label(code)}",
                    "region":           "Maroc",
                    "date_limite":      "",
                    "date_publication": date.today().strftime("%d/%m/%Y"),
                    "montant":          "",
                    "statut":           "actif",
                    "description":      "Source: OFPPT",
                    "scraped_at":       now,
                    "updated_at":       now,
                })
        except Exception as e:
            log_fn(f"✗ OFPPT: {e}")

    log_fn(f"ofppt: {len(results)} AO {_current_year()}")
    return results
