"""
Configuration pytest — Maroc Entrepreneuriat

Chaque test s'exécute sur une base SQLite temporaire: aucun test ne doit
pouvoir lire ni modifier la base de développement ou de production. La
variable DB_PATH est donc positionnée avant tout import de l'application.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Doit être défini avant l'import de app.core.config (lecture à l'import).
_TMP_DB = Path(tempfile.gettempdir()) / "atlas_test.db"
os.environ["DB_PATH"] = str(_TMP_DB)
os.environ.setdefault("ADMIN_PASS", "test_admin_password_1234567890")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-0123456789")


@pytest.fixture()
def db():
    """Base vierge, initialisée avec le schéma complet, détruite après le test."""
    if _TMP_DB.exists():
        _TMP_DB.unlink()
    from app.core.database import init_db, get_db
    init_db()

    # Le limiteur de débit est un état de module partagé entre les tests: sans
    # remise à zéro, les inscriptions d'un test épuisent le quota (5 par IP)
    # et font échouer les suivants pour une raison sans rapport avec eux.
    try:
        import main
        main._login_attempts.clear()
    except Exception:
        pass

    conn = get_db()
    yield conn
    conn.close()
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(_TMP_DB) + suffix)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


class SyncASGIClient:
    """Client HTTP synchrone minimal au-dessus de l'application ASGI.

    starlette.TestClient n'est pas utilisable ici: il appelle
    httpx.Client(app=...), raccourci retiré dans httpx >= 0.28, et
    ASGITransport y est désormais purement asynchrone. Ce pont exécute donc
    chaque requête dans une boucle d'événements dédiée, ce qui garde des
    tests synchrones et lisibles sans ajouter pytest-asyncio.

    Le cycle de vie (lifespan) n'est volontairement pas déclenché: la base
    est initialisée par la fixture `db`, et on évite de lancer les tâches de
    fond (veille, sauvegardes) pendant les tests.
    """

    def __init__(self, app):
        import httpx
        self._app = app
        self._httpx = httpx
        self.cookies = httpx.Cookies()

    def request(self, method: str, url: str, **kwargs):
        import asyncio

        async def _send():
            transport = self._httpx.ASGITransport(app=self._app)
            async with self._httpx.AsyncClient(
                transport=transport, base_url="http://testserver", cookies=self.cookies
            ) as ac:
                resp = await ac.request(method, url, **kwargs)
                self.cookies.update(ac.cookies)
                return resp

        return asyncio.run(_send())

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


@pytest.fixture()
def client(db):
    """Client HTTP de test sur l'application réelle."""
    import main
    return SyncASGIClient(main.app)
