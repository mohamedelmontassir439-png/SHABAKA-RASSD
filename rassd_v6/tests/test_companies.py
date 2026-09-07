"""Base entreprises — normalisation, déduplication, alimentation."""
import pytest

from app.services.companies import (
    normalize_company_name, normalize_phone, normalize_email, normalize_website,
    duplicate_score, upsert_company, seed_from_tender_results,
)


class TestNormalisationNoms:
    @pytest.mark.parametrize("raw,expected", [
        ("STE ATLAS BTP SARL", "atlas btp"),
        ("Atlas B.T.P. s.a.r.l", "atlas btp"),
        ("ATLAS BTP", "atlas btp"),
        ("Société clairis monde", "clairis monde"),
        ("ENTREPRISE HBAYOU", "hbayou"),
        ("-ENTREPRISE HBAYOU", "hbayou"),
        ("ZEF SCIENTIFIC SARL AU", "zef scientific"),
    ])
    def test_variantes_convergent(self, raw, expected):
        assert normalize_company_name(raw) == expected

    @pytest.mark.parametrize("raw", [
        "Infructueux", "annulée.", "Annulé", "NEANT", "Néant",
        "voir pv", "Voir détail des lots au niveau du PV",
        "Marché déclaré infructueux", "reporté", "SARL", "",
    ])
    def test_mentions_de_procedure_rejetees(self, raw):
        """Ces libellés occupent le champ adjudicataire sans être des entreprises."""
        assert normalize_company_name(raw) == ""


class TestNormalisationContacts:
    @pytest.mark.parametrize("raw", [
        "06 12 34 56 78", "+212612345678", "0612345678", "212612345678",
        "00212612345678", "06-12-34-56-78",
    ])
    def test_telephone_marocain(self, raw):
        assert normalize_phone(raw) == "212612345678"

    @pytest.mark.parametrize("raw", ["", "abc", "12", None])
    def test_telephone_invalide(self, raw):
        assert normalize_phone(raw) == ""

    def test_email(self):
        assert normalize_email("  Contact@Atlas.MA ") == "contact@atlas.ma"
        assert normalize_email("pas-un-email") == ""

    def test_site_web(self):
        assert normalize_website("https://WWW.Atlas.ma/") == "atlas.ma"
        assert normalize_website("atlas") == ""


class TestDeduplication:
    def _fiche(self, **kw):
        d = {"legal_name": kw.pop("legal_name", "ATLAS BTP")}
        d["normalized_name"] = normalize_company_name(d["legal_name"])
        d.update(kw)
        return d

    def test_ice_identique_conclut_seul(self):
        a = self._fiche(legal_name="ALPHA", ice="001234567000045")
        b = self._fiche(legal_name="BETA", ice="001234567000045")
        assert duplicate_score(a, b) == 2

    def test_rc_identique_conclut_seul(self):
        a = self._fiche(legal_name="ALPHA", rc="RC12345")
        b = self._fiche(legal_name="BETA", rc="RC12345")
        assert duplicate_score(a, b) == 2

    def test_nom_seul_est_un_doublon_possible(self):
        a = self._fiche(legal_name="STE ATLAS BTP SARL")
        b = self._fiche(legal_name="Atlas B.T.P.")
        assert duplicate_score(a, b) == 1

    def test_nom_plus_ville_est_un_doublon_fort(self):
        a = self._fiche(legal_name="ATLAS BTP", city="Casablanca")
        b = self._fiche(legal_name="Ste Atlas BTP sarl", city="CASABLANCA")
        assert duplicate_score(a, b) == 2

    def test_nom_plus_telephone_est_un_doublon_fort(self):
        a = self._fiche(legal_name="ATLAS BTP", phone="0612345678")
        b = self._fiche(legal_name="atlas btp", phone="+212612345678")
        assert duplicate_score(a, b) == 2

    def test_homonymes_de_villes_differentes_restent_separes(self):
        a = self._fiche(legal_name="ATLAS BTP", city="Fès")
        b = self._fiche(legal_name="ATLAS BTP", city="Agadir")
        assert duplicate_score(a, b) == 1, "doublon possible, jamais fusion automatique certaine"

    def test_entreprises_differentes(self):
        a = self._fiche(legal_name="ATLAS BTP")
        b = self._fiche(legal_name="OMEGA TRAVAUX")
        assert duplicate_score(a, b) == 0


class TestUpsert:
    def test_creation_puis_fusion(self, db):
        cid1, action1 = upsert_company(db, {
            "legal_name": "STE ATLAS BTP SARL", "city": "Casablanca", "source": "test"})
        assert action1 == "created"

        cid2, action2 = upsert_company(db, {
            "legal_name": "Atlas B.T.P.", "city": "Casablanca",
            "phone": "0612345678", "source": "autre"})
        assert cid2 == cid1, "la variante doit rejoindre la fiche existante"
        assert action2.startswith("merged")

        row = db.execute("SELECT phone FROM companies WHERE id=?", (cid1,)).fetchone()
        assert row["phone"] == "212612345678", "la fusion enrichit les champs vides"

        sources = db.execute(
            "SELECT COUNT(*) FROM company_sources WHERE company_id=?", (cid1,)).fetchone()[0]
        assert sources == 2, "chaque provenance est conservée après fusion"

    def test_ne_jamais_ecraser_une_valeur_existante(self, db):
        cid, _ = upsert_company(db, {"legal_name": "OMEGA", "email": "vrai@omega.ma", "source": "a"})
        upsert_company(db, {"legal_name": "OMEGA", "email": "autre@omega.ma",
                            "city": "Rabat", "source": "b"})
        row = db.execute("SELECT email, city FROM companies WHERE id=?", (cid,)).fetchone()
        assert row["email"] == "vrai@omega.ma", "une donnée déjà renseignée n'est pas remplacée"
        assert row["city"] == "Rabat", "mais un champ vide est complété"

    def test_libelle_de_procedure_rejete(self, db):
        cid, action = upsert_company(db, {"legal_name": "Infructueux", "source": "test"})
        assert action == "rejected" and cid == 0
        assert db.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0


class TestAlimentationDepuisAdjudications:
    def test_seed_ignore_les_mentions_de_procedure(self, db):
        rows = [
            ("r1", "STE ATLAS BTP SARL", "T101", "Casablanca-Settat"),
            ("r2", "Atlas B.T.P.", "T101", "Casablanca-Settat"),
            ("r3", "Infructueux", "T101", "Fès-Meknès"),
            ("r4", "Voir détail des lots au niveau du PV", "T102", "Rabat"),
            ("r5", "OMEGA TRAVAUX SARL", "T102", "Rabat"),
        ]
        for rid, adj, sect, reg in rows:
            db.execute(
                """INSERT INTO tender_results(id,adjudicataire,secteur,region,scraped_at)
                   VALUES(?,?,?,?,'2026-01-01')""", (rid, adj, sect, reg))
        db.commit()

        stats = seed_from_tender_results(db)
        assert stats["rejected"] == 2, "les deux mentions de procédure sont écartées"

        noms = [r["legal_name"] for r in
                db.execute("SELECT legal_name FROM companies").fetchall()]
        assert len(noms) == 2, "Atlas apparaît une seule fois, Omega une fois"
        assert not any("nfructueux" in n for n in noms)
