# -*- coding: utf-8 -*-
"""Le classement par le sens. Aucun appel réel: un faux client répond."""
import json
from types import SimpleNamespace

import pytest

from app.services import classement_ia as C


class FauxClient:
    """Imite client.beta.messages.create et garde les requêtes reçues."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.requetes = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requetes.append(kw)
        r = self.reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(r))])


def _rep(*paires):
    return {"classements": [{"id": i, "secteur": s} for i, s in paires]}


class TestRequete:
    def test_schema_ferme_et_consignes(self):
        client = FauxClient([_rep(("a", "S911"))])
        C.classer_lot([{"id": "a", "objet": "Nettoyage des locaux de l'Institut de Formation"}], client)
        kw = client.requetes[0]
        assert kw["model"] == "claude-opus-5-5"
        enum = kw["output_config"]["format"]["schema"]["properties"]["classements"]["items"][
            "properties"]["secteur"]["enum"]
        assert len(enum) == 83, "seuls les 83 secteurs officiels"
        assert "CE QUI EST ACHETÉ OU EXÉCUTÉ" in kw["system"][0]["text"]
        assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert "Institut de Formation" in kw["messages"][0]["content"]

    def test_un_code_hors_referentiel_est_ignore(self):
        client = FauxClient([_rep(("a", "S911"), ("b", "ZZZ"), ("inconnu", "T101"))])
        codes = C.classer_lot([{"id": "a", "objet": "x"}, {"id": "b", "objet": "y"}], client)
        assert codes == {"a": "S911"}


class TestListe:
    def test_classe_en_place_par_lots(self, monkeypatch):
        monkeypatch.setattr(C, "LOT", 2)
        items = [{"id": f"t{i}", "objet": f"objet {i}", "secteur": "S904"} for i in range(3)]
        client = FauxClient([_rep(("t0", "P816"), ("t1", "T104")), _rep(("t2", "S906"))])
        assert C.classer_liste(items, client) == 3
        assert [i["secteur"] for i in items] == ["P816", "T104", "S906"]
        assert all(i["secteur_ia"] for i in items)
        assert len(client.requetes) == 2

    def test_panne_de_l_api_garde_le_classement_par_mots(self):
        import anthropic
        import httpx2
        erreur = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
        items = [{"id": "t0", "objet": "x", "secteur": "S904"}]
        assert C.classer_liste(items, FauxClient([erreur])) == 0
        assert items[0]["secteur"] == "S904" and "secteur_ia" not in items[0]

    def test_sans_cle_rien_n_est_appele(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        items = [{"id": "t0", "objet": "x", "secteur": "S904"}]
        assert C.classer_liste(items) == 0


class TestEnregistrement:
    def test_secteur_ia_enregistre(self, db):
        import main
        t = {"id": "ao_1", "objet": "Climatisation des salles de la Fondation", "acheteur": "F",
             "secteur": "T104", "secteur_ia": "2026-10-24T10:00:00", "url": "u", "statut": "actif",
             "scraped_at": "2026-10-24 10:00:00", "date_limite": "01/12/2026"}
        main._save_tenders([t], [])
        r = db.execute("SELECT secteur, secteur_ia FROM tenders WHERE id='ao_1'").fetchone()
        assert tuple(r) == ("T104", "2026-10-24T10:00:00")


class TestReprise:
    def _avis(self, db, tid, objet, secteur):
        db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,scraped_at,url)
                      VALUES(?,?,'A',?,'actif','2026-10-01','u')""", (tid, objet, secteur))
        db.commit()

    def test_reprise_et_changements(self, db, monkeypatch):
        monkeypatch.setattr(C, "LOT", 25)
        self._avis(db, "ao_1", "Nettoyage des bâtiments de l'Institut de Formation", "S913")
        self._avis(db, "ao_2", "Travaux de construction d'un lycée", "T101")
        client = FauxClient([_rep(("ao_1", "S906"), ("ao_2", "T101"))])
        C.reclasser(client=client)
        assert C.ReclassementState.faits == 2 and C.ReclassementState.changes == 1
        assert db.execute("SELECT secteur FROM tenders WHERE id='ao_1'").fetchone()[0] == "S906"
        assert C.a_reprendre() == [], "un avis lu n'est pas repris"

    def test_arret_apres_trois_lots_sans_reponse(self, db, monkeypatch):
        import anthropic
        import httpx2
        monkeypatch.setattr(C, "LOT", 1)
        for i in range(5):
            self._avis(db, f"ao_{i}", f"objet {i}", "S904")
        err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x"))
        client = FauxClient([err] * 5)
        C.reclasser(client=client)
        assert "trois lots" in C.ReclassementState.arret and len(client.requetes) == 3

    def test_page_admin(self, admin, db, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        page = admin.get("/admin/classement").text
        assert "Clé d'API absente" in page and "ANTHROPIC_API_KEY" in page
