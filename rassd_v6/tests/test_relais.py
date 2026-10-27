# -*- coding: utf-8 -*-
"""Le relais local: un poste au Maroc collecte le portail et dépose ici."""
from datetime import datetime, timedelta

import pytest

import main


def _jeton():
    return {"X-Relais-Jeton": main._jeton_relais()}


def _bdc(n, objet="Achat de fournitures de bureau"):
    return {"id": f"bdc_{n}", "objet": objet, "acheteur": "Commune X", "region": "Agadir",
            "date_limite": (datetime.now() + timedelta(days=5)).strftime("%d/%m/%Y"),
            "url": f"https://www.marchespublics.gov.ma/bdc/entreprise/consultation/show/{n}",
            "secteur": "S903", "type_procedure": "bon_commande"}


class TestAcces:
    def test_sans_jeton_rien(self, client):
        assert client.get("/api/relais/etat").status_code == 401
        assert client.post("/api/relais/depot", json={}).status_code == 401

    def test_mauvais_jeton_rien(self, client):
        r = client.get("/api/relais/etat", headers={"X-Relais-Jeton": "faux"})
        assert r.status_code == 401


class TestEtat:
    def test_reprise_depuis_le_dernier_connu(self, client, db):
        for n in (398500, 398574):
            db.execute("""INSERT INTO tenders(id,objet,secteur,statut,scraped_at,url)
                          VALUES(?,?,?,?,?,?)""", (f"bdc_{n}", "x", "S903", "actif", "2026-10-20", "u"))
        db.commit()
        e = client.get("/api/relais/etat", headers=_jeton()).json()
        assert e["bdc_max"] == 398574 and 398500 in e["bdc_connus"]
        assert e["pages_ao"] == 40, "aucune collecte d'appels d'offres réussie: on relit l'archive"


class TestDepot:
    def test_enregistre_note_et_alerte(self, client, db, monkeypatch):
        alertes = []
        monkeypatch.setattr(main, "dispatch_notifications", lambda l: alertes.extend(l))
        r = client.post("/api/relais/depot", headers=_jeton(), json={
            "source": "marchespublics", "debut": datetime.now().isoformat(),
            "marches": [_bdc(399001), _bdc(399002, "Travaux de peinture")]})
        assert r.json() == {"ok": True, "recus": 2, "enregistres": 2}
        assert db.execute("SELECT source FROM tenders WHERE id='bdc_399001'").fetchone()[0] == "marchespublics"
        run = db.execute("SELECT status, message FROM scraper_runs WHERE source='marchespublics'").fetchone()
        assert tuple(run) == ("SUCCESS", main.MESSAGE_RELAIS)
        assert len(alertes) == 2

    def test_un_depot_vide_est_un_signe_de_vie(self, client, db):
        client.post("/api/relais/depot", headers=_jeton(), json={"source": "marchespublics", "marches": []})
        assert main._relais_actif()

    def test_rejette_ce_qui_ne_vient_pas_du_portail(self, client, db):
        faux = _bdc(399003); faux["url"] = "https://exemple.com/x"
        mauvais_id = _bdc(399004); mauvais_id["id"] = "ao_399004"
        r = client.post("/api/relais/depot", headers=_jeton(), json={
            "source": "marchespublics", "marches": [faux, mauvais_id, "pas un dict"]})
        assert r.json()["recus"] == 0

    def test_source_inconnue(self, client):
        r = client.post("/api/relais/depot", headers=_jeton(), json={"source": "autre", "marches": []})
        assert r.status_code == 400


class TestLeServeurSeRetire:
    def test_relais_recent_le_serveur_ne_tente_pas_le_portail(self, client, db, monkeypatch):
        import asyncio
        client.post("/api/relais/depot", headers=_jeton(), json={"source": "marchespublics", "marches": []})
        appels = []
        import app.services.scraper as sc
        monkeypatch.setattr(sc, "run", lambda *a, **k: appels.append(1) or [])
        import app.services.ao_scraper as ao
        monkeypatch.setattr(ao, "run", lambda *a, **k: appels.append(2) or [])
        # Les autres sources sont neutralisées: le test ne touche pas le réseau.
        import app.services.private_scraper as ps
        import app.services.gagnants as g
        for f in ("run", "run_results", "run_bc", "run_bc_results"):
            monkeypatch.setattr(ps, f, lambda *a, **k: [])
        monkeypatch.setattr(g, "inscrire", lambda *a, **k: {"gagnants": 0, "creees": 0, "lignes": 0})
        monkeypatch.setattr(g, "semer_prospection", lambda *a, **k: {})
        import app.services.notifications as n
        monkeypatch.setattr(n, "dispatch_pending", lambda *a, **k: 0)
        monkeypatch.setattr(main, "dispatch_notifications", lambda l: None)
        main.State.running = False
        asyncio.run(main.do_scrape())
        assert appels == []

    def test_relais_ancien_le_serveur_reprend(self, db):
        vieux = (datetime.now() - timedelta(hours=2)).isoformat()
        db.execute("""INSERT INTO scraper_runs(source,status,records_found,records_saved,duplicates,errors,
                      duration_ms,message,started_at,finished_at) VALUES('marchespublics','SUCCESS',0,0,0,0,1,?,?,?)""",
                   (main.MESSAGE_RELAIS, vieux, vieux))
        db.commit()
        assert main._relais_actif() == ""


class TestFichesACompleter:
    def _ao(self, db, tid, desc):
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,scraped_at,url,description)
                      VALUES(?,?,?,?,?,?,?)""",
                   (tid, "x", "S903", "actif", "2026-10-27 10:00:00",
                    f"https://www.marchespublics.gov.ma/?refConsultation={tid[3:]}", desc))
        db.commit()

    def test_liste_puis_complete(self, client, db):
        self._ao(db, "ao_1031130", "Référence : 60/2026 Objet : x")
        self._ao(db, "ao_1031131", "Date et heure limite de remise des plis : 30/10/2026 10:00 Référence : 1")
        e = client.get("/api/relais/a-completer", headers=_jeton()).json()
        assert [f["id"] for f in e["fiches"]] == ["ao_1031130"] and e["reste"] == 1
        desc = "Date et heure limite de remise des plis : 30/10/2026 10:00 Caution provisoire : 20 000,00 MAD Référence : 60/2026"
        r = client.post("/api/relais/fiches", headers=_jeton(), json={"fiches": [
            {"id": "ao_1031130", "description": desc, "montant": "1 214 040,00 MAD"},
            {"id": "bdc_1", "description": desc}]})
        assert r.json()["corriges"] == 1
        ligne = db.execute("SELECT description, montant FROM tenders WHERE id='ao_1031130'").fetchone()
        assert ligne[0] == desc and ligne[1] == "1 214 040,00 MAD"
        assert client.get("/api/relais/a-completer", headers=_jeton()).json()["reste"] == 0

    def test_sans_jeton_rien(self, client):
        assert client.get("/api/relais/a-completer").status_code == 401
        assert client.post("/api/relais/fiches", json={}).status_code == 401
