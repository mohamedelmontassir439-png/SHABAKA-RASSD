"""La nature de l'acheteur, et non la provenance de l'avis.

La plateforme ne connaissait que « Public » et « Privé », hérités de la
source qui publiait: ce qui venait du portail national était public, le
reste privé. Un même type d'organisme se retrouvait des deux côtés. Mesuré
le 01/10/2026 sur les marchés actifs: cent soixante-sept avis
d'établissements publics, dont cent dix classés « Public » et cinquante-sept
« Privé ».
"""
from datetime import date, datetime, timedelta

import pytest

from app.core import organismes as O


class TestParaPublic:
    """Les EEP marocains: leur propre famille, leurs propres règles d'achat."""

    @pytest.mark.parametrize("acheteur", [
        "ADM Autoroutes du Maroc",
        "ONEE Branche Eau",
        "ONCF Direction des achats",
        "CNSS Agence de Casablanca",
        "Marsa Maroc",
        "Societe Régionale Multiservices Oriental",
        "Agence urbaine de Meknès",
        "Agence du bassin hydraulique du Sebou",
        "AMDIE Agence marocaine de développement des investissements",
        "Academies regionales ACADEMIE REGIONALE D'EDUCATION",
        "Centre Hospitalier Provincial de Jerada",
        "Al Omrane Tanger",
        "Régie autonome de distribution d'eau de Fès",
        "Université Mohammed V",
        "OFPPT Direction régionale",
    ])
    def test_reconnus(self, acheteur):
        assert O.categorie(acheteur, "Public") == O.PARA, acheteur

    def test_le_pluriel_du_portail_est_compris(self):
        # Le portail écrit « Academies regionales », pas « académie régionale ».
        assert O.est_para_public("Academies regionales DIRECTION PROVINCIALE")


class TestEtat:
    @pytest.mark.parametrize("acheteur", [
        "Commune rurale de TANSIFTE",
        "Ministère de la Santé",
        "Province de Taza",
        "Préfecture de Tanger-Assilah",
        "Tribunal de première instance",
        "Gouverneur de Jerada",
    ])
    def test_reconnus(self, acheteur):
        assert O.categorie(acheteur, "Public") == O.ETAT, acheteur

    def test_une_administration_reste_l_etat_meme_publiee_comme_privee(self):
        """La provenance ne dit rien de la nature de l'acheteur.

        « Administration des Douanes et Impôts Indirects » arrivait classée
        « Privé » parce que l'avis venait de l'agrégateur.
        """
        assert O.categorie("Administration des Douanes et Impots Indirects",
                           "Privé") == O.ETAT


class TestPrive:
    @pytest.mark.parametrize("acheteur", [
        "SARL BATIMENT MODERNE",
        "Societe anonyme Casa Transport",
        "Groupe industriel du Nord",
    ])
    def test_une_entreprise_inconnue_suit_la_provenance(self, acheteur):
        assert O.categorie(acheteur, "Privé") == O.PRIVE

    def test_sans_indication_on_ne_devine_pas_prive(self):
        # En l'absence de provenance, l'État est le pari le plus sûr: la
        # quasi-totalité des avis collectés sont des marchés publics.
        assert O.categorie("Organisme sans nom reconnaissable", "") == O.ETAT


class TestPrudence:
    """Dans le doute, ne pas étiqueter à tort."""

    def test_un_sigle_ne_se_declenche_pas_dans_un_mot(self):
        # « ADM » ne doit pas s'activer sur « ADMINISTRATION », ni « SIE »
        # sur « SIEGE ».
        assert not O.est_para_public("ADMINISTRATION CENTRALE")
        assert not O.est_para_public("SIEGE SOCIAL DE LA SOCIETE")

    @pytest.mark.parametrize("acheteur", ["", None, "   "])
    def test_un_acheteur_vide_ne_casse_rien(self, acheteur):
        assert not O.est_para_public(acheteur)
        assert O.categorie(acheteur, "Public") == O.ETAT


def _membre(db):
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
               ("Ahmed", "o@example.com", "pro", "ACTIVE",
                (date.today() + timedelta(days=90)).strftime("%Y-%m-%d"),
                "x", "jeton-organismes", 1, '["T101"]', 1))
    db.commit()
    return "jeton-organismes"


def _marche(db, tid, acheteur, organisme):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,scraped_at,
                  date_limite,type_offre,type_procedure,organisme)
                  VALUES(?,?,?,?,'actif',?,?,?,?,?)""",
               (tid, f"TRAVAUX {tid}", acheteur, "T101",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                (date.today() + timedelta(days=20)).strftime("%d/%m/%Y"),
                "Public", "marche", organisme))
    db.commit()


class TestFiltre:
    def test_le_membre_peut_isoler_le_para_public(self, client, db):
        client.cookies.set("_session", _membre(db))
        _marche(db, "t_adm", "ADM Autoroutes du Maroc", "semi_public")
        _marche(db, "t_com", "Commune rurale de Tansifte", "public")
        html = client.get("/tenders?t=semi_public").text
        assert "t_adm" in html and "t_com" not in html

    def test_les_trois_categories_sont_proposees(self, client, db):
        client.cookies.set("_session", _membre(db))
        html = client.get("/tenders").text
        for valeur in ("public", "semi_public", "prive"):
            assert f'value="{valeur}"' in html


class TestLeSemiPublicEstAnnonce:
    """Dire ce qu'on couvre, partout où on le dit.

    Le semi-public pèse dix pour cent des marchés collectés. Le nommer
    seulement dans un filtre, en continuant d'annoncer « publics et privés »
    sur la page d'accueil, les tarifs, les pages de référencement et les
    documents remis aux clients, revenait à cacher un dixième de l'offre à
    un prospect — et à sous-vendre la plateforme.
    """

    FICHIERS = [
        "templates/landing.html", "templates/base_public.html",
        "templates/base.html", "templates/document.html",
        "templates/legal_mentions.html", "templates/legal_cgu.html",
        "templates/seo_index.html", "app/core/i18n.py", "app/core/marque.py",
    ]

    # Une formule complète contient la fautive: « semi-publics et privés »
    # contient « publics et privés », et « وشبه العمومية والخاصة » contient
    # « العمومية والخاصة ». On ne retient donc l'occurrence que si le
    # marqueur du semi-public ne la précède pas immédiatement.
    FAUTIVES = (
        ("publics et privés", ("semi-", "semi ")),
        ("publics & privés",  ("semi-", "semi ")),
        ("Public + Privé",    ("semi-", "semi ")),
        ("العمومية والخاصة",   ("وشبه ", "شبه ")),
    )

    @pytest.mark.parametrize("fichier", FICHIERS)
    def test_aucune_formule_n_oublie_le_semi_public(self, fichier):
        texte = open(fichier, encoding="utf-8").read()
        for fautive, marqueurs in self.FAUTIVES:
            depart = 0
            while True:
                i = texte.find(fautive, depart)
                if i < 0:
                    break
                avant = texte[max(0, i - 8):i]
                assert avant.endswith(marqueurs),                     f"{fichier}: « ...{texte[max(0, i-40):i+len(fautive)]} »"
                depart = i + 1

    @pytest.mark.parametrize("fichier", FICHIERS)
    def test_rien_n_est_dit_deux_fois(self, fichier):
        # Une passe de remplacement mal ordonnée avait produit
        # « semi-publics, semi-publics et privés ».
        texte = open(fichier, encoding="utf-8").read()
        for doublon in ("semi-publics, semi-publics", "semi-public, semi-public",
                        "شبه العمومية وشبه العمومية"):
            assert doublon not in texte, f"{fichier}: {doublon}"

    def test_l_en_tete_des_documents_le_porte(self):
        from app.core import marque
        assert "semi-public" in marque.entete_document(52)

    def test_les_deux_langues_sont_servies(self):
        from app.core import i18n
        assert "semi-public" in i18n.T["org_semi_public"]["fr"].lower()
        assert "شبه" in i18n.T["org_semi_public"]["ar"]
