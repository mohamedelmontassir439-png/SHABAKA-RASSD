# -*- coding: utf-8 -*-
"""La campagne: par où commencer, et ce qui part réellement.

Le message ne décrit pas la plateforme, il montre des marchés que
l'entreprise peut encore déposer. Sans marché ouvert, il n'y a rien à
montrer — et ces tests exigent qu'alors rien ne parte.
"""
import html
from datetime import date, timedelta

import pytest

from app.core.config import cfg
from app.services import campagne


@pytest.fixture()
def admin(client):
    client.get("/admin/login")
    client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                      "csrf_token": client.cookies.get("_csrf")})
    return client


def _entreprise(db, nom="BTP ATLAS SARL", secteur="T101", ville="Casablanca",
                email="contact@btpatlas.ma"):
    db.execute("""INSERT INTO companies(legal_name,normalized_name,sector,city,phone,email,
                  source,created_at) VALUES(?,?,?,?,'0612345678',?,'google-maps',
                  '2026-09-01T09:00:00')""", (nom, nom.lower(), secteur, ville, email))
    db.commit()
    return db.execute("SELECT id FROM companies WHERE legal_name=?", (nom,)).fetchone()["id"]


def _marche(db, tid="t_c1", secteur="T101", objet="CONSTRUCTION D'UNE ECOLE",
            acheteur="COMMUNE DE CASABLANCA"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,?,?,'Casablanca','1 200 000,00 MAD','actif',
                  '2026-09-22 08:00:00',?,'Public','marche')""",
               (tid, objet, acheteur, secteur,
                (date.today() + timedelta(days=12)).strftime("%d/%m/%Y")))
    db.commit()


class TestPriorites:
    def test_un_secteur_sans_marche_ouvert_est_exclu(self, db):
        """On ne brûle pas des noms avec un argument qu'on n'a pas."""
        _entreprise(db, secteur="T999")
        assert not [p for p in campagne.priorites() if p["secteur"] == "T999"]

    def test_le_classement_croise_marches_et_entreprises(self, db):
        _entreprise(db, nom="A SARL", secteur="T101")
        _entreprise(db, nom="B SARL", secteur="T102")
        _marche(db, "t_a1", "T101")
        _marche(db, "t_a2", "T101")
        _marche(db, "t_b1", "T102")
        ordre = [p["secteur"] for p in campagne.priorites()]
        assert ordre.index("T101") < ordre.index("T102")

    def test_il_compte_celles_quon_na_pas_encore_appelees(self, db):
        cid = _entreprise(db)
        _marche(db)
        avant = [p for p in campagne.priorites() if p["secteur"] == "T101"][0]
        assert avant["a_appeler"] == 1
        db.execute("""INSERT INTO prospection(company_id,statut,created_at,updated_at)
                      VALUES(?,'refus','x','x')""", (cid,))
        db.commit()
        apres = [p for p in campagne.priorites() if p["secteur"] == "T101"][0]
        assert apres["a_appeler"] == 0


class TestMessages:
    def test_le_whatsapp_cite_les_marches(self, db):
        cid = _entreprise(db)
        _marche(db)
        e = dict(db.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone())
        texte = campagne.message_whatsapp(e, "https://x.ma/i/abc")
        assert "ECOLE" in texte
        assert "COMMUNE DE CASABLANCA" in texte
        assert "https://x.ma/i/abc" in texte

    def test_le_whatsapp_porte_la_sortie_de_liste(self, db):
        """Loi 09-08: tout envoi doit dire comment s'y soustraire."""
        cid = _entreprise(db)
        _marche(db)
        e = dict(db.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone())
        assert "STOP" in campagne.message_whatsapp(e, "")

    def test_lobjet_de_lemail_nomme_le_metier_et_le_nombre(self, db):
        cid = _entreprise(db)
        _marche(db)
        e = dict(db.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone())
        objet, _ = campagne.message_email(e, "")
        assert "1 marchés publics ouverts en" in objet
        assert "Construction" in objet

    def test_sans_marche_ouvert_aucun_message_nest_produit(self, db):
        cid = _entreprise(db, secteur="T888")
        e = dict(db.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone())
        assert campagne.message_whatsapp(e, "") == ""
        assert campagne.message_email(e, "") == ("", "")

    def test_le_message_sarrete_a_trois_marches(self, db):
        cid = _entreprise(db)
        for i in range(6):
            _marche(db, tid=f"t_m{i}", objet=f"MARCHE NUMERO {i}")
        e = dict(db.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone())
        texte = campagne.message_whatsapp(e, "")
        assert texte.count("•") == campagne.MARCHES_PAR_MESSAGE
        # Le total annoncé reste le vrai total, pas le nombre cité.
        assert "6 marchés publics ouverts" in texte


def _courante(page: str) -> str:
    """Le lien du rail marqué comme page courante.

    On ne compte pas « aria-current » dans la page entière: la feuille de
    style contient le sélecteur .rail-lien[aria-current="page"], et le test
    croyait voir deux entrées allumées là où il n'y en avait qu'une.
    """
    import re
    trouves = [m.group(1) for m in
               re.finditer(r'<a class="rail-lien" href="([^"]+)"\s*([^>]*)>', page)
               if "aria-current" in m.group(2)]
    assert len(trouves) == 1, f"entrées allumées: {trouves}"
    return trouves[0]


class TestPagePlan:
    def test_la_page_rend(self, admin, db):
        _entreprise(db)
        _marche(db)
        r = admin.get("/admin/prospection/plan")
        assert r.status_code == 200
        assert "Par où commencer" in html.unescape(r.text)

    def test_elle_classe_le_secteur_qui_a_des_marches(self, admin, db):
        _entreprise(db)
        _marche(db)
        assert "Constructions" in admin.get("/admin/prospection/plan").text

    def test_le_rail_distingue_plan_et_file(self, admin, db):
        """Le préfixe commun ne doit pas allumer les deux entrées."""
        assert _courante(admin.get("/admin/prospection/plan").text) == "/admin/prospection/plan"

    def test_une_fiche_allume_bien_la_file_dappel(self, admin, db):
        cid = _entreprise(db)
        assert _courante(admin.get(f"/admin/prospection/{cid}").text) == "/admin/prospection"


class TestEnvoiEmail:
    def test_sans_marche_ouvert_rien_ne_part(self, admin, db, monkeypatch):
        partis = []
        monkeypatch.setattr("app.services.notifications.email_send",
                            lambda *a, **k: partis.append(a) or True)
        cid = _entreprise(db, secteur="T888")
        admin.get(f"/admin/prospection/{cid}")
        r = admin.post(f"/admin/prospection/{cid}/email",
                       data={"csrf_token": admin.cookies.get("_csrf")},
                       follow_redirects=False)
        assert "envoi=sans_marche" in r.headers.get("location", "")
        assert not partis

    def test_sans_adresse_rien_ne_part(self, admin, db):
        cid = _entreprise(db, email="")
        _marche(db)
        admin.get(f"/admin/prospection/{cid}")
        r = admin.post(f"/admin/prospection/{cid}/email",
                       data={"csrf_token": admin.cookies.get("_csrf")},
                       follow_redirects=False)
        assert "envoi=sans_adresse" in r.headers.get("location", "")

    def test_lenvoi_est_enregistre(self, admin, db, monkeypatch):
        monkeypatch.setattr("app.services.notifications.email_send", lambda *a, **k: True)
        cid = _entreprise(db)
        _marche(db)
        admin.get(f"/admin/prospection/{cid}")
        admin.post(f"/admin/prospection/{cid}/email",
                   data={"csrf_token": admin.cookies.get("_csrf")},
                   follow_redirects=False)
        ligne = db.execute("SELECT canal, dernier_contact FROM prospection "
                           "WHERE company_id=?", (cid,)).fetchone()
        assert ligne and ligne["canal"] == "email" and ligne["dernier_contact"]

    def test_il_faut_etre_admin(self, client, db):
        cid = _entreprise(db)
        r = client.post(f"/admin/prospection/{cid}/email", data={}, follow_redirects=False)
        assert "/admin/login" in r.headers.get("location", "")
