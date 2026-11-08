"""Les photographies du site, leurs auteurs et leurs licences.

Toutes viennent de Wikimedia Commons, sous licence libre: CC BY et CC BY-SA
demandent de nommer l'auteur et la licence, avec un lien. La page des
mentions légales les cite (templates/legal_mentions.html), et chaque image
garde ici sa source pour qu'on puisse la retrouver.
"""

PHOTOS = {
    "tanger-med": {
        "lieu": "Port Tanger Med, vue aérienne", "lieu_ar": "ميناء طنجة المتوسط، منظر جوي",
        "auteur": "Adam Cli", "licence": "CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:PortofTangerMed1.jpg",
    },
    "chantier-rabat": {
        "lieu": "Chantier du tramway, Rabat", "lieu_ar": "ورش الترامواي، الرباط",
        "auteur": "Pline", "licence": "CC BY-SA 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:Chantier_tramway_Rabat_P1060402.JPG",
    },
    "casablanca-finance-city": {
        "lieu": "Casablanca Finance City", "lieu_ar": "القطب المالي للدار البيضاء",
        "auteur": "AyourAchtouk", "licence": "CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:Casablanca_Finance_City_05.jpg",
    },
    "pont-settat": {
        "lieu": "Pont en construction, province de Settat", "lieu_ar": "جسر في طور البناء، إقليم سطات",
        "auteur": "Bertrand Soubeyrand", "licence": "CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:Pont_en_construction_province_Settat_Maroc-photo_Bertrand_SOUBEYRAND.jpg",
    },
    "tramway-casablanca": {
        "lieu": "Tramway T2, Casablanca", "lieu_ar": "الترامواي T2، الدار البيضاء",
        "auteur": "Casabus", "licence": "CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:TramwayT2-CFC-casablanca.jpg",
    },
    "noor-ouarzazate": {
        "lieu": "Centrale solaire Noor, Ouarzazate", "lieu_ar": "محطة نور للطاقة الشمسية، ورزازات",
        "auteur": "Richard Allaway", "licence": "CC BY 2.0",
        "source": "https://commons.wikimedia.org/wiki/File:Noor_1_and_2_-_Ouarzazate_Solar_Power_Station_(48962353822).jpg",
    },
}

LICENCES = {
    "CC BY 2.0": "https://creativecommons.org/licenses/by/2.0/",
    "CC BY-SA 3.0": "https://creativecommons.org/licenses/by-sa/3.0/",
    "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
}
