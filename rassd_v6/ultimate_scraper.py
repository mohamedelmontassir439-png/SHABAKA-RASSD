"""
Professional Scraper Module for Modern Business
Version: 5.1 - Enhanced Title & Date Extraction
"""

import re
import time
import hashlib
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ============================================================
# التصنيفات الرسمية STX10 - 47 قطاعاً (نفس المحتوى السابق)
# ============================================================

class SectorType(Enum):
    TRAVAUX = "T"
    FOURNITURES = "P"
    SERVICES = "S"

@dataclass
class Sector:
    code: str
    label: str
    type: SectorType
    keywords: List[str]
    weight: int = 1

SECTORS = {
    # Travaux (T)
    "T101": Sector("T101", "Constructions & Bâtiments", SectorType.TRAVAUX, 
                   ["bâtiment", "construction", "maçonnerie", "béton", "immeuble", "logement", "école", "hôpital"]),
    "T102": Sector("T102", "Terrassements & VRD", SectorType.TRAVAUX,
                   ["terrassement", "vrd", "voirie", "remblai", "déblai", "excavation"]),
    "T103": Sector("T103", "Menuiserie & Métallerie", SectorType.TRAVAUX,
                   ["menuiserie", "métallerie", "charpente", "ferronnerie", "portail", "fenêtre"]),
    "T104": Sector("T104", "Plomberie & CVC", SectorType.TRAVAUX,
                   ["plomberie", "chauffage", "climatisation", "cvc", "hvac", "sanitaire"]),
    "T105": Sector("T105", "Peinture & Revêtements", SectorType.TRAVAUX,
                   ["peinture", "revêtement", "carrelage", "parquet", "faïence", "enduit"]),
    "T106": Sector("T106", "Étanchéité & Isolation", SectorType.TRAVAUX,
                   ["étanchéité", "isolation", "toiture", "imperméabilisation", "bardage"]),
    "T107": Sector("T107", "Électricité & Éclairage", SectorType.TRAVAUX,
                   ["électricité", "éclairage", "câblage", "transformateur", "éclairage public"]),
    "T108": Sector("T108", "Plâtrerie & Faux Plafonds", SectorType.TRAVAUX,
                   ["plâtrerie", "faux plafond", "cloison", "plâtre", "staff"]),
    "T109": Sector("T109", "Chapes & Dallages", SectorType.TRAVAUX,
                   ["chape", "dallage", "béton ciré", "résine", "sol industriel"]),
    "T110": Sector("T110", "Génie Civil & Infrastructure", SectorType.TRAVAUX,
                   ["génie civil", "pont", "viaduc", "tunnel", "barrage", "ouvrage d'art"]),
    "T111": Sector("T111", "Espaces Verts & Paysage", SectorType.TRAVAUX,
                   ["espace vert", "jardin", "paysage", "plantation", "gazon", "élagage"]),
    "T201": Sector("T201", "Assainissement & Eaux Usées", SectorType.TRAVAUX,
                   ["assainissement", "égout", "step", "station épuration", "collecteur"]),
    "T202": Sector("T202", "Adduction d'Eau Potable", SectorType.TRAVAUX,
                   ["aep", "adduction", "eau potable", "forage", "pompage", "canalisation"]),
    "T301": Sector("T301", "Travaux Routiers", SectorType.TRAVAUX,
                   ["route", "chaussée", "bitume", "asphalte", "enrobé", "signalisation", "marquage"]),
    "T401": Sector("T401", "Équipements Électriques", SectorType.TRAVAUX,
                   ["poste électrique", "transformateur", "haute tension", "basse tension"]),
    "T402": Sector("T402", "Sécurité & Vidéosurveillance", SectorType.TRAVAUX,
                   ["vidéosurveillance", "cctv", "alarme", "contrôle accès", "sssi"]),
    "T501": Sector("T501", "Restauration Patrimoine", SectorType.TRAVAUX,
                   ["restauration", "patrimoine", "médina", "monument", "site historique"]),
    
    # Fournitures (P) - اختصاراً
    "P801": Sector("P801", "Équipements Médicaux", SectorType.FOURNITURES,
                   ["médical", "hôpital", "chirurgical", "scanner", "irm", "bloc opératoire"]),
    "P802": Sector("P802", "Informatique & Télécoms", SectorType.FOURNITURES,
                   ["informatique", "ordinateur", "serveur", "pc", "logiciel", "cloud", "réseau"]),
    "P803": Sector("P803", "Véhicules & Matériel Roulant", SectorType.FOURNITURES,
                   ["véhicule", "voiture", "camion", "bus", "ambulance", "engin", "tracteur"]),
    "P804": Sector("P804", "Mobilier & Équipements Bureau", SectorType.FOURNITURES,
                   ["mobilier", "bureau", "chaise", "armoire", "tableau blanc", "fourniture bureau"]),
    "P805": Sector("P805", "Matériel Électrique", SectorType.FOURNITURES,
                   ["onduleur", "ups", "batterie", "générateur", "armoire électrique", "disjoncteur"]),
    "P806": Sector("P806", "Climatisation & Froid", SectorType.FOURNITURES,
                   ["climatiseur", "split", "froid", "chambre froide", "réfrigération"]),
    "P807": Sector("P807", "Matériaux de Construction", SectorType.FOURNITURES,
                   ["ciment", "béton", "acier", "fer", "brique", "matériaux", "bois"]),
    "P808": Sector("P808", "Équipements Sportifs", SectorType.FOURNITURES,
                   ["équipement sportif", "terrain sport", "gymnase", "salle sport"]),
    "P809": Sector("P809", "Produits Pharmaceutiques", SectorType.FOURNITURES,
                   ["médicament", "pharmacie", "produits chimiques", "réactif"]),
    "P810": Sector("P810", "Alimentation & Restauration", SectorType.FOURNITURES,
                   ["alimentation", "denrée", "viande", "repas", "cantine", "restauration"]),
    "P811": Sector("P811", "Outillage & Équipements", SectorType.FOURNITURES,
                   ["outillage", "outil", "machine", "pièce rechange", "compresseur"]),
    "P812": Sector("P812", "Hygiène & Nettoyage", SectorType.FOURNITURES,
                   ["nettoyage", "hygiène", "désinfection", "savon", "détergent", "produits entretien"]),
    "P813": Sector("P813", "Énergies Renouvelables", SectorType.FOURNITURES,
                   ["solaire", "photovoltaïque", "panneau solaire", "éolien", "biomasse"]),
    "P814": Sector("P814", "Équipements Didactiques", SectorType.FOURNITURES,
                   ["équipement pédagogique", "scolaire", "didactique", "tableau interactif"]),
    "P815": Sector("P815", "Textile & Habillement", SectorType.FOURNITURES,
                   ["textile", "habillement", "uniforme", "tenue", "vêtement", "blouse"]),
    
    # Services (S)
    "S901": Sector("S901", "Développement & Cloud", SectorType.SERVICES,
                   ["développement", "logiciel", "application", "site web", "cloud", "saas", "devops"]),
    "S902": Sector("S902", "Études & Ingénierie", SectorType.SERVICES,
                   ["étude", "ingénierie", "conseil", "consultant", "bureau d'études", "maîtrise d'œuvre"]),
    "S903": Sector("S903", "Audit & Expertise", SectorType.SERVICES,
                   ["audit", "expertise", "comptable", "juridique", "avocat", "notaire", "certification"]),
    "S904": Sector("S904", "Maintenance & Entretien", SectorType.SERVICES,
                   ["maintenance", "entretien", "réparation", "dépannage", "contrat maintenance"]),
    "S905": Sector("S905", "Nettoyage & Propreté", SectorType.SERVICES,
                   ["nettoyage", "propreté", "désinfection", "dératisation", "hygiène locaux"]),
    "S906": Sector("S906", "Gardiennage & Sécurité", SectorType.SERVICES,
                   ["gardiennage", "sécurité", "surveillance", "agent sécurité", "rondier"]),
    "S907": Sector("S907", "Assurance & Mutuelles", SectorType.SERVICES,
                   ["assurance", "mutuelle", "garantie", "responsabilité civile", "prévoyance"]),
    "S908": Sector("S908", "Communication & Marketing", SectorType.SERVICES,
                   ["communication", "marketing", "publicité", "événementiel", "signalétique", "branding"]),
    "S909": Sector("S909", "Formation & Coaching", SectorType.SERVICES,
                   ["formation", "coaching", "séminaire", "certification", "e-learning", "perfectionnement"]),
    "S910": Sector("S910", "Recrutement & RH", SectorType.SERVICES,
                   ["recrutement", "placement", "intérim", "ressources humaines", "externalisation"]),
    "S911": Sector("S911", "Transport & Logistique", SectorType.SERVICES,
                   ["transport", "logistique", "location véhicule", "affrètement", "fret", "coursier"]),
    "S912": Sector("S912", "Restauration & Hôtellerie", SectorType.SERVICES,
                   ["restauration", "traiteur", "hôtel", "hébergement", "catering", "réception"]),
    "S913": Sector("S913", "Impression & Reprographie", SectorType.SERVICES,
                   ["impression", "imprimerie", "reprographie", "édition", "brochure", "flyer"]),
    "S914": Sector("S914", "Environnement & Développement Durable", SectorType.SERVICES,
                   ["environnement", "déchets", "recyclage", "développement durable", "bilan carbone"]),
    "S915": Sector("S915", "Gestion & Administration", SectorType.SERVICES,
                   ["gestion", "administration", "back-office", "secrétariat", "archivage"]),
}

# المناطق المغربية
REGIONS = {
    "Tanger-Tétouan-Al Hoceïma": ["tanger", "tétouan", "tetouan", "al hoceima", "chefchaouen", "larache", "fnideq"],
    "Oriental": ["oujda", "nador", "berkane", "taourirt", "jerada", "driouch", "figuig"],
    "Fès-Meknès": ["fès", "fes", "meknès", "meknes", "ifrane", "taza", "sefrou", "boulemane"],
    "Rabat-Salé-Kénitra": ["rabat", "salé", "sale", "kénitra", "kenitra", "témara", "khémisset"],
    "Béni Mellal-Khénifra": ["béni mellal", "beni mellal", "khénifra", "khenifra", "azilal", "khouribga"],
    "Casablanca-Settat": ["casablanca", "settat", "mohammedia", "berrechid", "benslimane", "bouskoura"],
    "Marrakech-Safi": ["marrakech", "safi", "essaouira", "kelaa", "youssoufia", "chichaoua"],
    "Drâa-Tafilalet": ["errachidia", "ouarzazate", "zagora", "midelt", "tinghir"],
    "Souss-Massa": ["agadir", "tiznit", "taroudant", "inezgane", "aït melloul", "biougra"],
    "Guelmim-Oued Noun": ["guelmim", "tan-tan", "sidi ifni", "assa", "zag"],
    "Laâyoune-Sakia El Hamra": ["laayoune", "laâyoune", "boujdour", "tarfaya", "smara"],
    "Dakhla-Oued Ed-Dahab": ["dakhla", "aousserd"],
}

CANCEL_KEYWORDS = ["annulé", "annulée", "infructueux", "reporté", "suspendu", "ajourné", "abandonné", "résilié", "caduc"]
AO_KEYWORDS = [
    "appel d'offres", "appel d offres", "consultation", "marché public",
    "fourniture", "travaux", "prestation", "acquisition", "maintenance",
    "construction", "réhabilitation", "étude", "mission", "location",
    "nettoyage", "gardiennage", "transport", "formation", "audit"
]

# ============================================================
# محرك استخراج التواريخ المحسن
# ============================================================

def extract_date(text: str) -> Optional[date]:
    """استخراج التاريخ من النص بغض النظر عن الكلمات المحيطة."""
    if not text:
        return None
    # أنماط التاريخ (مع إمكانية وجود نص مدمج)
    patterns = [
        (r'(\d{2})/(\d{2})/(\d{4})', '%d/%m/%Y'),
        (r'(\d{4})-(\d{2})-(\d{2})', '%Y-%m-%d'),
        (r'(\d{2})-(\d{2})-(\d{4})', '%d-%m-%Y'),
        (r'(\d{2})\.(\d{2})\.(\d{4})', '%d.%m.%Y'),
        (r'(\d{4})/(\d{2})/(\d{2})', '%Y/%m/%d'),
    ]
    for pattern, fmt in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return datetime.strptime(match.group(0), fmt).date()
            except ValueError:
                continue
    return None

def is_expired(date_str: str) -> bool:
    if not date_str:
        return False
    d = extract_date(date_str)
    return d is not None and d < date.today()

# ============================================================
# التصنيف الذكي
# ============================================================

class SmartClassifier:
    @staticmethod
    def classify_sector(title: str, description: str = "") -> Tuple[str, str, float]:
        text = f"{title} {description}".lower()
        scores = {}
        for code, sector in SECTORS.items():
            score = 0
            for kw in sector.keywords:
                if kw in text:
                    score += len(kw) * sector.weight
            if score > 0:
                scores[code] = score
        if not scores:
            return "P825", "Fournitures de Bureau", 0.0
        best = max(scores, key=scores.get)
        max_score = scores[best]
        confidence = min(max_score / 100, 1.0)
        return best, SECTORS[best].label, confidence

    @staticmethod
    def classify_region(text: str) -> str:
        t = text.lower()
        for region, keywords in REGIONS.items():
            if any(kw in t for kw in keywords):
                return region
        return "Maroc"

    @staticmethod
    def classify_type(text: str) -> str:
        t = text.lower()
        if any(kw in t for kw in SECTORS["T101"].keywords + ["travaux", "construction", "réhabilitation", "rénovation"]):
            return "Travaux"
        if any(kw in t for kw in SECTORS["S901"].keywords + ["service", "prestation", "maintenance", "étude", "formation"]):
            return "Services"
        return "Fournitures"

    @staticmethod
    def calculate_score(tender: Dict) -> int:
        score = 50
        if tender.get('date_limite'):
            dl = extract_date(tender['date_limite'])
            if dl:
                days_left = (dl - date.today()).days
                if 0 <= days_left <= 30:
                    score += 20
                elif days_left > 30:
                    score += 10
        budget = tender.get('montant_estime', '')
        if budget:
            try:
                montant = int(re.sub(r'[^\d]', '', budget))
                if montant > 1_000_000:
                    score += 20
                elif montant > 500_000:
                    score += 10
            except:
                pass
        if tender.get('description') and len(tender['description']) > 200:
            score += 10
        if len(tender.get('objet', '')) < 30:
            score -= 20
        return min(max(score, 0), 100)

# ============================================================
# سكرابر الموقع الرسمي (معدل)
# ============================================================

class MarchespublicsScraper:
    BASE_URL = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show"
    LIST_URL = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'Accept-Language': 'fr-FR,fr;q=0.9,ar;q=0.8',
        })
        self.classifier = SmartClassifier()

    def get_listing_ids(self, page: int = 1) -> List[str]:
        try:
            url = f"{self.LIST_URL}?page={page}"
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, 'html.parser')
            ids = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '/show/' in href:
                    m = re.search(r'/show/(\d+)', href)
                    if m:
                        ids.append(m.group(1))
            return list(set(ids))
        except Exception as e:
            print(f"Erreur listing: {e}")
            return []

    def scrape_detail(self, tender_id: str) -> Optional[Dict]:
        try:
            url = f"{self.BASE_URL}/{tender_id}"
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, 'html.parser')
            text = soup.get_text()

            # التحقق من الإلغاء
            if any(kw in text.lower() for kw in CANCEL_KEYWORDS):
                return None

            # ========== استخراج العنوان الحقيقي ==========
            objet = ""
            # 1. محاولة h1 (العنوان الرئيسي)
            h1 = soup.find('h1')
            if h1:
                objet = h1.get_text(strip=True)
                # إزالة بادئات مثل "Détails de l'avis d'achat #..."
                objet = re.sub(r'^Détails de l\'avis d\'achat\s*#?\d*\s*', '', objet, flags=re.I)
                objet = re.sub(r'^Avis d\'appel à la concurrence\s*#?\d*\s*', '', objet, flags=re.I)
            # 2. محاولة div أو span بكلاس "objet-marche" أو "objet"
            if not objet:
                obj_div = soup.find('div', class_='objet-marche') or soup.find('span', class_='objet')
                if obj_div:
                    objet = obj_div.get_text(strip=True)
            # 3. محاولة title
            if not objet:
                title_tag = soup.find('title')
                if title_tag:
                    objet = title_tag.get_text(strip=True)
                    objet = re.sub(r'\s*[|–\-]\s*.*marchés publics.*', '', objet, flags=re.I)
                    objet = re.sub(r'\s*[|–\-]\s*.*portail.*', '', objet, flags=re.I)
                    objet = re.sub(r'^Détails de l\'avis d\'achat\s*#?\d*\s*', '', objet, flags=re.I)
            # 4. أول فقرة طويلة كحل أخير
            if not objet or len(objet) < 20:
                first_p = soup.find('p')
                if first_p:
                    objet = first_p.get_text(strip=True)

            if not objet or len(objet) < 20:
                return None

            # ========== استخراج التاريخ ==========
            date_limite = ""
            # نبحث عن الجملة التي تحتوي على "Date limite" أو "Réception des offres" ونلتقط أقرب تاريخ
            date_patterns = [
                r'Date limite de réception des devis\s*(\d{2}/\d{2}/\d{4})',
                r'Date limite de réception des offres\s*(\d{2}/\d{2}/\d{4})',
                r'Remise des offres\s*(\d{2}/\d{2}/\d{4})',
                r'Clôture\s*(\d{2}/\d{2}/\d{4})',
                r'(\d{2}/\d{2}/\d{4})'  # أي تاريخ
            ]
            for pattern in date_patterns:
                m = re.search(pattern, text, re.I)
                if m:
                    date_limite = m.group(1)
                    break

            # ========== استخراج المشتري ==========
            acheteur = ""
            for kw in ["acheteur public", "maître d'ouvrage", "organisme acheteur"]:
                pattern = rf"{kw}[:\s]*([^\n]+)"
                m = re.search(pattern, text, re.I)
                if m:
                    acheteur = m.group(1).strip()[:200]
                    break

            # ========== استخراج المبلغ ==========
            montant = ""
            for kw in ["montant estimé", "montant", "budget"]:
                pattern = rf"{kw}[:\s]*([\d\s]+\.?\d*)\s*(DH|MAD|درهم)"
                m = re.search(pattern, text, re.I)
                if m:
                    montant = m.group(1).strip()
                    break

            # التصنيف
            code, domaine, _ = self.classifier.classify_sector(objet, text)
            region = self.classifier.classify_region(f"{acheteur} {text[:500]}")
            type_marche = self.classifier.classify_type(objet)
            days_left = None
            if date_limite:
                dl = extract_date(date_limite)
                if dl:
                    days_left = (dl - date.today()).days

            return {
                'id': f"bdc_{tender_id}",
                'objet': objet[:400],
                'description': text[:2000],
                'acheteur': acheteur,
                'region': region,
                'domaine_code': code,
                'domaine': f"{code} · {domaine}",
                'type_marche': type_marche,
                'date_limite': date_limite,
                'date_publication': '',
                'days_left': days_left,
                'urgence': 1 if (days_left is not None and 0 <= days_left <= 14) else 0,
                'montant_estime': montant,
                'source': 'marchespublics',
                'source_type': 'public',
                'url': url,
                'score': self.classifier.calculate_score({'objet': objet, 'date_limite': date_limite, 'montant_estime': montant}),
                'statut': 'actif' if not (date_limite and is_expired(date_limite)) else 'expire'
            }
        except Exception as e:
            print(f"Erreur scraping {tender_id}: {e}")
            return None

    def scrape_recent(self, max_pages: int = 5) -> List[Dict]:
        all_ids = []
        for page in range(1, max_pages + 1):
            ids = self.get_listing_ids(page)
            all_ids.extend(ids)
            time.sleep(0.5)
        results = []
        for tid in all_ids:
            t = self.scrape_detail(tid)
            if t and t.get('statut') == 'actif':
                results.append(t)
            time.sleep(0.3)
        return results

# ============================================================
# سكرابر الجرائد (مختصر)
# ============================================================

class NewspaperScraper:
    SOURCES = {
        'leconomiste': {
            'url': 'https://www.leconomiste.com/appels-offres',
            'article_selector': 'article, .node, .view-content .views-row',
            'title_selector': 'h2, h3, .title, a',
            'date_selector': '.date, .submitted, time',
        },
        'lematin': {
            'url': 'https://lematin.ma/annonces-legales/',
            'article_selector': '.article, .item, .post',
            'title_selector': 'h2, h3, .title',
            'date_selector': '.date, .meta',
        },
        'flasheconomie': {
            'url': 'https://flasheconomie.ma/category/annonces-legales/',
            'article_selector': 'article, .post',
            'title_selector': 'h2, .entry-title',
            'date_selector': '.date, .post-date',
        }
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        self.classifier = SmartClassifier()

    def is_ao(self, text: str) -> bool:
        t = text.lower()
        exclude = ['offre d\'emploi', 'emploi', 'recrutement', 'carrière', 'stage']
        if any(kw in t for kw in exclude):
            return False
        include = ['appel d\'offres', 'appel d offres', 'marché public', 'consultation']
        if any(kw in t for kw in include):
            return True
        ao_count = sum(1 for kw in AO_KEYWORDS if kw in t)
        return ao_count >= 2

    def extract_date_from_text(self, text: str) -> Optional[str]:
        for pattern in [r'(\d{2}/\d{2}/\d{4})', r'(\d{4}-\d{2}-\d{2})', r'(\d{2}-\d{2}-\d{4})']:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        return None

    def scrape_source(self, source_name: str) -> List[Dict]:
        if source_name not in self.SOURCES:
            return []
        source = self.SOURCES[source_name]
        results = []
        try:
            resp = self.session.get(source['url'], timeout=15)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, 'html.parser')
            articles = soup.select(source['article_selector'])
            for art in articles:
                text = art.get_text()
                if not self.is_ao(text):
                    continue
                title_elem = art.select_one(source['title_selector'])
                title = title_elem.get_text(strip=True) if title_elem else text[:200]
                date_elem = art.select_one(source['date_selector'])
                date_str = date_elem.get_text(strip=True) if date_elem else ""
                date_limite = self.extract_date_from_text(date_str or text)
                code, domaine, _ = self.classifier.classify_sector(title, text)
                region = self.classifier.classify_region(text)
                type_marche = self.classifier.classify_type(title)
                results.append({
                    'id': hashlib.md5(f"{source_name}_{title}".encode()).hexdigest()[:16],
                    'objet': title[:400],
                    'description': text[:2000],
                    'acheteur': '',
                    'region': region,
                    'domaine_code': code,
                    'domaine': f"{code} · {domaine}",
                    'type_marche': type_marche,
                    'date_limite': date_limite or '',
                    'date_publication': '',
                    'days_left': None,
                    'urgence': 0,
                    'montant_estime': '',
                    'source': source_name,
                    'source_type': 'presse',
                    'url': source['url'],
                    'score': self.classifier.calculate_score({'objet': title}),
                    'statut': 'actif' if not (date_limite and is_expired(date_limite)) else 'expire'
                })
        except Exception as e:
            print(f"Erreur {source_name}: {e}")
        return results

    def scrape_all(self) -> List[Dict]:
        all_results = []
        for src in self.SOURCES:
            all_results.extend(self.scrape_source(src))
            time.sleep(1)
        return all_results

# ============================================================
# السكرابر الرئيسي
# ============================================================

class UltimateScraper:
    def __init__(self):
        self.marchespublics = MarchespublicsScraper()
        self.newspapers = NewspaperScraper()
        self.classifier = SmartClassifier()

    def scrape_all(self, max_pages: int = 5) -> List[Dict]:
        print("="*60)
        print("Ultimate Scraper - جمع الصفقات من جميع المصادر")
        print("="*60)

        all_tenders = []

        print("\n📡 Source 1: marchespublics.gov.ma")
        public = self.marchespublics.scrape_recent(max_pages)
        print(f"   → {len(public)} صفقة نشطة")
        all_tenders.extend(public)

        print("\n📰 Source 2: Journaux légaux")
        press = self.newspapers.scrape_all()
        print(f"   → {len(press)} صفقة")
        all_tenders.extend(press)

        active = [t for t in all_tenders if t.get('statut') == 'actif']

        print("\n" + "="*60)
        print(f"✅ Total: {len(active)} صفقة نشطة")
        print("="*60)

        return active

    def get_statistics(self, tenders: List[Dict]) -> Dict:
        stats = {
            'total': len(tenders),
            'by_type': {'Travaux': 0, 'Fournitures': 0, 'Services': 0},
            'by_region': {},
            'urgent': 0,
            'avg_score': 0,
        }
        total_score = 0
        for t in tenders:
            typ = t.get('type_marche', 'Autre')
            if typ in stats['by_type']:
                stats['by_type'][typ] += 1
            reg = t.get('region', 'Maroc')
            stats['by_region'][reg] = stats['by_region'].get(reg, 0) + 1
            if t.get('urgence'):
                stats['urgent'] += 1
            total_score += t.get('score', 0)
        if stats['total'] > 0:
            stats['avg_score'] = total_score // stats['total']
        return stats

if __name__ == "__main__":
    scraper = UltimateScraper()
    tenders = scraper.scrape_all()
    stats = scraper.get_statistics(tenders)
    print("\n📊 Statistiques:")
    print(f"   Total: {stats['total']}")
    print(f"   Travaux: {stats['by_type']['Travaux']}")
    print(f"   Fournitures: {stats['by_type']['Fournitures']}")
    print(f"   Services: {stats['by_type']['Services']}")
    print(f"   Urgent: {stats['urgent']}")
    print(f"   Score moyen: {stats['avg_score']}/100")

    print("\n📋 Dernières offres:")
    for t in tenders[:5]:
        print(f"\n   [{t['domaine_code']}] {t['objet'][:80]}")
        print(f"   🏢 {t['acheteur'] or 'N/A'}")
        print(f"   📍 {t['region']}")
        print(f"   ⏰ {t['date_limite'] or 'Date non précisée'}")
        print(f"   🎯 Score: {t['score']}/100")