"""La page de paiement d'une formule.

Le membre qui choisit une formule voit le compte à créditer et reçoit les
mêmes informations par email, avec la consigne d'envoyer le reçu du virement
sur WhatsApp pour que son compte soit activé.
"""
import time
from datetime import datetime

import pytest

import app.services.notifications as notif
from app.core.config import cfg


@pytest.fixture()
def envois(monkeypatch):
    captures = []
    monkeypatch.setattr(notif, "email_send",
                        lambda to, sujet, html, **k: captures.append((to, sujet, html)) or True)
    return captures


def _connecte(client, db, email="paie@example.com"):
    db.execute("""INSERT INTO members(nom,email,company,plan,subscription_status,session_token,
                     email_verified,actif,secteurs,created_at)
                  VALUES('Karim','%s','Alaoui Travaux','free','TRIAL','jeton-paiement-0001',1,1,'["T101"]',?)""" % email,
               (datetime.now().isoformat(),))
    db.commit()
    client.cookies.set("_session", "jeton-paiement-0001")


def _attendre(liste, n=1):
    for _ in range(40):
        if len(liste) >= n:
            return
        time.sleep(.05)


class TestTarifs:
    def test_chaque_formule_mene_a_la_page_de_paiement(self, client):
        page = client.get("/tarifs").text
        for plan in ("monthly", "pro", "business"):
            assert f'href="/abonnement/paiement?plan={plan}"' in page


class TestPage:
    def test_elle_donne_le_compte_et_le_montant(self, client):
        page = client.get("/abonnement/paiement?plan=monthly").text
        assert cfg.PAYMENT_RIB in page and cfg.PAYMENT_IBAN in page and cfg.PAYMENT_SWIFT in page
        assert f"{cfg.PLANS['monthly']['price']} MAD" in page

    def test_elle_demande_le_recu_sur_whatsapp(self, client):
        page = client.get("/abonnement/paiement?plan=pro").text
        assert f"https://wa.me/{cfg.PAYMENT_PHONE}?text=" in page
        assert "re%C3%A7u" in page   # « reçu », dans le message prérempli

    def test_formule_inconnue_ramenee_au_mensuel(self, client):
        r = client.get("/abonnement/paiement?plan=xyz")
        assert r.status_code == 200 and "Mensuel" in r.text

    def test_pas_indexee(self, client):
        assert "noindex" in client.get("/abonnement/paiement").text

    def test_en_arabe(self, client):
        client.cookies.set("lang", "ar")
        page = client.get("/abonnement/paiement?plan=monthly").text
        assert "أرسل الوصل على واتساب" in page and cfg.PAYMENT_RIB in page


class TestEmail:
    def test_le_membre_recoit_le_rib_une_seule_fois(self, client, db, envois):
        _connecte(client, db)
        page = client.get("/abonnement/paiement?plan=monthly").text
        assert "paie@example.com" in page
        _attendre(envois)
        assert len(envois) == 1
        to, sujet, html = envois[0]
        assert to == "paie@example.com" and "Mensuel" in sujet
        assert cfg.PAYMENT_RIB in html and "Alaoui Travaux" in html
        client.get("/abonnement/paiement?plan=monthly")
        time.sleep(.3)
        assert len(envois) == 1

    def test_pas_demail_sans_compte(self, client, envois):
        client.get("/abonnement/paiement?plan=monthly")
        time.sleep(.3)
        assert envois == []
