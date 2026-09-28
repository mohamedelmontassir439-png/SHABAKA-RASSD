"""Corrections issues de l'audit système du 28/09/2026.

Trois défauts mesurés en production:
  1. le compteur anti-force-brute se dispersait (12 tentatives → 9 bloquées,
     mais 8 inscriptions → 1 seule bloquée): il comptait par nœud de
     l'hébergeur au lieu de compter par visiteur;
  2. la supervision alertait chaque nuit « aucun marché collecté » alors que
     les acheteurs publics ne publient tout simplement pas la nuit —
     15 fausses alertes en une semaine;
  3. 56 groupes de doublons subsistaient, antérieurs au filtre.
"""
from datetime import date, datetime, timedelta

import pytest
from starlette.requests import Request

import main
from app.core.config import cfg
from app.services import supervision as sup


def _requete(headers: dict, client=("10.0.0.9", 1234)) -> Request:
    entetes = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": entetes,
                    "query_string": b"", "client": client, "scheme": "https",
                    "server": ("marocentrepreneuriat.com", 443), "root_path": "",
                    "app": main.app})


class TestIdentificationDuVisiteur:
    def test_x_real_ip_prioritaire(self):
        # C'est l'en-tête posé par le proxy: il désigne le vrai client.
        req = _requete({"x-real-ip": "41.250.1.2",
                        "x-forwarded-for": "41.250.1.2, 10.1.2.3"})
        assert main.get_ip(req) == "41.250.1.2"

    def test_sans_x_real_ip_on_prend_le_premier_maillon(self):
        req = _requete({"x-forwarded-for": "41.250.1.2, 10.1.2.3, 10.4.5.6"})
        assert main.get_ip(req) == "41.250.1.2"

    def test_le_noeud_interne_ne_sert_plus_de_cle(self):
        """Deux requêtes du même visiteur passées par deux nœuds différents
        doivent compter dans le même seau."""
        a = main.get_ip(_requete({"x-forwarded-for": "41.250.1.2, 10.0.0.1"}))
        b = main.get_ip(_requete({"x-forwarded-for": "41.250.1.2, 10.0.0.2"}))
        assert a == b

    def test_repli_sur_la_connexion(self):
        assert main.get_ip(_requete({})) == "10.0.0.9"


class TestForceBrute:
    def test_blocage_apres_cinq_essais(self, monkeypatch):
        monkeypatch.setattr(main, "_login_attempts", __import__("collections").defaultdict(list))
        resultats = [main.check_rate_limit("41.250.1.2") for _ in range(8)]
        assert resultats[:5] == [True] * 5
        assert resultats[5:] == [False] * 3

    def test_deux_visiteurs_independants(self, monkeypatch):
        monkeypatch.setattr(main, "_login_attempts", __import__("collections").defaultdict(list))
        for _ in range(5):
            main.check_rate_limit("41.250.1.2")
        assert main.check_rate_limit("41.250.9.9") is True, "un visiteur n'en bloque pas un autre"


@pytest.fixture()
def sauvegarde_fraiche(tmp_path, monkeypatch):
    (tmp_path / "atlas_20260928_080000.db").write_bytes(b"SQLite format 3\x00")
    monkeypatch.setattr(sup, "DOSSIER_SAUVEGARDES", str(tmp_path))


@pytest.mark.usefixtures("sauvegarde_fraiche")
class TestSupervisionNocturne:
    def _run(self, db, statut="SUCCESS", il_y_a_heures=1):
        db.execute("""INSERT INTO scraper_runs(source,status,started_at,records_found,
                      records_saved,errors) VALUES('marchespublics',?,?,0,0,0)""",
                   (statut, (datetime.now() - timedelta(hours=il_y_a_heures)).isoformat()))
        db.commit()

    def _marche(self, db, heures):
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,scraped_at,date_limite,
                      type_offre,type_procedure) VALUES(?,?,?,?,?,?,?,?)""",
                   (f"t{heures}", "TRAVAUX", "T101", "actif",
                    (datetime.now() - timedelta(hours=heures)).strftime("%Y-%m-%d %H:%M:%S"),
                    "30/12/2026", "Public", "marche"))
        db.commit()

    def test_nuit_calme_sans_alerte(self, db, monkeypatch):
        """La veille tourne, mais personne n'a publié depuis 9 h: c'est la nuit."""
        self._run(db, il_y_a_heures=1)
        self._marche(db, heures=9)
        alertes = []
        monkeypatch.setattr("app.services.notifications.tg_admin", lambda m: alertes.append(m))
        sup.verifier()
        assert alertes == [], "les acheteurs publics ne publient pas la nuit"

    def test_collecte_arretee_alerte(self, db, monkeypatch):
        """Aucune exécution depuis plus de 3 h: là, c'est une panne."""
        self._run(db, il_y_a_heures=5)
        self._marche(db, heures=5)
        alertes = []
        monkeypatch.setattr("app.services.notifications.tg_admin", lambda m: alertes.append(m))
        sup.verifier()
        assert alertes and "ne s'exécute plus" in alertes[0]


class TestNettoyageDoublons:
    def _marche(self, db, tid, objet, montant="", acheteur="", quand="2026-09-20 08:00:00"):
        db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,montant,statut,
                      scraped_at,date_limite,type_offre,type_procedure,source)
                      VALUES(?,?,?,?,?,?,'actif',?,?,?,?,?)""",
                   (tid, objet, acheteur, "T101", "", montant, quand, "30/12/2026",
                    "Public", "marche", "global-marches"))
        db.commit()

    @pytest.fixture()
    def admin(self, client):
        client.get("/admin/login")
        client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS,
                                          "csrf_token": client.cookies.get("_csrf")})
        return client

    def test_simulation_sans_rien_modifier(self, admin, db):
        self._marche(db, "a1", "Travaux de réhabilitation du lycée")
        self._marche(db, "a2", "TRAVAUX DE RÉHABILITATION DU LYCÉE !")
        r = admin.get("/admin/nettoyer-doublons").json()
        assert r["groupes"] == 1 and r["exemplaires"] == 1 and r["applique"] is False
        assert db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0] == 2

    def test_application_garde_le_plus_complet(self, admin, db):
        self._marche(db, "pauvre", "Travaux de réhabilitation du lycée")
        self._marche(db, "riche", "Travaux de réhabilitation du lycée",
                     montant="1 200 000 MAD", acheteur="COMMUNE")
        admin.get("/admin/nettoyer-doublons?appliquer=1")
        statut = lambda t: db.execute("SELECT statut FROM tenders WHERE id=?", (t,)).fetchone()[0]
        assert statut("riche") == "actif", "on garde l'exemplaire renseigné"
        assert statut("pauvre") == "expire"

    def test_marches_distincts_intacts(self, admin, db):
        self._marche(db, "x1", "Travaux de voirie à Salé")
        self._marche(db, "x2", "Fourniture de mobilier de bureau")
        r = admin.get("/admin/nettoyer-doublons?appliquer=1").json()
        assert r["groupes"] == 0
        assert db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0] == 2
