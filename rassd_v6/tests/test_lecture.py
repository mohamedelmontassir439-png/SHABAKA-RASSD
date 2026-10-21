# -*- coding: utf-8 -*-
"""Les chiffres réels de l'encadré « Comprendre cet avis ».

Une valeur que la source ne publie pas est dite absente — jamais estimée.
"""
from app.core.lecture import articles_bdc, chiffres, qualifications_lisibles

AO = {
    "id": "ao_1", "type_procedure": "marche", "montant": "17 540 251,20 MAD",
    "date_limite": "05/11/2026",
    "description": (
        "Date et heure limite de remise des plis : 05/11/2026 10:00 "
        "Référence GRC/07/2026 Objet : x Procédure : Appel d'offres ouvert "
        "Allotissement : - "
        "Adresse de retrait des dossiers : www.marchespublics.gov.ma "
        "Prix d'acquisition des plans : 0,00 MAD Caution provisoire : 350 000,00 MAD "
        "Qualifications : Equipement / B- Travaux routiers / B.1- Travaux de terrassements "
        "routiers courants / Classe 2 Equipement / B- Travaux routiers / B.3- Ouvrages "
        "d'assainissement routiers / Classe 2 Agréments : Variante : Non"),
}

BDC = {
    "id": "bdc_1", "type_procedure": "bon_commande", "montant": "", "date_limite": "23/10/2026",
    "nature": "Prestations de recharge des extincteurs",
    "description": (
        "Date limite de réception des devis 23/10/2026 09:00 Lieu d'exécution CASABLANCA "
        "Pièces jointes Avis d'achat N°15-2026_0001.zip Articles Tout afficher "
        "#01 Recharge d’extincteur Caractéristiques et spécifications CO2 6KG ; "
        "Unité de mesure U Quantité 9 TVA (%) 20 Garanties exigées -- "
        "#02 Recharge d’extincteur Caractéristiques et spécifications Poudre 9KG ; "
        "Unité de mesure U Quantité 2 TVA (%) 20 Garanties exigées Attestation CNSS -- Copyright"),
}

GM = {"id": "gm_1", "type_procedure": "marche", "montant": "499.200,00 MAD",
      "date_limite": "28/10/2026", "description": "SGPTV Travaux de peinture"}


class TestAppelDOffres:
    def test_les_valeurs_de_l_avis(self):
        c = chiffres(AO)
        assert c["estimation"] == "17 540 251,20 MAD"
        assert c["caution"] == {"valeur": "350 000,00 MAD"}
        assert c["limite"]["jour"] == "05/11/2026" and c["limite"]["heure"] == "10:00"
        assert c["dossier"]["electronique"] and c["dossier"]["gratuit"]

    def test_qualifications_lisibles(self):
        assert chiffres(AO)["qualification"]["valeurs"] == [
            "B.1 Travaux de terrassements routiers courants — classe 2",
            "B.3 Ouvrages d'assainissement routiers — classe 2"]

    def test_format_laboratoire(self):
        q = qualifications_lisibles("Laboratoires / INVESTIGATIONS MARITIMES / ETUDES "
                                    "GEOTECHNIQUES PORTUAIRES / Classe 1")
        assert q == ["ETUDES GEOTECHNIQUES PORTUAIRES — classe 1"]

    def test_caution_nulle(self):
        c = chiffres(dict(AO, description=AO["description"].replace("350 000,00", "0,00")))
        assert c["caution"] == {"valeur": "", "aucune": True}

    def test_en_lots_la_caution_n_est_pas_aucune(self):
        d = AO["description"].replace("Allotissement : -", "Allotissement : 3 Lots") \
            .replace("350 000,00 MAD", "")
        assert chiffres(dict(AO, description=d))["caution"].get("par_lot")


class TestSourcePrivee:
    def test_rien_n_est_invente(self):
        c = chiffres(GM)
        assert c["estimation"] == "499.200,00 MAD"
        assert c["caution"] is None and c["qualification"] is None and c["dossier"] is None
        assert c["limite"]["heure"] == "", "le jour seul: pas d'heure inventée"


class TestBonDeCommande:
    def test_articles_heure_garanties(self):
        c = chiffres(BDC)
        assert c["limite"]["heure"] == "09:00"
        assert [(a["designation"], a["quantite"], a["unite"]) for a in c["articles"]] == [
            ("Recharge d’extincteur", "9", "U"), ("Recharge d’extincteur", "2", "U")]
        assert c["garanties"] == ["Attestation CNSS"]
        assert c["pieces"] == ["Avis d'achat N°15-2026_0001.zip"]

    def test_sans_article(self):
        assert articles_bdc("rien") == []


class TestRendu:
    def _rendre(self, t):
        import main
        g = main.templates.get_template("detail.html")
        source = g.environment.loader.get_source(g.environment, "detail.html")[0]
        debut = source.index("{% set bdc =")
        # L'encadré s'arrête où commencent les marchés comparables.
        bloc = source[debut:source.index("{# Ce que les marchés déjà attribués")]
        tpl = main.templates.env.from_string(bloc)
        return tpl.render(t=t, tr=lambda k, **kw: k + (str(kw.get("n", "")) if kw else ""),
                          ico=lambda *a: "", lang="fr")

    def test_les_valeurs_s_affichent(self):
        html = self._rendre(AO)
        assert "350 000,00 MAD" in html and "17 540 251,20 MAD" in html
        assert "10:00" in html and "B.1 Travaux de terrassements" in html

    def test_la_source_privee_dit_ce_qui_manque(self):
        html = self._rendre(GM)
        assert "lire_v_non_publie" in html and "499.200,00 MAD" in html

    def test_le_bon_de_commande(self):
        html = self._rendre(BDC)
        assert "Recharge d’extincteur" in html and "Attestation CNSS" in html and "09:00" in html
