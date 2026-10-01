"""Le numéro affiché doit être le bon, et le contact doit mener quelque part.

Le pied de page portait « +212 5 37 62 96 30 », écrit en dur dans les
traductions: le numéro de personne. Et l'adresse de contact, en simple lien
mailto:, n'ouvrait rien chez qui n'a pas de logiciel de messagerie installé
— cas courant sur Windows comme sur mobile.
"""
import re

import pytest

import main
from app.core.config import cfg


class TestNumeroDAffaires:
    def test_le_numero_vient_de_la_configuration(self):
        assert cfg.PAYMENT_PHONE == "212621728813"

    def test_il_s_affiche_lisiblement(self):
        assert cfg.TELEPHONE_AFFICHE == "+212 6 21 72 88 13"

    def test_le_lien_tel_est_au_format_international(self):
        assert cfg.TELEPHONE_LIEN == "+212621728813"
        assert " " not in cfg.TELEPHONE_LIEN

    def test_aucun_numero_n_est_ecrit_en_dur(self):
        """Celui du pied de page n'était celui de personne."""
        gabarits = open("templates/base_public.html", encoding="utf-8").read()
        traductions = open("app/core/i18n.py", encoding="utf-8").read()
        for texte in (gabarits, traductions):
            assert "537629630" not in texte
            assert "5 37 62 96 30" not in texte

    def test_le_pied_de_page_propose_whatsapp(self):
        # Le compte WhatsApp Business est ouvert sur ce numéro.
        page = open("templates/base_public.html", encoding="utf-8").read()
        assert "wa.me/{{ cfg.PAYMENT_PHONE }}" in page


class TestAdresseDeContact:
    def test_le_clic_copie_l_adresse(self, client):
        """mailto: n'ouvre rien sans logiciel de messagerie: le clic copie."""
        page = client.get("/").text
        assert "js-copier" in page
        assert f'data-copier="{cfg.CONTACT_EMAIL}"' in page

    def test_mailto_reste_en_secours(self, client):
        # Pour qui a bien un client mail, le comportement attendu demeure.
        page = client.get("/").text
        assert f'href="mailto:{cfg.CONTACT_EMAIL}"' in page

    def test_l_adresse_vient_de_la_configuration(self):
        page = open("templates/base_public.html", encoding="utf-8").read()
        assert "mailto:contact@marocentrepreneuriat.com" not in page


class TestPastilleDeProfil:
    @pytest.mark.parametrize("nom, email, attendu", [
        ("mohamed el montassir", "", "MM"),
        ("Ahmed Benali", "", "AB"),
        ("Ahmed", "", "AH"),
        ("", "karim@exemple.ma", "KA"),
        ("", "", "?"),
    ])
    def test_les_initiales(self, nom, email, attendu):
        assert main.initiales(nom, email) == attendu

    @pytest.mark.parametrize("gabarit", ["templates/base.html",
                                         "templates/base_public.html"])
    def test_le_nom_complet_ne_s_etale_dans_aucune_barre(self, gabarit):
        """Deux barres, deux endroits.

        La première correction n'avait touché que l'espace membre: le nom
        continuait de s'afficher en bout de barre sur les pages publiques,
        coupé en plein mot — « moha el mont… ».
        """
        page = open(gabarit, encoding="utf-8").read()
        for marque in ("topbar-user-name", "topbar-user-company", "nav-user-info"):
            assert marque not in page, f"{marque} subsiste dans {gabarit}"
        # Le nom ne doit apparaître que dans l'infobulle.
        for ligne in page.splitlines():
            if "member.nom or member.email" in ligne:
                assert "title=" in ligne, ligne.strip()[:90]

    @pytest.mark.parametrize("gabarit, classe", [
        ("templates/base.html", "topbar-avatar"),
        ("templates/base_public.html", "nav-avatar"),
    ])
    def test_les_deux_barres_portent_la_pastille(self, gabarit, classe):
        page = open(gabarit, encoding="utf-8").read()
        assert f'class="{classe}"' in page
        assert "initiales(member.nom, member.email)" in page

    def test_le_nom_reste_accessible_au_survol(self):
        page = open("templates/base.html", encoding="utf-8").read()
        assert 'title="{{ member.nom or member.email }}' in page

    def test_la_pastille_mene_au_compte(self):
        page = open("templates/base.html", encoding="utf-8").read()
        assert 'href="/settings" class="topbar-avatar"' in page
