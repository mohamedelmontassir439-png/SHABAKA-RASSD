import unicodedata
import re
from functools import lru_cache
"""
ATLAS PRO — Classification officielle des marchés publics Maroc
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
    "T201": ["assainissement","canalisation","égout","collecteur","réseau eau usée",
             "réseau d'eau potable","réseau d'assainissement","conduite d'eau",
             "branchement en eau potable","adduction"],
    "T202": ["fondation","injection","sondage","forage","micropieu","pieux"],
    "T203": ["hydraulique","traitement eau","station pompage","adduction","automatisme"],
    "T204": ["maritime","fluvial","port","barrage","digue","jetée"],
    "T301": ["route","voie ferrée","chaussée","autoroute","piste","bitume","asphalte","revêtement routier"],
    "T302": ["signalisation","glissière","panneau","marquage route","équipement route"],
    "T401": ["électricité","éclairage public","courant fort","groupe électrogène",
             "transformateur","hta","bta","poste électrique","lampe","luminaire",
             "ampoule","projecteur d'éclairage","candélabre"],
    "T402": ["télésurveillance","alarme","sonorisation","vidéosurveillance","cctv","intrusion","access control"],
    "T403": ["télécommunication","réseau informatique","fibre optique","téléphonie","antenne","câblage","vdi"],
    "T404": ["isolation frigorifique","chambre froide","réfrigération","congélation","froid industriel"],
    "T501": ["topographie","géomètre","arpentage","photogrammétrie","drone","levé","plan"],
    "T601": ["agricole","irrigation","drainage","serre","plantation","agriculture"],
    "P802": ["équipement électronique","équipement télécoms","switch","routeur","hub","modem"],
    "P804": ["sono","sonorisation","vidéo","photographie","caméra","projecteur","audiovisuel","écran"],
    "P805": ["mobilier bureau","meuble de bureau","chaise","armoire de bureau","table de réunion","bureau"],
    "P806": ["pompe","compresseur","vanne hydraulique","tuyauterie","raccord",
             "tuyau","polyéthylène","pehd"],
    "P808": ["matériel topographique","théodolite","gps topographie","station totale"],
    "P810": ["machinisme agricole","tracteur","moissonneuse","matériel agricole"],
    "P812": ["équipement électrique","tableau électrique","câble","disjoncteur","armoire électrique"],
    "P813": ["médical","laboratoire médical","équipement hospitalier","chirurgie","dentaire","radiologie","scanner","irm"],
    "P814": ["climatiseur","split","vmc","groupe froid","réfrigérateur"],
    "P815": ["chariot élévateur","grue","engin de manutention","nacelle","transpalette"],
    "P816": ["véhicule","camion","voiture","bus","ambulance","flotte automobile","minibus"],
    "P817": ["matériel didactique","équipement pédagogique","tableau interactif","tbi"],
        # « réseau » seul a ete retire: au Maroc il designe le plus souvent un
    # reseau d'eau ou d'electricite, et ramenait ces marches vers l'informatique.
    # Le contexte informatique reste couvert par « réseau informatique » (T403).
    "P818": ["ordinateur","serveur","laptop","imprimante","scanner","informatique","pc",
             "réseau informatique","matériel informatique","onduleur","clé usb"],
    "P819": ["équipement sportif","stade","terrain","piscine","campement"],
    "P820": ["équipement technique","matériel spécifique","outillage industriel"],
    "P821": ["équipement sécurité","protection incendie","extincteur","gilet","casque","epi"],
    "P822": ["outillage précision","instrument mesure","balance","microscope"],
    "P823": ["petit outillage","outillage","outil","matériel courant","consommable",
             "matériel d'atelier","quincaillerie"],
    "P824": ["cuisine","buanderie","restaurant collectif","cafétéria"],
    "P825": ["fourniture bureau","papeterie","cartouche","toner","tonner","ramette",
             "rame de papier","papier","feuille","stylo","enveloppe","classeur",
             "registre","chemise cartonnée","agrafeuse","parapheur"],
    "P830": ["pièce rechange","spare parts","maintenance industrielle","produit industriel"],
    "P831": ["carburant","gasoil","essence","mazout","lubrifiant","huile moteur"],
    "P832": ["produit chimique","réactif","solvant","acide","peinture industrielle"],
    "P833": ["médicament","pharmacie","consommable médical","réactif laboratoire","vaccin"],
    "P834": ["alimentaire","denrée","produit agricole","céréale","viande","poisson","légume"],
    "P836": ["imprimerie","impression","papeterie","reprographie","emballage","sérigraphie",
             "imprimé","photocopie","plastification","reliure"],
    "P837": ["textile","confection","vêtement","uniforme","blouse","tenue","tissu"],
    "P838": ["minerai","métal","acier","plastique","bois","matière première"],
    "P839": ["matériaux construction","ciment","brique","préfabriqué","parpaing","béton prêt"],
    "P840": ["ameublement","literie","matelas","meuble","décoration"],
    # La lutte antiparasitaire relevait d'aucun secteur: faute de mot-cle, ces
    # marches tombaient dans « Prestations diverses », invisibles pour les
    # fournisseurs concernes.
    "P841": ["produit hygiène","nettoyage","détergent","désinfectant","produit d'entretien",
             "insecticide","raticide","dératisation","désinsectisation","pesticide",
             "désinfection","antiparasitaire"],
    "P843": ["équipement laboratoire","paillasse","autoclave","centrifugeuse","spectromètre"],
    "P850": ["solaire","photovoltaïque","panneau solaire","énergie solaire","ingénierie solaire"],
    "P852": ["chauffe-eau solaire","pompe solaire","énergie renouvelable fourniture"],
    "P853": ["biomasse","hydraulique renouvelable","dessalement","step","autre énergie"],
    "S901": ["développement informatique","logiciel sur mesure","application web","système information","tic","digital","plateforme"],
    "S902": ["étude","conseil","audit","expertise","consulting","assistance technique","diagnostic"],
    "S903": ["étude btp","maîtrise d'œuvre","ingénierie","architecte","bureau d'étude","suivi travaux"],
    # « mission » retire le 06/10/2026: trop general — « Mission A : »,
    # « mission d'expertise », « mission de controle » relevent des etudes.
    # Et S904 est le seau par defaut: il n'a pas besoin d'attirer.
    "S904": ["prestation diverse","service général","sous-traitance"],
    "S906": ["maintenance","réparation","entretien","dépannage","service après-vente","révision"],
    "S907": ["nettoyage","hygiène","propreté","désinfection","lavage","assainissement locaux"],
    "S908": ["gardiennage","sécurité humaine","agent sécurité","vigile","intérim","rondier"],
    "S909": ["concours architecture","concours idées","appel à idées"],
    "S910": ["publicité","communication","affichage","spot","média","relations publiques","événement communication"],
    # « réception » retire le 06/10/2026: dans un avis de travaux, c'est la
    # reception de l'ouvrage, pas un cocktail. 53 titres la portent, et
    # « Reception des fonds de fouilles » tombait en Restauration. Le secteur
    # garde quinze autres mots-cles, tous sans equivoque.
    "S911": ["restauration","traiteur","hébergement hôtel","repas","buffet",
             "cantine","petit déjeuner","déjeuner","dîner","pause café","café",
             "collation","gâteau","eau minérale","cocktail"],
    "S912": ["assurance","couverture assurance","police assurance","multirisque"],
    # « atelier » precise: un atelier est aussi un local technique ou un
    # garage, et « construction d'un atelier mecanique » n'est pas une
    # formation.
    "S913": ["formation","stage","séminaire","atelier de formation","coaching",
             "enseignement","certification"],
    "S914": ["location","concession","bail","mise à disposition"],
    "S915": ["location véhicule","location matériel roulant","transport","chauffeur",
             "billet d'avion","billetterie","voyage","déplacement aérien","aller retour"],
    "S916": ["étude agricole","conseil agricole","agronomie"],
    # « salon » precise: un salon est aussi une piece et un ensemble de
    # sieges — « fourniture d'un salon pour la direction » est du mobilier.
    "S917": ["événementiel","cérémonie","conférence","congrès","forum",
             "salon professionnel","exposition"],
    "S918": ["déchet","collecte déchet","traitement déchet","recyclage","déchetterie"],
    "S919": ["archivage","numérisation","gestion documentaire","stockage document"],
    "S920": ["expertise immobilière","évaluation foncière","estimation bien","géomètre expert"],
    "S921": ["analyse laboratoire industriel","contrôle qualité","essai matériau"],
    "S922": ["analyse laboratoire médical","biologie médicale","bactériologie","sérologie"],
    "S923": ["analyse laboratoire btp","essai béton","contrôle sol","auscultation"],
    "S930": ["hébergement spécialisé","internat","résidence","foyer"],
    "S931": ["logiciel","licence","solution informatique","erp","crm","progiciel","saas"],
}


# Un mot-cle court ne vaut que comme mot entier. Meme adossee a une frontiere
# de mot, la regle de prefixe reste un piege en dessous de ce seuil:
# « plan » ouvre « planification » et « planning », « sol » ouvre « solution »
# et « solde », « port » ouvre « portail » et « portefeuille ». Au-dela, le
# prefixe reste utile et sur: « informatiq » n'ouvre que « informatique ».
_PREFIXE_LONGUEUR_MIN = 6

# Separateur tolere entre les mots d'une expression-cle: espaces, apostrophes
# et traits d'union, plus au plus un petit mot de liaison.
# Les particules d'elision, retirees des mots-cles: _LIAISON les remet.
_ELISIONS = {"d", "l", "de", "du", "des", "le", "la", "les", "au", "aux"}

_LIAISON = (r"[\s'" + chr(0x2019) + r"-]+(?:(?:de|du|des|d|le|la|les|l|au|aux|en|pour|sur)"
            r"[\s'" + chr(0x2019) + r"]+)?")


@lru_cache(maxsize=8192)
def _sans_accents(texte: str) -> str:
    """« DERATISATION » et « dératisation » doivent se rencontrer.

    Les avis marocains sont largement saisis en capitales et sans accents,
    alors que le referentiel de mots-cles les porte. Sans cette mise a plat,
    « DESINFECTION », « ELECTRICITE » ou « BETON » ne trouvaient aucun
    mot-cle et finissaient en « Prestations diverses ».
    """
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


@lru_cache(maxsize=4096)
def _motifs(kw: str):
    """Deux expressions par mot-cle: le mot entier, puis le mot en prefixe."""
    nu = _sans_accents(kw)
    # Entre deux mots d'une expression, le francais glisse des articles et des
    # elisions que le mot-cle ne porte pas: « systeme information » doit
    # reconnaitre « systeme d'information » et « systeme de l'information ».
    # Sans cette souplesse, « Conception, developpement, integration et mise en
    # exploitation d'un systeme d' information territorial » — releve le
    # 30/09/2026 — tombait en « Prestations diverses ».
    # Le pluriel touche chaque mot de l'expression, pas seulement le dernier:
    # « espace vert » doit reconnaitre « espaces verts ».
    #
    # On coupe aussi sur les apostrophes, et on jette les particules
    # d'elision: c'est _LIAISON qui les reconstitue, avec ou sans apostrophe.
    # Sans cela, « produit d'entretien » cherchait l'apostrophe a la lettre et
    # ne voyait pas « PRODUITS D ENTRETIEN » — or les avis marocains sont
    # largement saisis en capitales, sans accents ni apostrophes. Dix
    # mots-cles etaient dans ce cas, dont « ouvrage d'art », « reseau
    # d'assainissement » et « bureau d'etude »: du BTP de premiere ligne.
    mots = [m for m in re.split(r"[\s'" + chr(0x2019) + r"]+", nu)
            if m and m not in _ELISIONS]
    echappe = _LIAISON.join(re.escape(mot) + r"(?:s|x)?" for mot in mots)
    # Le pluriel francais fait partie du mot entier: « arbre » doit
    # reconnaitre « arbres », « outil » reconnaitre « outils ». Sans cela,
    # borner la regle de prefixe aux mots longs ferait perdre tous les
    # pluriels des mots-cles courts.
    entier = re.compile(r"\b" + echappe + r"\b")
    return (entier, re.compile(r"\b" + echappe))


# Un seul repli de famille, et c'est celui des travaux. « Genie civil &
# amenagements divers » est le secteur que la nomenclature prevoit pour des
# travaux sans specialite nommee: un entrepreneur du batiment l'a choisi
# pour cela, et il y trouvera ce qu'il attend.
#
# Pas d'equivalent du cote des produits. Un essai l'a montre le 06/10/2026:
# router vers « Equipement technique divers » tout avis disant « achat » y
# versait 253 avis sans rapport — bacs a ordures, articles de sport,
# alimentation animale. Cela ne classe rien: cela deplace la decharge dans
# un secteur auquel des gens s'abonnent. Ce qu'on ne sait pas lire reste
# donc en « Prestations diverses », qui dit au moins la verite.
_REPLI_TRAVAUX = "T110"
_REPLI_INCONNU = "S904"

# Ces mots ne designent aucun metier — « travaux » ne dit pas lesquels — et
# ne peuvent donc pas etre des mots-cles de secteur. Mais ils suffisent a
# dire qu'il s'agit de travaux, ce qui vaut mieux que de les ranger parmi
# les services.
_MOTS_TRAVAUX = re.compile(
    r"\b(?:travaux|amenagement|reamenagement|rehabilitation|refection|"
    r"renovation|construction|demolition|terrassement|revetement|etancheite|"
    r"voirie|edification)")

_POIDS_OBJET = 3   # le titre dit le metier
_POIDS_FOND = 1    # le corps de l'avis le confirme, ou le noie


def _repli(texte: str) -> str:
    """Le seau que designe un texte: les travaux, ou l'aveu d'ignorance."""
    if _MOTS_TRAVAUX.search(_sans_accents(texte or "")):
        return _REPLI_TRAVAUX
    return _REPLI_INCONNU


def _accroches(texte: str) -> dict:
    """{code: (score, precision)} pour un texte donne.

    La precision est le mot-cle le plus parlant qui ait repondu: son nombre
    de mots d'abord, sa longueur ensuite. C'est elle qui departage deux
    secteurs a egalite de points.
    """
    if not texte:
        return {}
    t = _sans_accents(texte)
    trouve = {}
    for code, keywords in KEYWORDS.items():
        score, precision = 0, (0, 0)
        for kw in keywords:
            entier, prefixe = _motifs(kw)
            poids = len(kw.split())
            if entier.search(t):
                score += 3 * poids
            elif len(kw) >= _PREFIXE_LONGUEUR_MIN and prefixe.search(t):
                score += poids
            else:
                continue
            precision = max(precision, (poids, len(kw)))
        if re.search(r"\b" + code.lower() + r"\b", t):
            score += 10
            precision = max(precision, (9, 99))   # le code ecrit: preuve directe
        if score:
            trouve[code] = (score, precision)
    return trouve


def classify(objet: str, contexte: str = "") -> str:
    """Classe un marche et rend le code officiel du referentiel MB SA.

    Trois regles, et chacune repare un defaut mesure sur 3 263 avis reels
    le 06/10/2026.

    **L'objet pese trois fois le reste.** Tout le texte etait auparavant
    concatene puis pese d'un bloc: mille cinq cents caracteres de formules
    administratives couvraient un titre de six mots. 28 % des avis
    finissaient a egalite entre plusieurs secteurs, et cette egalite venait
    presque toujours du corps de l'avis, jamais de son titre.

    **L'egalite se tranche par la precision, non par l'ordre du fichier.**
    `score > best` retenait le premier secteur declare: T101, ecrit en tete,
    remportait 109 egalites pendant que S911 — Restauration, declare en
    soixante-huitieme position — en perdait 263. La place d'un secteur dans
    le fichier decidait de sa part. A egalite de points on prefere desormais
    le mot-cle le plus specifique: une expression de deux mots avant un mot
    isole, un mot long avant un court.

    **Le repli suit la famille.** Un avis que rien ne reconnaissait tombait
    en « Prestations diverses », un seau de services — y compris quand il
    disait « Travaux d'amenagement ». 182 avis sur 348 parlant de travaux
    etaient ranges hors des secteurs T, invisibles pour les entreprises du
    batiment. Le repli choisit maintenant le seau de la bonne famille.

    `contexte` reste facultatif: un appelant qui n'a qu'un bloc de texte le
    passe en premier argument et retrouve l'ancien comportement, ponderation
    mise a part.
    """
    par_objet, par_fond = _accroches(objet), _accroches(contexte)

    # Quand le titre ne dit rien de precis, le corps de l'avis ne doit pas
    # decider seul: il est fait de formules administratives qui accrochent au
    # hasard. « Fourniture d'une tente caidale » n'accroche aucun mot-cle dans
    # son titre, et sa description le faisait tomber en Restauration. Si le
    # titre dit au moins sa famille, c'est elle qui tranche.
    if not par_objet:
        if _MOTS_TRAVAUX.search(_sans_accents(objet)):
            return _REPLI_TRAVAUX
        if not par_fond:
            return _repli(contexte)

    trouve = {}
    for code in set(par_objet) | set(par_fond):
        so, po = par_objet.get(code, (0, (0, 0)))
        sf, pf = par_fond.get(code, (0, (0, 0)))
        trouve[code] = (_POIDS_OBJET * so + _POIDS_FOND * sf, max(po, pf))

    # Trois criteres parlants, du plus fort au plus faible: les points, la
    # precision du mot-cle, puis le fait d'avoir repondu dans le titre plutot
    # que dans le corps de l'avis. Le code ne departage qu'en dernier ressort
    # — il le faut bien pour que le resultat soit stable d'une execution a
    # l'autre, mais il ne tranche presque jamais.
    return max(trouve.items(),
               key=lambda kv: (kv[1][0], kv[1][1],
                               par_objet.get(kv[0], (0,))[0], kv[0]))[0]


def get_label(code: str) -> str:
    """Retourne le libellé d'un code secteur"""
    return SECTORS.get(code, code)


def get_group(code: str) -> str:
    """Retourne le groupe (TRAVAUX / ÉQUIPEMENTS / SERVICES)"""
    if code.startswith('T'): return "TRAVAUX"
    if code.startswith('P'): return "ÉQUIPEMENTS"
    if code.startswith('S'): return "SERVICES"
    return "AUTRES"
