# -*- coding: utf-8 -*-
"""Comment répondre à un marché de la source privée, et à qui s'adresser."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.core.conditions import cartes, conditions_avis, contact_detaille
from app.core.lecture import chiffres
from app.services import fiches_privees as F

# Mise en page réelle de la fiche (relevée le 25/10/2026), abrégée.
FICHE = """<html><body><table>
<tr><td>N d'ordre :</td><td>1556229</td></tr>
<tr><td>Référence :</td><td>04/2026</td></tr>
<tr><td>Date/Heure limite :</td><td>27/10/2026 14:00</td></tr>
<tr><td>Organisme :</td><td>Archives du Maroc</td></tr>
<tr><td>Objet :</td><td>L’Audit comptable et financier des Archives du Maroc</td></tr>
<tr><td>Ville d'exécution :</td><td>- Rabat</td></tr>
<tr><td>Adresse retrait :</td><td>Avenue Ibn Battouta, Agdal, Rabat</td></tr>
<tr><td>Contact :</td><td>LATIFA MOFTAQIR - Téléphone: 05 37 77 66 83 - Email: latifa.moftaqir@yahoo.fr - Télécopieur: 05 37 68 35 45</td></tr>
<tr><td>Montant retrait :</td><td></td><td>D.ouvr.Plis :</td><td>---</td></tr>
<tr><td>Mode paiement :</td><td></td><td>D.Dépot.D'ech :</td><td>---</td></tr>
<tr><td>Mt caution :</td><td>4.500,00 MAD</td><td>D.réunion</td><td>---</td></tr>
<tr><td>Budget :</td><td>240.000,00 MAD</td><td>Délais D'exécution :</td><td>3 mois</td></tr>
<tr><td>Visite des lieux :</td><td>20/10/2026 10:00</td></tr>
<tr><td><a href="/downoaldcps/1556229.zip">Télécharger D.A.O</a></td></tr>
<tr><td>Type :</td><td>Appel d'offre réservé au PME nationales</td></tr>
<tr><td>Obsérvation :</td><td>budget en ttc + report de la date limite</td></tr>
<tr><td>Soumission électronique :</td><td>Non</td></tr>
<tr><td>Cliquer ici</td></tr></table></body></html>"""


class TestLecture:
    def test_champs(self):
        f = F.lire_fiche(FICHE)
        assert f["limite"] == "27/10/2026 14:00" and f["caution"] == "4.500,00 MAD"
        assert f["retrait"].startswith("Avenue Ibn Battouta")
        assert f["delai"] == "3 mois" and f["electronique"] == "Non"
        assert f["dao_url"] == "https://global-marches.com/downoaldcps/1556229.zip"
        assert "ouverture" not in f, "« --- » veut dire vide"

    def test_pas_une_fiche(self):
        assert F.lire_fiche("<html>Erreur 404</html>") == {}

    def test_reecriture_lue_par_les_conditions(self):
        d = F.description("Archives du Maroc", "Audit comptable", F.lire_fiche(FICHE))
        c = conditions_avis(d)
        assert c["caution"] == "4.500,00 MAD", "la caution ne déborde pas sur la suite"
        assert c["delai_execution"] == "3 mois" and "report" in c["observation"]
        assert c["depot"].startswith("dépôt papier auprès de l'acheteur")
        contact = contact_detaille(c["contact"])
        assert contact == {"nom": "LATIFA MOFTAQIR", "email": "latifa.moftaqir@yahoo.fr",
                           "tel": "0537776683"}, "le fax n'est pas gardé"

    def test_cases_sans_affirmer_ce_qu_on_ignore(self):
        d = F.description("A", "B", F.lire_fiche(FICHE).copy() | {"caution": ""})
        cles = [k for k, *_ in cartes(conditions_avis(d), portail=False)]
        assert "cond_agrement" not in cles, "la source ne publie pas les agréments"
        assert ("cond_caution", "aucune") not in [(k, v) for k, v, *_ in cartes(conditions_avis(d), portail=False)]
        assert "cond_retrait" in cles and "cond_type_consultation" in cles

    def test_encadre(self):
        d = F.description("A", "B", F.lire_fiche(FICHE))
        c = chiffres({"id": "gm_1", "type_procedure": "marche", "montant": "240.000,00 MAD",
                      "date_limite": "27/10/2026", "description": d})
        assert c["limite"]["heure"] == "14:00" and c["caution"] == {"valeur": "4.500,00 MAD"}
        assert c["dossier"]["adresse"].startswith("Avenue Ibn Battouta")


class FausseSession:
    def __init__(self, html):
        self.html, self.vus, self.headers = html, [], {}

    def get(self, url, timeout=0):
        self.vus.append(url)
        return SimpleNamespace(status_code=200, text=self.html)


def _avis(db, tid="gm_1556229"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,scraped_at,url,source,
                  type_procedure,date_limite,description)
                  VALUES(?,?,?,'S902','actif','2026-10-20',?, 'global-marches','marche',?,'A B')""",
               (tid, "Audit comptable", "Archives du Maroc",
                "https://global-marches.com/share/abc==",
                (date.today() + timedelta(days=5)).strftime("%d/%m/%Y")))
    db.commit()


class TestEnrichissement:
    def test_une_fois_par_avis(self, db):
        _avis(db)
        s = FausseSession(FICHE)
        assert F.enrichir(session=s, pause=0) == 1
        r = db.execute("SELECT description, dao_url, fiche_lue FROM tenders").fetchone()
        assert "Contact Administratif" in r["description"] and r["dao_url"].endswith(".zip") and r["fiche_lue"]
        assert F.enrichir(session=s, pause=0) == 0 and len(s.vus) == 1

    def test_fiche_vide_marquee_sans_rien_ecrire(self, db):
        _avis(db)
        F.enrichir(session=FausseSession("<html>rien</html>"), pause=0)
        r = db.execute("SELECT description, fiche_lue FROM tenders").fetchone()
        assert r["description"] == "A B" and r["fiche_lue"]


class TestFiche:
    def _membre(self, db):
        db.execute("""INSERT INTO members(id,nom,email,phone,company,plan,subscription_status,trial_ends,
                      pw_hash,session_token,actif,secteurs,email_verified)
                      VALUES(1,'Ahmed Alaoui','f@x.ma','0612345678','SIMAC','pro','ACTIVE',?,'x',
                      'jeton-fiche-1',1,'["S902"]',1)""", ((date.today() + timedelta(days=90)).isoformat(),))
        db.commit()

    def test_contact_et_dao_sur_la_fiche(self, client, db, monkeypatch):
        self._membre(db); _avis(db)
        F.enrichir(session=FausseSession(FICHE), pause=0)
        client.cookies.set("_session", "jeton-fiche-1")
        page = client.get("/tenders/gm_1556229").text
        assert "latifa.moftaqir@yahoo.fr" in page and "0537776683" in page
        assert "Avenue Ibn Battouta" in page and "/tenders/gm_1556229/dao" in page
        from app.services import pieces
        monkeypatch.setattr(pieces, "recuperer", lambda url: (b"PK\x03\x04zip", "application/zip", "zip"))
        r = client.get("/tenders/gm_1556229/dao")
        assert r.status_code == 200 and r.content.startswith(b"PK")


class TestPlateforme:
    def test_portail_seulement_s_il_est_nomme(self):
        f = F.lire_fiche(FICHE.replace("<td>Non</td>", "<td>Oui</td>"))
        d = F.description("A", "B", f)
        assert "plateforme indiquée dans l'avis" in d and "dépôt électronique sur www.marchespublics" not in d
        f["observation"] = "dépôt obligatoire dans le portail des marchés publics"
        assert "dépôt électronique sur www.marchespublics.gov.ma" in F.description("A", "B", f)

    def test_une_ancienne_lecture_est_refaite_une_fois(self, db):
        _avis(db)
        db.execute("UPDATE tenders SET fiche_lue='2026-10-25T01:00:00'"); db.commit()
        s = FausseSession(FICHE)
        assert F.enrichir(session=s, pause=0) == 1
        assert db.execute("SELECT fiche_lue FROM tenders").fetchone()[0].startswith("v2:")
        assert F.enrichir(session=s, pause=0) == 0
