"""Un seul domaine de référence: www renvoie vers le domaine nu.

Servir le même site sous deux domaines fait voir à Google deux sites
identiques qui se concurrencent. Le domaine retenu est celui de SITE_URL.
"""
import pytest

from app.core.config import cfg


@pytest.fixture()
def site(monkeypatch):
    monkeypatch.setattr(cfg, "SITE_URL", "https://marocentrepreneuriat.com")


class TestRedirectionWww:
    def test_www_renvoie_vers_le_domaine_nu(self, client, site):
        r = client.get("/tarifs", headers={"host": "www.marocentrepreneuriat.com"})
        assert r.status_code == 301
        assert r.headers["location"] == "https://marocentrepreneuriat.com/tarifs"

    def test_la_requete_garde_ses_parametres(self, client, site):
        r = client.get("/marches-publics?page=2",
                       headers={"host": "www.marocentrepreneuriat.com"})
        assert r.headers["location"].endswith("/marches-publics?page=2")

    def test_domaine_nu_non_redirige(self, client, site):
        r = client.get("/", headers={"host": "marocentrepreneuriat.com"})
        assert r.status_code == 200

    def test_domaine_railway_non_redirige(self, client, site):
        # L'ancienne adresse doit continuer à servir le site telle quelle.
        r = client.get("/", headers={"host": "atlaspro.up.railway.app"})
        assert r.status_code == 200

    def test_www_d_un_autre_domaine_ignore(self, client, site):
        # On ne redirige que notre propre www, pas n'importe quel hôte.
        r = client.get("/", headers={"host": "www.autre-site.ma"})
        assert r.status_code == 200

    def test_site_configure_en_www_ne_boucle_pas(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "SITE_URL", "https://www.marocentrepreneuriat.com")
        r = client.get("/", headers={"host": "www.marocentrepreneuriat.com"})
        assert r.status_code == 200, "une redirection vers soi-même boucle à l'infini"
