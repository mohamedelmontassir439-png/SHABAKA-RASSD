"""Extraction du budget depuis la colonne « Caution/Budget » de la source.

Fixtures reproduisant la structure réelle du tableau (8 colonnes), relevée
sur la source le 08/09/2026 — aucun appel réseau ici.
"""
import pytest

from app.services.private_scraper import _parse_budget
from app.services.matching import parse_amount


def _row(cellule_montant: str) -> str:
    cells = ["1 Facebook", "71/26/S", "Organisme : ADM Objet : Inventaire",
             cellule_montant, "- bouznika", "30/09/2026 10:00", "", "S.E"]
    return "".join(f"<td>{c}</td>" for c in cells)


class TestParseBudget:
    def test_retient_le_budget_pas_la_caution(self):
        """La cellule contient caution puis budget: c'est le budget qui compte."""
        assert _parse_budget(_row("23.000,00 1.160.000,00")) == "1.160.000,00 MAD"

    @pytest.mark.parametrize("cellule,attendu", [
        ("127.000,00 6.393.600,00", "6.393.600,00 MAD"),
        ("2.700,00 135.000,00", "135.000,00 MAD"),
        ("40.980,86 4.098.086,04", "4.098.086,04 MAD"),
    ])
    def test_cas_reels(self, cellule, attendu):
        assert _parse_budget(_row(cellule)) == attendu

    def test_montant_non_publie(self):
        """'------' signifie non publié: on ne devine pas un chiffre."""
        assert _parse_budget(_row("------ ------")) == ""

    def test_cellule_vide(self):
        assert _parse_budget(_row("")) == ""

    def test_ignore_dates_et_references(self):
        """Une date (30/09/2026) ou une référence (71/26/S) n'est pas un montant."""
        assert _parse_budget(_row("------ ------")) == ""

    def test_montant_unique(self):
        assert _parse_budget(_row("250.000,00")) == "250.000,00 MAD"

    def test_le_budget_extrait_est_relisible_par_le_filtre(self):
        """Le montant stocké doit être exploitable par le filtre budget."""
        montant = _parse_budget(_row("23.000,00 1.160.000,00"))
        assert parse_amount(montant) == 1160000.0

    def test_structure_inattendue_ne_casse_pas(self):
        assert _parse_budget("<td>rien</td>") == ""
        assert _parse_budget("") == ""
