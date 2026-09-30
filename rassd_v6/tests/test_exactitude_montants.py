"""Une case vide vaut mieux qu'un chiffre faux.

La plateforme se vend sur l'exactitude de ses données: un entrepreneur qui
lit « 18,00 MAD » en face de travaux de charpente ne revient pas. Relevé en
production le 30/09/2026 sur po_325001, dont l'objet contenait « Dimensions
unifiées : 18,00 m × 12,00 m ».
"""
from app.services import private_scraper as ps


def _ligne(*cellules) -> str:
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cellules) + "</tr>"


class TestBudgetDesAvis:
    def test_budget_lu_dans_sa_cellule(self):
        # Caution puis budget: on retient le plus élevé des deux.
        html = _ligne("réf", "objet", "acheteur", "12.000,00 400.000,00")
        assert ps._parse_budget(html) == "400.000,00 MAD"

    def test_ordre_des_deux_montants_indifferent(self):
        html = _ligne("réf", "objet", "acheteur", "400.000,00 12.000,00")
        assert ps._parse_budget(html) == "400.000,00 MAD"

    def test_cellule_sans_montant_reste_vide(self):
        html = _ligne("réf", "objet", "acheteur", "------")
        assert ps._parse_budget(html) == ""

    def test_une_dimension_dans_l_objet_n_est_pas_un_budget(self):
        """Le cas exact vu en production."""
        objet = "Travaux de rénovation d'une charpente (Dimensions : 18,00 m × 12,00 m)"
        html = _ligne("réf", objet, "acheteur", "------")
        assert ps._parse_budget(html) == "", "aucun chiffre ne doit sortir du texte libre"

    def test_structure_inattendue_ne_produit_rien(self):
        # Moins de colonnes que prévu: le tableau a changé. Se taire plutôt
        # que d'aller chercher un nombre ailleurs dans la ligne.
        assert ps._parse_budget(_ligne("réf", "9.999,00")) == ""

    def test_montant_implausible_ecarte(self):
        # Aucun achat public ne se chiffre à quelques centaines de dirhams:
        # un tel nombre vient du texte, pas d'un budget.
        assert ps._parse_budget(_ligne("a", "b", "c", "750,00")) == ""

    def test_montant_plausible_conserve(self):
        assert ps._parse_budget(_ligne("a", "b", "c", "1.500,00")) == "1.500,00 MAD"
