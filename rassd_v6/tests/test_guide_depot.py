# -*- coding: utf-8 -*-
"""Le guide public du dépôt électronique."""
import re


class TestGuide:
    def test_public_et_bilingue(self, client, db):
        fr = client.get("/guide/depot-electronique?lang=fr")
        assert fr.status_code == 200 and "marchespublics.gov.ma" in fr.text
        assert "Barid eSign" in fr.text and "accusé de réception" in fr.text
        ar = client.get("/guide/depot-electronique?lang=ar").text
        assert "شهادة التوقيع الإلكتروني" in ar

    def test_reference_pour_les_moteurs(self, client, db):
        h = client.get("/guide/depot-electronique").text.split("</head>")[0]
        assert '"@type": "HowTo"' in h and 'content="index,follow"' in h
        assert "/guide/depot-electronique" in client.get("/sitemap.xml").text

    def test_schemas_sans_variable_dans_les_attributs(self):
        """Une variable CSS dans fill="…" ne s'affiche pas: style seulement."""
        with open("templates/guide_depot.html", encoding="utf-8") as f:
            g = f.read()
        assert not re.search(r'\s(fill|stroke)="var\(', g)

    def test_lien_depuis_la_case_depot(self):
        with open("templates/detail.html", encoding="utf-8") as f:
            assert "/guide/depot-electronique" in f.read()
