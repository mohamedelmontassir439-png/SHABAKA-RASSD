"""Les pièces jointes ne doivent jamais faire sortir le membre du domaine.

La route redirigeait vers l'agrégateur: le navigateur quittait la
plateforme, affichait l'adresse de la source dans sa barre, et le
téléchargement se faisait ailleurs. Un abonné découvrait ainsi d'où
viennent les données — et n'avait plus besoin de l'abonnement.
"""
from datetime import date, datetime, timedelta

import pytest

from app.services import pieces


def _membre(db, email="p@example.com"):
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
               ("Ahmed", email, "free", "TRIAL",
                (date.today() + timedelta(days=5)).strftime("%Y-%m-%d"),
                "x", "jeton-piece", 1, '["T101"]', 1))
    db.commit()
    return "jeton-piece"


def _resultat(db, rid="r1", pv="https://global-marches.com/downoald-pv/PV-1774"):
    db.execute("""INSERT INTO tender_results(id,objet,acheteur,adjudicataire,
                  scraped_at,type_procedure,dao_url,pv_url)
                  VALUES(?,?,?,?,?,?,?,?)""",
               (rid, "Travaux d'entretien du réseau d'eau", "COMMUNE", "STE X",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "marche",
                "https://global-marches.com/downoaldcps/1501084", pv))
    db.commit()


class TestNommageDesFichiers:
    """« downoald-pv » ne dit rien une fois dans le dossier Téléchargements."""

    def test_le_nom_decrit_le_marche(self):
        nom = pieces.nom_fichier("Travaux d'entretien du réseau d'eau potable", "pv")
        assert nom.startswith("PV-") and nom.endswith(".pdf")
        assert "entretien" in nom

    def test_le_genre_prefixe_le_nom(self):
        assert pieces.nom_fichier("Achat", "dao").startswith("DAO-")
        assert pieces.nom_fichier("Achat", "pv").startswith("PV-")

    @pytest.mark.parametrize("objet", [
        "Travaux à Figuig — réseau d'eau potable",
        "ÉTUDE ** TECHNIQUE // 2026",
        "Marché n°71/26/S (lot 3)",
    ])
    def test_le_nom_reste_en_ascii(self, objet):
        """Content-Disposition ne transporte sûrement que de l'ASCII.

        Un accent mal encodé donne un nom illisible, ou un téléchargement
        refusé selon le navigateur.
        """
        nom = pieces.nom_fichier(objet, "pv")
        assert nom.isascii(), nom
        assert " " not in nom

    def test_un_objet_vide_ne_casse_rien(self):
        assert pieces.nom_fichier("", "pv") == "PV-document.pdf"

    def test_l_extension_suit_le_type_reel(self):
        assert pieces.nom_fichier("Achat", "dao", "zip").endswith(".zip")


class TestRouteInterne:
    def test_la_piece_est_servie_par_la_plateforme(self, client, db, monkeypatch):
        jeton = _membre(db)
        _resultat(db)
        monkeypatch.setattr(pieces, "recuperer",
                            lambda url: (b"%PDF-1.4 contenu", "application/pdf", "pdf"))
        client.cookies.set("_session", jeton)
        r = client.get("/resultats/r1/pv")
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")
        assert "attachment" in r.headers["content-disposition"]
        assert "PV-" in r.headers["content-disposition"]

    def test_aucune_redirection_vers_la_source(self, client, db, monkeypatch):
        jeton = _membre(db)
        _resultat(db)
        monkeypatch.setattr(pieces, "recuperer",
                            lambda url: (b"%PDF-1.4", "application/pdf", "pdf"))
        client.cookies.set("_session", jeton)
        r = client.get("/resultats/r1/pv", follow_redirects=False)
        assert r.status_code == 200
        assert "global-marches" not in str(r.headers)

    def test_source_muette_on_le_dit(self, client, db, monkeypatch):
        # Ni fichier vide nommé .pdf, ni repli vers la source.
        jeton = _membre(db)
        _resultat(db)
        monkeypatch.setattr(pieces, "recuperer", lambda url: (None, "", ""))
        client.cookies.set("_session", jeton)
        r = client.get("/resultats/r1/pv", follow_redirects=False)
        assert r.status_code == 302
        assert "global-marches" not in r.headers["location"]
        assert "indisponible" in r.headers["location"]

    def test_piece_absente_renvoie_a_la_liste(self, client, db):
        jeton = _membre(db)
        _resultat(db, "r2", pv="")
        client.cookies.set("_session", jeton)
        r = client.get("/resultats/r2/pv", follow_redirects=False)
        assert r.status_code == 302 and "/resultats" in r.headers["location"]

    def test_genre_inconnu_rejete(self, client, db):
        jeton = _membre(db)
        _resultat(db)
        client.cookies.set("_session", jeton)
        r = client.get("/resultats/r1/facture", follow_redirects=False)
        assert r.status_code == 302

    def test_sans_abonnement_pas_de_piece(self, client, db):
        r = client.get("/resultats/r1/pv", follow_redirects=False)
        assert r.status_code == 302 and "login" in r.headers["location"]


class TestGardeFousDuTelechargement:
    def test_une_page_html_n_est_pas_servie_comme_un_pdf(self, monkeypatch):
        """Session expirée: la source renvoie une page, pas un fichier."""
        class FausseReponse:
            headers = {"Content-Type": "text/html; charset=utf-8"}
            content = b"<!DOCTYPE html><html>Connexion</html>"
            def raise_for_status(self): pass

        class FausseSession:
            def get(self, *a, **k): return FausseReponse()

        monkeypatch.setattr(pieces, "_ouvrir_session", lambda: FausseSession())
        contenu, type_c, ext = pieces.recuperer("https://global-marches.com/x")
        assert contenu is None

    def test_sans_session_rien_n_est_servi(self, monkeypatch):
        monkeypatch.setattr(pieces, "_ouvrir_session", lambda: None)
        assert pieces.recuperer("https://global-marches.com/x")[0] is None

    def test_url_vide_sans_effet(self):
        assert pieces.recuperer("")[0] is None
