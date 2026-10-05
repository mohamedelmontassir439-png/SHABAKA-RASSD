# -*- coding: utf-8 -*-
"""La couverture d'accueil: du texte lisible, une marque, un seul fond.

Trois états se sont succédé, et chacun a laissé un piège:

1. Le titre était gravé dans un JPEG. La page arabe affichait donc une
   accroche française, et aucun moteur de recherche ne lisait la première
   phrase du site. Le texte est revenu en HTML.
2. La photo servait de fond, mais un dégradé et un motif de zellige
   l'accompagnaient: ils ne se voyaient que là où elle s'arrêtait, ce qui
   faisait deux fonds et une couture au milieu de la section.
3. La photo a été retirée. Le fond est désormais peint par CSS en une seule
   propriété `background`, et la marque — le médaillon, le même tracé qu'en
   en-tête de document — tient la place qu'occupait le globe de la photo.

Ce que ces tests retiennent, c'est ce qui casse sans qu'on le voie.
"""
import os
import re

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GABARIT = os.path.join(RACINE, "templates", "landing.html")


def _gabarit():
    with open(GABARIT, encoding="utf-8") as f:
        return f.read()


def _regle(selecteur):
    m = re.search(re.escape(selecteur) + r"\s*\{[^}]*\}", _gabarit())
    assert m, f"règle introuvable: {selecteur}"
    return m.group(0)


class TestLeTexteEstDuTexte:
    @pytest.mark.parametrize("langue,extrait", [
        ("fr", "La veille qui trouve"),
        ("ar", "الرصد الذي يجد"),
    ])
    def test_l_accroche_est_rendue_dans_la_langue_demandee(self, client, langue, extrait):
        page = client.get(f"/?lang={langue}").text
        titre = re.search(r'<h1 class="hero-titre">(.*?)</h1>', page, re.S)
        assert titre and extrait in titre.group(1), f"accroche absente en {langue}"

    def test_l_etiquette_et_le_paragraphe_suivent_aussi(self, client):
        page = client.get("/?lang=ar").text
        assert "الصفقات العمومية وشبه العمومية" in page
        assert "قطاعك" in page

    def test_aucun_titre_n_est_cache_a_l_oeil(self):
        """Il ne doit pas rester deux titres, l'un lu, l'autre vu."""
        assert "hors-ecran" not in _gabarit()


class TestAucuneImageDansLaCouverture:
    def test_la_photo_a_disparu(self):
        """Elle imposait son cadrage, sa couture, et 300 Ko au premier écran."""
        gabarit = _gabarit()
        assert "hero.jpg" not in gabarit
        assert "hero-banniere" not in gabarit

    def test_le_fond_est_une_seule_propriete(self):
        """Un `::before` posé par-dessus, c'était le second fond: il ne se
        voyait que là où le premier s'arrêtait."""
        assert ".hero::before" not in _gabarit()
        assert _regle(".hero").count("background:") == 1

    def test_le_fond_ne_charge_aucune_image_tramee(self):
        """Seules les données SVG en ligne sont admises: elles ne font pas de
        requête et ne pèsent presque rien."""
        for url in re.findall(r'url\(["\']?([^"\')]+)', _regle(".hero")):
            assert url.startswith("data:image/svg+xml"), url


class TestLaMarqueEstConservee:
    def test_le_medaillon_est_rendu_dans_la_couverture(self, client):
        page = client.get("/").text
        bloc = page[page.index('class="hero-marque"'):]
        bloc = bloc[:bloc.index("</section>")]
        for morceau in ("Maroc", "Entrepreneuriat", "COUVERTURE NATIONALE"):
            assert morceau in bloc, morceau

    def test_c_est_le_trace_commun_et_non_une_copie(self):
        """Une marque redessinée dans un gabarit cesse de suivre les autres."""
        assert "medaillon(" in _gabarit()

    def test_la_mention_tient_dans_le_cercle(self):
        """Mesurée dans le navigateur: à 12 px avec 4 d'interlettrage elle
        faisait 236 unités pour une corde de 165 à cette hauteur — elle
        traversait le cercle des deux côtés, et cela ne se voyait qu'en grand."""
        from app.core import marque
        m = re.search(r'letter-spacing="([\d.]+)"[^>]*font-size="([\d.]+)"',
                      marque.medaillon(300), re.S)
        assert m, "mention introuvable"
        interlettrage, corps = float(m.group(1)), float(m.group(2))
        # 20 glyphes; largeur moyenne mesurée à 0,667 du corps en Arial.
        largeur = 20 * corps * 0.667 + 19 * interlettrage
        assert largeur < 160, f"mention large de {largeur:.0f} pour une corde de 165"


class TestLaMiseEnPageTientDansLesDeuxSens:
    def test_la_grille_se_retourne_avec_la_langue(self):
        """Sans photo, rien n'impose un côté: en arabe la parole passe à
        droite et la marque à gauche, ce qui est la bonne lecture. Une marge
        physique l'en empêcherait — c'était nécessaire tant que la place
        libre était à gauche de la photo, ça ne l'est plus."""
        regle = _regle(".hero-texte")
        for fige in ("margin-left:", "margin-right:", "position: absolute", "left:"):
            assert fige not in regle, f"{fige} fige un côté"

    def test_l_anneau_ne_reprend_pas_sa_place_dans_le_flux(self):
        """« .hero-marque svg » l'emportait en spécificité sur « .hero-anneau »:
        l'anneau redevenait un élément du flux et poussait le médaillon contre
        le bord droit."""
        assert ".hero-marque > svg:not(.hero-anneau)" in _gabarit()

    def test_sous_900_px_la_marque_passe_sous_la_parole(self):
        petit = re.search(r"@media\(max-width: 900px\) \{.*?\n\}", _gabarit(), re.S).group(0)
        assert ".hero-inner { grid-template-columns: minmax(0, 1fr)" in petit
        assert ".hero-marque { order: 2; }" in petit

    def test_le_mouvement_se_tait_quand_on_le_demande(self):
        assert "prefers-reduced-motion" in _gabarit()
