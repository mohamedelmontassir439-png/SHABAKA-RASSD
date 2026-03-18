"""
Modern Business — Multi-Site Scraper Agent v3.0
══════════════════════════════════════════════════════════════════
Sites: marocao.com | lesoffres.ma | aljady.ma | marchesprives.ma
       marchespublics.gov.ma (already in main.py)

Features:
- Rotating User Agents + delays anti-blocking
- AI scoring "easy to win" (rule-based + keyword analysis)
- Duplicate detection (title hash)
- ISO date normalization
- Category auto-classification
- WhatsApp via Twilio API
══════════════════════════════════════════════════════════════════
"""
import re, time, random, hashlib, logging, os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("multi_scraper")

# ══════════════════════════════════════════════════════
# ROTATING USER AGENTS
# ══════════════════════════════════════════════════════
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

def get_session():
    """HTTP session with anti-blocking"""
    import requests
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT":             "1",
        "Connection":      "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return s

def random_delay(min_s=1.5, max_s=4.0):
    """Human-like delay"""
    time.sleep(random.uniform(min_s, max_s))

def safe_get(session, url: str, timeout=20, retries=3) -> Optional[object]:
    """Resilient GET with retry + rotating UA"""
    for attempt in range(retries):
        try:
            # Rotate UA on each retry
            session.headers["User-Agent"] = random.choice(USER_AGENTS)
            r = session.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code == 200:
                return r
            elif r.status_code == 429:
                logger.warning(f"Rate limited on {url} — waiting 30s")
                time.sleep(30)
            elif r.status_code in [403, 406]:
                logger.warning(f"Blocked {r.status_code} on {url}")
                time.sleep(random.uniform(10, 20))
            else:
                logger.debug(f"HTTP {r.status_code} on {url}")
                return None
        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(random.uniform(3, 8))
    return None

# ══════════════════════════════════════════════════════
# NORMALIZERS
# ══════════════════════════════════════════════════════
MONTH_MAP = {
    "janvier":"01","février":"02","mars":"03","avril":"04","mai":"05","juin":"06",
    "juillet":"07","août":"08","septembre":"09","octobre":"10","novembre":"11","décembre":"12",
    "jan":"01","fév":"02","mar":"03","avr":"04","mai":"05","jun":"06",
    "jul":"07","aoû":"08","sep":"09","oct":"10","nov":"11","déc":"12",
    "يناير":"01","فبراير":"02","مارس":"03","أبريل":"04","ماي":"05","يونيو":"06",
    "يوليوز":"07","غشت":"08","شتنبر":"09","أكتوبر":"10","نونبر":"11","دجنبر":"12",
}

def normalize_date(text: str) -> str:
    """Convert any date string to ISO YYYY-MM-DD"""
    if not text: return ""
    text = text.strip()
    # Already ISO
    if re.match(r'\d{4}-\d{2}-\d{2}', text): return text[:10]
    # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})', text)
    if m: return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    # "15 janvier 2025" or "15 jan 2025"
    m = re.search(r'(\d{1,2})\s+([a-zéûôèàùâêîA-Zأ-ي]+)\s+(\d{4})', text, re.I)
    if m:
        day, month_str, year = m.group(1), m.group(2).lower(), m.group(3)
        month = MONTH_MAP.get(month_str, "")
        if month: return f"{year}-{month}-{day.zfill(2)}"
    # Relative: "dans 30 jours"
    m = re.search(r'dans\s+(\d+)\s+jours?', text, re.I)
    if m: return (datetime.now() + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    return text[:20]

def tender_hash(title: str, source: str) -> str:
    """Unique ID for duplicate detection"""
    clean = re.sub(r'\s+', ' ', title.lower().strip())[:80]
    return hashlib.md5(f"{source}:{clean}".encode()).hexdigest()[:16]

REGIONS_MAP = {
    "Casablanca": ["casablanca","casa","anfa","ain chock","hay hassani"],
    "Rabat":      ["rabat","salé","sale","témara","skhirat","kénitra","kenitra"],
    "Marrakech":  ["marrakech","guéliz","hivernage","marrakesh"],
    "Fès":        ["fès","fez","sefrou","ifrane"],
    "Agadir":     ["agadir","inezgane","tiznit","taroudant"],
    "Tanger":     ["tanger","tétouan","tetouan","al hoceima","chefchaouen"],
    "Oujda":      ["oujda","nador","berkane"],
    "Meknès":     ["meknès","meknes"],
    "National":   ["national","maroc","toutes les régions","tout le maroc","royaume"],
}

def normalize_region(text: str) -> str:
    if not text: return "Maroc"
    low = text.lower()
    for region, kws in REGIONS_MAP.items():
        if any(k in low for k in kws): return region
    return text[:50].strip() or "Maroc"

# Official Moroccan codes T/P/S
CATEGORY_MAP = {
    "T101 - Constructions & Bâtiments":   ["construction","bâtiment","btp","travaux","gros oeuvre","maçonnerie","rénovation","réhabilitation"],
    "T110 - Génie Civil":                  ["génie civil","infrastructure","pont","viaduc","route","voirie","terrassement"],
    "T201 - Assainissement":               ["assainissement","réseau","eau","hydraulique","forage","station"],
    "T401 - Électricité":                  ["électricité","éclairage","câblage","électrique","solaire","énergie"],
    "T402 - Sécurité & Télésurveillance":  ["sécurité","surveillance","alarme","cctv","caméra","gardiennage"],
    "T403 - Télécommunications":            ["télécommunication","réseau","fibre","câblage","gsm","wifi"],
    "P818 - Informatique":                  ["informatique","logiciel","système","application","web","cloud","erp","crm","développement","numérique","digital"],
    "P813 - Médical":                       ["médical","santé","hôpital","laboratoire","pharmaceutique","équipement médical"],
    "P816 - Véhicules & Transport":         ["véhicule","transport","camion","voiture","bus","carburant","flotte"],
    "P825 - Fournitures Bureau":            ["fournitures","bureau","papier","mobilier","imprimante","consommables"],
    "P834 - Alimentation":                  ["alimentation","restauration","traiteur","denrée","repas"],
    "P841 - Nettoyage":                     ["nettoyage","hygiène","propreté","désinfection","entretien"],
    "S902 - Études & Conseil":              ["étude","conseil","consultant","audit","expertise","formation","mission"],
    "S906 - Maintenance":                   ["maintenance","entretien","réparation","contrat"],
    "S907 - Nettoyage Services":            ["service nettoyage","facility"],
    "S908 - Gardiennage":                   ["gardiennage","agent sécurité"],
    "S913 - Formation":                     ["formation","séminaire","coaching","certification"],
}

def classify_category(text: str) -> str:
    low = text.lower()
    scores = {}
    for cat, kws in CATEGORY_MAP.items():
        score = sum(2 if len(k) > 9 else 1 for k in kws if k in low)
        if score: scores[cat] = score
    return max(scores, key=scores.get) if scores else "P825 - Fournitures Bureau"

# ══════════════════════════════════════════════════════
# AI SCORING — "Easy to Win" prediction
# ══════════════════════════════════════════════════════
def ai_score_tender(tender: dict) -> dict:
    """
    Rule-based AI scoring for tender win probability.
    Returns score 0-100 + reasoning.
    """
    score = 50  # Base
    reasons = []

    title  = (tender.get("title") or "").lower()
    desc   = (tender.get("description") or "").lower()
    budget = tender.get("budget") or ""
    region = tender.get("region") or ""
    full   = title + " " + desc

    # ── Positive signals (higher score = easier) ──
    # Small budget → less competition
    try:
        bval = float(re.sub(r'[^\d.]', '', str(budget).replace(',','').replace(' ','')))
        if bval < 100000:    score += 15; reasons.append("Budget < 100K DH")
        elif bval < 500000:  score += 8;  reasons.append("Budget < 500K DH")
        elif bval > 5000000: score -= 15; reasons.append("Grand budget (>5M)")
    except: pass

    # Simple/routine categories
    easy_cats = ["nettoyage","fournitures","imprimerie","gardiennage","restauration","entretien","maintenance"]
    if any(k in full for k in easy_cats):
        score += 12; reasons.append("Catégorie accessible")

    # Specific city (less competition than national)
    if region and region.lower() not in ["national","maroc","tout le maroc"]:
        score += 8; reasons.append("Marché régional")

    # Short description = simple tender
    if len(desc) < 200:
        score += 5; reasons.append("Description courte/simple")

    # Deadline > 15 days (enough time to prepare)
    dl = tender.get("deadline") or ""
    if dl:
        try:
            d = datetime.strptime(dl, "%Y-%m-%d")
            days_left = (d - datetime.now()).days
            if days_left > 30:  score += 10; reasons.append(f"{days_left}j pour préparer")
            elif days_left < 7: score -= 20; reasons.append(f"Seulement {days_left}j restants")
        except: pass

    # ── Negative signals ──
    hard = ["étude","ingénierie","conception","maîtrise d'oeuvre","expertise","audit"]
    if any(k in full for k in hard):
        score -= 10; reasons.append("Nécessite expertise spécialisée")

    complex_kw = ["international","appel d'offres ouvert restreint","qualification","agréé"]
    if any(k in full for k in complex_kw):
        score -= 8; reasons.append("Procédure complexe")

    # Source private = possibly less scrutiny
    if tender.get("source") in ["marocao.com","lesoffres.ma","marchesprives.ma"]:
        score += 5; reasons.append("Marché privé")

    # Clamp
    score = max(5, min(95, score))

    # Label
    if score >= 70:   label = "🟢 Facile"
    elif score >= 45: label = "🟡 Moyen"
    else:             label = "🔴 Difficile"

    return {
        "score":   score,
        "label":   label,
        "reasons": reasons[:3],
    }

# ══════════════════════════════════════════════════════
# SITE SCRAPERS
# ══════════════════════════════════════════════════════

class MarocAOScraper:
    """https://marocao.com — Annonces d'appels d'offres Maroc"""
    BASE = "https://marocao.com"

    @staticmethod
    def scrape(log_fn=None) -> list:
        from bs4 import BeautifulSoup as BS
        results = []
        s = get_session()
        log = log_fn or logger.info
        log("[marocao.com] Démarrage...")

        for page in range(1, 6):
            url = f"{MarocAOScraper.BASE}/appels-offres" + (f"?page={page}" if page > 1 else "")
            try:
                r = safe_get(s, url)
                if not r: break
                soup = BS(r.text, "html.parser")

                # Try multiple card selectors
                cards = (soup.select(".tender-card") or
                         soup.select(".ao-item") or
                         soup.select("article.post") or
                         soup.select(".card") or
                         soup.select("li.tender") or
                         soup.select(".annonce"))

                if not cards:
                    # Fallback: parse all links with tender-like URLs
                    cards = [a.parent for a in soup.find_all("a", href=True)
                             if "/appel" in a.get("href","") or "/tender" in a.get("href","")
                             or "/marche" in a.get("href","")]

                if not cards:
                    log(f"[marocao.com] Page {page}: aucune annonce")
                    break

                for card in cards[:20]:
                    try:
                        title_el = (card.find(["h1","h2","h3","h4",".title",".titre"]) or
                                    card.find("a"))
                        title = title_el.get_text(strip=True) if title_el else ""
                        if not title or len(title) < 8: continue

                        desc_el = card.find(["p",".description",".excerpt",".content"])
                        desc = desc_el.get_text(strip=True)[:500] if desc_el else ""

                        # Dates
                        date_text = ""
                        for pat in [".date",".deadline",".date-limite","time","[class*='date']"]:
                            el = card.select_one(pat)
                            if el: date_text = el.get_text(strip=True); break

                        # Budget
                        budget = ""
                        full_text = card.get_text(" ")
                        m = re.search(r'(\d[\d\s,.]*)\s*(?:DH|MAD|dirham)', full_text, re.I)
                        if m: budget = m.group(0)[:60]

                        # Link
                        link_el = card.find("a", href=True)
                        link = link_el["href"] if link_el else ""
                        if link and not link.startswith("http"):
                            link = MarocAOScraper.BASE + link

                        t = {
                            "id":          f"marocao_{tender_hash(title, 'marocao.com')}",
                            "title":       title,
                            "description": desc,
                            "budget":      budget,
                            "region":      normalize_region(full_text),
                            "category":    classify_category(title + " " + desc),
                            "deadline":    normalize_date(date_text),
                            "source":      "marocao.com",
                            "url":         link,
                            "contact":     "",
                        }
                        t["ai"] = ai_score_tender(t)
                        results.append(t)
                    except Exception as e:
                        logger.debug(f"[marocao card] {e}")

                log(f"[marocao.com] Page {page}: +{len(cards)} → total {len(results)}")
                random_delay(2, 4)
            except Exception as e:
                log(f"[marocao.com] Erreur page {page}: {e}")
                break

        log(f"[marocao.com] ✓ {len(results)} appels d'offres")
        return results


class LesOffresScraper:
    """https://lesoffres.ma — Offres & marchés Maroc"""
    BASE = "https://lesoffres.ma"

    @staticmethod
    def scrape(log_fn=None) -> list:
        from bs4 import BeautifulSoup as BS
        results = []
        s = get_session()
        log = log_fn or logger.info
        log("[lesoffres.ma] Démarrage...")

        urls_to_try = [
            f"{LesOffresScraper.BASE}/appels-offres",
            f"{LesOffresScraper.BASE}/offres",
            f"{LesOffresScraper.BASE}/marches",
            LesOffresScraper.BASE,
        ]

        for base_url in urls_to_try:
            for page in range(1, 5):
                url = base_url + (f"?page={page}" if page > 1 else "")
                try:
                    r = safe_get(s, url)
                    if not r: continue
                    soup = BS(r.text, "html.parser")

                    items = (soup.select(".offre") or
                             soup.select(".tender") or
                             soup.select("article") or
                             soup.select(".post") or
                             soup.select(".item-offre") or
                             soup.select(".offer-card"))

                    if not items: continue

                    for item in items[:25]:
                        try:
                            t_el = item.find(["h1","h2","h3","h4","a",".title"])
                            title = t_el.get_text(strip=True) if t_el else ""
                            if not title or len(title) < 8: continue

                            desc_el = item.find(["p",".desc",".description",".summary"])
                            desc = desc_el.get_text(strip=True)[:500] if desc_el else ""

                            full = item.get_text(" ")
                            date_t = ""
                            for pat in [".date",".deadline","time",".expiry"]:
                                el = item.select_one(pat)
                                if el: date_t = el.get_text(strip=True); break
                            if not date_t:
                                m = re.search(r'\d{2}[/\-\.]\d{2}[/\-\.]\d{4}', full)
                                if m: date_t = m.group(0)

                            budget = ""
                            mb = re.search(r'(\d[\d\s,.]{2,14})\s*(?:DH|MAD)', full, re.I)
                            if mb: budget = mb.group(0)[:60]

                            link_el = item.find("a", href=True)
                            link = link_el["href"] if link_el else ""
                            if link and not link.startswith("http"):
                                link = LesOffresScraper.BASE + link

                            # Contact info
                            contact = ""
                            for pat in [r'[\w.+-]+@[\w-]+\.[\w.]+', r'[+\d]{10,14}', r'0[56789]\d{8}']:
                                cm = re.search(pat, full)
                                if cm: contact = cm.group(0); break

                            t = {
                                "id":          f"lesoffres_{tender_hash(title,'lesoffres.ma')}",
                                "title":       title,
                                "description": desc,
                                "budget":      budget,
                                "region":      normalize_region(full),
                                "category":    classify_category(title+" "+desc),
                                "deadline":    normalize_date(date_t),
                                "source":      "lesoffres.ma",
                                "url":         link,
                                "contact":     contact,
                            }
                            t["ai"] = ai_score_tender(t)
                            results.append(t)
                        except Exception as e:
                            logger.debug(f"[lesoffres item] {e}")

                    log(f"[lesoffres.ma] {url} page {page}: +{len(items)}")
                    random_delay(1.5, 3.5)
                    if len(results) > 50: break
                except Exception as e:
                    log(f"[lesoffres.ma] {e}")
            if results: break

        log(f"[lesoffres.ma] ✓ {len(results)} offres")
        return results


class AlJadyScraper:
    """https://aljady.ma — Marchés & offres Maroc (Arabic/French)"""
    BASE = "https://aljady.ma"

    @staticmethod
    def scrape(log_fn=None) -> list:
        from bs4 import BeautifulSoup as BS
        results = []
        s = get_session()
        log = log_fn or logger.info
        log("[aljady.ma] Démarrage...")

        urls = [
            f"{AlJadyScraper.BASE}/tenders",
            f"{AlJadyScraper.BASE}/marches",
            f"{AlJadyScraper.BASE}/appels-offres",
            f"{AlJadyScraper.BASE}/مناقصات",
            AlJadyScraper.BASE,
        ]

        for url in urls:
            try:
                r = safe_get(s, url)
                if not r: continue
                soup = BS(r.text, "html.parser")

                cards = (soup.select(".tender-item") or
                         soup.select(".marche") or
                         soup.select("article") or
                         soup.select(".post-item") or
                         soup.select(".content-item"))

                for card in cards[:30]:
                    try:
                        t_el = card.find(["h1","h2","h3","h4","a"])
                        title = t_el.get_text(strip=True) if t_el else ""
                        if not title or len(title) < 5: continue

                        desc_el = card.find(["p",".description",".excerpt"])
                        desc = desc_el.get_text(strip=True)[:500] if desc_el else ""
                        full = card.get_text(" ")

                        date_t = ""
                        dm = re.search(r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4}', full)
                        if dm: date_t = dm.group(0)

                        budget = ""
                        bm = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD|درهم)', full, re.I)
                        if bm: budget = bm.group(0)[:60]

                        link_el = card.find("a", href=True)
                        link = link_el["href"] if link_el else ""
                        if link and not link.startswith("http"):
                            link = AlJadyScraper.BASE + link

                        # Detect Arabic text
                        if re.search(r'[\u0600-\u06FF]', title):
                            # Translate category for Arabic titles
                            category = classify_category(title+" "+desc)
                        else:
                            category = classify_category(title+" "+desc)

                        t = {
                            "id":          f"aljady_{tender_hash(title,'aljady.ma')}",
                            "title":       title,
                            "description": desc,
                            "budget":      budget,
                            "region":      normalize_region(full),
                            "category":    category,
                            "deadline":    normalize_date(date_t),
                            "source":      "aljady.ma",
                            "url":         link,
                            "contact":     "",
                        }
                        t["ai"] = ai_score_tender(t)
                        results.append(t)
                    except Exception as e:
                        logger.debug(f"[aljady card] {e}")

                if results:
                    log(f"[aljady.ma] {url}: {len(results)} marchés")
                    break
                random_delay(2, 4)
            except Exception as e:
                log(f"[aljady.ma] {e}")

        log(f"[aljady.ma] ✓ {len(results)} marchés")
        return results


class MarchesPrivesScraper:
    """https://marchesprives.ma — Marchés privés Maroc"""
    BASE = "https://marchesprives.ma"

    @staticmethod
    def scrape(log_fn=None) -> list:
        from bs4 import BeautifulSoup as BS
        results = []
        s = get_session()
        log = log_fn or logger.info
        log("[marchesprives.ma] Démarrage...")

        pages_to_try = [
            f"{MarchesPrivesScraper.BASE}/marches",
            f"{MarchesPrivesScraper.BASE}/appels-offres",
            f"{MarchesPrivesScraper.BASE}/offres",
            MarchesPrivesScraper.BASE,
        ]

        for url in pages_to_try:
            for page in range(1, 4):
                full_url = url + (f"?page={page}" if page > 1 else "")
                try:
                    r = safe_get(s, full_url)
                    if not r: continue
                    soup = BS(r.text, "html.parser")

                    items = (soup.select(".marche-item") or
                             soup.select(".offre-item") or
                             soup.select("article") or
                             soup.select(".tender") or
                             soup.select(".post"))

                    if not items: continue

                    for item in items[:25]:
                        try:
                            t_el = item.find(["h1","h2","h3","h4","a",".title"])
                            title = t_el.get_text(strip=True) if t_el else ""
                            if not title or len(title) < 8: continue

                            desc_el = item.find(["p",".description",".excerpt",".content"])
                            desc = desc_el.get_text(strip=True)[:500] if desc_el else ""
                            full = item.get_text(" ")

                            # Date
                            date_t = ""
                            dm = re.search(r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4}', full)
                            if dm: date_t = dm.group(0)

                            # Budget
                            budget = ""
                            bm = re.search(r'(\d[\d\s,.]{2,14})\s*(?:DH|MAD|dirham)', full, re.I)
                            if bm: budget = bm.group(0)[:60]

                            # Contact (private markets often show contact)
                            contact = ""
                            em = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', full)
                            pm = re.search(r'(?:0[56789]|(?:\+212))\d{8}', full)
                            if em: contact = em.group(0)
                            elif pm: contact = pm.group(0)

                            link_el = item.find("a", href=True)
                            link = link_el["href"] if link_el else ""
                            if link and not link.startswith("http"):
                                link = MarchesPrivesScraper.BASE + link

                            t = {
                                "id":          f"prives_{tender_hash(title,'marchesprives.ma')}",
                                "title":       title,
                                "description": desc,
                                "budget":      budget,
                                "region":      normalize_region(full),
                                "category":    classify_category(title+" "+desc),
                                "deadline":    normalize_date(date_t),
                                "source":      "marchesprives.ma",
                                "url":         link,
                                "contact":     contact,
                            }
                            t["ai"] = ai_score_tender(t)
                            results.append(t)
                        except Exception as e:
                            logger.debug(f"[marchesprives item] {e}")

                    log(f"[marchesprives.ma] Page {page}: +{len(items)}")
                    random_delay(1.5, 3)
                except Exception as e:
                    log(f"[marchesprives.ma] {e}")
            if results: break

        log(f"[marchesprives.ma] ✓ {len(results)} marchés privés")
        return results

# ══════════════════════════════════════════════════════
# MASTER MULTI-SCRAPER
# ══════════════════════════════════════════════════════
SCRAPERS = [
    ("marocao.com",      MarocAOScraper.scrape),
    ("lesoffres.ma",     LesOffresScraper.scrape),
    ("aljady.ma",        AlJadyScraper.scrape),
    ("marchesprives.ma", MarchesPrivesScraper.scrape),
]

def run_all_scrapers(db_save_fn, log_fn=None, known_ids: set = None) -> dict:
    """
    Run all scrapers, deduplicate, save new tenders.
    
    Args:
        db_save_fn: function(tender_dict) -> bool  (returns True if new)
        log_fn:     function(str) for logging
        known_ids:  set of already known tender IDs
    
    Returns:
        dict with stats per site
    """
    log = log_fn or logger.info
    known = known_ids or set()
    stats = {}
    all_new = []

    log("═══ Multi-Scraper démarré ═══")
    log(f"Sites: {', '.join(s[0] for s in SCRAPERS)}")

    for site_name, scraper_fn in SCRAPERS:
        site_stats = {"found": 0, "new": 0, "errors": 0}
        try:
            tenders = scraper_fn(log_fn=log)
            site_stats["found"] = len(tenders)

            # Deduplicate + save
            seen_in_run = set()
            for t in tenders:
                tid = t.get("id","")
                if not tid or tid in known or tid in seen_in_run:
                    continue
                seen_in_run.add(tid)

                try:
                    is_new = db_save_fn(t)
                    if is_new:
                        site_stats["new"] += 1
                        all_new.append(t)
                        known.add(tid)
                except Exception as e:
                    site_stats["errors"] += 1
                    logger.error(f"[save {site_name}] {e}")

            log(f"[{site_name}] ✓ {site_stats['found']} trouvés | {site_stats['new']} nouveaux")
        except Exception as e:
            site_stats["errors"] += 1
            log(f"[{site_name}] ✗ Erreur: {e}")

        stats[site_name] = site_stats
        # Delay between sites
        random_delay(3, 7)

    total_new = sum(s["new"] for s in stats.values())
    log(f"═══ Multi-Scraper terminé: {total_new} nouveaux sur {len(SCRAPERS)} sites ═══")

    return {"stats": stats, "new_tenders": all_new, "total_new": total_new}
