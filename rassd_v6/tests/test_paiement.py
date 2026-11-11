"""L'abonnement unique et son règlement sur WhatsApp (11/11/2026).

Plus de page de virement: aucune coordonnée bancaire n'est publiée sur le
site. La page Tarifs mène à WhatsApp avec un message prêt, qui cite le
marché choisi quand le visiteur vient de l'accueil.
"""
import pathlib
from datetime import datetime
from urllib.parse import unquote

from app.core.config import cfg

RACINE = pathlib.Path(__file__).resolve().parent.parent


class TestTarifs:
    def test_une_seule_offre_a_3999(self, client):
        page = client.get("/tarifs").text
        assert cfg.PRIX_ANNUEL == 3999 and cfg.PRIX_TXT in page
        assert page.count('class="plan-card"') == 1

    def test_le_bouton_ouvre_whatsapp_avec_le_message(self, client):
        page = client.get("/tarifs").text
        assert f"https://wa.me/{cfg.PAYMENT_PHONE}?text=" in page
        assert "abonnement annuel" in unquote(page)

    def test_le_marche_choisi_est_repris(self, client, db):
        db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,date_limite,scraped_at)
                      VALUES('ao_abo1','Réfection de la piste de Tafraout','Commune de Tafraout',
                             'T101','actif','20/12/2099',?)""", (datetime.now().isoformat(),))
        db.commit()
        page = client.get("/tarifs?ao=ao_abo1").text
        assert "Réfection de la piste de Tafraout" in page
        assert "Réfection de la piste de Tafraout" in unquote(page.split("wa.me/", 1)[1].split('"', 1)[0])

    def test_en_arabe(self, client):
        client.cookies.set("lang", "ar")
        page = client.get("/tarifs").text
        assert "اشترك عبر واتساب" in page and "الاشتراك السنوي" in page


class TestPlusDeCoordonneesBancaires:
    def test_l_ancienne_page_renvoie_aux_tarifs(self, client):
        r = client.get("/abonnement/paiement?plan=monthly", follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == "/tarifs"

    def test_aucun_rib_dans_le_code(self):
        for dossier in ("app", "templates"):
            for f in (RACINE / dossier).rglob("*"):
                if f.suffix in (".py", ".html", ".json"):
                    texte = f.read_text(encoding="utf-8", errors="ignore")
                    assert "4193980211" not in texte and "CIHMMAMC" not in texte, f
        assert not hasattr(cfg, "PAYMENT_RIB")


class TestVideoDeLAccueil:
    def test_l_accueil_affiche_la_video(self, client):
        page = client.get("/").text
        assert 'src="/video/presentation_fr.mp4"' in page and 'id="video"' in page

    def test_lecture_par_plages_pour_safari(self, client):
        r = client.get("/video/presentation_fr.mp4", headers={"Range": "bytes=0-99"})
        assert r.status_code == 206 and len(r.content) == 100
        assert r.headers["content-range"].startswith("bytes 0-99/")
        assert client.get("/video/presentation_fr.mp4", headers={"Range": "bytes=-10"}).status_code == 206
        assert client.get("/video/autre.mp4").status_code == 404
