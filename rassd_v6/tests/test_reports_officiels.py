# -*- coding: utf-8 -*-
"""Les reports officiels des dates limites (avis TGR d'octobre 2026)."""
from datetime import date

from app.services import reports_officiels as R


def _avis(db, tid, limite, statut="actif", source="marchespublics", objet=None, scraped="2026-10-20 08:00:00"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,scraped_at,url,source,date_limite,description)
                  VALUES(?,?,'A','T101',?,?,'u',?,?,?)""",
               (tid, objet or f"Marché {tid}", statut, scraped, source, limite,
                f"Date et heure limite de remise des plis : {limite} 10:00 Référence 1/2026"))
    db.commit()


def test_report_applique_une_fois(db):
    _avis(db, "ao_1", "22/10/2026", statut="expire")
    _avis(db, "ao_2", "26/10/2026")
    _avis(db, "ao_3", "25/10/2026")
    assert R.appliquer() == {"reportes": 2, "rouverts": 1}
    r = {x["id"]: dict(x) for x in db.execute("SELECT * FROM tenders")}
    assert r["ao_1"]["date_limite"] == "28/10/2026" and r["ao_1"]["statut"] == "actif"
    assert r["ao_1"]["date_limite_initiale"] == "22/10/2026"
    assert "28/10/2026 10:00" in r["ao_1"]["description"], "l'heure est gardée"
    assert r["ao_2"]["date_limite"] == "30/10/2026"
    assert r["ao_3"]["date_limite"] == "25/10/2026", "hors du report"
    assert R.appliquer()["reportes"] == 0


def test_un_doublon_clos_n_est_pas_rouvert(db):
    _avis(db, "ao_1", "28/10/2026", objet="Travaux de voirie")
    _avis(db, "ao_2", "22/10/2026", statut="expire", objet="Travaux de voirie")
    R.appliquer()
    assert db.execute("SELECT statut FROM tenders WHERE id='ao_2'").fetchone()[0] == "expire"


def test_autres_sources_et_avis_recents_intacts(db):
    _avis(db, "gm_1", "22/10/2026", source="global-marches")
    _avis(db, "ao_9", "27/10/2026", scraped="2026-10-26 09:00:00")
    assert R.appliquer()["reportes"] == 0
    gm = dict(db.execute("SELECT * FROM tenders WHERE id='gm_1'").fetchone())
    assert R.pour_marche(gm)["etat"] == "possible"


def test_bandeau():
    assert R.report_actif(date(2026, 10, 25)) and not R.report_actif(date(2026, 10, 27))
    assert not R.report_actif(date(2026, 10, 25))["repris"]
    assert R.report_actif(date(2026, 10, 26))["repris"], "le bandeau annonce la réouverture"


def test_fiche(client, db):
    from datetime import timedelta
    db.execute("""INSERT INTO members(id,nom,email,phone,company,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(1,'Ahmed Alaoui','r@x.ma','0612345678','SIMAC','pro','ACTIVE',?,'x',
                  'jeton-report-1',1,'["T101"]',1)""", ((date.today() + timedelta(days=90)).isoformat(),))
    db.commit()
    _avis(db, "ao_1", "22/10/2026")
    R.appliquer()
    client.cookies.set("_session", "jeton-report-1")
    page = client.get("/tenders/ao_1").text
    assert "22/10/2026 → 28/10/2026" in page
