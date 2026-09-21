"""Canal WhatsApp suspendu tant que WA_ENABLED vaut 0.

Le service n'a pas d'expéditeur officiel: promettre des alertes WhatsApp
sur le site alors qu'aucune ne part est la pire des deux options. Le code
du canal reste entier — ces tests vérifient qu'il est bien hors ligne, et
qu'il revient intact une fois le drapeau remis à 1.
"""
from datetime import date, datetime, timedelta

import pytest

import app.services.notifications as notif
from app.core.config import cfg


def _membre_wa(db, email="wa@example.com"):
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                  whatsapp,whatsapp_verified,notif_wa,notif_email,notif_tg,notif_digest,
                  actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               ("Ahmed", email, "free", "TRIAL",
                (date.today() + timedelta(days=5)).strftime("%Y-%m-%d"),
                "0612345678", 1, 1, 0, 0, 0, 1, '["T101"]', 1))
    db.commit()
    return db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()["id"]


def _marche(db, tid="t_wa"):
    db.execute("""INSERT INTO tenders(id,objet,secteur,statut,scraped_at,date_limite,
                  type_offre,type_procedure) VALUES(?,?,?,?,?,?,?,?)""",
               (tid, "Travaux de construction", "T101", "actif",
                "2026-09-21 08:00:00", "30/10/2026", "Public", "marche"))
    db.commit()
    return {"id": tid, "objet": "Travaux de construction", "secteur": "T101",
            "region": "", "montant": "", "acheteur": "", "description": "",
            "date_limite": "30/10/2026", "type_offre": "Public", "type_procedure": "marche"}


@pytest.fixture()
def sans_reseau(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(notif, "tg_admin", lambda *a, **k: None)


class TestCanalHorsLigne:
    def test_aucun_marche_mis_en_file(self, db, monkeypatch, sans_reseau):
        monkeypatch.setattr(cfg, "WA_ENABLED", False)
        mid = _membre_wa(db)
        notif.dispatch_notifications([_marche(db)])
        assert db.execute("SELECT COUNT(*) FROM wa_digest_queue WHERE member_id=?",
                          (mid,)).fetchone()[0] == 0

    def test_resume_quotidien_ne_part_pas(self, db, monkeypatch, sans_reseau):
        monkeypatch.setattr(cfg, "WA_ENABLED", False)
        mid = _membre_wa(db)
        _marche(db)
        db.execute("INSERT INTO wa_digest_queue(member_id,tender_id,created_at) VALUES(?,?,?)",
                   (mid, "t_wa", datetime.now().isoformat()))
        db.commit()
        envois = []
        monkeypatch.setattr(notif, "send_wa", lambda *a: envois.append(a) or True)

        assert notif.send_daily_wa_digests(force=True) == 0
        assert envois == []

    def test_le_canal_revient_quand_on_reactive(self, db, monkeypatch, sans_reseau):
        monkeypatch.setattr(cfg, "WA_ENABLED", True)
        monkeypatch.setattr(cfg, "TWILIO_CONTENT_SID", "")
        monkeypatch.setattr(notif, "is_twilio_sandbox", lambda: False)
        mid = _membre_wa(db)
        notif.dispatch_notifications([_marche(db)])
        assert db.execute("SELECT COUNT(*) FROM wa_digest_queue WHERE member_id=?",
                          (mid,)).fetchone()[0] == 1

        envois = []
        monkeypatch.setattr(notif, "send_wa", lambda tel, msg: envois.append(msg) or True)
        assert notif.send_daily_wa_digests(force=True) == 1
        assert len(envois) == 1


class TestPagesPubliques:
    @pytest.mark.parametrize("chemin", ["/", "/tarifs"])
    def test_le_site_ne_promet_plus_whatsapp(self, client, monkeypatch, chemin):
        monkeypatch.setattr(cfg, "WA_ENABLED", False)
        page = client.get(chemin)
        assert page.status_code == 200
        texte = page.text.lower()
        # Seule mention tolérée: l'annonce « bientôt ».
        for fragment in ("alertes email + telegram + whatsapp",
                         "alertes telegram & whatsapp",
                         "email, telegram et whatsapp"):
            assert fragment not in texte, fragment

    def test_les_textes_whatsapp_reviennent_si_active(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "WA_ENABLED", True)
        assert "whatsapp" in client.get("/tarifs").text.lower()


class TestReglages:
    def _inscrire(self, client):
        client.get("/register")
        client.post("/register", data={
            "email": "set@example.com", "pw": "MotDePasse1!", "pw2": "MotDePasse1!",
            "nom": "Set", "csrf_token": client.cookies.get("_csrf")})
        from app.core.database import get_db
        d = get_db()
        d.execute("UPDATE members SET email_verified=1 WHERE email=?", ("set@example.com",))
        d.commit(); d.close()

    def test_ni_champ_ni_case_whatsapp(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "WA_ENABLED", False)
        self._inscrire(client)
        page = client.get("/settings")
        assert page.status_code == 200
        assert 'name="whatsapp"' not in page.text, "pas de champ numéro"
        assert 'name="notif_wa"' not in page.text, "pas de case à cocher WhatsApp"
        assert "bientôt disponible" in page.text.lower() or "قريباً" in page.text

    def test_envoi_de_code_refuse(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "WA_ENABLED", False)
        self._inscrire(client)
        r = client.post("/settings/whatsapp/send-code",
                        data={"csrf_token": client.cookies.get("_csrf")})
        assert r.status_code == 302 and r.headers["location"] == "/settings"

    def test_champ_present_si_active(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "WA_ENABLED", True)
        self._inscrire(client)
        page = client.get("/settings")
        assert 'name="whatsapp"' in page.text and 'name="notif_wa"' in page.text
