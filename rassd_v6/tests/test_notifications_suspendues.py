# -*- coding: utf-8 -*-
"""L'administration coupe les messages d'un membre, sans fermer son compte."""
from app.services import notifications as notif


def _membre(db, email="coupe@exemple.ma", suspendu=0):
    db.execute("""INSERT INTO members(email, nom, actif, notif_email, notif_suspendues, created_at)
                  VALUES(?,?,1,1,?, '2026-10-01')""", (email, "Membre", suspendu))
    db.commit()
    return db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()[0]


class TestBouton:
    def test_coupe_puis_retablit(self, admin, db):
        mid = _membre(db)
        page = admin.get("/admin/members").text
        assert "Couper les notifications" in page
        r = admin.post(f"/admin/member/{mid}/notifications",
                       data={"csrf_token": admin.cookies.get("_csrf")}, follow_redirects=False)
        assert r.status_code == 302
        assert db.execute("SELECT notif_suspendues FROM members WHERE id=?", (mid,)).fetchone()[0] == 1
        page = admin.get("/admin/members").text
        assert "notifications coupées" in page and "Rétablir les notifications" in page
        admin.post(f"/admin/member/{mid}/notifications",
                   data={"csrf_token": admin.cookies.get("_csrf")}, follow_redirects=False)
        assert db.execute("SELECT notif_suspendues FROM members WHERE id=?", (mid,)).fetchone()[0] == 0

    def test_reserve_a_ladmin(self, client, db):
        mid = _membre(db)
        client.post(f"/admin/member/{mid}/notifications", data={}, follow_redirects=False)
        assert db.execute("SELECT notif_suspendues FROM members WHERE id=?", (mid,)).fetchone()[0] == 0


class TestEnvoi:
    def test_aucun_email_automatique(self, db, monkeypatch):
        _membre(db, suspendu=1)
        appels = []
        monkeypatch.setattr(notif._req, "post", lambda *a, **k: appels.append(1))
        assert notif.email_send("Coupe@exemple.ma", "Alerte", "<p>x</p>") is False
        assert not appels

    def test_le_mot_de_passe_part_quand_meme(self, db, monkeypatch):
        _membre(db, suspendu=1)
        assert not notif.email_send("x", "s", "h")  # adresse invalide: rien
        assert notif.notifications_suspendues("coupe@exemple.ma")
        # « essentiel » passe le filtre: la suite dépend du fournisseur configuré.
        vus = []
        monkeypatch.setattr(notif, "notifications_suspendues", lambda e: vus.append(e) or True)
        notif.email_send("coupe@exemple.ma", "Réinitialisation", "<p>x</p>", essentiel=True)
        assert not vus

    def test_les_autres_membres_ne_sont_pas_touches(self, db):
        _membre(db, "libre@exemple.ma", 0)
        assert not notif.notifications_suspendues("libre@exemple.ma")
