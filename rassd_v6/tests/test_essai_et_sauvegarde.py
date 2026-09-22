"""Accompagnement de l'essai gratuit, sauvegarde hors Railway, bons de commande.

Un inscrit était laissé seul pendant sept jours, les sauvegardes dormaient
sur le même disque que la base, et les bons de commande affichaient une case
« montant » vide alors que le portail publie la quantité commandée.
"""
from datetime import date, datetime, timedelta

import pytest

import main
import app.services.notifications as notif
from app.services import scraper as sc


def _membre(db, email="essai@example.com", jours_depuis=0, **kw):
    debut = (date.today() - timedelta(days=jours_depuis)).strftime("%Y-%m-%d")
    champs = dict(nom="Ahmed", email=email, plan="free", subscription_status="TRIAL",
                  trial_start=debut,
                  trial_ends=(date.today() + timedelta(days=7 - jours_depuis)).strftime("%Y-%m-%d"),
                  notif_email=1, notif_tg=0, notif_wa=0, notif_digest=0, actif=1,
                  secteurs='["T101"]', email_verified=1, trial_seq=0,
                  created_at=f"{debut}T09:00:00")
    champs.update(kw)
    cols = ",".join(champs)
    db.execute(f"INSERT INTO members({cols}) VALUES({','.join('?' * len(champs))})",
               list(champs.values()))
    db.commit()
    return db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()["id"]


@pytest.fixture()
def envois(monkeypatch):
    captures = []
    monkeypatch.setattr(notif, "email_send",
                        lambda to, sujet, html: captures.append((to, sujet, html)) or True)
    return captures


class TestSequenceEssai:
    def test_bienvenue_le_jour_de_l_inscription(self, db, envois):
        _membre(db, jours_depuis=0)
        assert notif.send_trial_sequence() == 1
        assert "2 minutes" in envois[0][1] or "secteurs" in envois[0][2]

    def test_une_seule_etape_par_passage(self, db, envois):
        _membre(db, jours_depuis=0)
        notif.send_trial_sequence()
        assert notif.send_trial_sequence() == 0, "aucune relance le même jour"
        assert len(envois) == 1

    def test_etape_j5_pour_un_essai_de_cinq_jours(self, db, envois):
        mid = _membre(db, jours_depuis=5)
        notif.send_trial_sequence()
        # Le membre saute directement à l'étape utile: on ne lui envoie pas
        # trois emails de rattrapage d'un coup.
        assert len(envois) == 1
        assert db.execute("SELECT trial_seq FROM members WHERE id=?", (mid,)).fetchone()[0] == 3

    def test_rien_pour_une_adresse_non_confirmee(self, db, envois):
        _membre(db, email_verified=0)
        assert notif.send_trial_sequence() == 0 and envois == []

    def test_abonne_payant_ignore_la_relance_finale(self, db, envois):
        mid = _membre(db, jours_depuis=7, subscription_status="ACTIVE")
        notif.send_trial_sequence()
        assert envois == [], "on ne relance pas un membre qui paie déjà"
        assert db.execute("SELECT trial_seq FROM members WHERE id=?", (mid,)).fetchone()[0] == 4

    def test_echec_d_envoi_non_marque_comme_fait(self, db, monkeypatch):
        mid = _membre(db)
        monkeypatch.setattr(notif, "email_send", lambda *a, **k: False)
        notif.send_trial_sequence()
        assert db.execute("SELECT trial_seq FROM members WHERE id=?", (mid,)).fetchone()[0] == 0


class TestSauvegardeHorsRailway:
    def _fichier(self, tmp_path):
        chemin = tmp_path / "atlas_test.db"
        chemin.write_bytes(b"SQLite format 3\x00" + b"donnees" * 500)
        return str(chemin)

    def test_document_envoye_compresse(self, tmp_path, monkeypatch):
        appels = {}

        class Rep:
            status_code, text = 200, "{}"

        def faux_post(url, data=None, files=None, timeout=None):
            appels["url"] = url
            appels["chat"] = data["chat_id"]
            appels["taille"] = len(files["document"].read())
            return Rep()

        monkeypatch.setattr(main.cfg, "TELEGRAM_BOT", "123:abc")
        monkeypatch.setattr(main.cfg, "ADMIN_CHAT_ID", "4242")
        import requests
        monkeypatch.setattr(requests, "post", faux_post)

        chemin = self._fichier(tmp_path)
        assert main.envoyer_sauvegarde_telegram(chemin) is True
        assert appels["url"].endswith("/sendDocument")
        assert appels["chat"] == "4242"
        assert 0 < appels["taille"] < 3600, "l'archive est compressée"
        import os
        assert not os.path.exists(chemin + ".gz"), "l'archive temporaire est supprimée"

    def test_sans_telegram_configure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main.cfg, "TELEGRAM_BOT", "")
        assert main.envoyer_sauvegarde_telegram(self._fichier(tmp_path)) is False


class TestBonDeCommandeQuantite:
    FICHE = """<html><body><p>
      Détails de l'avis d'achat #BC14/2026
      Objet ACHAT DE MATERIEL INFORMATIQUE POUR LA DIRECTION
      Détails Acheteur public DIRECTION PROVINCIALE
      Date limite de réception des devis {limite} 16:30
      Lieu d'exécution IFRANE
      Catégorie principale Fournitures
      Nature de prestation Matériel informatique et accessoires
      Articles Caractéristiques et spécifications Unité de mesure u Quantité 25 TVA (%) 20
    </p></body></html>"""

    def _fiche(self):
        limite = (date.today() + timedelta(days=5)).strftime("%d/%m/%Y")
        return self.FICHE.replace("{limite}", limite) + " " * 1600

    def test_quantite_et_nature_collectees(self):
        t = sc.parse_page(self._fiche(), "1")
        assert t["quantite"] == "25 u"
        assert t["nature"] == "Matériel informatique et accessoires"

    def test_toujours_pas_de_montant_invente(self):
        assert sc.parse_page(self._fiche(), "1")["montant"] == ""

    def test_affichage_de_la_quantite(self, client, db):
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,scraped_at,date_limite,
                      type_offre,type_procedure,source,quantite,nature)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                   ("bdc_q", "ACHAT DE MATERIEL INFORMATIQUE", "P818", "actif",
                    "2026-09-22 08:00:00",
                    (date.today() + timedelta(days=5)).strftime("%d/%m/%Y"),
                    "Public", "bon_commande", "marchespublics", "25 u",
                    "Matériel informatique"))
        db.commit()
        client.get("/register")
        client.post("/register", data={
            "email": "bc@example.com", "pw": "MotDePasse1!", "pw2": "MotDePasse1!",
            "nom": "BC", "csrf_token": client.cookies.get("_csrf")})
        db.execute("UPDATE members SET email_verified=1 WHERE email=?", ("bc@example.com",))
        db.commit()

        page = client.get("/bons-de-commande")
        assert "25 u" in page.text, "la quantité remplace la case montant vide"
