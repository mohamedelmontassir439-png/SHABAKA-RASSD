"""SOURCE — Classificateur STX10 Sémantique v2"""
import json, logging, requests
from app.core.config import cfg
logger = logging.getLogger("source.stx10")

STX10 = {
    "T101":"Travaux de construction et réhabilitation de bâtiments",
    "T102":"Terrassements et travaux de sol",
    "T103":"Menuiserie, métallerie et charpente",
    "T104":"Plomberie, chauffage et climatisation",
    "T105":"Peinture et vitrerie",
    "T106":"Étanchéité et isolation",
    "T107":"Revêtements (carrelage, parquet, dallage)",
    "T108":"Plâtrerie et faux plafonds",
    "T109":"Ascenseurs et monte-charges",
    "T110":"Génie civil, VRD et aménagements urbains",
    "T111":"Espaces verts et jardins",
    "T201":"Assainissement et réseaux de conduite",
    "T202":"Fondations spéciales et forages",
    "T203":"Travaux hydromécaniques et traitement d'eau",
    "T301":"Travaux routiers et voies ferrées",
    "T302":"Signalisation routière",
    "T401":"Électricité et éclairage public",
    "T402":"Sécurité, vidéosurveillance et sonorisation",
    "T403":"Télécommunications et réseaux informatiques",
    "T501":"Travaux topographiques et photogrammétrie",
    "T601":"Travaux agricoles et irrigation",
    "P805":"Mobilier de bureau",
    "P812":"Équipements électriques",
    "P813":"Équipements médicaux et de laboratoire",
    "P814":"Équipements de climatisation",
    "P815":"Engins et matériel de manutention",
    "P816":"Véhicules et matériel roulant",
    "P817":"Matériel didactique et pédagogique",
    "P818":"Équipements et accessoires informatiques",
    "P825":"Fournitures de bureau et papeterie",
    "P831":"Combustibles et lubrifiants",
    "P833":"Produits pharmaceutiques",
    "P836":"Imprimerie et reprographie",
    "P837":"Textile, vêtements et uniformes",
    "P839":"Matériaux de construction",
    "P841":"Produits d'hygiène et de nettoyage",
    "P843":"Matériel de laboratoire et d'analyse",
    "P850":"Énergie solaire et photovoltaïque",
    "S901":"Développement logiciel et systèmes d'information",
    "S902":"Études générales, conseil et expertise",
    "S903":"Maîtrise d'œuvre BTP",
    "S906":"Maintenance, réparation et entretien",
    "S907":"Nettoyage et hygiène",
    "S908":"Gardiennage et sécurité",
    "S910":"Publicité et communication",
    "S911":"Restauration, traiteur et hébergement",
    "S912":"Services d'assurance",
    "S913":"Formation et ingénierie pédagogique",
    "S914":"Location et concession",
    "S915":"Transport et location de véhicules",
    "S917":"Organisation d'événements",
    "S918":"Traitement et collecte des déchets",
    "S919":"Archivage et gestion documentaire",
    "S931":"Licences logiciels et solutions informatiques",
}

# Règles sémantiques — sens de l'activité, pas mots-clés bruts
RULES = [
    (["construction","réhabilitation","rénovation","bâtiment","édifice","école","hôpital","immeuble","mosquée","salle","résidence","siège","bureau bâtiment","logement","villa"], "T101"),
    (["terrassement","déblai","remblai","fouille","excavation","nivellement","compactage"], "T102"),
    (["menuiserie","charpente","ferronnerie","portail","fenêtre","porte aluminium","métallerie","serrurerie","garde-corps"], "T103"),
    (["plomberie","chauffage","climatisation","hvac","sanitaire","chaudière","tuyauterie","vmc"], "T104"),
    (["peinture","vitrerie","enduit","ravalement","façade peinture"], "T105"),
    (["étanchéité","isolation","bitume","membrane","toiture étanche"], "T106"),
    (["carrelage","dallage","revêtement sol","parquet","faïence","marbre","zellige"], "T107"),
    (["plâtrerie","faux plafond","cloison","plaque de plâtre","doublage"], "T108"),
    (["ascenseur","monte-charge","élévateur"], "T109"),
    (["génie civil","vrd","voirie","caniveau","bordure","trottoir","clôture","aménagement urbain"], "T110"),
    (["espace vert","jardin","plantation","gazon","arrosage automatique","paysager"], "T111"),
    (["assainissement","canalisation","égout","adduction eau","réseau eau potable","station épuration"], "T201"),
    (["fondation spéciale","micropieu","pieu","injection sol","sondage","forage","géotechnique"], "T202"),
    (["station pompage","traitement eau","potabilisation","filtration eau"], "T203"),
    (["route","chaussée","autoroute","bitume","enrobé","asphalte","piste"], "T301"),
    (["signalisation routière","panneau route","marquage","glissière","feux tricolores"], "T302"),
    (["électricité","éclairage public","câblage électrique","installation électrique","tableau électrique","transformateur","réseau électrique","lampadaire"], "T401"),
    (["vidéosurveillance","cctv","alarme","contrôle accès","ssi","sécurité incendie","sonorisation"], "T402"),
    (["télécommunication","fibre optique","réseau informatique","câblage réseau","wifi infrastructure","data center"], "T403"),
    (["topographie","levé topographique","photogrammétrie","gps topographique","plan cadastral","lidar","bathymétrie"], "T501"),
    (["travaux agricoles","irrigation","serre","périmètre irrigué"], "T601"),
    (["mobilier bureau","chaise bureau","armoire bureau","bureau meuble","rayonnage"], "P805"),
    (["tableau électrique","disjoncteur","câble électrique","onduleur","groupe électrogène","ups"], "P812"),
    (["équipement médical","scanner","radiologie","échographe","bloc opératoire","matériel médical"], "P813"),
    (["climatiseur","split","vrf","groupe froid","unité climatisation"], "P814"),
    (["chariot élévateur","engin tp","pelleteuse","grue","nacelle","manutention"], "P815"),
    (["véhicule","voiture","camion","bus","ambulance","minibus","fourgon","flotte automobile"], "P816"),
    (["matériel pédagogique","tableau interactif","équipement éducatif","kit scolaire"], "P817"),
    (["ordinateur","pc","laptop","serveur","imprimante","scanner informatique","tablette","matériel informatique","hardware","routeur","switch réseau","nas"], "P818"),
    (["fournitures bureau","papeterie","cartouche","toner","ramette"], "P825"),
    (["carburant","gasoil","essence","fuel","lubrifiant"], "P831"),
    (["médicament","produit pharmaceutique","consommable laboratoire","réactif médical"], "P833"),
    (["imprimerie","impression","reprographie","publication","édition","brochure"], "P836"),
    (["tenue","uniforme","vêtement de travail","textile","habillement"], "P837"),
    (["ciment","béton","sable","gravier","brique","parpaing","matériaux construction"], "P839"),
    (["produit nettoyage","désinfectant","javel","entretien ménager","hygiène produit"], "P841"),
    (["équipement laboratoire","analyseur","centrifugeuse","microscope"], "P843"),
    (["photovoltaïque","panneau solaire","énergie solaire","pv","centrale solaire","onduleur solaire","installation solaire"], "P850"),
    (["développement logiciel","application web","site web","système information","erp","crm","intranet","plateforme numérique","digitalisation","transformation digitale","application mobile"], "S901"),
    (["étude","conseil","consulting","audit","expertise","diagnostic","assistance technique","faisabilité","schéma directeur"], "S902"),
    (["maîtrise d'oeuvre","moe","avant-projet","apd","dce","bureau contrôle btp"], "S903"),
    (["maintenance","entretien","réparation","dépannage","contrat maintenance","préventive corrective"], "S906"),
    (["nettoyage locaux","propreté","désinsectisation","dératisation","entretien ménager"], "S907"),
    (["gardiennage","sécurité gardiennage","surveillance","agent sécurité","rondes"], "S908"),
    (["publicité","communication","campagne","média","affichage","community management"], "S910"),
    (["restauration","traiteur","réception","buffet","repas","cantine"], "S911"),
    (["assurance","mutuelles","police assurance","responsabilité civile"], "S912"),
    (["formation","stage","séminaire","atelier","workshop","certification","e-learning"], "S913"),
    (["location matériel","concession","mise à disposition","bail"], "S914"),
    (["transport personnes","navette","taxi","location voiture service","transport scolaire"], "S915"),
    (["événementiel","organisation événement","conférence","colloque","salon","forum"], "S917"),
    (["déchet","collecte déchets","recyclage","ordures"], "S918"),
    (["archivage","gestion archives","ged","dématérialisation","numérisation documents"], "S919"),
    (["licence logiciel","microsoft","oracle","sap","windows server","antivirus"], "S931"),
]

def _ai(text):
    if not cfg.GROQ_API_KEY or not text: return {}
    try:
        codes = "\n".join(f"  {c}: {l}" for c,l in STX10.items())
        prompt = f"""Expert marchés publics marocains. Code STX10 pour ce marché.
Codes disponibles:
{codes}

Marché: {text[:500]}

RÈGLE IMPORTANTE: comprends l'OBJECTIF, pas les mots.
Ex: "Construction salle de classe" → T101 (bâtiment), PAS éducation.
Ex: "Acquisition ordinateurs" → P818, PAS services.
Ex: "Développement application" → S901, PAS bureau.

JSON uniquement: {{"code":"T101","label":"description","confidence":0.9}}"""
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {cfg.GROQ_API_KEY}"},
            json={"model":cfg.AI_MODEL,"max_tokens":100,"temperature":0.1,
                  "messages":[{"role":"user","content":prompt}],
                  "response_format":{"type":"json_object"}},
            timeout=8)
        if r.status_code==200:
            d = json.loads(r.json()["choices"][0]["message"]["content"])
            if d.get("code") and d["code"] in STX10: return d
    except Exception as e: logger.debug(f"[AI] {e}")
    return {}

def _hybrid(text):
    if not text: return {"code":"S902","label":STX10["S902"],"confidence":0.3}
    t = text.lower()
    scores = {}
    for kws, code in RULES:
        s = 0
        for kw in kws:
            if kw in t:
                w = len(kw.split())*2 + len(kw)*0.1
                if kw in t[:150]: w *= 2.0
                s += w
        if s > 0: scores[code] = scores.get(code,0)+s
    if not scores: return {"code":"S902","label":STX10["S902"],"confidence":0.3}
    best = max(scores, key=scores.get)
    mx = scores[best]
    return {"code":best,"label":STX10.get(best,""),"confidence":round(min(0.92,mx/(mx+12)),2)}

def classify(text):
    if not text: return {"code":"S902","label":STX10["S902"],"confidence":0.3}
    ai = _ai(text)
    if ai and ai.get("confidence",0)>=0.65:
        ai.setdefault("label", STX10.get(ai["code"],""))
        return ai
    return _hybrid(text)

def top3(text):
    if not text: return []
    t = text.lower()
    scores = {}
    for kws,code in RULES:
        s=0
        for kw in kws:
            if kw in t:
                w=len(kw.split())*2+len(kw)*0.1
                if kw in t[:150]: w*=2.0
                s+=w
        if s>0: scores[code]=scores.get(code,0)+s
    return [{"code":c,"label":STX10.get(c,""),"score":s}
            for c,s in sorted(scores.items(),key=lambda x:x[1],reverse=True)[:3]]

def match_member(text, codes):
    if not codes or not text: return []
    t3 = [r["code"] for r in top3(text)]
    matches = [c for c in codes if c in t3]
    if not matches:
        for mc in codes:
            for tc in t3:
                if tc.startswith(mc[:2]): matches.append(mc); break
    return list(set(matches))
