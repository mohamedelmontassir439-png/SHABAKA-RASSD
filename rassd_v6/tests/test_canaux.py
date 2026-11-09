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
    @pytest.mark.parametrize("chemin", ["/cgu", "/confidentialite"])
    def test_le_canal_dalerte_nest_pas_promis_sans_expediteur(self, client, chemin):
        """Les pages contractuelles ne citent que ce qui part tout seul."""
        assert cfg.WA_ENABLED is False, "ce test décrit l'état canal fermé"
        assert "Email, WhatsApp" not in client.get(chemin).text

    def test_le_resume_quotidien_peut_etre_annonce(self, client):
        """Il part réellement — de la main du fondateur, depuis /admin/recap.
        L'annoncer est exact. Ce qui serait faux, c'est de le dire
        automatique tant qu'aucun expéditeur Twilio n'existe.
        """
        texte = client.get("/").text
        assert "résumé WhatsApp" in texte
        assert "automatique" not in texte.split("WhatsApp")[1][:120]

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


class TestProvenanceSansLien:
    """Un visiteur arrivé sans « ?src= »: la page d'où il vient, puis ce
    qu'il répond à l'inscription."""

    def test_referent(self):
        from app.core.canaux import depuis_referent
        assert depuis_referent("https://www.google.com/", "marocentrepreneuriat.com") == ("recherche", "google.com")
        assert depuis_referent("https://www.google.co.ma/search?q=x")[0] == "recherche"
        assert depuis_referent("https://l.facebook.com/l.php?u=x")[0] == "facebook"
        assert depuis_referent("https://mail.google.com/")[0] == "email"
        assert depuis_referent("https://lnkd.in/abc")[0] == "linkedin"
        assert depuis_referent("https://exemple.ma/page") == ("site", "exemple.ma")

    def test_pas_de_referent_utile(self):
        from app.core.canaux import depuis_referent
        assert depuis_referent("", "marocentrepreneuriat.com") == ("", "")
        assert depuis_referent("https://marocentrepreneuriat.com/tarifs", "marocentrepreneuriat.com") == ("", "")

    def test_cookie_pose_depuis_google(self, client):
        r = client.get("/", headers={"referer": "https://www.google.com/"})
        assert r.cookies.get("_src", "").startswith("recherche|")

    def test_le_lien_suivi_l_emporte(self, client):
        r = client.get("/?src=facebook", headers={"referer": "https://www.google.com/"})
        assert r.cookies.get("_src", "").startswith("facebook|")

    def test_la_reponse_declaree_l_emporte(self):
        from app.core.canaux import declare, effective
        assert declare("Bouche") == "bouche" and declare("n'importe quoi") == ""
        assert effective("direct", "bouche") == "bouche"
        assert effective("facebook", "") == "facebook"
