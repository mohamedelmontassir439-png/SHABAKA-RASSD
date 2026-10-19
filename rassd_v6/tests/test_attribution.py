# -*- coding: utf-8 -*-
"""Un marché attribué, et un marché qui ne l'a pas été.

Le portail inscrit dans la colonne « attributaire » le résultat de la
procédure, quel qu'il soit: « Infructueux » quand aucune offre n'a convenu,
« Annulé » quand la consultation a été retirée. Ce ne sont pas des
entreprises.

Mesure du 19/10/2026 sur 522 résultats: **157, soit 30 %**. La page des
résultats les affichait en vert sous l'intitulé « Attributaire », et la
sous-traitance proposait d'aller démarcher une société nommée « Annulé ».

Un filtre existait déjà — mais il ne servait qu'à la page des prospects de
l'administration, là où le fondateur cherche qui appeler. Les membres, eux,
voyaient tout.
"""
import pytest

from app.core.attribution import est_attribue, issue


class TestLIssueDUneProcedure:
    @pytest.mark.parametrize("valeur,attendu", [
        ("Infructueux", "infructueux"),
        ("INFRUCTUEUX", "infructueux"),
        ("Déclaré infructueux", "infructueux"),
        ("Annulé", "annule"),
        ("annule", "annule"),
        ("sans suite", "sans_suite"),
        ("Non attribué", "sans_suite"),
    ])
    def test_la_mention_est_reconnue_quelle_que_soit_son_ecriture(self, valeur, attendu):
        """Les avis sont saisis en capitales, sans accents: « ANNULE »,
        « Annulé » et « annule » sont le même mot."""
        assert issue(valeur) == attendu
        assert not est_attribue(valeur)

    @pytest.mark.parametrize("nom", [
        "SOCIETE UBAC SARL AU", "2SBT", "GROUPEMENT CONJOINT GIMATIC SARL",
    ])
    def test_un_vrai_nom_reste_une_attribution(self, nom):
        assert est_attribue(nom) and issue(nom) == ""

    @pytest.mark.parametrize("nom", ["NC", "—", "x", "", "   "])
    def test_ce_qui_ne_designe_personne_nest_pas_une_attribution(self, nom):
        """Trois lettres ou moins ne nomment aucune société — on a vu « NC »
        et « — » dans cette colonne."""
        assert not est_attribue(nom)


class TestLaSousTraitance:
    def test_les_pistes_ecartent_les_procedures_sans_preneur(self, db):
        """Proposer de démarcher « Annulé » décrédibilise la page entière."""
        import json
        from app.services.soustraitance import opportunites_pour
        db.execute("""INSERT INTO tender_results(id,objet,acheteur,secteur,region,
                      montant,montant_num,adjudicataire,adjudicataire_norm,scraped_at)
                      VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))""",
                   ("r_annule", "Travaux divers", "COMMUNE", "T101", "Rabat",
                    "5.000.000,00", 5000000, "Annulé", ""))
        db.execute("""INSERT INTO tender_results(id,objet,acheteur,secteur,region,
                      montant,montant_num,adjudicataire,adjudicataire_norm,scraped_at)
                      VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))""",
                   ("r_vrai", "Travaux divers", "COMMUNE", "T101", "Rabat",
                    "5.000.000,00", 5000000, "SOCIETE UBAC SARL AU", "ubac"))
        db.commit()
        noms = [p["adjudicataire"] for p in opportunites_pour(
            {"secteurs": json.dumps(["T101"]), "regions": "[]", "company": ""},
            limite=50)]
        assert "SOCIETE UBAC SARL AU" in noms
        assert "Annulé" not in noms


class TestLesLibelles:
    def test_un_resultat_affiche_un_montant_attribue_pas_une_estimation(self):
        """Les deux pages partageaient le libellé « Montant ». En le
        renommant « Estimation (TTC) » pour la fiche d'un avis — où c'est
        exact — la page des résultats l'a suivi, où c'est faux: le montant
        y est celui auquel le marché a été attribué."""
        import os, re
        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(racine, "templates", "resultats.html"), encoding="utf-8") as f:
            page = f.read()
        assert "tr('res_montant')" in page
        assert "tr('detail_amount')" not in page

    def test_le_telephone_dune_piste_se_lit_et_se_compose(self):
        """Il s'affichait « 212661088052 » et se composait sans le « + »,
        ce qu'un téléphone ne sait pas toujours traiter."""
        import os
        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(racine, "templates", "subtraitance.html"), encoding="utf-8") as f:
            page = f.read()
        assert 'href="tel:+{{ p.contact_phone' in page
        assert "tel(p.contact_phone)" in page
