# -*- coding: utf-8 -*-
"""Le modèle interne appris des classements faits à la main."""
import pytest

from app.core.sectors import classify
from app.services import classement_local as L


@pytest.fixture(scope="module")
def exemples():
    ex = L.exemples_fichier()
    assert len(ex) > 3000, "le fichier des classements faits à la main est livré avec l'application"
    return ex


class TestPrecision:
    def test_mieux_que_les_mots_cles_sur_des_avis_jamais_vus(self, exemples):
        """Un avis sur cinq mis de côté; le modèle apprend sur les quatre autres."""
        test = exemples[::5]
        appris = [e for i, e in enumerate(exemples) if i % 5]
        m = L.Modele(appris)
        justes = sures = justes_sures = mots_cles = 0
        for objet, code in test:
            p, confiance = m.predire(objet)
            justes += p == code
            mots_cles += classify(objet) == code
            if confiance >= L.SEUIL:
                sures += 1
                justes_sures += p == code
        n = len(test)
        assert justes / n >= 0.60
        assert justes / n >= mots_cles / n + 0.15
        assert sures / n >= 0.75, "le modèle doit trancher la plupart des avis"
        assert justes_sures / sures >= 0.66


class TestSens:
    @pytest.mark.parametrize("objet, code", [
        ("Nettoyage des bâtiments de l'Institut de Formation Douanière", "S907"),
        ("Gardiennage et surveillance des locaux de la direction provinciale", "S908"),
        ("Restauration collective au profit des internats et cantines scolaires", "S911"),
        ("Achat de véhicules de transport scolaire au profit de la province", "P816"),
        ("Travaux de construction de pistes rurales à la commune", "T301"),
    ])
    def test_ce_qui_est_achete(self, objet, code):
        assert L.predire(objet)[0] == code


class TestListe:
    def test_ne_touche_pas_un_avis_deja_lu(self):
        items = [{"id": "a", "objet": "Gardiennage des locaux de la commune", "secteur": "S913",
                  "secteur_ia": "2026-10-25T10:00:00"}]
        assert L.classer_liste(items) == 0
        assert items[0]["secteur"] == "S913"

    def test_classe_quand_il_est_sur(self):
        items = [{"id": "a", "objet": "Gardiennage et surveillance des locaux administratifs",
                  "secteur": "S913"}]
        assert L.classer_liste(items) == 1
        assert items[0]["secteur"] == "S908"
        assert items[0]["secteur_ia"].startswith("local:")

    def test_garde_les_mots_cles_quand_il_doute(self, monkeypatch):
        monkeypatch.setattr(L, "predire", lambda objet: ("S908", 0.4))
        items = [{"id": "a", "objet": "Divers", "secteur": "S904"}]
        assert L.classer_liste(items) == 0
        assert items[0]["secteur"] == "S904" and not items[0].get("secteur_ia")

    def test_sans_cle_le_modele_interne_prend_le_relais(self, monkeypatch):
        from app.services import classement_ia
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        items = [{"id": "a", "objet": "Nettoyage et entretien des locaux du tribunal",
                  "secteur": "S904"}]
        assert classement_ia.classer_liste(items) == 1
        assert items[0]["secteur"] == "S907"


class TestBase:
    def test_reclasse_et_apprend_des_classements_manuels(self, db):
        db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,scraped_at,url)
                      VALUES('ao_1','Gardiennage et surveillance des locaux de l''agence','A','S913',
                             'actif','2026-10-01','u')""")
        db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,secteur_ia,statut,scraped_at,url)
                      VALUES('ao_2','Gardiennage des locaux du siège','A','S906','manuel:2026-10-25',
                             'actif','2026-10-01','u')""")
        db.commit()
        L.oublier()
        stats = L.reclasser_base()
        assert stats["lus"] == 1 and stats["classes"] == 1
        rows = {r["id"]: r for r in db.execute("SELECT id, secteur, secteur_ia FROM tenders")}
        assert rows["ao_1"]["secteur"] == "S908" and rows["ao_1"]["secteur_ia"].startswith("local:")
        assert rows["ao_2"]["secteur"] == "S906", "un classement fait à la main n'est jamais repris"
        assert ("Gardiennage des locaux du siège", "S906") in L.exemples()
        L.oublier()

    def test_le_modele_de_langage_relit_les_avis_du_modele_interne(self, db):
        from app.services import classement_ia
        db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,secteur_ia,statut,scraped_at,url)
                      VALUES('ao_1','x','A','S908','local:2026-10-25','actif','2026-10-01','u')""")
        db.commit()
        assert [l["id"] for _, l in classement_ia.a_reprendre()] == ["ao_1"]
