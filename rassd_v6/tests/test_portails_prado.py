# -*- coding: utf-8 -*-
"""Portails d'achats d'entreprises publiques (logiciel du portail national)."""
import os

from app.services import portails_prado as P


class Rep:
    def __init__(self, text): self.text, self.status_code = text, 200
    def raise_for_status(self): pass


class FausseSession:
    def __init__(self, liste, fiche): self.liste, self.fiche = liste, fiche
    def get(self, url, **k):
        return Rep(self.fiche if "DetailsConsultation" in url else self.liste)


def _fixture(nom):
    with open(os.path.join(os.path.dirname(__file__), nom), encoding="utf-8") as f:
        return f.read()


def test_lit_les_cartes_et_nomme_la_source(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    liste = _fixture("fixtures_carte_ao.html")
    s = FausseSession(liste, "<html>Référence : 13/2026/MASEN</html>")
    trouves = P.lire_portail("masen", "https://etendering.masen.ma", "Masen", set(), lambda m: None, s)
    assert trouves and all(t["id"].startswith("masen_") and t["source"] == "masen" for t in trouves)
    assert trouves[0]["url"].startswith("https://etendering.masen.ma/")
    deja = {t["id"] for t in trouves}
    assert P.lire_portail("masen", "https://etendering.masen.ma", "Masen", deja, lambda m: None, s) == []


def test_portail_en_panne_ne_casse_rien():
    class Panne:
        def get(self, *a, **k): raise ConnectionError("hors ligne")
    assert P.lire_portail("masen", "https://x", "Masen", set(), lambda m: None, Panne()) == []
