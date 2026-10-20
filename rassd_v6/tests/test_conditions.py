# -*- coding: utf-8 -*-
"""Les conditions d'un appel d'offres, lues dans l'avis du portail.

Le texte d'essai reprend mot pour mot la forme d'une description stockée:
« Référence » sans deux-points, les « @@@@ » du portail, la ville répétée,
le sous-champ « Date et heure » resté vide.
"""
import os

import pytest

from app.core.conditions import cartes, conditions_avis, contact_detaille

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AVIS = (
    "Date et heure limite de remise des plis : 11/11/2026 10:00 "
    "Référence 81/2026/DR9 Objet : Renforcement de l'AEP du centre "
    "Acheteur public : ONEE - Branche Eau Type d'annonce : Avis de consultation "
    "Procédure : Appel d'offres ouvert | Sur offre de prix "
    "Catégorie principale : Travaux Allotissement : - "
    "Lieu d'exécution : TAOURIRT TAOURIRT "
    "Estimation (en Dhs TTC) * : 1 200 000,00 "
    "Réservé à la TPE et PME installées au Maroc, jeunes entreprises innovantes, "
    "Coopératives et auto-entrepreneurs * : Oui @@@@ "
    "Domaines d'activité : Travaux / Hydraulique "
    "Adresse de retrait des dossiers : www.marchespublics.gov.ma "
    "Adresse de dépôt des offres : www.marchespublics.gov.ma. "
    "Lieu d'ouverture des plis : Direction Régionale, Oujda "
    "Prix d'acquisition des plans : 0,00 MAD "
    "Caution provisoire : 14 000,00 MAD "
    "Qualifications : Secteur A / Classe 4 Agréments : "
    "Prospectus, notices ou autres documents : Date et heure limite : "
    "Réunion : Date et heure : "
    "Visites des lieux : 29/10/2026 10:00 , siège de la commune "
    "Variante : Non "
    "Contact Administratif : Fadoua FERRASSI fferrasi@onee.ma +212539940208 +212539945258 "
    "Vous ne pouvez pas signer un document car le serveur n'est pas accessible."
)


class TestLecture:
    def test_les_champs(self):
        c = conditions_avis(AVIS)
        assert c["limite"] == "11/11/2026 10:00"
        assert c["reference"] == "81/2026/DR9"
        assert c["caution"] == "14 000,00 MAD"
        assert c["qualifications"] == "Secteur A / Classe 4"
        assert c["visite"].startswith("29/10/2026 10:00")
        assert c["variante"] == "Non"

    def test_la_barre_du_portail_devient_un_point(self):
        assert conditions_avis(AVIS)["procedure"] == "Appel d'offres ouvert · Sur offre de prix"

    def test_la_ville_repetee_une_fois(self):
        assert conditions_avis(AVIS)["lieu"] == "TAOURIRT"

    def test_un_sous_champ_vide_ne_fait_pas_une_case(self):
        """« Réunion : Date et heure : » veut dire qu'il n'y en a pas."""
        c = conditions_avis(AVIS)
        assert "reunion" not in c and "echantillons" not in c and "agrements" not in c

    def test_le_bloc_de_signature_est_ignore(self):
        assert "signer" not in conditions_avis(AVIS)["contact"]

    @pytest.mark.parametrize("texte", ["", None, "Bon de commande: 50 chaises"])
    def test_rien_hors_d_un_avis(self, texte):
        assert conditions_avis(texte) == {}
        assert cartes(conditions_avis(texte)) == []


class TestCases:
    def _cles(self, texte=AVIS):
        return {k: (v, exige) for k, v, _, exige in cartes(conditions_avis(texte))}

    def test_les_exigences_sont_signalees(self):
        c = self._cles()
        for exigence in ("cond_limite", "cond_reserve", "cond_caution",
                         "cond_qualification", "cond_visite"):
            assert c[exigence][1] is True, exigence

    def test_valeurs_traduites(self):
        c = self._cles()
        assert c["cond_reserve"][0] == "oui"
        assert c["cond_variante"][0] == "non"
        assert c["cond_depot"][0] == "electronique"
        assert c["cond_plans"][0] == "gratuit"

    def test_caution_nulle_dite_aucune(self):
        c = self._cles(AVIS.replace("14 000,00 MAD", "0,00 MAD"))
        assert c["cond_caution"] == ("aucune", False)

    def test_marche_en_lots_ne_pretend_pas_aucune_caution(self):
        """En lots, le portail laisse la caution générale vide: elle est
        dans le tableau des lots. Dire « aucune » ferait perdre le marché."""
        texte = (AVIS.replace("Allotissement : -", "Allotissement : 4 Lots")
                 .replace("14 000,00 MAD", "").replace("Secteur A / Classe 4", ""))
        c = self._cles(texte)
        assert c["cond_lots"][0] == "4 Lots"
        assert c["cond_caution"] == ("par_lot", True)
        assert "cond_agrement" not in c

    def test_l_ordre_suit_les_questions_du_soumissionnaire(self):
        ordre = [k for k, *_ in cartes(conditions_avis(AVIS))]
        assert ordre[0] == "cond_limite" and ordre[-1] == "cond_contact"

    def test_chaque_libelle_existe_dans_les_deux_langues(self):
        from app.core.i18n import tr
        cles = {"cond_titre", "cond_aide", "cond_exige", "cond_source", "cond_lots",
                "cond_lots_aide", "cond_reunion", "cond_echantillons",
                "cond_echantillons_aide", "cond_agrement", "cond_agrement_aide"}
        for k, v, aide, _ in cartes(conditions_avis(AVIS)):
            cles |= {k} | ({aide} if aide else set())
        for mot in ("oui", "non", "aucune", "aucun", "electronique", "gratuit", "par_lot"):
            cles.add("cond_v_" + mot)
        for cle in cles:
            for langue in ("fr", "ar"):
                assert tr(cle, langue) not in ("", cle), f"{cle} manquant en {langue}"


class TestContact:
    def test_trois_morceaux(self):
        c = contact_detaille("Fadoua FERRASSI fferrasi@onee.ma +212539940208 +212539945258")
        assert c == {"nom": "Fadoua FERRASSI", "email": "fferrasi@onee.ma",
                     "tel": "+212539940208"}

    def test_numero_avec_espaces(self):
        c = contact_detaille("Najat MEZIANE najatm4@gmail.com 06 60 13 44 64")
        assert c["nom"] == "Najat MEZIANE" and c["tel"] == "0660134464"


class TestFiche:
    def test_le_gabarit_pose_les_cases(self):
        with open(os.path.join(RACINE, "templates", "detail.html"), encoding="utf-8") as f:
            g = f.read()
        assert "cartes_conditions(t.description)" in g
        # Avant l'encadré pédagogique: les faits d'abord, l'explication ensuite.
        assert g.index('class="cond"') < g.index('class="lire"')

    def test_les_fonctions_sont_offertes_au_gabarit(self):
        import main
        g = main.templates.env.globals
        assert g["cartes_conditions"](AVIS)[0][0] == "cond_limite"
        assert g["contact_avis"]("A B a@b.ma 0612345678")["tel"] == "0612345678"

    def test_rendu_reel(self):
        import main
        tpl = main.templates.env.from_string(
            "{% for cle, valeur, aide, exige in cartes_conditions(d) %}"
            "{{ tr(cle) }}={{ valeur }};{% endfor %}")
        html = tpl.render(d=AVIS, tr=lambda k: k)
        assert "cond_caution=14 000,00 MAD" in html
