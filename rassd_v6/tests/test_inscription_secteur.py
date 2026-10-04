# -*- coding: utf-8 -*-
"""L'inscription exige au moins un secteur.

Le choix était facultatif, et l'indice sous les cases invitait même à le
sauter: « Laissez vide pour recevoir tous les marchés ». Or un profil vide
ne restreint rien — le nouvel inscrit recevait les deux mille quatre cents
marchés actifs, soit l'inverse de ce qu'il vient chercher, et jugeait la
plateforme sur un flot illisible.

Dix secondes au moment où il est motivé valent mieux qu'un réglage qu'il ne
trouvera jamais.
"""
import pytest


def _champs(client, **extra):
    base = {"email": "neuf@example.com", "pw": "MotDePasse1!", "pw2": "MotDePasse1!",
            "nom": "Ahmed", "csrf_token": client.cookies.get("_csrf")}
    base.update(extra)
    return base


class TestSecteurObligatoire:
    def test_sans_secteur_linscription_est_refusee(self, client, db):
        client.get("/register")
        r = client.post("/register", data=_champs(client), follow_redirects=False)
        assert r.status_code == 200, "la page doit se réafficher avec l'erreur"
        assert "au moins un secteur" in r.text
        assert db.execute("SELECT COUNT(*) FROM members WHERE email='neuf@example.com'"
                          ).fetchone()[0] == 0

    def test_avec_un_secteur_elle_passe(self, client, db):
        client.get("/register")
        r = client.post("/register", data=_champs(client, secteurs_sel=["T101"]),
                        follow_redirects=False)
        assert r.status_code in (302, 303), r.text[:300]
        ligne = db.execute("SELECT secteurs FROM members WHERE email='neuf@example.com'"
                           ).fetchone()
        assert ligne and "T101" in ligne[0]

    def test_des_cases_vides_ne_comptent_pas(self, client, db):
        """Un formulaire bricolé peut envoyer des valeurs blanches."""
        client.get("/register")
        r = client.post("/register", data=_champs(client, secteurs_sel=["", "  "]),
                        follow_redirects=False)
        assert r.status_code == 200 and "au moins un secteur" in r.text


class TestConsigne:
    def test_la_page_ninvite_plus_a_sauter_letape(self, client):
        """L'indice disait « Laissez vide pour recevoir tous les marchés »."""
        page = client.get("/register").text
        assert "Laissez vide" not in page
        assert "Choisissez vos m" in page

    @pytest.mark.parametrize("langue,attendu", [("fr", "Choisissez vos m"),
                                                ("ar", "اختر مجالاتك")])
    def test_la_consigne_existe_dans_les_deux_langues(self, client, langue, attendu):
        assert attendu in client.get(f"/register?lang={langue}").text
