# -*- coding: utf-8 -*-
"""Les canaux annoncés doivent être ceux qui fonctionnent.

Telegram a été retiré de l'offre: il demandait au client d'ouvrir un compte,
de trouver un robot et de lui envoyer /start avant de recevoir quoi que ce
soit. `tg_admin` reste, mais c'est la supervision de la plateforme, pas une
livraison au membre.

WhatsApp, lui, n'a pas d'expéditeur tant que WA_ENABLED vaut 0: le mécanisme
est entier, l'annonce attend.
"""
import glob
import os

import pytest

from app.core.config import cfg

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGES_PUBLIQUES = ["/", "/tarifs", "/contact", "/cgu", "/confidentialite",
                   "/mentions-legales", "/login", "/register"]


@pytest.fixture()
def membre_connecte(client, db):
    from datetime import date, timedelta
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
               ("Ahmed", "canaux@example.com", "pro", "ACTIVE",
                (date.today() + timedelta(days=90)).strftime("%Y-%m-%d"),
                "x", "jeton-canaux-reglages", 1, '["T101"]', 1))
    db.commit()
    client.cookies.set("_session", "jeton-canaux-reglages")
    return client


class TestTelegramRetire:
    @pytest.mark.parametrize("chemin", PAGES_PUBLIQUES)
    def test_aucune_page_ne_cite_telegram(self, client, chemin):
        texte = client.get(chemin).text.lower()
        assert "telegram" not in texte
        assert "تيليغرام" not in texte

    def test_aucune_traduction_ne_cite_telegram(self):
        with open(os.path.join(RACINE, "app", "core", "i18n.py"), encoding="utf-8") as f:
            contenu = f.read()
        assert "elegram" not in contenu
        assert "تيليغرام" not in contenu

    def test_les_reglages_ne_proposent_plus_le_canal(self, client, membre_connecte):
        texte = client.get("/settings").text.lower()
        assert "telegram" not in texte
        assert 'name="notif_tg"' not in texte

    def test_la_supervision_du_fondateur_reste(self):
        """tg_admin n'est pas une livraison au client: il nous prévient, nous."""
        from app.services import notifications
        assert hasattr(notifications, "tg_admin")

    def test_la_preference_du_membre_nest_plus_ni_lue_ni_ecrite(self):
        """Seul reste `tg_admin`, qui écrit au fondateur, pas au client."""
        with open(os.path.join(RACINE, "main.py"), encoding="utf-8") as f:
            code = [l for l in f if not l.lstrip().startswith("#")]
        assert not [l for l in code if "notif_tg" in l]

    def test_le_reglage_nest_plus_soumis(self, membre_connecte):
        assert 'name="notif_tg"' not in membre_connecte.get("/settings").text


class TestWhatsAppAnnonceSeulementSiVivant:
    @pytest.mark.parametrize("chemin", ["/", "/cgu", "/confidentialite"])
    def test_rien_nest_promis_sans_expediteur(self, client, chemin):
        assert cfg.WA_ENABLED is False, "ce test décrit l'état canal fermé"
        texte = client.get(chemin).text
        # Le numéro de paiement reste affiché: c'est un contact, pas une
        # alerte. Ce qui est interdit, c'est d'annoncer le canal d'alerte.
        assert "Email, WhatsApp" not in texte
        assert "résumé WhatsApp" not in texte

    def test_la_promesse_revient_avec_le_canal(self, client, monkeypatch):
        monkeypatch.setattr(cfg, "WA_ENABLED", True)
        assert "WhatsApp" in client.get("/cgu").text


class TestResumeQuotidienUnique:
    """Un seul message par jour, et il mène aux marchés de ce membre-là."""

    def test_le_texte_promet_un_message_par_jour(self):
        from app.core.i18n import tr
        for langue in ("fr", "ar"):
            texte = tr("set_ch_wa_desc", langue)
            assert texte, langue
        assert "seul message par jour" in tr("set_ch_wa_desc", "fr")

    def test_le_lien_du_digest_est_personnel(self):
        """Il ne doit plus pointer vers une page qui exige une connexion."""
        with open(os.path.join(RACINE, "app", "services", "notifications.py"),
                  encoding="utf-8") as f:
            source = f.read()
        debut = source.index("def send_daily_wa_digests")
        # On écarte les commentaires: ils citent l'ancienne adresse pour
        # expliquer pourquoi elle a été abandonnée.
        corps = "\n".join(l for l in source[debut:debut + 3000].splitlines()
                          if not l.lstrip().startswith("#"))
        assert "/recap/" in corps
        assert "/opportunites-du-jour" not in corps
