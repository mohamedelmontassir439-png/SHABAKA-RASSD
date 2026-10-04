# -*- coding: utf-8 -*-
"""La bannière d'accueil ne doit plus porter son texte en dur.

Le titre, l'étiquette et le paragraphe étaient gravés dans l'image: la page
arabe affichait donc une phrase française, et aucun moteur de recherche ne
lisait l'accroche. Les lettres ont été effacées de l'image et le texte est
revenu en HTML, posé à l'emplacement qu'elles occupaient.

Ce qui casse sans qu'on le voie, et que ces tests retiennent:

- une propriété logique (`inset-inline-start`) renvoie le bloc à droite en
  arabe, c'est-à-dire par-dessus le globe: le texte devient illisible.
- une taille en pixels ne suit pas l'image, qui est en largeur relative: le
  bloc déborde du cadre sombre dès qu'on change de largeur d'écran.
"""
import os
import re

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GABARIT = os.path.join(RACINE, "templates", "landing.html")


def _gabarit():
    with open(GABARIT, encoding="utf-8") as f:
        return f.read()


class TestLeTexteEstDuTexte:
    @pytest.mark.parametrize("langue,extrait", [
        ("fr", "La veille qui trouve"),
        ("ar", "الرصد الذي يجد"),
    ])
    def test_l_accroche_est_rendue_dans_la_langue_demandee(self, client, langue, extrait):
        page = client.get(f"/?lang={langue}").text
        assert extrait in page, f"accroche absente en {langue}"
        titre = re.search(r'<h1 class="hero-titre">(.*?)</h1>', page, re.S)
        assert titre and extrait in titre.group(1)

    def test_l_etiquette_et_le_paragraphe_suivent_aussi(self, client):
        page = client.get("/?lang=ar").text
        assert "الصفقات العمومية وشبه العمومية" in page
        assert "قطاعك" in page

    def test_aucun_titre_n_est_cache_a_l_oeil(self):
        """Le h1 était masqué parce que l'image portait le vrai titre; il ne
        doit pas rester deux titres, l'un lu, l'autre vu."""
        assert "hors-ecran" not in _gabarit()

    def test_la_banniere_est_decorative(self):
        """Son texte de remplacement répétait l'accroche, désormais à côté
        d'elle: un lecteur d'écran l'annonçait deux fois."""
        m = re.search(r'<img class="hero-banniere"[^>]*>', _gabarit(), re.S)
        assert m and 'alt=""' in m.group(0), m.group(0) if m else "image absente"


class TestLePlacementTientDansLesDeuxSens:
    def test_le_bloc_est_cale_a_gauche_physiquement(self):
        """La place libre dans l'image est à gauche, dans les deux langues."""
        regle = re.search(r"\.hero-texte \{[^}]*\}", _gabarit()).group(0)
        assert "left:" in regle
        assert "inset-inline-start" not in regle, (
            "propriété logique: en arabe le bloc passe sur le globe")

    def test_les_tailles_suivent_la_largeur_de_la_banniere(self):
        """En pixels fixes, le texte sort du cadre sombre dès qu'on change
        de largeur: l'image, elle, est en pourcentage."""
        gabarit = _gabarit()
        for classe in (".hero-titre", ".hero-dek", ".hero-sur"):
            regle = re.search(re.escape(classe) + r" \{[^}]*\}", gabarit).group(0)
            assert "cqw" in regle, f"{classe} ne suit pas la bannière"

    def test_la_banniere_sert_de_conteneur_de_reference(self):
        """Sans `container-type`, les cqw retombent sur la taille par défaut."""
        regle = re.search(r"\.hero \{[^}]*\}", _gabarit()).group(0)
        assert "container-type: inline-size" in regle

    def test_sous_900_px_le_bloc_revient_dans_le_flux(self):
        """Posé sur une bannière large de 400 px, le texte serait illisible."""
        petit = re.search(r"@media\(max-width: 900px\) \{.*?\n\}", _gabarit(), re.S).group(0)
        assert "position: static" in petit
