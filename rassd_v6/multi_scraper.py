"""
Modern Business — Multi-Source Scraper v1.0
Sources: marchespublics.gov.ma + marocao.com + lesoffres.ma + aljady.ma + marchesprives.ma
Features: rotating UA, AI classification, dedup, date normalization
"""
import re, time, random, logging, hashlib, json, os
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger("mb.scraper")

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
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
    })
    return s

def sleep_r(a=1.0, b=2.5): time.sleep(random.uniform(a, b))
def make_id(src, title, url=""): return f"{src}_{hashlib.md5(f'{src}:{title}:{url}'.encode()).hexdigest()[:12]}"

def normalize_date(raw):
    if not raw: return ""
    raw = raw.strip()
    MONTHS_FR = {"janvier":"01","février":"02","mars":"03","avril":"04","mai":"05","juin":"06",
                 "juillet":"07","août":"08","septembre":"09","octobre":"10","novembre":"11","décembre":"12"}
    for fr, num in MONTHS_FR.items():
        raw = raw.lower().replace(fr, num)
    for fmt in ["%d/%m/%Y","%d-%m-%Y","%d.%m.%Y","%Y-%m-%d","%d/%m/%y","%d-%m-%y"]:
        try: return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except: pass
    m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', raw)
    if m:
        d,mo,y = m.groups()
        if len(y)==2: y="20"+y
        try: return datetime(int(y),int(mo),int(d)).strftime("%Y-%m-%d")
        except: pass
    return ""

def extract_budget(text):
    if not text: return 0.0,0.0,""
    text = text.replace(" ","").replace(",",".")
    m = re.search(r'(\d[\d.]+)\s*(?:dh|mad|dirham)', text, re.I)
    if m:
        try: v=float(m.group(1)); return v,v,f"{v:,.0f} DH"
        except: pass
    return 0.0,0.0,text[:60]

def clean_text(t, n=500):
    if not t: return ""
    return re.sub(r'\s+',' ',t).strip()[:n]

def is_expired(d):
    if not d: return False
    try: return datetime.strptime(d,"%Y-%m-%d").date() < datetime.now().date()
    except: return False

REGIONS_MAP = {
    "Rabat-Salé-Kénitra":["rabat","salé","kénitra","kenitra","témara"],
    "Casablanca-Settat":["casablanca","settat","mohammedia","berrechid"],
    "Marrakech-Safi":["marrakech","safi","essaouira"],
    "Fès-Meknès":["fès","fez","meknès","meknes","ifrane","taza"],
    "Tanger-Tétouan-Al Hoceima":["tanger","tétouan","al hoceima","chefchaouen"],
    "Oriental":["oujda","nador","berkane"],
    "Béni Mellal-Khénifra":["béni mellal","khénifra","azilal","khouribga"],
    "Souss-Massa":["agadir","tiznit","taroudant"],
    "Drâa-Tafilalet":["errachidia","ouarzazate","zagora"],
}

def detect_region(text):
    t = text.lower()
    for r,kws in REGIONS_MAP.items():
        if any(k in t for k in kws): return r
    return "Maroc"

SECTEUR_KWS = {
    "T101 - Constructions & Bâtiments":["bâtiment","construction","maçonnerie","béton","gros oeuvre","btp","rénovation"],
    "T110 - Génie Civil":["génie civil","pont","infrastructure","ouvrage","géotechnique"],
    "T201 - Assainissement":["assainissement","égout","step","collecteur","canalisation"],
    "T203 - Hydraulique":["hydraulique","eau potable","adduction","barrage","forage","irrigation"],
    "T301 - Travaux Routiers":["route","voirie","chaussée","trottoir","bitume","asphalte"],
    "T401 - Électricité":["électricité","éclairage","câblage","tableau électrique"],
    "T402 - Sécurité Électronique":["télésurveillance","alarme","incendie","caméra","cctv"],
    "T403 - Télécommunications":["télécommunication","fibre optique","réseau","switch","routeur"],
    "P816 - Matériel Roulant":["véhicule","voiture","camion","bus","carburant","gasoil"],
    "P818 - Informatique":["informatique","ordinateur","pc","serveur","imprimante","logiciel","cloud"],
    "P813 - Équipements Médicaux":["médical","hôpital","laboratoire","réactif","chirurgical"],
    "P825 - Fournitures Bureau":["fournitures","papier","ramette","mobilier","bureau"],
    "P834 - Alimentation":["alimentation","denrée","viande","restauration","traiteur"],
    "P841 - Hygiène & Nettoyage":["nettoyage","propreté","désinfection","savon","détergent"],
    "P850 - Énergies Renouvelables":["solaire","photovoltaïque","énergie renouvelable"],
    "S901 - IT & Développement":["développement","application","site web","base de données","cybersécurité"],
    "S902 - Études & Conseil":["étude","conseil","consultant","expertise","audit","bureau d'études"],
    "S906 - Maintenance":["maintenance","entretien","réparation","dépannage"],
    "S907 - Nettoyage Service":["nettoyage service","propreté service","dératisation"],
    "S908 - Gardiennage":["gardiennage","sécurité","surveillance","agent"],
    "S913 - Formation":["formation","coaching","séminaire","certification"],
}

def detect_secteur(title, desc=""):
    text = (title+" "+desc).lower()
    scores = {}
    for s,kws in SECTEUR_KWS.items():
        sc = sum(2 if len(k)>9 else 1 for k in kws if k in text)
        if sc: scores[s]=sc
    return max(scores,key=scores.get) if scores else "P825 - Fournitures Bureau"

def detect_type(title):
    t = title.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","pose","démolition"]): return "Travaux"
    if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel"]): return "Fournitures"
    if any(k in t for k in ["service","prestation","maintenance","gardiennage","nettoyage"]): return "Services"
    if any(k in t for k in ["étude","mission","audit","conseil","formation"]): return "Études & Conseil"
    return "Fournitures"


class AIClassifier:
    PROMPT = """Analyse cet appel d'offres marocain pour PME.
Titre: {title}
Acheteur: {acheteur}
Montant: {montant}
Secteur: {secteur}
Description: {desc}

Réponds UNIQUEMENT en JSON valide (sans markdown):
{{"category":"{secteur}","score":<0-100 facilité PME>,"reason":"<80 mots max>","estimated_competition":"faible|moyen|fort"}}

Score: 80-100=facile(petit budget,services), 60-79=moyen, 40-59=technique, 20-39=gros lot, 0-19=très complexe"""

    @staticmethod
    async def classify(t, anthropic_key):
        if not anthropic_key:
            return {"category":t.domaine,"score":50,"reason":"IA non configurée","estimated_competition":"moyen"}
        try:
            import httpx
            prompt = AIClassifier.PROMPT.format(
                title=t.objet[:200], acheteur=t.acheteur[:80],
                montant=t.montant or "Non précisé", secteur=t.domaine,
                desc=t.description[:300]
            )
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key":anthropic_key,"anthropic-version":"2023-06-01","content-type":"application/json"},
                    json={"model":"claude-haiku-4-5-20251001","max_tokens":300,
                          "messages":[{"role":"user","content":prompt}]}
                )
                if r.status_code == 200:
                    text = r.json()["content"][0]["text"].strip()
                    text = re.sub(r'^```(?:json)?\s*|\s*```$','',text)
                    return json.loads(text)
        except Exception as e:
            logger.error(f"[AI] {e}")
        return {"category":t.domaine,"score":50,"reason":"Erreur","estimated_competition":"moyen"}

    @staticmethod
    async def batch_classify(tenders, anthropic_key, max_b=8):
        import asyncio
        results = []
        for t in tenders[:max_b]:
            res = await AIClassifier.classify(t, anthropic_key)
            t.ai_score = max(0,min(100,int(res.get("score",50))))
            t.ai_category = res.get("category",t.domaine)
            t.ai_reason = res.get("reason","")
            results.append(t)
            await asyncio.sleep(0.4)
        for t in tenders[max_b:]:
            t.ai_score=50; results.append(t)
        return results


def _parse_generic(card, source, base_url):
    try:
        from bs4 import BeautifulSoup as BS
        title_el = card.find(["h1","h2","h3","h4","strong"])
        title = clean_text(title_el.get_text() if title_el else card.get_text()[:120])
        if len(title) < 8: return None
        link = card.find("a", href=True)
        url = link["href"] if link else ""
        if url and not url.startswith("http"): url = base_url + url
        text = card.get_text(" ", strip=True)
        date_m = re.search(r'(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', text)
        date_lim = normalize_date(date_m.group(1) if date_m else "")
        mon_m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', text, re.I)
        bmin, bmax, montant = extract_budget(mon_m.group(0) if mon_m else "")
        contact_m = re.search(r'(?:tél|tel|email|contact)[:\s]*([^\s,<]{5,50})', text, re.I)
        return Tender(
            id=make_id(source, title, url), source=source, source_url=url,
            objet=title[:400], description=clean_text(text[:1200]),
            region=detect_region(text), domaine=detect_secteur(title, text),
            type_marche=detect_type(title), montant=montant,
            budget_min=bmin, budget_max=bmax, date_limite=date_lim,
            contact=contact_m.group(1).strip() if contact_m else "",
            statut="expire" if is_expired(date_lim) else "actif",
            date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    except: return None


def _scrape_site(source, base_url, known, log_fn, paths=None):
    from bs4 import BeautifulSoup as BS
    s = make_session()
    tenders = []
    def log(m):
        if log_fn: log_fn(f"[{source}] {m}")
    if paths is None:
        paths = ["/appels-offres","/offres","/marches","/marches-publics","/"]
    found = None
    for path in paths:
        try:
            r = s.get(base_url+path, timeout=15)
            if r.status_code==200 and len(r.text)>1000:
                found = base_url+path; break
            sleep_r(0.5,1.2)
        except: continue
    if not found:
        log("Inaccessible"); return []
    log(f"Found at {found}")
    for page in range(1,5):
        url = found if page==1 else f"{found}?page={page}"
        try:
            r = s.get(url, timeout=20)
            if r.status_code!=200: break
            soup = BS(r.text,"html.parser")
            cards = []
            for sel in ["article",".offre",".offer",".tender",".marche",".item",".post",".card"]:
                c = soup.select(sel)
                if len(c)>1: cards=c; break
            if not cards:
                cards = soup.find_all("div", class_=re.compile(r'offre|offer|tender|marche|item|card',re.I))
            new_on_page = 0
            for card in cards[:15]:
                t = _parse_generic(card, source, base_url)
                if t and t.id not in known:
                    tenders.append(t); known.add(t.id); new_on_page+=1
                    log(f"✓ {t.objet[:55]}")
            if new_on_page==0: break
            sleep_r(1.5,3.0)
        except Exception as e:
            log(f"Page {page}: {e}"); break
    log(f"Total: {len(tenders)}")
    return tenders


class MarchesPublicsScraper:
    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"
        s = make_session()
        tenders = []
        def log(m):
            if log_fn: log_fn(f"[MarchesPublics] {m}")
        ids_found = []
        for page in range(1,12):
            url = BASE+"/" if page==1 else f"{BASE}/?page={page}"
            try:
                r = s.get(url, timeout=20)
                if r.status_code!=200: break
                page_ids = list(set(re.findall(r'/show/(\d{3,7})', r.text)))
                new = [i for i in page_ids if f"bdc_{i}" not in known]
                if not new and page>1: break
                ids_found.extend(new)
                log(f"Page {page}: {len(new)} new IDs")
                sleep_r(1.0,2.0)
            except Exception as e:
                log(f"Page {page}: {e}"); break
        log(f"Fetching {len(ids_found)} tenders...")
        for tid in ids_found[:80]:
            try:
                r = s.get(f"{BASE}/show/{tid}", timeout=15)
                if r.status_code!=200: continue
                if "Liste des avis d'achat" in r.text[:2000] and len(r.text)<20000: continue
                t = cls._parse(r.text, tid)
                if t: tenders.append(t); log(f"✓ #{tid} {t.objet[:50]}")
                sleep_r(0.5,1.5)
            except Exception as e:
                log(f"#{tid}: {e}")
        log(f"Done: {len(tenders)}")
        return tenders

    @staticmethod
    def _parse(html, tid):
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html,"html.parser")
            full = soup.get_text(" ",strip=True)
            def cell(lbl):
                for row in soup.find_all("tr"):
                    cells=row.find_all(["td","th"])
                    for i,c in enumerate(cells):
                        if lbl.lower() in c.get_text().lower() and i+1<len(cells):
                            v=cells[i+1].get_text(strip=True)
                            if v and len(v)>1: return v[:400]
                return ""
            objet=""
            for sel in [".consultation-title",".objet","h1","h2"]:
                el=soup.select_one(sel)
                if el:
                    txt=el.get_text(strip=True)
                    skip=["accueil","liste des avis","connexion"]
                    if 8<len(txt)<600 and not any(s in txt.lower() for s in skip):
                        objet=txt; break
            if not objet:
                for lbl in ["objet du marché","objet","intitulé"]:
                    v=cell(lbl)
                    if v and len(v)>8: objet=v; break
            if not objet: return None
            acheteur=(cell("maître d'ouvrage") or cell("organisme") or "").strip()
            date_pub=normalize_date(cell("publication") or "")
            date_lim=normalize_date(cell("remise") or cell("limite") or "")
            mon_raw=cell("montant") or ""
            if not mon_raw:
                m=re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)',full,re.I)
                if m: mon_raw=m.group(0)[:80]
            bmin,bmax,montant=extract_budget(mon_raw)
            return Tender(
                id=make_id("bdc",objet,tid),
                source="marchespublics",
                source_url=f"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/{tid}",
                objet=clean_text(objet,400),
                description=clean_text(full,2000),
                acheteur=acheteur[:200],
                region=detect_region(acheteur+" "+full[:400]),
                domaine=detect_secteur(objet,full[:300]),
                type_marche=detect_type(objet),
                montant=montant,budget_min=bmin,budget_max=bmax,
                date_publication=date_pub,date_limite=date_lim,
                statut="annule" if "annulé" in full.lower() else ("expire" if is_expired(date_lim) else "actif"),
                date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
        except Exception as e:
            logger.error(f"[parse bdc #{tid}] {e}")
            return None


SCRAPERS = {
    "marchespublics": MarchesPublicsScraper,
    "marocao":    lambda known,log: _scrape_site("marocao","https://marocao.com",known,log),
    "lesoffres":  lambda known,log: _scrape_site("lesoffres","https://lesoffres.ma",known,log),
    "aljady":     lambda known,log: _scrape_site("aljady","https://aljady.ma",known,log),
    "marchesprives": lambda known,log: _scrape_site("marchesprives","https://marchesprives.ma",known,log),
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
            if hasattr(scraper,'scrape'):
                results = scraper.scrape(seen, log_fn)
            else:
                results = scraper(seen, log_fn)
            for t in results:
                if t.id not in seen:
                    seen.add(t.id)
                    all_tenders.append(t)
        except Exception as e:
            logger.error(f"[{src}] {e}")
            if log_fn: log_fn(f"❌ {src}: {e}")
    return all_tenders
