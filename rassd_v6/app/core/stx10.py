"""
SOURCE v2.1 — STX10 Classification
===================================
Classification STX10 des marchés publics marocains
"""

STX10 = {
    "01": "Travaux de bâtiment",
    "02": "Travaux publics",
    "03": "Travaux d'aménagement",
    "04": "Fournitures de bureau",
    "05": "Fournitures informatiques",
    "06": "Matériel médical",
    "07": "Services de nettoyage",
    "08": "Services de sécurité",
    "09": "Services de transport",
    "10": "Services de formation",
    "11": "Services de conseil",
    "12": "Services informatiques",
    "13": "Services de restauration",
    "14": "Services d'impression",
    "15": "Services de maintenance",
    "16": "Études et ingénierie",
    "17": "Fournitures électriques",
    "18": "Fournitures de construction",
    "19": "Matériel de transport",
    "20": "Autres services",
}

STX10_AR = {
    "01": "أشغال البناء",
    "02": "الأشغال العمومية",
    "03": "أشغال التهيئة",
    "04": "لوازم المكتب",
    "05": "لوازم الحاسوب",
    "06": "المعدات الطبية",
    "07": "خدمات التنظيف",
    "08": "خدمات الأمن",
    "09": "خدمات النقل",
    "10": "خدمات التكوين",
    "11": "خدمات الاستشارة",
    "12": "خدمات المعلوميات",
    "13": "خدمات المطاعم",
    "14": "خدمات الطباعة",
    "15": "خدمات الصيانة",
    "16": "الدراسات والهندسة",
    "17": "اللوازم الكهربائية",
    "18": "لوازم البناء",
    "19": "معدات النقل",
    "20": "خدمات أخرى",
}

def classify(objet: str) -> tuple:
    """Classify tender based on object description"""
    text = (objet or "").lower()

    keywords = {
        "01": ["bâtiment", "construction", "maçonnerie", "plâtrerie", "peinture", "carrelage"],
        "02": ["route", "pont", "voirie", "assainissement", "réseau", "canalisation"],
        "03": ["aménagement", "paysagisme", "jardin", "espace vert"],
        "04": ["bureau", "papier", "stylo", "classeur", "fourniture"],
        "05": ["ordinateur", "imprimante", "serveur", "logiciel", "informatique"],
        "06": ["médical", "hôpital", "clinique", "laboratoire", "pharmacie"],
        "07": ["nettoyage", "propreté", "hygiène", "désinfection"],
        "08": ["sécurité", "gardiennage", "surveillance", "garde"],
        "09": ["transport", "véhicule", "camion", "livraison"],
        "10": ["formation", "stage", "enseignement", "apprentissage"],
        "11": ["conseil", "consultant", "expertise", "audit"],
        "12": ["développement", "programmation", "application", "web", "site"],
        "13": ["restauration", "cantine", "repas", "alimentation"],
        "14": ["impression", "imprimerie", "brochure", "affiche"],
        "15": ["maintenance", "réparation", "entretien", "dépannage"],
        "16": ["étude", "ingénierie", "projet", "conception"],
        "17": ["électrique", "électricité", "câble", "tableau"],
        "18": ["ciment", "acier", "béton", "bois", "matériau"],
        "19": ["véhicule", "camion", "voiture", "bus", "moto"],
    }

    scores = {}
    for code, words in keywords.items():
        scores[code] = sum(1 for w in words if w in text)

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return (best, STX10[best])

    return ("20", STX10["20"])

def top3(objet: str) -> list:
    """Get top 3 matching STX10 codes"""
    text = (objet or "").lower()
    keywords = {
        "01": ["bâtiment", "construction", "maçonnerie"],
        "02": ["route", "pont", "voirie"],
        "03": ["aménagement", "paysagisme"],
        "04": ["bureau", "papier", "fourniture"],
        "05": ["ordinateur", "informatique", "serveur"],
        "06": ["médical", "hôpital", "clinique"],
        "07": ["nettoyage", "propreté"],
        "08": ["sécurité", "gardiennage"],
        "09": ["transport", "véhicule"],
        "10": ["formation", "stage"],
        "11": ["conseil", "consultant"],
        "12": ["développement", "programmation"],
        "13": ["restauration", "cantine"],
        "14": ["impression", "imprimerie"],
        "15": ["maintenance", "réparation"],
        "16": ["étude", "ingénierie"],
        "17": ["électrique", "électricité"],
        "18": ["ciment", "acier", "béton"],
        "19": ["véhicule", "camion"],
        "20": ["autre", "divers"],
    }

    scores = {}
    for code, words in keywords.items():
        scores[code] = sum(1 for w in words if w in text)

    sorted_codes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(code, STX10[code]) for code, _ in sorted_codes[:3] if scores[code] > 0]
