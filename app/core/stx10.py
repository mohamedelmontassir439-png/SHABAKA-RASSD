"""
SOURCE — Classificateur STX10 Sémantique
Stratégie: IA (Groq) → Fallback hybride TF-IDF-like
"""
import re, json, logging, requests
from app.core.config import cfg

logger = logging.getLogger("source.stx10")

STX10 = {
    "T101": "Travaux de construction et réhabilitation de bâtiments",
    "T102": "Terrassements et travaux de sol",
    "T103": "Menuiserie, métallerie et charpente",
    "T104": "Plomberie, chauffage et climatisation",
    "T105": "Peinture et vitrerie",
    "T106": "Étanchéité et isolation",
    "T107": "Revêtements (carrelage, parquet, dallage)",
    "T108": "Plâtrerie et faux plafonds",
    "T109": "Ascenseurs et monte-charges",
    "T110": "Génie civil, VRD et aménagements urbains",
    "T111": "Espaces verts et jardins",
    "T201": "Assainissement et réseaux de conduite",
    "T202": "Fondations spéciales et forages",
    "T203": "Travaux hydromécaniques et traitement d'eau",
    "T301": "Travaux routiers et voies ferrées",
    "T302": "Signalisation routière",
    "T401": "Électricité et éclairage public",
    "T402": "Sécurité, vidéosurveillance et sonorisation",
    "T403": "Télécommunications et réseaux informatiques",
    "T501": "Travaux topographiques et photogrammétrie",
    "T601": "Travaux agricoles et irrigation",
    "P805": "Mobilier de bureau",
    "P812": "Équipements électriques",
    "P813": "Équipements médicaux et de laboratoire",
    "P814": "Équipements de climatisation",
    "P815": "Engins et matériel de manutention",
    "P816": "Véhicules et matériel roulant",
    "P817": "Matériel didactique et pédagogique",
    "P818": "Équipements et accessoires informatiques",
    "P825": "Fournitures de bureau et papeterie",
    "P831": "Combustibles et lubrifiants",
    "P833": "Produits pharmaceutiques",
    "P836": "Imprimerie et reprographie",
    "P837": "Textile, vêtements et uniformes",
    "P839": "Matériaux de construction",
    "P841": "Produits d'hygiène et de nettoyage",
    "P843": "Matériel de laboratoire et d'analyse",
    "P850": "Énergie solaire et photovoltaïque",
    "S901": "Développement logiciel et systèmes d'information",
    "S902": "Études générales, conseil et expertise",
    "S903": "Maîtrise d'œuvre BTP",
    "S906": "Maintenance, réparation et entretien",
    "S907": "Nettoyage et hygiène",
    "S908": "Gardiennage et sécurité",
    "S910": "Publicité et communication",
    "S911": "Restauration, traiteur et hébergement",
    "S912": "Services d'assurance",
    "S913": "Formation et ingénierie pédagogique",
    "S914": "Location et concession",
    "S915": "Transport et location de véhicules",
    "S917": "Organisation d'événements",
    "S918": "Traitement et collecte des déchets",
    "S919": "Archivage et gestion documentaire",
    "S931": "Licences logiciels et solutions informatiques",
}

STX10_AR = {
    "T101": "أشغال البناء وإعادة التأهيل",
    "T110": "الهندسة المدنية والتهيئة العمرانية",
    "T201": "الصرف الصحي وشبكات القنوات",
    "T301": "أشغال الطرق والسكك الحديدية",
    "T401": "الكهرباء والإنارة العمومية",
    "T403": "الاتصالات والشبكات المعلوماتية",
    "T501": "أشغال المسح الطبوغرافي",
    "P818": "المعدات والملحقات المعلوماتية",
    "P813": "المعدات الطبية والمخبرية",
    "P816": "المركبات والمعدات المتنقلة",
    "P850": "الطاقة الشمسية والكهروضوئية",
    "S901": "تطوير البرمجيات وأنظمة المعلومات",
    "S902": "الدراسات العامة والاستشارة",
    "S906": "الصيانة والإصلاح",
    "S907": "النظافة والصحة",
    "S908": "الحراسة والأمن",
    "S913": "التكوين والهندسة البيداغوجية",
}

# Règles sémantiques par contexte d'usage (pas juste mots-clés)
SEMANTIC_RULES = [
    # Construction — sens: créer ou rénover un bâtiment physique
    (["construction","réhabilitation","rénovation","extension bâtiment","édifice",
      "école","lycée","hôpital","mosquée","stade","immeuble","villa","résidence",
      "bâtiment","salle","parking","hangar"], "T101"),
    # Sol — sens: travailler sur la terre avant construction
    (["terrassement","déblai","remblai","fouille","excavation","nivellement","compactage"], "T102"),
    # Menuiserie — sens: éléments d'ouvrage en bois/métal/aluminium
    (["menuiserie","charpente","ferronnerie","portail","fenêtre","porte aluminium",
      "serrurerie","garde-corps","métallerie","structure métallique"], "T103"),
    # Fluides — sens: eau, chaleur, froid dans un bâtiment
    (["plomberie","chauffage","climatisation","hvac","vmc","sanitaire","chaudière",
      "robinetterie","tuyauterie","pompe chaleur"], "T104"),
    # Finition surface — sens: couvrir les surfaces
    (["peinture","vitrerie","revêtement mural","enduit","ravalement"], "T105"),
    # Étanchéité — sens: protéger contre l'eau
    (["étanchéité","isolation","imperméabilisation","bitume","membrane","toiture étanche"], "T106"),
    # Sol fini — sens: revêtement de sol
    (["carrelage","dallage","revêtement sol","parquet","faïence","marbre","zellige"], "T107"),
    # Cloisons intérieures
    (["plâtrerie","faux plafond","cloison","plaque de plâtre","doublage"], "T108"),
    # Vertical transport
    (["ascenseur","monte-charge","élévateur"], "T109"),
    # Urbain — sens: espace public, voirie
    (["génie civil","vrd","voirie","caniveau","bordure","trottoir","clôture",
      "aménagement urbain","mur de soutènement"], "T110"),
    # Végétation
    (["espace vert","jardin","plantation","gazon","arrosage automatique"], "T111"),
    # Eau/égout — sens: réseau sous-terrain
    (["assainissement","canalisation","égout","adduction eau","réseau eau potable",
      "station épuration","collecteur"], "T201"),
    # Sol profond
    (["fondation spéciale","micropieu","pieu","injection sol","sondage","forage",
      "géotechnique"], "T202"),
    # Eau + machines
    (["station pompage","traitement eau","potabilisation","filtration eau","hydromécanique"], "T203"),
    # Transport terrestre
    (["route","chaussée","autoroute","bitume","enrobé","asphalte","piste",
      "réhabilitation route","déviation"], "T301"),
    # Signalisation
    (["signalisation routière","panneau route","marquage","glissière","feux tricolores"], "T302"),
    # Énergie électrique
    (["électricité","éclairage public","câblage","installation électrique",
      "tableau électrique","transformateur","réseau électrique","lampadaire",
      "poste hta","basse tension"], "T401"),
    # Sécurité électronique
    (["vidéosurveillance","cctv","alarme","contrôle accès","ssi",
      "sécurité incendie","sonorisation","interphone"], "T402"),
    # Data/télécoms
    (["télécommunication","fibre optique","réseau informatique","câblage réseau",
      "wifi","data center","courant faible","câblage structuré"], "T403"),
    # Cartographie terrain
    (["topographie","levé topographique","photogrammétrie","gps topographique",
      "plan cadastral","lidar","bathymétrie","maquette numérique"], "T501"),
    # Agriculture
    (["travaux agricoles","irrigation","serre","périmètre irrigué","drainage agricole"], "T601"),
    # Mobilier
    (["mobilier bureau","chaise bureau","armoire","bureau meuble","rayonnage","meuble"], "P805"),
    # Équip électrique
    (["tableau électrique","disjoncteur","câble électrique","onduleur",
      "groupe électrogène","ups","batterie"], "P812"),
    # Médical
    (["équipement médical","scanner","radiologie","échographe","bloc opératoire",
      "matériel médical","consommable médical","lit hôpital"], "P813"),
    # Froid
    (["climatiseur","split","vrf","groupe froid","unité climatisation"], "P814"),
    # Levage
    (["chariot élévateur","engin tp","pelleteuse","grue","nacelle","transpalette"], "P815"),
    # Véhicules — sens: acquérir des véhicules
    (["véhicule","voiture","camion","bus","ambulance","minibus","fourgon",
      "flotte automobile"], "P816"),
    # Pédagogie
    (["matériel pédagogique","tableau interactif","équipement éducatif",
      "kit scolaire","matériel didactique"], "P817"),
    # IT hardware — sens: acheter du matériel informatique
    (["ordinateur","pc","laptop","serveur","imprimante","scanner","tablette",
      "matériel informatique","hardware","switch","routeur","nas","stockage"], "P818"),
    # Papeterie
    (["fournitures bureau","papeterie","cartouche","toner","ramette",
      "consommable bureau"], "P825"),
    # Carburant
    (["carburant","gasoil","essence","fuel","lubrifiant","huile moteur"], "P831"),
    # Médicaments
    (["médicament","produit pharmaceutique","consommable laboratoire",
      "réactif médical","vaccin"], "P833"),
    # Print
    (["imprimerie","impression","reprographie","publication","édition",
      "brochure","flyer","affiche"], "P836"),
    # Textile
    (["tenue","uniforme","vêtement de travail","textile","habillement",
      "blouse","epi","chaussure sécurité"], "P837"),
    # Matériaux
    (["ciment","béton","sable","gravier","brique","parpaing",
      "matériaux construction","acier construction"], "P839"),
    # Nettoyage produit
    (["produit nettoyage","désinfectant","javel","entretien ménager",
      "produit hygiène"], "P841"),
    # Labo
    (["équipement laboratoire","analyseur","centrifugeuse","microscope",
      "ph mètre","matériel analyse"], "P843"),
    # Solaire — sens: capter énergie solaire
    (["photovoltaïque","panneau solaire","énergie solaire","pv","centrale solaire",
      "chauffe-eau solaire","onduleur solaire","installation solaire"], "P850"),
    # IT software — sens: créer ou déployer un logiciel
    (["développement logiciel","application web","site web","système information",
      "erp","crm","intranet","plateforme numérique","digitalisation",
      "transformation digitale","application mobile","portail"], "S901"),
    # Conseil — sens: étude, analyse, recommandation
    (["étude","conseil","consulting","audit","expertise","diagnostic",
      "assistance technique","faisabilité","schéma directeur","master plan",
      "plan directeur"], "S902"),
    # MOE
    (["maîtrise d'oeuvre","moe","avant-projet","apd","dce",
      "bureau contrôle","coordination sécurité"], "S903"),
    # Entretien — sens: maintenir en état de fonctionnement
    (["maintenance","entretien","réparation","dépannage","contrat maintenance",
      "maintenance préventive","maintenance corrective","gmao"], "S906"),
    # Nettoyage service
    (["nettoyage locaux","propreté","désinsectisation","dératisation",
      "entretien ménager","nettoyage industriel"], "S907"),
    # Sécurité humaine
    (["gardiennage","sécurité gardiennage","surveillance","agent sécurité",
      "rondes","intérim sécurité"], "S908"),
    # Comm
    (["publicité","communication","campagne","média","affichage",
      "community management","relations presse","web marketing"], "S910"),
    # Repas
    (["restauration","traiteur","réception","buffet","repas","cantine",
      "restaurant scolaire","hébergement"], "S911"),
    # Assurance
    (["assurance","mutuelles","police assurance","responsabilité civile",
      "assurance véhicule"], "S912"),
    # Formation — sens: développer compétences humaines
    (["formation","stage","séminaire","atelier","workshop","certification",
      "e-learning","ingénierie pédagogique","formateur"], "S913"),
    # Location
    (["location matériel","concession","mise à disposition","bail"], "S914"),
    # Transport service
    (["transport personnes","navette","taxi","location voiture service",
      "transport scolaire"], "S915"),
    # Événement
    (["événementiel","organisation événement","conférence","colloque",
      "salon","forum","journée","cérémonie"], "S917"),
    # Déchets
    (["déchet","collecte déchets","recyclage","déchetterie","ordures"], "S918"),
    # Archivage
    (["archivage","gestion archives","ged","dématérialisation","numérisation documents"], "S919"),
    # Licences
    (["licence logiciel","microsoft","oracle","sap","windows server",
      "antivirus","logiciel comptabilité"], "S931"),
]

def _ai_classify(text: str) -> dict:
    """Appel Groq pour classification sémantique profonde"""
    if not cfg.GROQ_API_KEY or not text:
        return {}
    try:
        codes_str = "\n".join([f"  {c}: {l}" for c,l in list(STX10.items())[:40]])
        codes_str2 = "\n".join([f"  {c}: {l}" for c,l in list(STX10.items())[40:]])
        prompt = f"""Expert marchés publics marocains. Classifie selon STX10.

Codes (1/2):
{codes_str}
Codes (2/2):
{codes_str2}

Marché: {text[:500]}

Règle: comprends l'OBJECTIF du marché, pas les mots.
Ex: "Construction d'une école" → T101 (bâtiment), pas éducation.
Ex: "Acquisition d'ordinateurs" → P818 (hardware IT).
Ex: "Développement application" → S901 (logiciel).

JSON uniquement: {{"code":"T101","label":"description courte","confidence":0.9}}"""

        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": cfg.AI_MODEL, "max_tokens": 150,
                  "messages": [{"role":"user","content":prompt}],
                  "temperature": 0.1,
                  "response_format": {"type":"json_object"}},
            timeout=10
        )
        if r.status_code == 200:
            data = json.loads(r.json()["choices"][0]["message"]["content"])
            if data.get("code") and data["code"] in STX10:
                return data
    except Exception as e:
        logger.debug(f"[AI classify] {e}")
    return {}

def _hybrid_classify(text: str) -> dict:
    """Règles sémantiques pondérées — fallback robuste"""
    if not text:
        return {"code":"S902","label":STX10["S902"],"confidence":0.3}
    t = text.lower()
    scores = {}
    for keywords, code in SEMANTIC_RULES:
        score = 0
        for kw in keywords:
            if kw in t:
                w = len(kw.split())*2 + len(kw)*0.1
                if kw in t[:150]: w *= 2.0  # Titre = plus important
                score += w
        if score > 0:
            scores[code] = scores.get(code, 0) + score
    if not scores:
        return {"code":"S902","label":STX10["S902"],"confidence":0.3}
    best = max(scores, key=scores.get)
    mx = scores[best]
    conf = min(0.92, mx/(mx+12))
    return {"code":best,"label":STX10.get(best,""),"confidence":round(conf,2)}

def classify(text: str) -> dict:
    """Interface principale: IA → fallback hybride"""
    if not text:
        return {"code":"S902","label":STX10["S902"],"confidence":0.3}
    ai = _ai_classify(text)
    if ai and ai.get("confidence",0) >= 0.65:
        ai.setdefault("label", STX10.get(ai["code"],""))
        return ai
    return _hybrid_classify(text)

def top3(text: str) -> list:
    """Top 3 codes pour matching membre"""
    if not text: return []
    t = text.lower()
    scores = {}
    for keywords, code in SEMANTIC_RULES:
        score = 0
        for kw in keywords:
            if kw in t:
                w = len(kw.split())*2 + len(kw)*0.1
                if kw in t[:150]: w *= 2.0
                score += w
        if score > 0: scores[code] = scores.get(code,0)+score
    return [{"code":c,"label":STX10.get(c,""),"score":s}
            for c,s in sorted(scores.items(),key=lambda x:x[1],reverse=True)[:3]]

def match_member(tender_text: str, member_codes: list) -> list:
    """Matching sémantique tender ↔ préférences membre"""
    if not member_codes or not tender_text: return []
    t3 = [r["code"] for r in top3(tender_text)]
    matches = [c for c in member_codes if c in t3]
    if not matches:
        for mc in member_codes:
            fam = mc[:2]
            for tc in t3:
                if tc.startswith(fam): matches.append(mc); break
    return list(set(matches))
