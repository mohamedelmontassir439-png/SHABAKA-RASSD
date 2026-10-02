# -*- coding: utf-8 -*-
"""Audit de toutes les pages: ce qui se voit, et ce qui ne devrait pas s'y voir.

Les tests fonctionnels vérifient qu'une page répond. Ceux-ci vérifient
qu'elle est bien faite: un seul titre de niveau 1, pas de lien interne qui
tombe à côté, pas de clef de traduction affichée en clair, pas de texte de
remplacement oublié.
"""
import html
import re
from datetime import date, timedelta

import pytest

# Ouvertes à tous: elles doivent répondre sans compte.
PUBLIQUES = ["/", "/tarifs", "/contact", "/cgu", "/confidentialite",
             "/mentions-legales", "/login", "/register", "/forgot",
             "/marches-publics"]

# Réservées aux membres: anonyme, elles renvoient vers la connexion.
MEMBRE = ["/dashboard", "/settings", "/favorites", "/mon-abonnement",
          "/tenders", "/bons-de-commande", "/resultats",
          "/sous-traitance",
          "/sous-traitance/nouveau", "/sous-traitance/profil",
          "/sous-traitance/opportunites"]


@pytest.fixture()
def connecte(client, db):
    db.execute("""INSERT INTO members(nom,email,company,plan,subscription_status,
                  trial_ends,pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               ("Ahmed", "audit@example.com", "SARL ALPHA", "pro", "ACTIVE",
                (date.today() + timedelta(days=90)).strftime("%Y-%m-%d"),
                "x", "jeton-audit-pages", 1, '["T101"]', 1))
    db.commit()
    client.cookies.set("_session", "jeton-audit-pages")
    return client


def _pages(client, connecte):
    """Toutes les pages, chacune demandée dans le bon état.

    `connecte` pose son cookie sur le même client: demander /login sans le
    retirer renvoyait une redirection, et l'audit croyait la page sans titre.
    """
    jeton = client.cookies.get("_session")
    client.cookies.delete("_session")
    try:
        for chemin in PUBLIQUES:
            yield chemin, client.get(chemin)
    finally:
        if jeton:
            client.cookies.set("_session", jeton)
    for chemin in MEMBRE:
        yield chemin, connecte.get(chemin)


class TestRendu:
    @pytest.mark.parametrize("chemin", PUBLIQUES)
    def test_les_pages_publiques_repondent(self, client, chemin):
        assert client.get(chemin).status_code == 200, chemin

    @pytest.mark.parametrize("chemin", MEMBRE)
    def test_les_pages_membre_renvoient_vers_la_connexion(self, client, chemin):
        """Anonyme, aucune ne doit répondre 200 ni tomber en erreur."""
        r = client.get(chemin, follow_redirects=False)
        assert r.status_code in (302, 303), f"{chemin} -> {r.status_code}"
        assert "/login" in r.headers.get("location", ""), chemin

    @pytest.mark.parametrize("chemin", MEMBRE)
    def test_les_pages_membre_repondent(self, connecte, chemin):
        assert connecte.get(chemin).status_code == 200, chemin


class TestStructure:
    def test_un_seul_titre_de_niveau_un_par_page(self, client, connecte):
        """Deux <h1> sur une page, c'est deux pages qui se disputent le sujet."""
        fautifs = {}
        for chemin, r in _pages(client, connecte):
            n = len(re.findall(r"<h1\b", r.text))
            if n > 1:
                fautifs[chemin] = n
        assert not fautifs, f"plusieurs <h1>: {fautifs}"

    def test_chaque_page_a_un_titre_de_fenetre(self, client, connecte):
        sans = [c for c, r in _pages(client, connecte)
                if not re.search(r"<title>\s*\S", r.text)]
        assert not sans, f"sans <title>: {sans}"

    def test_aucune_page_nexpose_une_clef_de_traduction(self, client, connecte):
        """« set_ch_tg » affiché en clair veut dire clef supprimée mais encore
        appelée: le visiteur lit un identifiant de code."""
        fautifs = {}
        for chemin, r in _pages(client, connecte):
            orphelines = re.findall(r">\s*((?:set|pr|tr|inv|feat|hero|channel)_[a-z0-9_]{3,})\s*<",
                                    r.text)
            if orphelines:
                fautifs[chemin] = sorted(set(orphelines))
        assert not fautifs, f"clefs affichées en clair: {fautifs}"

    def test_aucun_texte_de_remplacement_oublie(self, client, connecte):
        fautifs = {}
        for chemin, r in _pages(client, connecte):
            texte = html.unescape(r.text).lower()
            # « xxxx » n'en est pas un: « +212 6xx xxxxxx » est un format de
            # numéro, pas un bouche-trou oublié.
            trouves = [m for m in ("lorem ipsum", "à compléter", "todo:",
                                   "placeholder_", "undefined")
                       if m in texte]
            if trouves:
                fautifs[chemin] = trouves
        assert not fautifs, f"texte de remplacement: {fautifs}"


class TestLiensInternes:
    def test_aucun_lien_interne_ne_tombe_a_cote(self, client, connecte):
        """Un lien du menu vers une route inexistante se voit en production,
        pas dans les tests fonctionnels qui visent les routes directement."""
        morts = {}
        for chemin, r in _pages(client, connecte):
            for cible in set(re.findall(r'href="(/[^"#?]*)', r.text)):
                if cible.startswith(("/static", "/media")) or cible == chemin:
                    continue
                code = (connecte if chemin in MEMBRE else client).get(
                    cible, follow_redirects=False).status_code
                if code >= 400:
                    morts.setdefault(chemin, []).append(f"{cible} -> {code}")
        assert not morts, f"liens morts: {morts}"


class TestAccessibilite:
    def test_chaque_champ_a_une_etiquette(self, client, connecte):
        """Un champ sans étiquette n'est lisible ni au lecteur d'écran ni à
        l'œil quand le texte d'invite disparaît à la saisie."""
        fautifs = {}
        for chemin, r in _pages(client, connecte):
            ids_etiquetes = set(re.findall(r'<label[^>]+for="([^"]+)"', r.text))
            champs = re.findall(
                r'<(?:input|select|textarea)\b([^>]*)>', r.text)
            manquants = []
            for attrs in champs:
                if re.search(r'type="(hidden|submit|checkbox|radio)"', attrs):
                    continue
                if "aria-label" in attrs:
                    continue
                m = re.search(r'id="([^"]+)"', attrs)
                if not m or m.group(1) not in ids_etiquetes:
                    nom = re.search(r'name="([^"]+)"', attrs)
                    manquants.append(nom.group(1) if nom else "(sans nom)")
            if manquants:
                fautifs[chemin] = manquants
        assert not fautifs, f"champs sans étiquette: {fautifs}"
