"""Résumé quotidien et retours de livraison Brevo.

Mesuré sur la production: un secteur actif publie jusqu'à 48 marchés par
jour. Un membre en mode « direct » reçoit donc 48 emails — insupportable
pour lui, et au-delà du quota d'envoi gratuit (300/jour) dès 9 membres.
Par ailleurs, continuer d'écrire à une adresse qui rebondit fait chuter la
réputation du domaine et emporte la livraison de tous les autres messages.
"""
from datetime import date, datetime, timedelta

import pytest

import app.services.notifications as notif
from app.core.config import cfg


def _membre(db, email="pro@example.com", rythme="direct", **kw):
    champs = dict(nom="Ahmed", email=email, plan="free", subscription_status="TRIAL",
                  trial_ends=(date.today() + timedelta(days=5)).strftime("%Y-%m-%d"),
                  notif_email=1, notif_tg=0, notif_wa=0, notif_digest=0,
                  notif_rythme=rythme, actif=1, secteurs='["T101"]', email_verified=1)
    champs.update(kw)
    cols = ",".join(champs)
    db.execute(f"INSERT INTO members({cols}) VALUES({','.join('?' * len(champs))})",
               list(champs.values()))
    db.commit()
    return db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()["id"]


def _marche(db, tid, secteur="T101"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,?,?,?,?,'actif',?,?,?,?)""",
               (tid, f"TRAVAUX {tid}", "COMMUNE", secteur, "Casablanca", "",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "30/12/2026", "Public", "marche"))
    db.commit()
    return dict(db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone())


@pytest.fixture()
def envois(monkeypatch):
    captures = []
    monkeypatch.setattr(notif, "email_send",
                        lambda to, sujet, html: captures.append((to, sujet)) or True)
    monkeypatch.setattr(notif, "tg_admin", lambda *a, **k: None)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return captures


class TestRythmeDirect:
    def test_un_email_par_marche(self, db, envois):
        _membre(db, rythme="direct")
        marches = [_marche(db, f"t{i}") for i in range(3)]
        notif.dispatch_notifications(marches)
        assert len(envois) == 3


class TestRythmeQuotidien:
    def test_aucun_email_immediat(self, db, envois):
        mid = _membre(db, rythme="quotidien")
        notif.dispatch_notifications([_marche(db, f"t{i}") for i in range(5)])
        assert envois == [], "rien ne part marché par marché"
        # Mais tout est mis en file pour le résumé du matin.
        assert db.execute("SELECT COUNT(*) FROM notif_queue WHERE member_id=?",
                          (mid,)).fetchone()[0] == 5

    def test_un_seul_email_groupe(self, db, envois):
        mid = _membre(db, rythme="quotidien")
        notif.dispatch_notifications([_marche(db, f"t{i}") for i in range(5)])
        assert notif.send_daily_digests() == 1
        assert len(envois) == 1
        assert "5 marché(s)" in envois[0][1]
        assert db.execute("SELECT COUNT(*) FROM notif_queue WHERE member_id=?",
                          (mid,)).fetchone()[0] == 0, "la file est vidée après envoi"

    def test_pas_deux_resumes_le_meme_jour(self, db, envois):
        _membre(db, rythme="quotidien")
        notif.dispatch_notifications([_marche(db, "t1")])
        notif.send_daily_digests()
        notif.dispatch_notifications([_marche(db, "t2")])
        assert notif.send_daily_digests() == 0
        assert len(envois) == 1

    def test_file_vide_aucun_email(self, db, envois):
        _membre(db, rythme="quotidien")
        assert notif.send_daily_digests() == 0 and envois == []

    def test_membre_sans_acces_ignore(self, db, envois):
        _membre(db, rythme="quotidien",
                trial_ends=(date.today() - timedelta(days=1)).strftime("%Y-%m-%d"))
        notif.dispatch_notifications([_marche(db, "t1")])
        assert notif.send_daily_digests() == 0


class TestRetoursBrevo:
    def _membre_actif(self, db, email="rebond@example.com"):
        return _membre(db, email=email)

    @pytest.mark.parametrize("evenement", ["hard_bounce", "spam", "blocked",
                                           "invalid_email", "unsubscribed"])
    def test_adresse_coupee(self, db, evenement):
        mid = self._membre_actif(db)
        assert notif.traiter_evenement_brevo(
            {"event": evenement, "email": "rebond@example.com"}) == "coupé"
        assert db.execute("SELECT notif_email FROM members WHERE id=?",
                          (mid,)).fetchone()[0] == 0

    def test_evenement_anodin_sans_effet(self, db):
        mid = self._membre_actif(db)
        for anodin in ("delivered", "opened", "click", "soft_bounce"):
            assert notif.traiter_evenement_brevo(
                {"event": anodin, "email": "rebond@example.com"}) == "ignoré"
        assert db.execute("SELECT notif_email FROM members WHERE id=?",
                          (mid,)).fetchone()[0] == 1

    def test_adresse_inconnue(self, db):
        assert notif.traiter_evenement_brevo(
            {"event": "hard_bounce", "email": "personne@ailleurs.com"}) == "inconnu"

    def test_incident_journalise(self, db):
        mid = self._membre_actif(db)
        notif.traiter_evenement_brevo({"event": "spam", "email": "rebond@example.com"})
        ligne = db.execute("SELECT * FROM notif_log WHERE member_id=? ORDER BY id DESC",
                           (mid,)).fetchone()
        assert "spam" in ligne["tender_id"] and ligne["status"] == "FAILED"


class TestEndpointWebhook:
    def test_jeton_exige(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "BREVO_WEBHOOK_TOKEN", "jeton-secret")
        r = client.post("/webhooks/brevo", json={"event": "hard_bounce", "email": "x@y.z"})
        assert r.status_code == 403

    def test_jeton_valide_accepte(self, client, db, monkeypatch):
        monkeypatch.setattr(cfg, "BREVO_WEBHOOK_TOKEN", "jeton-secret")
        mid = _membre(db, email="w@example.com")
        r = client.post("/webhooks/brevo?t=jeton-secret",
                        json={"event": "hard_bounce", "email": "w@example.com"})
        assert r.status_code == 200 and r.json()["traitement"] == "coupé"
        assert db.execute("SELECT notif_email FROM members WHERE id=?",
                          (mid,)).fetchone()[0] == 0

    def test_corps_illisible(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "BREVO_WEBHOOK_TOKEN", "")
        r = client.post("/webhooks/brevo", data="pas du json")
        assert r.status_code == 400

    def test_accessible_sans_compte(self, client, monkeypatch):
        # Brevo appelle sans session: le filtre de vérification d'email ne
        # doit pas intercepter cette URL.
        monkeypatch.setattr(cfg, "BREVO_WEBHOOK_TOKEN", "")
        r = client.post("/webhooks/brevo", json={"event": "delivered", "email": "a@b.c"})
        assert r.status_code == 200
