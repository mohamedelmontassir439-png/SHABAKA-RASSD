"""Mois d'essai à 99 MAD (17/11/2026): toutes les fonctions, une seule fois
par compte; ensuite, seul l'abonnement annuel à 3 999 MAD est proposé."""
from datetime import datetime, timedelta
from urllib.parse import unquote

from app.core.config import cfg
from app.core.security import essai_ouvert, has_access, subscription_state


def _membre(db, email="essai@example.com", plan="free", statut="PENDING", fin="", jeton="jeton-essai-aaaa"):
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,subscription_end,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified,created_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
               ("Karim", email, plan, statut, fin, "", "x", jeton, 1, '["T101"]', 1,
                datetime.now().isoformat()))
    db.commit()
    return dict(db.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone())


def _payer(admin, mid, plan, montant):
    admin.get("/admin/payments")
    return admin.post("/admin/payments/record", data={
        "member_id": mid, "plan": plan, "amount": montant, "method": "Virement",
        "csrf_token": admin.cookies.get("_csrf")}, follow_redirects=False)


class TestOffre:
    def test_le_plan_essai_existe(self):
        p = cfg.PLANS["essai"]
        assert p["price"] == 99 and p["months"] == 1 and p["public"]
        assert cfg.PRIX_ESSAI_TXT == "99" and cfg.PRIX_ANNUEL == 3999

    def test_essai_ouvre_toutes_les_fonctions(self):
        fin = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        m = {"id": 1, "plan": "essai", "subscription_status": "ACTIVE", "subscription_end": fin}
        assert has_access(m) and subscription_state(m)["status"] == "ACTIVE"

    def test_essai_echu_ferme_l_acces(self):
        fin = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        m = {"id": 1, "plan": "essai", "subscription_status": "ACTIVE", "subscription_end": fin}
        assert not has_access(m)
        assert not essai_ouvert(m)


class TestUneSeuleFois:
    def test_le_visiteur_et_le_nouveau_compte_y_ont_droit(self, db):
        assert essai_ouvert(None)
        assert essai_ouvert(_membre(db))

    def test_premier_paiement_essai_puis_refus(self, admin, db):
        m = _membre(db)
        r = _payer(admin, m["id"], "essai", "99")
        assert r.status_code == 302 and "ok=" in r.headers["location"]
        apres = dict(db.execute("SELECT * FROM members WHERE id=?", (m["id"],)).fetchone())
        assert apres["plan"] == "essai" and apres["subscription_status"] == "ACTIVE"
        assert not essai_ouvert(apres)
        # Deuxième essai refusé, même après l'avoir remis en « Inactif ».
        db.execute("UPDATE members SET plan='free', subscription_end='' WHERE id=?", (m["id"],))
        db.commit()
        r = _payer(admin, m["id"], "essai", "99")
        assert "err=essai_deja_utilise" in r.headers["location"]
        assert db.execute("SELECT COUNT(*) FROM payments WHERE member_id=?", (m["id"],)).fetchone()[0] == 1
        # L'annuel, lui, passe.
        r = _payer(admin, m["id"], "pro", "3999")
        assert "ok=" in r.headers["location"]

    def test_un_ancien_abonne_annuel_n_y_a_pas_droit(self, admin, db):
        m = _membre(db, email="ancien@example.com", jeton="jeton-essai-bbbb")
        _payer(admin, m["id"], "pro", "3999")
        r = _payer(admin, m["id"], "essai", "99")
        assert "err=essai_deja_utilise" in r.headers["location"]

    def test_changement_d_offre_direct_aussi_refuse(self, admin, db):
        m = _membre(db, email="direct@example.com", jeton="jeton-essai-cccc")
        _payer(admin, m["id"], "essai", "99")
        admin.get("/admin/members")
        r = admin.post(f"/admin/member/{m['id']}/plan", data={
            "plan": "essai", "csrf_token": admin.cookies.get("_csrf")}, follow_redirects=False)
        assert "err=essai_deja_utilise" in r.headers["location"]


class TestPages:
    def test_tarifs_propose_l_essai_au_visiteur(self, client):
        page = client.get("/tarifs").text
        assert "Mois d'essai" in page or "Mois d&#39;essai" in page
        assert ">99<" in page
        assert "3 999" in page
        lien = unquote(page.split('href="https://wa.me/')[1].split('"')[0])
        assert "99 MAD" in lien

    def test_tarifs_ne_propose_que_l_annuel_apres_l_essai(self, client, db):
        fin = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        m = _membre(db, email="fini@example.com", plan="essai", statut="ACTIVE", fin=fin,
                    jeton="jeton-essai-dddd")
        db.execute("""INSERT INTO subscriptions(member_id,plan_id,price,currency,status,start_date,end_date,
                      created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                   (m["id"], "essai", 99, "MAD", "ACTIVE", "2026-10-01", fin, "x", "x"))
        db.commit()
        client.cookies.set("_session", "jeton-essai-dddd")
        page = client.get("/tarifs").text
        assert ">99<" not in page
        assert "Abonnement annuel" in page
        lien = unquote(page.split('href="https://wa.me/')[1].split('"')[0])
        assert "abonnement annuel" in lien and "essai" not in lien

    def test_accueil_annonce_l_essai(self, client):
        page = client.get("/").text
        assert "Essayer un mois" in page
