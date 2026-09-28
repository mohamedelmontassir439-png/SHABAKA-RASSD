"""Pages légales: une vraie version arabe, et plus de promesse WhatsApp.

En arabe, les trois pages affichaient du texte français dans une mise en
page de droite à gauche — la ponctuation se retrouvait en début de ligne.
Par ailleurs le site annonçait des alertes WhatsApp qui ne partent pas.
"""
import pytest

PAGES = ("/mentions-legales", "/cgu", "/confidentialite")

# Expressions françaises qui ne doivent plus apparaître en version arabe.
FRANCAIS = ("Le site", "Les présentes", "est édité", "Vos données",
            "Conditions générales", "Politique de")


class TestVersionArabe:
    @pytest.mark.parametrize("chemin", PAGES)
    def test_contenu_traduit(self, client, chemin):
        page = client.get(f"{chemin}?lang=ar")
        assert page.status_code == 200
        for mot in FRANCAIS:
            assert mot not in page.text, f"{mot} subsiste dans la version arabe de {chemin}"

    @pytest.mark.parametrize("chemin", PAGES)
    def test_texte_arabe_present(self, client, chemin):
        page = client.get(f"{chemin}?lang=ar")
        assert "العربية" in page.text or any(
            mot in page.text for mot in ("الخصوصية", "القانونية", "الشروط", "المعطيات"))

    @pytest.mark.parametrize("chemin", PAGES)
    def test_version_francaise_intacte(self, client, chemin):
        page = client.get(f"{chemin}?lang=fr")
        assert page.status_code == 200
        assert "Maroc Entrepreneuriat" in page.text


class TestPlusDeWhatsApp:
    @pytest.mark.parametrize("chemin", ["/", "/tarifs", "/confidentialite"] )
    def test_aucune_promesse_d_alerte(self, client, chemin):
        """Le paiement par WhatsApp reste possible; l'alerte WhatsApp, non."""
        texte = client.get(chemin).text.lower()
        for promesse in ("alertes email, telegram & whatsapp",
                         "alertes email + telegram + whatsapp",
                         "email, telegram et whatsapp",
                         "whatsapp arrive bientôt",
                         "bientôt disponible"):
            assert promesse not in texte, f"{promesse} subsiste sur {chemin}"

    def test_cgu_ne_liste_plus_whatsapp_comme_canal(self, client):
        texte = client.get("/cgu").text
        assert "(Email, Telegram)" in texte or "Email, Telegram" in texte
        assert "Telegram, WhatsApp" not in texte

    def test_contact_par_whatsapp_conserve(self, client, monkeypatch):
        # C'est le canal réel par lequel un abonné souscrit: il reste affiché
        # dès qu'un numéro est configuré (PAYMENT_PHONE).
        from app.core.config import cfg
        monkeypatch.setattr(cfg, "PAYMENT_PHONE", "212621728813")
        page = client.get("/contact")
        assert "whatsapp" in page.text.lower() and "212621728813" in page.text


class TestSourcesAnnoncees:
    def test_inventaire_sans_sources_mortes(self, client):
        data = client.get("/api/v1/sources").json()
        noms = " ".join(s["name"] for s in data["sources"])
        for mort in ("ONDA", "ONCF", "ONEE", "IAM", "SNRT", "Le Matin", "BCP"):
            assert mort not in noms, f"{mort} ne doit plus être annoncée"
        assert data["total"] == 3
        assert all(s["status"] == "active" for s in data["sources"])
