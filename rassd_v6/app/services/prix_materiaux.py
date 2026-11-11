"""Référentiel des prix de matériaux et des fabricants (app/data/prix_materiaux.json).

Les chiffres viennent de sites marocains de prix et de fournisseurs, cités
ligne par ligne: on ne montre aucune fourchette sans dire d'où elle vient.
"""
import json
import pathlib
from functools import lru_cache

FICHIER = pathlib.Path(__file__).resolve().parent.parent / "data" / "prix_materiaux.json"


UNITES_AR = {"sac 50 kg": "كيس 50 كغ", "sac 25 kg": "كيس 25 كغ", "tonne": "طن", "m³": "م³",
             "m²": "م²", "unité": "وحدة", "kg": "كغ", "ml": "متر طولي", "bidon 20 L": "سطل 20 لتر"}


def _nombre(v: float) -> str:
    if v == int(v):
        return f"{int(v):,}".replace(",", " ")
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


@lru_cache(maxsize=1)
def referentiel() -> dict:
    data = json.loads(FICHIER.read_text(encoding="utf-8"))
    for cat in data["categories"]:
        for l in cat["lignes"]:
            l["prix"] = _nombre(l["min"]) if l["min"] == l["max"] else f"{_nombre(l['min'])} – {_nombre(l['max'])}"
            l["unite_ar"] = UNITES_AR.get(l["unite"], l["unite"])
            l["sources"] = [dict(data["sources"][s], cle=s) for s in l["src"]]
    return data
