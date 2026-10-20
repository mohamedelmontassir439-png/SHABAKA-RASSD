# -*- coding: utf-8 -*-
"""La campagne publique: d'où vient chaque inscrit, et ce qu'on publie.

Une campagne sur cinq canaux sans suivi des sources, c'est cinq dépenses
dont on ne saura jamais laquelle a rapporté un abonné.
"""
from datetime import date, datetime, timedelta

import pytest

from app.core import canaux


def _marche(db, tid, secteur="T101", montant="1 200 000,00 MAD", jours=12,
            objet="CONSTRUCTION D'UNE ECOLE", acheteur="COMMUNE DE CASABLANCA"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,?,?,'Casablanca',?,'actif',?,?,'Public','marche')""",
               (tid, objet, acheteur, secteur, montant,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                (date.today() + timedelta(days=jours)).strftime("%d/%m/%Y")))
    db.commit()


def _inscription(client, **extra):
    base = {"email": "neuf@example.com", "pw": "MotDePasse1!", "pw2": "MotDePasse1!",
            "nom": "Ahmed", "phone": "0612345678", "company": "SIMAC",
            "secteurs_sel": ["T101"], "csrf_token": client.cookies.get("_csrf")}
    base.update(extra)
    return client.post("/register", data=base, follow_redirects=False)


class TestCanaux:
    @pytest.mark.parametrize("brut,attendu", [
        ("facebook", "facebook"), ("FB", "facebook"), ("lnkd.in", "linkedin"),
        ("qr", "affiche"), ("wa", "whatsapp"), ("xxx", ""), ("", ""),
        # Un canal déduit ne s'écrit pas dans un lien: on ne le prend pas.
        ("parrainage", ""), ("invitation", ""),
    ])
    def test_seuls_les_canaux_connus(self, brut, attendu):
        assert canaux.canal(brut) == attendu

    def test_le_nom_de_campagne_est_nettoye(self):
        assert canaux.campagne("S42-2026<script>") == "s42-2026script"

    def test_le_lien(self):
        assert canaux.lien("https://x.ma/", "linkedin", "/", "s42-2026") == \
            "https://x.ma/?src=linkedin&cmp=s42-2026"


class TestSuiviDesInscriptions:
    def _source(self, db, email="neuf@example.com"):
        return tuple(db.execute("SELECT source, source_campagne FROM members WHERE email=?",
                                (email,)).fetchone())

    def test_le_canal_du_lien_arrive_sur_la_fiche(self, client, db):
        client.get("/?src=facebook&cmp=s42-2026")
        client.get("/register")
        assert _inscription(client).status_code == 302
        assert self._source(db) == ("facebook", "s42-2026")

    def test_les_utm_des_regies_sont_compris(self, client, db):
        client.get("/?utm_source=ig&utm_campaign=Lancement")
        client.get("/register")
        _inscription(client)
        assert self._source(db) == ("instagram", "lancement")

    def test_le_premier_contact_garde_le_credit(self, client, db):
        client.get("/?src=linkedin")
        client.get("/?src=facebook")
        client.get("/register")
        _inscription(client)
        assert self._source(db)[0] == "linkedin"

    def test_sans_lien_c_est_direct(self, client, db):
        client.get("/register")
        _inscription(client)
        assert self._source(db)[0] == "direct"

    def test_un_canal_invente_est_ignore(self, client, db):
        client.get("/?src=nimportequoi")
        assert canaux.COOKIE not in client.cookies
        client.get("/register")
        _inscription(client)
        assert self._source(db)[0] == "direct"


class TestPublications:
    def test_elles_citent_des_marches_reels(self, db):
        from app.services.diffusion import publications
        _marche(db, "t1", "T101", "6.983.640,00 MAD", objet="ROUTE DE SETTAT")
        _marche(db, "t2", "F201", "470 400,00 MAD", objet="FOURNITURE DE MOBILIER")
        pubs = publications()
        assert {p["canal"] for p in pubs} >= {"facebook", "linkedin", "whatsapp", "instagram"}
        fb = next(p for p in pubs if p["canal"] == "facebook" and p["langue"] == "fr")
        assert "ROUTE DE SETTAT" in fb["texte"] and "6,9 millions de dirhams" in fb["texte"]
        assert "src=facebook" in fb["texte"], "le lien publié est suivi"

    def test_un_marche_qui_ferme_bientot_n_est_pas_cite(self, db):
        """La publication circule une semaine: citer un marché qui ferme dans
        deux jours, c'est montrer une porte fermée."""
        from app.services.diffusion import publications
        _marche(db, "t1", "T101", "9 000 000,00 MAD", jours=2, objet="BIENTOT FERME")
        _marche(db, "t2", "T101", "100 000,00 MAD", jours=20, objet="ENCORE OUVERT")
        textes = " ".join(p["texte"] for p in publications())
        assert "BIENTOT FERME" not in textes and "ENCORE OUVERT" in textes

    def test_une_estimation_aberrante_n_est_pas_citee(self, db):
        """« Gardiennage, 5,4 milliards »: une erreur de saisie de l'acheteur,
        qui ferait reprendre la publication en commentaire."""
        from app.services.diffusion import matiere
        _marche(db, "t1", "S901", "5 400 000 000,00 MAD", objet="GARDIENNAGE")
        _marche(db, "t2", "S901", "820 000,00 MAD", objet="NETTOYAGE")
        assert [m["objet"] for m in matiere()["vitrine"]] == ["NETTOYAGE"]

    def test_un_marche_par_secteur(self, db):
        from app.services.diffusion import matiere
        for i in range(4):
            _marche(db, f"b{i}", "T101", f"{i + 1} 000 000,00 MAD")
        _marche(db, "f1", "F201", "50 000,00 MAD")
        assert [m["secteur"] for m in matiere()["vitrine"]] == ["T101", "F201"]

    def test_le_pays_est_retire_de_la_ville(self, db):
        from app.services.diffusion import publications
        _marche(db, "t1")
        db.execute("UPDATE tenders SET region=\"Province d'Ifrane MAROC\"")
        db.commit()
        texte = publications()[0]["texte"]
        assert "Province d'Ifrane" in texte and "MAROC" not in texte

    def test_rien_a_publier_sans_marche(self, db):
        from app.services.diffusion import publications
        assert publications() == []

    def test_montant_lisible(self):
        from app.services.diffusion import montant_lisible
        assert montant_lisible(1_000_000) == "1 million de dirhams"
        assert montant_lisible(470_400) == "470 400 dirhams"
        assert montant_lisible(2_500_000, "ar") == "2,5 مليون درهم"


class TestPageAdmin:
    def test_le_bilan_compte_les_payants_par_canal(self, admin, db):
        db.execute("""INSERT INTO members(nom,email,plan,source,source_campagne,created_at)
                      VALUES('A','a@x.ma','monthly','facebook','s42-2026',?),
                            ('B','b@x.ma','free','facebook','',?),
                            ('C','c@x.ma','free','linkedin','',?)""",
                   (datetime.now().isoformat(),) * 3)
        db.commit()
        from app.services.diffusion import bilan_canaux
        b = {x["cle"]: x for x in bilan_canaux()}
        assert (b["facebook"]["inscrits"], b["facebook"]["payants"]) == (2, 1)
        assert bilan_canaux()[0]["cle"] == "facebook", "les payants d'abord"

    def test_la_page_s_ouvre(self, admin, db):
        _marche(db, "t1")
        r = admin.get("/admin/campagne")
        assert r.status_code == 200
        assert "Publications de la semaine" in r.text and "src=linkedin" in r.text

    def test_elle_est_reservee_a_l_admin(self, client, db):
        r = client.get("/admin/campagne", follow_redirects=False)
        assert r.status_code in (302, 303, 307, 404)
