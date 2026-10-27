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
<div>Date et heure limite de remise des plis : 11/11/2026 10:00</div>
<div>Référence 11/2026/DRANEFFM Objet : Acquisition d’un véhicule vivier
     Acheteur public : ANEF / DRANEFFM
     Procédure : Appel d'offres ouvert | Sur offre de prix
     Catégorie principale : Fournitures Allotissement : -
     Lieu d'exécution : IFRANE IFRANE
     Estimation (en Dhs TTC) * : 470 400,00
     Réservé à la TPE et PME installées au Maroc, jeunes entreprises innovantes,
     Coopératives et auto-entrepreneurs * : Oui</div>
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
        # L'étiquette est sur toutes les fiches: seule sa valeur compte.
        assert ao.parse_fiche(FICHE.replace("* : Oui", "* : Non"))["reserve_pme"] is False

    def test_description_sans_les_menus(self):
        desc = ao.parse_fiche(FICHE)["description"]
        assert "Aller au menu" not in desc and "Mon panier" not in desc
        assert "Référence 11/2026/DRANEFFM" in desc

    def test_heure_limite_gardee(self):
        """Elle précède « Référence » sur la page: la coupe la perdait."""
        from app.core.conditions import conditions_avis
        desc = ao.parse_fiche(FICHE)["description"]
        assert desc.startswith("Date et heure limite de remise des plis : 11/11/2026 10:00")
        assert conditions_avis(desc)["limite"] == "11/11/2026 10:00"


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
        # L'erreur remonte pour être notée FAILED; do_scrape l'attrape source
        # par source, si bien que les autres collectes continuent.
        import pytest
        with pytest.raises(ConnectionError):
            ao.run(set(), log_fn=lambda m: None, pages=1)


class TestPortailInjoignable:
    """Le 27/10/2026 la collecte a tourné des heures sans joindre le portail,
    notée SUCCESS à zéro: l'échec doit se voir."""

    def test_la_liste_illisible_est_une_erreur(self, monkeypatch):
        import pytest
        from app.services import ao_scraper
        def panne(*a, **k):
            raise TimeoutError("connect timeout")
        monkeypatch.setattr(ao_scraper, "_lister_cartes", panne)
        monkeypatch.setattr(ao_scraper, "_lister", panne)
        with pytest.raises(ConnectionError):
            ao_scraper.run(set(), lambda *_: None)

    def test_toutes_les_fiches_en_echec_est_une_erreur(self, monkeypatch):
        import pytest
        from app.services import scraper
        monkeypatch.setattr(scraper, "find_max_id", lambda s, log: 400000)
        monkeypatch.setattr(scraper, "_fetch_one", lambda s, tid: (None, "connect timeout"))
        with pytest.raises(ConnectionError, match="portail injoignable"):
            scraper.run(set(), lambda *_: None)

    def test_quelques_echecs_ne_font_pas_une_panne(self, monkeypatch):
        from app.services import scraper
        monkeypatch.setattr(scraper, "find_max_id", lambda s, log: 400000)
        monkeypatch.setattr(scraper, "_fetch_one",
                            lambda s, tid: (None, "timeout") if tid.endswith("7") else (None, None))
        assert scraper.run(set(), lambda *_: None) == []


class TestRattrapage:
    """Après une coupure, la collecte reprend où elle s'était arrêtée."""

    def _plage(self, monkeypatch, connus, max_portail):
        from app.services import scraper
        vus = []
        monkeypatch.setattr(scraper, "find_max_id", lambda s, log: max_portail)
        monkeypatch.setattr(scraper, "_fetch_one", lambda s, tid: (vus.append(int(tid)), (None, None))[1])
        scraper.run({f"bdc_{i}" for i in connus}, lambda *_: None)
        return min(vus), max(vus)

    def test_les_avis_publies_pendant_la_coupure_sont_repris(self, monkeypatch):
        bas, haut = self._plage(monkeypatch, [398574], 399500)
        assert bas <= 398575 and haut >= 399500

    def test_le_rattrapage_est_borne(self, monkeypatch):
        from app.services import scraper
        bas, haut = self._plage(monkeypatch, [380000], 399500)
        assert bas == 399500 - scraper.RATTRAPAGE_MAX

    def test_portail_muet_arret_immediat(self, monkeypatch):
        import pytest, requests
        from app.services import scraper
        class S:
            def get(self, *a, **k): raise requests.exceptions.ConnectTimeout("timed out")
        appels = []
        monkeypatch.setattr(scraper, "_fetch_one", lambda s, tid: appels.append(tid))
        with pytest.raises(ConnectionError):
            scraper.find_max_id(S(), lambda *_: None)


class TestCartes:
    """La présentation en cartes du portail rouvert le 26/10/2026."""

    def _carte(self):
        import os
        from bs4 import BeautifulSoup
        chemin = os.path.join(os.path.dirname(__file__), "fixtures_carte_ao.html")
        soup = BeautifulSoup(open(chemin, encoding="utf-8").read(), "html.parser")
        return soup.find("div", class_="contentColumn")

    def test_une_carte_donne_tous_les_champs(self):
        from app.services import ao_scraper as ao
        f = ao.parse_carte(self._carte())
        assert f["ref"] == "1043336" and f["org"] == "g8e"
        assert f["reference"] == "239/2026"
        assert f["objet"].startswith("CONSTRUCTION DE LA ROUTE RELIANT CENTRE ZAOUIAT AHANSAL")
        assert f["acheteur"].startswith("AGENCE REGIONALE D'EXECUTION DES PROJETS")
        assert f["date_limite"] == "29/12/2026"
        assert f["region"].lower() == "azilal"
        assert f["procedure"] == "Appel d'offres ouvert"

    def test_les_dates_en_lettres(self):
        from app.services import ao_scraper as ao
        assert ao._date_carte("Mar 29 Dec 2026 10:30") == "29/12/2026"
        assert ao._date_carte("Jeu 05 févr. 2027") == "05/02/2027"
        assert ao._date_carte("rien") == ""

    def test_livraison_par_lots(self, monkeypatch):
        from app.services import ao_scraper as ao
        lignes = [{"ref": str(i), "org": "x", "objet": f"Objet {i}", "acheteur": "A", "region": "",
                   "date_publication": "", "date_limite": "", "categorie": ""} for i in range(120)]
        monkeypatch.setattr(ao, "_lister_cartes", lambda *a, **k: lignes)
        monkeypatch.setattr(ao, "DELAI", 0)
        class S:
            def get(self, *a, **k): raise OSError("hors ligne")
        monkeypatch.setattr(ao, "make_session", lambda: S())
        lots = []
        reste = ao.run(set(), lambda *_: None, par_lot=lambda l: lots.append(len(l)))
        assert lots == [50, 50] and len(reste) == 20


class TestPagination:
    def test_un_doublon_n_arrete_pas_la_lecture(self, monkeypatch):
        from app.services import ao_scraper as ao
        from bs4 import BeautifulSoup
        def page(debut):
            refs = list(range(debut, debut + 500))
            refs[-1] = refs[0]          # un doublon dans une page pleine
            html = "".join(f'<div class="contentColumn" onclick="x?refConsultation={r}&orgAcronyme=a"></div>' for r in refs)
            return BeautifulSoup(html, "html.parser")
        pages = [page(1000), page(2000), BeautifulSoup('<div class="contentColumn" onclick="refConsultation=9&orgAcronyme=a"></div>', "html.parser")]
        class S:
            def get(self, *a, **k):
                class R:
                    text = "<html></html>"
                    def raise_for_status(self): pass
                return R()
        appels = iter([pages[0], pages[0], pages[1], pages[2]])
        monkeypatch.setattr(ao, "_postback", lambda *a, **k: next(appels))
        monkeypatch.setattr(ao, "DELAI", 0)
        monkeypatch.setattr(ao, "parse_carte", lambda c: {"ref": ao._reference_et_organisme(c.get("onclick"))[0]})
        lignes = ao._lister_cartes(S(), 3, lambda *_: None)
        assert len(lignes) == 499 + 499 + 1
