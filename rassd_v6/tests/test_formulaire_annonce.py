"""Les deux types d'annonce doivent être choisissables.

Relevé le 01/10/2026: un clic sur « Propose ses services » ne faisait rien.
Les deux options étaient enfermées dans un unique <label>, qui ne pilote
qu'un seul contrôle — le premier. Toute la zone activait donc « Recherche un
sous-traitant », et personne ne pouvait publier une offre de services.
"""
from datetime import date, timedelta

import pytest


def _membre(db):
    db.execute("""INSERT INTO members(nom,email,company,plan,subscription_status,
                  trial_ends,pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               ("Ahmed", "a@example.com", "SARL ALPHA", "pro", "ACTIVE",
                (date.today() + timedelta(days=90)).strftime("%Y-%m-%d"),
                "x", "jeton-annonce", 1, '["T101"]', 1))
    db.commit()
    return "jeton-annonce"


@pytest.fixture()
def connecte(client, db):
    client.cookies.set("_session", _membre(db))
    return client


class TestChoixDuType:
    def test_chaque_option_porte_son_propre_label(self):
        page = open("templates/subtraitance_new.html", encoding="utf-8").read()
        bloc = page[page.index('class="type-choice"'):page.index("</div>", page.index('value="offre"'))]
        assert bloc.count("<label class=\"type-opt\"") == 2, \
            "un label partagé n'active que le premier bouton"

    def test_le_conteneur_n_est_plus_un_label(self):
        page = open("templates/subtraitance_new.html", encoding="utf-8").read()
        assert '<label class="type-choice"' not in page

    def test_le_bouton_reste_atteignable_au_clavier(self):
        # display:none l'aurait retiré de la tabulation et des lecteurs d'écran.
        page = open("templates/subtraitance_new.html", encoding="utf-8").read()
        regle = page[page.index(".type-opt input {"):page.index("}", page.index(".type-opt input {"))]
        assert "display: none" not in regle

    @pytest.mark.parametrize("type_annonce", ["demande", "offre"])
    def test_les_deux_types_sont_enregistres(self, connecte, db, type_annonce):
        """Le vrai test: ce que le serveur reçoit, pas ce que la page montre."""
        jeton = connecte.get("/sous-traitance/nouveau").text
        import re
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', jeton).group(1)
        connecte.post("/sous-traitance/nouveau", data={
            "csrf_token": csrf, "type": type_annonce,
            "titre": f"Annonce {type_annonce}", "secteur": "T101",
            "region": "Casablanca", "budget": "", "date_limite": "",
            "description": "Description suffisamment longue pour passer.",
        })
        ligne = db.execute("SELECT type FROM subcontract_posts WHERE titre=?",
                           (f"Annonce {type_annonce}",)).fetchone()
        assert ligne is not None, "l'annonce n'a pas été créée"
        assert ligne[0] == type_annonce
