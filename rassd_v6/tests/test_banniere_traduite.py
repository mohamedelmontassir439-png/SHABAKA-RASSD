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
    """La règle CSS entière, accolades de Jinja comprises.

    Une expression qui s'arrête à la première accolade fermante coupe la
    règle au premier `}}` d'un `{{ … }}`: depuis que le fond appelle des
    fabriques de motifs, elle n'en rendait plus que les trois premières
    lignes, et les tests qui la lisaient ne regardaient plus rien.
    """
    src = _gabarit()
    i = src.index(selecteur + " {")
    j = i
    while True:
        j = src.index("}", j + 1)
        if src[j + 1:j + 2] == "}":      # début d'un « }} » de Jinja
            j += 1
            continue
        if src[j - 1:j] == "}":          # fin d'un « }} » de Jinja
            continue
        return src[i:j + 1]


class TestLeTexteEstDuTexte:
    @pytest.mark.parametrize("langue,extrait", [
        ("fr", "Trouvez, comprenez et remportez"),
        ("ar", "اعثر على صفقات المغرب"),
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

    def test_le_fond_ne_charge_aucune_image_tramee(self, client):
        """Seules les données SVG en ligne sont admises: elles ne font pas de
        requête et ne pèsent presque rien.

        Sur la page rendue, et non sur le gabarit: les motifs y sont des
        appels Jinja, aucune adresse ne s'y lit encore, et ce test passait
        sans rien examiner — une boucle sur une liste vide ne se plaint pas.
        """
        regle = re.search(r"\.hero \{[^}]*\}", client.get("/").text).group(0)
        adresses = re.findall(r"url\(([^)]+)\)", regle)
        # La photo de l'équipe est une balise <img> chargée à part; le fond
        # CSS, lui, n'appelle plus aucune image depuis le 27/10/2026.
        for url in adresses:
            assert url.startswith("data:image/svg+xml"), url[:60]


class TestLaCarteDeLaVeille:
    """Depuis le 27/10/2026 la couverture montre la veille en direct: le
    Maroc en points, balayé par un radar, chaque région avec le nombre réel
    de ses marchés ouverts. Le médaillon reste la marque partout ailleurs."""

    def test_la_carte_porte_les_douze_regions_et_leurs_chiffres(self, client, db):
        import json, html
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,scraped_at,region)
                      VALUES('c1','x','T101','actif','2026-10-27','Agadir Ida Ou Tanane'),
                            ('c2','y','T101','actif','2026-10-27','Taroudannt'),
                            ('c3','z','T101','expire','2026-10-27','Agadir')""")
        db.commit()
        page = client.get("/").text
        m = re.search(r"data-regions='([^']*)'", page)
        regions = json.loads(html.unescape(m.group(1)))
        assert len(regions) == 12
        souss = next(r for r in regions if r["nom"] == "Souss-Massa")
        assert souss["n"] == 2, "les marchés clos ne comptent pas"
        assert all(-17.5 < r["lon"] < -1 and 20 < r["lat"] < 36.5 for r in regions)

    def test_le_script_est_servi_et_appele(self, client):
        assert '<script src="/static/js/carte-veille.js" defer></script>' in client.get("/").text
        r = client.get("/static/js/carte-veille.js")
        assert r.status_code == 200 and "prefers-reduced-motion" in r.text

    def test_les_noms_suivent_la_langue(self, client):
        import json, html
        page = client.get("/?lang=ar").text
        regions = json.loads(html.unescape(re.search(r"data-regions='([^']*)'", page).group(1)))
        assert "سوس ماسة" in [r["nom"] for r in regions]

    def test_le_contour_comprend_les_provinces_du_sud(self):
        js = open(os.path.join(RACINE, "static", "js", "carte-veille.js"), encoding="utf-8").read()
        assert "[-17.05, 20.85]" in js and "[-15.95, 23.70]" in js, "Lagouira et Dakhla dans le contour"


class TestLaMiseEnPageTientDansLesDeuxSens:
    def test_la_grille_se_retourne_avec_la_langue(self):
        """Sans photo, rien n'impose un côté: en arabe la parole passe à
        droite et la marque à gauche, ce qui est la bonne lecture. Une marge
        physique l'en empêcherait — c'était nécessaire tant que la place
        libre était à gauche de la photo, ça ne l'est plus."""
        regle = _regle(".hero-texte")
        for fige in ("margin-left:", "margin-right:", "position: absolute", "left:"):
            assert fige not in regle, f"{fige} fige un côté"

    def test_sous_900_px_la_marque_passe_sous_la_parole(self):
        petit = re.search(r"@media\(max-width: 900px\) \{.*?\n\}", _gabarit(), re.S).group(0)
        assert ".hero-inner { grid-template-columns: minmax(0, 1fr)" in petit
        assert ".hero-marque { order: 2; }" in petit

    def test_le_mouvement_se_tait_quand_on_le_demande(self):
        assert "prefers-reduced-motion" in _gabarit()


class TestFriseEtApercu:
    """Deux coutures de la page d'accueil.

    La couverture est sombre et texturée, le corps est clair et lisse: sans
    rien entre les deux, ils se touchent comme deux sites cousus l'un à
    l'autre. Et la section « derniers marchés » montrait, au visiteur
    anonyme, un grand cadre vide qui disait seulement ce qu'il n'aurait pas.
    """

    def test_la_photo_de_couverture_reste_nette(self):
        """Depuis le 27/10/2026 la photo de l'équipe porte la couverture:
        ni frise, ni rosaces, ni trame par-dessus, et un médaillon ajouré."""
        regle = _regle(".hero")
        for motif in ("fond_frise", "fond_rosace", "fond_trame"):
            assert motif not in regle
        page = open(os.path.join(RACINE, "templates", "landing.html"), encoding="utf-8").read()
        assert 'class="hero-photo"' in page and "hero-meridiens" not in page

    def test_aucun_marche_nest_montre_au_visiteur_anonyme(self, client):
        """Le détail d'un marché est réservé aux membres activés. L'aperçu
        montre des secteurs et leur nombre — un agrégat de même nature que
        les totaux déjà affichés — et jamais un objet de marché."""
        from app.core.database import get_db
        db = get_db()
        objets = [r[0] for r in db.execute(
            "SELECT objet FROM tenders WHERE statut='actif' LIMIT 5").fetchall()]
        db.close()
        page = client.get("/").text
        for objet in objets:
            assert objet[:40] not in page, f"objet de marché exposé: {objet[:40]!r}"

    def test_lapercu_annonce_ce_quil_montre(self, client):
        """« Voici ce qui vient de paraître » au-dessus d'une liste de
        secteurs annonce autre chose que ce qui suit."""
        from app.core.i18n import tr
        page = client.get("/").text
        assert tr("latest_label_secteurs", "fr") in page
        assert "ça bouge" in page

    def test_lapercu_nest_pas_cliquable(self, client):
        """Il ne mène nulle part: le faire ressembler à un lien serait
        promettre une page qui n'existe pas pour ce visiteur."""
        page = client.get("/").text
        bloc = page[page.index("latest-apercu"):]
        bloc = bloc[:bloc.index("latest-promo")]
        assert "<a " not in bloc
