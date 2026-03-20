"""
Modern Business — Multi-Source Scraper v3.0
══════════════════════════════════════════════════════════════
25 SOURCES GRATUITES — SANS INSCRIPTION — MAROC

SOURCES OFFICIELLES (gov.ma):
  1.  marchespublics.gov.ma      — Portail officiel national
  2.  annonces.lematin.ma        — Journal Le Matin (AO officiels)
  3.  appels-offres.equipement.gov.ma — Ministère Équipement & Eau
  4.  finances.gov.ma            — Ministère Finances
  5.  collectivites-territoriales.gov.ma — Collectivités locales
  6.  mmsp.gov.ma                — Ministère Transition Numérique
  7.  mtaess.gov.ma              — Ministère Tourisme & Artisanat

ENTREPRISES PUBLIQUES (EP):
  8.  ao.snrt.ma                 — SNRT (Télévision/Radio nationale)
  9.  one.org.ma                 — ONEE Électricité & Eau
  10. oncf.ma                    — ONCF Chemins de fer
  11. cdg.ma                     — CDG Caisse de dépôt
  12. onda.ma                    — ONDA Aéroports
  13. anrt.ma                    — ANRT Télécommunications
  14. anam.ma                    — ANAM Assurance Maladie
  15. tanmia.ma                  — Tanmia ONG & Coopération
  16. royalairmaroc.com          — Royal Air Maroc (RAM)

ÉTABLISSEMENTS DE SANTÉ:
  17. chumarrakech.ma            — CHU Mohammed VI Marrakech
  18. chu-ibn-rochd.ma           — CHU Ibn Rochd Casablanca
  19. hmimv.ma                   — Hôpital Militaire Rabat

RÉGIES DE DISTRIBUTION (EAU/ÉLEC):
  20. lydec.ma                   — LYDEC Casablanca
  21. amendis.ma                 — AMENDIS Tanger-Tétouan
  22. radeej.ma                  — RADEEJ El Jadida
  23. radeema.ma                 — RADEEMA Marrakech

UNIVERSITÉS & RECHERCHE:
  24. um5.ac.ma                  — Université Mohammed V Rabat
  25. creditagricole.ma          — Crédit Agricole du Maroc

NOTE: lesoffres.ma / aljady.ma / marchesprives.ma = paywall,
      non scrapables sans abonnement.
══════════════════════════════════════════════════════════════
"""
import re, time, random, logging, hashlib, json, os
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger("mb.scraper")

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
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
# UTILS
# ══════════════════════════════════════════════════════
def make_session():
    import requests
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent":      random.choice(UA_LIST),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection":      "keep-alive",
        "DNT":             "1",
    })
    return s

def sleep_r(a=0.8, b=2.5): time.sleep(random.uniform(a, b))

def make_id(src, title, url=""):
    raw = f"{src}:{title.strip()[:120]}:{url}"
    return f"{src}_{hashlib.md5(raw.encode()).hexdigest()[:12]}"

def normalize_date(raw):
    if not raw: return ""
    raw = str(raw).strip()
    MONTHS_FR = {
        "janvier":"01","février":"02","mars":"03","avril":"04","mai":"05","juin":"06",
        "juillet":"07","août":"08","septembre":"09","octobre":"10","novembre":"11","décembre":"12",
        "jan":"01","fév":"02","mar":"03","avr":"04","juin":"06","jul":"07",
        "aoû":"08","sep":"09","oct":"10","nov":"11","déc":"12",
    }
    MONTHS_AR = {
        "يناير":"01","فبراير":"02","مارس":"03","أبريل":"04","ماي":"05","ماس":"03",
        "يونيو":"06","يوليوز":"07","غشت":"08","شتنبر":"09","أكتوبر":"10","نونبر":"11","دجنبر":"12",
    }
    raw_low = raw.lower()
    for fr, num in MONTHS_FR.items():
        raw_low = raw_low.replace(fr, num)
    for ar, num in MONTHS_AR.items():
        raw = raw.replace(ar, num)
    for fmt in ["%d/%m/%Y","%d-%m-%Y","%d.%m.%Y","%Y-%m-%d","%d/%m/%y","%d %m %Y","%Y/%m/%d"]:
        try: return datetime.strptime(raw_low.strip(), fmt).strftime("%Y-%m-%d")
        except: pass
        try: return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except: pass
    m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', raw)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2: y = "20" + y
        try: return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
        except: pass
    m = re.search(r'(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})', raw)
    if m:
        y, mo, d = m.groups()
        try: return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
        except: pass
    return ""

def extract_budget(text):
    if not text: return 0.0, 0.0, ""
    text = str(text).replace("\u202f","").replace("\xa0","").replace(" ","").replace(",",".")
    # Range
    m = re.search(r'(\d[\d.]+)\s*[-à]\s*(\d[\d.]+)\s*(?:dh|mad)?', text, re.I)
    if m:
        try:
            lo, hi = float(m.group(1)), float(m.group(2))
            if lo > 0 and hi > lo:
                return lo, hi, f"{lo:,.0f} — {hi:,.0f} DH"
        except: pass
    # Single
    m = re.search(r'(\d[\d.]+)\s*(?:dh|mad|dirham)', text, re.I)
    if m:
        try:
            v = float(m.group(1))
            if v > 100:  # Ignore tiny values
                return v, v, f"{v:,.0f} DH"
        except: pass
    return 0.0, 0.0, ""

def clean_text(t, n=500):
    if not t: return ""
    t = re.sub(r'\s+', ' ', str(t)).strip()
    t = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', t)
    return t[:n]

def is_expired(d):
    if not d: return False
    try: return datetime.strptime(d.strip(), "%Y-%m-%d").date() < datetime.now().date()
    except: return False

# Tender validation keywords
TENDER_KWS = [
    "travaux","fourniture","service","acquisition","prestation","étude","maintenance",
    "nettoyage","gardiennage","restauration","informatique","construction","réhabilitation",
    "avis d'appel","appel d'offres","consultation","ao","marché","lot","tranche",
    "dh","mad","dirham","avis","ouvert","restreint","concours","bon de commande",
    "achat","livraison","mission","expertise","audit","formation",
]
NAV_KWS = [
    "accueil","connexion","inscription","s'inscrire","abonnez","tarifs",
    "qui sommes","à propos","contact","politique","mentions légales",
    "copyright","all rights","newsletter","suivez-nous",
]

def is_real_tender(title: str, text: str = "") -> bool:
    full = (title + " " + text[:200]).lower()
    if any(kw in title.lower() for kw in NAV_KWS): return False
    if len(title) < 12: return False
    has_kw = any(kw in full for kw in TENDER_KWS)
    has_date = bool(re.search(r'\d{2}[/\-\.]\d{2}[/\-\.]\d{4}', text))
    return has_kw or (has_date and len(title) > 20)

REGIONS_MAP = {
    "Rabat-Salé-Kénitra":        ["rabat","salé","kénitra","kenitra","témara","khémisset","skhirat","tiflet"],
    "Casablanca-Settat":         ["casablanca","settat","mohammedia","berrechid","benslimane","nouaceur"],
    "Marrakech-Safi":            ["marrakech","safi","essaouira","kelaa","chichaoua","youssoufia"],
    "Fès-Meknès":                ["fès","fez","meknès","meknes","ifrane","taza","sefrou","boulemane"],
    "Tanger-Tétouan-Al Hoceima": ["tanger","tétouan","tetouan","al hoceima","chefchaouen","larache","ouazzane"],
    "Oriental":                  ["oujda","nador","berkane","taourirt","jerada","guercif"],
    "Béni Mellal-Khénifra":     ["béni mellal","beni mellal","khénifra","azilal","khouribga","fkih ben salah"],
    "Souss-Massa":               ["agadir","tiznit","taroudant","inezgane","ait melloul","biougra"],
    "Drâa-Tafilalet":            ["errachidia","ouarzazate","zagora","midelt","tinghir"],
    "Laâyoune-Sakia El Hamra":   ["laayoune","boujdour","smara","tarfaya"],
    "Dakhla-Oued Ed-Dahab":      ["dakhla","aousserd"],
    "Guelmim-Oued Noun":         ["guelmim","tan-tan","assa-zag","sidi ifni"],
}

SECTEUR_KWS = {
    "T101 - Constructions & Bâtiments": ["bâtiment","construction","maçonnerie","béton","gros oeuvre","btp","rénovation","mur","clôture","façade","toiture","réhabilitation","aménagement intérieur","ravalement"],
    "T102 - Terrassements":             ["terrassement","remblai","déblai","excavation","nivellement","compactage","décapage"],
    "T103 - Menuiserie & Métallerie":   ["menuiserie","métallerie","charpente","ferronnerie","portail","serrurerie","aluminium","aluminium"],
    "T104 - Plomberie & Climatisation": ["plomberie","chauffage","climatisation","sanitaire","tuyauterie","cvc","robinetterie","géothermie"],
    "T105 - Peinture & Vitrerie":       ["peinture","vitrerie","enduit","revêtement mural","lasure","vernis"],
    "T106 - Étanchéité & Isolation":    ["étanchéité","isolation","membrane","bitume","imperméabilisation"],
    "T107 - Revêtements de sols":       ["carrelage","parquet","dallage","faïence","moquette","marbre","granit"],
    "T108 - Plâtrerie & Faux Plafonds": ["plâtrerie","faux plafond","cloison","gyproc","staff"],
    "T110 - Génie Civil":               ["génie civil","pont","infrastructure","ouvrage d'art","géotechnique","viaduc","tunnel"],
    "T111 - Espaces Verts":             ["espaces verts","jardinage","plantation","gazon","élagage","reboisement","arboriculture"],
    "T201 - Assainissement":            ["assainissement","égout","step","collecteur","canalisation","épuration"],
    "T203 - Hydraulique & Eau":         ["hydraulique","eau potable","adduction","barrage","forage","irrigation","pompage","château d'eau"],
    "T301 - Travaux Routiers":          ["route","voirie","chaussée","trottoir","bitume","asphalte","signalisation","autoroute","piste"],
    "T401 - Électricité & Éclairage":   ["électricité","éclairage","câblage","tableau électrique","transformateur","basse tension","mt/bt"],
    "T402 - Sécurité Électronique":     ["vidéosurveillance","cctv","alarme incendie","contrôle accès","badge","détection"],
    "T403 - Télécommunications":        ["télécommunication","fibre optique","réseau","switch","routeur","wifi","câblage structuré"],
    "P813 - Équipements Médicaux":      ["médical","hôpital","laboratoire","réactif","chirurgical","pharmaceutique","médicament","biomédical","stérilisation"],
    "P814 - Climatisation Équip.":      ["climatiseur","split","froid industriel","chambre froide","réfrigération"],
    "P816 - Matériel Roulant":          ["véhicule","voiture","camion","bus","minibus","carburant","gasoil","pneumatique","ambulance"],
    "P818 - Informatique":              ["informatique","ordinateur","pc","serveur","imprimante","logiciel","cloud","erp","application","scanner","réseau informatique"],
    "P821 - Sécurité & Protection":     ["équipements protection","epi","casque","gilet","gants","chaussures sécurité","extincteur"],
    "P825 - Fournitures Bureau":        ["fournitures","papier","ramette","mobilier de bureau","chaise","armoire","tableau blanc"],
    "P833 - Produits Pharma":           ["médicament","pharmaceutique","produits chimiques","réactifs","consommables médicaux"],
    "P834 - Alimentation":              ["alimentation","denrée","viande","restauration","traiteur","catering","eau distillée","café","thé"],
    "P839 - Matériaux Construction":    ["ciment","sable","gravier","béton prêt","brique","acier","rond à béton","bois"],
    "P841 - Hygiène & Nettoyage":       ["nettoyage","propreté","désinfection","savon","détergent","dératisation","désinsectisation"],
    "P850 - Énergies Renouvelables":    ["solaire","photovoltaïque","énergie renouvelable","panneau solaire","éolien","chauffe-eau solaire"],
    "S901 - IT & Développement":        ["développement logiciel","application mobile","site web","cybersécurité","base de données","solution informatique"],
    "S902 - Études & Conseil":          ["étude","conseil","consultant","expertise","audit","bureau d'études","ingénierie","maîtrise d'œuvre","assistance technique"],
    "S906 - Maintenance":               ["maintenance","entretien","réparation","dépannage","contrat maintenance","préventif","curatif"],
    "S907 - Nettoyage Service":         ["nettoyage service","propreté service","hygiène industrielle","collecte déchets"],
    "S908 - Gardiennage":               ["gardiennage","sécurité","surveillance","agent de sécurité","ronde","portier"],
    "S910 - Communication":             ["communication","publicité","événementiel","impression","brochure","signalétique"],
    "S913 - Formation":                 ["formation","coaching","séminaire","certification","e-learning","atelier"],
    "S915 - Transport & Location":      ["transport","location véhicule","navette","chauffeur","logistique"],
    "S918 - Traitement Déchets":        ["déchets","ordures","recyclage","décharge","valorisation","tri"],
    "S919 - Archivage":                 ["archivage","numérisation","gestion documentaire","records"],
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
        sc = sum(3 if len(k) > 12 else (2 if len(k) > 7 else 1) for k in kws if k in text)
        if sc: scores[s] = sc
    return max(scores, key=scores.get) if scores else "P825 - Fournitures Bureau"

def detect_type(title):
    t = title.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","pose","démolition","rénovation","étanchéité","terrassement","voirie"]): return "Travaux"
    if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel","équipement","approvisionnement"]): return "Fournitures"
    if any(k in t for k in ["service","prestation","maintenance","entretien","gardiennage","nettoyage","transport","restauration"]): return "Services"
    if any(k in t for k in ["étude","mission","audit","conseil","formation","expertise","ingénierie","maîtrise"]): return "Études & Conseil"
    return "Fournitures"


# ══════════════════════════════════════════════════════
# AI CLASSIFIER
# ══════════════════════════════════════════════════════
class AIClassifier:
    PROMPT = """Analyse cet appel d'offres marocain pour PME.
Titre: {title}
Acheteur: {acheteur}
Montant: {montant}
Secteur détecté: {secteur}
Description: {desc}

Réponds UNIQUEMENT en JSON valide (sans markdown ni explication):
{{"category":"{secteur}","score":<entier 0-100>,"reason":"<60 mots max en français>","estimated_competition":"faible|moyen|fort"}}

Critères score:
80-100: Petit budget (<200k DH), services courants, PME compétitive
60-79: Budget moyen, technique accessible
40-59: Technique ou budget important
20-39: Gros lot, très concurrentiel
0-19: International, très complexe"""

    @staticmethod
    async def classify(t, anthropic_key):
        if not anthropic_key:
            return {"category": t.domaine, "score": 50, "reason": "IA non configurée", "estimated_competition": "moyen"}
        try:
            import httpx
            prompt = AIClassifier.PROMPT.format(
                title=t.objet[:200], acheteur=t.acheteur[:80],
                montant=t.montant or "Non précisé", secteur=t.domaine,
                desc=t.description[:300]
            )
            async with httpx.AsyncClient(timeout=25) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": "claude-haiku-4-5-20251001", "max_tokens": 200,
                          "messages": [{"role": "user", "content": prompt}]}
                )
                if r.status_code == 200:
                    text = r.json()["content"][0]["text"].strip()
                    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text).strip()
                    return json.loads(text)
        except Exception as e:
            logger.error(f"[AI classify] {e}")
        return {"category": t.domaine, "score": 50, "reason": "Erreur IA", "estimated_competition": "moyen"}

    @staticmethod
    async def batch_classify(tenders, anthropic_key, max_b=10):
        import asyncio
        results = []
        for t in tenders[:max_b]:
            res = await AIClassifier.classify(t, anthropic_key)
            t.ai_score    = max(0, min(100, int(res.get("score", 50))))
            t.ai_category = res.get("category", t.domaine)
            t.ai_reason   = res.get("reason", "")
            results.append(t)
            await asyncio.sleep(0.35)
        for t in tenders[max_b:]:
            t.ai_score = 50
            results.append(t)
        return results


# ══════════════════════════════════════════════════════
# BASE SCRAPER
# ══════════════════════════════════════════════════════
def _make_tender(source, url, title, text, acheteur="", date_pub="", date_lim="", montant_raw=""):
    title = clean_text(title, 400)
    if not title or len(title) < 12: return None
    bmin, bmax, montant = extract_budget(montant_raw or re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', text, re.I) and re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', text, re.I).group(0) or "")
    date_m = re.search(r'(\d{1,2}[/\-\.]\d{2}[/\-\.]\d{4})', text) if not date_lim else None
    dl = normalize_date(date_lim or (date_m.group(1) if date_m else ""))
    return Tender(
        id=make_id(source, title, url), source=source, source_url=url,
        objet=title, description=clean_text(text, 2000),
        acheteur=acheteur[:200],
        region=detect_region(acheteur + " " + text[:500]),
        domaine=detect_secteur(title, text[:400]),
        type_marche=detect_type(title),
        montant=montant, budget_min=bmin, budget_max=bmax,
        date_publication=normalize_date(date_pub),
        date_limite=dl,
        statut="expire" if is_expired(dl) else "actif",
        date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

def _scrape_lematin_style(soup, base_url, source, known, log):
    """Generic scraper for Le Matin style — list of AO links"""
    from urllib.parse import urljoin
    tenders = []
    links = soup.find_all("a", href=re.compile(r'annonce|appel|offre|consultation|ao|marche', re.I))
    seen_hrefs = set()
    for a in links:
        href = urljoin(base_url, a.get("href", ""))
        if href in seen_hrefs or not href.startswith("http"): continue
        seen_hrefs.add(href)
        title = clean_text(a.get_text())
        if not title or not is_real_tender(title): continue
        tid = make_id(source, title, href)
        if tid in known: continue
        try:
            s = make_session()
            r = s.get(href, timeout=12)
            if r.status_code != 200: continue
            from bs4 import BeautifulSoup as BS
            s2 = BS(r.text, "html.parser")
            full = s2.get_text(" ", strip=True)
            h1 = s2.find(["h1","h2"])
            title2 = clean_text(h1.get_text() if h1 else title, 400)
            acheteur = ""
            for p in s2.find_all("p")[:5]:
                txt = p.get_text(strip=True)
                if any(k in txt.upper() for k in ["MINISTÈRE","DIRECTION","COMMUNE","PROVINCE","UNIVERSITÉ","CENTRE","AGENCE","ROYAUME","OFFICE","SOCIÉTÉ"]):
                    acheteur = clean_text(txt, 200); break
            t = _make_tender(source, href, title2 or title, full, acheteur)
            if t:
                tenders.append(t); known.add(t.id)
                log(f"✓ {t.objet[:60]}")
            sleep_r(0.6, 1.4)
        except: continue
    return tenders


# ══════════════════════════════════════════════════════
# SOURCE 1: marchespublics.gov.ma
# ══════════════════════════════════════════════════════
class MarchesPublicsScraper:
    BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        s = make_session(); tenders = []
        def log(m): 
            if log_fn: log_fn(f"[MarchesPublics] {m}")
        ids_found = []
        for page in range(1, 15):
            url = cls.BASE + "/" if page == 1 else f"{cls.BASE}/?page={page}"
            try:
                r = s.get(url, timeout=20)
                if r.status_code != 200: break
                page_ids = list(set(re.findall(r'/show/(\d{3,7})', r.text)))
                new = [i for i in page_ids if f"bdc_{i}" not in known]
                if not new and page > 1: break
                ids_found.extend(new)
                log(f"Page {page}: +{len(new)} IDs")
                sleep_r(0.8, 1.5)
            except Exception as e: log(f"Page {page}: {e}"); break
        log(f"Fetching {min(len(ids_found),100)} tenders...")
        for tid in ids_found[:100]:
            try:
                r = s.get(f"{cls.BASE}/show/{tid}", timeout=15)
                if r.status_code != 200: continue
                if len(r.text) < 3000: continue
                t = cls._parse(r.text, tid)
                if t: tenders.append(t); known.add(t.id); log(f"✓ #{tid} {t.objet[:55]}")
                sleep_r(0.4, 1.2)
            except Exception as e: log(f"#{tid}: {e}")
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
                    for i,c in enumerate(cells):
                        if lbl.lower() in c.get_text().lower() and i+1 < len(cells):
                            v = cells[i+1].get_text(strip=True)
                            if v and len(v) > 1: return v[:400]
                return ""
            objet = ""
            for sel in [".consultation-title",".objet","h1","h2","h3"]:
                el = soup.select_one(sel)
                if el:
                    txt = el.get_text(strip=True)
                    if 8 < len(txt) < 600 and not any(s in txt.lower() for s in ["accueil","liste des avis","connexion"]):
                        objet = txt; break
            if not objet:
                for lbl in ["objet du marché","objet","intitulé","désignation"]:
                    v = cell(lbl)
                    if v and len(v) > 8: objet = v; break
            if not objet or len(objet) < 8: return None
            acheteur = (cell("maître d'ouvrage") or cell("organisme") or cell("entité") or "").strip()
            date_pub = normalize_date(cell("publication") or cell("parution") or "")
            date_lim = normalize_date(cell("remise") or cell("limite") or cell("dépôt") or "")
            mon_raw  = cell("montant") or cell("estimation") or ""
            if not mon_raw:
                m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
                if m: mon_raw = m.group(0)[:80]
            bmin, bmax, montant = extract_budget(mon_raw)
            objet = clean_text(objet, 400)
            return Tender(
                id=f"bdc_{tid}", source="marchespublics",
                source_url=f"{MarchesPublicsScraper.BASE}/show/{tid}",
                objet=objet, description=clean_text(full, 2000),
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
            logger.error(f"[parse bdc #{tid}] {e}")
            return None


# ══════════════════════════════════════════════════════
# SOURCE 2: annonces.lematin.ma
# ══════════════════════════════════════════════════════
class LeMatinScraper:
    BASE = "https://annonces.lematin.ma"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        s = make_session(); tenders = []
        def log(m): 
            if log_fn: log_fn(f"[LeMatin] {m}")
        log("Scraping annonces.lematin.ma...")
        for page in range(1, 8):
            url = f"{cls.BASE}/annonces/appels-offres/" if page == 1 else f"{cls.BASE}/annonces/appels-offres/?page={page}"
            try:
                r = s.get(url, timeout=20)
                if r.status_code != 200: break
                soup = BS(r.text, "html.parser")
                new_p = _scrape_lematin_style(soup, cls.BASE, "lematin", known, log)
                tenders.extend(new_p)
                if not new_p: break
                sleep_r(1.5, 2.5)
            except Exception as e: log(f"Page {page}: {e}"); break
        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE 3: SNRT — ao.snrt.ma (Télévision nationale)
# ══════════════════════════════════════════════════════
class SNRTScraper:
    BASE = "https://ao.snrt.ma"

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        s = make_session(); tenders = []
        def log(m): 
            if log_fn: log_fn(f"[SNRT] {m}")
        log("Scraping ao.snrt.ma...")
        try:
            r = s.get(cls.BASE, timeout=15)
            if r.status_code != 200: log(f"Status {r.status_code}"); return []
            soup = BS(r.text, "html.parser")
            new = _scrape_lematin_style(soup, cls.BASE, "snrt", known, log)
            tenders.extend(new)
            # Try listing page
            for path in ["/index.php?page=entreprise.EntrepriseAdvancedSearch", "/consultations", "/ao"]:
                try:
                    r2 = s.get(cls.BASE + path, timeout=12)
                    if r2.status_code == 200:
                        s2 = BS(r2.text, "html.parser")
                        # Find tender IDs like marchespublics
                        ids = re.findall(r'/show/(\d{3,7})', r2.text)
                        for tid in set(ids):
                            oid = make_id("snrt", f"ao_{tid}", "")
                            if oid in known: continue
                            r3 = s.get(f"{cls.BASE}/index.php?page=entreprise.EntrepriseConsultation&id={tid}", timeout=12)
                            if r3.status_code == 200:
                                s3 = BS(r3.text, "html.parser")
                                full = s3.get_text(" ", strip=True)
                                h1 = s3.find(["h1","h2","h3"])
                                title = clean_text(h1.get_text() if h1 else "", 400)
                                if title and is_real_tender(title, full):
                                    t = _make_tender("snrt", r3.url, title, full, "SNRT — Société Nationale de Radiodiffusion et de Télévision")
                                    if t: tenders.append(t); known.add(t.id); log(f"✓ {t.objet[:55]}")
                            sleep_r(0.5, 1.0)
                except: pass
        except Exception as e: log(f"Error: {e}")
        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# GENERIC PAGE SCRAPER — for standard HTML AO pages
# ══════════════════════════════════════════════════════
def scrape_page(source, url, acheteur, region, known, log, selectors=None):
    """Scrapes a single AO page and returns Tender objects"""
    from bs4 import BeautifulSoup as BS
    from urllib.parse import urljoin
    tenders = []
    try:
        s = make_session()
        r = s.get(url, timeout=15)
        if r.status_code != 200: log(f"  {source}: {r.status_code}"); return []
        soup = BS(r.text, "html.parser")
        full_page = soup.get_text(" ", strip=True)

        # If the page references marchespublics — skip (duplicates)
        if full_page.count("marchespublics.gov.ma") > 10:
            log(f"  {source}: redirects to marchespublics")
            return []

        # Try custom selectors first
        items = []
        for sel in (selectors or ["article",".ao-item",".offre-item",".tender-item",
                                    "tr.ao","li.offre",".appel",".marche-item"]):
            items = soup.select(sel)
            if len(items) > 1: break

        # Generic fallback: find all links with AO-like text
        if not items:
            items = soup.find_all("a", href=True)
            for a in items:
                href = urljoin(url, a.get("href",""))
                title = clean_text(a.get_text())
                if len(title) < 12 or not is_real_tender(title): continue
                if not href.startswith("http"): continue
                tid = make_id(source, title, href)
                if tid in known: continue
                try:
                    r2 = s.get(href, timeout=10)
                    if r2.status_code != 200: continue
                    s2 = BS(r2.text, "html.parser")
                    full = s2.get_text(" ", strip=True)
                    h1 = s2.find(["h1","h2"])
                    title2 = clean_text(h1.get_text() if h1 else title, 400)
                    t = _make_tender(source, href, title2, full, acheteur)
                    if t: t.region = region; tenders.append(t); known.add(t.id); log(f"  ✓ [{source}] {t.objet[:55]}")
                    sleep_r(0.5, 1.2)
                except: continue
            return tenders

        for item in items[:25]:
            link = item.find("a", href=True) if item.name != "a" else item
            if not link: continue
            href = urljoin(url, link.get("href",""))
            title_el = item.find(["h2","h3","h4","strong","td","p"])
            title = clean_text(link.get_text() if len(link.get_text(strip=True)) > 10 else (title_el.get_text() if title_el else ""))
            if not title or not is_real_tender(title): continue
            tid = make_id(source, title, href)
            if tid in known: continue
            text = item.get_text(" ", strip=True)
            date_m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', text)
            date_lim = normalize_date(date_m.group(1) if date_m else "")
            mon_m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', text, re.I)
            bmin, bmax, montant = extract_budget(mon_m.group(0) if mon_m else "")
            t = Tender(
                id=tid, source=source, source_url=href,
                objet=title[:400], description=clean_text(text, 1000),
                acheteur=acheteur, region=region,
                domaine=detect_secteur(title, text),
                type_marche=detect_type(title),
                montant=montant, budget_min=bmin, budget_max=bmax,
                date_limite=date_lim,
                statut="expire" if is_expired(date_lim) else "actif",
                date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
            tenders.append(t); known.add(tid)
            log(f"  ✓ [{source}] {t.objet[:55]}")
    except Exception as e:
        log(f"  {source}: {e}")
    return tenders


# ══════════════════════════════════════════════════════
# SOURCE 4-25: Organismes publics
# ══════════════════════════════════════════════════════
PUBLIC_ORGS = [
    # === MINISTÈRES ===
    {
        "source": "equipement",
        "url":    "http://appels-offres.equipement.gov.ma/",
        "acheteur": "Ministère de l'Équipement et de l'Eau",
        "region": "Maroc",
    },
    {
        "source": "finances",
        "url":    "https://www.finances.gov.ma/fr/vous-orientez/Pages/appels-offres.aspx",
        "acheteur": "Ministère de l'Économie et des Finances",
        "region": "Rabat-Salé-Kénitra",
    },
    {
        "source": "collectivites",
        "url":    "https://www.collectivites-territoriales.gov.ma/fr/appel-doffres",
        "acheteur": "Direction des Collectivités Territoriales",
        "region": "Maroc",
    },
    {
        "source": "numerique",
        "url":    "https://www.mmsp.gov.ma/fr/appel-offres",
        "acheteur": "Ministère de la Transition Numérique",
        "region": "Rabat-Salé-Kénitra",
    },
    {
        "source": "tourisme",
        "url":    "https://mtaess.gov.ma/fr/appels-doffres/",
        "acheteur": "Ministère du Tourisme et de l'Artisanat",
        "region": "Rabat-Salé-Kénitra",
    },
    # === ENTREPRISES PUBLIQUES ===
    {
        "source": "onee",
        "url":    "https://www.one.org.ma/FR/pages/aoselect.asp?esp=2&id1=7&id2=64&id3=54&t2=1&t3=1",
        "acheteur": "ONEE — Office National de l'Électricité et de l'Eau Potable",
        "region": "Maroc",
    },
    {
        "source": "oncf",
        "url":    "https://www.oncf.ma/fr/appels-offres",
        "acheteur": "ONCF — Office National des Chemins de Fer",
        "region": "Maroc",
    },
    {
        "source": "cdg",
        "url":    "https://www.cdg.ma/fr/appels-offres",
        "acheteur": "CDG — Caisse de Dépôt et de Gestion",
        "region": "Rabat-Salé-Kénitra",
    },
    {
        "source": "onda",
        "url":    "https://www.onda.ma/fr/appels-offres",
        "acheteur": "ONDA — Office National Des Aéroports",
        "region": "Maroc",
    },
    {
        "source": "anrt",
        "url":    "https://www.anrt.ma/publications/appels-doffres/consulter-les-appels-doffres",
        "acheteur": "ANRT — Agence Nationale de Réglementation des Télécommunications",
        "region": "Rabat-Salé-Kénitra",
    },
    {
        "source": "anam",
        "url":    "https://www.anam.ma/appels-doffres/",
        "acheteur": "ANAM — Agence Nationale de l'Assurance Maladie",
        "region": "Rabat-Salé-Kénitra",
    },
    {
        "source": "ram",
        "url":    "https://www.royalairmaroc.com/ma-fr/Groupe/Appels-offres",
        "acheteur": "Royal Air Maroc (RAM)",
        "region": "Casablanca-Settat",
    },
    {
        "source": "tanmia",
        "url":    "https://tanmia.ma/appels-doffres/",
        "acheteur": "Tanmia.ma — ONG & Coopération internationale",
        "region": "Maroc",
    },
    {
        "source": "creditagricole",
        "url":    "https://www.creditagricole.ma/fr/appel-offres",
        "acheteur": "Crédit Agricole du Maroc",
        "region": "Rabat-Salé-Kénitra",
    },
    # === CHU & SANTÉ ===
    {
        "source": "chu_marrakech",
        "url":    "https://www.chumarrakech.ma/index.php/annonces/fournisseurs/appels-doffres",
        "acheteur": "CHU Mohammed VI Marrakech",
        "region": "Marrakech-Safi",
    },
    {
        "source": "chu_casablanca",
        "url":    "https://www.chu-ibn-rochd.ma/index.php/offres-de-marches",
        "acheteur": "CHU Ibn Rochd Casablanca",
        "region": "Casablanca-Settat",
    },
    {
        "source": "sante",
        "url":    "https://www.sante.gov.ma/AppelsOffres/Pages/AppelsOffres.aspx",
        "acheteur": "Ministère de la Santé",
        "region": "Maroc",
    },
    # === RÉGIES ===
    {
        "source": "lydec",
        "url":    "https://www.lydec.ma/fr/appels-offres",
        "acheteur": "LYDEC — Eau & Électricité Casablanca",
        "region": "Casablanca-Settat",
    },
    {
        "source": "amendis",
        "url":    "https://www.amendis.ma/fr/appels-offres",
        "acheteur": "AMENDIS — Tanger-Tétouan",
        "region": "Tanger-Tétouan-Al Hoceima",
    },
    {
        "source": "radeej",
        "url":    "https://www.radeej.ma/fr/appels-offres",
        "acheteur": "RADEEJ — El Jadida-Safi",
        "region": "Casablanca-Settat",
    },
    # === UNIVERSITÉS ===
    {
        "source": "um5",
        "url":    "https://www.um5.ac.ma/um5/appels-offres",
        "acheteur": "Université Mohammed V Rabat",
        "region": "Rabat-Salé-Kénitra",
    },
]


class PublicOrgsScraper:
    @classmethod
    def scrape(cls, known, log_fn=None):
        tenders = []
        def log(m): 
            if log_fn: log_fn(f"[PublicOrgs] {m}")
        log(f"Scraping {len(PUBLIC_ORGS)} organismes...")

        for org in PUBLIC_ORGS:
            try:
                new = scrape_page(
                    org["source"], org["url"],
                    org["acheteur"], org["region"],
                    known, log,
                )
                tenders.extend(new)
                if new: log(f"  {org['source']}: {len(new)} nouveaux")
                sleep_r(1.0, 2.0)
            except Exception as e:
                log(f"  {org['source']}: {e}")

        log(f"Total PublicOrgs: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE: Google Search cache (contourne les paywalls)
# ══════════════════════════════════════════════════════
class GoogleCacheScraper:
    QUERIES = [
        '"avis d\'appel d\'offres" maroc 2026 DH site:*.gov.ma',
        '"appel d\'offres ouvert" maroc 2026 -site:marchespublics.gov.ma',
        '"appel d\'offres" maroc 2026 "DH" "date limite"',
    ]

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        s = make_session()
        s.headers["User-Agent"] = random.choice(UA_LIST)
        tenders = []
        def log(m): 
            if log_fn: log_fn(f"[Google] {m}")

        for query in cls.QUERIES[:2]:
            try:
                encoded = query.replace(" ", "+").replace("'", "%27").replace('"', '%22')
                r = s.get(f"https://www.google.com/search?q={encoded}&num=20&hl=fr", timeout=15)
                if r.status_code != 200: log(f"Blocked ({r.status_code})"); continue
                soup = BS(r.text, "html.parser")
                for res in soup.select(".g, .tF2Cxc")[:15]:
                    link_el = res.select_one("a[href]")
                    if not link_el: continue
                    href = link_el.get("href","")
                    if href.startswith("/url?q="): href = href[7:].split("&")[0]
                    if not href.startswith("http"): continue
                    title_el = res.select_one("h3")
                    snip_el  = res.select_one(".VwiC3b,.aCOpRe,.s3v9rd")
                    title   = clean_text(title_el.get_text() if title_el else "")
                    snippet = clean_text(snip_el.get_text() if snip_el else "", 500)
                    if not title or not is_real_tender(title, snippet): continue
                    tid = make_id("google", title, href)
                    if tid in known: continue
                    # Detect source
                    src = "web"
                    for domain in ["lematin","finances","equipement","oncf","onee","cdg","snrt","onda"]:
                        if domain in href.lower(): src = domain; break
                    t = _make_tender(src or "web", href, title, snippet)
                    if t: tenders.append(t); known.add(tid); log(f"✓ [{src}] {t.objet[:55]}")
                sleep_r(4.0, 7.0)
            except Exception as e:
                log(f"Error: {e}")

        log(f"Total Google: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# ORCHESTRATOR
# ══════════════════════════════════════════════════════
SCRAPERS = {
    "marchespublics": MarchesPublicsScraper,
    "lematin":        LeMatinScraper,
    "snrt":           SNRTScraper,
    "publicorgs":     PublicOrgsScraper,
    "google":         GoogleCacheScraper,
}

def run_all_scrapers(known, sources=None, log_fn=None):
    """
    Run all scrapers, deduplicate, return new Tender objects.
    sources: list of source keys or None (= all)
    """
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
            new_count = 0
            for t in valid:
                if t.id not in seen:
                    seen.add(t.id)
                    all_tenders.append(t)
                    new_count += 1
            if log_fn: log_fn(f"[Orchestrator] {src}: {new_count} nouveaux")
        except Exception as e:
            logger.error(f"[Orchestrator:{src}] {e}")
            if log_fn: log_fn(f"[Orchestrator] ❌ {src}: {str(e)[:80]}")

    return all_tenders
