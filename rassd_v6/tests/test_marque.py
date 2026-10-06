# -*- coding: utf-8 -*-
"""L'identité visuelle: un globe de méridiens dans un médaillon cerclé.

Le signe dit ce que fait la plateforme — une couverture nationale, une
veille qui embrasse le territoire. L'étoile sous le nom est celle du
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
        pas une sphère.

        L'expression ne suppose rien de ce qui précède « cx »: elle cherchait
        « <ellipse cx », et le jour où les méridiens ont reçu une classe elle
        n'a plus rien trouvé — or une liste vide est décroissante et sans
        doublon, si bien que le test passait sans rien vérifier.
        """
        svg = marque.etoile(64)
        rx = [float(v) for v in
              re.findall(r'<ellipse[^>]*? cx="50" cy="50" rx="([\d.]+)"', svg)]
        assert len(rx) == 3, f"trois méridiens attendus, {len(rx)} trouvés"
        assert rx == sorted(rx, reverse=True) and len(set(rx)) == len(rx)

    def test_aucun_point_blanc_ne_se_pose_sur_la_sphere(self):
        """Il y en avait un, en haut à droite, censé figurer un reflet. À la
        taille où la marque se regarde vraiment, il ne se lisait pas comme un
        reflet mais comme une poussière sur l'écran."""
        assert 'fill="#fff"' not in marque.etoile(64)

    def test_le_relief_vient_du_degrade_et_du_voile(self):
        """C'est ce qui creuse la sphère depuis que le point a disparu: sans
        eux il ne resterait qu'un disque cerclé."""
        svg = marque.etoile(64)
        assert "radialGradient" in svg
        assert svg.count("<ellipse") >= 7

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
    """L'étoile du drapeau marocain, et pas une autre.

    Deux triangles superposés — ce qui occupait cette place jusqu'au
    05/10/2026 — font une étoile à **six** branches. Ce n'est pas celle du
    Maroc, et elle se lit tout autrement. L'erreur a vécu sur la page
    d'accueil, dans l'en-tête des documents et dans l'image de partage.
    """

    def test_letoile_a_cinq_sommets(self):
        pts = re.findall(r'points="([^"]+)"', marque.sceau())
        assert len(pts) == 1, "un seul tracé, d'un seul trait"
        assert len(pts[0].split()) == 5, f"cinq sommets attendus: {pts[0]}"

    def test_elle_est_entrelacee_et_non_remplie(self):
        """C'est le croisement du trait qui fait l'étoile du drapeau; remplie,
        elle devient un pentagone à cinq pointes, une autre figure."""
        assert 'fill="none"' in marque.sceau()

    def test_les_sommets_sont_sur_un_cercle(self):
        """Une étoile dont les sommets ne sont pas équidistants penche."""
        import math
        pts = [tuple(map(float, p.split(",")))
               for p in re.findall(r'points="([^"]+)"', marque.sceau())[0].split()]
        rayons = {round(math.hypot(x - 50, y - 50), 1) for x, y in pts}
        assert len(rayons) == 1, f"sommets à des distances différentes: {rayons}"

    def test_une_pointe_regarde_le_haut(self):
        """Posée sur une pointe, l'étoile paraît tombée."""
        pts = [tuple(map(float, p.split(",")))
               for p in re.findall(r'points="([^"]+)"', marque.sceau())[0].split()]
        haut = min(pts, key=lambda p: p[1])
        assert abs(haut[0] - 50) < 0.2, f"la pointe du haut est décalée: {haut}"

    def test_le_medaillon_porte_la_meme_etoile(self):
        """Il en gardait une copie en dur: corriger le sceau ne la corrigeait
        pas, et les deux signes auraient divergé."""
        from app.core.marque import _etoile_marocaine
        assert _etoile_marocaine() in marque.medaillon(300)


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


class TestRotation:
    """Le globe tourne, et il tourne comme une sphère.

    Un globe qui pivote sur lui-même à l'écran n'est pas un globe qui
    tourne: c'est un dessin qui pivote. Ce sont les méridiens qui
    s'amincissent jusqu'au trait en passant de profil, pendant que les
    parallèles, invariants sous une rotation d'axe vertical, ne bougent pas.
    """

    def test_les_meridiens_portent_le_mouvement(self):
        svg = marque.medaillon(300)
        classes = re.findall(r'<ellipse class="([^"]+)" cx="50" cy="50"', svg)
        assert len(classes) == 3 and len(set(classes)) == 3, classes

    def test_les_trois_sont_dephases(self):
        """Sans décalage, ils s'amincissent ensemble: la sphère bat au lieu
        de tourner."""
        style = re.search(r"<style>(.*?)</style>", marque.medaillon(300), re.S).group(1)
        retards = set(re.findall(r"animation-delay:(-[\d.]+s)", style))
        assert len(retards) == 2, f"deux retards attendus, {retards}"

    def test_le_meridien_de_profil_reste_un_trait(self):
        """`rx: 0` n'est pas une ellipse plate: c'est une ellipse qui ne se
        dessine pas. Le méridien disparaîtrait au lieu de s'amincir."""
        style = re.search(r"<style>(.*?)</style>", marque.medaillon(300), re.S).group(1)
        valeurs = [float(v) for v in re.findall(r"rx:([\d.]+)px", style)]
        assert valeurs and min(valeurs) > 0, f"minimum {min(valeurs) if valeurs else '—'}"

    def test_le_mouvement_suit_le_cosinus(self):
        """Interpolé au plus simple, le méridien ralentit au moment où il
        passe de profil — là où il devrait aller le plus vite."""
        style = re.search(r"<style>(.*?)</style>", marque.medaillon(300), re.S).group(1)
        v = [float(x) for x in re.findall(r"rx:([\d.]+)px", style)]
        milieu = len(v) // 2
        assert v[0] == max(v) and v[milieu] == min(v)
        # Le pas s'accélère vers le profil: dernier écart > premier écart.
        assert (v[milieu - 1] - v[milieu]) > (v[0] - v[1])

    def test_deux_marques_sur_une_page_ne_se_commandent_pas(self):
        """Le style d'un SVG n'est pas isolé: il s'applique à la page."""
        a = set(re.findall(r"@keyframes (\w+)", marque.etoile(64)))
        b = set(re.findall(r"@keyframes (\w+)", marque.etoile(40)))
        assert a and b and not (a & b)

    def test_le_mouvement_se_tait_quand_on_le_demande(self):
        assert "prefers-reduced-motion" in marque.medaillon(300)

    def test_licone_de_longlet_ne_porte_aucun_mouvement(self):
        """Elle est recopiée dans l'en-tête de chaque page: une feuille de
        style y pèserait pour rien, et rien ne l'y regarde tourner."""
        assert "keyframes" not in marque.favicon_data_uri()
        assert "<style>" not in marque.etoile(32, anime=False)

    def test_les_paralleles_ne_bougent_pas(self):
        """Ils sont invariants sous une rotation d'axe vertical; les animer
        trahirait la sphère."""
        svg = marque.medaillon(300)
        animes = re.findall(r'<ellipse class="mg[^"]*"', svg)
        assert len(animes) == 3, "seuls les trois méridiens doivent être animés"


class TestMotifsDuZellige:
    """Le khatam n'est pas « une étoile à huit pointes » dessinée au jugé.

    C'est le polygone étoilé {8/3}: on relie un sommet sur trois d'un
    octogone. Tracé avec deux rayons alternés, il n'est juste que pour un
    rapport précis — cos(3π/8)/cos(2π/8) = 0,5412. Au-delà l'étoile
    s'arrondit en fleur, en deçà elle se hérisse en scie, et dans les deux
    cas l'œil la reconnaît comme fausse.
    """

    def test_le_khatam_a_seize_sommets(self):
        """Huit pointes et huit creux: c'est ce qui en fait une étoile et
        non un octogone."""
        pts = marque._etoile_khatam(0, 0, 100).split()
        assert len(pts) == 16

    def test_le_creux_suit_la_proportion_du_polygone_etoile(self):
        import math
        pts = [tuple(map(float, p.split(","))) for p in
               marque._etoile_khatam(0, 0, 100).split()]
        rayons = [math.hypot(x, y) for x, y in pts]
        pointe, creux = max(rayons), min(rayons)
        assert abs(creux / pointe - 0.5412) < 0.002, f"{creux / pointe:.4f}"

    def test_la_trame_se_raccorde(self):
        """Le même khatam est posé au centre et aux quatre coins. Sans les
        coins, le motif laisse une grille de vides à chaque raccord — et
        c'est au raccord qu'on voit qu'un fond a été fabriqué."""
        svg = marque.trame_zellige(120)
        for coin in ("0.00,", "120.00,"):
            assert coin in svg, f"aucun sommet en {coin}"
        assert svg.count("<polygon") == 5

    @pytest.mark.parametrize("fabrique", ["fond_trame", "fond_rosace"])
    def test_ladresse_tient_dans_un_attribut_style(self, fabrique):
        """Des guillemets doubles autour de l'adresse refermaient l'attribut
        `style` qui la portait, et le motif disparaissait sans un mot."""
        uri = getattr(marque, fabrique)()
        assert uri.startswith("url(data:image/svg+xml,") and uri.endswith(")")
        for interdit in ('"', "'", " ", "#"):
            assert interdit not in uri, f"caractère non encodé: {interdit!r}"

    def test_la_rosace_garde_ses_etoiles_distinctes(self):
        """L'étoile intérieure dépassait de l'extérieure: les deux figures
        se brouillaient en une tache à seize pointes."""
        import math
        svg = marque.rosace(440)
        polys = re.findall(r'<polygon points="([^"]+)"', svg)
        assert len(polys) >= 2
        def rayon_max(p):
            pts = [tuple(map(float, q.split(","))) for q in p.split()]
            return max(math.hypot(x - 220, y - 220) for x, y in pts)
        exterieure, interieure = rayon_max(polys[0]), rayon_max(polys[1])
        assert interieure < exterieure * 0.5412, (
            f"intérieure {interieure:.1f} dépasse le creux de l'extérieure "
            f"{exterieure * 0.5412:.1f}")
