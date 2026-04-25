"""
ATLAS PRO — STX10 Classifier v1.0
=====================================
مطابقة دقيقة للصفقات حسب تصنيف STX10 الرسمي المغربي
"""

# ══════════════════════════════════════════════════════════
# التصنيف الكامل STX10
# ══════════════════════════════════════════════════════════
STX10_CODES = {
    # ── TRAVAUX ────────────────────────────────────────────
    "T101": {
        "label": "Travaux de constructions, bâtiments et ouvrages d'art",
        "keywords": ["construction","bâtiment","ouvrage d'art","btp","génie civil","immeuble","réhabilitation","rénovation","extension bâtiment","infrastructure","édifice","logement","résidence","bureau","siège","école","lycée","université","hôpital","salle","stade","piscine","gymnase","mosquée","musée","bibliothèque","parking","hangar","entrepôt"],
    },
    "T102": {
        "label": "Travaux de Terrassements",
        "keywords": ["terrassement","terrassements","déblai","remblai","excavation","fouille","nivellement","talus","drainage","décapage","compactage","stabilisation sol"],
    },
    "T103": {
        "label": "Travaux de Menuiserie – Métallerie – Charpente – Ferronnerie",
        "keywords": ["menuiserie","métallerie","charpente","ferronnerie","portes","fenêtres","menuiserie aluminium","menuiserie bois","serrurerie","garde-corps","grilles","portail","hangar métallique","charpente métallique","structure métallique"],
    },
    "T104": {
        "label": "Travaux de Plomberie – Chauffage – Climatisation",
        "keywords": ["plomberie","chauffage","climatisation","hvac","vmc","ventilation","sanitaires","robinetterie","tuyauterie","chaudière","réfrigération","air conditionné","split","pac","pompe chaleur"],
    },
    "T105": {
        "label": "Travaux de Peinture – Vitrerie",
        "keywords": ["peinture","vitrerie","revêtement mural","enduit","lasure","vernissage","vitrage","baie vitrée","verre","miroiterie","ravalement","façade peinture"],
    },
    "T106": {
        "label": "Travaux d'Étanchéité – Isolation",
        "keywords": ["étanchéité","isolation","imperméabilisation","toiture étanche","bitume","membrane","polyuréthane","isolant thermique","isolation acoustique","laine de roche","polystyrène"],
    },
    "T107": {
        "label": "Travaux de Revêtement",
        "keywords": ["revêtement","carrelage","dallage","parquet","moquette","pavage","revêtement sol","faïence","zellige","marbre","granit","béton ciré"],
    },
    "T108": {
        "label": "Travaux de Plâtrerie – Faux plafonds",
        "keywords": ["plâtrerie","faux plafond","cloison","doublage","staff","stuc","enduit plâtre","plaque de plâtre","ba13","cloisonnement"],
    },
    "T109": {
        "label": "Monte-charge – Ascenseurs",
        "keywords": ["ascenseur","monte-charge","élévateur","escalier mécanique","tapis roulant","plateforme élévatrice"],
    },
    "T110": {
        "label": "Travaux de génie civil & aménagements divers liés au génie civil",
        "keywords": ["génie civil","vrd","voirie réseaux divers","assainissement pluvial","réseau divers","aménagement urbain","trottoir","bordure","caniveau","clôture","mur de soutènement","ouvrage hydraulique"],
    },
    "T111": {
        "label": "Aménagement des espaces verts et jardins",
        "keywords": ["espaces verts","jardin","aménagement paysager","plantation","gazon","arrosage automatique","parc","pelouse","horticulture","reboisement"],
    },
    "T112": {
        "label": "Aménagements Divers associés aux bâtiments",
        "keywords": ["aménagement intérieur","agencement","mobilier fixe","faux plancher","podium","scène","signalétique bâtiment"],
    },
    "T201": {
        "label": "Travaux d'assainissement – Conduite",
        "keywords": ["assainissement","conduite","canalisation","égout","réseau eau","adduction eau","eau potable réseau","station épuration","lagunage","collecteur","coupole","réseau pluvial"],
    },
    "T202": {
        "label": "Fondations spéciales – Injections – Sondages et forages",
        "keywords": ["fondation spéciale","micropieu","pieu","injection","sondage","forage","reconnaissance sol","carottage","géotechnique","consolidation"],
    },
    "T203": {
        "label": "Travaux hydromécaniques – Traitement d'eau – Automatisme",
        "keywords": ["hydromécanique","vanne","pompage","station pompage","traitement eau","potabilisation","filtration","chloration","automatisme hydraulique"],
    },
    "T204": {
        "label": "Travaux maritimes et fluviaux",
        "keywords": ["maritime","fluvial","port","quai","digue","jetée","barrage","retenue","oued","dragage","berge"],
    },
    "T301": {
        "label": "Travaux routiers et de voies ferrées",
        "keywords": ["route","voirie","chaussée","autoroute","voie ferrée","rail","bitume","enrobé","asphalte","déviation","rond-point","échangeur","piste","chemin"],
    },
    "T302": {
        "label": "Travaux de signalisation et équipements de la route",
        "keywords": ["signalisation routière","panneau","marquage","glissière","barrière","éclairage public route","radar","équipement route","feux tricolores"],
    },
    "T401": {
        "label": "Travaux d'électricité & d'éclairage public",
        "keywords": ["électricité","éclairage public","câblage","installation électrique","tableau électrique","transformateur","poste hta","basse tension","haute tension","réseau électrique","lampadaire","photovoltaïque réseau"],
    },
    "T402": {
        "label": "Travaux de sécurité, télésurveillance, sonorisation et protection",
        "keywords": ["vidéosurveillance","télésurveillance","câblage sécurité","alarme incendie","système alarme","contrôle accès","sonorisation","interphone","cctv","détection intrusion","ssi"],
    },
    "T403": {
        "label": "Travaux de télécommunications et d'électroniques",
        "keywords": ["télécommunication","câblage réseau","fibre optique","réseau informatique","courant faible","câblage structuré","data center cablage","antenne","wifi infrastructure"],
    },
    "T404": {
        "label": "Travaux d'isolation frigorifique et chambre froide",
        "keywords": ["chambre froide","isolation frigorifique","entrepôt frigorifique","congélateur industriel","froid"],
    },
    "T501": {
        "label": "Travaux topographiques, couverture aérienne, photogrammétrie",
        "keywords": ["topographie","levé topographique","photogrammétrie","drone cartographie","plan cadastral","couverture aérienne","lidar","bathymétrie"],
    },
    "T601": {
        "label": "Travaux agricoles",
        "keywords": ["travaux agricoles","labour","irrigation","drainage agricole","serre","amenagement agricole","périmètre irrigué"],
    },

    # ── ÉQUIPEMENTS ────────────────────────────────────────
    "P802": {
        "label": "Équipements et accessoires électroniques et de télécommunication",
        "keywords": ["équipement électronique","téléphonie","central téléphonique","autocommutateur","routeur","switch","équipement réseau","radio","émetteur","récepteur"],
    },
    "P804": {
        "label": "Équipement de Sono, Vidéo & de Photographie",
        "keywords": ["sonorisation","vidéoprojecteur","caméra","matériel photo","écran","audiovisuel","ampli","enceinte","microphone","système de conférence"],
    },
    "P805": {
        "label": "Mobilier de Bureau",
        "keywords": ["mobilier bureau","bureau","chaise","armoire","meuble","mobilier scolaire","table","mobilier administratif","rayonnage","bibliothèque meuble"],
    },
    "P806": {
        "label": "Équipements et matériels hydrauliques",
        "keywords": ["pompe","groupe motopompe","compresseur","vanne","accessoires hydrauliques","équipement hydraulique","surpresseur"],
    },
    "P808": {
        "label": "Matériel et équipements topographiques",
        "keywords": ["gps","théodolite","niveau optique","station totale","distancemètre","matériel topographique"],
    },
    "P810": {
        "label": "Équipement machinismes agricoles",
        "keywords": ["tracteur","moissonneuse","matériel agricole","outil agricole","pulvérisateur","motoculteur","système irrigation goutte"],
    },
    "P812": {
        "label": "Équipements et accessoires électriques",
        "keywords": ["équipement électrique","tableau électrique","disjoncteur","câble","onduleur","groupe électrogène","ups","transformateur","batterie","armoire électrique"],
    },
    "P813": {
        "label": "Équipements médicaux, de laboratoire",
        "keywords": ["équipement médical","matériel médical","scanner","radiologie","échographe","bloc opératoire","stérilisateur","oxymètre","tensiomètre","fauteuil dentaire","laboratoire médical","consommable médical"],
    },
    "P814": {
        "label": "Équipement de climatisation",
        "keywords": ["climatiseur","split","vrf","groupe froid","clim","unité intérieure","unité extérieure","pompe à chaleur"],
    },
    "P815": {
        "label": "Matériel de manutention et engins mobiles",
        "keywords": ["chariot élévateur","engin tp","pelleteuse","bulldozer","grue","nacelle","manutention","transpalette","reach truck","pelle","niveleuse"],
    },
    "P816": {
        "label": "Matériel roulant et véhicules",
        "keywords": ["véhicule","voiture","camion","bus","minibus","camionnette","ambulance","véhicule utilitaire","fourgon","moto","bicyclette","location véhicule"],
    },
    "P817": {
        "label": "Matériel et outillage didactique et pédagogique",
        "keywords": ["matériel pédagogique","tableau blanc","tableau interactif","matériel scolaire","équipement éducatif","kit pédagogique","simulateur formation"],
    },
    "P818": {
        "label": "Équipements et accessoires informatiques",
        "keywords": ["informatique","ordinateur","laptop","pc","serveur","imprimante","scanner","tablette","périphérique","disque dur","mémoire","matériel informatique","hardware"],
    },
    "P818": {
        "label": "Équipements et accessoires informatiques",
        "keywords": ["ordinateur","pc","laptop","serveur","imprimante","scanner","tablette","matériel informatique","hardware","stockage","baie serveur","nas","rack"],
    },
    "P819": {
        "label": "Équipements sportifs et de campement",
        "keywords": ["équipement sportif","terrain sport","tente","camping","vestiaire","gradins","filet","poteau","cage foot","panier basket"],
    },
    "P820": {"label": "Équipement technique divers", "keywords": ["équipement technique","outillage technique","matériel spécialisé"]},
    "P821": {
        "label": "Équipement de sécurité, protection et surveillance",
        "keywords": ["équipement sécurité","epi","casque","gilet","harnais","détecteur","extincteur","borne incendie","alarme","badge","portique sécurité"],
    },
    "P822": {"label": "Matériel et outillage de précision", "keywords": ["instrument mesure","oscilloscope","multimètre","calibreur","pied à coulisse","outillage précision"]},
    "P823": {"label": "Petit matériel et outillage", "keywords": ["outillage","outil","perceuse","meuleuse","scie","marteau","clé","petits matériels"]},
    "P824": {"label": "Installation de cuisine et buanderies", "keywords": ["cuisine industrielle","équipement cuisine","four","réfrigérateur","lave-linge","buanderie","restaurant scolaire","cantine"]},
    "P825": {
        "label": "Fournitures et matériels de Bureau",
        "keywords": ["fournitures bureau","papeterie","cartouche","toner","ramette","stylo","classeur","fourniture administrative","consommable bureau"],
    },
    "P830": {"label": "Pièces de rechanges et produits industriels", "keywords": ["pièces rechange","spare parts","maintenance industrielle","consommables industriels"]},
    "P831": {"label": "Combustibles et lubrifiants", "keywords": ["carburant","gasoil","essence","fuel","huile","lubrifiant","combustible","pétrole"]},
    "P832": {"label": "Produits chimiques et para chimiques", "keywords": ["produit chimique","réactif","acide","chlore","coagulant","produit traitement","détergent industriel","désinfectant"]},
    "P833": {"label": "Produits pharmaceutiques et consommables de laboratoire", "keywords": ["médicament","produit pharmaceutique","consommable laboratoire","réactif laboratoire","milieu culture","seringue","gants médicaux"]},
    "P834": {"label": "Produits d'industrie alimentaire, agricoles et pêches", "keywords": ["produit alimentaire","denrée","vivres","alimentation","farine","huile alimentaire","sucre","produit agricole","semence"]},
    "P836": {
        "label": "Imprimerie – Papeterie – Reprographie",
        "keywords": ["imprimerie","impression","reprographie","publication","livre","brochure","flyer","affiche","édition","sérigraphie","papeterie impression"],
    },
    "P837": {"label": "Confection / Textile / Cuir / Habillement", "keywords": ["tenue","uniforme","vêtement","textile","tissu","habillement","costume","blouse","chaussure","maroquinerie"]},
    "P838": {"label": "Minerais, Métaux, Plastiques, Bois", "keywords": ["acier","fer","aluminium","cuivre","métal","plastique","bois","matière première","profilé","tôle"]},
    "P839": {
        "label": "Matériaux de construction et préfabriqués",
        "keywords": ["matériaux construction","ciment","béton","sable","gravier","brique","parpaing","tuile","préfabriqué","élément préfabriqué","acier construction","enduit","mortier"],
    },
    "P840": {"label": "Ameublement et literie", "keywords": ["meuble","lit","matelas","armoire","chambre","ameublement","literie","canapé"]},
    "P841": {"label": "Produits d'hygiène et de nettoiement", "keywords": ["produit hygiène","nettoyage","désinfectant","savon","javel","balai","aspirateur","produit ménager"]},
    "P843": {"label": "Matériels et équipements de laboratoire et d'analyse", "keywords": ["équipement laboratoire","analyseur","spectromètre","centrifugeuse","microscope","ph mètre","matériel analyse"]},
    "P850": {
        "label": "Énergies renouvelables – Solaire",
        "keywords": ["photovoltaïque","panneau solaire","solaire","énergie solaire","pv","chauffe-eau solaire","centrale solaire","onduleur solaire"],
    },
    "P852": {"label": "Énergies renouvelables – Fournitures & Services", "keywords": ["pompe solaire","chauffe-eau","panneau thermique","énergie verte","renouvelable fourniture"]},
    "P853": {"label": "Énergies renouvelables – Autres", "keywords": ["éolien","biomasse","step","hydraulique barrage","dessalement","autre renouvelable"]},

    # ── SERVICES ────────────────────────────────────────────
    "S901": {
        "label": "Études et développement TIC",
        "keywords": ["développement logiciel","application web","site web","système information","si","erp","crm","intranet","extranet","application mobile","développement informatique","solution informatique","logiciel","progiciel","plateforme numérique","digitalisation","transformation digitale"],
    },
    "S902": {
        "label": "Études générales / Conseil",
        "keywords": ["étude","conseil","consulting","audit","expertise","diagnostic","assistance technique","accompagnement","stratégie","plan directeur","schéma directeur","master plan","faisabilité"],
    },
    "S903": {
        "label": "Études relatives aux bâtiments et travaux publics",
        "keywords": ["maîtrise d'oeuvre","mission moe","avant-projet","apd","dce","études btp","béton armé calcul","structure calcul","bureau de contrôle","coordination sécurité"],
    },
    "S904": {
        "label": "Prestations diverses",
        "keywords": ["prestation service","mission","service divers","assistance","prestations"],
    },
    "S906": {
        "label": "Maintenance, Réparation et Entretien",
        "keywords": ["maintenance","entretien","réparation","dépannage","maintenance préventive","maintenance corrective","contrat maintenance","gmao","mco"],
    },
    "S907": {
        "label": "Nettoyage et hygiène",
        "keywords": ["nettoyage","propreté","hygiène","désinfection","désinsectisation","dératisation","entretien ménager","nettoyage locaux"],
    },
    "S908": {
        "label": "Gardiennage et sécurité",
        "keywords": ["gardiennage","sécurité gardiennage","surveillance","agent sécurité","protection","rondes","intérim sécurité"],
    },
    "S909": {"label": "Concours d'idées d'architecture", "keywords": ["concours architecture","concours idées","concours urbanisme"]},
    "S910": {
        "label": "Publicité, communication et information",
        "keywords": ["publicité","communication","campagne pub","média","affichage","spot","communication institutionnelle","relations presse","community management","web marketing"],
    },
    "S911": {
        "label": "Restauration, réception et hébergement",
        "keywords": ["restauration","traiteur","réception","buffet","hébergement","hôtel","séminaire","événement","cocktail","repas"],
    },
    "S912": {"label": "Services d'assurance", "keywords": ["assurance","mutuelles","police assurance","responsabilité civile","assurance véhicule","assurance maladie"]},
    "S913": {
        "label": "Prestations de formation",
        "keywords": ["formation","stage","séminaire","atelier","workshop","certification","e-learning","ingénierie pédagogique","formateur"],
    },
    "S914": {"label": "Locations et Concessions", "keywords": ["location","concession","mise à disposition","bail","loyer"]},
    "S915": {"label": "Location matériels roulants et transport", "keywords": ["location véhicule","transport de personnes","navette","taxi","location voiture","transport scolaire"]},
    "S916": {"label": "Études agricoles", "keywords": ["étude agricole","agronomie","irrigation étude","sol agricole"]},
    "S917": {"label": "Événementiel", "keywords": ["événementiel","organisation événement","conférence","colloque","salon","exposition","forum","journée","cérémonie"]},
    "S918": {"label": "Traitement des déchets", "keywords": ["déchet","collecte déchets","traitement déchets","recyclage","déchetterie","ordures ménagères","rebuts"]},
    "S919": {"label": "Archivage physique et électronique", "keywords": ["archivage","gestion archives","ged","dématérialisation","numérisation documents","records management"]},
    "S920": {"label": "Expertise et évaluation immobilière", "keywords": ["expertise immobilière","évaluation foncière","estimation immobilier","topographe foncier"]},
    "S921": {"label": "Analyses de laboratoire industrielles", "keywords": ["analyse industrielle","contrôle qualité laboratoire","essai mécanique","analyse eau","contrôle matériaux"]},
    "S922": {"label": "Analyses de laboratoire médicales", "keywords": ["analyse médicale","biologie médicale","bilan sanguin","laboratoire médical"]},
    "S923": {"label": "Analyses laboratoire BTP et VRD", "keywords": ["essai béton","analyse sol","contrôle btp","laboratoire géotechnique","essai compactage","carottage béton"]},
    "S930": {"label": "Hébergement spécialisé", "keywords": ["data center","hébergement serveur","cloud hosting","infogérance","saas"]},
    "S931": {
        "label": "Achat et installation logiciels, solutions et licences informatiques",
        "keywords": ["licence logiciel","microsoft","oracle","sap","windows","office","antivirus","logiciel comptabilité","erp achat","crm achat","solution informatique achat"],
    },
}

# ══════════════════════════════════════════════════════════
# MOTEUR DE CLASSIFICATION STX10
# ══════════════════════════════════════════════════════════
def classify_stx10(text: str, top_n: int = 3) -> list:
    """
    Classifie un texte selon STX10.
    Retourne liste de (code, label, score) triée par score.
    """
    if not text:
        return []

    text_lower = text.lower()
    scores = {}

    for code, info in STX10_CODES.items():
        score = 0
        for kw in info["keywords"]:
            kw_lower = kw.lower()
            if kw_lower in text_lower:
                # Score pondéré par longueur du mot-clé
                score += len(kw_lower.split()) * 2
                # Bonus si dans les 200 premiers caractères
                if text_lower[:200].find(kw_lower) >= 0:
                    score += 3

        if score > 0:
            scores[code] = score

    # Trier par score
    sorted_codes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result = []
    for code, score in sorted_codes[:top_n]:
        result.append({
            "code": code,
            "label": STX10_CODES[code]["label"],
            "score": score,
            "category": code[0]  # T, P, ou S
        })

    return result


def classify_primary(text: str) -> dict:
    """Retourne le code STX10 principal uniquement"""
    results = classify_stx10(text, 1)
    if results:
        return results[0]
    return {"code": "S904", "label": "Prestations diverses", "score": 0, "category": "S"}


def match_member_codes(tender_text: str, member_codes: list) -> list:
    """
    Vérifie si un marché correspond aux codes STX10 d'un membre.
    Retourne les codes qui correspondent.
    """
    if not member_codes:
        return []

    tender_results = classify_stx10(tender_text, top_n=5)
    tender_codes = [r["code"] for r in tender_results]

    matches = []
    for code in member_codes:
        if code in tender_codes:
            matches.append(code)
        # Match par famille (ex: membre T101 → match T102, T103...)
        elif member_codes and code[0] == "T" and any(t.startswith("T") for t in tender_codes):
            # Si la famille principale correspond
            family = code[:2]
            for tc in tender_codes:
                if tc.startswith(family):
                    matches.append(code)
                    break

    return list(set(matches))


# Test rapide
if __name__ == "__main__":
    test_texts = [
        "Construction d'un bâtiment administratif R+3 à Rabat avec terrassement",
        "Acquisition d'ordinateurs portables et imprimantes pour 50 postes",
        "Prestation de maintenance et entretien des climatiseurs",
        "Développement d'un système d'information RH",
        "Fourniture et pose de panneaux solaires photovoltaïques",
        "Travaux d'assainissement et réseau d'eau potable",
        "Formation en gestion de projets pour 30 cadres",
        "Service de gardiennage et surveillance 24h/24",
        "Étude et réalisation d'un réseau de fibre optique",
        "Acquisition de matériels médicaux pour le CHU",
    ]

    print("=" * 60)
    print("  TEST CLASSIFICATION STX10")
    print("=" * 60)
    for text in test_texts:
        results = classify_stx10(text, 3)
        print(f"\n📋 {text[:60]}")
        for r in results:
            print(f"   → [{r['code']}] {r['label'][:50]} (score: {r['score']})")
    print("\n" + "=" * 60)
