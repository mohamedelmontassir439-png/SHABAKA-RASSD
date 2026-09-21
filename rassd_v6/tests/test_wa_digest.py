"""Résumé WhatsApp quotidien via Twilio.

Aucun appel réseau: Twilio est simulé. On vérifie que WhatsApp ne part plus
marché par marché, qu'un seul message part par jour, et que les variables
envoyées à Meta respectent ses règles (pas de saut de ligne).
"""
import json
from datetime import date, datetime, timedelta

import pytest

import app.services.notifications as notif
import app.services.whatsapp as wa


def _membre(db, email="wa@example.com", **kw):
    champs = dict(
        nom="Ahmed Benali", email=email, plan="free", subscription_status="TRIAL",
        trial_ends=(date.today() + timedelta(days=5)).strftime("%Y-%m-%d"),
        whatsapp="0612345678", whatsapp_verified=1, notif_wa=1,
        notif_email=0, notif_tg=0, notif_digest=0, actif=1, secteurs='["T101"]',
    )
    champs.update(kw)
    cols = ",".join(champs)
    cur = db.execute(f"INSERT INTO members({cols}) VALUES({','.join('?' * len(champs))})",
                     list(champs.values()))
    db.commit()
    return cur.lastrowid


def _marche(db, tid, objet="Travaux de construction", scraped="2026-09-13 08:00:00"):
    db.execute("""INSERT INTO tenders(id,objet,secteur,statut,scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,?,?,?,?,?,?)""",
               (tid, objet, "T101", "actif", scraped, "30/09/2026", "Public", "marche"))
    db.commit()
    return {"id": tid, "objet": objet, "secteur": "T101", "region": "", "montant": "",
            "acheteur": "", "description": "", "date_limite": "30/09/2026",
            "type_offre": "Public", "type_procedure": "marche"}


@pytest.fixture(autouse=True)
def canal_actif(monkeypatch):
    """Ce fichier décrit le canal WhatsApp en service.

    Par défaut il est suspendu (WA_ENABLED=0, cf. test_wa_suspendu.py); on
    l'active ici pour vérifier le comportement du jour où il rouvrira.
    """
    monkeypatch.setattr(notif.cfg, "WA_ENABLED", True)


@pytest.fixture()
def sans_attente(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Un vrai TELEGRAM_BOT peut être présent dans le .env local: aucun test ne
    # doit envoyer de message réel à l'administrateur.
    monkeypatch.setattr(notif, "tg_admin", lambda *a, **k: None)
    monkeypatch.setattr(notif, "is_twilio_sandbox", lambda: False)


class TestVariablesDeModele:
    def test_sauts_de_ligne_et_tabulations_supprimes(self):
        assert wa.clean_template_var("Travaux\nde\tconstruction     lot 2") == "Travaux de construction lot 2"

    def test_valeur_vide_remplacee(self):
        assert wa.clean_template_var("", "cher membre") == "cher membre"
        assert wa.clean_template_var(None, "x") == "x"

    def test_valeur_trop_longue_tronquee(self):
        v = wa.clean_template_var("a" * 500, max_len=50)
        assert len(v) == 50 and v.endswith("…")

    def test_detection_du_sandbox(self, monkeypatch):
        monkeypatch.setattr(wa.cfg, "TWILIO_WA_FROM", "whatsapp:+14155238886")
        assert wa.is_twilio_sandbox() is True
        monkeypatch.setattr(wa.cfg, "TWILIO_WA_FROM", "+212600000000")
        assert wa.is_twilio_sandbox() is False


class TestEnvoiModeleTwilio:
    def test_parametres_content_sid(self, monkeypatch):
        monkeypatch.setattr(wa.cfg, "TWILIO_SID", "ACtest")
        monkeypatch.setattr(wa.cfg, "TWILIO_AUTH_TOKEN", "secret")
        monkeypatch.setattr(wa.cfg, "TWILIO_WA_FROM", "+14155238886")
        capture = {}

        class Rep:
            status_code = 201
            text = "{}"

        def faux_post(url, auth=None, data=None, timeout=None):
            capture.update(url=url, data=data)
            return Rep()

        monkeypatch.setattr(wa.requests, "post", faux_post)
        ok = wa.send_wa_template("06 12 34 56 78", "HXabc", {"1": "Ahmed\nBenali", "2": 3})
        assert ok is True
        assert capture["data"]["ContentSid"] == "HXabc"
        assert capture["data"]["To"] == "whatsapp:+212612345678"
        assert capture["data"]["From"] == "whatsapp:+14155238886"
        variables = json.loads(capture["data"]["ContentVariables"])
        assert variables == {"1": "Ahmed Benali", "2": "3"}

    def test_sans_twilio_rien_ne_part(self, monkeypatch):
        monkeypatch.setattr(wa.cfg, "TWILIO_SID", "")
        assert wa.send_wa_template("0612345678", "HXabc", {"1": "x"}) is False


class TestMiseEnFile:
    def test_whatsapp_mis_en_file_et_non_envoye(self, db, monkeypatch, sans_attente):
        mid = _membre(db)
        t = _marche(db, "t_file_1")
        appels = []
        monkeypatch.setattr(notif, "send_wa", lambda *a, **k: appels.append(a) or True)

        notif.dispatch_notifications([t])

        assert appels == [], "aucun WhatsApp ne doit partir au moment du scraping"
        rows = db.execute("SELECT tender_id, sent_at FROM wa_digest_queue WHERE member_id=?",
                          (mid,)).fetchall()
        assert [(r["tender_id"], r["sent_at"]) for r in rows] == [("t_file_1", "")]

    def test_numero_non_verifie_non_mis_en_file(self, db, monkeypatch, sans_attente):
        mid = _membre(db, whatsapp_verified=0)
        notif.dispatch_notifications([_marche(db, "t_nv")])
        assert db.execute("SELECT COUNT(*) FROM wa_digest_queue WHERE member_id=?",
                          (mid,)).fetchone()[0] == 0


class TestResumeQuotidien:
    MATIN = datetime(2026, 9, 13, 9, 30)

    def _prepare(self, db, n=3, **kw):
        mid = _membre(db, **kw)
        for i in range(n):
            _marche(db, f"t_{mid}_{i}", objet=f"Marché numéro {i}",
                    scraped=f"2026-09-13 0{i}:00:00")
            db.execute("INSERT INTO wa_digest_queue(member_id,tender_id,created_at) VALUES(?,?,?)",
                       (mid, f"t_{mid}_{i}", "2026-09-13T08:00:00"))
        db.commit()
        return mid

    def test_rien_avant_l_heure(self, db, monkeypatch, sans_attente):
        self._prepare(db)
        monkeypatch.setattr(notif.cfg, "WA_DIGEST_HOUR", 9)
        assert notif.send_daily_wa_digests(now=datetime(2026, 9, 13, 7, 0)) == 0

    def test_un_seul_message_pour_plusieurs_marches(self, db, monkeypatch, sans_attente):
        mid = self._prepare(db, n=3)
        monkeypatch.setattr(notif.cfg, "TWILIO_CONTENT_SID", "")
        envois = []
        monkeypatch.setattr(notif, "send_wa", lambda tel, msg: envois.append(msg) or True)

        assert notif.send_daily_wa_digests(now=self.MATIN) == 1
        assert len(envois) == 1
        assert "3 nouvelle(s) opportunité(s)" in envois[0]
        assert "/opportunites-du-jour" in envois[0]
        assert db.execute("SELECT COUNT(*) FROM wa_digest_queue WHERE member_id=? AND sent_at!=''",
                          (mid,)).fetchone()[0] == 3

    def test_pas_de_second_envoi_le_meme_jour(self, db, monkeypatch, sans_attente):
        mid = self._prepare(db, n=2)
        monkeypatch.setattr(notif.cfg, "TWILIO_CONTENT_SID", "")
        envois = []
        monkeypatch.setattr(notif, "send_wa", lambda tel, msg: envois.append(msg) or True)
        notif.send_daily_wa_digests(now=self.MATIN)

        _marche(db, "t_tardif")
        db.execute("INSERT INTO wa_digest_queue(member_id,tender_id,created_at) VALUES(?,?,?)",
                   (mid, "t_tardif", "2026-09-13T15:00:00"))
        db.commit()
        assert notif.send_daily_wa_digests(now=datetime(2026, 9, 13, 16, 0)) == 0
        assert len(envois) == 1, "le marché tardif attend le résumé du lendemain"

    def test_file_vide_aucun_message(self, db, monkeypatch, sans_attente):
        _membre(db)
        envois = []
        monkeypatch.setattr(notif, "send_wa", lambda tel, msg: envois.append(msg) or True)
        assert notif.send_daily_wa_digests(now=self.MATIN) == 0
        assert envois == []

    def test_echec_retente_puis_abandonne_apres_trois(self, db, monkeypatch, sans_attente):
        mid = self._prepare(db, n=1)
        monkeypatch.setattr(notif.cfg, "TWILIO_CONTENT_SID", "")
        tentatives = []

        def echec(tel, msg):
            tentatives.append(1)
            return False

        monkeypatch.setattr(notif, "send_wa", echec)
        for _ in range(5):
            notif.send_daily_wa_digests(now=self.MATIN)
        assert len(tentatives) == 3, "au plus 3 tentatives facturées par jour"
        assert db.execute("SELECT COUNT(*) FROM wa_digest_queue WHERE member_id=? AND sent_at!=''",
                          (mid,)).fetchone()[0] == 0, "un échec n'est jamais marqué comme envoyé"

    def test_modele_approuve_utilise_en_production(self, db, monkeypatch, sans_attente):
        self._prepare(db, n=4)
        monkeypatch.setattr(notif.cfg, "TWILIO_CONTENT_SID", "HXresume")
        monkeypatch.setattr(notif, "twilio_configured", lambda: True)
        capture = {}

        def faux_modele(tel, sid, variables):
            capture.update(sid=sid, v=variables)
            return True

        def texte_libre_interdit(*a, **k):
            pytest.fail("texte libre interdit quand un modèle approuvé est configuré")

        monkeypatch.setattr(notif, "send_wa_template", faux_modele)
        monkeypatch.setattr(notif, "send_wa", texte_libre_interdit)

        assert notif.send_daily_wa_digests(now=self.MATIN) == 1
        assert capture["sid"] == "HXresume"
        assert capture["v"]["1"] == "Ahmed"
        assert capture["v"]["2"] == "4"
        assert all("\n" not in str(v) for v in capture["v"].values())

    def test_membre_sans_acces_ignore(self, db, monkeypatch, sans_attente):
        passe = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        self._prepare(db, n=2, trial_ends=passe)
        envois = []
        monkeypatch.setattr(notif, "send_wa", lambda tel, msg: envois.append(msg) or True)
        assert notif.send_daily_wa_digests(now=self.MATIN) == 0
        assert envois == []


class TestPageDuJour:
    def test_exige_une_connexion(self, client):
        r = client.get("/opportunites-du-jour")
        assert r.status_code == 302 and "/login" in r.headers["location"]

    def test_affiche_les_marches_en_file(self, client, db, confirmer_email):
        client.get("/register")
        client.post("/register", data={
            "email": "page@example.com", "pw": "MotDePasse1!", "pw2": "MotDePasse1!",
            "nom": "Page", "csrf_token": client.cookies.get("_csrf")})
        confirmer_email("page@example.com")
        mid = db.execute("SELECT id FROM members WHERE email=?", ("page@example.com",)).fetchone()["id"]
        _marche(db, "t_page", objet="MARCHE VISIBLE DANS LE RESUME")
        db.execute("INSERT INTO wa_digest_queue(member_id,tender_id,created_at) VALUES(?,?,?)",
                   (mid, "t_page", datetime.now().isoformat()))
        db.commit()
        page = client.get("/opportunites-du-jour")
        assert page.status_code == 200
        assert "MARCHE VISIBLE DANS LE RESUME" in page.text
