"""« Pouvez-vous répondre ? » en tête de fiche (app/services/synthese.py)."""
from datetime import date, datetime, timedelta

from app.services import synthese


def _ech(*paires):
    auj = date.today()
    return [{"cle": c, "jour": auj + timedelta(days=n), "reste": n} for c, n in paires]


PIECES_OK = [{"code": c, "etat": "ok"} for c in ("fiscale", "cnss", "rc")]


class TestVerdict:
    def test_tout_est_pret(self):
        s = synthese.pour_marche({"etat": "libre", "lignes": []}, PIECES_OK, _ech(("depot", 20)), "aucune")
        assert s["verdict"] == "go" and s["a_regler"] == 0

    def test_une_piece_manque(self):
        pieces = PIECES_OK[:2] + [{"code": "rc", "etat": "manquante"}]
        s = synthese.pour_marche({"etat": "libre", "lignes": []}, pieces, _ech(("depot", 20)))
        assert s["verdict"] == "a_regler" and s["a_regler"] == 1
        dossier = next(p for p in s["points"] if p["cle"] == "dossier")
        assert dossier["args"] == {"n": 2, "total": 3, "reste": 1} and dossier["lien"] == "/coffre"

    def test_qualification_insuffisante_bloque(self):
        elig = {"etat": "non_eligible", "lignes": [{"code": "B.1", "classe": "2", "ok": False}]}
        s = synthese.pour_marche(elig, PIECES_OK, _ech(("depot", 20)))
        assert s["verdict"] == "non"
        q = next(p for p in s["points"] if p["cle"] == "qualif")
        assert q["lien"] == "/groupements" and "B.1" in q["args"]["exigee"]

    def test_date_limite_passee_bloque(self):
        s = synthese.pour_marche({"etat": "libre", "lignes": []}, PIECES_OK, _ech(("depot", -1)))
        assert s["verdict"] == "clos" and s["dates"] == []

    def test_qualification_non_declaree_a_regler(self):
        elig = {"etat": "inconnu", "lignes": [{"code": "A.2", "classe": "4", "ok": None}]}
        s = synthese.pour_marche(elig, PIECES_OK, _ech(("depot", 20)))
        assert s["verdict"] == "a_regler"


class TestCautionEtDelai:
    def test_caution_a_demander_avant_une_date(self):
        s = synthese.pour_marche({"etat": "libre"}, PIECES_OK,
                                 _ech(("caution", 7), ("depot", 14)), "67 000,00 MAD")
        c = next(p for p in s["points"] if p["cle"] == "caution")
        assert c["etat"] == "info" and c["args"]["montant"] == "67 000,00 MAD"
        assert [d["cle"] for d in s["dates"]] == ["caution", "depot"]

    def test_caution_en_retard_devient_urgente(self):
        s = synthese.pour_marche({"etat": "libre"}, PIECES_OK,
                                 _ech(("caution", -2), ("depot", 5)), "10 000 MAD")
        assert next(p for p in s["points"] if p["cle"] == "caution")["etat"] == "attention"

    def test_delai_serre(self):
        s = synthese.pour_marche({"etat": "libre"}, PIECES_OK, _ech(("depot", 2)))
        assert next(p for p in s["points"] if p["cle"] == "delai")["etat"] == "attention"

    def test_classe_en_arabe(self):
        elig = {"etat": "eligible", "lignes": [{"code": "B.1", "classe": "4", "ok": True}]}
        s = synthese.pour_marche(elig, PIECES_OK, _ech(("depot", 20)), lang="ar")
        assert next(p for p in s["points"] if p["cle"] == "qualif")["args"]["exigee"] == "B.1 الصنف 4"


class TestFiche:
    def test_la_fiche_affiche_la_synthese(self, client, db):
        limite = (date.today() + timedelta(days=12)).strftime("%d/%m/%Y")
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,source,date_limite,description,scraped_at)
                      VALUES('ao_999001','Travaux de piste','T101','actif','marchespublics',?,?,?)""",
                   (limite, f"Date limite : {limite} Caution provisoire : 20 000,00 MAD",
                    datetime.now().isoformat()))
        fin = (datetime.now() + timedelta(days=2)).isoformat(timespec="seconds")
        db.execute("""INSERT INTO members(nom,email,plan,subscription_status,session_token,email_verified,
                         actif,secteurs,created_at,trial_ends)
                      VALUES('Karim','syn@example.com','free','TRIAL','jeton-synthese-0001',1,1,'["T101"]',?,?)""",
                   (datetime.now().isoformat(), fin))
        db.commit()
        client.cookies.set("_session", "jeton-synthese-0001")
        page = client.get("/tenders/ao_999001").text
        assert "Pouvez-vous répondre ?" in page
        assert "Caution provisoire" in page and "Vos prochaines dates" in page


class TestCarte:
    def test_sans_qualification_exigee(self):
        c = synthese.pour_carte([], {"id": "ao_1", "description": "Caution provisoire : 0,00 MAD Qualifications : - Agréments : -"})
        assert c["etat"] == "libre" and c["caution"] == "aucune"

    def test_caution_arrondie(self):
        c = synthese.pour_carte([], {"id": "ao_1", "description": "Caution provisoire : 67 000,00 MAD Qualifications : -"})
        assert c["caution"] == "67 000 MAD"

    def test_hors_portail_on_ne_conclut_pas_a_aucune(self):
        c = synthese.pour_carte([], {"id": "gm_1", "description": ""})
        assert c["caution"] == "" and c["etat"] == "libre"


    def test_agrement_en_toutes_lettres_raccourci(self, monkeypatch):
        from app.services import eligibilite
        monkeypatch.setattr(eligibilite, "exigences", lambda d: [
            {"code": "CONTROLE DES TRAVAUX DE TERRASSEMENT ET VOIRIE", "libelle": "", "classe": "3"}])
        c = synthese.pour_carte([{"code": "B.1", "classe": "3"}], {"id": "ao_1", "description": "x"})
        assert len(c["exigee"]) < 40 and c["exigee"].startswith("CONTROLE DES")


class TestListe:
    def test_chaque_ligne_dit_si_lon_peut_repondre(self, client, db):
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,source,date_limite,description,scraped_at,type_procedure)
                      VALUES('ao_999002','Travaux de piste','T101','actif','marchespublics','20/12/2026',
                             'Caution provisoire : 15 000,00 MAD Qualifications : -',?,'marche')""", (datetime.now().isoformat(),))
        fin = (datetime.now() + timedelta(days=2)).isoformat(timespec="seconds")
        db.execute("""INSERT INTO members(nom,email,plan,subscription_status,session_token,email_verified,
                         actif,secteurs,created_at,trial_ends)
                      VALUES('Karim','liste@example.com','free','TRIAL','jeton-liste-0001',1,1,'["T101"]',?,?)""",
                   (datetime.now().isoformat(), fin))
        db.commit()
        client.cookies.set("_session", "jeton-liste-0001")
        page = client.get("/tenders").text
        assert "Vous pouvez répondre" in page and "15 000 MAD" in page
        assert "Correspond à votre profil" not in page
