# -*- coding: utf-8 -*-
"""Le profil d'un membre doit porter de quoi le joindre.

Jusqu'au 19/10/2026, l'inscription n'exigeait que l'email, le mot de passe
et un secteur. Le nom, le téléphone et la société étaient facultatifs — et
restaient vides. Or un marché se joue parfois en deux jours: sans numéro, on
ne peut pas prévenir, et la veille qu'on vend s'arrête à l'email.

Chaque contrôle reste modeste à dessein. Une exigence trop stricte ne
produit pas de meilleures données: elle produit des « . », des « aaa » et
des cases pleines qui mentent — pire qu'une case vide, puisqu'on croit
l'avoir.
"""
import pytest

from app.core.profil import (nom_valide, societe_valide, telephone_marocain,
                             telephone_normalise, profil_incomplet)


class TestLesControles:
    @pytest.mark.parametrize("valeur,attendu", [
        ("Mohamed Alaoui", True),
        ("Alaoui", True),          # un seul nom suffit: en refuser un coûte un abonné
        ("محمد العلوي", True),
        ("aaa", False),            # une lettre répétée remplit sans rien dire
        ("...", False),
        ("  ", False),
    ])
    def test_le_nom(self, valeur, attendu):
        assert nom_valide(valeur) is attendu

    @pytest.mark.parametrize("valeur,attendu", [
        ("SIMAC", True), ("2SBT", True),
        ("MM", True),              # deux lettres: trop court pour juger, on accorde
        ("aaa", False), ("..", False),
    ])
    def test_la_societe(self, valeur, attendu):
        assert societe_valide(valeur) is attendu

    @pytest.mark.parametrize("brut,range", [
        ("0612345678", "0612345678"),
        ("+212 6 12 34 56 78", "0612345678"),
        ("212612345678", "0612345678"),
        ("06 12 34 56 78", "0612345678"),
        ("0522963000", "0522963000"),     # un fixe est joignable aussi
    ])
    def test_un_numero_marocain_est_range_sous_une_seule_forme(self, brut, range):
        """Deux écritures du même numéro en feraient deux contacts, dont l'un
        ne serait jamais rappelé."""
        assert telephone_marocain(brut)
        assert telephone_normalise(brut) == range

    @pytest.mark.parametrize("brut", ["061234567", "0812345678", "abc", "", "00000"])
    def test_ce_qui_nest_pas_joignable_est_refuse(self, brut):
        assert not telephone_marocain(brut)
        assert telephone_normalise(brut) == ""


class TestInscription:
    def _poster(self, client, **extra):
        client.get("/register")
        champs = {"nom": "Mohamed Alaoui", "email": "neuf@example.com",
                  "phone": "0612345678", "company": "SIMAC",
                  "pw": "MotDePasse!2026", "pw2": "MotDePasse!2026",
                  "secteurs_sel": ["T101"],
                  "csrf_token": client.cookies.get("_csrf")}
        champs.update(extra)
        return client.post("/register", data=champs)

    @pytest.mark.parametrize("champ,valeur", [
        ("nom", ""), ("nom", "aaa"),
        ("phone", ""), ("phone", "12345"),
        ("company", ""),
        ("secteurs_sel", []),
    ])
    def test_un_champ_manquant_refuse_l_inscription(self, client, db, champ, valeur):
        r = self._poster(client, **{champ: valeur})
        assert r.status_code == 200, "la page doit se réafficher, pas rediriger"
        ligne = db.execute("SELECT COUNT(*) c FROM members WHERE email=?",
                           ("neuf@example.com",)).fetchone()
        assert ligne["c"] == 0, f"inscrit malgré {champ}={valeur!r}"

    def test_le_formulaire_le_dit_aussi_au_navigateur(self):
        """Le serveur protège; `required` évite d'envoyer pour rien."""
        import os
        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(racine, "templates", "register.html"), encoding="utf-8") as f:
            page = f.read()
        for champ in ("nom", "phone", "company"):
            bloc = page[page.index(f'name="{champ}"'):][:160]
            assert "required" in bloc, champ


class TestProfilsDejaInscrits:
    def test_on_liste_ce_qui_manque_sans_mettre_dehors(self):
        """Ils paient: on ne leur ferme pas la porte, on leur dit quoi finir."""
        assert profil_incomplet({"nom": "", "phone": "", "company": ""}) == \
            ["nom", "phone", "company"]
        assert profil_incomplet({"nom": "Alaoui", "phone": "0612345678",
                                 "company": "SIMAC"}) == []

    def test_le_bandeau_suit_le_membre_partout(self):
        """Dans la coquille, pas sur le seul tableau de bord — qu'il peut ne
        jamais ouvrir."""
        import os
        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(racine, "templates", "base.html"), encoding="utf-8") as f:
            assert "profil_manque(member)" in f.read()
