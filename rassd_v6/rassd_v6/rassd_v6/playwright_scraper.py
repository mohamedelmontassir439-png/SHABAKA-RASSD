#!/usr/bin/env python3
"""
Modern Business — Playwright Scraper
Pour les journaux légaux qui bloquent requests (lavieeco, aujourdhui)
Remplace le local_scraper.py pour ces sources

Installation:
  pip install playwright
  playwright install chromium

Usage:
  python playwright_scraper.py
  python playwright_scraper.py --debug   # voir les pages
  python playwright_scraper.py --test    # tester sans envoyer
"""

import sys, re, time, hashlib, asyncio, warnings
from datetime import datetime, date
from typing import Optional

warnings.filterwarnings("ignore")

RAILWAY = "https://web-production-b4ae4.up.railway.app"
PWD     = "rassd2026"
TODAY   = date.today()

# ══════════════════════════════════════════════════════════
# DATE ENGINE
# ══════════════════════════════════════════════════════════

DATE_RE = re.compile(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})')
DL_KW   = [
    "date limite","date de clôture","date de remise","date de dépôt",
    "date de réception","réception des offres","réception des devis",
    "remise des offres","remise des plis","dépôt des offres",
    "avant le","au plus tard","clôture","échéance","soumission",
]
FMTS = ["%d/%m/%Y","%Y-%m-%d","%d-%m-%Y","%d.%m.%Y"]

def _pdate(s: str) -> Optional[date]:
    s = str(s).strip().split()[0]
    for fmt in FMTS:
        try: return datetime.strptime(s, fmt).date()
        except: pass
    return None

def extract_deadline(text: str) -> Optional[date]:
    if not text: return None
    tl = text.lower()
    found = [(m.start(), _pdate(m.group(1))) for m in DATE_RE.finditer(text)]
    found = [(p,d) for p,d in found if d and date(2025,1,1) <= d <= date(2029,12,31)]
    if not found: return None
    for kw in DL_KW:
        idx = tl.find(kw)
        if idx < 0: continue
        near = [(p,d) for p,d in found if idx <= p <= idx+200]
        if near: return min(near, key=lambda x: x[0])[1]
    future = [(p,d) for p,d in found if d >= TODAY]
    return max(future, key=lambda x: x[1])[1] if future else found[-1][1]

def is_future(text: str) -> bool:
    dl = extract_deadline(str(text))
    return dl is None or dl >= TODAY

def fmt_date(text: str) -> str:
    dl = extract_deadline(str(text)) if text else None
    return dl.strftime("%d/%m/%Y") if dl else ""

# ══════════════════════════════════════════════════════════
# AO DETECTION
# ══════════════════════════════════════════════════════════

AO_REQUIRED = [
    "appel d'offres","appel d offres","appel d'offre",
    "appel à la concurrence","marché public","marchés publics",
    "cahier des charges","avis d'appel","consultation",
    "fourniture de ","acquisition de ","travaux de ",
    "prestation de service","ao n°","ao ","aac ","ami ",
]
AO_EXCLUDED = [
    "offre d'emploi","offres d'emploi","recrutement",
    "marchés financiers","marchés boursiers","marchés de capitaux",
    "offre commerciale",
]

def is_ao(title: str, ctx: str = "") -> bool:
    text = (title + " " + ctx).lower()
    if any(e in text for e in AO_EXCLUDED): return False
    return any(k in text for k in AO_REQUIRED)

def mkid(src, title, url=""):
    return f"{src}_" + hashlib.md5(f"{title[:80]}{url[-20:]}".encode()).hexdigest()[:10]

def build(src, url, title, dl_text=""):
    return {
        "id": mkid(src, title, url),
        "objet": title[:300].strip(),
        "source": src,
        "source_url": url,
        "acheteur": "",
        "region": "Maroc",
        "date_limite": fmt_date(dl_text),
        "statut": "actif",
        "description": "",
    }

# ══════════════════════════════════════════════════════════
# PLAYWRIGHT SCRAPERS
# ══════════════════════════════════════════════════════════

async def scrape_with_playwright(sources: list, debug: bool = False):
    """Lance Playwright et scrape toutes les sources"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ Playwright non installé. Lancer: pip install playwright && playwright install chromium")
        return []

    results = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=not debug,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"]
        )
        ctx = await browser.new_context(
            viewport={"width":1280,"height":800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0",
            locale="fr-FR",
        )
        page = await ctx.new_page()
        page.set_default_timeout(25000)

        for name, fn in sources:
            try:
                print(f"\n  → {name}")
                res = await fn(page, debug)
                results.extend(res)
                print(f"    ✅ {len(res)} AO valides")
            except Exception as e:
                print(f"    ✗ {e}")

        await browser.close()

    return results


async def scrape_lavieeco(page, debug=False):
    """La Vie Eco — bloque requests, Playwright contourne"""
    results = []; seen = set(); skip = 0
    urls = [
        "https://www.lavieeco.com/appels-offres/",
        "https://www.lavieeco.com/appels-offres/page/2/",
    ]
    for url in urls:
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            content = await page.content()

            from bs4 import BeautifulSoup as BS
            soup = BS(content, "html.parser")

            for el in soup.find_all(["article","div"],
                                     class_=re.compile(r'post|entry|article|td-module', re.I)):
                a = el.find("a", href=True)
                if not a: continue
                href = a["href"]
                if href in seen or len(href) < 30: continue
                seen.add(href)
                h = el.find(["h2","h3"])
                title = h.get_text(strip=True) if h else a.get_text(strip=True)
                if not is_ao(title) or len(title) < 10: continue

                # Fetch detail
                try:
                    await page.goto(href, wait_until="domcontentloaded")
                    await page.wait_for_timeout(1500)
                    detail = await page.content()
                    if not is_future(detail): skip += 1; continue
                    results.append(build("lavieeco", href, title, detail[:2000]))
                except: pass
                await page.wait_for_timeout(800)
        except: pass

    print(f"    lavieeco: {len(results)} valides, {skip} expirés")
    return results


async def scrape_aujourdhui(page, debug=False):
    """Aujourd'hui le Maroc — Playwright"""
    results = []; seen = set(); skip = 0
    urls = [
        "https://aujourdhui.ma/appels-offres",
        "https://aujourdhui.ma/category/appels-doffres",
    ]
    for url in urls:
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            content = await page.content()

            from bs4 import BeautifulSoup as BS
            soup = BS(content, "html.parser")

            for el in soup.find_all(["article","div"],
                                     class_=re.compile(r'post|article|td-block|item', re.I)):
                a = el.find("a", href=True)
                if not a: continue
                href = a["href"]
                if href in seen or "aujourdhui" not in href: continue
                seen.add(href)
                h = el.find(["h2","h3"])
                title = h.get_text(strip=True) if h else a.get_text(strip=True)
                if not is_ao(title) or len(title) < 10: continue

                try:
                    await page.goto(href, wait_until="domcontentloaded")
                    await page.wait_for_timeout(1500)
                    detail = await page.content()
                    if not is_future(detail): skip += 1; continue
                    results.append(build("aujourdhui", href, title, detail[:2000]))
                except: pass
                await page.wait_for_timeout(800)
        except: pass

    print(f"    aujourdhui: {len(results)} valides, {skip} expirés")
    return results


async def scrape_leconomiste_pw(page, debug=False):
    """L'Économiste via Playwright (plus fiable que requests)"""
    results = []; seen = set(); skip = 0
    for url in [
        "https://www.leconomiste.com/appels-offres",
        "https://www.leconomiste.com/appels-offres?page=1",
        "https://www.leconomiste.com/appels-offres?page=2",
    ]:
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            content = await page.content()

            from bs4 import BeautifulSoup as BS
            soup = BS(content, "html.parser")

            # Vraie structure Drupal: div.views-row
            for el in soup.find_all("div", class_=re.compile(r'views-row|node-teaser', re.I)):
                a = el.find("a", href=True)
                if not a: continue
                href = a["href"]
                if not href.startswith("http"):
                    href = "https://www.leconomiste.com" + href
                if href in seen or "leconomiste" not in href: continue
                seen.add(href)

                h = el.find(["h2","h3","h4"]) or a
                title = h.get_text(strip=True)
                ctx   = el.get_text()

                # Exclure marchés financiers etc.
                if not is_ao(title, ctx): continue
                if not is_future(ctx): skip += 1; continue
                results.append(build("leconomiste", href, title, ctx))
        except: pass

    print(f"    leconomiste: {len(results)} valides, {skip} expirés")
    return results


async def scrape_lematin_pw(page, debug=False):
    """Le Matin Annonces via Playwright"""
    results = []; seen = set(); skip = 0
    base = "https://annonces.lematin.ma"
    cats = [
        f"{base}/annonces/appels-offres/",
        f"{base}/annonces/marches-publics/",
        f"{base}/annonces/appels-a-la-concurrence/",
    ]
    for cat in cats:
        try:
            await page.goto(cat, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            content = await page.content()

            from bs4 import BeautifulSoup as BS
            soup = BS(content, "html.parser")

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("http"):
                    href = base + href
                if href in seen or base not in href: continue
                title = a.get_text(strip=True)
                if len(title) < 20: continue
                if not is_ao(title): continue
                seen.add(href)

                try:
                    await page.goto(href, wait_until="domcontentloaded")
                    await page.wait_for_timeout(1200)
                    det = await page.content()
                    from bs4 import BeautifulSoup as BS2
                    s2 = BS2(det, "html.parser")
                    h1 = s2.find("h1") or s2.find("h2")
                    real_title = h1.get_text(strip=True) if h1 else title
                    if not is_future(det): skip += 1; continue
                    results.append(build("lematin", href, real_title, det[:2000]))
                except: pass
                await page.wait_for_timeout(900)
        except: pass

    print(f"    lematin: {len(results)} valides, {skip} expirés")
    return results


# ══════════════════════════════════════════════════════════
# PUSH TO RAILWAY
# ══════════════════════════════════════════════════════════

def push(tenders, dry_run=False):
    if not tenders:
        print("  → Rien à envoyer")
        return 0
    seen = set()
    unique = [t for t in tenders
              if t["id"] not in seen
              and not seen.add(t["id"])
              and len(t["objet"]) > 10]
    if dry_run:
        print(f"  DRY RUN — {len(unique)} AO:")
        for t in unique[:5]:
            print(f"    • {t['objet'][:60]} | ⏰{t['date_limite'] or '?'}")
        return 0
    import requests as _r
    try:
        r = _r.post(f"{RAILWAY}/api/v1/ingest",
                    json={"tenders":unique,"pwd":PWD}, timeout=30)
        if r.status_code == 200:
            d = r.json()
            print(f"  ✅ {d.get('saved',0)}/{len(unique)} sauvegardés sur Railway")
            return d.get("saved",0)
        print(f"  ❌ HTTP {r.status_code}")
    except Exception as e:
        print(f"  ❌ {e}")
    return 0


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

async def main():
    debug   = "--debug" in sys.argv
    dry_run = "--test"  in sys.argv

    print(f"{'═'*56}")
    print(f"  Modern Business — Playwright Scraper")
    print(f"  Sources: lavieeco · aujourdhui · leconomiste · lematin")
    print(f"  Filtre: date_limite >= {TODAY}")
    if dry_run: print(f"  MODE: DRY RUN (pas d'envoi)")
    print(f"{'═'*56}\n")

    sources = [
        ("La Vie Eco",       scrape_lavieeco),
        ("Aujourd'hui Maroc",scrape_aujourdhui),
        ("L'Économiste",     scrape_leconomiste_pw),
        ("Le Matin",         scrape_lematin_pw),
    ]

    results = await scrape_with_playwright(sources, debug=debug)

    print(f"\n  Total: {len(results)} AO valides")
    push(results, dry_run=dry_run)


if __name__ == "__main__":
    asyncio.run(main())
