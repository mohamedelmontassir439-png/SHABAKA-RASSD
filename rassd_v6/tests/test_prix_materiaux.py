"""Prix des matériaux: chaque fourchette dit d'où elle vient."""
from datetime import datetime, timedelta

from app.services.prix_materiaux import referentiel


class TestReferentiel:
    def test_chaque_ligne_a_une_source_connue(self):
        ref = referentiel()
        for cat in ref["categories"]:
            for l in cat["lignes"]:
                assert l["src"] and all(s in ref["sources"] for s in l["src"]), l["fr"]
                assert 0 < l["min"] <= l["max"], l["fr"]
                assert l["ar"] and l["unite"]

    def test_chaque_fabricant_a_une_source(self):
        for f in referentiel()["fabricants"]:
            assert f["src"] and all(s["url"].startswith("https://") for s in f["src"])

    def test_fourchette_lisible(self):
        cpj45 = next(l for c in referentiel()["categories"] for l in c["lignes"] if l["fr"] == "Ciment CPJ 45")
        assert cpj45["prix"] == "65 – 85"


class TestPage:
    def _connecte(self, client, db):
        fin = (datetime.now() + timedelta(days=2)).isoformat(timespec="seconds")
        db.execute("""INSERT INTO members(nom,email,plan,subscription_status,session_token,email_verified,
                         actif,secteurs,created_at,trial_ends)
                      VALUES('Karim','pm@example.com','free','TRIAL','jeton-prix-0001',1,1,'["T101"]',?,?)""",
                   (datetime.now().isoformat(), fin))
        db.commit()
        client.cookies.set("_session", "jeton-prix-0001")

    def test_reservee_aux_membres(self, client):
        r = client.get("/prix-materiaux", follow_redirects=False)
        assert r.status_code == 302 and "/login" in r.headers["location"]

    def test_page(self, client, db):
        self._connecte(client, db)
        page = client.get("/prix-materiaux").text
        assert "Ciment CPJ 45" in page and "65 – 85" in page and "Sonasid" in page
        assert "enginloc.ma" in page and 'href="/prix-materiaux"' in page

    def test_en_arabe(self, client, db):
        self._connecte(client, db)
        client.cookies.set("lang", "ar")
        page = client.get("/prix-materiaux").text
        assert "أثمنة" in page and "كيس 50 كغ" in page
