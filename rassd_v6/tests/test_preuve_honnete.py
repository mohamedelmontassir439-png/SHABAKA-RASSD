"""La page d'accueil ne doit affirmer que ce qui est vrai.

Elle portait trois témoignages de clients — noms, villes, citations, cinq
étoiles — alors que la base ne comptait aucun abonné. Relevé le 30/09/2026.
Un prospect du BTP casablancais connaît son milieu: une seule question sur
l'identité du témoin suffit à ruiner la crédibilité de tout le reste.
"""
import re

import pytest

from app.core import i18n


class TestAucunTemoignageInvente:
    @pytest.mark.parametrize("nom", ["Benali", "Tahiri", "Alaoui"])
    def test_les_noms_inventes_ont_disparu(self, nom):
        page = open("templates/landing.html", encoding="utf-8").read()
        assert nom not in page

    def test_aucune_note_attribuee_a_la_plateforme(self):
        """Des étoiles au-dessus d'un nom sont une note inventée.

        Celles qui restent sur la page illustrent la fonction d'évaluation
        entre membres de la place de marché: elles ne notent pas la
        plateforme et ne sont rattachées à personne. La distinction tient à
        ce voisinage, c'est donc lui qu'on vérifie.
        """
        page = open("templates/landing.html", encoding="utf-8").read()
        for bloc in page.split("★★★")[:-1]:
            queue = bloc[-400:]
            assert "proof-author" not in queue, "étoiles rattachées à un témoin"
            assert "proof-card" not in queue, "étoiles dans le bloc de preuve"

    def test_aucune_cle_de_temoignage_ne_subsiste(self):
        restantes = [k for k in i18n.T
                     if re.match(r"proof[123]_(text|sector)$", k)]
        assert restantes == []


class TestChiffresAffiches:
    def test_la_page_lit_des_compteurs_reels(self):
        page = open("templates/landing.html", encoding="utf-8").read()
        for champ in ("stats.tenders", "stats.resultats",
                      "stats.secteurs_actifs", "stats.today"):
            assert champ in page, champ

    def test_le_nombre_de_membres_n_est_pas_exhibe(self):
        # Quatre comptes dont trois de test: le chiffre dessert la vente et
        # dira toujours la vérité, même quand elle est mauvaise.
        page = open("templates/landing.html", encoding="utf-8").read()
        assert "stats.members" not in page

    def test_les_legendes_existent_en_francais_et_en_arabe(self):
        for k in ("proof_n1", "proof_n2", "proof_n3", "proof_n4"):
            assert i18n.T[k]["fr"].strip()
            assert i18n.T[k]["ar"].strip()
