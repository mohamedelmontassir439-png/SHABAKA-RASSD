# -*- coding: utf-8 -*-
"""Les marchés auxquels l'entreprise peut répondre, selon ses qualifications."""
from datetime import date, timedelta

from app.services import eligibilite as E

AVIS = ("Référence 1/2026 Objet : x Qualifications : Equipement / B- Travaux routiers / "
        "B.1- Travaux de terrassements routiers courants / Classe 3 Equipement / B- Travaux "
        "routiers / B.3- Ouvrages d'assainissement routiers / Classe 2 Agréments : Variante : Non")


def _membre(db):
    db.execute("""INSERT INTO members(id,nom,email,phone,company,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(1,'Ahmed Alaoui','e@x.ma','0612345678','SIMAC','pro','ACTIVE',?,'x',
                  'jeton-elig-1',1,'["T101"]',1)""", ((date.today() + timedelta(days=90)).isoformat(),))
    db.commit()


def _marche(db, tid, description):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,statut,scraped_at,date_limite,
                  type_offre,type_procedure,source,description)
                  VALUES(?,?,'DP','T101','Rabat','actif','2026-10-01',?,'Public','marche',
                  'marchespublics',?)""",
               (tid, f"Marché {tid}", (date.today() + timedelta(days=20)).strftime("%d/%m/%Y"), description))
    db.commit()


class TestRegles:
    def test_ordre_des_classes(self):
        assert E.rang("S") < E.rang("1") < E.rang("2") < E.rang("6")

    def test_exigences(self):
        assert [(e["code"], e["classe"]) for e in E.exigences(AVIS)] == [("B.1", "3"), ("B.3", "2")]

    def test_une_classe_superieure_suffit(self):
        v = E.verdict([{"code": "B.1", "classe": "1"}, {"code": "B.3", "classe": "2"}], E.exigences(AVIS))
        assert v["etat"] == "eligible"

    def test_une_classe_inferieure_ne_suffit_pas(self):
        v = E.verdict([{"code": "B.1", "classe": "1"}, {"code": "B.3", "classe": "4"}], E.exigences(AVIS))
        assert v["etat"] == "non_eligible" and [l["ok"] for l in v["lignes"]] == [True, False]

    def test_sans_qualification_declaree_on_ne_juge_pas(self):
        assert E.verdict([], E.exigences(AVIS))["etat"] == "inconnu"

    def test_sans_exigence_tout_le_monde_peut(self):
        assert E.verdict([{"code": "A.2", "classe": "5"}], [])["etat"] == "libre"

    def test_code_invalide_refuse(self, db):
        _membre(db)
        assert E.ajouter(1, "n'importe", "2") is False
        assert E.ajouter(1, "b.1", "7") is False
        assert E.ajouter(1, "b.1", "2") is True
        assert E.mes_qualifications(1)[0]["code"] == "B.1"


class TestListe:
    def test_filtre(self, client, db):
        _membre(db)
        _marche(db, "ao_1", AVIS)
        _marche(db, "ao_2", "Référence 2/2026 Objet : y Qualifications : Agréments : Variante : Non")
        E.ajouter(1, "B.1", "3"); E.ajouter(1, "B.3", "4")
        client.cookies.set("_session", "jeton-elig-1")
        tout = client.get("/tenders").text
        assert "Marché ao_1" in tout and "Marché ao_2" in tout
        filtre = client.get("/tenders?elig=1").text
        assert "Marché ao_2" in filtre and "Marché ao_1" not in filtre

    def test_fiche_et_coffre(self, client, db):
        _membre(db); _marche(db, "ao_1", AVIS)
        client.cookies.set("_session", "jeton-elig-1")
        assert "Déclarer la mienne" in client.get("/tenders/ao_1").text
        client.get("/coffre")
        client.post("/qualifications", data={"code": "B.1", "classe": "2", "csrf_token": client.cookies.get("_csrf")})
        assert "B.1" in client.get("/coffre").text
        assert "Oui — votre classe 2" in client.get("/tenders/ao_1").text
