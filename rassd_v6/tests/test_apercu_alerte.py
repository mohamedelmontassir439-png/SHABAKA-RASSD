# -*- coding: utf-8 -*-
"""L'aperçu d'alerte: voir ce que reçoit vraiment un abonné.

L'ancien test envoyait un marché fabriqué — objet « TEST — Marché de test »,
acheteur « Administration Marocaine », montant rond. On ne pouvait donc rien
juger: ni la longueur d'un objet réel, ni un montant à la marocaine, ni une
date limite proche qui change le bandeau.
"""
from datetime import date, timedelta

import pytest

from app.core.config import cfg
from app.services import notifications as notif


@pytest.fixture()
def admin(client):
    client.get("/admin/login")
    client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                      "csrf_token": client.cookies.get("_csrf")})
    return client


def _marche(db, tid="t_ap", objet="TRAVAUX DE CONSTRUCTION D'UN GROUPE SCOLAIRE A SIDI BERNOUSSI"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,'COMMUNE DE CASABLANCA','T101','Casablanca',
                  '1 248 500,00 MAD','actif','2026-10-03 08:00:00',?,'Public','marche')""",
               (tid, objet, (date.today() + timedelta(days=9)).strftime("%d/%m/%Y")))
    db.commit()


class TestContenu:
    def test_il_envoie_un_marche_reel(self, db, monkeypatch):
        envois = []
        monkeypatch.setattr(notif, "email_send",
                            lambda to, obj, html: envois.append((to, obj, html)) or True)
        _marche(db)
        ok, marche = notif.envoyer_apercu("essai@example.com")
        assert ok and marche["id"] == "t_ap"
        destinataire, objet, html = envois[0]
        assert destinataire == "essai@example.com"
        assert "SIDI BERNOUSSI" in objet
        assert "1 248 500,00 MAD" in html

    def test_lobjet_nannonce_plus_un_test(self, db, monkeypatch):
        envois = []
        monkeypatch.setattr(notif, "email_send",
                            lambda to, obj, html: envois.append(obj) or True)
        _marche(db)
        notif.envoyer_apercu("essai@example.com")
        assert "TEST" not in envois[0] and "🧪" not in envois[0]

    def test_il_prend_le_plus_recent(self, db, monkeypatch):
        monkeypatch.setattr(notif, "email_send", lambda *a: True)
        _marche(db, "t_vieux", "ANCIEN MARCHE")
        db.execute("UPDATE tenders SET scraped_at='2026-01-01 08:00:00' WHERE id='t_vieux'")
        _marche(db, "t_neuf", "MARCHE RECENT")
        db.commit()
        _, marche = notif.envoyer_apercu("essai@example.com")
        assert marche["id"] == "t_neuf"

    def test_on_peut_choisir_le_marche(self, db, monkeypatch):
        monkeypatch.setattr(notif, "email_send", lambda *a: True)
        _marche(db, "t_a", "PREMIER")
        _marche(db, "t_b", "SECOND")
        _, marche = notif.envoyer_apercu("essai@example.com", "t_a")
        assert marche["id"] == "t_a"

    def test_sans_marche_en_base_rien_ne_part(self, db, monkeypatch):
        envois = []
        monkeypatch.setattr(notif, "email_send", lambda *a: envois.append(a) or True)
        ok, marche = notif.envoyer_apercu("essai@example.com")
        assert not ok and marche is None and not envois

    def test_une_adresse_invalide_nenvoie_rien(self, db, monkeypatch):
        envois = []
        monkeypatch.setattr(notif, "email_send", lambda *a: envois.append(a) or True)
        _marche(db)
        assert notif.envoyer_apercu("pas-une-adresse") == (False, None)
        assert not envois


class TestRoute:
    def test_elle_exige_ladmin(self, client):
        r = client.post("/admin/apercu-alerte", data={"email": "x@y.ma"},
                        follow_redirects=False)
        assert "/admin/login" in r.headers.get("location", "")

    def test_un_get_nenvoie_rien(self, admin):
        """Un GET qui envoie un email part sur un simple préchargement."""
        assert admin.get("/admin/apercu-alerte").status_code in (404, 405)

    def test_le_bouton_est_sur_le_tableau_de_bord(self, admin):
        assert 'action="/admin/apercu-alerte"' in admin.get("/admin").text

    def test_envoi_depuis_la_page(self, admin, db, monkeypatch):
        monkeypatch.setattr(notif, "email_send", lambda *a: True)
        _marche(db)
        admin.get("/admin")
        r = admin.post("/admin/apercu-alerte",
                       data={"email": "boukilfarida69@example.com",
                             "csrf_token": admin.cookies.get("_csrf")},
                       follow_redirects=False)
        assert "apercu=ok" in r.headers.get("location", "")
