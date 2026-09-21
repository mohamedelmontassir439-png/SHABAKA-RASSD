"""Collecte des appels d'offres du portail national.

Jusqu'ici la plateforme ne ramenait que des bons de commande: 400 « marchés »
contre 16 432 bons de commande. Ces tests figent la lecture des pages du
portail — fragments réels, aucun appel réseau.
"""
from bs4 import BeautifulSoup as BS

from app.services import ao_scraper as ao

LIGNE = """<table><tr class="on">
  <td class="check-col"></td>
  <td class="col-90">AOO ... Appel d'offres ouvert Travaux 24/08/2026
      Comporte des dispositions envrionnementales</td>
  <td class="col-450">074/2026/AS - ... Objet : Travaux d’assainissement liquide du
      POLE URBAIN KSAR SGHIR. Lot : STATION D’EPURATION
      Acheteur public : SOCIETE REGIONALE MULTISERVICES TANGER-TETOUAN</td>
  <td class="col-90">- FAHS-ANJRA ... MAROC, FAHS-ANJRA ...</td>
  <td class="col-60">11/11/2026 10:00 ...</td>
  <td class="actions"></td>
  <td class="actions">: 0 : 0</td>
  <td><a href="https://www.marchespublics.gov.ma/?page=entreprise.EntrepriseDetailsConsultation&amp;refConsultation=1034700&amp;orgAcronyme=w7t">Détails</a></td>
</tr></table>"""

FICHE = """<html><body>
<div>Marchés publics électroniques Aller au menu Aller au contenu Mon panier
     Consultations Toutes les consultations Recherche avancée</div>
<div>Référence 11/2026/DRANEFFM Objet : Acquisition d’un véhicule vivier
     Acheteur public : ANEF / DRANEFFM
     Procédure : Appel d'offres ouvert | Sur offre de prix
     Catégorie principale : Fournitures Allotissement : -
     Lieu d'exécution : IFRANE IFRANE
     Estimation (en Dhs TTC) * : 470 400,00
     Réservé à la TPE et PME installées au Maroc</div>
</body></html>"""


def _ligne(html=LIGNE):
    return ao.parse_ligne(BS(html, "html.parser").find("tr"))


class TestLigneDeResultats:
    def test_champs_principaux(self):
        f = _ligne()
        assert f["ref"] == "1034700" and f["org"] == "w7t"
        assert f["objet"].startswith("Travaux d’assainissement liquide")
        assert "Acheteur public" not in f["objet"], "l'acheteur n'est pas dans l'objet"
        assert f["acheteur"] == "SOCIETE REGIONALE MULTISERVICES TANGER-TETOUAN"
        assert f["date_limite"] == "11/11/2026"
        assert f["categorie"] == "Travaux"

    def test_lieu_non_duplique(self):
        assert _ligne()["region"] == "Fahs-Anjra"

    def test_ligne_sans_lien_ignoree(self):
        html = LIGNE.replace("refConsultation=1034700", "autre=1")
        assert _ligne(html) == {}


class TestNormalisationDuLieu:
    def test_variantes(self):
        assert ao._lieu("- FAHS-ANJRA ... MAROC, FAHS-ANJRA ...") == "Fahs-Anjra"
        assert ao._lieu("MAROC, TETOUAN ...") == "Tetouan"
        assert ao._lieu("Rabat") == "Rabat"
        assert ao._lieu("") == ""

    def test_pays_seul_retombe_sur_la_ville(self):
        assert ao._lieu("CASABLANCA ... MAROC ...") == "Casablanca"


class TestFicheDetaillee:
    def test_estimation_lue(self):
        assert ao.parse_fiche(FICHE)["montant"] == "470 400,00 MAD"

    def test_estimation_nulle_ignoree(self):
        # « 0,00 » veut dire « non communiquée »: un budget nul découragerait
        # une entreprise pour rien.
        html = FICHE.replace("470 400,00", "0,00")
        assert ao.parse_fiche(html)["montant"] == ""

    def test_reservation_pme_detectee(self):
        assert ao.parse_fiche(FICHE)["reserve_pme"] is True
        assert ao.parse_fiche(FICHE.replace("Réservé à la TPE et PME", ""))["reserve_pme"] is False

    def test_description_sans_les_menus(self):
        desc = ao.parse_fiche(FICHE)["description"]
        assert "Aller au menu" not in desc and "Mon panier" not in desc
        assert desc.startswith("Référence")


class TestCollecte:
    def _session_factice(self, monkeypatch, fiche=FICHE):
        """Rejoue une page de résultats et une fiche, sans réseau."""
        class Rep:
            def __init__(self, texte): self.text, self.status_code = texte, 200
            def raise_for_status(self): pass

        class Session:
            def get(self, url, **kw):
                return Rep(fiche if "DetailsConsultation" in url else LIGNE)
            def post(self, url, **kw):
                return Rep(LIGNE)

        monkeypatch.setattr(ao, "make_session", lambda: Session())
        monkeypatch.setattr(ao.time, "sleep", lambda s: None)

    def test_marche_complet(self, monkeypatch):
        self._session_factice(monkeypatch)
        res = ao.run(set(), log_fn=lambda m: None, pages=1)
        assert len(res) == 1
        t = res[0]
        assert t["id"] == "ao_1034700"
        assert t["type_procedure"] == "marche", "un appel d'offres n'est pas un bon de commande"
        assert t["type_offre"] == "Public"
        assert t["montant"] == "470 400,00 MAD"
        assert t["region"] == "Fahs-Anjra"
        assert t["secteur"] == "T201", "assainissement, pas menuiserie"
        assert "refConsultation=1034700" in t["url"]

    def test_marche_deja_connu_ignore(self, monkeypatch):
        self._session_factice(monkeypatch)
        assert ao.run({"ao_1034700"}, log_fn=lambda m: None, pages=1) == []

    def test_fiche_indisponible_n_annule_pas_le_marche(self, monkeypatch):
        self._session_factice(monkeypatch, fiche="<html><body>erreur</body></html>")
        res = ao.run(set(), log_fn=lambda m: None, pages=1)
        assert len(res) == 1 and res[0]["montant"] == ""

    def test_portail_injoignable_ne_casse_pas_la_veille(self, monkeypatch):
        class Session:
            def get(self, *a, **kw): raise OSError("connexion refusée")
        monkeypatch.setattr(ao, "make_session", lambda: Session())
        assert ao.run(set(), log_fn=lambda m: None, pages=1) == []
