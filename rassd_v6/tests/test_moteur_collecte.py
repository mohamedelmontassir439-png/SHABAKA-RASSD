# -*- coding: utf-8 -*-
"""Le choix du moteur de collecte, sur la page annuaire.

Le serveur n'embarque pas de navigateur: le moteur Google Maps y échoue
immédiatement. Le proposer coché par défaut menait l'utilisateur droit dans
le mur — constaté en production le 02/10/2026.
"""
import pytest

from app.core.config import cfg


@pytest.fixture()
def admin(client):
    client.get("/admin/login")
    client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                      "csrf_token": client.cookies.get("_csrf")})
    return client


def _page(admin, monkeypatch, cle):
    monkeypatch.setattr(cfg, "GOOGLE_PLACES_API_KEY", cle, raising=False)
    r = admin.get("/admin/companies")
    assert r.status_code == 200
    return r.text


class TestMoteurParDefaut:
    def test_avec_cle_places_est_coche(self, admin, monkeypatch):
        page = _page(admin, monkeypatch, "cle-de-test")
        bloc = page[page.index('value="places"'):page.index('value="places"') + 120]
        assert "checked" in bloc

    def test_avec_cle_maps_nest_plus_coche(self, admin, monkeypatch):
        page = _page(admin, monkeypatch, "cle-de-test")
        bloc = page[page.index('value="maps"'):page.index('value="maps"') + 90]
        assert "checked" not in bloc

    def test_sans_cle_places_est_desactive(self, admin, monkeypatch):
        page = _page(admin, monkeypatch, "")
        bloc = page[page.index('value="places"'):page.index('value="places"') + 120]
        assert "disabled" in bloc and "checked" not in bloc

    def test_sans_cle_maps_reste_le_seul_choix(self, admin, monkeypatch):
        page = _page(admin, monkeypatch, "")
        bloc = page[page.index('value="maps"'):page.index('value="maps"') + 90]
        assert "checked" in bloc


class TestAvertissement:
    def test_la_page_dit_que_le_serveur_na_pas_de_navigateur(self, admin, monkeypatch):
        assert "n'embarque pas de navigateur" in _page(admin, monkeypatch, "")

    def test_le_moteur_maps_est_etiquete_local(self, admin, monkeypatch):
        assert "sur votre ordinateur seulement" in _page(admin, monkeypatch, "").lower()


class TestMessageDerreur:
    """Ce que lit l'utilisateur quand le moteur Maps est lancé sur le serveur."""

    @pytest.fixture()
    def sans_navigateur(self, monkeypatch):
        """Simule l'absence de Playwright, comme sur Railway."""
        import sys
        monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
        monkeypatch.setitem(sys.modules, "playwright", None)

    def _message(self, sans_navigateur):
        from app.services.maps_scraper import collecter
        dit = []
        collecter(["T101"], ["Casablanca"], log_fn=dit.append)
        return " ".join(dit)

    def test_il_dit_ou_est_la_voie_qui_marche(self, sans_navigateur):
        assert "GOOGLE_PLACES_API_KEY" in self._message(sans_navigateur)

    def test_il_ne_conseille_plus_une_installation_impossible(self, sans_navigateur):
        """« pip install playwright » n'a pas de sens sur un serveur reconstruit."""
        assert "pip install" not in self._message(sans_navigateur)

    def test_il_propose_la_collecte_locale(self, sans_navigateur):
        assert "votre ordinateur" in self._message(sans_navigateur)
