"""Dossier de candidature: fiche entreprise, bordereau, pièces aux modèles officiels."""
from datetime import datetime, timedelta

import pytest

from app.services import candidature as cand


class TestLettres:
    @pytest.mark.parametrize("v, attendu", [
        (21, "vingt et un dirhams"), (71, "soixante et onze dirhams"), (80, "quatre-vingts dirhams"),
        (81, "quatre-vingt-un dirhams"), (200, "deux cents dirhams"), (201, "deux cent un dirhams"),
        (80000, "quatre-vingt mille dirhams"), (1000000, "un million de dirhams"),
        (234567.4, "deux cent trente-quatre mille cinq cent soixante-sept dirhams et quarante centimes"),
        (3397250.4, "trois millions trois cent quatre-vingt-dix-sept mille deux cent cinquante dirhams et quarante centimes"),
    ])
    def test_montants(self, v, attendu):
        assert cand.en_lettres(v) == attendu

    def test_nombres_saisis(self):
        assert cand.nombre("1 234,56") == 1234.56 and cand.nombre("1.234,5") == 1234.5
        assert cand.nombre("") == 0


class TestCalculs:
    def test_totaux(self):
        t = cand.totaux([{"quantite": 10, "pu": 150.5}, {"quantite": 2.5, "pu": 1000}], 20)
        assert t["ht"] == 4005.0 and t["montant_tva"] == 801.0 and t["ttc"] == 4806.0 and t["complet"]

    def test_incomplet_sans_prix(self):
        assert not cand.totaux([{"quantite": 10, "pu": 0}], 20)["complet"]

    def test_controle_rib_et_ice(self):
        assert cand.erreurs_profil({"rib": "230 270 41939802110071 00 02", "ice": "123"}) == ["ice"]
        assert cand.erreurs_profil({"rib": "123", "ice": "001234567000089"}) == ["rib"]


AVIS = ("Référence 04/2026 Objet : Travaux de piste Procédure : Appel d'offres ouvert | Sur offre de prix "
        "Caution provisoire : 20 000,00 MAD Qualifications : -")
PROFIL = {"statut": "societe", "raison_sociale": "ATLAS PISTES SARL", "forme_juridique": "SARL",
          "capital": "100 000", "signataire": "Karim Alaoui", "qualite": "Gérant",
          "adresse_siege": "12 rue X, Kelaa", "telephone": "0612345678", "email": "k@atlas.ma",
          "cnss": "1234567", "rc_ville": "Kelaa", "rc": "4567", "tp": "11122233", "ice": "001234567000089",
          "rib_type": "bancaire", "rib": "230 270 4193980211007100 02", "ville_signature": "Kelaa"}


@pytest.fixture()
def membre(client, db):
    fin = (datetime.now() + timedelta(days=2)).isoformat(timespec="seconds")
    db.execute("""INSERT INTO members(nom,email,company,plan,subscription_status,session_token,email_verified,
                     actif,secteurs,created_at,trial_ends)
                  VALUES('Karim','cand@example.com','Atlas','free','TRIAL','jeton-cand-0001',1,1,'["T101"]',?,?)""",
               (datetime.now().isoformat(), fin))
    db.execute("""INSERT INTO tenders(id,objet,secteur,statut,source,date_limite,description,scraped_at,type_procedure)
                  VALUES('ao_777001','Travaux de construction de pistes','T101','actif','marchespublics',
                         '20/12/2026',?,?,'marche')""", (AVIS, datetime.now().isoformat()))
    db.execute("""INSERT INTO tenders(id,objet,secteur,statut,source,date_limite,description,scraped_at,type_procedure)
                  VALUES('ao_777002','Gardiennage','S501','actif','marchespublics','20/12/2026','',?,'marche')""",
               (datetime.now().isoformat(),))
    db.commit()
    client.cookies.set("_session", "jeton-cand-0001")
    client.get("/entreprise/fiche")
    return client


def _csrf(client):
    return client.cookies.get("_csrf")


class TestParcours:
    def test_fiche_enregistree_puis_pieces_remplies(self, membre):
        r = membre.post("/entreprise/fiche", data=dict(PROFIL, csrf_token=_csrf(membre)), follow_redirects=False)
        assert r.status_code == 303
        page = membre.get("/tenders/ao_777001/candidature").text
        assert "Pièces remplies au nom de ATLAS PISTES SARL" in page
        dec = membre.get("/tenders/ao_777001/candidature/declaration").text
        assert "ATLAS PISTES SARL" in dec and "001234567000089" in dec
        assert "cinquante pour cent (50%)" in dec and "article 152" in dec

    def test_rib_faux_refuse(self, membre):
        r = membre.post("/entreprise/fiche", data=dict(PROFIL, rib="123", csrf_token=_csrf(membre)))
        assert r.status_code == 400 and "24 chiffres" in r.text

    def test_bordereau_et_acte_en_lettres(self, membre):
        membre.post("/entreprise/fiche", data=dict(PROFIL, csrf_token=_csrf(membre)))
        membre.post("/tenders/ao_777001/candidature", data={
            "csrf_token": _csrf(membre), "tva": "20",
            "n_0": "1", "des_0": "Terrassement", "u_0": "m3", "q_0": "1000", "pu_0": "45",
            "n_1": "2", "des_1": "Couche de base", "u_1": "m3", "q_1": "500", "pu_1": "110,50"})
        bp = membre.get("/tenders/ao_777001/candidature/bordereau").text
        assert "100 250,00" in bp and "120 300,00" in bp      # HT, TTC
        acte = membre.get("/tenders/ao_777001/candidature/acte").text
        assert "Cent mille deux cent cinquante dirhams" in acte
        assert "Cent vingt mille trois cents dirhams" in acte and "04/2026" in acte

    def test_hors_secteur_refuse(self, membre):
        assert membre.get("/tenders/ao_777002/candidature").status_code == 404

    def test_sans_compte(self, client):
        r = client.get("/tenders/ao_777001/candidature", follow_redirects=False)
        assert r.status_code == 302 and "/login" in r.headers["location"]

    def test_lien_depuis_la_fiche(self, membre):
        assert 'href="/tenders/ao_777001/candidature"' in membre.get("/tenders/ao_777001").text
