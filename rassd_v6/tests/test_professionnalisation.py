"""Supervision, relances d'abonnement, pages publiques, doublons.

Quatre manques relevés sur la production du 22/09/2026: personne n'était
prévenu si la veille s'arrêtait, un abonné payant pouvait être coupé sans
préavis, le site n'exposait que quatre URLs aux moteurs de recherche, et
65 marchés existaient en double.
"""
from datetime import date, datetime, timedelta

import pytest

import main
import app.services.notifications as notif
from app.services import supervision as sup


def _membre(db, email="abo@example.com", **kw):
    champs = dict(nom="Ahmed", email=email, plan="monthly",
                  subscription_status="ACTIVE", subscription_end="",
                  trial_ends=(date.today() + timedelta(days=30)).strftime("%Y-%m-%d"),
                  notif_email=1, notif_tg=0, notif_wa=0, notif_digest=0, actif=1,
                  secteurs='["T101"]', email_verified=1)
    champs.update(kw)
    cols = ",".join(champs)
    db.execute(f"INSERT INTO members({cols}) VALUES({','.join('?' * len(champs))})",
               list(champs.values()))
    db.commit()
    return db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()["id"]


def _marche(db, tid, objet="TRAVAUX DE VOIRIE", secteur="T101", heures=1, statut="actif",
            limite="30/12/2026", source="marchespublics"):
    quand = (datetime.now() - timedelta(hours=heures)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                  scraped_at,date_limite,type_offre,type_procedure,source)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
               (tid, objet, "COMMUNE", secteur, "Casablanca", "", statut, quand,
                limite, "Public", "marche", source))
    db.commit()


@pytest.fixture()
def sauvegarde_fraiche(tmp_path, monkeypatch):
    """Isole la vérification des sauvegardes du dossier réel de la machine."""
    (tmp_path / "atlas_20260923_080000.db").write_bytes(b"SQLite format 3\x00")
    monkeypatch.setattr(sup, "DOSSIER_SAUVEGARDES", str(tmp_path))


@pytest.mark.usefixtures("sauvegarde_fraiche")
class TestSupervision:
    def test_veille_arretee_declenche_une_alerte(self, db, monkeypatch):
        _marche(db, "t_vieux", heures=30)
        alertes = []
        monkeypatch.setattr(notif, "tg_admin", lambda m: alertes.append(m))
        ind = sup.verifier()
        assert ind["heures_sans_marche"] > 6
        assert alertes and "Aucun marché collecté" in alertes[0]

    def test_veille_normale_ne_reveille_personne(self, db, monkeypatch):
        _marche(db, "t_frais", heures=1)
        alertes = []
        monkeypatch.setattr(notif, "tg_admin", lambda m: alertes.append(m))
        sup.verifier()
        assert alertes == []

    def test_alerte_non_repetee_dans_les_six_heures(self, db, monkeypatch):
        _marche(db, "t_vieux", heures=30)
        alertes = []
        monkeypatch.setattr(notif, "tg_admin", lambda m: alertes.append(m))
        sup.verifier()
        sup.verifier()
        assert len(alertes) == 1, "un canal qui répète la même alerte n'est plus lu"

    def test_collectes_en_echec_signalees(self, db, monkeypatch):
        _marche(db, "t_frais", heures=1)
        for i in range(3):
            db.execute("""INSERT INTO scraper_runs(source,status,started_at,records_found,
                          records_saved,errors) VALUES('marchespublics','FAILED',?,0,0,1)""",
                       (datetime.now().isoformat(),))
        db.commit()
        alertes = []
        monkeypatch.setattr(notif, "tg_admin", lambda m: alertes.append(m))
        sup.verifier()
        assert alertes and "collecte(s) en échec" in alertes[0]

    def test_bilan_quotidien_chiffre(self, db, monkeypatch):
        _marche(db, "t_frais", heures=1)
        _membre(db)
        envois = []
        monkeypatch.setattr(notif, "tg_admin", lambda m: envois.append(m))
        sup.verifier(envoyer_bilan=True)
        bilan = envois[-1]
        assert "Bilan du" in bilan and "Marchés actifs" in bilan and "Membres" in bilan


class TestRelancesAbonnement:
    def _envois(self, monkeypatch):
        captures = []
        monkeypatch.setattr(notif, "email_send",
                            lambda to, sujet, html: captures.append((to, sujet)) or True)
        return captures

    @pytest.mark.parametrize("dans_jours,attendu", [(7, True), (1, True), (0, True),
                                                    (9, False), (-1, False)])
    def test_fenetre_de_relance(self, db, monkeypatch, dans_jours, attendu):
        fin = (date.today() + timedelta(days=dans_jours)).strftime("%Y-%m-%d")
        _membre(db, subscription_end=fin)
        envois = self._envois(monkeypatch)
        notif.send_renewal_reminders()
        assert bool(envois) is attendu

    def test_une_seule_relance_par_etape(self, db, monkeypatch):
        _membre(db, subscription_end=(date.today() + timedelta(days=7)).strftime("%Y-%m-%d"))
        envois = self._envois(monkeypatch)
        notif.send_renewal_reminders()
        notif.send_renewal_reminders()
        assert len(envois) == 1

    def test_essai_gratuit_non_concerne(self, db, monkeypatch):
        # L'essai a sa propre séquence: le relancer ici ferait doublon.
        _membre(db, subscription_status="TRIAL",
                subscription_end=(date.today() + timedelta(days=1)).strftime("%Y-%m-%d"))
        envois = self._envois(monkeypatch)
        notif.send_renewal_reminders()
        assert envois == []

    def test_adresse_non_confirmee_ignoree(self, db, monkeypatch):
        _membre(db, email_verified=0,
                subscription_end=(date.today() + timedelta(days=1)).strftime("%Y-%m-%d"))
        envois = self._envois(monkeypatch)
        notif.send_renewal_reminders()
        assert envois == []


class TestPagesPubliques:
    def test_index_accessible_sans_compte(self, client, db):
        _marche(db, "t_seo")
        page = client.get("/marches-publics")
        assert page.status_code == 200
        assert "Constructions" in page.text

    def test_page_secteur_montre_le_volume(self, client, db):
        _marche(db, "t_seo", objet="TRAVAUX DE VOIRIE COMMUNALE")
        slug = main._slug("Constructions, bâtiments & ouvrages d'art")
        page = client.get(f"/marches-publics/{slug}")
        assert page.status_code == 200
        assert "TRAVAUX DE VOIRIE COMMUNALE" in page.text
        assert "canonical" in page.text and "og:title" in page.text

    def test_page_secteur_ne_livre_pas_le_detail(self, client, db):
        # L'aperçu attire; l'acheteur et le lien officiel restent aux membres.
        _marche(db, "t_seo")
        slug = main._slug("Constructions, bâtiments & ouvrages d'art")
        page = client.get(f"/marches-publics/{slug}")
        assert "réservés aux membres" in page.text
        assert "/tenders/t_seo" not in page.text

    def test_secteur_inconnu(self, client):
        assert client.get("/marches-publics/secteur-invente").status_code == 404

    def test_sitemap_liste_les_secteurs(self, client, db):
        _marche(db, "t_seo")
        xml = client.get("/sitemap.xml").text
        assert xml.count("<loc>") > 50, "un plan de site à 4 URLs n'existe pas pour Google"
        assert "/marches-publics/" in xml
        assert "<?xml" in xml and "\n" in xml


class TestDoublons:
    def test_meme_marche_de_deux_sources(self, db):
        _marche(db, "gm_1", objet="Travaux d'assainissement du quartier Riad",
                source="global-marches")
        ajoutes = []
        n = main._save_tenders([{
            "id": "bdc_1", "objet": "TRAVAUX D'ASSAINISSEMENT DU QUARTIER RIAD !",
            "acheteur": "COMMUNE", "secteur": "T101", "region": "", "montant": "",
            "date_publication": "", "date_limite": "30/12/2026", "description": "",
            "url": "http://x", "statut": "actif",
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "marchespublics", "type_procedure": "marche"}], ajoutes)
        assert n == 0 and ajoutes == []
        assert db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0] == 1

    def test_marche_different_bien_enregistre(self, db):
        _marche(db, "gm_1", objet="Travaux d'assainissement du quartier Riad",
                source="global-marches")
        ajoutes = []
        n = main._save_tenders([{
            "id": "bdc_2", "objet": "Fourniture de mobilier de bureau",
            "acheteur": "COMMUNE", "secteur": "P805", "region": "", "montant": "",
            "date_publication": "", "date_limite": "30/12/2026", "description": "",
            "url": "http://y", "statut": "actif",
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "marchespublics", "type_procedure": "marche"}], ajoutes)
        assert n == 1 and len(ajoutes) == 1

    def test_meme_objet_mais_echeance_differente(self, db):
        # Deux lots successifs portent souvent le même intitulé: seule la
        # date limite les distingue, on ne doit pas en perdre un.
        _marche(db, "gm_1", objet="Entretien des espaces verts", limite="10/10/2026",
                source="global-marches")
        ajoutes = []
        n = main._save_tenders([{
            "id": "bdc_3", "objet": "Entretien des espaces verts",
            "acheteur": "COMMUNE", "secteur": "T111", "region": "", "montant": "",
            "date_publication": "", "date_limite": "25/11/2026", "description": "",
            "url": "http://z", "statut": "actif",
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "marchespublics", "type_procedure": "marche"}], ajoutes)
        assert n == 1
