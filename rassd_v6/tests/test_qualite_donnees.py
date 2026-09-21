"""Qualité des données affichées aux membres.

Deux défauts constatés en production sur la sauvegarde du 21/09/2026:
94 % des marchés « actifs » avaient une date limite dépassée, et les
9 090 fiches du portail public n'avaient ni acheteur ni région — la fiche
n'est pas un tableau HTML, ce que supposait l'ancien extracteur.
"""
from datetime import date, datetime, timedelta

import pytest

import main
from app.services import scraper as sc

# Extrait fidèle d'une fiche réelle du portail (structure « libellé valeur »).
FICHE = """<html><body>
<h1>#BC14/2026/DPA/IFRANE</h1>
<p>Détails de l'avis d'achat #BC14/2026/DPA/IFRANE Retour à la liste
Objet ENTRETIEN ET REPARATION DES ORDINATEURS DE LA DIRECTION PROVINCIALE.
Détails Acheteur public DIRECTEUR PROVINCIAL D'AGRICULTURE IFRANE
Date mise en ligne 21/09/2026 16:08
Date limite de réception des devis {limite} 16:30
Lieu d'exécution IFRANE
Catégorie principale Services
Nature de prestation Entretien et maintenance des équipements informatique
Pièces jointes AVIS.zip Articles Quantité 25 TVA (%) 20</p>
</body></html>"""


def _fiche(jours: int = 5) -> str:
    limite = (date.today() + timedelta(days=jours)).strftime("%d/%m/%Y")
    return FICHE.replace("{limite}", limite) + " " * 1600


class TestExtractionPortail:
    def test_acheteur_et_region_recuperes(self):
        t = sc.parse_page(_fiche(), "383684")
        assert t is not None
        assert t["acheteur"] == "DIRECTEUR PROVINCIAL D'AGRICULTURE IFRANE"
        assert t["region"] == "Ifrane", "la ville est normalisée, pas criée"

    def test_classe_en_bon_de_commande(self):
        # Le portail n'expose ici que ses avis d'achat sur bon de commande.
        assert sc.parse_page(_fiche(), "383684")["type_procedure"] == "bon_commande"

    def test_pas_de_faux_montant(self):
        # La page ne contient qu'une quantité (25) et un taux de TVA (20).
        assert sc.parse_page(_fiche(), "383684")["montant"] == ""

    def test_montant_retenu_s_il_est_annonce(self):
        html = _fiche().replace("Catégorie principale",
                                "Montant estimé 450 000,00 MAD Catégorie principale")
        assert "450 000,00" in sc.parse_page(html, "1")["montant"]

    def test_secteur_classe_avec_la_nature_de_prestation(self):
        t = sc.parse_page(_fiche(), "383684")
        assert t["secteur"], "un secteur doit être attribué"

    def test_champ_absent_reste_vide(self):
        html = _fiche().replace("Lieu d'exécution IFRANE", "")
        assert sc.parse_page(html, "1")["region"] == ""


class TestCloture:
    def _marche(self, db, tid, limite, statut="actif"):
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,scraped_at,date_limite,
                      type_offre,type_procedure) VALUES(?,?,?,?,?,?,?,?)""",
                   (tid, "Travaux", "T101", statut, "2026-09-01 08:00:00", limite,
                    "Public", "marche"))
        db.commit()

    def test_les_marches_depasses_sont_clotures(self, db):
        hier = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")
        demain = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")
        self._marche(db, "t_passe", hier)
        self._marche(db, "t_ouvert", demain)

        expires, actifs = main.expire_tenders()

        assert expires == 1 and actifs == 1
        statut = lambda t: db.execute("SELECT statut FROM tenders WHERE id=?", (t,)).fetchone()[0]
        assert statut("t_passe") == "expire"
        assert statut("t_ouvert") == "actif"

    def test_gros_volume_cloture_en_une_fois(self, db):
        # Plus de 999 identifiants: un IN (...) unique dépasserait la limite
        # de paramètres de SQLite et ne clôturerait rien du tout.
        hier = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")
        for i in range(1200):
            self._marche(db, f"t_{i}", hier)
        expires, actifs = main.expire_tenders()
        assert expires == 1200 and actifs == 0

    def test_date_illisible_ne_fait_pas_planter(self, db):
        self._marche(db, "t_bizarre", "bientôt")
        expires, actifs = main.expire_tenders()
        assert expires == 0 and actifs == 1

    def test_un_marche_deja_clos_n_est_pas_recompte(self, db):
        hier = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")
        self._marche(db, "t_deja", hier, statut="expire")
        assert main.expire_tenders()[0] == 0


class TestPagesSeparees:
    def test_les_pages_suivent_le_type_de_procedure(self, db, client):
        """Un bon de commande ne doit pas apparaître dans la page Marchés."""
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,scraped_at,date_limite,
                      type_offre,type_procedure,source)
                      VALUES(?,?,?,?,?,?,?,?,?)""",
                   ("bdc_1", "ACHAT DE CLIMATISEURS PORTAIL", "P814", "actif",
                    "2026-09-21 08:00:00",
                    (date.today() + timedelta(days=5)).strftime("%d/%m/%Y"),
                    "Public", "bon_commande", "marchespublics"))
        db.commit()

        client.get("/register")
        client.post("/register", data={
            "email": "q@example.com", "pw": "MotDePasse1!", "pw2": "MotDePasse1!",
            "nom": "Q", "csrf_token": client.cookies.get("_csrf")})
        db.execute("UPDATE members SET email_verified=1 WHERE email=?", ("q@example.com",))
        db.commit()

        assert "ACHAT DE CLIMATISEURS PORTAIL" not in client.get("/tenders").text
        assert "ACHAT DE CLIMATISEURS PORTAIL" in client.get("/bons-de-commande").text
