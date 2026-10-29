# -*- coding: utf-8 -*-
"""Entreprises suivies chez l'agrégateur (Maroc Telecom): seul l'acheteur compte."""
from app.services import private_scraper as p


def _ligne(tid, org, objet):
    return (f'<tr class="odd"><td><div class="favimg_custom" id="{tid}"></div></td>'
            f'<td><b>Organisme :</b> {org} <br/><br/><b>Objet :</b> {objet} </td>'
            f'<td><span style="color:orange">16/11/2026 10:00</span></td></tr>')


class FausseSession:
    def __init__(self, html): self.html = html
    def get(self, *a, **k):
        class R:
            status_code = 200
            text = self.html
            def raise_for_status(self): pass
        return R()


def test_seuls_les_avis_de_lentreprise():
    html = _ligne("1", "Maroc telecom ( IAM )", "peinture de la flotte automobile") + \
           _ligne("2", "Commune de Fes", "câblage pour maroc telecom")
    nom, motif = p.ORGANISMES_SUIVIS[0]
    trouves = p._organisme_suivi(FausseSession(html), nom, motif, set(), lambda m: None)
    assert [t["id"] for t in trouves] == ["gm_1"]


def test_deja_connu_ignore():
    html = _ligne("1", "Maroc telecom ( IAM )", "peinture de la flotte automobile")
    nom, motif = p.ORGANISMES_SUIVIS[0]
    assert p._organisme_suivi(FausseSession(html), nom, motif, {"gm_1"}, lambda m: None) == []
