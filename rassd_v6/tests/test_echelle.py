# -*- coding: utf-8 -*-
"""Une seule échelle typographique, et personne n'en sort.

Trente-six tailles de police coexistaient: 13 px à côté de 13,5, 12 à côté
de 12,5, et la même icône d'état vide valait 48 px sur une page, 56 sur une
autre, 72 sur une troisième. Pris un par un, ces écarts ne se voient pas;
ensemble, ils font qu'aucune page n'a l'air réglée.

Ces tests empêchent la dérive de recommencer: toute taille passe par un
jeton, tout jeton est défini quelque part dans la chaîne d'héritage.
"""
import glob
import os
import re

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GABARITS = os.path.join(RACINE, "templates")

# Les coquilles qui déclarent l'échelle; toute autre page en hérite.
COQUILLES = ("base.html", "base_public.html", "admin_base.html", "admin_login.html")

PAS_ATTENDUS = {"--f1", "--f2", "--f3", "--f4", "--f5", "--f6", "--f7", "--f8"}


def _pages():
    for chemin in sorted(glob.glob(os.path.join(GABARITS, "*.html"))):
        with open(chemin, encoding="utf-8") as f:
            yield os.path.basename(chemin), f.read()


class TestAucuneValeurEnDur:
    def test_aucune_taille_de_police_en_pixels(self):
        """Une taille écrite en dur est une taille que personne ne reverra."""
        fautifs = {}
        for nom, contenu in _pages():
            brutes = re.findall(r"font-size:\s*([\d.]+px)", contenu)
            if brutes:
                fautifs[nom] = sorted(set(brutes))
        assert not fautifs, f"tailles hors échelle: {fautifs}"

    def test_aucun_rayon_en_pixels_dans_ladministration(self):
        fautifs = {}
        for nom, contenu in _pages():
            if not nom.startswith("admin"):
                continue
            brutes = re.findall(r"border-radius:\s*([\d.]+px)", contenu)
            if brutes:
                fautifs[nom] = sorted(set(brutes))
        assert not fautifs, f"rayons hors échelle: {fautifs}"


class TestJetonsResolus:
    def test_toute_page_autonome_declare_ce_quelle_utilise(self):
        """Un jeton non défini rend la règle invalide: le navigateur revient
        à sa taille par défaut, et la page part en morceaux."""
        orphelins = {}
        for nom, contenu in _pages():
            utilises = set(re.findall(r"var\((--f\d|--fg|--r\d|--rp)\)", contenu))
            if not utilises or "{% extends" in contenu:
                continue
            definis = set(re.findall(r"(--f\d|--fg|--r\d|--rp)\s*:", contenu))
            manquants = utilises - definis
            if manquants:
                orphelins[nom] = sorted(manquants)
        assert not orphelins, f"jetons non définis: {orphelins}"

    @pytest.mark.parametrize("coquille", COQUILLES)
    def test_chaque_coquille_declare_les_huit_pas(self, coquille):
        with open(os.path.join(GABARITS, coquille), encoding="utf-8") as f:
            definis = set(re.findall(r"(--f\d)\s*:", f.read()))
        assert PAS_ATTENDUS <= definis, f"{coquille} ne déclare pas {PAS_ATTENDUS - definis}"


class TestEchelleCoherente:
    def test_les_pas_sont_strictement_croissants(self):
        """Deux pas de même valeur, ou inversés, et la hiérarchie ne tient plus."""
        with open(os.path.join(GABARITS, "base_public.html"), encoding="utf-8") as f:
            contenu = f.read()
        valeurs = [float(v) for _, v in sorted(
            re.findall(r"(--f(\d)):\s*([\d.]+)px", contenu.replace("--f", "--f"))
            and re.findall(r"--f(\d):\s*([\d.]+)px", contenu))]
        assert valeurs == sorted(valeurs) and len(set(valeurs)) == len(valeurs)

    def test_les_trois_coquilles_portent_la_meme_echelle(self):
        """Une échelle qui diffère entre l'admin et le public, c'est deux
        plateformes qui se ressemblent de loin."""
        echelles = {}
        for coquille in ("base.html", "base_public.html", "admin_base.html"):
            with open(os.path.join(GABARITS, coquille), encoding="utf-8") as f:
                echelles[coquille] = dict(re.findall(r"(--f\d):\s*([\d.]+px)", f.read()))
        reference = echelles["base_public.html"]
        for nom, valeurs in echelles.items():
            communs = set(reference) & set(valeurs)
            differents = {k: (reference[k], valeurs[k]) for k in communs
                          if reference[k] != valeurs[k]}
            assert not differents, f"{nom} diverge: {differents}"


class TestEtatsVides:
    def test_le_glyphe_detat_vide_a_une_seule_taille(self):
        """Il valait 48 px ici, 56 là, 72 ailleurs — pour la même chose."""
        tailles = set()
        for nom, contenu in _pages():
            for m in re.finditer(r"\.empty-(?:icon|glyph)\s*\{[^}]*font-size:\s*([^;}]+)",
                                 contenu):
                tailles.add(m.group(1).strip())
        assert len(tailles) <= 1, f"plusieurs tailles de glyphe: {tailles}"
