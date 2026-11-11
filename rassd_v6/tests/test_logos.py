"""L'emblème de l'acheteur devant son nom (app/core/logos.py)."""
from app.core.logos import ARMOIRIES, embleme, logo_html


class TestEmbleme:
    def test_administration_et_commune_portent_les_armoiries(self):
        assert embleme("Commune rurale de AMEJJAOU") == {"img": ARMOIRIES}
        assert embleme("DIRECTION PROVINCIALE DE L'EQUIPEMENT DE SIDI KACEM") == {"img": ARMOIRIES}
        assert embleme("") == {"img": ARMOIRIES}

    def test_etablissement_public_reconnu_par_son_sigle(self):
        assert embleme("OFFICE NATIONAL DE L'ELECTRICITE ET DE L'EAU POTABLE - BRANCHE EAU")["sigle"] == "ONEE"
        assert embleme("Ofppt OFPPT/DIRECTION REGIONALE DE L'ORIENTAL")["sigle"] == "OFPPT"
        assert embleme("Societe Royale d'Encouragement Du Cheval (SOREC)")["sigle"] == "SOREC"

    def test_acheteur_prive_a_ses_initiales(self):
        assert embleme("Hotel Atlas Sky", "Privé")["sigle"] == "HAS"

    def test_meme_sigle_meme_couleur(self):
        assert embleme("Cnss")["teinte"] == embleme("CNSS DIRECTION REGIONALE SETTAT")["teinte"]

    def test_le_nom_est_echappe(self):
        assert "<script" not in str(logo_html("<script>X</script>", "Privé"))


def test_la_liste_des_marches_montre_l_embleme(client, db):
    from datetime import datetime
    db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,statut,date_limite,scraped_at)
                  VALUES('ao_logo1','Construction d''un dispensaire rural','Commune de Tata',
                         'T101','actif','20/12/2099',?)""", (datetime.now().isoformat(),))
    db.commit()
    assert "/static/img/logos/armoiries.webp" in client.get("/").text
