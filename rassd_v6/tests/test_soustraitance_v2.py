"""Sous-traitance: opportunités déduites des adjudications, profil, offres.

Une bourse d'annonces vide reste vide. Ces tests couvrent ce qui la remplit
sans attendre personne: les marchés attribués deviennent des pistes, et les
réponses arrivent sous forme d'offres comparables (prix, délai, pièce jointe).
"""
from datetime import date, datetime, timedelta

import pytest

from app.services import soustraitance as st


def _membre(db, email="pro@example.com", secteurs='["T101"]', regions='[]',
            company="BTP ATLAS", **kw):
    champs = dict(nom="Ahmed", email=email, company=company, plan="free",
                  subscription_status="TRIAL",
                  trial_ends=(date.today() + timedelta(days=5)).strftime("%Y-%m-%d"),
                  secteurs=secteurs, regions=regions, notif_email=1, notif_tg=0,
                  notif_wa=0, notif_digest=0, actif=1, email_verified=1,
                  pw_hash="x", session_token=f"tok_{email}")
    champs.update(kw)
    cols = ",".join(champs)
    db.execute(f"INSERT INTO members({cols}) VALUES({','.join('?' * len(champs))})",
               list(champs.values()))
    db.commit()
    return db.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone()


def _resultat(db, rid="r1", secteur="T101", montant="1 500 000,00 MAD",
              gagnant="SOCIETE GAMMA", region="Casablanca", jours=2):
    db.execute("""INSERT INTO tender_results(id,reference,objet,acheteur,adjudicataire,
                  region,budget,montant,secteur,date_adjudication,scraped_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               (rid, "AO/1", "TRAVAUX DE VOIRIE ET ASSAINISSEMENT", "COMMUNE",
                gagnant, region, "", montant, secteur, "01/09/2026",
                (datetime.now() - timedelta(days=jours)).strftime("%Y-%m-%d %H:%M:%S")))
    db.commit()


class TestLectureDesMontants:
    @pytest.mark.parametrize("brut,attendu", [
        ("48 516 000,00 MAD", 48516000.0),
        ("1.189.476.00", 1189476.0),
        ("180000000", 180000000.0),
        ("0,00 MAD", 0.0),
        ("", 0.0),
        ("néant", 0.0),
    ])
    def test_formats_du_portail(self, brut, attendu):
        assert st.parse_montant(brut) == attendu


class TestOpportunites:
    def test_marche_du_secteur_propose(self, db):
        m = _membre(db)
        _resultat(db)
        pistes = st.opportunites_pour(dict(m))
        assert len(pistes) == 1
        assert pistes[0]["adjudicataire"] == "SOCIETE GAMMA"

    def test_autre_secteur_ignore(self, db):
        m = _membre(db, secteurs='["T101"]')
        _resultat(db, secteur="S911")
        assert st.opportunites_pour(dict(m)) == []

    def test_petit_marche_ignore(self, db):
        # Sous 300 000 MAD, l'attributaire exécute seul: proposer une
        # sous-traitance ferait perdre son temps au membre.
        m = _membre(db)
        _resultat(db, montant="80 000,00 MAD")
        assert st.opportunites_pour(dict(m)) == []

    def test_mon_propre_marche_ignore(self, db):
        m = _membre(db, company="SOCIETE GAMMA")
        _resultat(db, gagnant="SOCIETE GAMMA")
        assert st.opportunites_pour(dict(m)) == []

    def test_filtre_par_zone(self, db):
        m = _membre(db, regions='["Agadir"]')
        _resultat(db, region="Casablanca")
        assert st.opportunites_pour(dict(m)) == []

    def test_contact_de_l_attributaire_joint(self, db):
        m = _membre(db)
        db.execute("""INSERT INTO companies(legal_name,normalized_name,sector,city,phone,source,created_at)
                      VALUES(?,?,?,?,?,?,?)""",
                   ("SOCIETE GAMMA", "societe gamma", "T101", "Casablanca",
                    "0612345678", "google-maps", "2026-09-01"))
        db.commit()
        _resultat(db, gagnant="SOCIETE GAMMA")
        assert st.opportunites_pour(dict(m))[0]["contact_phone"] == "0612345678"

    def test_message_pret_a_envoyer(self, db):
        m = dict(_membre(db))
        _resultat(db)
        piste = st.opportunites_pour(m)[0]
        texte = st.message_de_contact(m, piste)
        assert "BTP ATLAS" in texte and "TRAVAUX DE VOIRIE" in texte


class TestAlerteAnnonce:
    def _annonce(self, auteur_id, secteur="T101", region="Casablanca"):
        return {"id": "st_1", "member_id": auteur_id, "titre": "Recherche électricien",
                "secteur": secteur, "region": region, "budget": "50 000 MAD"}

    def test_membre_du_metier_prevenu(self, db, monkeypatch):
        auteur = _membre(db, email="auteur@example.com")
        _membre(db, email="sous@example.com")
        envois = []
        monkeypatch.setattr("app.services.notifications.email_send",
                            lambda to, s, h: envois.append(to) or True)
        assert st.notifier_nouvelle_annonce(self._annonce(auteur["id"])) == 1
        assert envois == ["sous@example.com"]

    def test_auteur_jamais_prevenu(self, db, monkeypatch):
        auteur = _membre(db, email="auteur@example.com")
        envois = []
        monkeypatch.setattr("app.services.notifications.email_send",
                            lambda to, s, h: envois.append(to) or True)
        st.notifier_nouvelle_annonce(self._annonce(auteur["id"]))
        assert envois == []

    def test_autre_metier_non_prevenu(self, db, monkeypatch):
        auteur = _membre(db, email="auteur@example.com")
        _membre(db, email="autre@example.com", secteurs='["S911"]')
        envois = []
        monkeypatch.setattr("app.services.notifications.email_send",
                            lambda to, s, h: envois.append(to) or True)
        st.notifier_nouvelle_annonce(self._annonce(auteur["id"]))
        assert envois == []

    def test_essai_expire_non_prevenu(self, db, monkeypatch):
        auteur = _membre(db, email="auteur@example.com")
        _membre(db, email="expire@example.com",
                trial_ends=(date.today() - timedelta(days=2)).strftime("%Y-%m-%d"))
        envois = []
        monkeypatch.setattr("app.services.notifications.email_send",
                            lambda to, s, h: envois.append(to) or True)
        st.notifier_nouvelle_annonce(self._annonce(auteur["id"]))
        assert envois == []


def _connecte(client, db, email="pro@example.com", **kw):
    m = _membre(db, email=email, **kw)
    client.cookies.set("_session", m["session_token"])
    return m


class TestProfil:
    def test_enregistrement_et_relecture(self, client, db):
        _connecte(client, db)
        client.get("/sous-traitance/profil")
        r = client.post("/sous-traitance/profil", data={
            "raison_sociale": "BTP ATLAS SARL", "metiers": ["T101", "T104"],
            "zones": ["Casablanca"], "effectif": "12 ouvriers",
            "moyens": "2 camions", "experience": "8 ans",
            "references_txt": "Voirie Témara 2025", "certifications": "Qualif BTP",
            "disponible": "1", "csrf_token": client.cookies.get("_csrf")})
        assert r.status_code == 302

        page = client.get("/sous-traitance/profil")
        assert "BTP ATLAS SARL" in page.text and "12 ouvriers" in page.text
        ligne = db.execute("SELECT * FROM subcontract_profiles").fetchone()
        assert "T104" in ligne["metiers"] and ligne["disponible"] == 1

    def test_profil_reserve_aux_membres(self, client):
        r = client.get("/sous-traitance/profil")
        assert r.status_code == 302 and "/login" in r.headers["location"]


class TestOffres:
    def _annonce_en_base(self, db, auteur_id, pid="st_x"):
        db.execute("""INSERT INTO subcontract_posts(id,member_id,type,titre,secteur,region,
                      budget,description,statut,created_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (pid, auteur_id, "demande", "Recherche électricien", "T101",
                    "Casablanca", "50 000 MAD", "Lot électricité", "actif",
                    datetime.now().isoformat()))
        db.commit()
        return pid

    def test_depot_et_mise_a_jour(self, client, db):
        auteur = _membre(db, email="auteur@example.com")
        pid = self._annonce_en_base(db, auteur["id"])
        _connecte(client, db, email="candidat@example.com")
        client.get(f"/sous-traitance/{pid}")

        client.post(f"/sous-traitance/{pid}/offre", data={
            "prix": "180 000 MAD", "delai": "45 jours", "message": "Équipe disponible",
            "csrf_token": client.cookies.get("_csrf")})
        offre = db.execute("SELECT * FROM subcontract_offers WHERE post_id=?", (pid,)).fetchone()
        assert offre["prix"] == "180 000 MAD" and offre["statut"] == "envoyee"

        client.post(f"/sous-traitance/{pid}/offre", data={
            "prix": "165 000 MAD", "delai": "40 jours",
            "csrf_token": client.cookies.get("_csrf")})
        assert db.execute("SELECT COUNT(*) FROM subcontract_offers WHERE post_id=?",
                          (pid,)).fetchone()[0] == 1, "une seule offre par candidat"
        assert db.execute("SELECT prix FROM subcontract_offers WHERE post_id=?",
                          (pid,)).fetchone()[0] == "165 000 MAD"

    def test_l_auteur_ne_peut_pas_repondre_a_sa_propre_annonce(self, client, db):
        auteur = _connecte(client, db, email="auteur@example.com")
        pid = self._annonce_en_base(db, auteur["id"])
        client.get(f"/sous-traitance/{pid}")
        client.post(f"/sous-traitance/{pid}/offre", data={
            "prix": "1", "csrf_token": client.cookies.get("_csrf")})
        assert db.execute("SELECT COUNT(*) FROM subcontract_offers").fetchone()[0] == 0

    def test_l_auteur_compare_les_offres(self, client, db):
        auteur = _membre(db, email="auteur@example.com")
        pid = self._annonce_en_base(db, auteur["id"])
        for i, prix in enumerate(["180 000 MAD", "165 000 MAD"]):
            c = _membre(db, email=f"cand{i}@example.com", company=f"SOUS TRAITANT {i}")
            db.execute("""INSERT INTO subcontract_offers(post_id,member_id,prix,delai,
                          statut,created_at) VALUES(?,?,?,?,'envoyee',?)""",
                       (pid, c["id"], prix, "45 jours", datetime.now().isoformat()))
        db.commit()

        client.cookies.set("_session", auteur["session_token"])
        page = client.get(f"/sous-traitance/{pid}")
        assert "180 000 MAD" in page.text and "165 000 MAD" in page.text
        assert "SOUS TRAITANT 0" in page.text and "SOUS TRAITANT 1" in page.text

    def test_un_candidat_ne_voit_pas_les_prix_des_autres(self, client, db):
        auteur = _membre(db, email="auteur@example.com")
        pid = self._annonce_en_base(db, auteur["id"])
        rival = _membre(db, email="rival@example.com")
        db.execute("""INSERT INTO subcontract_offers(post_id,member_id,prix,statut,created_at)
                      VALUES(?,?,?,'envoyee',?)""",
                   (pid, rival["id"], "99 000 MAD", datetime.now().isoformat()))
        db.commit()

        _connecte(client, db, email="candidat@example.com")
        page = client.get(f"/sous-traitance/{pid}")
        assert "99 000 MAD" not in page.text

    def test_retenir_une_offre_ecarte_les_autres(self, client, db):
        auteur = _membre(db, email="auteur@example.com")
        pid = self._annonce_en_base(db, auteur["id"])
        ids = []
        for i in range(2):
            c = _membre(db, email=f"c{i}@example.com")
            cur = db.execute("""INSERT INTO subcontract_offers(post_id,member_id,prix,statut,created_at)
                                VALUES(?,?,?,'envoyee',?)""",
                             (pid, c["id"], f"{i}00 000 MAD", datetime.now().isoformat()))
            ids.append(cur.lastrowid)
        db.commit()

        client.cookies.set("_session", auteur["session_token"])
        client.get(f"/sous-traitance/{pid}")
        client.post(f"/sous-traitance/{pid}/offre/{ids[0]}/retenir",
                    data={"csrf_token": client.cookies.get("_csrf")})
        statuts = {r["id"]: r["statut"] for r in
                   db.execute("SELECT id,statut FROM subcontract_offers WHERE post_id=?", (pid,))}
        assert statuts[ids[0]] == "retenue" and statuts[ids[1]] == "ecartee"

    def test_seul_l_auteur_retient(self, client, db):
        auteur = _membre(db, email="auteur@example.com")
        pid = self._annonce_en_base(db, auteur["id"])
        c = _membre(db, email="c@example.com")
        cur = db.execute("""INSERT INTO subcontract_offers(post_id,member_id,prix,statut,created_at)
                            VALUES(?,?,?,'envoyee',?)""",
                         (pid, c["id"], "10 MAD", datetime.now().isoformat()))
        db.commit()
        client.cookies.set("_session", c["session_token"])
        client.get(f"/sous-traitance/{pid}")
        r = client.post(f"/sous-traitance/{pid}/offre/{cur.lastrowid}/retenir",
                        data={"csrf_token": client.cookies.get("_csrf")})
        assert r.status_code == 403


class TestDeclaration:
    def test_generee_depuis_l_offre_retenue(self, client, db):
        auteur = _membre(db, email="auteur@example.com", company="ENTREPRISE TITULAIRE")
        db.execute("""INSERT INTO subcontract_posts(id,member_id,type,titre,secteur,statut,created_at)
                      VALUES('st_d',?,'demande','Lot électricité','T101','actif',?)""",
                   (auteur["id"], datetime.now().isoformat()))
        c = _membre(db, email="sous@example.com", company="SOUS TRAITANT SARL")
        db.execute("""INSERT INTO subcontract_offers(post_id,member_id,prix,delai,statut,created_at)
                      VALUES('st_d',?,'180 000 MAD','45 jours','retenue',?)""",
                   (c["id"], datetime.now().isoformat()))
        db.commit()

        client.cookies.set("_session", auteur["session_token"])
        page = client.get("/sous-traitance/st_d/declaration")
        assert page.status_code == 200
        assert "ENTREPRISE TITULAIRE" in page.text and "SOUS TRAITANT SARL" in page.text
        assert "180 000 MAD" in page.text
        assert "sous-traitance" in page.text.lower()

    def test_refusee_sans_offre_retenue(self, client, db):
        auteur = _membre(db, email="auteur@example.com")
        db.execute("""INSERT INTO subcontract_posts(id,member_id,type,titre,secteur,statut,created_at)
                      VALUES('st_e',?,'demande','Lot','T101','actif',?)""",
                   (auteur["id"], datetime.now().isoformat()))
        db.commit()
        client.cookies.set("_session", auteur["session_token"])
        r = client.get("/sous-traitance/st_e/declaration")
        assert r.status_code == 302 and "err=offre" in r.headers["location"]
