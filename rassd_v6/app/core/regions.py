# -*- coding: utf-8 -*-
"""Les douze régions du Maroc, quelle que soit la façon dont l'avis écrit le lieu.

Le champ « région » des avis est en fait le lieu d'exécution tel que
l'acheteur l'a saisi: une province (« Taroudannt »), une préfecture
(« Agadir Ida Ou Tanane »), une ville (« Bouarfa »), parfois précédée de
« Maroc, » ou suivie de « MAROC ». Relevé du 26/10/2026: 176 écritures
différentes pour les marchés ouverts — « Al Haouz » et « Al haouz »,
« Assa zag » et « Assa-Zag », « Beni Mellal » et « Beni mellal ». Proposer
cette liste au membre pour ses alertes, c'était lui demander de cocher
quatre fois la même province, et de deviner que « Biougra » est dans le
Souss.

On ramène chaque écriture à l'une des douze régions du découpage de 2015,
par ses provinces et préfectures, et par les villes qui reviennent dans
les avis.
"""
import re
import unicodedata
from functools import lru_cache

# Nom (fr), nom (ar), mots qui la désignent (forme réduite: minuscules, sans
# accents, tirets et apostrophes en espaces). L'ordre compte peu: un mot
# n'appartient qu'à une région.
REGIONS = [
    ("Tanger-Tétouan-Al Hoceïma", "طنجة تطوان الحسيمة",
     ["tanger", "tangier", "assilah", "asilah", "tetouan", "mdiq", "m diq", "fnideq", "martil",
      "fahs anjra", "anjra", "larache", "ksar el kebir", "ksar kebir", "al hoceima", "hoceima",
      "chefchaouen", "chaouen", "ouezzane", "ouazzane", "jebha"]),
    ("L'Oriental", "الشرق",
     ["oujda", "angad", "nador", "driouch", "jerada", "jrada", "berkane", "saidia", "ahfir", "taourirt",
      "guercif", "figuig", "bouarfa", "zaio", "selouane", "oriental", "el aioun sidi mellouk"]),
    ("Fès-Meknès", "فاس مكناس",
     ["fes", "fez", "meknes", "el hajeb", "hajeb", "ifrane", "azrou", "moulay yacoub", "moulay yaacoub", "sefrou",
      "boulemane", "missour", "taounate", "taza"]),
    ("Rabat-Salé-Kénitra", "الرباط سلا القنيطرة",
     ["rabat", "sale", "skhirate", "skhirat", "temara", "kenitra", "khemisset", "khemissat", "tiflet",
      "sidi kacem", "sidi slimane", "souk el arbaa", "mehdia"]),
    ("Béni Mellal-Khénifra", "بني ملال خنيفرة",
     ["beni mellal", "azilal", "fquih ben salah", "fkih ben salah", "fqih ben salah", "khenifra",
      "khouribga", "kasba tadla", "oued zem", "demnate", "mrirt"]),
    ("Casablanca-Settat", "الدار البيضاء سطات",
     ["casablanca", "casa", "mohammedia", "mohammadia", "el jadida", "jadida", "nouaceur", "nouacer", "bouznika",
      "mediouna", "benslimane", "ben slimane", "berrechid", "settat", "sidi bennour",
      "bouskoura", "azemmour", "had soualem"]),
    ("Marrakech-Safi", "مراكش آسفي",
     ["marrakech", "chichaoua", "al haouz", "haouz", "el kelaa", "kelaa", "sraghna", "essaouira",
      "rehamna", "rhamna", "ben guerir", "benguerir", "safi", "youssoufia", "tahannaout",
      "amizmiz"]),
    ("Drâa-Tafilalet", "درعة تافيلالت",
     ["errachidia", "ouarzazate", "midelt", "tinghir", "tinerhir", "zagora", "rissani",
      "erfoud", "goulmima", "draa tafilalet", "tafilalet"]),
    ("Souss-Massa", "سوس ماسة",
     ["agadir", "inezgane", "ait melloul", "chtouka", "ait baha", "biougra", "taroudant",
      "taroudannt", "ouled teima", "tiznit", "tata", "souss"]),
    ("Guelmim-Oued Noun", "كلميم واد نون",
     ["guelmim", "assa", "zag", "tan tan", "tantan", "sidi ifni", "ifni"]),
    ("Laâyoune-Sakia El Hamra", "العيون الساقية الحمراء",
     ["laayoune", "laayoun", "layoune", "boujdour", "tarfaya", "es semara", "smara", "semara"]),
    ("Dakhla-Oued Ed-Dahab", "الداخلة وادي الذهب",
     ["dakhla", "oued ed dahab", "oued eddahab", "aousserd", "lagouira", "guerguerat"]),
]

NOMS = [r[0] for r in REGIONS]
_AR = {r[0]: r[1] for r in REGIONS}


def _nu(texte: str) -> str:
    d = unicodedata.normalize("NFD", (texte or "").lower())
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return " " + re.sub(r"[^a-z0-9]+", " ", d).strip() + " "


# Les plus longs d'abord: « el aioun sidi mellouk » (Oriental) avant tout
# mot plus court, « sidi ifni » avant « ifni ».
_MOTS = sorted(((" " + m + " ", nom) for nom, _, mots in REGIONS for m in mots),
               key=lambda x: -len(x[0]))


@lru_cache(maxsize=4096)
def region_de(lieu: str) -> str:
    """La région officielle d'un lieu d'avis, ou "" si on ne la reconnaît pas."""
    nu = _nu(lieu)
    if len(nu.strip()) < 3:
        return ""
    for mot, nom in _MOTS:
        if mot in nu:
            return nom
    return ""


def nom(region: str, lang: str = "fr") -> str:
    return _AR.get(region, region) if lang == "ar" else region


def est_officielle(valeur: str) -> bool:
    return valeur in _AR
