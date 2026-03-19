"""
Modern Business — Multi-Source Scraper v2.0
═══════════════════════════════════════════════════════
SOURCES GRATUITES SANS INSCRIPTION:
  1. marchespublics.gov.ma  — Portail officiel
  2. annonces.lematin.ma    — Journal Le Matin (public, gratuit)
  3. bo.gov.ma              — Bulletin Officiel (textes légaux + AO)
  4. appels-offres.equipement.gov.ma — Ministère Équipement
  5. finances.gov.ma        — Ministère Finances
  6. tanmia.ma              — ONG + Coopération internationale
  7. onee.ma                — ONEE électricité/eau
  8. oncf.ma                — ONCF chemins de fer
  9. iam.ma                 — Maroc Telecom (IAM)
 10. lydec.ma               — LYDEC (eau/élec Casablanca)

STRATÉGIE ANTI-PAYWALL:
  - Google Search pour lesoffres.ma/aljady.ma (cache public)
  - Sitemap.xml parsing
  - RSS feeds quand disponibles
═══════════════════════════════════════════════════════
"""
import re, time, random, logging, hashlib, json, os
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger("mb.scraper")

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3) AppleWebKit/605.1.15 Version/17.0 Mobile Safari/604.1",
]

@dataclass
class Tender:
    id: str = ""
    source: str = ""
    source_url: str = ""
    objet: str = ""
    description: str = ""
    acheteur: str = ""
    region: str = ""
    domaine: str = ""
    type_marche: str = ""
    montant: str = ""
    budget_min: float = 0.0
    budget_max: float = 0.0
    date_publication: str = ""
    date_limite: str = ""
    contact: str = ""
    statut: str = "actif"
    ai_score: int = 50
    ai_category: str = ""
    ai_reason: str = ""
    date_extraction: str = ""

def make_session():
    import requests
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent": random.choice(UA_LIST),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    })
    return s

def sleep_r(a=0.8, b=2.0): time.sleep(random.uniform(a, b))
def make_id(src, title, url=""): return f"{src}_{hashlib.md5(f'{src}:{title}:{url}'.encode()).hexdigest()[:12]}"

def normalize_date(raw):
    if not raw: return ""
    raw = raw.strip()
    MONTHS_FR = {
        "janvier":"01","février":"02","mars":"03","avril":"04","mai":"05","juin":"06",
        "juillet":"07","août":"08","septembre":"09","octobre":"10","novembre":"11","décembre":"12",
        "jan":"01","fév":"02","mar":"03","avr":"04","jun":"06","jul":"07",
        "aoû":"08","sep":"09","oct":"10","nov":"11","déc":"12",
    }
    raw_low = raw.lower()
    for fr, num in MONTHS_FR.items():
        raw_low = raw_low.replace(fr, num)
    for fmt in ["%d/%m/%Y","%d-%m-%Y","%d.%m.%Y","%Y-%m-%d","%d/%m/%y","%d %m %Y"]:
        try: return datetime.strptime(raw_low.strip(), fmt).strftime("%Y-%m-%d")
        except: pass
    try: return datetime.strptime(raw.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except: pass
    m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', raw)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2: y = "20" + y
        try: return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
        except: pass
    return ""

def extract_budget(text):
    if not text: return 0.0, 0.0, ""
    text = text.replace("\u202f", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    m = re.search(r'(\d[\d.]+)\s*(?:dh|mad|dirham)', text, re.I)
    if m:
        try:
            v = float(m.group(1))
            if v > 0: return v, v, f"{v:,.0f} DH"
        except: pass
    return 0.0, 0.0, text[:60] if len(text) < 60 else ""

def clean_text(t, n=500):
    if not t: return ""
    return re.sub(r'\s+', ' ', str(t)).strip()[:n]

def is_expired(d):
    if not d: return False
    try: return datetime.strptime(d, "%Y-%m-%d").date() < datetime.now().date()
    except: return False

REGIONS_MAP = {
    "Rabat-Salé-Kénitra":        ["rabat","salé","kénitra","kenitra","témara","skhirat","khémisset"],
    "Casablanca-Settat":         ["casablanca","settat","mohammedia","berrechid","benslimane"],
    "Marrakech-Safi":            ["marrakech","safi","essaouira","kelaa","youssoufia"],
    "Fès-Meknès":                ["fès","fez","meknès","meknes","ifrane","taza","sefrou"],
    "Tanger-Tétouan-Al Hoceima": ["tanger","tétouan","tetouan","al hoceima","chefchaouen","larache"],
    "Oriental":                  ["oujda","nador","berkane","taourirt","jerada"],
    "Béni Mellal-Khénifra":     ["béni mellal","beni mellal","khénifra","azilal","khouribga"],
    "Souss-Massa":               ["agadir","tiznit","taroudant","inezgane"],
    "Drâa-Tafilalet":            ["errachidia","ouarzazate","zagora","midelt"],
    "Laâyoune":                  ["laayoune","boujdour"],
    "Dakhla":                    ["dakhla"],
    "Guelmim":                   ["guelmim","tan-tan"],
}

SECTEUR_KWS = {
    "T101 - Constructions & Bâtiments": ["bâtiment","construction","maçonnerie","béton","gros oeuvre","btp","rénovation","mur","clôture","façade","toiture","réhabilitation"],
    "T104 - Plomberie & Climatisation": ["plomberie","chauffage","climatisation","cvc","sanitaire","tuyauterie"],
    "T105 - Peinture & Vitrerie":       ["peinture","vitrerie","enduit","revêtement"],
    "T106 - Étanchéité":                ["étanchéité","isolation","imperméabilisation","membrane"],
    "T110 - Génie Civil":               ["génie civil","pont","infrastructure","ouvrage d'art","géotechnique"],
    "T201 - Assainissement":            ["assainissement","égout","step","collecteur","canalisation"],
    "T203 - Hydraulique":               ["hydraulique","eau potable","adduction","barrage","forage","irrigation","pompage"],
    "T301 - Travaux Routiers":          ["route","voirie","chaussée","trottoir","bitume","asphalte","signalisation","autoroute"],
    "T401 - Électricité":               ["électricité","éclairage","câblage","tableau électrique","transformateur","basse tension"],
    "T402 - Sécurité Électronique":     ["vidéosurveillance","cctv","alarme","incendie","contrôle accès"],
    "T403 - Télécommunications":        ["télécommunication","fibre optique","réseau informatique","switch","wifi","gsm"],
    "P813 - Équipements Médicaux":      ["médical","hôpital","laboratoire","réactif","chirurgical","pharmaceutique","médicament"],
    "P814 - Climatisation":             ["climatiseur","split","froid industriel","chambre froide"],
    "P816 - Matériel Roulant":          ["véhicule","voiture","camion","bus","carburant","gasoil","pneumatique"],
    "P818 - Informatique":              ["informatique","ordinateur","pc","serveur","imprimante","logiciel","cloud","erp","application"],
    "P825 - Fournitures Bureau":        ["fournitures","papier","ramette","mobilier de bureau","chaise","armoire"],
    "P834 - Alimentation":              ["alimentation","denrée","viande","restauration","traiteur","eau distillée"],
    "P839 - Matériaux Construction":    ["ciment","sable","gravier","béton prêt","brique","acier","rond à béton"],
    "P841 - Hygiène & Nettoyage":       ["nettoyage","propreté","désinfection","savon","détergent","dératisation"],
    "P850 - Énergies Renouvelables":    ["solaire","photovoltaïque","énergie renouvelable","panneau solaire"],
    "S901 - IT & Développement":        ["développement logiciel","application mobile","site web","cybersécurité","base de données"],
    "S902 - Études & Conseil":          ["étude","conseil","consultant","expertise","audit","bureau d'études","ingénierie","maîtrise"],
    "S906 - Maintenance":               ["maintenance","entretien","réparation","dépannage","contrat maintenance"],
    "S907 - Nettoyage Service":         ["nettoyage service","propreté service","hygiène industrielle"],
    "S908 - Gardiennage":               ["gardiennage","sécurité","surveillance","agent de sécurité"],
    "S910 - Communication":             ["communication","publicité","événementiel","impression","brochure"],
    "S913 - Formation":                 ["formation","coaching","séminaire","certification","e-learning"],
    "S915 - Transport":                 ["transport","location véhicule","navette","chauffeur"],
}

def detect_region(text):
    t = text.lower()
    for r, kws in REGIONS_MAP.items():
        if any(k in t for k in kws): return r
    return "Maroc"

def detect_secteur(title, desc=""):
    text = (title + " " + desc).lower()
    scores = {}
    for s, kws in SECTEUR_KWS.items():
        sc = sum(2 if len(k) > 10 else 1 for k in kws if k in text)
        if sc: scores[s] = sc
    return max(scores, key=scores.get) if scores else "P825 - Fournitures Bureau"

def detect_type(title):
    t = title.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","pose","démolition","rénovation","étanchéité"]): return "Travaux"
    if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel","équipement"]): return "Fournitures"
    if any(k in t for k in ["service","prestation","maintenance","gardiennage","nettoyage","transport"]): return "Services"
    if any(k in t for k in ["étude","mission","audit","conseil","formation","expertise","ingénierie"]): return "Études & Conseil"
    return "Fournitures"


# ══════════════════════════════════════════════════════
# AI CLASSIFIER
# ══════════════════════════════════════════════════════
class AIClassifier:
    PROMPT = """Analyse cet appel d'offres marocain pour PME.
Titre: {title}
Acheteur: {acheteur}
Montant: {montant}
Secteur: {secteur}

Réponds UNIQUEMENT en JSON valide (sans markdown):
{{"category":"{secteur}","score":<0-100>,"reason":"<explication 60 mots max>","estimated_competition":"faible|moyen|fort"}}

Score: 80-100=facile(petit budget/services), 60-79=moyen, 40-59=technique, 20-39=gros lot, 0-19=très complexe"""

    @staticmethod
    async def classify(t, anthropic_key):
        if not anthropic_key:
            return {"category": t.domaine, "score": 50, "reason": "IA non configurée", "estimated_competition": "moyen"}
        try:
            import httpx
            prompt = AIClassifier.PROMPT.format(
                title=t.objet[:200], acheteur=t.acheteur[:80],
                montant=t.montant or "Non précisé", secteur=t.domaine
            )
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": "claude-haiku-4-5-20251001", "max_tokens": 200,
                          "messages": [{"role": "user", "content": prompt}]}
                )
                if r.status_code == 200:
                    text = r.json()["content"][0]["text"].strip()
                    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
                    return json.loads(text)
        except Exception as e:
            logger.error(f"[AI] {e}")
        return {"category": t.domaine, "score": 50, "reason": "Erreur IA", "estimated_competition": "moyen"}

    @staticmethod
    async def batch_classify(tenders, anthropic_key, max_b=10):
        import asyncio
        results = []
        for t in tenders[:max_b]:
            res = await AIClassifier.classify(t, anthropic_key)
            t.ai_score = max(0, min(100, int(res.get("score", 50))))
            t.ai_category = res.get("category", t.domaine)
            t.ai_reason = res.get("reason", "")
            results.append(t)
            await asyncio.sleep(0.3)
        for t in tenders[max_b:]:
            t.ai_score = 50; results.append(t)
        return results


# ══════════════════════════════════════════════════════
# SOURCE 1: marchespublics.gov.ma (officiel)
# ══════════════════════════════════════════════════════
class MarchesPublicsScraper:
    BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        s = make_session()
        tenders = []
        def log(m):
            if log_fn: log_fn(f"[MarchesPublics] {m}")
        ids_found = []
        for page in range(1, 12):
            url = cls.BASE + "/" if page == 1 else f"{cls.BASE}/?page={page}"
            try:
                r = s.get(url, timeout=20)
                if r.status_code != 200: break
                page_ids = list(set(re.findall(r'/show/(\d{3,7})', r.text)))
                new = [i for i in page_ids if f"bdc_{i}" not in known]
                if not new and page > 1: break
                ids_found.extend(new)
                log(f"Page {page}: {len(new)} new IDs")
                sleep_r(1.0, 2.0)
            except Exception as e:
                log(f"Page {page}: {e}"); break
        log(f"Fetching {len(ids_found)} tenders...")
        for tid in ids_found[:80]:
            try:
                r = s.get(f"{cls.BASE}/show/{tid}", timeout=15)
                if r.status_code != 200: continue
                if "Liste des avis d'achat" in r.text[:2000] and len(r.text) < 20000: continue
                t = cls._parse(r.text, tid)
                if t: tenders.append(t); log(f"✓ #{tid} {t.objet[:55]}")
                sleep_r(0.5, 1.5)
            except Exception as e:
                log(f"#{tid}: {e}")
        log(f"Done: {len(tenders)}")
        return tenders

    @staticmethod
    def _parse(html, tid):
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html, "html.parser")
            full = soup.get_text(" ", strip=True)
            def cell(lbl):
                for row in soup.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    for i, c in enumerate(cells):
                        if lbl.lower() in c.get_text().lower() and i + 1 < len(cells):
                            v = cells[i+1].get_text(strip=True)
                            if v and len(v) > 1: return v[:400]
                return ""
            objet = ""
            for sel in [".consultation-title", ".objet", "h1", "h2"]:
                el = soup.select_one(sel)
                if el:
                    txt = el.get_text(strip=True)
                    if 8 < len(txt) < 600 and "accueil" not in txt.lower() and "liste des avis" not in txt.lower():
                        objet = txt; break
            if not objet:
                for lbl in ["objet du marché", "objet", "intitulé"]:
                    v = cell(lbl)
                    if v and len(v) > 8: objet = v; break
            if not objet: return None
            acheteur = (cell("maître d'ouvrage") or cell("organisme") or "").strip()
            date_pub = normalize_date(cell("publication") or "")
            date_lim = normalize_date(cell("remise") or cell("limite") or "")
            mon_raw = cell("montant") or ""
            if not mon_raw:
                m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
                if m: mon_raw = m.group(0)[:80]
            bmin, bmax, montant = extract_budget(mon_raw)
            return Tender(
                id=make_id("bdc", objet, tid),
                source="marchespublics",
                source_url=f"{MarchesPublicsScraper.BASE}/show/{tid}",
                objet=clean_text(objet, 400), description=clean_text(full, 2000),
                acheteur=acheteur[:200],
                region=detect_region(acheteur + " " + full[:400]),
                domaine=detect_secteur(objet, full[:300]),
                type_marche=detect_type(objet),
                montant=montant, budget_min=bmin, budget_max=bmax,
                date_publication=date_pub, date_limite=date_lim,
                statut="annule" if "annulé" in full.lower() else ("expire" if is_expired(date_lim) else "actif"),
                date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
        except Exception as e:
            logger.error(f"[parse bdc #{tid}] {e}")
            return None


# ══════════════════════════════════════════════════════
# SOURCE 2: annonces.lematin.ma (Journal Le Matin — GRATUIT)
# ══════════════════════════════════════════════════════
class LeMatinScraper:
    BASE = "https://annonces.lematin.ma"
    LISTING = "https://annonces.lematin.ma/annonces/appels-offres/"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        s = make_session()
        tenders = []
        def log(m):
            if log_fn: log_fn(f"[LeMatin] {m}")
        log("Scraping annonces.lematin.ma...")

        for page in range(1, 8):
            url = cls.LISTING if page == 1 else f"{cls.LISTING}?page={page}"
            try:
                r = s.get(url, timeout=20)
                if r.status_code != 200: break
                soup = BS(r.text, "html.parser")

                # Le Matin specific: articles with tender links
                items = soup.select("article, .annonce-item, .annonce, li.annonce, div.annonce")
                if not items:
                    # Try finding all links with /annonce/ pattern
                    links = soup.find_all("a", href=re.compile(r'/annonce/appels-offres/'))
                    items = [a.find_parent(["li", "div", "article"]) for a in links if a.find_parent(["li", "div", "article"])]
                    items = list({id(x): x for x in items if x}.values())

                new_this_page = 0
                for item in items[:20]:
                    link_el = item.find("a", href=re.compile(r'/annonce/'))
                    if not link_el: continue
                    href = link_el["href"]
                    if not href.startswith("http"): href = cls.BASE + href
                    title = clean_text(link_el.get_text())
                    if len(title) < 10: continue
                    tid = make_id("lematin", title, href)
                    if tid in known: continue

                    try:
                        r2 = s.get(href, timeout=15)
                        if r2.status_code != 200: continue
                        t = cls._parse_detail(r2.text, href, title)
                        if t:
                            tenders.append(t)
                            known.add(t.id)
                            new_this_page += 1
                            log(f"✓ {t.objet[:60]}")
                        sleep_r(0.8, 1.5)
                    except: continue

                if new_this_page == 0 and page > 1: break
                sleep_r(1.5, 2.5)
            except Exception as e:
                log(f"Page {page}: {e}"); break

        log(f"Total: {len(tenders)}")
        return tenders

    @staticmethod
    def _parse_detail(html, url, fallback_title=""):
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html, "html.parser")
            full = soup.get_text(" ", strip=True)

            title_el = soup.find("h1") or soup.find("h2")
            title = clean_text(title_el.get_text() if title_el else fallback_title)
            if len(title) < 10: return None

            # Extract AVIS info
            # Le Matin format: "AVIS D'APPEL D'OFFRES OUVERT N° XX/2025"
            # Acheteur is usually in first paragraph
            paras = soup.find_all("p")
            acheteur = ""
            for p in paras[:5]:
                txt = p.get_text(strip=True)
                if any(k in txt.upper() for k in ["ROYAUME DU MAROC","MINISTÈRE","DIRECTION","COMMUNE","PROVINCE","UNIVERSITÉ","CENTRE","AGENCE","SOCIÉTÉ"]):
                    if len(txt) > 10:
                        acheteur = clean_text(txt, 200); break

            # Extract budget/montant
            mon_m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD|dirham)', full, re.I)
            bmin, bmax, montant = extract_budget(mon_m.group(0) if mon_m else "")

            # Extract date limite
            date_patterns = [
                r'(?:date limite|date d\'ouverture|ouverture)[^\d]*(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})',
                r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})',
            ]
            date_lim = ""
            for pat in date_patterns:
                m = re.search(pat, full, re.I)
                if m: date_lim = normalize_date(m.group(1)); break

            # Extract date publication from URL or meta
            pub_m = re.search(r'(\d{4}-\d{2}-\d{2})', url)
            date_pub = pub_m.group(1) if pub_m else ""

            # Extract reference number
            ref_m = re.search(r'[Nn]°\s*[\d/]+/\d{4}', full)
            if ref_m and not title.startswith("AVIS"):
                pass  # already in title

            return Tender(
                id=make_id("lematin", title, url),
                source="lematin", source_url=url,
                objet=clean_text(title, 400), description=clean_text(full[:2000]),
                acheteur=acheteur,
                region=detect_region(acheteur + " " + full[:500]),
                domaine=detect_secteur(title, full[:400]),
                type_marche=detect_type(title),
                montant=montant, budget_min=bmin, budget_max=bmax,
                date_publication=date_pub, date_limite=date_lim,
                statut="expire" if is_expired(date_lim) else "actif",
                date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
        except Exception as e:
            logger.error(f"[LeMatin parse] {e}")
            return None


# ══════════════════════════════════════════════════════
# SOURCE 3: appels-offres.equipement.gov.ma (Ministère Équipement)
# ══════════════════════════════════════════════════════
class EquipementScraper:
    BASE = "http://appels-offres.equipement.gov.ma"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        s = make_session()
        tenders = []
        def log(m):
            if log_fn: log_fn(f"[Equipement] {m}")
        log("Scraping equipement.gov.ma...")

        try:
            r = s.get(cls.BASE + "/", timeout=20)
            if r.status_code != 200:
                log(f"Status {r.status_code}"); return []
            soup = BS(r.text, "html.parser")

            # Find all AO links
            ao_links = soup.find_all("a", href=re.compile(r'ao|appel|offre|consultation', re.I))
            for link in ao_links[:30]:
                href = link["href"]
                if not href.startswith("http"): href = cls.BASE + href
                title = clean_text(link.get_text())
                if len(title) < 10: continue
                tid = make_id("equipement", title, href)
                if tid in known: continue
                try:
                    r2 = s.get(href, timeout=12)
                    if r2.status_code != 200: continue
                    soup2 = BS(r2.text, "html.parser")
                    full = soup2.get_text(" ", strip=True)
                    h1 = soup2.find("h1")
                    objet = clean_text(h1.get_text() if h1 else title, 400)
                    date_m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', full)
                    date_lim = normalize_date(date_m.group(1) if date_m else "")
                    mon_m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
                    bmin, bmax, montant = extract_budget(mon_m.group(0) if mon_m else "")
                    t = Tender(
                        id=tid, source="equipement", source_url=href,
                        objet=objet, description=clean_text(full[:2000]),
                        acheteur="Ministère de l'Équipement et de l'Eau",
                        region=detect_region(full[:500]),
                        domaine=detect_secteur(objet, full[:300]),
                        type_marche=detect_type(objet),
                        montant=montant, budget_min=bmin, budget_max=bmax,
                        date_limite=date_lim,
                        statut="expire" if is_expired(date_lim) else "actif",
                        date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    )
                    tenders.append(t); known.add(tid)
                    log(f"✓ {t.objet[:55]}")
                    sleep_r(0.8, 1.5)
                except: continue
        except Exception as e:
            log(f"Error: {e}")

        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE 4: Organismes publics — pages AO directes
# ══════════════════════════════════════════════════════
PUBLIC_ORGS = [
    {
        "name": "ONEE",
        "url": "https://www.one.org.ma/FR/pages/interne.asp?esp=1&id1=3&id2=78&id3=0&t2=1&t3=0",
        "acheteur": "ONEE — Office National de l'Électricité et de l'Eau Potable",
        "region": "Maroc",
    },
    {
        "name": "ONCF",
        "url": "https://www.oncf.ma/fr/appels-offres",
        "acheteur": "ONCF — Office National des Chemins de Fer",
        "region": "Maroc",
    },
    {
        "name": "CDG",
        "url": "https://www.cdg.ma/fr/appels-offres",
        "acheteur": "CDG — Caisse de Dépôt et de Gestion",
        "region": "Rabat-Salé-Kénitra",
    },
    {
        "name": "RAM",
        "url": "https://www.royalairmaroc.com/ma-fr/Groupe/Appels-offres",
        "acheteur": "Royal Air Maroc",
        "region": "Casablanca-Settat",
    },
    {
        "name": "CréditAgricole",
        "url": "https://www.creditagricole.ma/fr/appel-offres",
        "acheteur": "Crédit Agricole du Maroc",
        "region": "Rabat-Salé-Kénitra",
    },
    {
        "name": "CHU_Marrakech",
        "url": "https://www.chumarrakech.ma/index.php/annonces/fournisseurs/appels-doffres",
        "acheteur": "CHU Mohammed VI Marrakech",
        "region": "Marrakech-Safi",
    },
    {
        "name": "LYDEC",
        "url": "https://www.lydec.ma/fr/appels-offres",
        "acheteur": "LYDEC — Eau et Électricité Casablanca",
        "region": "Casablanca-Settat",
    },
    {
        "name": "ANAM",
        "url": "https://www.anam.ma/appels-doffres/",
        "acheteur": "ANAM — Agence Nationale de l'Assurance Maladie",
        "region": "Rabat-Salé-Kénitra",
    },
    {
        "name": "Tanmia",
        "url": "https://tanmia.ma/appels-doffres/",
        "acheteur": "Tanmia.ma — ONG et Coopération internationale",
        "region": "Maroc",
    },
]

class PublicOrgsScraper:
    """Scrapes AO pages of public organizations directly"""

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        s = make_session()
        tenders = []
        def log(m):
            if log_fn: log_fn(f"[PublicOrgs] {m}")
        log(f"Scraping {len(PUBLIC_ORGS)} organismes publics...")

        for org in PUBLIC_ORGS:
            try:
                r = s.get(org["url"], timeout=15)
                if r.status_code != 200:
                    log(f"  {org['name']}: {r.status_code}"); continue

                soup = BS(r.text, "html.parser")
                full = soup.get_text(" ", strip=True)

                # Find AO items
                items = (
                    soup.select("article, .ao-item, .appel-item, .offre, li.ao") or
                    soup.find_all(["tr", "li"], class_=re.compile(r'ao|offre|appel|tender', re.I)) or
                    soup.find_all("div", class_=re.compile(r'ao|offre|appel|item', re.I))
                )

                org_new = 0
                for item in items[:20]:
                    link = item.find("a", href=True)
                    title_el = item.find(["h2", "h3", "h4", "strong", "td", "p"])
                    title = clean_text(
                        link.get_text() if link and len(link.get_text(strip=True)) > 10
                        else (title_el.get_text() if title_el else item.get_text()[:120])
                    )
                    if len(title) < 10: continue
                    # Skip nav/menu items
                    skip = ["accueil", "contact", "à propos", "connexion", "mentions légales"]
                    if any(s_kw in title.lower() for s_kw in skip): continue

                    href = ""
                    if link:
                        href = link["href"]
                        if not href.startswith("http"):
                            from urllib.parse import urljoin
                            href = urljoin(org["url"], href)

                    tid = make_id(org["name"].lower(), title, href)
                    if tid in known: continue

                    text = item.get_text(" ", strip=True)
                    date_m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', text)
                    date_lim = normalize_date(date_m.group(1) if date_m else "")
                    mon_m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', text, re.I)
                    bmin, bmax, montant = extract_budget(mon_m.group(0) if mon_m else "")

                    t = Tender(
                        id=tid,
                        source=org["name"].lower(),
                        source_url=href or org["url"],
                        objet=title[:400],
                        description=clean_text(text[:1000]),
                        acheteur=org["acheteur"],
                        region=org.get("region", "Maroc"),
                        domaine=detect_secteur(title, text),
                        type_marche=detect_type(title),
                        montant=montant, budget_min=bmin, budget_max=bmax,
                        date_limite=date_lim,
                        statut="expire" if is_expired(date_lim) else "actif",
                        date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    )
                    tenders.append(t); known.add(tid); org_new += 1
                    log(f"  ✓ [{org['name']}] {t.objet[:50]}")

                if org_new > 0:
                    log(f"  {org['name']}: {org_new} nouveaux")
                sleep_r(1.0, 2.0)
            except Exception as e:
                log(f"  {org['name']}: {e}")

        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE 5: Google Search — extraire ce qui est indexé publiquement
# (contourne les paywalls en récupérant les résultats Google)
# ══════════════════════════════════════════════════════
class GoogleSearchScraper:
    """
    Uses Google Search to find public tender pages from paywalled sites.
    The snippets in Google results often contain enough info.
    """
    QUERIES = [
        'site:lesoffres.ma appel offres maroc 2026',
        'site:marocao.com appel offres 2026',
        'site:aljady.ma appel offres maroc',
        '"appel d\'offres" maroc 2026 -site:marchespublics.gov.ma',
        '"avis appel d\'offres" maroc 2026 DH',
    ]

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        s = make_session()
        # Use a search-engine-friendly UA
        s.headers["User-Agent"] = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        tenders = []
        def log(m):
            if log_fn: log_fn(f"[GoogleSearch] {m}")

        log("Searching Google for public tender data...")
        for query in cls.QUERIES[:3]:  # Limit to avoid rate limit
            try:
                encoded = query.replace(" ", "+").replace("'", "%27")
                url = f"https://www.google.com/search?q={encoded}&num=20&hl=fr"
                r = s.get(url, timeout=15)
                if r.status_code != 200:
                    log(f"Google blocked ({r.status_code})"); continue

                soup = BS(r.text, "html.parser")
                # Extract search result snippets
                results = soup.select(".g, .tF2Cxc, [data-hveid]")
                for res in results[:15]:
                    link_el = res.select_one("a[href]")
                    if not link_el: continue
                    href = link_el.get("href", "")
                    if href.startswith("/url?q="):
                        href = href[7:].split("&")[0]
                    if not href.startswith("http"): continue

                    # Get title and snippet
                    title_el = res.select_one("h3")
                    snip_el = res.select_one(".VwiC3b, .aCOpRe, .s3v9rd, .IsZvec")
                    title = clean_text(title_el.get_text() if title_el else "")
                    snippet = clean_text(snip_el.get_text() if snip_el else "", 500)

                    if len(title) < 10: continue
                    # Check if it's a real tender
                    tender_kws = ["appel d'offres", "avis", "ao ", "consultation", "marché", "dh", "dirham", "ouvert"]
                    if not any(k in (title + snippet).lower() for k in tender_kws): continue

                    tid = make_id("google", title, href)
                    if tid in known: continue

                    date_m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', snippet)
                    date_lim = normalize_date(date_m.group(1) if date_m else "")
                    mon_m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', snippet, re.I)
                    bmin, bmax, montant = extract_budget(mon_m.group(0) if mon_m else "")

                    # Detect source
                    src = "web"
                    for domain in ["lesoffres", "marocao", "aljady", "marchesprives", "lematin"]:
                        if domain in href.lower():
                            src = domain; break

                    t = Tender(
                        id=tid, source=src, source_url=href,
                        objet=title[:400], description=snippet,
                        region=detect_region(title + " " + snippet),
                        domaine=detect_secteur(title, snippet),
                        type_marche=detect_type(title),
                        montant=montant, budget_min=bmin, budget_max=bmax,
                        date_limite=date_lim,
                        statut="expire" if is_expired(date_lim) else "actif",
                        date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    )
                    tenders.append(t); known.add(tid)
                    log(f"✓ [{src}] {t.objet[:55]}")

                sleep_r(3.0, 6.0)  # Respectful delay for Google
            except Exception as e:
                log(f"Query error: {e}"); continue

        log(f"Total from Google: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# ORCHESTRATOR
# ══════════════════════════════════════════════════════
SCRAPERS = {
    "marchespublics": MarchesPublicsScraper,
    "lematin":        LeMatinScraper,
    "equipement":     EquipementScraper,
    "publicorgs":     PublicOrgsScraper,
    "google":         GoogleSearchScraper,
}

def run_all_scrapers(known, sources=None, log_fn=None):
    """
    Run all scrapers, deduplicate, return new Tender objects.
    sources: list of source names or None (= all)
    """
    if sources is None:
        sources = list(SCRAPERS.keys())
    all_tenders = []
    seen = set(known)
    for src in sources:
        scraper = SCRAPERS.get(src)
        if not scraper: continue
        try:
            if log_fn: log_fn(f"Starting {src}...")
            results = scraper.scrape(seen, log_fn)
            for t in results:
                if t.id not in seen:
                    seen.add(t.id)
                    all_tenders.append(t)
        except Exception as e:
            logger.error(f"[{src}] {e}")
            if log_fn: log_fn(f"❌ {src}: {e}")
    return all_tenders
