"""Vérification de l'adresse email à l'inscription.

Une adresse bien formée n'est pas une adresse qui existe: un ami de
l'auteur s'est inscrit avec une adresse Gmail inexistante et la plateforme
lui a ouvert un essai complet. Ces tests verrouillent la règle: pas de
marchés tant que le lien envoyé n'a pas été cliqué.
"""
from datetime import datetime, timedelta

import pytest


def _inscrire(client, email="nouveau@example.com"):
    client.get("/register")
    return client.post("/register", data={
        "email": email, "pw": "MotDePasse1!", "pw2": "MotDePasse1!",
        "nom": "Nouveau", "csrf_token": client.cookies.get("_csrf")})


def _membre(db, email="nouveau@example.com"):
    return db.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone()


@pytest.fixture(autouse=True)
def _pas_d_envoi_reel(monkeypatch):
    """Aucun test n'envoie d'email: on capture les appels."""
    envois = []
    import main
    monkeypatch.setattr(main, "envoyer_lien_verification",
                        lambda email, token, lang="fr": envois.append((email, token)))
    return envois


class TestInscription:
    def test_compte_cree_non_verifie_avec_jeton(self, client, db):
        _inscrire(client)
        m = _membre(db)
        assert m["email_verified"] == 0
        assert m["email_token"], "un jeton de confirmation doit être généré"
        assert m["email_token_expires"] > datetime.now().isoformat()

    def test_redirige_vers_la_page_de_confirmation(self, client):
        r = _inscrire(client)
        assert r.status_code == 302
        assert "/verifier-email" in r.headers["location"]

    def test_lien_envoye_a_l_adresse_saisie(self, client, _pas_d_envoi_reel):
        _inscrire(client, "cible@example.com")
        assert [e for e, _ in _pas_d_envoi_reel] == ["cible@example.com"]


class TestBlocageAvantConfirmation:
    @pytest.mark.parametrize("chemin", ["/tenders", "/bons-de-commande",
                                        "/resultats", "/favorites", "/dashboard"])
    def test_pages_de_donnees_renvoient_vers_la_confirmation(self, client, chemin):
        _inscrire(client)
        r = client.get(chemin)
        assert r.status_code == 302
        assert "/verifier-email" in r.headers["location"]

    def test_api_refuse_avec_403(self, client):
        _inscrire(client)
        r = client.get("/api/v1/tenders")
        assert r.status_code == 403

    def test_pages_publiques_restent_ouvertes(self, client):
        _inscrire(client)
        for chemin in ("/", "/tarifs", "/settings", "/verifier-email"):
            assert client.get(chemin).status_code == 200, chemin


class TestConfirmation:
    def test_jeton_valide_ouvre_l_acces(self, client, db):
        _inscrire(client)
        token = _membre(db)["email_token"]

        r = client.get(f"/verifier-email?token={token}")
        assert r.status_code == 302 and "verifie=1" in r.headers["location"]

        m = _membre(db)
        assert m["email_verified"] == 1
        assert m["email_token"] == "", "le jeton est consommé"
        assert client.get("/tenders").status_code == 200

    def test_jeton_inconnu_refuse(self, client, db):
        _inscrire(client)
        r = client.get("/verifier-email?token=jeton-invente")
        assert r.status_code == 400
        assert _membre(db)["email_verified"] == 0

    def test_jeton_expire_refuse(self, client, db):
        _inscrire(client)
        token = _membre(db)["email_token"]
        db.execute("UPDATE members SET email_token_expires=? WHERE email_token=?",
                   ((datetime.now() - timedelta(days=1)).isoformat(), token))
        db.commit()

        r = client.get(f"/verifier-email?token={token}")
        assert r.status_code == 400
        assert _membre(db)["email_verified"] == 0

    def test_jeton_non_rejouable(self, client, db):
        _inscrire(client)
        token = _membre(db)["email_token"]
        client.get(f"/verifier-email?token={token}")
        assert client.get(f"/verifier-email?token={token}").status_code == 400


class TestRenvoi:
    def test_nouveau_jeton_envoye(self, client, db, _pas_d_envoi_reel):
        _inscrire(client)
        premier = _membre(db)["email_token"]
        client.get("/verifier-email")

        r = client.post("/verifier-email/renvoyer",
                        data={"csrf_token": client.cookies.get("_csrf")})
        assert r.status_code == 302
        second = _membre(db)["email_token"]
        assert second and second != premier, "l'ancien lien est remplacé"
        assert len(_pas_d_envoi_reel) == 2

    def test_ancien_jeton_invalide_apres_renvoi(self, client, db):
        _inscrire(client)
        premier = _membre(db)["email_token"]
        client.get("/verifier-email")
        client.post("/verifier-email/renvoyer",
                    data={"csrf_token": client.cookies.get("_csrf")})
        assert client.get(f"/verifier-email?token={premier}").status_code == 400


class TestNotifications:
    def test_pas_d_email_vers_une_adresse_non_confirmee(self, db, monkeypatch):
        import app.services.notifications as notif
        db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                      notif_email,notif_tg,notif_wa,notif_digest,actif,secteurs,email_verified)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                   ("Faux", "inexistant@example.com", "free", "TRIAL",
                    (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"),
                    1, 0, 0, 0, 1, '["T101"]', 0))
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,scraped_at,date_limite,
                      type_offre,type_procedure)
                      VALUES(?,?,?,?,?,?,?,?)""",
                   ("t_verif", "Travaux de construction", "T101", "actif",
                    "2026-09-20 08:00:00", "30/10/2026", "Public", "marche"))
        db.commit()

        envois = []
        monkeypatch.setattr(notif, "email_send", lambda *a, **k: envois.append(a) or True)
        monkeypatch.setattr(notif, "tg_admin", lambda *a, **k: None)

        notif.dispatch_notifications([{
            "id": "t_verif", "objet": "Travaux de construction", "secteur": "T101",
            "region": "", "montant": "", "acheteur": "", "description": "",
            "date_limite": "30/10/2026", "type_offre": "Public", "type_procedure": "marche"}])

        assert envois == [], "aucun email vers une adresse jamais confirmée"
