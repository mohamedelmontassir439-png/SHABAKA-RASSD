# -*- coding: utf-8 -*-
"""La coquille partagée de l'administration.

Douze pages construites chacune de son côté: onze redéfinissaient la même
palette, et huit sur douze ne menaient qu'au tableau de bord. Ces tests
tiennent les deux promesses du regroupement — chaque page rend, et chaque
page donne accès à toutes les autres.
"""
import glob
import os

import pytest

from app.core.config import cfg

# Les pages d'administration qui s'affichent (on écarte les routes d'action,
# d'export et de flux, qui ne rendent pas de gabarit).
PAGES = [
    "/admin",
    "/admin/sources",
    "/admin/backups",
    "/admin/members",
    "/admin/payments",
    "/admin/recap",
    "/admin/prospection",
    "/admin/companies",
    "/admin/prospects",
    "/admin/sous-traitance",
]

# Ce que le rail doit proposer, depuis n'importe où.
DESTINATIONS = PAGES


@pytest.fixture()
def admin(client):
    client.get("/admin/login")
    client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                      "csrf_token": client.cookies.get("_csrf")})
    return client


@pytest.mark.parametrize("page", PAGES)
def test_chaque_page_rend(admin, page):
    r = admin.get(page)
    assert r.status_code == 200, f"{page} -> {r.status_code}"


@pytest.mark.parametrize("page", PAGES)
def test_chaque_page_donne_acces_a_toutes_les_autres(admin, page):
    """Le défaut d'origine: huit pages sur douze étaient des culs-de-sac."""
    texte = admin.get(page).text
    manquantes = [d for d in DESTINATIONS if f'href="{d}"' not in texte]
    assert not manquantes, f"{page} ne mène pas à: {', '.join(manquantes)}"


@pytest.mark.parametrize("page", PAGES)
def test_la_page_courante_est_signalee(admin, page):
    assert 'aria-current="page"' in admin.get(page).text


class TestPaletteUnique:
    def test_une_seule_page_declare_la_palette(self):
        """La coquille la porte; aucune page ne doit en garder une copie."""
        dossier = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "templates")
        coupables = []
        for chemin in glob.glob(os.path.join(dossier, "admin*.html")):
            nom = os.path.basename(chemin)
            if nom in ("admin_base.html", "admin_login.html"):
                continue
            with open(chemin, encoding="utf-8") as f:
                if "--terre:" in f.read() or "--amber:" in f.read():
                    coupables.append(nom)
        assert not coupables, f"palette dupliquée dans: {', '.join(coupables)}"

    def test_toutes_les_pages_heritent_de_la_coquille(self):
        dossier = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "templates")
        orphelines = []
        for chemin in glob.glob(os.path.join(dossier, "admin*.html")):
            nom = os.path.basename(chemin)
            if nom in ("admin_base.html", "admin_login.html"):
                continue
            with open(chemin, encoding="utf-8") as f:
                if "admin_base.html" not in f.read():
                    orphelines.append(nom)
        assert not orphelines, f"n'héritent pas de la coquille: {', '.join(orphelines)}"


class TestZoneSensible:
    """Ce qui détruit ne se range pas à côté de ce qui consulte."""

    def test_vider_la_base_nest_plus_un_lien_de_navigation(self, admin):
        """Un GET destructeur dans la barre: un préchargement suffisait."""
        assert 'href="/admin/clear' not in admin.get("/admin").text

    def test_vider_la_base_refuse_un_get(self, admin):
        r = admin.get("/admin/clear?confirm=yes", follow_redirects=False)
        assert r.status_code in (404, 405), (
            "la suppression de tous les marchés doit exiger un POST")
