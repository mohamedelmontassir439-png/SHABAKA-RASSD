"""Une panne de collecte ne doit pas ressembler à une journée calme.

Les quatre collecteurs n'annonçaient que le nombre de nouveautés. Une page
dont la structure change renvoie elle aussi zéro: « 0 nouveaux » s'écrivait
pareil dans les deux cas. Constaté le 30/09/2026 sur les résultats de bons
de commande — plusieurs cycles à zéro sans moyen de savoir si la source se
taisait ou si le collecteur était cassé.
"""
from datetime import datetime, timedelta

import pytest

from app.services import private_scraper as ps
from app.services import supervision as sup


class TestBilanDeCollecte:
    def _journal(self):
        lignes = []
        return lignes, lambda m: lignes.append(str(m))

    def test_journee_calme_reste_muette(self):
        lignes, log = self._journal()
        ps._bilan(log, "Résultats", nouveaux=0, trouves=40, analyses=40)
        assert "40 trouvés" in lignes[0]
        assert not [l for l in lignes if l.startswith("⚠")], "rien d'anormal"

    def test_page_vide_est_signalee(self):
        lignes, log = self._journal()
        ps._bilan(log, "Résultats", nouveaux=0, trouves=0, analyses=0)
        assert any("structure de la page" in l for l in lignes)

    def test_blocs_illisibles_sont_signales(self):
        # La page répond, les blocs sont là, mais plus aucun champ ne se lit:
        # les expressions de parsing ont décroché.
        lignes, log = self._journal()
        ps._bilan(log, "Résultats", nouveaux=0, trouves=40, analyses=0)
        assert any("aucun exploitable" in l for l in lignes)

    def test_les_trois_chiffres_sont_distincts(self):
        lignes, log = self._journal()
        ps._bilan(log, "Bons de commande", nouveaux=3, trouves=40, analyses=38)
        assert "3 nouveaux" in lignes[0] and "38 lus" in lignes[0] and "40 trouvés" in lignes[0]


def _resultat(db, rid, type_procedure="bon_commande", jours=0):
    quand = (datetime.now() - timedelta(days=jours)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("""INSERT INTO tender_results(id,objet,acheteur,adjudicataire,montant,
                  scraped_at,type_procedure) VALUES(?,?,?,?,?,?,?)""",
               (rid, "TRAVAUX", "COMMUNE", "STE X", "1 000,00", quand, type_procedure))
    db.commit()


class TestSourceTarie:
    def test_source_a_l_arret_declenche_une_alerte(self, db):
        _resultat(db, "r1", jours=sup.JOURS_SANS_RESULTAT + 3)
        ind = sup.collecter_indicateurs()
        assert any("bon de commande" in a for a in sup.anomalies(ind))

    def test_source_active_ne_declenche_rien(self, db):
        _resultat(db, "r2", jours=1)
        ind = sup.collecter_indicateurs()
        assert not [a for a in sup.anomalies(ind) if "résultat" in a]

    def test_base_neuve_ne_declenche_rien(self, db):
        # Aucun résultat n'a jamais été collecté: installation neuve, pas
        # source tarie. Une alerte ici serait un faux positif permanent.
        ind = sup.collecter_indicateurs()
        assert ind["resultats_total"] == 0
        assert not [a for a in sup.anomalies(ind) if "résultat" in a]

    def test_les_marches_et_les_bons_sont_suivis_separement(self, db):
        # Les marchés coulent, les bons de commande sont à l'arrêt: seul le
        # second doit remonter.
        _resultat(db, "r3", type_procedure="marche", jours=1)
        _resultat(db, "r4", type_procedure="bon_commande",
                  jours=sup.JOURS_SANS_RESULTAT + 3)
        alertes = sup.anomalies(sup.collecter_indicateurs())
        assert any("bon de commande" in a for a in alertes)
        assert not any(a.startswith("Aucun résultat d'adjudication") for a in alertes)
