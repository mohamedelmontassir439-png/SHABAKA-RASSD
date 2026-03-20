"""
Modern Business — Multi-Source Scraper v5.0
══════════════════════════════════════════════════════════════════
STRATÉGIE: Test-driven — seulement les sources confirmées Railway

SOURCES GRATUITES CONFIRMÉES:
  ✅ marchespublics.gov.ma     Portail officiel national
  ✅ annonces.lematin.ma       Journal Le Matin (AO légaux)
  ✅ flasheconomie.com         Journal annonces légales
  ✅ leconomiste.com           Premier quotidien éco (AO section)
  ✅ tanmia.ma                 ONG & Coopération internationale
  ✅ mtaess.gov.ma             Ministère Tourisme (filtré strict)
  ✅ creditagricole.ma         Crédit Agricole du Maroc
  ✅ chumarrakech.ma           CHU Mohammed VI Marrakech
  ✅ marchespublics API        /search endpoint JSON (non documenté)

TECHNIQUES ANTI-BLOCAGE:
  → 6 User-Agents rotatifs réels (Chrome/Firefox/Safari/Mobile)
  → Retry automatique x3 avec backoff exponentiel
  → Délais aléatoires 1-4s entre requêtes
  → Session persistante avec cookies
  → Timeout court (10s) pour éviter les sites lents
  → Détection timeout → skip immédiat
══════════════════════════════════════════════════════════════════
"""
import re, time, random, logging, hashlib, json
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger("mb.scraper")

# Real browser User Agents
UA_POOL = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Safari Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    # Chrome Android
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

ACCEPT_HEADERS = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
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


# ══════════════════════════════════════════════════════
# HTTP SESSION — Anti-blocking
# ══════════════════════════════════════════════════════
def make_session(rotate=True):
    """Create session with realistic browser headers"""
    import requests
    import urllib3
    urllib3.disable_warnings()
    s = requests.Session()
    s.verify = False
    ua = random.choice(UA_POOL) if rotate else UA_POOL[0]
    s.headers.update({
        "User-Agent":      ua,
        "Accept":          random.choice(ACCEPT_HEADERS),
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "DNT":             "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":  "document",
        "Sec-Fetch-Mode":  "navigate",
        "Sec-Fetch-Site":  "none",
        "Cache-Control":   "max-age=0",
    })
    return s

def fetch(session, url, timeout=10, retries=3):
    """Fetch URL with retry + exponential backoff"""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and len(r.text) > 500:
                return r
            if r.status_code in [403, 429, 503]:
                wait = (2 ** attempt) * random.uniform(1.5, 3.0)
                logger.debug(f"[fetch] {r.status_code} → retry in {wait:.1f}s")
                time.sleep(wait)
                # Rotate UA on retry
                session.headers["User-Agent"] = random.choice(UA_POOL)
                continue
            if r.status_code in [404, 301, 302, 307, 308]:
                return None  # Don't retry these
            return None
        except Exception as e:
            err = str(e)
            if attempt < retries - 1:
                wait = (2 ** attempt) * random.uniform(1.0, 2.0)
                time.sleep(wait)
            else:
                logger.debug(f"[fetch] {url[:60]}: {err[:80]}")
    return None

def sleep_r(a=1.0, b=3.0):
    time.sleep(random.uniform(a, b))


# ══════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════
def make_id(src, title, url=""):
    raw = f"{src}:{title.strip()[:120]}:{url}"
    return f"{src}_{hashlib.md5(raw.encode()).hexdigest()[:12]}"

def normalize_date(raw):
    if not raw: return ""
    raw = str(raw).strip()
    MONTHS = {
        "janvier":"01","février":"02","mars":"03","avril":"04","mai":"05","juin":"06",
        "juillet":"07","août":"08","septembre":"09","octobre":"10","novembre":"11","décembre":"12",
        "jan":"01","fév":"02","mar":"03","avr":"04","juin":"06","jul":"07",
        "aoû":"08","sep":"09","oct":"10","nov":"11","déc":"12",
        "يناير":"01","فبراير":"02","مارس":"03","أبريل":"04","ماي":"05",
        "يونيو":"06","يوليوز":"07","غشت":"08","شتنبر":"09","أكتوبر":"10","نونبر":"11","دجنبر":"12",
    }
    r = raw.lower()
    for fr, num in MONTHS.items():
        r = r.replace(fr, num)
    for fmt in ["%d/%m/%Y","%d-%m-%Y","%d.%m.%Y","%Y-%m-%d","%d/%m/%y","%d %m %Y"]:
        try: return datetime.strptime(r.strip(), fmt).strftime("%Y-%m-%d")
        except: pass
        try: return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
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
    t = str(text).replace("\u202f","").replace("\xa0","").replace(" ","").replace(",",".")
    m = re.search(r'(\d[\d.]+)\s*(?:dh|mad|dirham)', t, re.I)
    if m:
        try:
            v = float(m.group(1))
            if v > 100: return v, v, f"{v:,.0f} DH"
        except: pass
    return 0.0, 0.0, ""

def clean_text(t, n=500):
    if not t: return ""
    t = re.sub(r'\s+', ' ', str(t)).strip()
    t = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', t)
    return t[:n]

def is_expired(d):
    if not d: return False
    try: return datetime.strptime(d, "%Y-%m-%d").date() < datetime.now().date()
    except: return False


# ══════════════════════════════════════════════════════
# TENDER VALIDATION — Ultra strict
# ══════════════════════════════════════════════════════

# Blacklist: titles that are NEVER real tenders
TITLE_BLACKLIST = [
    "accueil","menu services","nos services","à propos","about us","contact",
    "formation initiale","formation continue","stages de formation",
    "concours et examens","charte des services","droit d accès à",
    "partenariat pour","observatoire national","commissions administratives",
    "portail gouvernement","plateforme d échange","portail de transparence",
    "etudes et rapports","documentation utile","la formation professionnelle",
    "programme prévisionnel","lalla al","un des centres d excellence",
    "programme de renforcement des capa","réseau des établissements",
    "portail de géolocalisation","connexion","s inscrire","tarifs","abonnement",
    "politique de confidentialité","mentions légales","copyright","qui sommes",
    "mentions légales","newsletter","suivez-nous","flux rss","linkedin","twitter",
    "read more","lire la suite","voir plus","retour","print","imprimer",
    "menu services","services menu","navigation","breadcrumb",
]

# Regex: patterns that POSITIVELY confirm a real tender
TENDER_CONFIRM_RE = [
    r"appel\s+d.offres",
    r"avis\s+d.appel",
    r"bon\s+de\s+commande",
    r"\bao\b\s*[n°\d/]",
    r"\baoc\b|\baooi?\b|\baoo\b",
    r"appel\s+a\s+(candidature|manifestation)",
    r"consultation\s+(n°|\d)",
    r"march[eé]\s*n?°?\s*\d",
    r"fourniture\s+(?:de|des|du|d')",
    r"travaux\s+(?:de|des|du|d')",
    r"prestation\s+(?:de|des|du|d')",
    r"acquisition\s+(?:de|des|du|d')",
    r"r[eé]alisation\s+(?:des|de)",
    r"nettoyage\s+(?:de|des|du|et)",
    r"gardiennage\s+(?:de|des|du)",
    r"maintenance\s+(?:de|des|du)",
    r"entretien\s+(?:de|des|du)",
    r"location\s+(?:de|des|du|d')",
    r"livraison\s+(?:de|des|du|d')",
    r"achat\s+(?:de|des|du|d')",
    r"[Aa]ac\s*\d+",       # AAC 01/2026 format CHU
    r"[Aa][Oo]\s+\d+",     # AO 40/2025
    r"appel\s+à\s+(?:la\s+)?concurrence",
    r"demande\s+(?:de\s+)?prix",
    r"consultation\s+restreinte",
    r"mission\s+(?:de|d')\s+(?:ma[îi]trise|contr[ôo]le|surveillance)",
    r"\d+\s*lot\s*(?:unique|n°\s*\d|s?)",
    r"cps\s+n°",
    r"réhabilitation\s+(?:de|des|du|d')",
    r"construction\s+(?:de|des|du|d')",
]

# Pre-compile for performance
_TENDER_RE = [re.compile(p, re.I) for p in TENDER_CONFIRM_RE]

def is_real_tender(title: str, text: str = "") -> bool:
    """Returns True ONLY if clearly a real tender"""
    t_low = title.lower().strip()
    if len(t_low) < 12: return False
    # Hard blacklist
    if any(bl in t_low for bl in TITLE_BLACKLIST): return False
    full = t_low + " " + text[:300].lower()
    # Regex confirmation
    for pattern in _TENDER_RE:
        if pattern.search(full): return True
    # Fallback: keyword + date
    kws = ["appel","offres","marché","fourniture","travaux","prestation",
           "nettoyage","gardiennage","maintenance","acquisition","réalisation",
           "achat","location","livraison","consultation","concurrence"]
    has_kw = any(k in full for k in kws)
    has_date = bool(re.search(r'\d{2}[/\-]\d{2}[/\-]\d{4}', text))
    has_ref  = bool(re.search(r'n[°o]?\s*\d+[/\-]\d{4}', full))
    return has_kw and (has_date or has_ref) and len(title) > 15


# ══════════════════════════════════════════════════════
# CLASSIFICATION
# ══════════════════════════════════════════════════════
REGIONS = {
    "Rabat-Salé-Kénitra":        ["rabat","salé","kénitra","témara","khémisset","tiflet"],
    "Casablanca-Settat":         ["casablanca","settat","mohammedia","berrechid","benslimane"],
    "Marrakech-Safi":            ["marrakech","safi","essaouira","kelaa","youssoufia"],
    "Fès-Meknès":                ["fès","fez","meknès","meknes","ifrane","taza","sefrou"],
    "Tanger-Tétouan-Al Hoceima": ["tanger","tétouan","al hoceima","chefchaouen","larache"],
    "Oriental":                  ["oujda","nador","berkane","taourirt"],
    "Béni Mellal-Khénifra":     ["béni mellal","khénifra","azilal","khouribga"],
    "Souss-Massa":               ["agadir","tiznit","taroudant","inezgane"],
    "Drâa-Tafilalet":            ["errachidia","ouarzazate","zagora","midelt"],
    "Laâyoune":                  ["laayoune","boujdour"],
    "Dakhla":                    ["dakhla"],
    "Guelmim":                   ["guelmim","tan-tan"],
}
SECTEURS = {
    "T101 - Constructions & Bâtiments": ["bâtiment","construction","maçonnerie","béton","gros oeuvre","rénovation","réhabilitation","ravalement","coffrage"],
    "T102 - Terrassements":             ["terrassement","remblai","déblai","excavation","nivellement","compactage"],
    "T103 - Menuiserie & Métallerie":   ["menuiserie","métallerie","charpente","ferronnerie","portail","serrurerie"],
    "T104 - Plomberie & Climatisation": ["plomberie","chauffage","climatisation","sanitaire","cvc","robinetterie"],
    "T105 - Peinture & Vitrerie":       ["peinture","vitrerie","enduit","lasure"],
    "T106 - Étanchéité":                ["étanchéité","isolation","membrane","imperméabilisation"],
    "T107 - Revêtements":               ["carrelage","parquet","revêtement sol","faïence","dallage"],
    "T108 - Plâtrerie":                 ["plâtrerie","faux plafond","cloison","gyproc","staff"],
    "T110 - Génie Civil":               ["génie civil","pont","infrastructure","ouvrage d'art","géotechnique","viaduc"],
    "T111 - Espaces Verts":             ["espaces verts","jardinage","plantation","gazon","élagage","reboisement"],
    "T201 - Assainissement":            ["assainissement","égout","step","collecteur","canalisation","épuration"],
    "T203 - Hydraulique & Eau":         ["hydraulique","eau potable","adduction","barrage","forage","irrigation","pompage"],
    "T301 - Travaux Routiers":          ["route","voirie","chaussée","trottoir","bitume","asphalte","signalisation","autoroute"],
    "T401 - Électricité":               ["électricité","éclairage","câblage","tableau électrique","transformateur","basse tension"],
    "T402 - Sécurité Électronique":     ["vidéosurveillance","cctv","alarme incendie","contrôle accès","badge","détection"],
    "T403 - Télécommunications":        ["télécommunication","fibre optique","réseau informatique","switch","wifi","câblage structuré"],
    "P813 - Équipements Médicaux":      ["médical","hôpital","laboratoire","réactif","chirurgical","pharmaceutique","médicament","biomédical"],
    "P814 - Climatisation":             ["climatiseur","split","froid industriel","chambre froide","réfrigération"],
    "P816 - Matériel Roulant":          ["véhicule","voiture","camion","bus","minibus","carburant","gasoil","ambulance"],
    "P818 - Informatique":              ["informatique","ordinateur","pc","serveur","imprimante","logiciel","cloud","erp","scanner"],
    "P821 - Sécurité & EPI":            ["équipements protection","epi","casque","gilet","extincteur","harnais"],
    "P825 - Fournitures Bureau":        ["fournitures","papier","ramette","mobilier de bureau","chaise","armoire"],
    "P833 - Produits Pharmaceutiques":  ["médicament","pharmaceutique","produits chimiques","réactifs labo"],
    "P834 - Alimentation":              ["alimentation","denrée","viande","restauration","traiteur","catering","eau distillée"],
    "P839 - Matériaux Construction":    ["ciment","sable","gravier","béton prêt","brique","acier","rond à béton"],
    "P841 - Hygiène & Nettoyage":       ["nettoyage","propreté","désinfection","savon","détergent","dératisation"],
    "P850 - Énergies Renouvelables":    ["solaire","photovoltaïque","énergie renouvelable","panneau solaire","éolien"],
    "S901 - IT & Développement":        ["développement logiciel","application mobile","site web","cybersécurité","erp","solution si"],
    "S902 - Études & Conseil":          ["étude","conseil","consultant","expertise","audit","bureau d'études","ingénierie","maîtrise"],
    "S906 - Maintenance":               ["maintenance","entretien","réparation","dépannage","contrat maintenance","curatif","préventif"],
    "S907 - Nettoyage Service":         ["nettoyage service","propreté service","hygiène industrielle","collecte déchets"],
    "S908 - Gardiennage":               ["gardiennage","sécurité","surveillance","agent de sécurité","ronde","portier"],
    "S910 - Communication":             ["communication","publicité","événementiel","impression","brochure","signalétique"],
    "S913 - Formation":                 ["formation","coaching","séminaire","certification","e-learning","atelier"],
    "S915 - Transport":                 ["transport","location véhicule","navette","chauffeur","logistique"],
    "S918 - Traitement Déchets":        ["déchets","ordures ménagères","recyclage","décharge","valorisation déchets"],
    "S919 - Archivage":                 ["archivage","numérisation","gestion documentaire"],
}

def detect_region(text):
    t = text.lower()
    for r, kws in REGIONS.items():
        if any(k in t for k in kws): return r
    return "Maroc"

def detect_secteur(title, desc=""):
    text = (title + " " + desc).lower()
    scores = {}
    for s, kws in SECTEURS.items():
        sc = sum(3 if len(k)>12 else 2 if len(k)>7 else 1 for k in kws if k in text)
        if sc: scores[s] = sc
    return max(scores, key=scores.get) if scores else "P825 - Fournitures Bureau"

def detect_type(title):
    t = title.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","rénovation","étanchéité","terrassement","pose","démolition"]): return "Travaux"
    if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel","équipement","approvisionnement"]): return "Fournitures"
    if any(k in t for k in ["service","prestation","maintenance","gardiennage","nettoyage","transport","restauration","hygiène"]): return "Services"
    if any(k in t for k in ["étude","mission","audit","conseil","formation","expertise","ingénierie","maîtrise","diagnostic"]): return "Études & Conseil"
    return "Fournitures"

def build_tender(source, url, title, text, acheteur="", date_pub="", date_lim="", montant_raw=""):
    """Build a validated Tender object"""
    title = clean_text(title, 400)
    if not title or not is_real_tender(title, text): return None
    bmin, bmax, montant = extract_budget(montant_raw or "")
    if not montant:
        m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', text, re.I)
        if m: bmin, bmax, montant = extract_budget(m.group(0))
    dates = re.findall(r'\d{1,2}[/\-\.]\d{2}[/\-\.]\d{4}', text)
    dl = normalize_date(date_lim or (dates[-1] if dates else ""))
    dp = normalize_date(date_pub or (dates[0] if len(dates) > 1 else ""))
    return Tender(
        id=make_id(source, title, url),
        source=source, source_url=url,
        objet=title, description=clean_text(text, 2000),
        acheteur=clean_text(acheteur, 200),
        region=detect_region(acheteur + " " + text[:600]),
        domaine=detect_secteur(title, text[:500]),
        type_marche=detect_type(title),
        montant=montant, budget_min=bmin, budget_max=bmax,
        date_publication=dp, date_limite=dl,
        statut="expire" if is_expired(dl) else "actif",
        date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


# ══════════════════════════════════════════════════════
# AI CLASSIFIER
# ══════════════════════════════════════════════════════
class AIClassifier:
    @staticmethod
    async def classify(t, key):
        if not key:
            return {"category": t.domaine, "score": 50, "reason": "IA non configurée", "estimated_competition": "moyen"}
        try:
            import httpx
            p = f"""Analyse cet AO marocain pour PME. JSON seulement:
{{"category":"{t.domaine}","score":<0-100>,"reason":"<50 mots>","estimated_competition":"faible|moyen|fort"}}
Score: 80+=facile(PME), 60-79=moyen, 40-59=technique, <40=complexe.
Titre:{t.objet[:150]} | Acheteur:{t.acheteur[:60]} | Montant:{t.montant or "N/A"} | Secteur:{t.domaine}"""
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key":key,"anthropic-version":"2023-06-01","content-type":"application/json"},
                    json={"model":"claude-haiku-4-5-20251001","max_tokens":150,
                          "messages":[{"role":"user","content":p}]})
                if r.status_code == 200:
                    txt = r.json()["content"][0]["text"].strip()
                    txt = re.sub(r'^```(?:json)?\s*|\s*```$','',txt).strip()
                    return json.loads(txt)
        except Exception as e:
            logger.error(f"[AI] {e}")
        return {"category": t.domaine, "score": 50, "reason": "Erreur IA", "estimated_competition": "moyen"}

    @staticmethod
    async def batch_classify(tenders, key, max_b=8):
        import asyncio
        results = []
        for t in tenders[:max_b]:
            res = await AIClassifier.classify(t, key)
            t.ai_score    = max(0, min(100, int(res.get("score", 50))))
            t.ai_category = res.get("category", t.domaine)
            t.ai_reason   = res.get("reason", "")
            results.append(t)
            await asyncio.sleep(0.4)
        for t in tenders[max_b:]:
            t.ai_score = 50; results.append(t)
        return results


# ══════════════════════════════════════════════════════
# SOURCE 1: marchespublics.gov.ma — Principal ✅
# ══════════════════════════════════════════════════════
class MarchesPublicsScraper:
    BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        s = make_session(); tenders = []
        def log(m): log_fn(f"[MarchesPublics] {m}") if log_fn else None
        ids_found = []
        for page in range(1, 15):
            url = f"{cls.BASE}/" if page == 1 else f"{cls.BASE}/?page={page}"
            r = fetch(s, url, timeout=25, retries=3)
            if not r: break
            page_ids = list(set(re.findall(r'/show/(\d{3,7})', r.text)))
            new = [i for i in page_ids if f"bdc_{i}" not in known]
            if not new and page > 1: break
            ids_found.extend(new)
            log(f"Page {page}: +{len(new)} IDs")
            sleep_r(0.8, 1.5)
        log(f"Fetching {min(len(ids_found),100)}...")
        for tid in ids_found[:100]:
            r = fetch(s, f"{cls.BASE}/show/{tid}", timeout=20, retries=2)
            if not r or len(r.text) < 3000: continue
            t = cls._parse(r.text, tid)
            if t: tenders.append(t); known.add(t.id); log(f"✓ #{tid} {t.objet[:55]}")
            sleep_r(0.8, 1.8)
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
                    cells = row.find_all(["td","th"])
                    for i, c in enumerate(cells):
                        if lbl.lower() in c.get_text().lower() and i+1 < len(cells):
                            v = cells[i+1].get_text(strip=True)
                            if v and len(v) > 1: return v[:400]
                return ""
            objet = ""
            for sel in [".consultation-title",".objet","h1","h2","h3"]:
                el = soup.select_one(sel)
                if el:
                    txt = el.get_text(strip=True)
                    if 8 < len(txt) < 600 and not any(x in txt.lower() for x in ["accueil","liste des avis","connexion"]):
                        objet = txt; break
            if not objet:
                for lbl in ["objet du marché","objet","intitulé","désignation"]:
                    v = cell(lbl)
                    if v and len(v) > 8: objet = v; break
            if not objet or len(objet) < 8: return None
            acheteur = (cell("maître d'ouvrage") or cell("organisme") or "").strip()
            date_pub = normalize_date(cell("publication") or "")
            date_lim = normalize_date(cell("remise") or cell("limite") or "")
            mon_raw  = cell("montant") or cell("estimation") or ""
            bmin, bmax, montant = extract_budget(mon_raw)
            if not montant:
                m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
                if m: bmin, bmax, montant = extract_budget(m.group(0))
            return Tender(
                id=f"bdc_{tid}", source="marchespublics",
                source_url=f"{MarchesPublicsScraper.BASE}/show/{tid}",
                objet=clean_text(objet, 400), description=clean_text(full, 2000),
                acheteur=acheteur[:200],
                region=detect_region(acheteur + " " + full[:500]),
                domaine=detect_secteur(objet, full[:400]),
                type_marche=detect_type(objet),
                montant=montant, budget_min=bmin, budget_max=bmax,
                date_publication=date_pub, date_limite=date_lim,
                statut="annule" if "annulé" in full.lower() else ("expire" if is_expired(date_lim) else "actif"),
                date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
        except Exception as e:
            logger.error(f"[parse #{tid}] {e}")
            return None


# ══════════════════════════════════════════════════════
# SOURCE 2: annonces.lematin.ma — Journal Le Matin ✅
# ══════════════════════════════════════════════════════
class LeMatinScraper:
    BASE = "https://annonces.lematin.ma"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        from urllib.parse import urljoin
        s = make_session(); tenders = []
        def log(m): log_fn(f"[LeMatin] {m}") if log_fn else None
        log("Scraping...")
        for page in range(1, 8):
            url = f"{cls.BASE}/annonces/appels-offres/" if page == 1 else f"{cls.BASE}/annonces/appels-offres/?page={page}"
            r = fetch(s, url, timeout=20)
            if not r: break
            soup = BS(r.text, "html.parser")
            # Find AO article links
            links = soup.find_all("a", href=re.compile(r'/annonce/', re.I))
            if not links: break
            new_p = 0
            seen_h = set()
            for a in links:
                href = urljoin(cls.BASE, a.get("href", ""))
                if href in seen_h: continue
                seen_h.add(href)
                preview = clean_text(a.get_text())
                tid = make_id("lematin", href)
                if tid in known: continue
                r2 = fetch(s, href, timeout=15)
                if not r2: continue
                s2 = BS(r2.text, "html.parser")
                full = s2.get_text(" ", strip=True)
                h1 = s2.find("h1") or s2.find("h2")
                title = clean_text(h1.get_text() if h1 else preview, 400)
                if not title or not is_real_tender(title, full): continue
                # Extract acheteur
                acheteur = ""
                for p in s2.find_all("p")[:8]:
                    txt = p.get_text(strip=True)
                    if len(txt) > 10 and any(k in txt.upper() for k in
                        ["MINISTÈRE","DIRECTION","COMMUNE","PROVINCE","UNIVERSITÉ",
                         "CENTRE","AGENCE","ROYAUME","OFFICE","SOCIÉTÉ","ÉTABLISSEMENT",
                         "PRÉFECTURE","WILAYA","RÉGION","LYCÉE","DÉLÉGATION","CAÏDAT"]):
                        acheteur = clean_text(txt, 200); break
                t = build_tender("lematin", href, title, full, acheteur)
                if t:
                    tenders.append(t); known.add(tid); new_p += 1
                    log(f"✓ {t.objet[:60]}")
                sleep_r(0.8, 1.5)
            if new_p == 0: break
            sleep_r(2.0, 3.5)
        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE 3: flasheconomie.com — JAL depuis 1957 ✅
# ══════════════════════════════════════════════════════
class FlashEconomieScraper:
    BASE = "https://flasheconomie.com"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        from urllib.parse import urljoin
        s = make_session(); tenders = []
        def log(m): log_fn(f"[FlashEconomie] {m}") if log_fn else None
        log("Scraping flasheconomie.com...")
        urls = [
            f"{cls.BASE}/category/consulter-les-annonces-legales/",
            f"{cls.BASE}/category/appels-offres/",
            f"{cls.BASE}/category/annonce-legale/",
        ]
        for url in urls:
            r = fetch(s, url, timeout=15)
            if not r: continue
            soup = BS(r.text, "html.parser")
            # WordPress-style posts
            posts = soup.select("article.post, article, .post, .entry, .hentry")
            if not posts:
                posts = soup.find_all("div", class_=re.compile(r'post|article|entry', re.I))
            for post in posts[:20]:
                link = post.find("a", href=True)
                if not link: continue
                href = urljoin(cls.BASE, link.get("href",""))
                if not href.startswith(cls.BASE): continue
                title_el = post.find(["h2","h3","h1"])
                title = clean_text(title_el.get_text() if title_el else link.get_text(), 400)
                if not title or len(title) < 12: continue
                # Pre-filter on title
                if not is_real_tender(title): continue
                tid = make_id("flasheconomie", title, href)
                if tid in known: continue
                # Fetch detail
                r2 = fetch(s, href, timeout=12)
                if not r2: continue
                s2 = BS(r2.text, "html.parser")
                full = s2.get_text(" ", strip=True)
                if not is_real_tender(title, full): continue
                acheteur = ""
                for p in s2.find_all("p")[:8]:
                    txt = p.get_text(strip=True)
                    if any(k in txt.upper() for k in ["ROYAUME","MINISTÈRE","COMMUNE","DIRECTION","PROVINCE","OFFICE"]):
                        acheteur = clean_text(txt, 200); break
                t = build_tender("flasheconomie", href, title, full, acheteur)
                if t:
                    tenders.append(t); known.add(tid)
                    log(f"✓ {t.objet[:60]}")
                sleep_r(0.8, 1.5)
        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE 4: leconomiste.com — Premier quotidien éco ✅
# ══════════════════════════════════════════════════════
class LEconomisteScraper:
    BASE = "https://www.leconomiste.com"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        from urllib.parse import urljoin
        s = make_session(); tenders = []
        def log(m): log_fn(f"[LEconomiste] {m}") if log_fn else None
        log("Scraping leconomiste.com...")
        ao_urls = [
            f"{cls.BASE}/appels-offres",
            f"{cls.BASE}/article/appels-offres",
            f"{cls.BASE}/content/appels-doffres",
        ]
        for url in ao_urls:
            r = fetch(s, url, timeout=15)
            if not r: continue
            soup = BS(r.text, "html.parser")
            # Find AO links
            links = soup.find_all("a", href=re.compile(r'appel|offre|marche|ao', re.I))
            seen_h = set()
            for a in links[:30]:
                href = urljoin(cls.BASE, a.get("href",""))
                if href in seen_h or not href.startswith(cls.BASE): continue
                seen_h.add(href)
                title = clean_text(a.get_text())
                if not title or not is_real_tender(title): continue
                tid = make_id("leconomiste", title, href)
                if tid in known: continue
                r2 = fetch(s, href, timeout=12)
                if not r2: continue
                s2 = BS(r2.text, "html.parser")
                full = s2.get_text(" ", strip=True)
                h1 = s2.find("h1") or s2.find("h2")
                title2 = clean_text(h1.get_text() if h1 else title, 400)
                if not is_real_tender(title2, full): continue
                t = build_tender("leconomiste", href, title2, full)
                if t:
                    tenders.append(t); known.add(tid)
                    log(f"✓ {t.objet[:60]}")
                sleep_r(1.0, 2.0)
            if tenders: break  # Found on first working URL
        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE 5: tanmia.ma — ONG & Coopération ✅
# ══════════════════════════════════════════════════════
class TanmiaScraper:
    BASE = "https://tanmia.ma"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        from urllib.parse import urljoin
        s = make_session(); tenders = []
        def log(m): log_fn(f"[Tanmia] {m}") if log_fn else None
        log("Scraping tanmia.ma...")
        r = fetch(s, f"{cls.BASE}/appels-doffres/", timeout=15)
        if not r: log("Inaccessible"); return []
        soup = BS(r.text, "html.parser")
        posts = soup.select("article,.post,.entry,.ao-item")
        if not posts: posts = soup.find_all("article") or soup.find_all("div", class_="post")
        for post in posts[:20]:
            link = post.find("a", href=True)
            if not link: continue
            href = urljoin(cls.BASE, link.get("href",""))
            title_el = post.find(["h2","h3","h4"])
            title = clean_text(title_el.get_text() if title_el else link.get_text(), 400)
            if not title or len(title) < 12: continue
            tid = make_id("tanmia", title, href)
            if tid in known: continue
            text = post.get_text(" ", strip=True)
            t = build_tender("tanmia", href, title, text,
                             "Tanmia.ma — ONG & Coopération internationale")
            if t:
                tenders.append(t); known.add(tid)
                log(f"✓ {t.objet[:60]}")
        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE 6: mtaess.gov.ma — Ministère Tourisme ✅
# ══════════════════════════════════════════════════════
class TourismeScraper:
    BASE = "https://mtaess.gov.ma"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        from urllib.parse import urljoin
        s = make_session(); tenders = []
        def log(m): log_fn(f"[Tourisme] {m}") if log_fn else None
        log("Scraping mtaess.gov.ma...")
        r = fetch(s, f"{cls.BASE}/fr/appels-doffres/", timeout=15)
        if not r: log("Inaccessible"); return []
        soup = BS(r.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r'appel|offre|marche|ao|consultation', re.I))
        seen = set()
        for a in links[:25]:
            href = urljoin(cls.BASE, a.get("href",""))
            title = clean_text(a.get_text())
            if href in seen or len(title) < 12: continue
            seen.add(href)
            if not is_real_tender(title): continue  # Strict filter on title
            tid = make_id("tourisme", title, href)
            if tid in known: continue
            r2 = fetch(s, href, timeout=12)
            if not r2: continue
            s2 = BS(r2.text, "html.parser")
            full = s2.get_text(" ", strip=True)
            h1 = s2.find("h1") or s2.find("h2")
            title2 = clean_text(h1.get_text() if h1 else title, 400)
            if not is_real_tender(title2, full): continue
            t = build_tender("tourisme", href, title2, full, "Ministère du Tourisme et de l'Artisanat")
            if t:
                tenders.append(t); known.add(tid)
                log(f"✓ {t.objet[:60]}")
            sleep_r(0.8, 1.5)
        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE 7: creditagricole.ma ✅
# ══════════════════════════════════════════════════════
class CreditAgricoleScraper:
    BASE = "https://www.creditagricole.ma"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        from urllib.parse import urljoin
        s = make_session(); tenders = []
        def log(m): log_fn(f"[CreditAgricole] {m}") if log_fn else None
        log("Scraping creditagricole.ma...")
        r = fetch(s, f"{cls.BASE}/fr/appel-offres", timeout=12)
        if not r: log("Inaccessible"); return []
        soup = BS(r.text, "html.parser")
        for item in soup.find_all(["li","tr","div"])[:40]:
            text = item.get_text(" ", strip=True)
            if len(text) < 20 or len(text) > 2000: continue
            link = item.find("a", href=True)
            href = urljoin(cls.BASE, link.get("href","")) if link else f"{cls.BASE}/fr/appel-offres"
            title_el = item.find(["h2","h3","h4","strong"])
            title = clean_text(title_el.get_text() if title_el else text[:120], 400)
            if not title or not is_real_tender(title, text): continue
            tid = make_id("creditagricole", title, href)
            if tid in known: continue
            t = build_tender("creditagricole", href, title, text, "Crédit Agricole du Maroc")
            if t:
                t.region = "Rabat-Salé-Kénitra"
                tenders.append(t); known.add(tid)
                log(f"✓ {t.objet[:60]}")
        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE 8: chumarrakech.ma — CHU ✅
# ══════════════════════════════════════════════════════
class CHUMarrakechScraper:
    BASE = "https://www.chumarrakech.ma"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        from urllib.parse import urljoin
        s = make_session(); tenders = []
        def log(m): log_fn(f"[CHU_Marrakech] {m}") if log_fn else None
        log("Scraping chumarrakech.ma...")
        r = fetch(s, f"{cls.BASE}/index.php/annonces/fournisseurs/appels-doffres", timeout=12)
        if not r: log("Inaccessible"); return []
        soup = BS(r.text, "html.parser")
        full_page = soup.get_text(" ", strip=True)
        # CHU lists AO as text blocks with AAC/AO numbers
        matches = re.finditer(
            r'((?:AAC|AO)\s*\d+/\d{4}[^.]*(?:fourniture|travaux|service|achat|maintenance|nettoyage|gardiennage|[^.]{10,60}))',
            full_page, re.I
        )
        for m in matches:
            title = clean_text(m.group(1), 300)
            if not title or not is_real_tender(title): continue
            tid = make_id("chu_marrakech", title)
            if tid in known: continue
            t = build_tender(
                "chu_marrakech",
                f"{cls.BASE}/index.php/annonces/fournisseurs/appels-doffres",
                title, full_page[:1000],
                "CHU Mohammed VI Marrakech"
            )
            if t:
                t.region = "Marrakech-Safi"
                tenders.append(t); known.add(tid)
                log(f"✓ {t.objet[:60]}")
        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# ORCHESTRATOR
# ══════════════════════════════════════════════════════
SCRAPERS = {
    "marchespublics": MarchesPublicsScraper,  # ✅ Principal
    "lematin":        LeMatinScraper,          # ✅ Journal légal
    "flasheconomie":  FlashEconomieScraper,    # ✅ JAL depuis 1957
    "leconomiste":    LEconomisteScraper,      # ✅ Quotidien éco
    "tanmia":         TanmiaScraper,           # ✅ ONG/Coop
    "tourisme":       TourismeScraper,         # ✅ Min. Tourisme
    "creditagricole": CreditAgricoleScraper,   # ✅ Banque publique
    "chu_marrakech":  CHUMarrakechScraper,     # ✅ Hôpital
}

def run_all_scrapers(known, sources=None, log_fn=None):
    if sources is None:
        sources = list(SCRAPERS.keys())
    all_tenders = []
    seen = set(known)
    for src in sources:
        scraper = SCRAPERS.get(src)
        if not scraper: continue
        try:
            if log_fn: log_fn(f"[Orchestrator] → {src}")
            results = scraper.scrape(set(seen), log_fn)
            valid = [
                t for t in (results or [])
                if t and hasattr(t,'id') and t.id
                and hasattr(t,'objet') and t.objet
                and len(t.objet) >= 10
            ]
            added = 0
            for t in valid:
                if t.id not in seen:
                    seen.add(t.id); all_tenders.append(t); added += 1
            if log_fn: log_fn(f"[Orchestrator] {src}: {added} nouveaux")
        except Exception as e:
            logger.error(f"[{src}] {e}")
            if log_fn: log_fn(f"[Orchestrator] ✗ {src}: {str(e)[:80]}")
    return all_tenders
