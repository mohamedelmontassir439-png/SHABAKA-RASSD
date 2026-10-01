"""Le récapitulatif du jour, envoyé à la main par le fondateur.

Le canal WhatsApp automatique demande un compte Meta approuvé et un modèle
de message validé. En attendant, l'envoi reste manuel — et pour les premiers
abonnés, un message écrit de la main du fondateur vaut mieux qu'une
notification de plus. Ce qui manquait n'était pas le canal mais la matière.

Le lien est signé plutôt que stocké: aucune table, et un lien qui ne vaut
que pour un membre et un jour.
"""
from datetime import date, datetime, timedelta

import pytest

from app.services import recap as R


def _membre(db, email="r@example.com", secteurs='["T101"]', phone="0612345678"):
    db.execute("""INSERT INTO members(nom,email,company,phone,plan,subscription_status,
                  trial_ends,pw_hash,session_token,actif,secteurs,notif_types,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               ("Ahmed Benali", email, "SARL ALPHA", phone, "pro", "ACTIVE",
                (date.today() + timedelta(days=90)).strftime("%Y-%m-%d"),
                "x", "jeton-recap-" + email, 1, secteurs, '[]', 1))
    db.commit()
    return db.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone()


def _marche(db, tid, secteur="T101", jour=None):
    quand = (jour or date.today().strftime("%Y-%m-%d")) + " 09:30:00"
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,?,?,?,'actif',?,?,?,?)""",
               (tid, f"TRAVAUX {tid}", "COMMUNE", secteur, "Casablanca", quand,
                (date.today() + timedelta(days=20)).strftime("%d/%m/%Y"),
                "Public", "marche"))
    db.commit()


class TestJetonSigne:
    def test_un_aller_retour_rend_le_membre_et_le_jour(self):
        jour = date.today().strftime("%Y-%m-%d")
        assert R.lire_jeton(R.jeton(12, jour)) == (12, jour)

    def test_le_jeton_d_un_membre_ne_vaut_pas_pour_un_autre(self):
        """Sans signature, il suffirait de changer le chiffre de l'adresse."""
        jour = date.today().strftime("%Y-%m-%d")
        falsifie = R.jeton(12, jour).replace("12-", "13-", 1)
        assert R.lire_jeton(falsifie) == (0, "")

    def test_une_signature_inventee_est_rejetee(self):
        jour = date.today().strftime("%Y-%m-%d")
        assert R.lire_jeton(f"12-{jour}-000000000000000000000000") == (0, "")

    def test_un_lien_ancien_expire(self):
        vieux = (date.today() - timedelta(days=R.JOURS_VALIDITE + 1)).strftime("%Y-%m-%d")
        assert R.lire_jeton(R.jeton(12, vieux)) == (0, "")

    def test_un_lien_dans_la_fenetre_reste_valable(self):
        hier = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        assert R.lire_jeton(R.jeton(12, hier))[0] == 12

    @pytest.mark.parametrize("bricole", ["", "n'importe quoi", "12", "12-2026-10-01",
                                         "abc-2026-10-01-xxxx"])
    def test_rien_de_malforme_ne_passe(self, bricole):
        assert R.lire_jeton(bricole) == (0, "")


class TestContenu:
    def test_seuls_les_marches_du_membre_remontent(self, db):
        m = dict(_membre(db))
        _marche(db, "t_sien", secteur="T101")
        _marche(db, "t_autre", secteur="S930")
        ids = {t["id"] for t in R.marches_du_jour(m)}
        assert ids == {"t_sien"}

    def test_un_autre_jour_ne_remonte_pas(self, db):
        m = dict(_membre(db))
        _marche(db, "t_hier", jour=(date.today() - timedelta(days=1)).strftime("%Y-%m-%d"))
        assert R.marches_du_jour(m) == []

    def test_la_liste_est_bornee(self, db):
        # Au-delà, le message devient un mur de texte que personne ne lit.
        m = dict(_membre(db))
        for i in range(R.MAX_PAR_RECAP + 10):
            _marche(db, f"t{i}")
        assert len(R.marches_du_jour(m)) == R.MAX_PAR_RECAP


class TestMessage:
    def test_il_porte_le_nombre_et_le_lien(self, db):
        m = dict(_membre(db))
        texte = R.message_whatsapp(m, 4, "https://x.ma/recap/abc")
        assert "4 marchés" in texte and "https://x.ma/recap/abc" in texte

    def test_le_singulier_est_respecte(self, db):
        m = dict(_membre(db))
        assert "1 marché " in R.message_whatsapp(m, 1, "https://x.ma/r")

    def test_une_journee_vide_a_son_message(self, db):
        m = dict(_membre(db))
        texte = R.message_whatsapp(m, 0, "https://x.ma/r")
        assert "Aucun marché" in texte and "https://x.ma/r" not in texte

    def test_le_prenom_est_utilise(self, db):
        m = dict(_membre(db))
        assert R.message_whatsapp(m, 2, "https://x.ma/r").startswith("Bonjour Ahmed,")


class TestPageDuMembre:
    def test_elle_s_ouvre_sans_connexion(self, client, db):
        """Le destinataire lit sur un téléphone où il n'est pas connecté."""
        m = _membre(db)
        _marche(db, "t1")
        r = client.get(f"/recap/{R.jeton(m['id'])}")
        assert r.status_code == 200 and "t1" in r.text

    def test_un_lien_falsifie_donne_404(self, client, db):
        _membre(db)
        assert client.get("/recap/1-2026-10-01-zzzzzzzzzzzz").status_code == 404

    def test_elle_n_est_pas_indexable(self, client, db):
        m = _membre(db)
        assert "noindex" in client.get(f"/recap/{R.jeton(m['id'])}").text


class TestListeDAdministration:
    def test_chaque_membre_a_son_lien_et_son_message(self, db):
        _membre(db, email="a@example.com")
        _membre(db, email="b@example.com")
        lignes = R.membres_a_prevenir()
        assert len(lignes) == 2
        for l in lignes:
            assert l["lien"].startswith("http") and "/recap/" in l["lien"]
            assert l["message"]

    def test_les_membres_fournis_passent_devant(self, db):
        # On commence par ceux qui ont de quoi lire.
        _membre(db, email="vide@example.com", secteurs='["S930"]')
        _membre(db, email="plein@example.com", secteurs='["T101"]')
        _marche(db, "t1", secteur="T101")
        lignes = R.membres_a_prevenir()
        assert lignes[0]["membre"]["email"] == "plein@example.com"
        assert lignes[0]["nombre"] == 1 and lignes[-1]["nombre"] == 0

    def test_la_page_est_reservee_a_l_administration(self, client):
        r = client.get("/admin/recap", follow_redirects=False)
        assert r.status_code in (302, 404)
