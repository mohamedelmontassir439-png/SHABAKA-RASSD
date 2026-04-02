"""
Modern Business — Classification IA des صفقات
47 codes T/P/S + région + score
"""
import re
from datetime import datetime

SECTEURS = {
    "T": {"T101":"Bâtiments & Génie Civil","T102":"Routes & Autoroutes",
          "T103":"Hydraulique & Eau","T104":"Électricité & Éclairage",
          "T201":"Infrastructure Télécom","T202":"Réseaux Informatiques",
          "T203":"Systèmes de Sécurité","T301":"Travaux Agricoles",
          "T401":"Entretien & Maintenance","T402":"Réhabilitation Bâtiments",
          "T403":"Aménagement Espaces"},
    "P": {"P811":"Informatique & Logiciels","P812":"Téléphonie & Réseaux",
          "P813":"Électronique & Mesure","P814":"Médical & Laboratoire",
          "P815":"Mobilier & Équipement Bureau","P816":"Véhicules & Transport",
          "P817":"Outillage & Machines","P818":"Informatique Matériel",
          "P819":"Sécurité & Surveillance","P820":"Énergie & Électricité",
          "P821":"Alimentation & Nutrition","P822":"Produits Chimiques",
          "P823":"Textiles & Vêtements","P824":"Papeterie & Imprimerie",
          "P825":"Fournitures Générales","P826":"Sport & Loisirs",
          "P827":"Agriculture & Élevage","P828":"Médecine & Pharmacie",
          "P829":"Hygiène & Nettoyage","P830":"Électroménager",
          "P831":"Matériaux Construction","P832":"Équipements Industriels",
          "P833":"Instruments Scientifiques","P860":"Autres Fournitures"},
    "S": {"S901":"Études & Ingénierie","S902":"Études & Conseil",
          "S903":"Formation & Éducation","S904":"Audit & Expertise",
          "S905":"Gardiennage & Sécurité","S906":"Nettoyage & Entretien",
          "S907":"Transport & Logistique","S908":"Restauration & Hôtellerie",
          "S909":"Communication & Publicité","S910":"Informatique Services",
          "S911":"Juridique & Notariat","S912":"Santé & Médical Services",
          "S913":"Architecture & Urbanisme","S914":"Environnement",
          "S915":"Énergie & Eau Services","S916":"Culture & Événements",
          "S917":"Recherche & Développement"}
}

REGIONS_MA = {
    "rabat": "Rabat-Salé-Kénitra", "casablanca": "Casablanca-Settat",
    "marrakech": "Marrakech-Safi", "fes": "Fès-Meknès",
    "tanger": "Tanger-Tétouan-Al Hoceïma", "agadir": "Souss-Massa",
    "oujda": "Oriental", "laayoune": "Laâyoune-Sakia El Hamra",
    "kenitra": "Rabat-Salé-Kénitra", "sale": "Rabat-Salé-Kénitra",
    "meknes": "Fès-Meknès", "tetouan": "Tanger-Tétouan-Al Hoceïma",
    "safi": "Marrakech-Safi", "beni mellal": "Béni Mellal-Khénifra",
    "settat": "Casablanca-Settat", "nador": "Oriental",
}


def secteur(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","génie civil","béton"]): return "T401"
    if any(k in t for k in ["route","autoroute","voirie","chaussée"]): return "T102"
    if any(k in t for k in ["informatique","logiciel","système","application","réseau"]): return "P818"
    if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel","équipement"]): return "P825"
    if any(k in t for k in ["médical","médicament","hôpital","santé","clinique","laboratoire"]): return "P814"
    if any(k in t for k in ["véhicule","automobile","voiture","camion","transport"]): return "P816"
    if any(k in t for k in ["nettoyage","entretien","maintenance","hygiène"]): return "S906"
    if any(k in t for k in ["gardiennage","sécurité","surveillance"]): return "S905"
    if any(k in t for k in ["étude","mission","audit","conseil","expertise","ingénierie"]): return "S902"
    if any(k in t for k in ["formation","enseignement","éducation","stage"]): return "S903"
    if any(k in t for k in ["restauration","hôtellerie","alimentation","repas"]): return "S908"
    if any(k in t for k in ["communication","publicité","impression","media"]): return "S909"
    if any(k in t for k in ["électricité","éclairage","énergie","photovoltaïque"]): return "T104"
    if any(k in t for k in ["hydraulique","eau","assainissement","réseau d'eau"]): return "T103"
    if any(k in t for k in ["papeterie","bureau","cartouche","toner"]): return "P824"
    return "P825"


def region(text: str) -> str:
    t = text.lower()
    for key, region_name in REGIONS_MA.items():
        if key in t: return region_name
    return "Maroc"


def type_marche(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","pose","démolition"]): return "Travaux"
    if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel"]): return "Fournitures"
    if any(k in t for k in ["étude","mission","audit","conseil","formation","expertise"]): return "Études & Conseil"
    return "Services"


def score(objet: str, description: str = "") -> int:
    """Score de priorité 0-100"""
    text = (objet + " " + description).lower()
    s = 50
    # Boost
    if any(k in text for k in ["urgence","urgent","priorité"]): s += 15
    if any(k in text for k in ["informatique","système","logiciel"]): s += 10
    if any(k in text for k in ["travaux","construction"]): s += 8
    if any(k in text for k in ["national","maroc entier"]): s += 5
    # Pénalités
    if any(k in text for k in ["fournitures générales","papeterie"]): s -= 5
    if len(objet) < 20: s -= 10
    return max(0, min(100, s))


def classify(tender: dict) -> dict:
    """Classifie un tender et retourne les champs enrichis"""
    objet = tender.get("objet", "")
    desc  = tender.get("description", "")
    acheteur = tender.get("acheteur", "")
    return {
        **tender,
        "domaine":     secteur(objet + " " + desc),
        "type_marche": type_marche(objet),
        "region":      region(acheteur + " " + objet),
        "ai_score":    score(objet, desc),
    }
