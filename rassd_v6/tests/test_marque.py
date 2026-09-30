"""La marque sort d'un seul endroit, et tient à toutes les tailles.

Le signe est le khatim, l'étoile à huit branches du zellige marocain.
Dessiné dans chaque gabarit, il aurait fini différent partout: une version
dans la navigation, une autre dans les emails, une troisième sur le document
qu'un membre imprime et remet à un maître d'ouvrage.
"""
import math
import re

import pytest

from app.core import marque as M


class TestGeometrieDuKhatim:
    def test_le_rapport_creux_pointe_est_celui_du_khatim(self):
        """Deux carrés superposés, l'un pivoté d'un quart de tour.

        Les creux tombent à R·cos(45°)/cos(22,5°). Posé au jugé, ce rapport
        donne une fleur ou une roue dentée, pas une étoile marocaine.
        """
        assert abs(M._CREUX - 0.76537) < 1e-4

    def test_les_seize_sommets_alternent_pointe_et_creux(self):
        coords = [(float(x), float(y)) for x, y in
                  re.findall(r"[ML] (-?\d+\.\d+) (-?\d+\.\d+)", M._sommets(48))]
        assert len(coords) == 16
        for i, (x, y) in enumerate(coords):
            rayon = math.hypot(x - 50, y - 50)
            attendu = 48 if i % 2 == 0 else 48 * M._CREUX
            assert abs(rayon - attendu) < 0.05, \
                f"sommet {i}: {rayon:.2f} au lieu de {attendu:.2f}"

    def test_la_pointe_est_en_haut(self):
        premier = re.search(r"M (-?\d+\.\d+) (-?\d+\.\d+)", M._sommets(48))
        assert abs(float(premier.group(1)) - 50) < 0.05
        assert abs(float(premier.group(2)) - 2) < 0.05

    def test_le_centre_est_ajoure_en_decoupe_reelle(self):
        # Peint en blanc, l'ajour ferait une tache sur tout fond non blanc.
        svg = M.etoile(48)
        assert 'fill-rule="evenodd"' in svg
        assert "#fff" not in svg.lower() and "white" not in svg.lower()


class TestPetitesTailles:
    @pytest.mark.parametrize("taille", [16, 24, 32, 48, 96, 512])
    def test_la_marque_se_decline_a_toute_taille(self, taille):
        svg = M.etoile(taille)
        assert f'width="{taille}"' in svg and 'viewBox="0 0 100 100"' in svg

    def test_l_ajour_disparait_sous_vingt_pixels(self):
        # À cette taille il se refermerait en deux ou trois pixels sales.
        assert "L 70 50" not in M.etoile(16)
        assert "L 70 50" in M.etoile(32)


class TestUsages:
    def test_le_favicon_est_encode_pour_un_attribut_href(self):
        uri = M.favicon_data_uri()
        assert uri.startswith("data:image/svg+xml,")
        for interdit in ('"', "<", ">", "#"):
            assert interdit not in uri, f"{interdit} casserait l'attribut"

    @pytest.mark.parametrize("fabrique", [M.logo_email, M.logo_email_sombre])
    def test_les_emails_sont_en_typographie_seule(self, fabrique):
        """Gmail supprime les SVG insérés et bloque les images distantes.

        Reconstituer l'étoile en CSS demanderait clip-path, qu'aucun client
        de messagerie n'interprète: le nom entre deux filets rend partout.
        """
        html = fabrique()
        assert "<svg" not in html and "<img" not in html
        assert "clip-path" not in html
        assert "MAROC" in html and "ENTREPRENEURIAT" in html

    def test_le_logo_associe_la_marque_et_le_nom(self):
        html = M.logo(44)
        assert "<svg" in html, "la marque reste vectorielle"
        assert "MAROC" in html and "ENTREPRENEURIAT" in html

    def test_l_en_tete_de_document_porte_la_ligne_de_description(self):
        # Ce document part chez un maître d'ouvrage: il doit dire d'où il
        # vient sans qu'on le cherche.
        assert "Veille des marchés" in M.entete_document(52)
        assert "Veille des marchés" not in M.logo(44), "réservé aux documents"


class TestCouleurs:
    def test_les_teintes_sont_celles_de_la_plateforme(self):
        assert (M.OR, M.TERRE, M.ENCRE, M.CREME) == \
               ("#f2662d", "#c94e1f", "#2b211b", "#f8f1e1")

    def test_le_nom_s_adapte_au_fond(self):
        assert M.ENCRE in M.logo(44, couleur_texte=M.ENCRE)
        assert M.CREME in M.logo(44, couleur_texte=M.CREME)


class TestResistanceALaCompression:
    """La marque ne doit pas être la variable d'ajustement d'une barre serrée.

    Relevé en production le 30/09/2026: l'étoile avait disparu de l'en-tête
    d'un membre connecté — neuf liens de navigation — tout en restant
    visible dans le pied de page. La règle « svg { max-width: 100% } » la
    laissait se réduire à rien pendant que le nom, en nowrap, tenait sa
    place.
    """

    @pytest.mark.parametrize("taille", [28, 38, 42, 52])
    def test_la_marque_refuse_de_retrecir(self, taille):
        svg = M.etoile(taille)
        assert "flex:none" in svg
        assert f"min-width:{taille}px" in svg

    def test_le_logo_complet_protege_aussi_sa_marque(self):
        assert "flex:none" in M.logo(42)


class TestLisibiliteSurFondSombre:
    def test_le_nom_passe_en_creme_quand_on_le_demande(self):
        # Laissé en encre sur la barre latérale brune, il devenait illisible.
        sombre = M.logo(38, couleur_texte=M.CREME)
        assert M.CREME in sombre and f"color:{M.ENCRE}" not in sombre
