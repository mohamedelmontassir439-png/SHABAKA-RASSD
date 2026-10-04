# -*- coding: utf-8 -*-
"""Le code doit compiler avec les règles de la version du serveur.

Le serveur tourne en Python 3.11 (.python-version), le poste de
développement en 3.14. Entre les deux, PEP 701 a levé l'interdiction des
antislashs dans la partie expression d'une f-string. Résultat: un fichier
qui compile ici échouait là-bas, et l'étape « gagnants » tombait à chaque
cycle de collecte sans qu'aucun test ne bronche.

    ❌ Gagnants: f-string expression part cannot include a backslash

Ce test rejoue la règle ancienne à la main, puisqu'un interpréteur 3.14 ne
sait plus la faire respecter.
"""
import ast
import glob
import os
import re

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fichiers():
    for chemin in glob.glob(os.path.join(RACINE, "**", "*.py"), recursive=True):
        if "__pycache__" in chemin or ".venv" in chemin:
            continue
        yield chemin


class TestVersionDuServeur:
    def test_la_version_visee_est_declaree(self):
        """Sans ce fichier, on ne saurait pas quelles règles appliquer."""
        chemin = os.path.join(RACINE, ".python-version")
        assert os.path.exists(chemin)
        with open(chemin, encoding="utf-8") as f:
            version = f.read().strip()
        assert re.match(r"^3\.\d+$", version), version


class TestFStrings:
    def test_aucun_antislash_dans_une_expression_de_f_string(self):
        """Interdit avant 3.12 — et le serveur est en 3.11."""
        fautifs = []
        for chemin in _fichiers():
            with open(chemin, encoding="utf-8") as f:
                for n, ligne in enumerate(f, 1):
                    if 'f"' not in ligne and "f'" not in ligne:
                        continue
                    for m in re.finditer(r"\{([^{}]+)\}", ligne):
                        if "\\" in m.group(1):
                            fautifs.append(
                                f"{os.path.relpath(chemin, RACINE)}:{n} → {{{m.group(1)[:50]}}}")
        assert not fautifs, "antislash dans une f-string:\n  " + "\n  ".join(fautifs)

    # Un second piege existe avant 3.12 — f"{d["cle"]}", guillemets identiques
    # imbriques — mais aucune expression reguliere ne le distingue d'un
    # dictionnaire ordinaire: la mienne signalait cinq lignes de i18n.py qui
    # ne sont pas des f-strings, et sa propre source. Un garde-fou qui crie a
    # tort finit par être ignore; mieux vaut ne pas le poser.


class TestSyntaxeGenerale:
    def test_tout_le_projet_s_analyse(self):
        """Un fichier qui ne s'analyse pas ne se déploie pas."""
        casses = []
        for chemin in _fichiers():
            with open(chemin, encoding="utf-8") as f:
                try:
                    ast.parse(f.read(), filename=chemin)
                except SyntaxError as e:
                    casses.append(f"{os.path.relpath(chemin, RACINE)}:{e.lineno} {e.msg}")
        assert not casses, casses
