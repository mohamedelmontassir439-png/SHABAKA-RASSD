# -*- coding: utf-8 -*-
"""Le lien de dépôt retrouvé sans intelligence artificielle."""
from app.services import lien_depot as L


def _avis(db, tid, source, description, limite="28/10/2026", acheteur="Madaëf", initiale="", url="u", dao=""):
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,scraped_at,url,source,date_limite,
                  date_limite_initiale,description,fiche_lue,dao_url)
                  VALUES(?,?,?,'T101','actif','2026-10-20',?,?,?,?,?,'v2:2026-10-25',?)""",
               (tid, f"Marché {tid}", acheteur, url, source, limite, initiale, description, dao))
    db.commit()


class TestDossier:
    def test_l_adresse_du_depot_d_abord(self):
        texte = ("Le dossier est téléchargeable sur www.exemple.ma. "
                 "La remise des offres se fait exclusivement sur la plateforme https://safakat.cdg.ma/ "
                 "Contact : achats@cdg.ma")
        liens = L.dans_le_dossier(texte)
        assert liens[0]["url"].startswith("https://safakat.cdg.ma")
        assert all("cdg.ma" != l["url"] for l in liens), "un email n'est pas une plateforme"

    def test_rien_sans_contexte_de_depot(self):
        assert L.dans_le_dossier("Voir notre site www.societe.ma pour nos actualités.") == []


class TestReference:
    def test_meme_reference_et_date_initiale(self, db):
        _avis(db, "ao_1", "marchespublics", "Référence 07/2026/DPE Objet : x", limite="28/10/2026",
              initiale="22/10/2026", acheteur="Direction provinciale de Taza", url="https://www.marchespublics.gov.ma/x")
        _avis(db, "gm_1", "global-marches", "Référence 07/2026/DPE Adresse de dépôt des offres : dépôt électronique — plateforme",
              limite="22/10/2026", acheteur="DP Taza")
        idx = L.index_portail()
        t = dict(db.execute("SELECT * FROM tenders WHERE id='gm_1'").fetchone())
        assert L.par_reference(t, idx)["id"] == "ao_1"

    def test_reference_courante_sans_date_commune(self, db):
        _avis(db, "ao_1", "marchespublics", "Référence 01/2026 Objet : x", limite="30/11/2026")
        _avis(db, "gm_1", "global-marches", "Référence 01/2026 x", limite="28/10/2026")
        t = dict(db.execute("SELECT * FROM tenders WHERE id='gm_1'").fetchone())
        assert L.par_reference(t, L.index_portail()) is None


class TestPasse:
    def test_dao_lu_une_fois(self, db):
        _avis(db, "gm_1", "global-marches", "Référence 9/2026 Adresse de dépôt des offres : dépôt électronique — plateforme",
              dao="https://global-marches.com/downoaldcps/1.zip")
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", "<w:p><w:t>Les offres sont déposées sur la plateforme https://safakat.cdg.ma</w:t></w:p>")
        appels = []
        rec = lambda url: appels.append(url) or (buf.getvalue(), "application/zip", "docx")
        assert L.rapprocher(recuperer=rec) == {"lus": 1, "portail": 0, "dossier": 1, "acheteur": 0}
        r = db.execute("SELECT lien_depot, lien_depot_origine FROM tenders").fetchone()
        assert r["lien_depot"] == "https://safakat.cdg.ma" and r["lien_depot_origine"] == "dossier"
        assert L.rapprocher(recuperer=rec)["lus"] == 0 and len(appels) == 1


def _lu(db, tid, acheteur, lien, extrait="La remise des offres se fait sur la plateforme"):
    _avis(db, tid, "global-marches", "Adresse de dépôt des offres : dépôt électronique", acheteur=acheteur)
    db.execute("""UPDATE tenders SET lien_depot=?, lien_depot_origine=?, lien_depot_extrait=?,
                  lien_depot_cherche='2026-10-25' WHERE id=?""",
               (lien, "dossier" if lien else "", extrait if lien else "", tid))
    db.commit()


class TestAcheteur:
    def test_cle_ignore_forme_et_prefixe(self):
        assert L.cle_acheteur("Société Madaëf S.A") == L.cle_acheteur("MADAEF")
        assert L.cle_acheteur("Autres organismes particuliers /Institut Pasteur du Maroc") == \
            L.cle_acheteur("institut Pasteur du Maroc")

    def test_registre_par_majorite(self, db):
        _lu(db, "gm_1", "Madaëf", "https://safakat.cdg.ma/consultation/1")
        _lu(db, "gm_2", "MADAEF", "https://www.safakat.cdg.ma")
        _lu(db, "gm_3", "CGI", "https://www.marchespublics.gov.ma")
        _lu(db, "gm_4", "Hésitant", "https://a.ma")
        _lu(db, "gm_5", "Hésitant", "https://b.ma")
        reg = L.registre()
        assert reg[L.cle_acheteur("Madaëf")]["hote"] == "safakat.cdg.ma"
        assert reg[L.cle_acheteur("Madaëf")]["vus"] == 2
        assert reg[L.cle_acheteur("CGI")]["url"] == "https://marchespublics.gov.ma"
        assert L.cle_acheteur("Hésitant") not in reg, "deux plateformes à égalité: on ne choisit pas"

    def test_complete_un_avis_du_meme_acheteur(self, db):
        _lu(db, "gm_1", "Madaëf", "https://safakat.cdg.ma", extrait="remise des offres sur safakat.cdg.ma")
        _lu(db, "gm_2", "Madaëf SA", "")
        _lu(db, "gm_3", "Autre société", "")
        assert L.completer_par_acheteur() == 1
        r = dict(db.execute("SELECT * FROM tenders WHERE id='gm_2'").fetchone())
        assert r["lien_depot"] == "https://safakat.cdg.ma" and r["lien_depot_origine"] == "acheteur"
        assert "safakat" in r["lien_depot_extrait"], "la preuve du dossier précédent est montrée"
        assert not db.execute("SELECT lien_depot FROM tenders WHERE id='gm_3'").fetchone()[0]

    def test_le_guide_montre_le_registre(self, client, db):
        _lu(db, "gm_1", "Madaëf", "https://safakat.cdg.ma")
        html = client.get("/guide/depot-electronique").text
        assert "safakat.cdg.ma" in html and "Madaëf" in html
