"""L'administration n'est atteignable que par son URL privée.

Le lien « Admin » a disparu du site, mais /admin restait devinable: les
robots testent cette adresse en permanence. Avec ADMIN_GATE, le serveur
répond 404 à qui n'a pas d'abord ouvert l'URL secrète.
"""
import pytest

from app.core.config import cfg

SECRET = "entree-privee-9f3a"


@pytest.fixture()
def porte(monkeypatch):
    monkeypatch.setattr(cfg, "ADMIN_GATE", SECRET)


class TestSansLaPorte:
    def test_admin_introuvable(self, client, porte):
        r = client.get("/admin")
        assert r.status_code == 404

    def test_page_de_connexion_admin_introuvable(self, client, porte):
        # C'est la page qu'un attaquant cherche pour tenter des mots de passe.
        assert client.get("/admin/login").status_code == 404

    def test_toutes_les_sous_pages_couvertes(self, client, porte):
        for chemin in ("/admin/members", "/admin/backups", "/admin/prospection",
                       "/admin/companies/export"):
            assert client.get(chemin).status_code == 404, chemin

    def test_post_aussi_bloque(self, client, porte):
        r = client.post("/admin/login", data={"pwd": "peu importe"})
        assert r.status_code == 404, "une tentative de connexion doit être invisible"

    def test_le_site_public_reste_normal(self, client, porte):
        assert client.get("/").status_code == 200
        assert client.get("/tarifs").status_code == 200


class TestAvecLaPorte:
    def test_l_url_privee_ouvre_l_acces(self, client, porte):
        r = client.get(f"/{SECRET}")
        assert r.status_code == 302 and r.headers["location"] == "/admin/login"
        assert client.cookies.get("_gate"), "un laissez-passer est déposé"
        assert client.get("/admin/login").status_code == 200

    def test_acces_conserve_apres_ouverture(self, client, porte):
        client.get(f"/{SECRET}")
        assert client.get("/admin").status_code in (200, 302)

    def test_url_privee_erronee_sans_effet(self, client, porte):
        r = client.get("/entree-privee-9f3b")
        assert r.status_code == 404
        assert client.get("/admin/login").status_code == 404


class TestPorteNonConfiguree:
    def test_admin_accessible_si_aucune_porte(self, client, monkeypatch):
        # En local et dans les tests, on ne veut pas d'obstacle supplémentaire.
        monkeypatch.setattr(cfg, "ADMIN_GATE", "")
        assert client.get("/admin/login").status_code == 200
