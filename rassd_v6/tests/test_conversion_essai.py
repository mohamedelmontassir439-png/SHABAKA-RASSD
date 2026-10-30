"""Ce qui transforme un essai en abonnement.

Un essai de 24 heures laissait le nouvel inscrit juger la plateforme sur une
journée souvent vide; le rappel de fin ne disait pas ce que l'essai avait
apporté; et le lien de parrainage ne rapportait rien à celui qui le partageait.
"""
import re
from datetime import datetime, timedelta

import pytest

import main
import app.services.notifications as notif
from app.core.config import cfg


def _membre(db, email, heures_depuis=0, duree=168, **kw):
    debut = datetime.now() - timedelta(hours=heures_depuis, minutes=1)
    champs = dict(nom="Ahmed Benali", email=email, plan="free", subscription_status="TRIAL",
                  trial_start=debut.strftime("%Y-%m-%d"),
                  trial_ends=(debut + timedelta(hours=duree)).isoformat(timespec="seconds"),
                  notif_email=1, notif_tg=0, notif_wa=0, notif_digest=0, actif=1,
                  secteurs='["T101"]', email_verified=1, trial_seq=0, phone="0612345678",
                  created_at=debut.isoformat(timespec="seconds"))
    champs.update(kw)
    cols = ",".join(champs)
    db.execute(f"INSERT INTO members({cols}) VALUES({','.join('?' * len(champs))})",
               list(champs.values()))
    db.commit()
    return db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()["id"]


def _marche(db, tid, objet, secteur="T101"):
    db.execute("""INSERT INTO tenders(id,objet,secteur,statut,source,scraped_at)
                  VALUES(?,?,?,?,?,?)""",
               (tid, objet, secteur, "actif", "marchespublics",
                datetime.now().isoformat(timespec="seconds")))
    db.commit()


@pytest.fixture()
def envois(monkeypatch):
    captures = []
    monkeypatch.setattr(notif, "email_send",
                        lambda to, sujet, html, **k: captures.append((to, sujet, html)) or True)
    return captures


class TestEssaiDeSeptJours:
    def test_duree_par_defaut(self):
        assert cfg.TRIAL_HOURS == 168 and cfg.essai() == "7 jours"

    def test_inscription_ouvre_sept_jours(self, client, db):
        page = client.get("/register").text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        client.post("/register", data={
            "nom": "Karim Alaoui", "email": "karim@example.com", "phone": "0612345678",
            "company": "Alaoui Travaux", "pw": "Motdepasse!2026", "pw2": "Motdepasse!2026",
            "csrf_token": csrf, "secteurs_sel": ["T101"]}, follow_redirects=False)
        fin = db.execute("SELECT trial_ends FROM members WHERE email='karim@example.com'").fetchone()[0]
        reste = datetime.fromisoformat(fin) - datetime.now()
        assert timedelta(days=6, hours=23) < reste <= timedelta(days=7)


class TestBilanDEssai:
    def test_le_rappel_chiffre_les_marches_trouves(self, db, envois):
        _membre(db, "bilan@example.com", heures_depuis=130, trial_seq=2)
        _marche(db, "ao_1", "Construction d'une salle polyvalente à Agadir")
        _marche(db, "ao_2", "Réfection de la voirie communale")
        assert notif.send_trial_sequence() == 1
        sujet, html = envois[0][1], envois[0][2]
        assert sujet.startswith("2 marché(s) trouvé(s) pour vous")
        assert "se termine dans" in sujet
        assert "2 marché(s) de vos secteurs" in html

    def test_sans_marche_le_rappel_reste_simple(self, db, envois):
        _membre(db, "vide@example.com", heures_depuis=130, trial_seq=2)
        notif.send_trial_sequence()
        assert envois[0][1].startswith("Votre essai gratuit se termine dans")
        assert "0 marché" not in envois[0][2]

    def test_whatsapp_quand_le_canal_est_ouvert(self, db, envois, monkeypatch):
        _membre(db, "wa@example.com", heures_depuis=130, trial_seq=2,
                notif_wa=1, whatsapp_verified=1, whatsapp="0612345678")
        _marche(db, "ao_3", "Aménagement d'un jardin public")
        messages = []
        monkeypatch.setattr(cfg, "WA_ENABLED", True)
        monkeypatch.setattr(notif, "twilio_configured", lambda: False)
        monkeypatch.setattr(notif, "send_wa", lambda tel, txt: messages.append(txt) or True)
        notif.send_trial_sequence()
        assert len(messages) == 1 and "*1 marché(s)*" in messages[0]
        assert "Aménagement d'un jardin public" in messages[0]

    def test_pas_de_whatsapp_canal_ferme(self, db, envois, monkeypatch):
        _membre(db, "waoff@example.com", heures_depuis=130, trial_seq=2,
                notif_wa=1, whatsapp_verified=1, whatsapp="0612345678")
        _marche(db, "ao_4", "Travaux d'étanchéité")
        monkeypatch.setattr(cfg, "WA_ENABLED", False)
        monkeypatch.setattr(notif, "send_wa", lambda *a: pytest.fail("canal fermé"))
        notif.send_trial_sequence()

    def test_lien_whatsapp_pret_dans_l_admin(self, admin, db):
        _membre(db, "lien@example.com", heures_depuis=50)
        _marche(db, "ao_5", "Construction d'un dispensaire rural")
        page = admin.get("/admin/members").text
        assert "Bilan d&#39;essai (1)" in page or "Bilan d'essai (1)" in page
        assert "wa.me/212612345678?text=" in page


class TestParrainage:
    def _payer(self, admin, mid, montant=249):
        page = admin.get("/admin/payments").text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        return admin.post("/admin/payments/record", data={
            "member_id": mid, "plan": "monthly", "amount": montant,
            "method": "Virement", "csrf_token": csrf}, follow_redirects=False)

    def test_un_mois_offert_au_parrain(self, admin, db, monkeypatch):
        courriers = []
        monkeypatch.setattr(notif, "email_send", lambda to, s, h, **k: courriers.append((to, s)) or True)
        parrain = _membre(db, "parrain@example.com", heures_depuis=200)
        filleul = _membre(db, "filleul@example.com", referred_by=parrain, company="Benali BTP")
        r = self._payer(admin, filleul)
        assert "parrain=1" in r.headers["location"]
        p = db.execute("SELECT * FROM members WHERE id=?", (parrain,)).fetchone()
        assert p["subscription_status"] == "ACTIVE"
        attendu = (datetime.now().date() + timedelta(days=30)).isoformat()
        assert p["subscription_end"] == attendu
        assert courriers and courriers[0][0] == "parrain@example.com"
        assert "Benali BTP" in courriers[0][1]

    def test_le_mois_s_ajoute_a_l_echeance(self, admin, db, monkeypatch):
        monkeypatch.setattr(notif, "email_send", lambda *a, **k: True)
        fin = (datetime.now().date() + timedelta(days=10)).isoformat()
        parrain = _membre(db, "abonne@example.com", subscription_status="ACTIVE",
                          plan="monthly", subscription_end=fin)
        filleul = _membre(db, "f2@example.com", referred_by=parrain)
        self._payer(admin, filleul)
        p = db.execute("SELECT subscription_end FROM members WHERE id=?", (parrain,)).fetchone()
        assert p[0] == (datetime.now().date() + timedelta(days=40)).isoformat()

    def test_une_seule_recompense_par_filleul(self, admin, db, monkeypatch):
        monkeypatch.setattr(notif, "email_send", lambda *a, **k: True)
        parrain = _membre(db, "p3@example.com")
        filleul = _membre(db, "f3@example.com", referred_by=parrain)
        self._payer(admin, filleul)
        premier = db.execute("SELECT subscription_end FROM members WHERE id=?", (parrain,)).fetchone()[0]
        r = self._payer(admin, filleul)
        assert "parrain=1" not in r.headers["location"]
        assert db.execute("SELECT subscription_end FROM members WHERE id=?", (parrain,)).fetchone()[0] == premier

    def test_sans_parrain_rien_ne_change(self, admin, db):
        seul = _membre(db, "seul@example.com")
        r = self._payer(admin, seul)
        assert "parrain=1" not in r.headers["location"]

    def test_la_page_reglages_annonce_le_mois_offert(self):
        from app.core.i18n import tr
        assert "Un mois offert" in tr("set_referral_sub", "fr", n=0)
