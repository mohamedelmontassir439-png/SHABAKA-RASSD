# -*- coding: utf-8 -*-
"""Les annuaires professionnels, et ce qu'on refuse d'en tirer.

Global Marché publie qui a gagné un marché, jamais comment le joindre. Deux
annuaires publics comblent une partie du trou. Mesures du 04/10/2026 sur nos
propres noms:

    289 entreprises sans aucun contact
    → 97 retrouvées chez Télécontact, 191 chez Charika, 214 en tout (74 %)
    → Télécontact rend un téléphone dans 2 fiches sur 3; Charika, surtout des
      emails et le nom du dirigeant.

Ce que ces tests tiennent, ce sont les erreurs qui coûtent un appel:

- une page de Télécontact porte un bloc d'autres annonceurs, avec leurs
  adresses en microdonnées. Les lire donnait à une entreprise d'Aït Ourir
  une adresse à Casablanca.
- Charika publie plusieurs adresses pour la même société: les additionner
  annonçait 390 reconnaissances pour 289 entreprises cherchées.
- son formulaire de contact porte un gabarit `utilisateur@exemple.com`. Pris
  pour un email d'entreprise, il remplissait quatorze fiches sur quatorze.
- un numéro affiché en bloc de douze chiffres se recopie de travers.
"""
import re

import pytest

from app.services import annuaires
from app.services.companies import telephone_lisible


class TestExtractionTelecontact:
    PAGE = '''<html><head><title>Tabarak Travaux - Electricité générale à Aït Ourir
              | Telecontact.ma</title></head><body>
              <a href="tel:05 24 48 00 67">appeler</a>
              <div class="autres-annonceurs">
                <p itemprop="streetAddress">611 bd Aba Chouaïb Doukali - Casablanca</p>
                <span itemprop="addressLocality">Casablanca - Maroc</span>
              </div></body></html>'''

    def test_le_telephone_est_pris_au_lien_dappel(self):
        assert annuaires._fiche_telecontact(self.PAGE)["phone"] == "212524480067"

    def test_ladresse_des_annonces_voisines_nest_pas_prise(self):
        """Elle est en microdonnées, comme la vraie: seule la place diffère.
        Une adresse fausse est pire qu'une adresse absente."""
        f = annuaires._fiche_telecontact(self.PAGE)
        assert f["address"] == "" and f["city"] == ""
        assert "Casablanca" not in str(f.values())

    def test_lactivite_vient_du_titre_de_la_page(self):
        assert annuaires._fiche_telecontact(self.PAGE)["activite"] == "Electricité générale"

    def test_une_page_sans_numero_ne_rend_rien(self):
        assert annuaires._fiche_telecontact("<html><title>x</title></html>")["phone"] == ""


class TestExtractionCharika:
    PAGE = '''<html><body>
        <span class="marketingInfoTelFax">0522963000</span>
        <span class="marketingInfoTelFax">0522964080</span>
        <a href="mailto:france-agencement@prima.sa.com">écrire</a>
        <li><span><b class="text-color">M. Pierre RAGULSKY : </b></span>
            <span> directeur général</span></li>
        <a href="mailto:contact@charika.ma">le site</a>
        <input placeholder="utilisateur@exemple.com">
        <a href="mailto:utilisateur@exemple.com">gabarit</a>
        </body></html>'''

    def test_le_telephone_et_le_fax_sont_distingues(self):
        f = annuaires._fiche_charika(self.PAGE)
        assert f["phone"] == "212522963000" and f["mobile"] == "212522964080"

    def test_lemail_de_lentreprise_est_pris(self):
        assert annuaires._fiche_charika(self.PAGE)["email"] == "france-agencement@prima.sa.com"

    @pytest.mark.parametrize("gabarit", ["utilisateur@exemple.com", "contact@charika.ma"])
    def test_ni_le_gabarit_ni_ladresse_du_site_ne_passent(self, gabarit):
        """Le gabarit du formulaire remplissait toutes les fiches d'un coup."""
        assert annuaires._fiche_charika(self.PAGE)["email"] != gabarit

    def test_le_dirigeant_est_lu_avec_sa_fonction(self):
        """C'est lui qui change la première phrase d'un appel."""
        m = annuaires._fiche_charika(self.PAGE)["manager"]
        assert "Pierre RAGULSKY" in m and "directeur général" in m


class TestCleDeRapprochement:
    @pytest.mark.parametrize("url,attendu", [
        ("https://www.charika.ma/societe-france-agencement--150436", "france agencement"),
        ("https://www.charika.ma/societe-jet-robuste-222583", "jet robuste"),
    ])
    def test_lidentifiant_final_nest_pas_le_nom(self, url, attendu):
        """Sans le retirer, aucune clé ne correspondait: 0 appariement sur 612."""
        assert annuaires._cle_du_slug(annuaires.ANNUAIRES["charika"], url) == attendu

    def test_telecontact_lit_le_nom_dans_le_chemin(self):
        url = "https://www.telecontact.ma/annonceur/tabarak-travaux/3307630/ait-ourir.php"
        assert annuaires._cle_du_slug(annuaires.ANNUAIRES["telecontact"], url) == "tabarak travaux"

    def test_une_adresse_qui_nest_pas_une_fiche_ne_donne_pas_de_cle(self):
        for url in ("https://www.telecontact.ma/trouver/carte.php?x=1",
                    "https://www.charika.ma/blog/article"):
            for a in annuaires.ANNUAIRES.values():
                cle = annuaires._cle_du_slug(a, url)
                assert "trouver" not in cle and "blog" not in cle


class TestNumeroLisible:
    @pytest.mark.parametrize("brut,lu", [
        ("212524480067", "05 24 48 00 67"),
        ("0608110110", "06 08 11 01 10"),
        ("+212 661 08 80 52", "06 61 08 80 52"),
    ])
    def test_un_numero_saffiche_comme_on_le_compose(self, brut, lu):
        assert telephone_lisible(brut) == lu

    @pytest.mark.parametrize("brut", ["", "non renseigné", "12"])
    def test_ce_qui_nest_pas_un_numero_est_rendu_tel_quel(self, brut):
        """Inventer un format sur une valeur douteuse la ferait passer pour sûre."""
        assert telephone_lisible(brut) == brut


class TestPage:
    def test_la_page_annonce_ce_qui_reste_injoignable(self, client, admin):
        page = admin.get("/admin/annuaires")
        assert page.status_code == 200
        assert "Sans aucun contact" in page.text
        for a in annuaires.ANNUAIRES.values():
            assert a.libelle in page.text

    def test_les_deux_etapes_sont_distinctes(self, admin):
        """Reconnaître traverse des sitemaps; lire ouvre des fiches une à une.
        Les confondre ferait ouvrir deux millions de pages."""
        page = admin.get("/admin/annuaires").text
        assert 'name="etape" value="apparier"' in page
        assert 'name="etape" value="enrichir"' in page

    def test_un_annuaire_inconnu_est_refuse(self, admin):
        r = admin.post("/admin/annuaires/lancer",
                       data={"source": "ailleurs", "etape": "apparier",
                             "csrf_token": "x"}, follow_redirects=False)
        assert r.status_code in (302, 303, 400, 403)

    def test_letat_nest_pas_public(self, client):
        assert client.get("/admin/annuaires/etat").status_code in (401, 302, 307)


class TestCourtoisie:
    def test_lagent_se_nomme_et_laisse_une_adresse(self):
        """Le site doit pouvoir nous reconnaître et nous écrire."""
        assert "marocentrepreneuriat.com" in annuaires._AGENT

    def test_un_delai_separe_deux_fiches(self):
        assert annuaires._DELAI >= 1.0

    def test_une_execution_ne_lit_pas_tout_lannuaire(self):
        assert 0 < annuaires._PLAFOND_FICHES <= 1000

    def test_les_sitemaps_sont_lus_dans_lindex_du_site(self):
        """Une liste écrite en dur cesserait de voir les entreprises ajoutées."""
        source = open(annuaires.__file__, encoding="utf-8").read()
        assert "_sous_sitemaps" in source
        for a in annuaires.ANNUAIRES.values():
            assert re.search(r"sitemap", a.index)
