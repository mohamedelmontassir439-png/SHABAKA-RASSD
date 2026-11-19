# -*- coding: utf-8 -*-
"""Ventes de la douane (/encheres).

Même règle que les marchés: la liste est publique, le détail (caution,
lots, visite, pièces, avis officiel) et l'alerte sont réservés aux abonnés.
"""
from datetime import date, timedelta

import pytest

from app.services import encheres

LISTE = """<html><div class="BlocCentent">
<h3>Direction Régionale du Nord</h3><ul>
<li><a href="/dms/loadDocument?documentId=1234567">Vente sur appel d'offres de prix de lots de téléphones portables au Bureau de Tanger Med (24.11).</a></li>
<li><a href="/dms/loadDocument?documentId=1234568">Vente de ferraille (02.12)</a></li>
</ul>
<h3>Direction Régionale de Casablanca</h3><ul>
<li><a href="/dms/loadDocument?documentId=1234569">Avis d&#39;annulation de la vente du 20.11</a></li>
</ul></div></html>"""

TEXTE = """ROYAUME DU MAROC
Les offres doivent parvenir jusqu'au 21/11/2026 à 15 heures 30.
L'ouverture des plis aura lieu le 24/11/2026.
La visite des marchandises est possible à partir du 17.11.2026.
Désignation Qté (U) Etat Caution (DH)
Lot 1 Téléphone portable de marque IPHONE 17 PRO MAX 256 GB 230 Neuf
Lot 2 Téléphone portable de marque SAMSUNG GALAXY S25 40 Usagé
Caution 230 300.000,00
Les soumissionnaires doivent produire le registre de commerce et le quitus fiscal.
Conformément à la décision de la CNDP du 17/03/2023 relative aux données.
"""


def _avis(doc_id, titre="Vente de lots de téléphones portables", jours=10, cat="telephones",
          kind="aop", cautions='["300 000"]'):
    return {"doc_id": doc_id, "kind": kind, "region": "Direction Régionale du Nord", "title": titre,
            "short_date": "", "url": f"{encheres.BASE}/dms/loadDocument?documentId={doc_id}",
            "date_iso": (date.today() + timedelta(days=jours)).isoformat(), "heure": "15:30",
            "visite": "", "ouverture": "", "cautions": ["300 000"], "pieces": ["rc"],
            "lots": [{"nom": "IPHONE 17 PRO MAX", "qte": 230, "etat": "neuf"}], "apercu": "",
            "categorie": cat, "texte_len": 900}


def _membre(db, email="enc@example.com", jeton="jeton-encheres-aa", actif=True):
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
               ("Sara", email, "pro" if actif else "free", "ACTIVE" if actif else "PENDING",
                (date.today() + timedelta(days=90 if actif else -5)).strftime("%Y-%m-%d"),
                "x", jeton, 1, "[]", 1))
    db.commit()


class TestLecture:
    def test_liste(self):
        lignes = encheres.lire_liste(LISTE, "aop")
        assert [l["doc_id"] for l in lignes] == [1234567, 1234568, 1234569]
        assert lignes[0]["region"] == "Direction Régionale du Nord"
        assert lignes[0]["short_date"] == "24/11"
        assert not lignes[0]["title"].endswith("(24.11).")
        assert lignes[2]["title"].startswith("Avis d'annulation")

    def test_avis(self):
        a = encheres.analyser({"doc_id": 1, "kind": "aop", "title": "Vente de lots", "short_date": "24/11"},
                              TEXTE, date(2026, 11, 19))
        assert a["date_iso"] == "2026-11-21"      # date limite, pas l'ouverture
        assert a["heure"] == "15:30"
        assert a["ouverture"] == "2026-11-24"
        assert a["visite"] == "2026-11-17"
        assert a["cautions"] == ["300 000"]       # pas « 230 300 000 »
        assert {"rc", "quitus"} <= set(a["pieces"])
        assert a["lots"][0] == {"nom": "IPHONE 17 PRO MAX 256 GB", "qte": 230, "etat": "neuf"}
        assert a["lots"][1]["etat"] == "usage"
        assert a["categorie"] == "telephones"     # d'après les lots, le titre est générique

    def test_date_cndp_ignoree(self):
        a = encheres.analyser({"doc_id": 1, "kind": "ep", "title": "Vente", "short_date": ""},
                              "Décision de la CNDP du 17/03/2023. Rien d'autre.", date(2026, 11, 19))
        assert a["date_iso"] == ""

    def test_pdf_scanne(self):
        a = encheres.analyser({"doc_id": 1, "kind": "aop", "title": "Vente judiciaire d'un immeuble",
                               "short_date": "02/12"}, "", date(2026, 11, 19))
        assert a["date_iso"] == "2026-12-02"
        assert a["categorie"] == "immobilier"

    @pytest.mark.parametrize("titre,cle", [
        ("Vente de bijoux en or.", "or"),
        ("Vente d'ordinateurs portables", "telephones"),
        ("Vente de véhicules de tourisme", "vehicules"),
        ("Avis d’annulation de la vente", "annulation"),
        ("Vente de lots de marchandises diverses", "divers"),
    ])
    def test_categories(self, titre, cle):
        assert encheres.classer(titre) == cle

    def test_message_whatsapp(self):
        d = encheres.pour_affichage(dict(_avis(5), cautions='["300 000"]', pieces='["rc"]',
                                         lots='[{"nom": "IPHONE", "qte": 3, "etat": "neuf"}]'), "ar")
        m = encheres.message_whatsapp(d, "ar")
        assert "300 000 درهم" in m and "سجل تجاري" in m and d["url"] in m


class TestBase:
    def test_enregistrer_et_retirer(self, db):
        n = encheres.enregistrer(db, [_avis(11), _avis(12)], presents=[11, 12])
        assert len(n) == 2
        assert encheres.enregistrer(db, [_avis(11)], presents=[11]) == []
        assert db.execute("SELECT retire FROM encheres WHERE doc_id=12").fetchone()[0] == 1
        assert db.execute("SELECT retire FROM encheres WHERE doc_id=11").fetchone()[0] == 0

    def test_avis_invalide_refuse(self, db):
        mauvais = dict(_avis(13), url="https://exemple.com/x.pdf")
        assert encheres.enregistrer(db, [mauvais]) == []


class TestPages:
    def test_liste_publique_sans_details(self, client, db):
        encheres.enregistrer(db, [_avis(21, "Vente de lots de téléphones au Bureau de Tanger Med")])
        page = client.get("/encheres")
        assert page.status_code == 200
        assert "Tanger Med" in page.text
        assert "300 000" not in page.text          # la caution est réservée
        assert "documentId=21" not in page.text    # l'avis officiel aussi

    def test_vente_passee_cachee(self, client, db):
        encheres.enregistrer(db, [_avis(22, "VENTE PASSEE", jours=-2)])
        assert "VENTE PASSEE" not in client.get("/encheres").text

    def test_filtre_categorie(self, client, db):
        encheres.enregistrer(db, [_avis(23, "VENTE DE TELEPHONES"), _avis(24, "VENTE DE FERRAILLE", cat="ferraille")])
        page = client.get("/encheres?c=ferraille").text
        assert "VENTE DE FERRAILLE" in page and "VENTE DE TELEPHONES" not in page

    def test_detail_reserve(self, client, db):
        encheres.enregistrer(db, [_avis(25)])
        r = client.get("/encheres/25", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].startswith("/login")
        _membre(db, "libre@example.com", "jeton-encheres-bb", actif=False)
        client.cookies.set("_session", "jeton-encheres-bb")
        r = client.get("/encheres/25", follow_redirects=False)
        assert r.status_code == 302 and "/tarifs" in r.headers["location"]

    def test_abonne_voit_tout(self, client, db):
        encheres.enregistrer(db, [_avis(26)])
        _membre(db)
        client.cookies.set("_session", "jeton-encheres-aa")
        assert "300 000" in client.get("/encheres").text
        page = client.get("/encheres/26").text
        assert "300 000" in page and "IPHONE 17 PRO MAX" in page and "documentId=26" in page

    def test_alerte(self, client, db):
        _membre(db)
        client.cookies.set("_session", "jeton-encheres-aa")
        client.get("/encheres")
        jeton = client.cookies.get("_csrf")
        r = client.post("/encheres/alerte", data={"actif": "1", "csrf_token": jeton}, follow_redirects=False)
        assert r.status_code == 303
        assert db.execute("SELECT notif_encheres FROM members WHERE email='enc@example.com'").fetchone()[0] == 1


class TestRelais:
    def test_jeton_obligatoire(self, client, db):
        assert client.get("/api/relais/encheres").status_code == 401
        assert client.post("/api/relais/encheres", json={"avis": []}).status_code == 401

    def test_depot_et_alerte(self, client, db, monkeypatch):
        import main
        envoyes = []
        monkeypatch.setattr("app.services.notifications.email_send",
                            lambda to, sujet, corps, essentiel=False: envoyes.append(to) or True)
        _membre(db)
        db.execute("UPDATE members SET notif_encheres=1"); db.commit()
        h = {"X-Relais-Jeton": main._jeton_relais()}
        etat = client.get("/api/relais/encheres", headers=h).json()
        assert etat["ok"] and etat["connus"] == [] and etat["a_faire"]
        r = client.post("/api/relais/encheres", headers=h, json={"avis": [_avis(31)], "presents": [31]}).json()
        assert r["enregistres"] == 1
        assert envoyes == ["enc@example.com"]
        assert client.get("/api/relais/encheres", headers=h).json()["connus"] == [31]
        # Un second dépôt du même avis n'alerte pas deux fois.
        client.post("/api/relais/encheres", headers=h, json={"avis": [_avis(31)], "presents": [31]})
        assert envoyes == ["enc@example.com"]

    def test_panne_notee(self, client, db):
        import main
        h = {"X-Relais-Jeton": main._jeton_relais()}
        client.post("/api/relais/encheres", headers=h, json={"panne": "douane.gov.ma injoignable"})
        assert db.execute("SELECT status FROM scraper_runs WHERE source='douane'").fetchone()[0] == "FAILED"


def test_admin_page(admin, db):
    encheres.enregistrer(db, [_avis(41)])
    page = admin.get("/admin/encheres")
    assert page.status_code == 200
    assert "Ventes de la douane" in page.text and "درهم" in page.text
