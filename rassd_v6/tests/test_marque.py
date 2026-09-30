"""Le logo sort d'un seul endroit, et tient à toutes les tailles.

Dessiné dans chaque gabarit, il aurait fini différent partout: une version
dans la navigation, une autre dans les emails, une troisième sur le document
qu'un membre imprime et remet à un maître d'ouvrage.
"""
import math
import re

import pytest

from app.core import marque as M


class TestGeometrie:
    def test_les_arcs_se_ferment_sur_le_cercle(self):
        """Une extrémité posée au jugé laisse un décrochement visible.

        Pour une corde horizontale à distance e du centre, la demi-largeur
        vaut racine(r² − e²). Le dessin doit respecter ce calcul.
        """
        svg = M.logo(300)
        xs = [float(v) for v in re.findall(r"M (\d+\.?\d*) 1[48]0", svg)]
        attendu = 210 - math.sqrt(150 ** 2 - 20 ** 2)
        for x in xs:
            assert abs(x - attendu) < 0.05, f"{x} au lieu de {attendu:.2f}"

    def test_le_cadre_est_plus_large_que_le_disque(self):
        # Le nom déborde du disque: sans marge, il serait coupé.
        svg = M.logo(300)
        assert 'viewBox="0 0 420 320"' in svg
        assert "MAROC ENTREPRENEURIAT" in svg

    @pytest.mark.parametrize("taille", [16, 24, 32, 48, 96, 512])
    def test_la_marque_se_decline_a_toute_taille(self, taille):
        svg = M.marque(taille)
        assert f'width="{taille}"' in svg and 'viewBox="0 0 100 100"' in svg


class TestUsages:
    def test_le_favicon_est_encode_pour_un_attribut_href(self):
        uri = M.favicon_data_uri()
        assert uri.startswith("data:image/svg+xml,")
        for interdit in ('"', "<", ">", "#"):
            assert interdit not in uri, f"{interdit} casserait l'attribut"

    @pytest.mark.parametrize("fabrique", [M.logo_email, M.logo_email_sombre])
    def test_les_emails_n_embarquent_aucun_svg(self, fabrique):
        """Gmail supprime les SVG insérés et bloque les images distantes."""
        html = fabrique()
        assert "<svg" not in html and "<img" not in html
        assert "MAROC ENTREPRENEURIAT" in html

    def test_l_en_tete_de_document_nomme_la_plateforme_en_toutes_lettres(self):
        # Réduit à la hauteur d'un en-tête, le logo empilé rend son nom
        # illisible: le document imprimé porte donc la version horizontale.
        html = M.entete_document(54)
        assert "MAROC ENTREPRENEURIAT" in html
        assert "<svg" in html, "la marque reste vectorielle sur un document"


class TestCouleurs:
    def test_les_teintes_sont_celles_de_la_plateforme(self):
        assert (M.OR, M.TERRE, M.ENCRE, M.CREME) == \
               ("#f2662d", "#c94e1f", "#2b211b", "#f8f1e1")

    def test_la_couleur_du_texte_s_adapte_au_fond(self):
        clair = M.logo(300, couleur_texte=M.ENCRE)
        sombre = M.logo(300, couleur_texte=M.CREME)
        assert M.ENCRE in clair and M.CREME in sombre
