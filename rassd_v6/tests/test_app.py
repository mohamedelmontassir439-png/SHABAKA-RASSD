"""Contrôles d'accès, paiements/documents et pages publiques."""
import re

import pytest


def _register(client, email="membre@example.com", **extra):
    client.get("/register")
    token = client.cookies.get("_csrf")
    data = {"email": email, "pw": "MotDePasse1!", "pw2": "MotDePasse1!",
            "nom": "Membre Test", "csrf_token": token}
    data.update(extra)
    return client.post("/register", data=data)


def _login_admin(client):
    from app.core.config import cfg
    client.get("/admin/login")
    token = client.cookies.get("_csrf")
    return client.post("/admin/login", data={"pwd": cfg.ADMIN_PASS, "csrf_token": token})


class TestPagesPubliques:
    @pytest.mark.parametrize("path", [
        "/", "/tarifs", "/login", "/register",
        "/mentions-legales", "/cgu", "/confidentialite", "/contact",
    ])
    def test_accessibles_sans_compte(self, client, path):
        assert client.get(path).status_code == 200

    def test_offre_mensuelle_affichee(self, client):
        page = client.get("/tarifs").text
        assert "250" in page and "Mensuel" in page

    def test_pages_legales_ont_du_contenu_reel(self, client):
        assert "Éditeur du site" in client.get("/mentions-legales").text
        assert "loi n° 09-08" in client.get("/confidentialite").text
        assert "Droit applicable" in client.get("/cgu").text


class TestControleAcces:
    @pytest.mark.parametrize("path", [
        "/dashboard", "/settings", "/favorites", "/mon-abonnement",
        "/sous-traitance", "/bons-de-commande",
    ])
    def test_espace_membre_exige_connexion(self, client, path):
        r = client.get(path)
        assert r.status_code == 302
        assert "/login" in r.headers.get("location", "")

    @pytest.mark.parametrize("path", [
        "/admin", "/admin/payments", "/admin/companies",
        "/admin/sources", "/admin/backups", "/admin/prospects", "/admin/sous-traitance",
    ])
    def test_admin_exige_authentification(self, client, path):
        r = client.get(path)
        assert r.status_code == 302
        assert "/admin/login" in r.headers.get("location", "")

    def test_api_refuse_les_anonymes(self, client):
        assert client.get("/api/v1/tenders").status_code == 401

    def test_csrf_bloque_un_post_sans_jeton(self, client):
        r = client.post("/register", data={
            "email": "sans-jeton@example.com", "pw": "MotDePasse1!",
            "pw2": "MotDePasse1!", "nom": "X"})
        assert r.status_code == 403, "un POST sans jeton CSRF doit être rejeté"


class TestPaiementEtDocuments:
    def test_paiement_active_l_abonnement_et_genere_les_documents(self, client, db):
        _register(client, "client@example.com", company="BTP Atlas SARL")
        mid = db.execute("SELECT id FROM members WHERE email=?",
                         ("client@example.com",)).fetchone()["id"]

        admin = type(client)(client._app)
        _login_admin(admin)
        admin.get("/admin/payments")
        token = admin.cookies.get("_csrf")
        r = admin.post("/admin/payments/record", data={
            "member_id": mid, "plan": "monthly", "amount": "250",
            "method": "Virement", "reference": "VIR-001", "csrf_token": token})
        assert r.status_code == 302
        receipt = re.search(r"ok=(REC-\d{4}-\d{4})", r.headers["location"]).group(1)

        member = db.execute("SELECT plan, subscription_status, subscription_end FROM members WHERE id=?",
                            (mid,)).fetchone()
        assert member["plan"] == "monthly"
        assert member["subscription_status"] == "ACTIVE"
        assert member["subscription_end"]

        pay = db.execute("SELECT amount, status, subscription_id FROM payments WHERE member_id=?",
                         (mid,)).fetchone()
        assert pay["amount"] == 250.0 and pay["status"] == "PAID"
        assert pay["subscription_id"], "le paiement doit être rattaché à un abonnement"

        docs = {d["doc_type"] for d in db.execute(
            "SELECT doc_type FROM documents WHERE member_id=?", (mid,)).fetchall()}
        assert docs == {"receipt", "contract"}

        page = client.get(f"/documents/{receipt}")
        assert page.status_code == 200
        assert "BTP Atlas SARL" in page.text and "VIR-001" in page.text

    def test_un_membre_ne_lit_pas_les_documents_d_un_autre(self, client, db):
        _register(client, "proprietaire@example.com")
        mid = db.execute("SELECT id FROM members WHERE email=?",
                         ("proprietaire@example.com",)).fetchone()["id"]
        admin = type(client)(client._app)
        _login_admin(admin)
        admin.get("/admin/payments")
        token = admin.cookies.get("_csrf")
        r = admin.post("/admin/payments/record", data={
            "member_id": mid, "plan": "monthly", "amount": "250",
            "method": "Espèces", "csrf_token": token})
        receipt = re.search(r"ok=(REC-\d{4}-\d{4})", r.headers["location"]).group(1)

        intrus = type(client)(client._app)
        _register(intrus, "intrus@example.com")
        assert intrus.get(f"/documents/{receipt}").status_code == 404

    def test_numerotation_sequentielle_des_recus(self, client, db):
        admin = type(client)(client._app)
        _login_admin(admin)
        numeros = []
        for i in range(2):
            _register(client, f"seq{i}@example.com")
            mid = db.execute("SELECT id FROM members WHERE email=?",
                             (f"seq{i}@example.com",)).fetchone()["id"]
            admin.get("/admin/payments")
            token = admin.cookies.get("_csrf")
            r = admin.post("/admin/payments/record", data={
                "member_id": mid, "plan": "monthly", "amount": "250",
                "method": "Virement", "csrf_token": token})
            numeros.append(re.search(r"ok=(REC-\d{4}-\d{4})", r.headers["location"]).group(1))
        assert numeros[0] != numeros[1]
        assert numeros == sorted(numeros), "les numéros doivent se suivre"


class TestBonsDeCommandeSepares:
    def test_les_bons_de_commande_n_apparaissent_pas_dans_les_marches(self, client, db):
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,type_procedure,scraped_at)
                      VALUES('bc_1','BON DE COMMANDE TEST','T101','actif','bon_commande','2026-01-01')""")
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,type_procedure,scraped_at)
                      VALUES('m_1','MARCHE CLASSIQUE TEST','T101','actif','marche','2026-01-01')""")
        db.commit()
        _register(client, "separation@example.com")

        marches = client.get("/tenders").text
        assert "MARCHE CLASSIQUE TEST" in marches
        assert "BON DE COMMANDE TEST" not in marches, \
            "un bon de commande ne doit jamais apparaître dans la page Marchés"

        bc = client.get("/bons-de-commande").text
        assert "BON DE COMMANDE TEST" in bc
        assert "MARCHE CLASSIQUE TEST" not in bc

    def test_aucune_reference_a_la_source_privee_dans_la_page(self, client, db):
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,type_procedure,source,url,scraped_at)
                      VALUES('bc_2','BC AVEC SOURCE','T101','actif','bon_commande',
                             'global-marches','https://global-marches.com/x','2026-01-01')""")
        db.commit()
        _register(client, "source@example.com")
        page = client.get("/bons-de-commande").text
        assert "global-marches" not in page.lower()

    def test_le_lien_source_ne_redirige_pas_vers_le_fournisseur_prive(self, client, db):
        db.execute("""INSERT INTO tenders(id,objet,secteur,statut,source,url,scraped_at)
                      VALUES('gm_1','MARCHE PRIVE','T101','actif','global-marches',
                             'https://global-marches.com/share/xyz','2026-01-01')""")
        db.commit()
        _register(client, "redirect@example.com")
        r = client.get("/tenders/gm_1/source")
        assert r.status_code == 302
        assert "global-marches" not in r.headers.get("location", "")


class TestSuppressionDeCompte:
    def test_le_membre_supprime_son_propre_compte(self, client, db):
        _register(client, "aupartir@example.com")
        mid = db.execute("SELECT id FROM members WHERE email=?",
                         ("aupartir@example.com",)).fetchone()["id"]
        db.execute("INSERT INTO favorites(member_id,tender_id) VALUES(?,'t1')", (mid,))
        db.commit()

        token = client.cookies.get("_csrf")
        r = client.post("/settings/delete",
                        data={"password": "MotDePasse1!", "csrf_token": token})
        assert r.status_code == 302 and "deleted=1" in r.headers["location"]
        assert db.execute("SELECT COUNT(*) FROM members WHERE id=?", (mid,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM favorites WHERE member_id=?", (mid,)).fetchone()[0] == 0

    def test_mauvais_mot_de_passe_ne_supprime_rien(self, client, db):
        _register(client, "protege@example.com")
        token = client.cookies.get("_csrf")
        r = client.post("/settings/delete",
                        data={"password": "MauvaisMotDePasse!", "csrf_token": token})
        assert "err=wrongpw" in r.headers["location"]
        assert db.execute("SELECT COUNT(*) FROM members WHERE email=?",
                          ("protege@example.com",)).fetchone()[0] == 1

    def test_admin_supprime_un_compte_avec_confirmation(self, client, db):
        _register(client, "asupprimer@example.com")
        mid = db.execute("SELECT id FROM members WHERE email=?",
                         ("asupprimer@example.com",)).fetchone()["id"]
        admin = type(client)(client._app)
        _login_admin(admin)
        admin.get("/admin/members")
        token = admin.cookies.get("_csrf")
        r = admin.post(f"/admin/member/{mid}/delete",
                       data={"confirm": "asupprimer@example.com", "csrf_token": token})
        assert r.status_code == 302 and "deleted=" in r.headers["location"]
        assert db.execute("SELECT COUNT(*) FROM members WHERE id=?", (mid,)).fetchone()[0] == 0

    def test_admin_sans_confirmation_ne_supprime_pas(self, client, db):
        _register(client, "garde@example.com")
        mid = db.execute("SELECT id FROM members WHERE email=?",
                         ("garde@example.com",)).fetchone()["id"]
        admin = type(client)(client._app)
        _login_admin(admin)
        admin.get("/admin/members")
        token = admin.cookies.get("_csrf")
        r = admin.post(f"/admin/member/{mid}/delete",
                       data={"confirm": "mauvais@email.com", "csrf_token": token})
        assert "err=confirmation" in r.headers["location"]
        assert db.execute("SELECT COUNT(*) FROM members WHERE id=?", (mid,)).fetchone()[0] == 1

    def test_les_pieces_comptables_survivent_mais_sont_detachees(self, client, db):
        """Un reçu est une pièce comptable: il ne disparaît pas, il est anonymisé."""
        _register(client, "comptable@example.com")
        mid = db.execute("SELECT id FROM members WHERE email=?",
                         ("comptable@example.com",)).fetchone()["id"]
        admin = type(client)(client._app)
        _login_admin(admin)
        admin.get("/admin/payments")
        token = admin.cookies.get("_csrf")
        admin.post("/admin/payments/record", data={
            "member_id": mid, "plan": "monthly", "amount": "250",
            "method": "Virement", "csrf_token": token})
        assert db.execute("SELECT COUNT(*) FROM payments WHERE member_id=?", (mid,)).fetchone()[0] == 1

        admin.get("/admin/members")
        token = admin.cookies.get("_csrf")
        admin.post(f"/admin/member/{mid}/delete",
                   data={"confirm": "comptable@example.com", "csrf_token": token})
        assert db.execute("SELECT COUNT(*) FROM payments WHERE member_id=?", (mid,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM payments WHERE member_id=0").fetchone()[0] == 1

    def test_admin_membres_protege(self, client):
        r = client.get("/admin/members")
        assert r.status_code == 302 and "/admin/login" in r.headers["location"]


class TestEssaiGratuitSurLaLanding:
    def test_essai_annonce_sur_la_page_daccueil(self, client):
        page = client.get("/").text
        assert "Essai gratuit" in page
        assert "7 jours" in page
        assert 'href="/register"' in page

    def test_essai_annonce_sur_la_page_tarifs(self, client):
        page = client.get("/tarifs").text
        assert "Essai gratuit" in page and "Sans carte bancaire" in page
