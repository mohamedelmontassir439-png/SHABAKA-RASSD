# -*- coding: utf-8 -*-
"""La case de recherche du haut de page.

Elle était désactivée: visible sur toutes les pages, elle ne répondait pas
— signalé par le fondateur le 20/10/2026. Une case qui ne répond pas fait
douter de tout le reste.
"""
import os
from datetime import date, timedelta

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _base():
    with open(os.path.join(RACINE, "templates", "base.html"), encoding="utf-8") as f:
        return f.read()


class TestLeGabarit:
    def test_c_est_un_vrai_formulaire(self):
        g = _base()
        debut = g.index('class="topbar-search"')
        bloc = g[g.rfind("<", 0, debut):g.index("</form>", debut)]
        assert bloc.startswith("<form") and 'action="/tenders"' in bloc
        assert 'name="q"' in bloc and "disabled" not in bloc

    def test_ctrl_k_y_mene(self):
        assert "e.ctrlKey" in _base() and "recherche-haut" in _base()


class TestLeFiltre:
    def _filtre(self, q):
        import main
        where, params = [], []
        main.filtre_recherche(q, where, params)
        return where, params

    def test_vide_ne_filtre_rien(self):
        assert self._filtre("   ") == ([], [])

    def test_un_nom_de_secteur_trouve_le_secteur(self):
        from app.core.config import cfg
        code, label = next((c, l) for c, l in cfg.SECTEURS.items() if "Peinture" in l)
        where, params = self._filtre("peinture")
        assert "secteur IN" in where[0] and code in params

    def test_sans_accents(self):
        from app.core.config import cfg
        code = next(c for c, l in cfg.SECTEURS.items() if "Électricité" in l)
        assert code in self._filtre("electricite")[1]

    def test_deux_lettres_n_ouvrent_pas_les_secteurs(self):
        assert "secteur IN" not in self._filtre("de")[0][0]


class TestDeBoutEnBout:
    def test_la_recherche_du_haut_trouve_le_marche(self, client, db, confirmer_email):
        db.execute("""INSERT INTO members(nom,email,phone,company,plan,subscription_status,
                      trial_ends,pw_hash,session_token,actif,secteurs,email_verified)
                      VALUES('Ahmed','r@x.ma','0612345678','SIMAC','monthly','ACTIVE',?,
                      'x','jeton-recherche',1,'[]',1)""",
                   ((date.today() + timedelta(days=30)).isoformat(),))
        for tid, objet in (("t1", "REFECTION ET PEINTURE DES GRUES"), ("t2", "ACHAT DE CARBURANT")):
            db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,statut,scraped_at,
                          date_limite,type_offre,type_procedure)
                          VALUES(?,?,'SGPTV','T101','Tanger','actif','2026-10-01 08:00:00',?,
                          'Public','marche')""",
                       (tid, objet, (date.today() + timedelta(days=9)).strftime("%d/%m/%Y")))
        db.commit()
        client.cookies.set("_session", "jeton-recherche")
        page = client.get("/tenders?q=grues").text
        assert "PEINTURE DES GRUES" in page and "CARBURANT" not in page
        # La case garde ce qu'on a cherché.
        assert 'value="grues"' in page
