# -*- coding: utf-8 -*-
"""Le langage du récit de l'accueil, porté sur tout le site (08/11/2026).

Chaque page publique s'ouvre sur une photographie réelle du Maroc, les pages
de compte la montrent à côté du formulaire, et l'espace membre la garde en
bande au-dessus de chaque rubrique. Ce qui compte: que la photo existe, que
son lieu soit dit dans la langue de la page, et qu'aucune page n'y perde son
titre.
"""
import re

import pytest

from app.core.photos import PHOTOS


@pytest.fixture()
def membre(client, db):
    from datetime import date, timedelta
    db.execute("""INSERT INTO members(nom,email,plan,subscription_status,trial_ends,
                  pw_hash,session_token,actif,secteurs,email_verified)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
               ("Salma", "bandeau@example.com", "monthly", "ACTIVE",
                (date.today() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "x", "jeton-bandeaux", 1, '["T101"]', 1))
    db.commit()
    client.cookies.set("_session", "jeton-bandeaux")
    return client


def _photo(page):
    m = re.search(r'/static/img/recit/([a-z-]+)\.webp', page)
    return m and m.group(1)


@pytest.mark.parametrize("url", ["/tarifs", "/contact", "/marches-publics", "/guide/depot-electronique"])
def test_les_pages_publiques_ouvrent_sur_une_photo(client, url):
    page = client.get(url).text
    assert 'class="bandeau-fond"' in page and "sur-bandeau" in page
    assert _photo(page) in PHOTOS
    assert len(re.findall(r"<h1\b", page)) == 1


@pytest.mark.parametrize("url", ["/login", "/register", "/forgot"])
def test_les_pages_de_compte_montrent_la_photo_a_cote_du_formulaire(client, url):
    page = client.get(url).text
    assert 'class="auth-photo"' in page and "auth-scene" in page and "<form" in page
    assert _photo(page) in PHOTOS


def test_le_lieu_suit_la_langue(client):
    assert PHOTOS["chantier-rabat"]["lieu_ar"] in client.get("/login?lang=ar").text
    assert PHOTOS["chantier-rabat"]["lieu"] in client.get("/login?lang=fr").text


def test_chaque_rubrique_de_l_espace_membre_a_sa_photo(membre):
    vues = {}
    for url in ("/dashboard", "/tenders", "/resultats", "/suivi", "/settings"):
        page = membre.get(url).text
        assert 'class="app-bandeau"' in page, url
        vues[url] = _photo(page[page.index('class="app-bandeau"'):])
        assert vues[url] in PHOTOS, url
    assert len(set(vues.values())) >= 4, "une même photo partout ne situe rien"
