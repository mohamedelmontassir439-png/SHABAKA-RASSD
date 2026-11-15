"""Recentrage du 12/11/2026: fonctions masquées, compteur de visites, preuve
de valeur du compte en attente, veille du relais, raison de l'alerte."""
from datetime import date, datetime, timedelta

import pytest

from app.core.config import cfg

NAVIGATEUR = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}
MASQUE_REEL = ("sous-traitance", "groupements", "financement", "documents", "api")


def _membre(db, statut="PENDING", plan="free", secteurs='["T101"]', jeton="jeton-recentrage-aa",
            email="attente@example.com"):
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified,created_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               ("Samira", email, plan, statut, "", "x", jeton, 1, secteurs, 1,
                datetime.now().isoformat()))
    db.commit()
    return db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()["id"]


def _marche(db, tid="ao_rc1", secteur="T101", objet="Construction d'une école communale à Taroudant"):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,statut,scraped_at,date_limite,
                  type_offre,type_procedure,source,url)
                  VALUES(?,?,'COMMUNE DE TAROUDANT',?,'Taroudant','actif',?,?,'Public','marche',
                  'marchespublics','https://www.marchespublics.gov.ma/x')""",
               (tid, objet, secteur, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                (date.today() + timedelta(days=20)).strftime("%d/%m/%Y")))
    db.commit()


class TestFonctionsMasquees:
    def test_le_reglage_par_defaut_masque_cinq_fonctions(self, monkeypatch):
        monkeypatch.delenv("FONCTIONS_MASQUEES", raising=False)
        from app.core.config import Settings
        assert set(Settings().FONCTIONS_MASQUEES) == set(MASQUE_REEL)
        assert Settings().prefixes_masques() == ("/sous-traitance", "/groupements", "/financement",
                                                 "/documents", "/api/v1")

    def test_les_pages_masquees_repondent_404(self, client, db, monkeypatch):
        monkeypatch.setattr(cfg, "FONCTIONS_MASQUEES", MASQUE_REEL)
        for url in ("/sous-traitance", "/sous-traitance/nouveau", "/groupements", "/financement",
                    "/api/v1/tenders", "/api/v1/stats", "/documents/ME-2026-0001"):
            assert client.get(url).status_code == 404, url
        # Le reste du site vit normalement, administration comprise.
        assert client.get("/").status_code == 200
        assert client.get("/tarifs").status_code == 200

    def test_les_liens_disparaissent(self, client, db, monkeypatch):
        monkeypatch.setattr(cfg, "FONCTIONS_MASQUEES", MASQUE_REEL)
        accueil = client.get("/").text
        assert 'href="/sous-traitance"' not in accueil
        assert "st-spot" not in accueil.split("<body")[-1].split("</style>")[-1]
        for promesse in ("Groupements", "Sous-traitance", "Caution et financement"):
            assert f"<li>{promesse}</li>" not in accueil
        tarifs = client.get("/tarifs").text
        assert "Sous-traitance et groupements" not in tarifs
        _membre(db, statut="ACTIVE", plan="pro")
        client.cookies.set("_session", "jeton-recentrage-aa")
        espace = client.get("/dashboard").text
        for lien in ('href="/groupements"', 'href="/sous-traitance"', 'href="/financement"'):
            assert lien not in espace

    def test_tout_rouvre_quand_la_liste_est_vide(self, client, db, monkeypatch):
        monkeypatch.setattr(cfg, "FONCTIONS_MASQUEES", ())
        assert client.get("/api/v1/stats").status_code == 200
        _membre(db, statut="ACTIVE", plan="pro")
        client.cookies.set("_session", "jeton-recentrage-aa")
        assert 'href="/sous-traitance"' in client.get("/dashboard").text


class TestVisites:
    def test_une_page_vue_par_une_personne_est_comptee(self, client, db):
        from app.services import visites
        assert client.get("/tarifs", headers=NAVIGATEUR).status_code == 200
        assert client.get("/", headers={"user-agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"}).status_code == 200
        assert client.get("/static/img/og.png", headers=NAVIGATEUR).status_code in (200, 404)
        lignes = db.execute("SELECT chemin, evenement FROM visites ORDER BY id").fetchall()
        assert [tuple(l) for l in lignes] == [("/tarifs", "")]
        t = visites.tableau(7)
        assert t["totaux"]["pages"] == 1 and t["totaux"]["visiteurs"] == 1 and t["totaux"]["tarifs"] == 1

    def test_l_empreinte_change_chaque_jour_et_ne_se_renverse_pas(self):
        from app.services import visites
        a = visites.empreinte("41.0.0.1", "Mozilla", "2026-11-12")
        b = visites.empreinte("41.0.0.1", "Mozilla", "2026-11-13")
        assert a != b and len(a) == 16 and "41.0.0.1" not in a

    def test_le_referent_externe_seulement(self):
        from app.services import visites
        assert visites.referent_externe("https://www.facebook.com/groups/x", "marocentrepreneuriat.com") == "facebook.com"
        assert visites.referent_externe("https://marocentrepreneuriat.com/tarifs", "marocentrepreneuriat.com") == ""
        assert visites.referent_externe("", "marocentrepreneuriat.com") == ""

    def test_le_clic_whatsapp_est_compte_puis_redirige(self, client, db):
        _marche(db)
        r = client.get("/aller/whatsapp?ao=ao_rc1", headers=NAVIGATEUR)
        assert r.status_code == 302
        assert r.headers["location"].startswith(f"https://wa.me/{cfg.PAYMENT_PHONE}?text=")
        assert "Taroudant" in __import__("urllib.parse").parse.unquote(r.headers["location"])
        evt = db.execute("SELECT chemin, evenement FROM visites").fetchall()
        assert [tuple(e) for e in evt] == [("/tarifs?ao=ao_rc1", "whatsapp")]
        # Le bouton de la page des tarifs passe par là.
        page = client.get("/tarifs?ao=ao_rc1").text
        assert 'href="/aller/whatsapp?ao=ao_rc1"' in page

    def test_l_inscription_est_comptee(self, client, db):
        client.get("/register", headers=NAVIGATEUR)
        r = client.post("/register", headers=NAVIGATEUR, data={
            "nom": "Karim Alaoui", "email": "karim@example.com", "phone": "0612345678",
            "company": "Alaoui Travaux SARL", "pw": "motdepasse1", "pw2": "motdepasse1",
            "secteurs_sel": ["T101"], "csrf_token": client.cookies.get("_csrf")})
        assert r.status_code == 302, r.text[:300]
        assert db.execute("SELECT COUNT(*) FROM visites WHERE evenement='inscription'").fetchone()[0] == 1

    def test_la_page_admin_des_visites(self, admin, db):
        admin.get("/", headers=NAVIGATEUR)
        page = admin.get("/admin/visites").text
        assert "Pages vues" in page and "Visiteurs" in page and "/" in page
        assert admin.get("/admin/visites?jours=7").status_code == 200


class TestPreuveDeValeur:
    def test_le_compte_en_attente_voit_ce_qu_il_manque(self, client, db):
        _membre(db)
        _marche(db)
        _marche(db, tid="ao_rc2", secteur="S904", objet="Nettoyage des locaux")
        client.cookies.set("_session", "jeton-recentrage-aa")
        page = client.get("/dashboard").text
        assert "Depuis 30 jours, 1 marchés ont été publiés dans vos secteurs" in page
        assert "Construction d'une école communale" in page or "Construction d&#39;une école communale" in page
        assert "Nettoyage des locaux" not in page, "hors de ses secteurs"
        assert "COMMUNE DE TAROUDANT" in page.upper()
        assert 'href="/tenders/ao_rc1"' not in page, "pas de lien vers le détail avant l'abonnement"

    def test_sans_marche_le_message_le_dit(self, client, db):
        _membre(db)
        client.cookies.set("_session", "jeton-recentrage-aa")
        page = client.get("/dashboard").text
        assert "Aucun marché publié dans vos secteurs ces 30 derniers jours" in page


class TestVeilleDuRelais:
    def _depot(self, db, il_y_a_heures: float):
        quand = (datetime.now() - timedelta(hours=il_y_a_heures)).isoformat(timespec="seconds")
        db.execute("""INSERT INTO scraper_runs(source,status,records_found,records_saved,duplicates,errors,
                      duration_ms,message,started_at,finished_at)
                      VALUES('marchespublics','SUCCESS',3,3,0,0,100,'relais local: dépôt',?,?)""", (quand, quand))
        db.commit()

    def test_un_relais_muet_depuis_trois_heures_alerte(self, db):
        from app.services import supervision as sup
        self._depot(db, 5)
        alertes = sup.anomalies(sup.collecter_indicateurs())
        assert any("relais local" in a for a in alertes), alertes

    def test_un_relais_recent_ne_declenche_rien(self, db):
        from app.services import supervision as sup
        self._depot(db, 0.2)
        ind = sup.collecter_indicateurs()
        assert not [a for a in sup.anomalies(ind) if "relais" in a]
        assert "Relais local : dernier dépôt il y a" in sup.bilan_texte(ind)

    def test_sans_relais_jamais_vu_pas_d_alerte(self, db):
        from app.services import supervision as sup
        ind = sup.collecter_indicateurs()
        assert not [a for a in sup.anomalies(ind) if "relais" in a]
        assert "jamais vu" in sup.bilan_texte(ind)


class TestRaisonDeLAlerte:
    def test_la_ligne_nomme_le_secteur_et_le_mot_cle(self):
        from app.services.matching import raison
        from app.core.sectors import get_label
        membre = {"secteurs": '["T101"]', "notif_keywords": "peinture, carrelage", "notif_regions": "[]",
                  "notif_types": "[]", "notif_min_budget": 0}
        marche = {"secteur": "T101", "objet": "Travaux de peinture des façades", "acheteur": "COMMUNE", "description": ""}
        ligne = raison(membre, marche)
        assert get_label("T101") in ligne and "peinture" in ligne and "carrelage" not in ligne

    def test_l_email_porte_la_raison(self):
        from app.services.notifications import build_email
        t = {"id": "ao_1", "objet": "Travaux", "acheteur": "COMMUNE", "secteur": "T101", "url": "https://x",
             "date_limite": "01/12/2026", "source": "marchespublics"}
        assert "🎯 Pourquoi" in build_email(t, "Samira", "secteur « Bâtiment »")
        assert "🎯 Pourquoi" not in build_email(t, "Samira")


class TestClassementIA:
    def test_coupe_par_defaut_meme_avec_une_cle(self, monkeypatch):
        from app.services import classement_ia
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setattr(cfg, "CLASSEMENT_IA", False)
        assert not classement_ia.disponible()
        monkeypatch.setattr(cfg, "CLASSEMENT_IA", True)
        assert classement_ia.disponible()


class TestDisque:
    def test_health_dit_la_cause_quand_la_base_tombe(self, client, db, monkeypatch):
        import main
        def casse():
            raise __import__("sqlite3").OperationalError("database or disk is full")
        monkeypatch.setattr(main, "get_db", casse)
        r = client.get("/health")
        assert r.status_code == 503
        corps = r.json()
        assert corps["status"] == "erreur_base" and "disk is full" in corps["erreur"]
        assert "libre_mo" in corps["disque"]

    def test_les_vieilles_copies_partent(self, tmp_path, monkeypatch):
        import main
        monkeypatch.setattr(main, "BACKUP_DIR", str(tmp_path))
        for i in range(9):
            (tmp_path / f"atlas_2026110{i}_000000.db").write_bytes(b"x")
        (tmp_path / "atlas_20261101_000000.db.gz").write_bytes(b"x")
        main.liberer_disque(garder=5)
        restes = sorted(f.name for f in tmp_path.iterdir())
        assert restes == [f"atlas_2026110{i}_000000.db" for i in range(4, 9)]


class TestCopieExterne:
    def test_grosse_archive_en_morceaux_puis_restauree(self, tmp_path, monkeypatch, db):
        """Une base au-delà du plafond Telegram part en morceaux, et l'outil
        de restauration la recolle à l'identique."""
        import os, random, sqlite3, subprocess, sys
        import main, requests
        monkeypatch.setattr(main, "BACKUP_DIR", str(tmp_path / "copies"))
        monkeypatch.setattr(main, "MORCEAU_MAX", 20_000)
        monkeypatch.setattr(main.cfg, "TELEGRAM_BOT", "123:abc")
        monkeypatch.setattr(main.cfg, "ADMIN_CHAT_ID", "4242")
        # De quoi dépasser 20 ko une fois compressé: du texte peu répétitif.
        rnd = random.Random(1)
        for i in range(400):
            db.execute("INSERT INTO tenders(id,objet,statut,scraped_at) VALUES(?,?,'actif','2026-11-15')",
                       (f"ao_{i}", " ".join(str(rnd.random()) for _ in range(12))))
        db.commit()
        recus = tmp_path / "recus"; recus.mkdir()

        class Rep:
            status_code, text = 200, "{}"

        def faux_post(url, data=None, files=None, timeout=None):
            f = files["document"]
            (recus / os.path.basename(f.name)).write_bytes(f.read())
            return Rep()
        monkeypatch.setattr(requests, "post", faux_post)

        chemin = main.make_db_backup()
        assert chemin and main.envoyer_sauvegarde_telegram(chemin) is True
        etat = main._etat_externe()
        assert etat["ok"] and etat["morceaux"] >= 2
        assert len(list(recus.iterdir())) == etat["morceaux"]
        assert not [f for f in os.listdir(main.BACKUP_DIR) if ".gz" in f], "pas de reste sur le disque"

        sortie = tmp_path / "restauree.db"
        r = subprocess.run([sys.executable, "outils/restaurer_sauvegarde.py", str(recus), str(sortie)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert ": ok, 400 march" in r.stdout
        assert sqlite3.connect(sortie).execute("SELECT COUNT(*) FROM tenders").fetchone()[0] == 400

    def test_echec_note_dans_l_etat(self, tmp_path, monkeypatch):
        import main, requests
        monkeypatch.setattr(main, "BACKUP_DIR", str(tmp_path))
        monkeypatch.setattr(main.cfg, "TELEGRAM_BOT", "123:abc")
        monkeypatch.setattr(main.cfg, "ADMIN_CHAT_ID", "4242")
        class Rep:
            status_code, text = 413, "Request Entity Too Large"
        monkeypatch.setattr(requests, "post", lambda *a, **k: Rep())
        f = tmp_path / "atlas_20261115_000000.db"; f.write_bytes(b"x" * 100)
        assert main.envoyer_sauvegarde_telegram(str(f)) is False
        assert main._etat_externe()["ok"] is False and "413" in main._etat_externe()["erreur"]
