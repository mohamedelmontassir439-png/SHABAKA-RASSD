# -*- coding: utf-8 -*-
"""L'identité visuelle: un globe de méridiens dans un médaillon cerclé.

Le signe dit ce que fait la plateforme — une couverture nationale, une
veille qui embrasse le territoire. Le sceau à six branches sous le nom est
le khatam, motif du zellige marocain.

Ces tests ne jugent pas du goût: ils tiennent ce qui casse sans qu'on le
voie. Un globe tracé au jugé devient une pelote; un nom trop large sort du
médaillon; un SVG dans un email disparaît chez Gmail.
"""
import re

import pytest

from app.core import marque


class TestGlobe:
    def test_la_sphere_porte_meridiens_et_paralleles(self):
        """Tracés, pas dessinés: trois méridiens, quatre parallèles."""
        svg = marque.etoile(64)
        assert len(re.findall(r"<ellipse", svg)) >= 7, svg[:200]

    def test_les_meridiens_retrecissent_vers_le_centre(self):
        """Des demi-largeurs égales donneraient des cercles concentriques,
        pas une sphère."""
        svg = marque.etoile(64)
        rx = [float(v) for v in re.findall(r'<ellipse cx="50" cy="50" rx="([\d.]+)"', svg)]
        assert rx == sorted(rx, reverse=True) and len(set(rx)) == len(rx)

    def test_le_point_de_lumiere_est_en_haut_a_droite(self):
        """C'est lui qui fait la sphère plutôt que le disque."""
        svg = marque.etoile(64)
        m = re.search(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="[\d.]+" fill="#fff"', svg)
        assert m, "aucun point de lumière"
        assert float(m.group(1)) > 50 and float(m.group(2)) < 50

    def test_le_globe_repose_sur_un_arc(self):
        assert "<path d=" in marque.etoile(64)

    def test_les_degrades_ne_se_confondent_pas_entre_deux_marques(self):
        """Deux marques sur la même page partageraient leurs identifiants, et
        la seconde hériterait du dégradé de la première."""
        ids_a = set(re.findall(r'id="(\w+)"', marque.etoile(64)))
        ids_b = set(re.findall(r'id="(\w+)"', marque.etoile(40)))
        assert ids_a and ids_b and not (ids_a & ids_b)


class TestPetitesTailles:
    def test_sous_vingt_quatre_pixels_le_globe_se_simplifie(self):
        """Les méridiens s'y referment en une tache: on garde la sphère nue."""
        assert "<ellipse" not in marque.etoile(18)
        assert "<ellipse" in marque.etoile(40)

    def test_la_marque_reste_lisible_meme_reduite(self):
        petit = marque.etoile(16)
        assert "<circle" in petit and marque.OR in petit

    def test_la_marque_ne_peut_pas_etre_ecrasee(self):
        """Dans une barre chargée, « svg { max-width: 100% } » la réduisait
        à rien pendant que le nom, en nowrap, tenait sa place."""
        svg = marque.etoile(40)
        assert "flex:none" in svg and "min-width:40px" in svg


class TestSceau:
    def test_le_khatam_est_fait_de_deux_triangles(self):
        assert marque.sceau().count("<polygon") == 2

    def test_les_deux_triangles_sont_decales(self):
        """Superposés sans décalage, ils ne font qu'un triangle."""
        pts = re.findall(r'points="([^"]+)"', marque.sceau())
        assert len(pts) == 2 and pts[0] != pts[1]


class TestMedaillon:
    def test_il_porte_le_nom_le_sceau_et_la_mention(self):
        svg = marque.medaillon(240)
        for morceau in ("Maroc", "Entrepreneuriat", "COUVERTURE NATIONALE", "<polygon"):
            assert morceau in svg, morceau

    def test_le_nom_tient_dans_le_cercle(self):
        """« Entrepreneuriat » à 26 px mesure environ 218 px; la corde du
        cercle à cette hauteur en fait 240. Le corps ne doit pas remonter."""
        corps = [float(v) for v in re.findall(r'font-size="(\d+)"', marque.medaillon(240))]
        assert corps and max(corps) <= 26

    def test_l_arc_ne_traverse_pas_le_nom(self):
        """Le globe descendait trop: son arc coupait « Maroc » en deux."""
        svg = marque.medaillon(240)
        y_nom = min(float(v) for v in re.findall(r'<text x="150" y="(\d+)"', svg))
        echelle = float(re.search(r"scale\(([\d.]+)\)", svg).group(1))
        dy = float(re.search(r"translate\(\d+,(\d+)\)", svg).group(1))
        y_arc = dy + (50 + 30 * 1.16) * echelle
        assert y_arc < y_nom - 10, f"arc={y_arc}, nom={y_nom}"


class TestEmails:
    @pytest.mark.parametrize("fonction", ["logo_email", "logo_email_sombre"])
    def test_les_emails_sont_en_typographie_seule(self, fonction):
        """Gmail supprime le SVG et bloque les images par défaut."""
        html = getattr(marque, fonction)()
        assert "<svg" not in html and "<img" not in html
        assert "Maroc" in html and "Entrepreneuriat" in html

    def test_les_deux_versions_different_par_la_couleur_du_texte(self):
        assert marque.logo_email() != marque.logo_email_sombre()
        assert marque.ENCRE in marque.logo_email()
        assert marque.CREME in marque.logo_email_sombre()


class TestUsages:
    def test_le_logo_associe_la_marque_et_le_nom(self):
        html = marque.logo(44)
        assert "<svg" in html and "Maroc" in html and "Entrepreneuriat" in html

    def test_le_nom_peut_etre_masque_sans_toucher_a_la_marque(self):
        """Le rail masque le nom sous 1400 px pour rendre sa largeur aux liens."""
        assert 'class="me-logo-nom"' in marque.logo(44)

    def test_l_en_tete_de_document_porte_la_mention(self):
        assert "Couverture nationale" in marque.entete_document(52)

    def test_sur_papier_le_nom_passe_en_encre(self):
        """Le fond d'un document imprimé est blanc: la crème y disparaîtrait."""
        assert marque.ENCRE in marque.entete_document(52)

    def test_le_favicon_est_une_adresse_de_donnees(self):
        uri = marque.favicon_data_uri()
        assert uri.startswith("data:image/svg+xml,") and len(uri) > 120


class TestCouleurs:
    def test_un_seul_orange_sur_la_plateforme(self):
        """Deux oranges proches font jurer la marque contre ses boutons."""
        assert marque.OR == "#f2662d"

    def test_les_teintes_sont_declarees_une_fois(self):
        for nom in ("OR", "ENCRE", "CREME", "BRUN"):
            valeur = getattr(marque, nom)
            assert isinstance(valeur, str) and valeur.startswith("#")

class TestIconeDuNavigateur:
    """L'icône de l'onglet était une adresse de données collée à la main.

    Elle est restée l'ancienne étoile à seize sommets pendant que tout le
    reste changeait — le seul endroit de la plateforme que le module de
    marque ne gouvernait pas.
    """

    def test_aucune_coquille_n_ecrit_l_icone_en_dur(self):
        import glob
        import os
        dossier = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "templates")
        fautifs = []
        for chemin in glob.glob(os.path.join(dossier, "*.html")):
            with open(chemin, encoding="utf-8") as f:
                contenu = f.read()
            if re.search(r'rel="icon"[^>]*href="data:', contenu):
                fautifs.append(os.path.basename(chemin))
        assert not fautifs, f"icône écrite en dur dans: {fautifs}"

    def test_les_pages_servent_l_icone_de_la_marque(self, client):
        page = client.get("/").text
        assert 'rel="icon"' in page
        # Le globe porte des ellipses; l'ancienne étoile, un seul chemin.
        assert "ellipse" in page[page.index('rel="icon"'):page.index('rel="icon"') + 3000]

    def test_l_icone_de_l_application_suit_aussi(self, client):
        svg = client.get("/icon-192.svg").text
        assert "<ellipse" in svg and marque.OR in svg
