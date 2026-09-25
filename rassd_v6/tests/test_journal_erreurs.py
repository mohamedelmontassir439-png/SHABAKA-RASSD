"""Le journal des erreurs ne doit contenir que de vraies erreurs.

Constaté en production: 8 « erreurs » en 7 jours, toutes provoquées par des
visiteurs ou des robots qui ferment la connexion pendant l'envoi de la
réponse. Starlette les remonte comme des exceptions applicatives. Les
compter comme des bugs finit par faire sonner la supervision pour rien — et
un journal qui crie au loup n'est plus lu.
"""
import anyio
import pytest
from starlette.requests import Request

import main


def _requete(chemin="/login", methode="POST"):
    return Request({"type": "http", "method": methode, "path": chemin,
                    "headers": [], "query_string": b"", "scheme": "https",
                    "server": ("marocentrepreneuriat.com", 443),
                    "client": ("1.2.3.4", 1234), "root_path": "", "app": main.app})


class TestReconnaissanceDesDeconnexions:
    @pytest.mark.parametrize("exc", [
        RuntimeError("No response returned."),
        anyio.ClosedResourceError(),
        anyio.BrokenResourceError(),
        ConnectionResetError("connection reset by peer"),
        BrokenPipeError(),
    ])
    def test_deconnexion_identifiee(self, exc):
        assert main._client_parti(exc) is True

    @pytest.mark.parametrize("exc", [
        ValueError("secteur inconnu"),
        KeyError("montant"),
        RuntimeError("base de données verrouillée"),
        TypeError("objet non sérialisable"),
    ])
    def test_vraie_erreur_non_confondue(self, exc):
        assert main._client_parti(exc) is False


class TestJournalisation:
    def _erreurs(self, db):
        return db.execute("SELECT COUNT(*) FROM error_log").fetchone()[0]

    def test_deconnexion_non_journalisee(self, db):
        avant = self._erreurs(db)
        reponse = _appeler(main.unhandled_exception_handler,
                           _requete(), RuntimeError("No response returned."))
        assert reponse.status_code == 499
        assert self._erreurs(db) == avant, "rien ne doit entrer au journal"

    def test_vraie_erreur_journalisee_avec_sa_trace(self, db):
        avant = self._erreurs(db)
        reponse = _appeler(main.unhandled_exception_handler,
                           _requete("/tenders", "GET"), ValueError("secteur inconnu"))
        assert reponse.status_code == 500
        assert self._erreurs(db) == avant + 1

        ligne = db.execute(
            "SELECT * FROM error_log ORDER BY created_at DESC LIMIT 1").fetchone()
        assert ligne["path"] == "/tenders" and ligne["method"] == "GET"
        assert "secteur inconnu" in ligne["message"]

    def test_la_page_reste_brandee(self, db):
        reponse = _appeler(main.unhandled_exception_handler,
                           _requete("/", "GET"), ValueError("boum"))
        assert b"MAROC" in reponse.body or b"Maroc" in reponse.body


def _appeler(handler, requete, exc):
    """Exécute un handler asynchrone depuis un test synchrone."""
    resultat = {}

    async def _go():
        resultat["r"] = await handler(requete, exc)

    anyio.run(_go)
    return resultat["r"]
