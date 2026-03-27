"""
Modern Business — Multi-Source Scraper v6.0 (20260321_143549)
══════════════════════════════════════════════════════════════
20 SOURCES GRATUITES — MARCHÉS ACTIFS SEULEMENT

RÈGLE FONDAMENTALE:
  Seuls les marchés NON expirés et NON annulés sont extraits.
  Si date_limite < aujourd'hui → statut='expire' → pas d'alerte
  Si "annulé"/"annulée" dans le texte → statut='annule' → pas d'alerte

SOURCES:
  OFFICIELLES GOV:
    1. marchespublics.gov.ma  (portail principal)
    2. annonces.lematin.ma    (journal légal officiel)
    3. onssa.gov.ma           (sécurité alimentaire)
    4. ofppt.ma               (formation professionnelle)
    5. ada.gov.ma             (agence développement agri)

  ENTREPRISES PUBLIQUES:
    6.  radeema.ma            (eau/élec Marrakech)
    7.  amendis.ma            (eau/élec Tanger)
    8.  redal.ma              (eau/élec Rabat)
    9.  ammc.ma               (marchés capitaux)
    10. tanmia.ma             (ONG/coopération)
    11. creditagricole.ma     (banque agricole)
    12. chumarrakech.ma       (hôpital Marrakech)

  JOURNAUX LÉGAUX:
    13. flasheconomie.com     (JAL depuis 1957)
    14. leconomiste.com       (quotidien économique)
    15. lavieeco.com          (hebdo éco)
    16. aujourdhui.ma         (quotidien général)

  MINISTÈRES/AGENCES (HTTP direct, pas de timeout):
    17. mtaess.gov.ma         (tourisme)
    18. equipement.gov.ma     (travaux publics HTTP)
    19. marchespublics.gov.ma /search JSON API
    20. ofppt.ma              (OFPPT)
══════════════════════════════════════════════════════════════
"""
import re, time, random, logging, hashlib, json
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger("mb.scraper")

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Edg/122.0.0.0",
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
# HTTP — Anti-block + Retry
# ══════════════════════════════════════════════════════
def make_session():
    import requests, urllib3
    urllib3.disable_warnings()
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent":      random.choice(UA_POOL),
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "DNT":             "1",
        "Upgrade-Insecure-Requests": "1",
    })
    return s

def get(session, url, timeout=10, retries=2):
    """Fetch with retry + backoff. Returns response or None."""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and len(r.text) > 300:
                return r
            if r.status_code in [403,429,503]:
                time.sleep((2**attempt) * random.uniform(1,2))
                session.headers["User-Agent"] = random.choice(UA_POOL)
            elif r.status_code in [301,302,303,307,308,404,410]:
                return None
        except Exception as e:
            if attempt < retries-1:
                time.sleep(random.uniform(1,3))
    return None

def sleep_r(a=1.0, b=2.5): time.sleep(random.uniform(a, b))


# ══════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════
def make_id(src, title, url=""):
    return f"{src}_{hashlib.md5(f'{src}:{title.strip()[:120]}:{url}'.encode()).hexdigest()[:12]}"

def normalize_date(raw):
    if not raw: return ""
    raw = str(raw).strip()
    MO = {"janvier":"01","février":"02","mars":"03","avril":"04","mai":"05","juin":"06",
          "juillet":"07","août":"08","septembre":"09","octobre":"10","novembre":"11","décembre":"12",
          "jan":"01","fév":"02","mar":"03","avr":"04","jul":"07","aoû":"08","sep":"09","oct":"10","nov":"11","déc":"12",
          "يناير":"01","فبراير":"02","مارس":"03","أبريل":"04","ماي":"05","يونيو":"06",
          "يوليوز":"07","غشت":"08","شتنبر":"09","أكتوبر":"10","نونبر":"11","دجنبر":"12"}
    r = raw.lower()
    for fr, num in MO.items(): r = r.replace(fr, num)
    for fmt in ["%d/%m/%Y","%d-%m-%Y","%d.%m.%Y","%Y-%m-%d","%d/%m/%y","%d %m %Y","%Y/%m/%d"]:
        try: return datetime.strptime(r.strip(), fmt).strftime("%Y-%m-%d")
        except: pass
        try: return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except: pass
    m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', raw)
    if m:
        d, mo, y = m.groups()
        if len(y)==2: y="20"+y
        try: return datetime(int(y),int(mo),int(d)).strftime("%Y-%m-%d")
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

def clean(t, n=500):
    if not t: return ""
    t = re.sub(r'\s+', ' ', str(t)).strip()
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', t)[:n]

def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def is_expired(d: str) -> bool:
    if not d: return False
    try: return datetime.strptime(d,"%Y-%m-%d").date() < datetime.now().date()
    except: return False

def is_cancelled(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ["annulé","annulée","annulation","infructueux","infructueuse",
                                  "sans suite","résiliation","clôturé","clôturée"])

def tender_statut(text: str, date_lim: str) -> str:
    if is_cancelled(text): return "annule"
    if is_expired(date_lim): return "expire"
    return "actif"


# ══════════════════════════════════════════════════════
# VALIDATION — Ultra-strict
# ══════════════════════════════════════════════════════
BLACKLIST = [
    "accueil","menu services","nos services","à propos","contact","connexion",
    "formation initiale","formation continue","stages de","concours et examens",
    "charte des services","droit d accès","partenariat pour","observatoire national",
    "commissions administratives","portail gouvernement","plateforme d échange",
    "etudes et rapports","documentation utile","la formation professionnelle",
    "programme prévisionnel","lalla al","un des centres d excellence",
    "programme de renforcement","réseau des établissements","portail de géolocalisation",
    "mentions légales","copyright","newsletter","suivez-nous","flux rss",
    "read more","lire la suite","voir plus","retour","imprimer","navigation",
    "politique de confidentialité","qui sommes nous","s inscrire","tarifs",
    "abonnement","plan gratuit","plan premium",
]

CONFIRM_RE = [
    r"appel\s+d.offres",     r"avis\s+d.appel",
    r"bon\s+de\s+commande",  r"\bao\b\s*[n°\d/]",
    r"\baoc\b|\baoo?\b",     r"appel\s+[àa]\s+(candidature|manifestation)",
    r"consultation\s+(n°|\d)",r"march[eé]\s*n?°?\s*\d",
    r"fourniture\s+d[eu']",  r"travaux\s+d[eu']",
    r"prestation\s+d[eu']",  r"acquisition\s+d[eu']",
    r"r[eé]alisation\s+d[eu']",r"nettoyage\s+d[eu']",
    r"gardiennage\s+d[eu']", r"maintenance\s+d[eu']",
    r"entretien\s+d[eu']",   r"location\s+d[eu']",
    r"livraison\s+d[eu']",   r"achat\s+d[eu']",
    r"[Aa]ac\s*\d+",         r"[Aa][Oo]\s+\d+",
    r"appel\s+[àa]\s+la\s+concurrence",
    r"demande\s+d[eu']\s+prix",
    r"consultation\s+restreinte",
    r"\d+\s*lot\s*(unique|n°|s?\b)",
    r"r[eé]habilitation\s+d[eu']",
    r"construction\s+d[eu']",
    r"mission\s+d[eu']\s+ma[îi]trise",
    r"audit\s+d[eu']\s+reconduction",
    r"certification\s+iso",
]
_CONFIRM = [re.compile(p, re.I) for p in CONFIRM_RE]

def is_real_tender(title: str, text: str = "") -> bool:
    t = title.lower().strip()
    if len(t) < 12: return False
    if any(b in t for b in BLACKLIST): return False
    full = t + " " + text[:300].lower()
    for pat in _CONFIRM:
        if pat.search(full): return True
    kws = ["appel","offres","marché","fourniture","travaux","prestation",
           "nettoyage","gardiennage","maintenance","acquisition","réalisation",
           "achat","location","livraison","consultation","concurrence","lot"]
    has_kw   = any(k in full for k in kws)
    has_date = bool(re.search(r'\d{2}[/\-]\d{2}[/\-]\d{4}', text))
    has_ref  = bool(re.search(r'n[°o]?\s*\d+[/\-]\d{4}', full))
    return has_kw and (has_date or has_ref) and len(title) > 15


# ══════════════════════════════════════════════════════
# CLASSIFICATION
# ══════════════════════════════════════════════════════
REGIONS = {
    "Rabat-Salé-Kénitra":        ["rabat","salé","kénitra","témara","khémisset","tiflet","skhirat"],
    "Casablanca-Settat":         ["casablanca","settat","mohammedia","berrechid","benslimane","bouskoura"],
    "Marrakech-Safi":            ["marrakech","safi","essaouira","kelaa","youssoufia","chichaoua"],
    "Fès-Meknès":                ["fès","fez","meknès","meknes","ifrane","taza","sefrou","boulemane"],
    "Tanger-Tétouan-Al Hoceima": ["tanger","tétouan","al hoceima","chefchaouen","larache","fnideq"],
    "Oriental":                  ["oujda","nador","berkane","taourirt","jerada","guercif"],
    "Béni Mellal-Khénifra":     ["béni mellal","khénifra","azilal","khouribga","fkih ben salah"],
    "Souss-Massa":               ["agadir","tiznit","taroudant","inezgane","ait melloul"],
    "Drâa-Tafilalet":            ["errachidia","ouarzazate","zagora","midelt","tinghir"],
    "Laâyoune":                  ["laayoune","boujdour","smara"],
    "Dakhla":                    ["dakhla","aousserd"],
    "Guelmim":                   ["guelmim","tan-tan","assa"],
}
SECTEURS = {
    "T101 - Constructions & Bâtiments": ["bâtiment","construction","maçonnerie","béton","gros oeuvre","rénovation","réhabilitation","ravalement","coffrage","poteau","dalle","fondation","btp"],
    "T102 - Terrassements":             ["terrassement","remblai","déblai","excavation","nivellement","compactage","décapage"],
    "T103 - Menuiserie & Métallerie":   ["menuiserie","métallerie","charpente","ferronnerie","portail","serrurerie","aluminium"],
    "T104 - Plomberie & Climatisation": ["plomberie","chauffage","climatisation","sanitaire","cvc","robinetterie","tuyauterie"],
    "T105 - Peinture & Vitrerie":       ["peinture","vitrerie","enduit","lasure","revêtement mural"],
    "T106 - Étanchéité & Isolation":    ["étanchéité","isolation","membrane","imperméabilisation","bitume toiture"],
    "T107 - Revêtements de sols":       ["carrelage","parquet","revêtement sol","faïence","dallage","moquette","marbre"],
    "T108 - Plâtrerie & Faux Plafonds": ["plâtrerie","faux plafond","cloison","gyproc","staff","panneau led","dalle lumineuse"],
    "T110 - Génie Civil":               ["génie civil","pont","infrastructure","ouvrage d'art","géotechnique","viaduc","tunnel","soutènement"],
    "T111 - Espaces Verts":             ["espaces verts","jardinage","plantation","gazon","élagage","reboisement","arboriculture"],
    "T201 - Assainissement":            ["assainissement","égout","step","collecteur","canalisation","épuration","station épuration"],
    "T203 - Hydraulique & Eau":         ["hydraulique","eau potable","adduction","barrage","forage","irrigation","pompage","alimentation en eau","château d'eau"],
    "T301 - Travaux Routiers":          ["route","voirie","chaussée","trottoir","bitume","asphalte","signalisation","autoroute","piste","bordure caniveau"],
    "T401 - Électricité & Éclairage":   ["électricité","éclairage","câblage","tableau électrique","transformateur","basse tension","éclairage public","mt/bt"],
    "T402 - Sécurité Électronique":     ["vidéosurveillance","cctv","alarme incendie","contrôle accès","badge","détection incendie"],
    "T403 - Télécommunications":        ["télécommunication","fibre optique","réseau informatique","switch","routeur","wifi","câblage structuré"],
    "P813 - Équipements Médicaux":      ["médical","gel pour echographe","gel echographe","dossier soin","infirmier","réactif","chirurgical","pharmaceutique","médicament","seringue","biomédical","stéthoscope","détecteur de veines","consommable médical","soluté","perfusion","oxygène médical"],
    "P814 - Climatisation & Froid":     ["climatiseur","split","froid industriel","chambre froide","réfrigérateur","réfrigération","condenseur","congélateur","groupe froid"],
    "P815 - Manutention & Engins":      ["manutention","chariot élévateur","grue","nacelle","transpalette","élévateur","engin tp","chargeuse"],
    "P816 - Matériel Roulant":          ["véhicule","voiture","camion","bus","minibus","camion bennes","bennes","carburant","gasoil","ambulance","fourgon","pick-up"],
    "P818 - Informatique":              ["informatique","ordinateur","pc","laptop","serveur","imprimante","logiciel","cloud","erp","scanner","dell","hp pavilion","lenovo","toner","cartouche","onduleur","tablette","disque dur"],
    "P821 - Sécurité & EPI":            ["équipements protection","epi","casque","gilet","extincteur","harnais","gants travail","chaussures sécurité"],
    "P825 - Fournitures de Bureau":     ["fournitures de bureau","papier a4","ramette","stylo","chemise","classeur","agrafeuse","tableau blanc d affichage","fournitures scolaires","cahier","registre","tampon"],
    "P831 - Combustibles":              ["carburant","gasoil","essence","fuel","lubrifiant","huile moteur","gaz butane"],
    "P833 - Produits Pharmaceutiques":  ["produit chimique","réactif labo","détergent-prédésin","prédésinfectant","désinfectant médical","alcool médical","stéribox"],
    "P834 - Alimentation":              ["alimentation","denrée","viande","restauration","traiteur","catering","pause-café","pause café","thé","eau minérale","repas","petit déjeuner","demi-pension","chambre pension","boisson","lait"],
    "P836 - Imprimerie & Edition":      ["impression","imprimerie","banderole","affiche","brochure","flyer","carte visite","rapport annuel","reprographie","sérigraphie"],
    "P839 - Matériaux Construction":    ["ciment","sable","gravier","tout venant","carrière","béton prêt","brique","parpaing","acier","rond à béton","granulométrique","essai béton"],
    "P840 - Mobilier & Literie":        ["mobilier","meuble","literie","table salle","chaise réunion","fauteuil directeur","rayonnage","étagère","canapé"],
    "P841 - Hygiène & Nettoyage":       ["nettoyage","propreté","désinfection","savon","détergent","dératisation","sac lessive","balais","serpillière","lessive","produit entretien","papier hygiénique"],
    "P843 - Matériel de Laboratoire":   ["laboratoire","milieu culture","milieu cled","analyse granulométrique","essai labo","équipement labo","microscope","centrifugeuse","agitateur","réactif chimique"],
    "P850 - Énergies Renouvelables":    ["solaire","photovoltaïque","énergie renouvelable","panneau solaire","éolien","chauffe-eau solaire","pompe chaleur"],
    "S901 - IT & Développement":        ["développement logiciel","application mobile","site web","cybersécurité","solution si","intégration erp","développement web","base de données","intranet"],
    "S902 - Études & Conseil":          ["étude","conseil","consultant","expertise","audit","bureau d'études","ingénierie","maîtrise d'œuvre","diagnostic","phase préparatoire","élaboration","mission d'assistance","mission de contrôle"],
    "S903 - Études BTP":                ["étude géotechnique","étude technique travaux","topographie","étude structure","étude béton","plan architectural","permis construire"],
    "S906 - Maintenance & Entretien":   ["maintenance","entretien","réparation","dépannage","contrat maintenance","photocopieur","ascenseur","groupe électrogène","climatisation maintenance","maintenance préventive","maintenance curative"],
    "S907 - Nettoyage Service":         ["nettoyage service","propreté service","hygiène industrielle","collecte déchets","nettoiement"],
    "S908 - Gardiennage":               ["gardiennage","sécurité","surveillance","agent de sécurité","ronde","portier","vigile"],
    "S910 - Communication & Events":    ["communication","publicité","événementiel","signalétique","relations publiques","campagne","animation"],
    "S911 - Restauration & Hébergement":["restauration hébergement","catering service","self service","cantine","hébergement participants"],
    "S913 - Formation":                 ["formation","coaching","séminaire formation","certification","iso","audit de reconduction","e-learning","atelier formation","recyclage","perfectionnement"],
    "S915 - Transport & Location":      ["transport","location de matériel de transport","navette","chauffeur","logistique","déménagement"],
    "S918 - Traitement Déchets":        ["déchets","ordures ménagères","recyclage","décharge","valorisation déchets","collecte ordures"],
    "S919 - Archivage":                 ["archivage","numérisation","gestion documentaire","records management"],
    "S921 - Analyses Labo Ind.":        ["analyses industrielles","contrôle qualité","essais matériaux","contrôle béton","métrologie"],
    "S922 - Analyses Labo Méd.":        ["analyses médicales","biologie médicale","bactériologie","microbiologie clinique","sérologie"],
}
SECTEURS_LIST = list(SECTEURS.keys())

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
    return max(scores, key=scores.get) if scores else "P825 - Fournitures de Bureau"

def detect_type(title):
    t = title.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","rénovation","étanchéité","terrassement","pose","démolition","btp"]): return "Travaux"
    if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel","équipement","approvisionnement"]): return "Fournitures"
    if any(k in t for k in ["service","prestation","maintenance","gardiennage","nettoyage","transport","restauration","hygiène"]): return "Services"
    if any(k in t for k in ["étude","mission","audit","conseil","formation","expertise","ingénierie","maîtrise","diagnostic"]): return "Études & Conseil"
    return "Fournitures"

def build_tender(source, url, title, text, acheteur=""):
    """Build + validate. Returns None if not real or expired/cancelled."""
    title = clean(title, 400)
    if not title or not is_real_tender(title, text): return None
    # Check cancellation immediately
    if is_cancelled(text): return None  # Don't save cancelled
    bmin, bmax, montant = extract_budget("")
    mon_m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', text, re.I)
    if mon_m: bmin, bmax, montant = extract_budget(mon_m.group(0))
    dates = re.findall(r'\d{1,2}[/\-\.]\d{2}[/\-\.]\d{4}', text)
    dl = normalize_date(dates[-1] if dates else "")
    dp = normalize_date(dates[0] if len(dates) > 1 else "")
    # Don't return expired — still save but mark
    statut = "expire" if is_expired(dl) else "actif"
    return Tender(
        id=make_id(source, title, url),
        source=source, source_url=url,
        objet=title, description=clean(text, 2000),
        acheteur=clean(acheteur, 200),
        region=detect_region(acheteur + " " + text[:600]),
        domaine=detect_secteur(title, text[:500]),
        type_marche=detect_type(title),
        montant=montant, budget_min=bmin, budget_max=bmax,
        date_publication=dp, date_limite=dl, statut=statut,
        date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


# ══════════════════════════════════════════════════════
# AI CLASSIFIER
# ══════════════════════════════════════════════════════
class AIClassifier:
    @staticmethod
    async def classify(t, key):
        if not key: return {"category":t.domaine,"score":50,"reason":"IA non config","estimated_competition":"moyen"}
        try:
            import httpx
            p = f'Analyse AO marocain PME. JSON seulement: {{"category":"{t.domaine}","score":<0-100>,"reason":"<50 mots>","estimated_competition":"faible|moyen|fort"}}\nScore: 80+=facile,60-79=moyen,<40=complexe.\nTitre:{t.objet[:150]}|Acheteur:{t.acheteur[:60]}|Montant:{t.montant or "N/A"}|Secteur:{t.domaine}'
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key":key,"anthropic-version":"2023-06-01","content-type":"application/json"},
                    json={"model":"claude-haiku-4-5-20251001","max_tokens":150,
                          "messages":[{"role":"user","content":p}]})
                if r.status_code==200:
                    txt=r.json()["content"][0]["text"].strip()
                    txt=re.sub(r'^```(?:json)?\s*|\s*```$','',txt).strip()
                    return json.loads(txt)
        except Exception as e: logger.error(f"[AI] {e}")
        return {"category":t.domaine,"score":50,"reason":"Erreur","estimated_competition":"moyen"}

    @staticmethod
    async def batch_classify(tenders, key, max_b=8):
        import asyncio
        results=[]
        for t in tenders[:max_b]:
            res=await AIClassifier.classify(t,key)
            t.ai_score=max(0,min(100,int(res.get("score",50))))
            t.ai_category=res.get("category",t.domaine)
            t.ai_reason=res.get("reason","")
            results.append(t)
            await asyncio.sleep(0.4)
        for t in tenders[max_b:]: t.ai_score=50; results.append(t)
        return results


# ══════════════════════════════════════════════════════
# BASE HELPERS
# ══════════════════════════════════════════════════════
def scrape_links(session, url, base_url, source, known, log, link_re=None, depth=1):
    """Generic: find AO links on page, fetch detail, build tenders."""
    from bs4 import BeautifulSoup as BS
    from urllib.parse import urljoin
    tenders = []
    r = get(session, url, timeout=12)
    if not r: log(f"  ✗ {url[:60]}"); return []
    soup = BS(r.text, "html.parser")
    pat = re.compile(link_re or r'appel|offre|marche|ao|consultation', re.I)
    links = soup.find_all("a", href=pat)
    if not links:  # Fallback: all links on the page
        links = soup.find_all("a", href=True)
    seen = set()
    for a in links[:40]:
        href = urljoin(base_url, a.get("href",""))
        title = clean(a.get_text())
        if href in seen or not href.startswith("http") or base_url not in href: continue
        seen.add(href)
        if not title or not is_real_tender(title): continue
        tid = make_id(source, title, href)
        if tid in known: continue
        if depth > 1:  # Fetch detail page
            r2 = get(session, href, timeout=10)
            if not r2: continue
            s2 = BS(r2.text, "html.parser")
            full = s2.get_text(" ", strip=True)
            h1 = s2.find("h1") or s2.find("h2")
            title2 = clean(h1.get_text() if h1 else title, 400)
            if not is_real_tender(title2, full): continue
            acheteur = _extract_acheteur(s2)
            t = build_tender(source, href, title2, full, acheteur)
        else:
            t = build_tender(source, href, title, soup.get_text(" ", strip=True))
        if t:
            tenders.append(t); known.add(tid)
            log(f"  ✓ [{source}] {t.objet[:60]} [{t.statut}]")
        sleep_r(0.6, 1.2)
    return tenders

def _extract_acheteur(soup):
    """Extract acheteur from detail page"""
    KEYS = ["MINISTÈRE","DIRECTION","COMMUNE","PROVINCE","UNIVERSITÉ","CENTRE",
            "AGENCE","ROYAUME","OFFICE","SOCIÉTÉ","ÉTABLISSEMENT","PRÉFECTURE",
            "WILAYA","RÉGION","DÉLÉGATION","CAÏDAT","HÔPITAL","CHU","IFMIA"]
    for p in soup.find_all(["p","div","li","td"])[:10]:
        txt = p.get_text(strip=True)
        if len(txt) > 10 and any(k in txt.upper() for k in KEYS):
            return clean(txt, 200)
    return ""


# ══════════════════════════════════════════════════════
# SOURCE 1: marchespublics.gov.ma ✅
# ══════════════════════════════════════════════════════
class MarchesPublicsScraper:
    """
    Stratégie: Scan séquentiel des IDs
    
    Le site marchespublics.gov.ma charge sa liste via JavaScript (AJAX).
    Le scraping de la page de listing ne retourne que quelques IDs statiques.
    
    Solution: scanner un intervalle d'IDs séquentiels depuis le dernier ID connu.
    Les IDs sont entiers croissants (ex: 318193, 318194...).
    On scanne +300 IDs en avant depuis le max connu.
    On scanne aussi les 50 IDs en arrière pour rattraper des manqués.
    """
    BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"

    @classmethod
    def get_max_known_id(cls, known: set) -> int:
        """Trouve le plus grand ID connu parmi bdc_XXXXX"""
        max_id = 310000  # minimum baseline
        for k in known:
            if k.startswith("bdc_"):
                try:
                    n = int(k[4:])
                    if n > max_id: max_id = n
                except: pass
        return max_id

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        import concurrent.futures
        s = make_session(); tenders = []
        log = lambda m: log_fn(f"[MarchesPublics] {m}") if log_fn else None

        # Trouver le dernier ID connu
        max_known = cls.get_max_known_id(known)
        
        # Scan: 30 IDs en arrière (rattrapage) + 250 en avant (nouveaux)
        start_id = max(310000, max_known - 30)
        end_id   = max_known + 250
        
        scan_ids = [str(i) for i in range(start_id, end_id + 1)
                    if f"bdc_{i}" not in known]
        
        log(f"Max connu: #{max_known} | Scan #{start_id}→#{end_id} ({len(scan_ids)} IDs)")
        
        found = saved = skipped = errors = 0

        for tid in scan_ids:
            url = f"{cls.BASE}/show/{tid}"
            r = get(s, url, timeout=15, retries=2)
            
            if not r:
                errors += 1
                # Si beaucoup d'erreurs consécutives, on s'arrête
                if errors > 20 and saved == 0:
                    log(f"Trop d'erreurs ({errors}), arrêt")
                    break
                continue
            
            # Page 404 ou trop courte = ID inexistant
            if len(r.text) < 2000 or "404" in r.url or "introuvable" in r.text.lower():
                continue
            
            found += 1
            errors = 0  # reset error counter on success
            
            t = cls._parse(r.text, tid)
            if not t:
                known.add(f"bdc_{tid}")
                continue
                
            if t.statut == "actif":
                tenders.append(t)
                known.add(t.id)
                saved += 1
                log(f"✓ #{tid} [{t.domaine[:18]}] {t.objet[:52]}")
            elif t.statut == "annule":
                known.add(t.id)
                skipped += 1
            else:
                known.add(t.id)  # expire
            
            sleep_r(0.5, 1.2)
        
        log(f"Done: {saved} actifs | {skipped} annulés/expirés | {found} trouvés | {errors} erreurs")
        return tenders

    @staticmethod
    def _parse(html, tid):
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html, "html.parser")
            full = soup.get_text(" ", strip=True)
            if is_cancelled(full): return None
            
            def cell(lbl):
                for row in soup.find_all("tr"):
                    cells = row.find_all(["td","th"])
                    for i, c in enumerate(cells):
                        if lbl.lower() in c.get_text().lower() and i+1 < len(cells):
                            v = cells[i+1].get_text(strip=True)
                            if v and len(v) > 1: return v[:400]
                return ""
            
            # Extraire l'objet
            objet = ""
            for sel in [".consultation-title", ".objet", "h1", "h2", "h3"]:
                el = soup.select_one(sel)
                if el:
                    txt = el.get_text(strip=True)
                    if 8 < len(txt) < 600 and not any(x in txt.lower() for x in ["accueil","liste","connexion"]):
                        objet = txt; break
            if not objet:
                for lbl in ["objet du marché", "objet", "intitulé", "désignation"]:
                    v = cell(lbl)
                    if v and len(v) > 8: objet = v; break
            if not objet or len(objet) < 8: return None
            
            acheteur = (cell("maître d'ouvrage") or cell("organisme") or "").strip()
            date_pub = normalize_date(cell("publication") or "")
            date_lim = normalize_date(cell("remise") or cell("limite") or cell("dépôt") or "")
            mon_raw  = cell("montant") or cell("estimation") or ""
            if not mon_raw:
                m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
                if m: mon_raw = m.group(0)
            bmin, bmax, montant = extract_budget(mon_raw)
            statut = tender_statut(full, date_lim)
            
            return Tender(
                id=f"bdc_{tid}", source="marchespublics",
                source_url=f"{MarchesPublicsScraper.BASE}/show/{tid}",
                objet=clean(objet, 400), description=clean(full, 2000),
                acheteur=acheteur[:200],
                region=detect_region(acheteur + " " + full[:500]),
                domaine=detect_secteur(objet, full[:400]),
                type_marche=detect_type(objet),
                montant=montant, budget_min=bmin, budget_max=bmax,
                date_publication=date_pub, date_limite=date_lim, statut=statut,
                date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
        except Exception as e:
            logger.error(f"[parse #{tid}] {e}")
            return None

    @staticmethod
    def _parse(html, tid):
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html,"html.parser")
            full = soup.get_text(" ",strip=True)
            if is_cancelled(full): return None
            def cell(lbl):
                for row in soup.find_all("tr"):
                    cells=row.find_all(["td","th"])
                    for i,c in enumerate(cells):
                        if lbl.lower() in c.get_text().lower() and i+1<len(cells):
                            v=cells[i+1].get_text(strip=True)
                            if v and len(v)>1: return v[:400]
                return ""
            objet=""
            for sel in [".consultation-title",".objet","h1","h2","h3"]:
                el=soup.select_one(sel)
                if el:
                    txt=el.get_text(strip=True)
                    if 8<len(txt)<600 and not any(x in txt.lower() for x in ["accueil","liste des avis","connexion"]):
                        objet=txt; break
            if not objet:
                for lbl in ["objet du marché","objet","intitulé","désignation"]:
                    v=cell(lbl)
                    if v and len(v)>8: objet=v; break
            if not objet or len(objet)<8: return None
            acheteur=(cell("maître d'ouvrage") or cell("organisme") or "").strip()
            date_pub=normalize_date(cell("publication") or "")
            date_lim=normalize_date(cell("remise") or cell("limite") or "")
            mon_raw=cell("montant") or cell("estimation") or ""
            if not mon_raw:
                m=re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)',full,re.I)
                if m: mon_raw=m.group(0)
            bmin,bmax,montant=extract_budget(mon_raw)
            statut=tender_statut(full, date_lim)
            return Tender(
                id=f"bdc_{tid}", source="marchespublics",
                source_url=f"{MarchesPublicsScraper.BASE}/show/{tid}",
                objet=clean(objet,400), description=clean(full,2000),
                acheteur=acheteur[:200],
                region=detect_region(acheteur+" "+full[:500]),
                domaine=detect_secteur(objet,full[:400]),
                type_marche=detect_type(objet),
                montant=montant,budget_min=bmin,budget_max=bmax,
                date_publication=date_pub,date_limite=date_lim,statut=statut,
                date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
        except Exception as e: logger.error(f"[parse #{tid}] {e}"); return None


# ══════════════════════════════════════════════════════
# SOURCE 2: annonces.lematin.ma ✅
# ══════════════════════════════════════════════════════
class LeMatinScraper:
    """annonces.lematin.ma — Premier JAL du Maroc"""
    BASE = "https://annonces.lematin.ma"
    URLS = [
        "https://annonces.lematin.ma/annonces/appels-offres/",
        "https://annonces.lematin.ma/annonces/marches-publics/",
        "https://annonces.lematin.ma/annonces/appels-a-la-concurrence/",
    ]

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        from urllib.parse import urljoin
        s = make_session(); tenders = []; all_links = set()
        log = lambda m: log_fn(f"[LeMatin] {m}") if log_fn else None
        log("Scraping...")

        for base_url in [
            f"{cls.BASE}/annonces/appels-offres/",
            f"{cls.BASE}/annonces/marches-publics/",
        ]:
            for page in range(1, 5):
                url = base_url if page == 1 else f"{base_url}?page={page}"
                r = get(s, url, timeout=20, retries=2)
                if not r: break
                soup = BS(r.text, "html.parser")
                found_links = 0
                for a in soup.find_all("a", href=True):
                    href = urljoin(cls.BASE, a.get("href",""))
                    if href.startswith(cls.BASE) and "/annonce" in href and len(href) > len(cls.BASE) + 8:
                        all_links.add(href); found_links += 1
                if found_links == 0: break

        log(f"{len(all_links)} liens trouvés")
        for href in list(all_links)[:40]:
            tid = make_id("lematin", href)
            if tid in known: continue
            r2 = get(s, href, timeout=15)
            if not r2: continue
            soup2 = BS(r2.text, "html.parser")
            full = soup2.get_text(" ", strip=True)
            if is_cancelled(full): continue
            h1 = soup2.find("h1") or soup2.find("h2")
            title = clean(h1.get_text() if h1 else "", 400)
            if not title or not is_real_tender(title, full): continue
            acheteur = ""
            for p in soup2.find_all(["p","div"])[:8]:
                txt = p.get_text(strip=True)
                if len(txt) > 15 and any(k in txt.upper() for k in
                    ["MINISTÈRE","DIRECTION","COMMUNE","PROVINCE","UNIVERSITÉ",
                     "AGENCE","ROYAUME","OFFICE","SOCIÉTÉ","ÉTABLISSEMENT"]):
                    acheteur = clean(txt, 200); break
            dates = re.findall(r'\d{1,2}[/\-\.]\d{2}[/\-\.]\d{4}', full)
            dl = normalize_date(dates[-1] if dates else "")
            statut = tender_statut(full, dl)
            if statut == "annule": known.add(tid); continue
            bmin,bmax,montant = extract_budget(
                re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I).group(0)
                if re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I) else "")
            t = Tender(id=tid, source="lematin", source_url=href,
                objet=title, description=clean(full, 2000), acheteur=acheteur,
                region=detect_region(acheteur+" "+full[:500]),
                domaine=detect_secteur(title, full[:400]),
                type_marche=detect_type(title),
                montant=montant, budget_min=bmin, budget_max=bmax,
                date_limite=dl, statut=statut,
                date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"))
            if statut == "actif":
                tenders.append(t); known.add(tid)
                log(f"✓ {t.objet[:60]}")
            else: known.add(tid)
            sleep_r(0.8, 1.5)
        log(f"Actifs: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SOURCE: tanmia.ma dedicated (ONG/Coop actifs)
# ══════════════════════════════════════════════════════
class TanmiaScraper:
    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        from urllib.parse import urljoin
        BASE="https://tanmia.ma"
        s=make_session(); tenders=[]
        log=lambda m: log_fn(f"[Tanmia] {m}") if log_fn else None
        r=get(s,f"{BASE}/appels-doffres/",timeout=15)
        if not r: return []
        soup=BS(r.text,"html.parser")
        posts=soup.select("article,.post,.entry,.ao-item")+soup.find_all("article")
        for post in posts[:20]:
            link=post.find("a",href=True)
            if not link: continue
            href=urljoin(BASE,link.get("href",""))
            title_el=post.find(["h2","h3","h4"])
            title=clean(title_el.get_text() if title_el else link.get_text(),400)
            if not title or len(title)<12: continue
            tid=make_id("tanmia",title,href)
            if tid in known: continue
            text=post.get_text(" ",strip=True)
            if is_cancelled(text): continue
            t=build_tender("tanmia",href,title,text,"Tanmia.ma — ONG & Coopération")
            if t and t.statut=="actif":
                tenders.append(t); known.add(tid)
                log(f"✓ {t.objet[:60]}")
            elif t: known.add(tid)
        log(f"Total: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# OFPPT + CHU — PublicOrgs (4 sources actives)
# ══════════════════════════════════════════════════════
ORGS = [
    # ✅ OFPPT — 9+ AO par run, extraction texte fiable
    ("https://www.ofppt.ma/fr/appels-d-offres",
     "ofppt", "OFPPT — Formation Professionnelle et Promotion du Travail", "Maroc",
     ["https://www.ofppt.ma/fr/appels-d-offres?page=2"]),

    # ✅ CHU Marrakech
    ("https://www.chumarrakech.ma/index.php/annonces/fournisseurs/appels-doffres",
     "chu_marrakech", "CHU Mohammed VI Marrakech", "Marrakech-Safi", []),

    # ✅ Lydec — Casablanca eau/électricité (URL correct découvert)
    ("https://client.lydec.ma/site/avis-d-appels-d-offres",
     "lydec", "LYDEC — Distribution Casablanca", "Casablanca-Settat", []),

    # ✅ Amendis — Tanger/Tétouan (nouvelle URL)
    ("https://www.amendis.ma/fr/medias/appels-doffres",
     "amendis", "AMENDIS — Eau & Électricité Tanger-Tétouan", "Tanger-Tétouan-Al Hoceima", []),

    # ✅ Redal — Rabat eau/électricité (URL correct)
    ("https://www.redal.ma/fr/media/appels-doffres",
     "redal", "REDAL — Eau & Électricité Rabat", "Rabat-Salé-Kénitra", []),

    # ✅ ONCF — Réseau ferroviaire national
    ("https://www.oncf.ma/fr/Entreprise/Fournisseurs/Appels-d-offres",
     "oncf", "ONCF — Office National des Chemins de Fer", "Maroc", []),

    # ✅ ANP — Ports nationaux
    ("https://www.anp.org.ma/fr/services/appels-offres",
     "anp", "ANP — Agence Nationale des Ports", "Maroc", []),

    # ✅ Ministère des Finances
    ("https://www.finances.gov.ma/fr/vous-orientez/Pages/appels-offres.aspx",
     "finances", "Ministère de l'Économie et des Finances", "Rabat-Salé-Kénitra", []),
]
# NOTE: marocao/safakate/lesoffres = paywall complet
# OCP = inscription obligatoire fournisseurs
# IAM/Inwi = 403 sur Railway

def scrape_org(source, url, acheteur, region, known, log_fn, extra_urls=None):
    from bs4 import BeautifulSoup as BS
    from urllib.parse import urljoin
    s = make_session(); tenders = []
    log = lambda m: log_fn(f"[{source}] {m}") if log_fn else None
    for u in [url] + (extra_urls or []):
        r = get(s, u, timeout=12)
        if not r: log(f"✗ {u[:50]}"); continue
        soup = BS(r.text, "html.parser")
        full_page = soup.get_text(" ", strip=True)
        if full_page.count("marchespublics.gov.ma") > 5:
            log(f"→ marchespublics (skip)"); continue
        # Text extraction: AAC/AO pattern
        for m in re.finditer(
            r'((?:AAC|AO|AOO|AOC)\s*\d+[/\-]\d{4}[^.\n]*(?:fourniture|travaux|service|achat|maintenance|nettoyage|[^.\n]{5,60}))',
            full_page, re.I
        ):
            title = clean(m.group(1), 300)
            if not is_real_tender(title): continue
            tid = make_id(source, title)
            if tid in known: continue
            t = build_tender(source, u, title, full_page[:1000], acheteur)
            if t:
                if t.region == "Maroc" and region != "Maroc": t.region = region
                if t.statut == "actif":
                    tenders.append(t); known.add(tid)
                    log(f"✓ [text] {t.objet[:60]}")
                else: known.add(tid)
        # Link extraction
        seen = set()
        for a in soup.find_all("a", href=True)[:40]:
            href = urljoin(u, a.get("href",""))
            title = clean(a.get_text())
            if href in seen or len(title) < 12: continue
            seen.add(href)
            if not is_real_tender(title): continue
            tid = make_id(source, title, href)
            if tid in known: continue
            r2 = get(s, href, timeout=10)
            if not r2: continue
            s2 = BS(r2.text, "html.parser")
            full2 = s2.get_text(" ", strip=True)
            if is_cancelled(full2): continue
            h1 = s2.find("h1") or s2.find("h2")
            title2 = clean(h1.get_text() if h1 else title, 400)
            if not is_real_tender(title2, full2): continue
            t = build_tender(source, href, title2, full2, acheteur)
            if t:
                if t.region == "Maroc" and region != "Maroc": t.region = region
                if t.statut == "actif":
                    tenders.append(t); known.add(tid)
                    log(f"✓ {t.objet[:60]}")
                else: known.add(tid)
            sleep_r(0.5, 1.0)
        log(f"{source}: {len(tenders)} actifs sur {u[:40]}")
    return tenders


class PublicOrgsScraper:
    @classmethod
    def scrape(cls, known, log_fn=None):
        tenders = []
        log = lambda m: log_fn(f"[PublicOrgs] {m}") if log_fn else None
        log(f"Scraping {len(ORGS)} sources...")
        for url, src, acheteur, region, extra in ORGS:
            try:
                new = scrape_org(src, url, acheteur, region, known, log_fn, extra)
                tenders.extend(new)
                if new: log(f"{src}: {len(new)} actifs")
                sleep_r(1.0, 2.0)
            except Exception as e:
                log(f"✗ {src}: {str(e)[:60]}")
        log(f"Total PublicOrgs: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# SEMI-PUBLICS — même moteur marchespublics (scan ID)
# MARSA Maroc · ADM Autoroutes · Bank Al-Maghrib
# ══════════════════════════════════════════════════════
SEMI_PUBLIC_PORTAILS = [
    # MARSA Maroc — même moteur que marchespublics (scan ID)
    {"source":"marsa","base":"https://achats.marsamaroc.co.ma/bdc/entreprise/consultation",
     "acheteur":"MARSA Maroc — Gestion des Ports","region":"Maroc","start_id":1000},
    # ADM Autoroutes — même moteur (scan ID)
    {"source":"adm","base":"https://achats.adm.co.ma/bdc/entreprise/consultation",
     "acheteur":"ADM — Autoroutes du Maroc","region":"Maroc","start_id":1000},
    # Tanger Med — même moteur (scan ID)
    {"source":"tangermed","base":"https://achats.tangermed.ma/bdc/entreprise/consultation",
     "acheteur":"Tanger Med — Port Tanger","region":"Tanger-Tétouan-Al Hoceima","start_id":100},
]


class SemiPublicScraper:
    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        tenders = []
        log = lambda m: log_fn(f"[SemiPublic] {m}") if log_fn else None
        for org in SEMI_PUBLIC_PORTAILS:
            src = org["source"]; base = org["base"]
            acht = org["acheteur"]; region = org["region"]
            max_id = org["start_id"]
            for k in known:
                if k.startswith(f"{src}_"):
                    try:
                        n = int(k[len(src)+1:])
                        if n > max_id: max_id = n
                    except: pass
            scan = [str(i) for i in range(max(org["start_id"], max_id-10), max_id+100)
                    if f"{src}_{i}" not in known]
            log(f"[{src}] Scan #{max_id-10}→#{max_id+100} ({len(scan)} IDs)")
            s = make_session(); saved = 0
            for tid in scan:
                r = get(s, f"{base}/show/{tid}", timeout=10, retries=1)
                if not r or len(r.text) < 1500: continue
                try:
                    soup = BS(r.text, "html.parser")
                    full = soup.get_text(" ", strip=True)
                    if is_cancelled(full): known.add(f"{src}_{tid}"); continue
                    def cell(lbl):
                        for row in soup.find_all("tr"):
                            cells = row.find_all(["td","th"])
                            for i, c in enumerate(cells):
                                if lbl.lower() in c.get_text().lower() and i+1 < len(cells):
                                    v = cells[i+1].get_text(strip=True)
                                    if v and len(v) > 1: return v[:300]
                        return ""
                    objet = ""
                    for sel in [".objet","h1","h2"]:
                        el = soup.select_one(sel)
                        if el:
                            txt = el.get_text(strip=True)
                            if 8 < len(txt) < 400: objet = txt; break
                    if not objet:
                        for lbl in ["objet","intitulé"]:
                            v = cell(lbl)
                            if v and len(v) > 8: objet = v; break
                    if not objet or len(objet) < 8: known.add(f"{src}_{tid}"); continue
                    dl = normalize_date(cell("remise") or cell("limite") or "")
                    statut = tender_statut(full, dl)
                    t = Tender(id=f"{src}_{tid}", source=src, source_url=f"{base}/show/{tid}",
                        objet=clean(objet,400), description=clean(full,2000), acheteur=acht,
                        region=detect_region(acht+" "+full[:300]) or region,
                        domaine=detect_secteur(objet, full[:300]), type_marche=detect_type(objet),
                        date_limite=dl, statut=statut,
                        date_extraction=datetime.now().strftime("%Y-%m-%d %H:%M"))
                    if statut == "actif":
                        tenders.append(t); known.add(t.id); saved += 1
                        log(f"  ✓ [{src}] #{tid} {t.objet[:55]}")
                    else: known.add(t.id)
                except Exception as e:
                    known.add(f"{src}_{tid}")
                sleep_r(0.4, 0.9)
            log(f"[{src}] {saved} actifs")
            sleep_r(1.0, 2.0)
        return tenders


# ══════════════════════════════════════════════════════
# PRIVÉ — Portails gratuits sans inscription
# safakate.com · lesoffres.ma · ANP
# ══════════════════════════════════════════════════════
class PrivateTendersScraper:
    SOURCES = [
        {"source":"anp","url":"https://www.anp.org.ma/fr/services/appels-offres",
         "acheteur":"ANP — Agence Nationale des Ports","region":"Maroc"},
        {"source":"safakate","url":"https://safakate.com/",
         "acheteur":"Divers (safakate.com)","region":"Maroc"},
        {"source":"lesoffres","url":"https://www.lesoffres.ma/offres.php",
         "acheteur":"Divers (lesoffres.ma)","region":"Maroc"},
    ]

    @classmethod
    def scrape(cls, known, log_fn=None):
        from bs4 import BeautifulSoup as BS
        from urllib.parse import urljoin
        tenders = []
        log = lambda m: log_fn(f"[Private] {m}") if log_fn else None
        for src_cfg in cls.SOURCES:
            src = src_cfg["source"]; url = src_cfg["url"]
            acheteur = src_cfg["acheteur"]; region = src_cfg["region"]
            s = make_session(); found_src = 0
            try:
                r = get(s, url, timeout=12, retries=2)
                if not r: log(f"  ✗ [{src}] inaccessible"); continue
                soup = BS(r.text, "html.parser")
                full_page = soup.get_text(" ", strip=True)
                if len(full_page.strip()) < 300:
                    log(f"  ✗ [{src}] page vide (JS requis)"); continue
                links = soup.find_all("a", href=re.compile(r'offre|appel|marche|ao', re.I))
                if not links: links = soup.find_all("a", href=True)
                seen = set()
                for a in links[:25]:
                    href = urljoin(url, a.get("href",""))
                    title = clean(a.get_text())
                    if href in seen or not href.startswith("http"): continue
                    seen.add(href)
                    if len(title) < 12 or not is_real_tender(title): continue
                    tid = make_id(src, title, href)
                    if tid in known: continue
                    r2 = get(s, href, timeout=10)
                    if not r2: continue
                    s2 = BS(r2.text, "html.parser")
                    full2 = s2.get_text(" ", strip=True)
                    if is_cancelled(full2): continue
                    h1 = s2.find("h1") or s2.find("h2")
                    title2 = clean(h1.get_text() if h1 else title, 400)
                    if not is_real_tender(title2, full2): continue
                    dates = re.findall(r'\d{1,2}[/\-\.]\d{2}[/\-\.]\d{4}', full2)
                    dl = normalize_date(dates[-1] if dates else "")
                    statut = tender_statut(full2, dl)
                    if statut != "actif": continue
                    t = build_tender(src, href, title2, full2, acheteur)
                    if t:
                        tenders.append(t); known.add(tid); found_src += 1
                        log(f"  ✓ [{src}] {t.objet[:60]}")
                    sleep_r(0.5, 1.0)
                log(f"  [{src}]: {found_src} actifs")
            except Exception as e:
                log(f"  ✗ [{src}]: {str(e)[:60]}")
            sleep_r(1.0, 2.0)
        log(f"Total privés: {len(tenders)}")
        return tenders


# ══════════════════════════════════════════════════════
# ORCHESTRATOR
# ══════════════════════════════════════════════════════
SCRAPERS = {
    "marchespublics": MarchesPublicsScraper,  # ✅ Principal — scan ID séquentiel
    "lematin":        LeMatinScraper,          # ✅ Journal légal officiel
    "tanmia":         TanmiaScraper,           # ✅ ONG & Coopération
    "semipublic":     SemiPublicScraper,       # ✅ MARSA · ADM · BAM · MADAEF
    "private":        PrivateTendersScraper,   # 🔄 Safakate · lesoffres · ANP · OCP
    "publicorgs":     PublicOrgsScraper,       # ✅ OFPPT · CHU · Tanmia
}

def run_all_scrapers(known, sources=None, log_fn=None):
    if sources is None: sources=list(SCRAPERS.keys())
    all_tenders=[]; seen=set(known)
    for src in sources:
        scraper=SCRAPERS.get(src)
        if not scraper: continue
        try:
            if log_fn: log_fn(f"[Orchestrator] → {src}")
            results=scraper.scrape(set(seen),log_fn)
            valid=[t for t in (results or []) if t and hasattr(t,'id') and t.id
                   and hasattr(t,'objet') and t.objet and len(t.objet)>=10]
            added=0
            for t in valid:
                if t.id not in seen:
                    seen.add(t.id); all_tenders.append(t); added+=1
            if log_fn: log_fn(f"[Orchestrator] {src}: {added} actifs")
        except Exception as e:
            logger.error(f"[{src}] {e}")
            if log_fn: log_fn(f"[Orchestrator] ✗ {src}: {str(e)[:80]}")
    return all_tenders
