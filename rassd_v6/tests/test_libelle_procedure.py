# -*- coding: utf-8 -*-
"""L'alerte nomme la procédure: marché, ou bon de commande.

Elle annonçait « Un nouveau marché » pour tout. Un bon de commande est une
procédure d'achat simplifiée, aux montants et aux délais tout autres: un
entrepreneur qui ouvre l'email en préparant un dossier de marché perd son
temps, et doute du reste.
"""
import pytest

from app.services.notifications import build_email, libelle_type


def _tender(procedure="marche"):
    return {"id": "t1", "objet": "SUR ELEVATION D'UN MUR DE CLOTURE",
            "acheteur": "Centre de Qualification Professionnelle Maritime",
            "secteur": "T101", "region": "Laâyoune", "montant": "120 000,00 MAD",
            "date_limite": "30/12/2026", "type_procedure": procedure}


class TestLibelle:
    def test_un_marche_sappelle_marche(self):
        assert libelle_type(_tender("marche")) == "marché"

    def test_un_bon_de_commande_sappelle_bon_de_commande(self):
        assert libelle_type(_tender("bon_commande")) == "bon de commande"

    def test_sans_procedure_on_suppose_un_marche(self):
        """C'est le défaut du schéma, et la procédure la plus fréquente."""
        assert libelle_type({}) == "marché"


class TestEmail:
    def test_le_corps_annonce_un_bon_de_commande(self):
        html = build_email(_tender("bon_commande"), "Ahmed")
        assert "Un nouveau bon de commande" in html
        assert "Un nouveau marché" not in html

    def test_le_corps_annonce_un_marche(self):
        html = build_email(_tender("marche"), "Ahmed")
        assert "Un nouveau marché" in html

    def test_le_bouton_suit_aussi(self):
        html = build_email(_tender("bon_commande"), "")
        assert "Voir le bon de commande" in html


class TestObjet:
    def test_lobjet_de_lalerte_nomme_la_procedure(self):
        """L'objet est tout ce qui se lit avant la décision d'ouvrir."""
        import inspect

        from app.services import notifications
        code = inspect.getsource(notifications.dispatch_notifications)
        assert "Nouveau {libelle_type(t)}" in code


class TestCanalRetire:
    def test_le_constructeur_telegram_a_disparu(self):
        """Plus aucun appelant depuis le retrait du canal: le garder
        laissait croire qu'un envoi partait encore."""
        from app.services import notifications
        assert not hasattr(notifications, "build_tg_message")
