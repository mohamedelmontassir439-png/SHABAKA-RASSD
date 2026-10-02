# -*- coding: utf-8 -*-
"""Rapprochement avec un annuaire professionnel externe.

Le risque n'est pas de rater une fiche: c'est d'en poser une qui appartient à
une autre société. Le fondateur composerait alors un numéro étranger en
parlant d'un marché que son interlocuteur n'a jamais remporté.
"""
import pytest

from app.core.config import cfg
from app.services import annuaire_externe


SITEMAP_01 = "\n".join([
    "https://www.kerix.net/en/",
    "https://www.kerix.net/en/annuaire-entreprise/hbayou-entreprise",
    "https://www.kerix.net/en/annuaire-entreprise/simac",
    "https://www.kerix.net/en/annuaire-entreprise/alpha-challenge",
    "https://www.kerix.net/en/annuaire-entreprise/batiment.html",
    "https://www.kerix.net/en/annuaire-entreprise/filtre//ville-casablanca",
])
SITEMAP_02 = "\n".join([
    "https://www.kerix.net/fr/annuaire-entreprise/hbayou-entreprise",
    "https://www.kerix.net/fr/annuaire-entreprise/simac",
])


@pytest.fixture(autouse=True)
def sitemaps_simules(monkeypatch):
    pages = {annuaire_externe.SITEMAPS[0]: SITEMAP_01,
             annuaire_externe.SITEMAPS[1]: SITEMAP_02}
    monkeypatch.setattr(annuaire_externe, "_lire_sitemap",
                        lambda url, log_fn: pages[url].splitlines())


def _gagnant(db, nom, cle, wins=1):
    db.execute("""INSERT INTO companies(legal_name,normalized_name,sector,city,
                  phone,wins,source,created_at)
                  VALUES(?,?,?,?,'',?,'tender_results','2026-09-01T09:00:00')""",
               (nom, cle, "T101", "Marrakech", wins))
    db.commit()
    return db.execute("SELECT id FROM companies WHERE legal_name=?", (nom,)).fetchone()["id"]


class TestIndex:
    def test_les_fiches_sont_indexees_par_nom_canonique(self):
        index = annuaire_externe.index_annuaire(lambda *a: None)
        # « entreprise » est une forme juridique: le nom canonique du slug
        # « hbayou-entreprise » est « hbayou », comme celui de l'attributaire
        # « ENTREPRISE HBAYOU ». C'est exactement ce qui les rapproche.
        assert "hbayou" in index
        assert "simac" in index

    def test_la_version_francaise_est_preferee(self):
        index = annuaire_externe.index_annuaire(lambda *a: None)
        assert "/fr/" in index["simac"]

    def test_les_pages_de_categorie_et_de_filtre_sont_ignorees(self):
        index = annuaire_externe.index_annuaire(lambda *a: None)
        assert not any("filtre" in u for u in index.values())
        # « batiment.html » est une page de catégorie, pas une entreprise.
        assert "batiment" not in index

    def test_un_sitemap_injoignable_ne_fait_pas_echouer(self, monkeypatch):
        def tombe(url, log_fn):
            raise OSError("réseau coupé")
        monkeypatch.setattr(annuaire_externe, "_lire_sitemap", tombe)
        assert annuaire_externe.index_annuaire(lambda *a: None) == {}


class TestAppariement:
    def test_un_nom_identique_recoit_sa_fiche(self, db):
        cid = _gagnant(db, "ENTREPRISE HBAYOU", "hbayou", wins=2)
        annuaire_externe.apparier(lambda *a: None)
        url = db.execute("SELECT annuaire_url FROM companies WHERE id=?", (cid,)).fetchone()[0]
        assert url == "https://www.kerix.net/fr/annuaire-entreprise/hbayou-entreprise"

    def test_un_nom_absent_ne_recoit_rien(self, db):
        cid = _gagnant(db, "SOCIETE INTROUVABLE SARL", "introuvable")
        annuaire_externe.apparier(lambda *a: None)
        assert not db.execute(
            "SELECT annuaire_url FROM companies WHERE id=?", (cid,)).fetchone()[0]

    def test_un_nom_approchant_ne_recoit_rien(self, db):
        """« SIMACO » n'est pas « SIMAC »: aucun lien plutôt qu'un faux."""
        cid = _gagnant(db, "SIMACO SARL", "simaco")
        annuaire_externe.apparier(lambda *a: None)
        assert not db.execute(
            "SELECT annuaire_url FROM companies WHERE id=?", (cid,)).fetchone()[0]

    def test_les_non_gagnants_sont_laisses_de_cote(self, db):
        db.execute("""INSERT INTO companies(legal_name,normalized_name,wins,
                      source,created_at) VALUES('SIMAC','simac',0,'google-maps','x')""")
        db.commit()
        stats = annuaire_externe.apparier(lambda *a: None)
        assert stats["apparies"] == 0

    def test_relancer_ne_change_rien(self, db):
        _gagnant(db, "SIMAC", "simac")
        premier = annuaire_externe.apparier(lambda *a: None)
        second = annuaire_externe.apparier(lambda *a: None)
        assert premier["apparies"] == 1 and second["apparies"] == 0


class TestPage:
    @pytest.fixture()
    def admin(self, client):
        client.get("/admin/login")
        client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                          "csrf_token": client.cookies.get("_csrf")})
        return client

    def test_le_bouton_de_rapprochement_exige_ladmin(self, client):
        r = client.post("/admin/prospection/apparier", data={}, follow_redirects=False)
        assert r.status_code in (302, 303)
        assert "/admin/login" in r.headers.get("location", "")

    def test_apparier_nest_pas_confondu_avec_un_identifiant(self, admin, db):
        """« apparier » ne doit pas tomber dans /admin/prospection/{cid}."""
        _gagnant(db, "SIMAC", "simac")
        admin.get("/admin/prospection?gagnants=1")
        r = admin.post("/admin/prospection/apparier",
                       data={"csrf_token": admin.cookies.get("_csrf")},
                       follow_redirects=False)
        assert r.status_code in (302, 303)
        assert db.execute(
            "SELECT annuaire_url FROM companies WHERE normalized_name='simac'").fetchone()[0]

    def test_la_fiche_affiche_le_lien(self, admin, db):
        cid = _gagnant(db, "SIMAC", "simac")
        admin.get("/admin/prospection?gagnants=1")
        admin.post("/admin/prospection/apparier",
                   data={"csrf_token": admin.cookies.get("_csrf")},
                   follow_redirects=False)
        assert "kerix.net" in admin.get(f"/admin/prospection/{cid}").text
