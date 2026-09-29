"""Aucune alerte perdue, bons de commande compris.

Les alertes ne partaient que pour les marchés gardés en mémoire pendant la
collecte: un redémarrage entre l'écriture en base et l'envoi les perdait, et
un import lancé depuis l'admin n'alertait personne. Constaté en production le
22/09/2026: 11 bons de commande du portail collectés sans aucune alerte.
"""
from datetime import date, datetime, timedelta

import pytest

import app.services.notifications as notif


def _membre(db, email="m@example.com", **kw):
    champs = dict(nom="Ahmed", email=email, plan="free", subscription_status="TRIAL",
                  trial_ends=(date.today() + timedelta(days=5)).strftime("%Y-%m-%d"),
                  notif_email=1, notif_tg=0, notif_wa=0, notif_digest=0, actif=1,
                  secteurs='["T101"]', notif_types='[]', email_verified=1)
    champs.update(kw)
    cols = ",".join(champs)
    db.execute(f"INSERT INTO members({cols}) VALUES({','.join('?' * len(champs))})",
               list(champs.values()))
    db.commit()
    return db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()["id"]


def _marche(db, tid, procedure="bon_commande", secteur="T101", minutes=10):
    quand = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,scraped_at,
                  date_limite,type_offre,type_procedure,source)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
               (tid, f"ACHAT POUR {tid}", "COMMUNE", secteur, "actif", quand,
                (date.today() + timedelta(days=9)).strftime("%d/%m/%Y"),
                "Public", procedure, "marchespublics"))
    db.commit()


@pytest.fixture()
def envois(monkeypatch):
    captures = []
    monkeypatch.setattr(notif, "email_send",
                        lambda to, sujet, html: captures.append((to, sujet)) or True)
    monkeypatch.setattr(notif, "tg_admin", lambda *a, **k: None)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return captures


class TestBonsDeCommande:
    def test_un_bon_de_commande_declenche_une_alerte(self, db, envois):
        _membre(db)
        _marche(db, "bdc_1")
        notif.dispatch_notifications([dict(db.execute(
            "SELECT * FROM tenders WHERE id='bdc_1'").fetchone())])
        assert len(envois) == 1

    def test_filtre_de_type_respecte(self, db, envois):
        # Un membre qui ne veut que des appels d'offres ne reçoit pas les
        # bons de commande — et inversement.
        _membre(db, notif_types='["marche"]')
        _marche(db, "bdc_2")
        notif.dispatch_notifications([dict(db.execute(
            "SELECT * FROM tenders WHERE id='bdc_2'").fetchone())])
        assert envois == []


class TestRattrapage:
    def test_marche_ecrit_sans_alerte_est_repris(self, db, envois):
        _membre(db)
        _marche(db, "bdc_oublie")          # écrit en base, jamais notifié
        assert notif.dispatch_pending() == 1
        assert len(envois) == 1

    def test_pas_de_doublon_apres_rattrapage(self, db, envois):
        _membre(db)
        _marche(db, "bdc_3")
        notif.dispatch_pending()
        notif.dispatch_pending()
        assert len(envois) == 1, "la déduplication empêche un second envoi"

    def test_marche_trop_ancien_ignore(self, db, envois):
        _membre(db)
        _marche(db, "bdc_vieux", minutes=60 * 24 * 5)
        assert notif.dispatch_pending(heures=48) == 0
        assert envois == []

    def test_marche_clos_non_repris(self, db, envois):
        _membre(db)
        _marche(db, "bdc_clos")
        db.execute("UPDATE tenders SET statut='expire' WHERE id='bdc_clos'")
        db.commit()
        assert notif.dispatch_pending() == 0

    def test_rafale_limitee_par_passage(self, db, envois):
        """Après un gros import, le membre ne reçoit pas 300 emails d'un coup."""
        _membre(db)
        for i in range(50):
            _marche(db, f"bdc_masse_{i}")
        notif.dispatch_pending()
        assert len(envois) == 40, "plafond par membre et par passage"

        # Le reste part au passage suivant: rien n'est perdu.
        notif.dispatch_pending()
        assert len(envois) == 50


class TestConvergenceDuRattrapage:
    """Un marché que personne n'a demandé ne doit pas revenir chaque cycle.

    Le rattrapage sélectionnait les marchés dépourvus de ligne dans
    notif_log. Or un marché écarté par les filtres n'en produit aucune: il
    était repris indéfiniment. Constaté en production le 29/09/2026, dans les
    journaux: « 400 marché(s) sans alerte — reprise » puis « 400 filtrés », à
    chaque cycle, 400 étant exactement le plafond de la requête.
    """

    def test_marche_sans_preneur_nest_repris_quune_fois(self, db, envois):
        _membre(db, secteurs='["T101"]')
        _marche(db, "bdc_hors_secteur", secteur="T999")

        assert notif.dispatch_pending() == 1, "premier passage: le marché est évalué"
        assert envois == [], "aucun membre ne le demande"
        assert notif.dispatch_pending() == 0, "il ne revient pas au passage suivant"

    def test_marche_reporte_par_le_plafond_reste_repechable(self, db, envois):
        # Le marquage ne doit pas avaler ce que le plafond par passage a
        # simplement remis à plus tard.
        _membre(db)
        for i in range(50):
            _marche(db, f"bdc_p_{i}")
        notif.dispatch_pending()
        assert len(envois) == 40
        assert notif.dispatch_pending() == 10, "le reste est toujours en attente"
        assert len(envois) == 50

    def test_les_plus_anciens_passent_en_premier(self, db, envois):
        # La fenêtre étant plafonnée, on sert d'abord ce qui est le plus près
        # de sortir des 48 heures — sinon un marché ancien n'entre jamais.
        _membre(db)
        _marche(db, "bdc_recent", minutes=5)
        _marche(db, "bdc_ancien", minutes=60 * 40)
        notif.dispatch_pending(limite=1)
        assert len(envois) == 1
        assert "bdc_ancien" in db.execute(
            "SELECT tender_id FROM notif_log ORDER BY id DESC LIMIT 1").fetchone()[0]

    def test_un_nouveau_membre_recoit_les_marches_deja_evalues(self, db, envois):
        # Sans réouverture, un marché évalué avant l'arrivée du membre lui
        # resterait invisible alors qu'il est encore ouvert.
        _marche(db, "bdc_avant")
        notif.dispatch_pending()
        assert envois == []

        _membre(db, email="nouveau@example.com")
        assert notif.rouvrir_rattrapage() == 1
        notif.dispatch_pending()
        assert len(envois) == 1

    def test_la_reouverture_ne_renvoie_pas_aux_deja_servis(self, db, envois):
        _membre(db)
        _marche(db, "bdc_servi")
        notif.dispatch_pending()
        assert len(envois) == 1

        notif.rouvrir_rattrapage()
        notif.dispatch_pending()
        assert len(envois) == 1, "notif_log empêche le doublon"

    def test_la_reouverture_ignore_les_marches_hors_fenetre(self, db, envois):
        _membre(db)
        _marche(db, "bdc_vieux2", minutes=60 * 24 * 5)
        db.execute("UPDATE tenders SET alertes_faites_at='2026-01-01' WHERE id='bdc_vieux2'")
        db.commit()
        assert notif.rouvrir_rattrapage(heures=48) == 0
