"""
SOURCE — Classification officielle des marchés publics Maroc
Basée sur le référentiel MB SA (maroc-business.com)
83 secteurs organisés en 3 groupes: Travaux / Équipements / Services
"""

# ── Dictionnaire complet code → libellé ──────────────────
SECTORS: dict = {
    # TRAVAUX
    "T101": "Constructions, bâtiments & ouvrages d'art",
    "T102": "Terrassements",
    "T103": "Menuiserie – Métallerie – Charpente",
    "T104": "Plomberie – Chauffage – Climatisation",
    "T105": "Peinture – Vitrerie",
    "T106": "Étanchéité – Isolation",
    "T107": "Revêtement",
    "T108": "Plâtrerie – Faux plafonds",
    "T109": "Monte-charge – Ascenseurs",
    "T110": "Génie civil & aménagements divers",
    "T111": "Espaces verts et jardins",
    "T112": "Aménagements associés aux bâtiments",
    "T201": "Assainissement – Conduite",
    "T202": "Fondations spéciales – Sondages",
    "T203": "Hydromécaniques – Traitement eau potable",
    "T204": "Travaux maritimes et fluviaux",
    "T301": "Travaux routiers et voies ferrées",
    "T302": "Signalisation & équipements route",
    "T401": "Électricité & éclairage public",
    "T402": "Sécurité – Télésurveillance – Sonorisation",
    "T403": "Télécommunications & électroniques",
    "T404": "Isolation frigorifique & chambres froides",
    "T501": "Topographie – Couverture aérienne",
    "T601": "Travaux agricoles",
    # ÉQUIPEMENTS
    "P802": "Équipements électroniques & télécoms",
    "P804": "Sono – Vidéo – Photographie",
    "P805": "Mobilier de Bureau",
    "P806": "Équipements hydrauliques",
    "P808": "Matériels topographiques",
    "P810": "Machinismes agricoles",
    "P812": "Équipements électriques",
    "P813": "Équipements médicaux & laboratoire",
    "P814": "Équipement de climatisation",
    "P815": "Manutention & engins mobiles",
    "P816": "Matériel roulant & véhicules",
    "P817": "Matériel didactique & pédagogique",
    "P818": "Équipements & accessoires informatiques",
    "P819": "Équipements sportifs & campement",
    "P820": "Équipement technique divers",
    "P821": "Sécurité – Protection – Surveillance",
    "P822": "Matériel & outillage de précision",
    "P823": "Petit matériel & outillage",
    "P824": "Installation cuisine & buanderies",
    "P825": "Fournitures & matériels de Bureau",
    "P830": "Pièces de rechange & produits industriels",
    "P831": "Combustibles & lubrifiants",
    "P832": "Produits chimiques & para-chimiques",
    "P833": "Produits pharmaceutiques & consommables",
    "P834": "Produits alimentaires & agricoles",
    "P836": "Imprimerie – Papeterie – Reprographie",
    "P837": "Confection – Textile – Cuir – Habillement",
    "P838": "Minerais – Métaux – Plastiques – Bois",
    "P839": "Matériaux de construction & préfabriqués",
    "P840": "Ameublement & literie",
    "P841": "Produits hygiène & nettoiement",
    "P843": "Matériels & équipements de laboratoire",
    "P850": "Énergies renouvelables – Solaire",
    "P852": "Énergies renouvelables – Fournitures",
    "P853": "Énergies renouvelables – Autres",
    # SERVICES
    "S901": "Études TIC & développement informatique",
    "S902": "Études générales & Conseil",
    "S903": "Études BTP",
    "S904": "Prestations diverses",
    "S906": "Maintenance – Réparation – Entretien",
    "S907": "Nettoyage & hygiène",
    "S908": "Gardiennage – Sécurité – Intérim",
    "S909": "Concours architecture",
    "S910": "Publicité – Communication – Information",
    "S911": "Restauration – Réception – Hébergement",
    "S912": "Services d'assurance",
    "S913": "Formation",
    "S914": "Location & concessions",
    "S915": "Location matériels roulants & transport",
    "S916": "Études agricoles",
    "S917": "Événementiel",
    "S918": "Traitement des déchets",
    "S919": "Archivage physique & électronique",
    "S920": "Expertise immobilière & foncière",
    "S921": "Analyses laboratoire industrielles",
    "S922": "Analyses laboratoire médicales",
    "S923": "Analyses laboratoire BTP & VRD",
    "S930": "Hébergement spécialisé",
    "S931": "Logiciels – Solutions – Licences",
}

# ── Groupes pour l'UI ─────────────────────────────────────
GROUPS = {
    "🏗 TRAVAUX": {k:v for k,v in SECTORS.items() if k.startswith('T')},
    "🔧 ÉQUIPEMENTS": {k:v for k,v in SECTORS.items() if k.startswith('P')},
    "🛎 SERVICES": {k:v for k,v in SECTORS.items() if k.startswith('S')},
}

# ── Listes plates ─────────────────────────────────────────
SECTOR_CODES = list(SECTORS.keys())
SECTOR_LABELS = list(SECTORS.values())

# ── Mots-clés de classification ───────────────────────────
KEYWORDS: dict = {
    "T101": ["construction","bâtiment","ouvrage d'art","maçonnerie","béton","immeuble","logement","édifice","infrastructure","tertre"],
    "T102": ["terrassement","excavation","déblai","remblai","fouille","nivellement"],
    "T103": ["menuiserie","métallerie","charpente","ferronnerie","serrurerie","portail","garde-corps","alu","aluminium","pvc"],
    "T104": ["plomberie","chauffage","climatisation","hvac","ventilation","sanitaire","chaudière","radiateur"],
    "T105": ["peinture","vitrerie","vitrage","enduit","badigeon","façade"],
    "T106": ["étanchéité","isolation","imperméabilisation","membrane","toiture"],
    "T107": ["revêtement","carrelage","dallage","parquet","marbre","sol"],
    "T108": ["plâtrerie","plâtre","faux plafond","cloison","doublage"],
    "T109": ["ascenseur","monte-charge","escalier mécanique","élévateur"],
    "T110": ["génie civil","voirie","vrd","terrassement divers","plateforme"],
    "T111": ["espace vert","jardin","plantation","gazon","arbre","paysag","horticulture"],
    "T112": ["aménagement bâtiment","aménagement intérieur","rénovation","réhabilitation"],
    "T201": ["assainissement","canalisation","égout","collecteur","réseau eau usée"],
    "T202": ["fondation","injection","sondage","forage","micropieu","pieux"],
    "T203": ["hydraulique","traitement eau","station pompage","adduction","automatisme"],
    "T204": ["maritime","fluvial","port","barrage","digue","jetée"],
    "T301": ["route","voie ferrée","chaussée","autoroute","piste","bitume","asphalte","revêtement routier"],
    "T302": ["signalisation","glissière","panneau","marquage route","équipement route"],
    "T401": ["électricité","éclairage public","courant fort","groupe électrogène","transformateur","hta","bta","poste électrique"],
    "T402": ["télésurveillance","alarme","sonorisation","vidéosurveillance","cctv","intrusion","access control"],
    "T403": ["télécommunication","réseau informatique","fibre optique","téléphonie","antenne","câblage","vdi"],
    "T404": ["isolation frigorifique","chambre froide","réfrigération","congélation","froid industriel"],
    "T501": ["topographie","géomètre","arpentage","photogrammétrie","drone","levé","plan"],
    "T601": ["agricole","irrigation","drainage","serre","plantation","agriculture"],
    "P802": ["équipement électronique","équipement télécoms","switch","routeur","hub","modem"],
    "P804": ["sono","sonorisation","vidéo","photographie","caméra","projecteur","audiovisuel","écran"],
    "P805": ["mobilier bureau","meuble de bureau","chaise","armoire de bureau","table de réunion","bureau"],
    "P806": ["pompe","compresseur","vanne hydraulique","tuyauterie","raccord"],
    "P808": ["matériel topographique","théodolite","gps topographie","station totale"],
    "P810": ["machinisme agricole","tracteur","moissonneuse","matériel agricole"],
    "P812": ["équipement électrique","tableau électrique","câble","disjoncteur","armoire électrique"],
    "P813": ["médical","laboratoire médical","équipement hospitalier","chirurgie","dentaire","radiologie","scanner","irm"],
    "P814": ["climatiseur","split","vmc","groupe froid","réfrigérateur"],
    "P815": ["chariot élévateur","grue","engin de manutention","nacelle","transpalette"],
    "P816": ["véhicule","camion","voiture","bus","ambulance","flotte automobile","minibus"],
    "P817": ["matériel didactique","équipement pédagogique","tableau interactif","tbi"],
    "P818": ["ordinateur","serveur","laptop","imprimante","scanner","informatique","pc","réseau"],
    "P819": ["équipement sportif","stade","terrain","piscine","campement"],
    "P820": ["équipement technique","matériel spécifique","outillage industriel"],
    "P821": ["équipement sécurité","protection incendie","extincteur","gilet","casque","epi"],
    "P822": ["outillage précision","instrument mesure","balance","microscope"],
    "P823": ["petit outillage","outil","matériel courant","consommable"],
    "P824": ["cuisine","buanderie","restaurant collectif","cafétéria"],
    "P825": ["fourniture bureau","papeterie","cartouche","toner","ramette","stylo"],
    "P830": ["pièce rechange","spare parts","maintenance industrielle","produit industriel"],
    "P831": ["carburant","gasoil","essence","mazout","lubrifiant","huile moteur"],
    "P832": ["produit chimique","réactif","solvant","acide","peinture industrielle"],
    "P833": ["médicament","pharmacie","consommable médical","réactif laboratoire","vaccin"],
    "P834": ["alimentaire","denrée","produit agricole","céréale","viande","poisson","légume"],
    "P836": ["imprimerie","impression","papeterie","reprographie","emballage","sérigraphie"],
    "P837": ["textile","confection","vêtement","uniforme","blouse","tenue","tissu"],
    "P838": ["minerai","métal","acier","plastique","bois","matière première"],
    "P839": ["matériaux construction","ciment","brique","préfabriqué","parpaing","béton prêt"],
    "P840": ["ameublement","literie","matelas","meuble","décoration"],
    "P841": ["produit hygiène","nettoyage","détergent","désinfectant","produit d'entretien"],
    "P843": ["équipement laboratoire","paillasse","autoclave","centrifugeuse","spectromètre"],
    "P850": ["solaire","photovoltaïque","panneau solaire","énergie solaire","ingénierie solaire"],
    "P852": ["chauffe-eau solaire","pompe solaire","énergie renouvelable fourniture"],
    "P853": ["biomasse","hydraulique renouvelable","dessalement","step","autre énergie"],
    "S901": ["développement informatique","logiciel sur mesure","application web","système information","tic","digital","plateforme"],
    "S902": ["étude","conseil","audit","expertise","consulting","assistance technique","diagnostic"],
    "S903": ["étude btp","maîtrise d'œuvre","ingénierie","architecte","bureau d'étude","suivi travaux"],
    "S904": ["prestation diverse","service général","mission","sous-traitance"],
    "S906": ["maintenance","réparation","entretien","dépannage","service après-vente","révision"],
    "S907": ["nettoyage","hygiène","propreté","désinfection","lavage","assainissement locaux"],
    "S908": ["gardiennage","sécurité humaine","agent sécurité","vigile","intérim","rondier"],
    "S909": ["concours architecture","concours idées","appel à idées"],
    "S910": ["publicité","communication","affichage","spot","média","relations publiques","événement communication"],
    "S911": ["restauration","traiteur","hébergement hôtel","repas","buffet","réception","cantine"],
    "S912": ["assurance","couverture assurance","police assurance","multirisque"],
    "S913": ["formation","stage","séminaire","atelier","coaching","enseignement","certification"],
    "S914": ["location","concession","bail","mise à disposition"],
    "S915": ["location véhicule","location matériel roulant","transport","chauffeur"],
    "S916": ["étude agricole","conseil agricole","agronomie"],
    "S917": ["événementiel","cérémonie","conférence","congrès","forum","salon","exposition"],
    "S918": ["déchet","collecte déchet","traitement déchet","recyclage","déchetterie"],
    "S919": ["archivage","numérisation","gestion documentaire","stockage document"],
    "S920": ["expertise immobilière","évaluation foncière","estimation bien","géomètre expert"],
    "S921": ["analyse laboratoire industriel","contrôle qualité","essai matériau"],
    "S922": ["analyse laboratoire médical","biologie médicale","bactériologie","sérologie"],
    "S923": ["analyse laboratoire btp","essai béton","contrôle sol","auscultation"],
    "S930": ["hébergement spécialisé","internat","résidence","foyer"],
    "S931": ["logiciel","licence","solution informatique","erp","crm","progiciel","saas"],
}


def classify(text: str) -> str:
    """
    Classe un marché selon le texte.
    Algorithme de scoring pondéré:
    - Mots exacts dans l'objet = 3 pts
    - Mots partiels = 1 pt
    Retourne le code officiel MB SA.
    """
    t = text.lower()
    best_code  = "S904"
    best_score = 0

    for code, keywords in KEYWORDS.items():
        score = 0
        for kw in keywords:
            kw_lower = kw.lower()
            if f" {kw_lower} " in f" {t} ":
                score += 3   # exact word match
            elif kw_lower in t:
                score += 1   # partial match
        # Bonus: code in text (ex: "T101" mentioned)
        if code.lower() in t:
            score += 10
        if score > best_score:
            best_score = score
            best_code  = code

    return best_code


def get_label(code: str) -> str:
    """Retourne le libellé d'un code secteur"""
    return SECTORS.get(code, code)


def get_group(code: str) -> str:
    """Retourne le groupe (TRAVAUX / ÉQUIPEMENTS / SERVICES)"""
    if code.startswith('T'): return "TRAVAUX"
    if code.startswith('P'): return "ÉQUIPEMENTS"
    if code.startswith('S'): return "SERVICES"
    return "AUTRES"
