# -*- coding: utf-8 -*-
"""Le script d'appel affiché sur la fiche.

Un script générique se récite et s'entend. Celui-ci ne tient que parce qu'il
nomme un marché réel, ouvert, dans le secteur de l'entreprise appelée — une
chose que l'interlocuteur peut vérifier après avoir raccroché.
"""
import html
from datetime import date, timedelta

import pytest

from app.core.config import cfg


@pytest.fixture()
def admin(client):
    client.get("/admin/login")
    client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                      "csrf_token": client.cookies.get("_csrf")})
    return client


def _entreprise(db, secteur="T101", ville="Casablanca"):
    db.execute("""INSERT INTO companies(legal_name,normalized_name,sector,city,phone,
                  source,created_at) VALUES('BTP ATLAS SARL','btp atlas',?,?,'0612345678',
                  'google-maps','2026-09-01T09:00:00')""", (secteur, ville))
    db.commit()
    return db.execute("SELECT id FROM companies WHERE normalized_name='btp atlas'").fetchone()["id"]


def _marche(db, secteur="T101", objet="TRAVAUX DE CONSTRUCTION D'UNE ECOLE"):
    # L'identifiant se dérive du compte: plusieurs marchés par test sont
    # nécessaires pour vérifier l'accord du pluriel.
    tid = "t_sc%d" % db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure)
                  VALUES(?,?,'COMMUNE DE CASABLANCA',?,'Casablanca','1 200 000,00 MAD',
                  'actif','2026-09-22 08:00:00',?,'Public','marche')""",
               (tid, objet, secteur,
                (date.today() + timedelta(days=12)).strftime("%d/%m/%Y")))
    db.commit()


class TestContenu:
    def test_le_script_apparait_sur_la_fiche(self, admin, db):
        cid = _entreprise(db)
        page = html.unescape(admin.get(f"/admin/prospection/{cid}").text)
        assert "Script d'appel" in page

    def test_il_cite_un_marche_reel_du_secteur(self, admin, db):
        cid = _entreprise(db)
        _marche(db)
        assert "ECOLE" in admin.get(f"/admin/prospection/{cid}").text

    def test_il_annonce_le_nombre_de_marches_ouverts(self, admin, db):
        """Au singulier quand il n'y en a qu'un: le script se dit à voix haute."""
        cid = _entreprise(db)
        _marche(db)
        texte = html.unescape(admin.get(f"/admin/prospection/{cid}").text)
        assert "1 marché public ouvert en" in texte
        assert "marché(s)" not in texte

    def test_il_accorde_le_pluriel(self, admin, db):
        cid = _entreprise(db)
        _marche(db, objet="PREMIER MARCHE")
        _marche(db)
        texte = html.unescape(admin.get(f"/admin/prospection/{cid}").text)
        assert "2 marchés publics ouverts en" in texte

    def test_il_nomme_la_ville_de_lentreprise(self, admin, db):
        cid = _entreprise(db, ville="Agadir")
        assert "Agadir" in admin.get(f"/admin/prospection/{cid}").text

    def test_il_annonce_la_duree_reelle_de_lessai(self, admin, db):
        cid = _entreprise(db)
        assert f"{cfg.TRIAL_DAYS} jours gratuits" in admin.get(f"/admin/prospection/{cid}").text


class TestSansPreuve:
    """Sans marché ouvert, le script doit le dire au lieu d'inventer."""

    def test_il_conseille_de_rappeler_plus_tard(self, admin, db):
        cid = _entreprise(db, secteur="T999")
        texte = html.unescape(admin.get(f"/admin/prospection/{cid}").text)
        assert "Aucun marché ouvert dans ce secteur" in texte
        assert "rappeler cette entreprise un jour où il y en a" in texte


class TestObjections:
    def test_les_quatre_objections_sont_la(self, admin, db):
        cid = _entreprise(db)
        texte = html.unescape(admin.get(f"/admin/prospection/{cid}").text)
        for objection in ("Envoyez-moi un email", "C'est combien", "déjà quelqu'un",
                          "Ça ne m'intéresse pas"):
            assert objection in texte, objection

    def test_le_refus_renvoie_vers_le_bon_statut(self, admin, db):
        """La loi 09-08: un refus doit être enregistré, pas seulement entendu."""
        cid = _entreprise(db)
        assert "Ne plus contacter" in admin.get(f"/admin/prospection/{cid}").text
