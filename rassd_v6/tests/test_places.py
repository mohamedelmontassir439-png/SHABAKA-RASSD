"""Collecte annuaire via l'API Google Places (réponses simulées).

L'API est appelée avec une clé facturée: les tests utilisent des réponses
conformes au format réel plutôt que le réseau, et vérifient la chaîne
complète parsing → normalisation → déduplication → base.
"""
import pytest

from app.services import places_scraper as ps
from app.services.places_scraper import place_vers_entreprise, _requete_secteur, VILLES


def _place(nom, tel="+212 522 45 67 89", site="https://exemple.ma/", ville="Casablanca"):
    return {
        "id": "ChIJ" + nom.replace(" ", "")[:10],
        "displayName": {"text": nom},
        "formattedAddress": f"12 Rue Test, {ville}, Maroc",
        "internationalPhoneNumber": tel,
        "websiteUri": site,
        "primaryTypeDisplayName": {"text": "Entreprise de construction"},
        "addressComponents": [
            {"longText": ville, "types": ["locality"]},
            {"longText": "Casablanca-Settat", "types": ["administrative_area_level_1"]},
        ],
    }


class TestConversion:
    def test_champs_extraits(self):
        f = place_vers_entreprise(_place("STE ATLAS BTP SARL"), "T101", "q")
        assert f["legal_name"] == "STE ATLAS BTP SARL"
        assert f["sector"] == "T101"
        assert f["city"] == "Casablanca"
        assert f["region"] == "Casablanca-Settat"
        assert f["phone"] == "+212 522 45 67 89"
        assert f["source"] == "google-places"
        assert "place_id:" in f["source_url"]

    def test_place_sans_nom_ignoree(self):
        assert place_vers_entreprise({"id": "x"}, "T101", "q") == {}

    def test_numero_national_en_repli(self):
        p = _place("OMEGA", tel="")
        p.pop("internationalPhoneNumber", None)
        p["nationalPhoneNumber"] = "0522 11 22 33"
        assert place_vers_entreprise(p, "T101", "q")["phone"] == "0522 11 22 33"


class TestRequetesSecteur:
    def test_les_83_secteurs_ont_une_requete(self):
        from app.core.sectors import SECTORS
        vides = [c for c in SECTORS if not _requete_secteur(c).strip()]
        assert vides == [], f"secteurs sans requête: {vides}"

    def test_libelle_nettoye(self):
        assert _requete_secteur("T103") == "menuiserie métallerie charpente"

    def test_villes_principales_presentes(self):
        for v in ("Casablanca", "Rabat", "Tanger", "Marrakech"):
            assert v in VILLES


class TestCollecteCompleteSimulee:
    def test_pipeline_complet(self, db, monkeypatch):
        """Deux graphies d'une même entreprise doivent produire une seule fiche."""
        pages = [
            ([_place("STE ATLAS BTP SARL"), _place("OMEGA TRAVAUX SARL")], "token1"),
            ([_place("Atlas B.T.P.")], ""),
        ]
        appels = {"n": 0}

        def faux_search(requete, page_token=""):
            i = appels["n"]; appels["n"] += 1
            return pages[i] if i < len(pages) else ([], "")

        monkeypatch.setattr(ps, "recherche_texte", faux_search)
        monkeypatch.setattr(ps.cfg, "PLACES_DELAY_MS", 0)

        stats = ps.collecter(["T101"], ["Casablanca"], lambda *a: None, avec_email=False)

        assert stats["trouvees"] == 3
        assert stats["creees"] == 2, "Atlas apparaît deux fois: une seule fiche attendue"
        assert stats["fusionnees"] == 1

        noms = [r["legal_name"] for r in
                db.execute("SELECT legal_name FROM companies ORDER BY legal_name").fetchall()]
        assert len(noms) == 2

        tel = db.execute("SELECT phone FROM companies LIMIT 1").fetchone()["phone"]
        assert tel == "212522456789", "le téléphone doit être normalisé au format international"

    def test_cle_refusee_arrete_immediatement(self, db, monkeypatch):
        """Une clé refusée ne doit pas enchaîner des centaines d'appels facturés."""
        appels = {"n": 0}

        def refus(requete, page_token=""):
            appels["n"] += 1
            raise RuntimeError("clé Google refusée (403)")

        monkeypatch.setattr(ps, "recherche_texte", refus)
        monkeypatch.setattr(ps.cfg, "PLACES_DELAY_MS", 0)
        logs = []
        stats = ps.collecter(["T101", "T102", "T103"], VILLES, logs.append, avec_email=False)
        assert appels["n"] == 1, "arrêt dès le premier refus"
        assert stats["erreurs"] == 1
        assert any("refus" in l for l in logs)

    def test_email_ajoute_a_la_fiche(self, db, monkeypatch):
        monkeypatch.setattr(ps, "recherche_texte",
                            lambda q, t="": ([_place("SOCIETE EMAIL SARL")], ""))
        monkeypatch.setattr(ps.cfg, "PLACES_DELAY_MS", 0)
        import app.services.email_finder as ef
        monkeypatch.setattr(ef, "find_email", lambda site: "contact@exemple.ma")

        stats = ps.collecter(["T101"], ["Rabat"], lambda *a: None, avec_email=True)
        assert stats["emails"] == 1
        assert db.execute("SELECT email FROM companies LIMIT 1").fetchone()["email"] == "contact@exemple.ma"


class TestEmailFinder:
    @pytest.mark.parametrize("email,valide", [
        ("contact@atlas.ma", True),
        ("info@societe-btp.co.ma", True),
        ("logo@2x.png", False),
        ("test@example.com", False),
        ("noreply@site.ma", False),
        ("sentry@wixpress.com", False),
        ("pasdemail", False),
        ("", False),
    ])
    def test_filtrage(self, email, valide):
        from app.services.email_finder import is_plausible_email
        assert is_plausible_email(email) is valide

    def test_priorite_au_domaine_de_l_entreprise(self):
        from app.services.email_finder import extract_emails
        html = '<a href="mailto:perso@gmail.com">x</a> <p>contact@masociete.ma</p>'
        assert extract_emails(html, prefer_domain="masociete.ma")[0] == "contact@masociete.ma"

    def test_aucun_email_invente(self):
        from app.services.email_finder import extract_emails
        assert extract_emails("<html>aucune adresse ici</html>") == []


class TestLectureCarteMaps:
    """Analyse des cartes Google Maps — textes réels relevés le 08/09/2026."""

    def test_carte_complete(self):
        from app.services.maps_scraper import lire_carte
        texte = ("ENGOR\nENGOR\n4,3\nSociété de travaux publics · 20 Rue Ahmed El Kadmiri\n"
                 "Fermé · Ouvre à 08:30 mer. · 05 22 23 68 50\n\nSite Web\n\nItinéraires")
        infos = lire_carte(texte)
        assert infos["phone"] == "05 22 23 68 50"
        assert infos["subsector"] == "Société de travaux publics"
        assert infos["address"] == "20 Rue Ahmed El Kadmiri"

    def test_segment_vide_au_milieu(self):
        from app.services.maps_scraper import lire_carte
        texte = ("SBTH\nSBTH\n4,6\nEntreprise de construction ·  · 1 angle rue ibnou younouss\n"
                 "Fermé · Ouvre à 08:30 mer. · 05 22 48 10 89")
        infos = lire_carte(texte)
        assert infos["subsector"] == "Entreprise de construction"
        assert infos["address"] == "1 angle rue ibnou younouss"
        assert infos["phone"] == "05 22 48 10 89"

    def test_mobile_marocain(self):
        from app.services.maps_scraper import lire_carte
        infos = lire_carte("HSTB\nHSTB\nConstructeur · 34 Rue Soumaya\nOuvert · 06 63 61 85 81")
        assert infos["phone"] == "06 63 61 85 81"

    def test_sans_telephone(self):
        from app.services.maps_scraper import lire_carte
        infos = lire_carte("SOCIETE X\nSOCIETE X\n4,2\nEntrepreneur · 3 Rue 6\nFermé")
        assert infos["phone"] == ""
        assert infos["address"] == "3 Rue 6"

    def test_horaire_pas_confondu_avec_un_numero(self):
        """'Ouvre à 08:30' ne doit pas être pris pour un téléphone."""
        from app.services.maps_scraper import lire_carte
        infos = lire_carte("X\nX\nEntrepreneur · Rue A\nFermé · Ouvre à 08:30 mer.")
        assert infos["phone"] == ""

    def test_carte_vide(self):
        from app.services.maps_scraper import lire_carte
        assert lire_carte("") == {"subsector": "", "address": "", "phone": ""}

    def test_les_83_secteurs_ont_une_requete_maps(self):
        from app.services.maps_scraper import requete_secteur
        from app.core.sectors import SECTORS
        assert [c for c in SECTORS if not requete_secteur(c).strip()] == []
