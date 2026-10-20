# -*- coding: utf-8 -*-
"""Ce que les moteurs de recherche peuvent lire.

Le site exposait l'accueil, les tarifs et les pages sectorielles; les fiches
de marchés renvoyaient vers la connexion. Chaque test ici protège une page
lisible par Google, ou empêche qu'une page privée le devienne.
"""
import re
from datetime import date, timedelta

import pytest


def _marche(db, tid="ao_1043943", source="marchespublics", objet="Achèvement des travaux de la RP5125",
            region="Guercif", secteur="T101", jours=12, statut="actif", n_region=1):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,scraped_at,
                  date_limite,type_offre,type_procedure,source,description)
                  VALUES(?,?,'DIRECTION PROVINCIALE DE L EQUIPEMENT',?,?,'17 540 251,20 MAD',?,
                  '2026-10-04 19:45:58',?,'Public','marche',?,?)""",
               (tid, objet, secteur, region, statut,
                (date.today() + timedelta(days=jours)).strftime("%d/%m/%Y"), source,
                "Référence GRC/07/2026 Objet : x Procédure : Appel d'offres ouvert "
                "Caution provisoire : 350 000,00 MAD Visites des lieux : 28/10/2026 09:00 "
                "Variante : Non"))
    db.commit()


def _tete(html):
    return html.split("</head>")[0]


class TestLaTete:
    def test_une_seule_description_par_page(self, client, db):
        for page in ("/", "/tarifs", "/marches-publics", "/register"):
            assert _tete(client.get(page).text).count('name="description"') == 1, page

    def test_chaque_page_a_sa_description(self, client, db):
        descs = {re.search(r'name="description" content="([^"]*)', _tete(client.get(p).text)).group(1)
                 for p in ("/", "/tarifs", "/register", "/marches-publics")}
        assert len(descs) == 4

    def test_canonique_sans_parametres(self, client, db):
        h = _tete(client.get("/?src=facebook&cmp=s43").text)
        assert 'rel="canonical" href="http://localhost:8000/"' in h or \
            re.search(r'rel="canonical" href="[^"?]*/"', h)

    def test_hreflang_sur_les_pages_bilingues(self, client, db):
        h = _tete(client.get("/").text)
        assert 'hreflang="ar"' in h and 'hreflang="fr"' in h

    def test_pas_de_hreflang_sur_une_page_ecrite_en_francais(self, client, db):
        assert "hreflang" not in _tete(client.get("/marches-publics").text)

    def test_apercu_de_partage(self, client, db):
        h = _tete(client.get("/").text)
        assert 'og:image" content="' in h and "/static/og.png" in h and 'og:title' in h

    @pytest.mark.parametrize("page", ["/login", "/forgot"])
    def test_les_pages_de_compte_ne_sont_pas_indexees(self, client, db, page):
        assert 'name="robots" content="noindex' in _tete(client.get(page).text)


class TestPageMarche:
    def test_elle_existe_et_cache_l_acheteur(self, client, db):
        _marche(db)
        r = client.get("/appel-offres/1043943-achevement-des-travaux-de-la-rp5125")
        assert r.status_code == 200
        assert "Achèvement des travaux de la RP5125" in r.text
        assert "DIRECTION PROVINCIALE" not in r.text, "l'acheteur reste réservé aux membres"
        assert "350 000" not in r.text, "la caution aussi"
        assert "Caution provisoire" in r.text, "mais on dit qu'il y en a une"
        assert 'content="index,follow"' in _tete(r.text)

    def test_une_seule_adresse(self, client, db):
        _marche(db)
        r = client.get("/appel-offres/1043943-ancien-intitule", follow_redirects=False)
        assert r.status_code == 301
        assert r.headers["location"] == "/appel-offres/1043943-achevement-des-travaux-de-la-rp5125"

    def test_pas_de_page_pour_un_agregateur_prive(self, client, db):
        _marche(db, tid="gm_988395", source="global-marches")
        assert client.get("/appel-offres/988395-x").status_code == 404

    def test_cloture_reste_lisible_mais_sort_de_l_index(self, client, db):
        _marche(db, statut="expire", jours=-3)
        r = client.get("/appel-offres/1043943-achevement-des-travaux-de-la-rp5125")
        assert r.status_code == 200 and "noindex" in _tete(r.text)

    def test_un_lien_partage_mene_a_la_page_publique(self, client, db):
        _marche(db)
        r = client.get("/tenders/ao_1043943", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].startswith("/appel-offres/1043943-")


class TestVilles:
    def test_page_ville_et_alias(self, client, db):
        for i in range(3):
            _marche(db, tid=f"ao_10{i}", region="El Kelaa Des Sraghna", objet=f"Marché {i}")
        for i in range(3):
            _marche(db, tid=f"ao_20{i}", region="El kelaa sraghna", objet=f"Autre {i}")
        r = client.get("/marches-publics/ville/el-kelaa-des-sraghna")
        assert r.status_code == 200 and "6 marchés ouverts" in r.text

    def test_pas_de_page_mince(self, client, db):
        _marche(db, region="Tata")
        assert client.get("/marches-publics/ville/tata").status_code == 404

    def test_alias(self):
        from app.core.villes import ville
        assert ville("Agadir Ida Ou Tanane") == "Agadir"
        assert ville("Province d'Ifrane MAROC") == "Ifrane"
        assert ville("Oujda-Angad") == "Oujda"


class TestPlanDuSite:
    def test_contenu(self, client, db):
        _marche(db)
        _marche(db, tid="ao_2", statut="expire", jours=-2, objet="Clos")
        _marche(db, tid="gm_3", source="global-marches", objet="Prive")
        xml = client.get("/sitemap.xml").text
        assert "/appel-offres/1043943-" in xml
        assert "/appel-offres/2-" not in xml, "un marché clôturé sort du plan"
        assert "gm_3" not in xml and "/appel-offres/3-" not in xml
        assert "/login" not in xml

    def test_robots_ecarte_les_espaces_prives(self, client, db):
        txt = client.get("/robots.txt").text
        for chemin in ("/tenders", "/settings", "/invitation/", "/api/"):
            assert f"Disallow: {chemin}" in txt
        assert "Disallow: /appel-offres" not in txt and "Disallow: /marches-publics" not in txt
