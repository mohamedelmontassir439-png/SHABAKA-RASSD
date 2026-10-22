# -*- coding: utf-8 -*-
"""Concurrents et prix (2), suivi des offres (4), alertes de résultats (5)."""
from datetime import date, timedelta

import pytest


def _membre(db, mid=1, jeton="jeton-intel-1", email="i@x.ma", secteurs='["T101"]'):
    db.execute("""INSERT INTO members(id,nom,email,phone,company,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,'pro','ACTIVE',?,'x',?,1,?,1)""",
               (mid, "Ahmed Alaoui", email, "0612345678", "SIMAC",
                (date.today() + timedelta(days=90)).isoformat(), jeton, secteurs))
    db.commit()


def _resultat(db, rid, adj="STE ATLAS BTP SARL", montant="1.200.000,00", secteur="T101",
              acheteur="ministere /DIRECTION PROVINCIALE DE BOU- LEMANE", objet="Travaux de voirie",
              jour="10/10/2026", region="Boulemane"):
    db.execute("""INSERT INTO tender_results(id,objet,acheteur,adjudicataire,region,budget,montant,
                  secteur,date_adjudication,scraped_at) VALUES(?,?,?,?,?,'',?,?,?,'')""",
               (rid, objet, acheteur, adj, region, montant, secteur, jour))
    db.commit()


def _marche(db, tid="ao_9", jours=20, description=""):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,scraped_at,
                  date_limite,type_offre,type_procedure,source,description)
                  VALUES(?,?,?,'T101','Boulemane','',?,'2026-10-01 08:00:00',?,'Public','marche',
                  'marchespublics',?)""",
               (tid, "Travaux de voirie à Boulemane", "DIRECTION PROVINCIALE DE BOULEMANE", "actif",
                (date.today() + timedelta(days=jours)).strftime("%d/%m/%Y"), description))
    db.commit()


class TestIntelligence:
    def test_montants_de_la_source(self):
        from app.services.intelligence import montant
        assert montant("6.720.600.00") == 6720600
        assert montant("5.916.000,00") == 5916000
        assert montant("12575208622272548,00") == 0, "aberrant: on se tait"

    def test_cle_acheteur_recolle_les_mots(self):
        from app.services.intelligence import cle_acheteur
        assert cle_acheteur("ministere /DIRECTION PROVINCIALE DE BOU- LEMANE") == \
            "direction provinciale de boulemane"

    def test_comparables_chez_le_meme_acheteur(self, db):
        from app.services.intelligence import comparables
        _resultat(db, "r1")
        _resultat(db, "r2", adj="annulée.")
        c = comparables({"secteur": "T101", "acheteur": "DIRECTION PROVINCIALE DE BOULEMANE",
                         "region": "Boulemane"})
        assert c["portee"] == "acheteur" and [r["id"] for r in c["lignes"]] == ["r1"]

    def test_qui_gagne(self, db):
        from app.services.intelligence import qui_gagne
        _resultat(db, "r1"); _resultat(db, "r2"); _resultat(db, "r3", adj="SOMAGEC")
        g = qui_gagne("T101")
        assert g[0]["nom"] == "STE ATLAS BTP SARL" and g[0]["marches"] == 2

    def test_page_concurrent_et_suivi(self, client, db):
        _membre(db); _resultat(db, "r1")
        client.cookies.set("_session", "jeton-intel-1")
        page = client.get("/intelligence?q=ATLAS").text
        assert "Travaux de voirie" in page and "Suivre ce concurrent" in page
        client.post("/intelligence/suivre", data={"nom": "ATLAS BTP", "csrf_token": client.cookies.get("_csrf")})
        assert db.execute("SELECT COUNT(*) FROM concurrents_suivis").fetchone()[0] == 1


class TestSuivi:
    AVIS = ("Date et heure limite de remise des plis : {lim} 10:00 Référence 1/2026 Objet : x "
            "Caution provisoire : 20 000,00 MAD Visites des lieux : {vis} 10:00 , siège Variante : Non")

    def _avis(self, lim_j=20, vis_j=6):
        f = lambda n: (date.today() + timedelta(days=n)).strftime("%d/%m/%Y")
        return self.AVIS.format(lim=f(lim_j), vis=f(vis_j))

    def test_echeances_tirees_de_l_avis(self):
        from app.services.suivi import echeances
        e = echeances({"id": "ao_1", "description": self._avis(), "date_limite": ""})
        assert [x["cle"] for x in e] == ["visite", "caution", "depot"]
        assert e[1]["reste"] == 13, "caution: 7 jours avant le dépôt"

    def test_parcours(self, client, db):
        _membre(db); _marche(db, description=self._avis())
        client.cookies.set("_session", "jeton-intel-1")
        client.get("/tenders/ao_9")
        client.post("/suivi/ajouter", data={"tender_id": "ao_9", "csrf_token": client.cookies.get("_csrf")})
        s = db.execute("SELECT * FROM suivi_offres").fetchone()
        assert s["etape"] == "etude"
        client.post(f"/suivi/{s['id']}", data={"etape": "depose", "notes": "Prix 950 000",
                                               "retour": "https://evil.example",
                                               "csrf_token": client.cookies.get("_csrf")})
        s = db.execute("SELECT * FROM suivi_offres").fetchone()
        assert s["etape"] == "depose" and s["notes"] == "Prix 950 000"
        assert "Offre déposée" in client.get("/suivi").text

    def test_le_retour_ne_sort_pas_du_site(self, client, db):
        _membre(db); _marche(db)
        client.cookies.set("_session", "jeton-intel-1")
        client.get("/suivi")
        from app.services.suivi import ajouter
        sid = ajouter(1, {"id": "ao_9", "objet": "x"})
        r = client.post(f"/suivi/{sid}", data={"etape": "etude", "retour": "//evil.example",
                                               "csrf_token": client.cookies.get("_csrf")},
                        follow_redirects=False)
        assert r.headers["location"] == "/suivi"

    def test_rappels(self, db, monkeypatch):
        from app.services import suivi
        _membre(db); _marche(db, description=self._avis(lim_j=20, vis_j=2))
        suivi.ajouter(1, {"id": "ao_9", "objet": "Voirie", "date_limite": ""})
        envoyes = []
        monkeypatch.setattr("app.services.notifications.email_send",
                            lambda to, s, h: envoyes.append(s) or True)
        assert suivi.envoyer_rappels() == 1 and "Visite" in envoyes[0]
        assert suivi.envoyer_rappels() == 0, "un rappel par seuil"
        # Caution demandée: plus de rappel de caution.
        db.execute("UPDATE suivi_offres SET etape='caution'"); db.commit()
        assert all(d["echeance"]["cle"] != "caution"
                   for d in suivi.rappels_dus(date.today() + timedelta(days=13)))


class TestAlertesResultats:
    def test_concurrent_et_marche_suivi(self, db, monkeypatch):
        from app.services import veille_resultats as V, suivi
        _membre(db); _marche(db)
        V.suivre(1, "Atlas BTP")
        suivi.ajouter(1, {"id": "ao_9", "objet": "Travaux de voirie à Boulemane"})
        envoyes = []
        monkeypatch.setattr("app.services.notifications.email_send",
                            lambda to, s, h: envoyes.append((s, h)) or True)
        n = V.notifier([
            {"objet": "Travaux de voirie à Boulemane", "adjudicataire": "STE ATLAS BTP SARL",
             "acheteur": "DP", "montant": "1.000.000,00"},
            {"objet": "Autre chose", "adjudicataire": "Infructueux", "acheteur": "DP"},
        ])
        assert n == 1, "un seul email par membre"
        sujet, corps = envoyes[0]
        assert "suiviez" in sujet and "ATLAS" in corps

    def test_rien_sans_correspondance(self, db, monkeypatch):
        from app.services import veille_resultats as V
        _membre(db)
        monkeypatch.setattr("app.services.notifications.email_send", lambda *a: True)
        assert V.notifier([{"objet": "x", "adjudicataire": "SOMAGEC"}]) == 0


class TestAcheteur:
    def test_adresse_entiere(self):
        from app.services.intelligence import slug_acheteur
        a = slug_acheteur("DIRECTION PROVINCIALE DE L'EQUIPEMENT DU TRANSPORT DE LA LOGISTIQUE ET DE L'EAU DE RABAT")
        b = slug_acheteur("DIRECTION PROVINCIALE DE L'EQUIPEMENT DU TRANSPORT DE LA LOGISTIQUE ET DE L'EAU DE GUERCIF")
        assert a != b

    def test_profil(self, client, db):
        _membre(db); _marche(db)
        _resultat(db, "r1", acheteur="DIRECTION PROVINCIALE DE BOULEMANE")
        _resultat(db, "r2", adj="Annulé", acheteur="DIRECTION PROVINCIALE DE BOULEMANE")
        from app.services.intelligence import profil_acheteur, slug_acheteur
        s = slug_acheteur("DIRECTION PROVINCIALE DE BOULEMANE")
        p = profil_acheteur(s)
        assert p["n_ouverts"] == 1 and p["resultats"] == 2 and p["taux_annule"] == 50
        client.cookies.set("_session", "jeton-intel-1")
        page = client.get(f"/acheteurs/{s}").text
        assert "STE ATLAS BTP SARL" in page and "50 %" in page
        assert f"/acheteurs/{s}" in client.get("/tenders/ao_9").text
