"""Essai gratuit et abonnements — machine à états."""
from datetime import date, datetime, timedelta

import pytest

from app.core.security import subscription_state, has_access


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).strftime("%Y-%m-%d")


class TestSubscriptionState:
    def test_anonyme_sans_acces(self):
        assert has_access(None) is False
        assert subscription_state(None)["status"] == "NONE"

    def test_essai_en_cours_donne_acces(self):
        m = {"plan": "free", "subscription_status": "TRIAL", "trial_ends": _day(3)}
        s = subscription_state(m)
        assert s["status"] == "TRIAL"
        assert s["is_active"] is True
        assert s["in_trial"] is True
        assert s["days_left"] == 3
        assert has_access(m) is True

    def test_dernier_jour_d_essai_encore_actif(self):
        m = {"plan": "free", "subscription_status": "TRIAL", "trial_ends": _day(0)}
        assert has_access(m) is True, "l'essai doit rester valable le jour de son échéance"

    def test_essai_expire_bloque_l_acces(self):
        m = {"plan": "free", "subscription_status": "TRIAL", "trial_ends": _day(-1)}
        s = subscription_state(m)
        assert s["status"] == "EXPIRED"
        assert has_access(m) is False

    @pytest.mark.parametrize("plan", ["monthly", "pro", "business"])
    def test_abonnement_payant_actif(self, plan):
        m = {"plan": plan, "subscription_status": "ACTIVE", "subscription_end": _day(20)}
        assert has_access(m) is True
        assert subscription_state(m)["status"] == "ACTIVE"

    def test_abonnement_payant_expire(self):
        m = {"plan": "monthly", "subscription_status": "ACTIVE", "subscription_end": _day(-1)}
        assert has_access(m) is False
        assert subscription_state(m)["status"] == "EXPIRED"

    def test_plan_payant_sans_echeance_reste_actif(self):
        """Activation manuelle sans date: on n'expire pas sur une donnée absente."""
        m = {"plan": "pro", "subscription_status": "ACTIVE", "subscription_end": ""}
        assert has_access(m) is True

    def test_paiement_prime_sur_essai_expire(self):
        """Un membre qui paie pendant son essai ne doit pas être rétrogradé."""
        m = {"plan": "monthly", "subscription_status": "TRIAL",
             "trial_ends": _day(-5), "subscription_end": _day(25)}
        s = subscription_state(m)
        assert s["status"] == "ACTIVE"
        assert has_access(m) is True

    def test_ancien_membre_free_sans_acces_retroactif(self):
        """Cas de la migration: un compte 'free' historique dont trial_ends est
        encore dans le futur ne doit pas obtenir l'accès sans validation."""
        m = {"plan": "free", "subscription_status": "EXPIRED", "trial_ends": _day(9)}
        assert has_access(m) is False

    def test_date_illisible_ne_donne_pas_l_acces(self):
        m = {"plan": "free", "subscription_status": "TRIAL", "trial_ends": "pas-une-date"}
        assert has_access(m) is False


class TestInscriptionAccordeUnEssai:
    def test_inscription_cree_essai_de_7_jours(self, client, db):
        from app.core.config import cfg
        page = client.get("/register")
        token = page.cookies.get("_csrf")
        r = client.post("/register", data={"phone": "0612345678", "company": "SIMAC", 
            "email": "essai@example.com", "pw": "MotDePasse1!", "pw2": "MotDePasse1!",
            "nom": "Essai", "csrf_token": token, "secteurs_sel": ["T101"]}, follow_redirects=False)
        assert r.status_code == 302

        row = db.execute(
            "SELECT plan, subscription_status, trial_start, trial_ends FROM members WHERE email=?",
            ("essai@example.com",)).fetchone()
        assert row["subscription_status"] == "TRIAL"
        # À l'heure près: 24 heures après l'inscription, pas « demain » entier.
        fin = datetime.fromisoformat(row["trial_ends"])
        assert abs((fin - datetime.now()).total_seconds() - cfg.TRIAL_HOURS * 3600) < 120
        assert row["trial_start"] == date.today().strftime("%Y-%m-%d")

        sub = db.execute("SELECT plan_id, status FROM subscriptions WHERE member_id="
                         "(SELECT id FROM members WHERE email=?)", ("essai@example.com",)).fetchone()
        assert sub is not None, "une ligne d'abonnement doit être ouverte à l'inscription"
        assert sub["status"] == "TRIAL"

    def test_nouvel_inscrit_accede_aux_marches(self, client, confirmer_email):
        page = client.get("/register")
        token = page.cookies.get("_csrf")
        client.post("/register", data={"phone": "0612345678", "company": "SIMAC", 
            "email": "acces@example.com", "pw": "MotDePasse1!", "pw2": "MotDePasse1!",
            "nom": "Acces", "csrf_token": token, "secteurs_sel": ["T101"]}, follow_redirects=False)
        confirmer_email("acces@example.com")
        r = client.get("/tenders", follow_redirects=False)
        assert r.status_code == 200, "pendant l'essai, les marchés doivent être accessibles"


class TestEssaiDe24Heures:
    """L'essai se compte à l'heure près, pas au jour près."""

    def _essai(self, fin):
        return {"plan": "free", "subscription_status": "TRIAL", "trial_ends": fin}

    def test_actif_jusqu_a_l_heure_dite(self):
        fin = (datetime.now() + timedelta(hours=5, minutes=30)).isoformat(timespec="seconds")
        etat = subscription_state(self._essai(fin))
        assert etat["status"] == "TRIAL" and etat["heures_restantes"] == 6

    def test_termine_meme_si_le_jour_n_est_pas_fini(self):
        fin = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
        assert subscription_state(self._essai(fin))["status"] == "EXPIRED"

    def test_un_ancien_essai_au_jour_pres_dure_jusqu_au_soir(self):
        etat = subscription_state(self._essai(date.today().isoformat()))
        assert etat["status"] == "TRIAL"

    def test_la_duree_s_ecrit_dans_les_deux_langues(self):
        from app.core.security import duree_txt
        assert duree_txt(24, "fr") == "24 heures" and duree_txt(24, "ar") == "24 ساعة"
        assert duree_txt(1, "fr") == "1 heure" and duree_txt(5, "ar") == "5 ساعات"
        assert duree_txt(168, "fr") == "7 jours" and duree_txt(168, "ar") == "7 أيام"

    def test_l_accueil_annonce_24_heures(self, client):
        page = client.get("/").text
        assert "Essai gratuit 24 heures" in page and "Essai gratuit 7 jours" not in page
