# -*- coding: utf-8 -*-
"""La lecture du dossier de consultation (CPS, règlement)."""
import io
import zipfile
from datetime import date, timedelta

import pytest

from app.services.analyse_dossier import analyser, analyser_texte, bordereau

CPS = """ARTICLE 5 : PIECES A FOURNIR PAR LES CONCURRENTS
Le dossier administratif comprend :
- la déclaration sur l'honneur ;
- l'original du récépissé du cautionnement provisoire ;
- l'attestation de la CNSS délivrée depuis moins d'un an.
ARTICLE 12 : DELAI D'EXECUTION
Le délai d'exécution des travaux est fixé à 6 mois à compter de la date de l'ordre de service.
ARTICLE 14 : PENALITES POUR RETARD
Il sera appliqué à l'entrepreneur une pénalité journalière de 2/1000 du montant du marché. Le montant cumulé des pénalités est plafonné à 10% du montant initial du marché.
ARTICLE 15 : CAUTIONNEMENT DEFINITIF ET RETENUE DE GARANTIE
Le cautionnement définitif est fixé à 3% du montant initial du marché. La retenue de garantie est fixée à 7% du montant de chaque acompte. Le délai de garantie est de 12 mois.
ARTICLE 18 : CARACTERE DES PRIX
Les prix du présent marché sont fermes et non révisables.
ARTICLE 20 : MODALITES DE PAIEMENT
Le paiement sera effectué dans un délai de 90 jours à compter de la constatation du service fait.
ARTICLE 25 : CRITERES D'EVALUATION DES OFFRES
1) Moyens humains
2) Références techniques
BORDEREAU DES PRIX
1 Terrassement en grande masse m3 1 200
2 Béton de propreté dosé à 150 kg m3 45
3 Fourniture et pose de bordures T3 ml 320,50
"""


def _pdf(lignes):
    """Un vrai PDF texte, minimal, écrit à la main."""
    flux = "BT /F1 9 Tf 40 800 Td 11 TL " + " ".join(
        "(" + l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '" for l in lignes) + " ET"
    flux = flux.encode("latin-1", "replace")
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(flux)).encode() + b" >>\nstream\n" + flux + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    sortie, positions = io.BytesIO(), []
    sortie.write(b"%PDF-1.4\n")
    for i, o in enumerate(objets, 1):
        positions.append(sortie.tell())
        sortie.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
    xref = sortie.tell()
    sortie.write(f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode())
    for p in positions:
        sortie.write(f"{p:010d} 00000 n \n".encode())
    sortie.write(f"trailer << /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return sortie.getvalue()


def _docx(texte):
    corps = "".join(f"<w:p><w:r><w:t>{l.replace('&', '&amp;').replace('<', '&lt;')}</w:t></w:r></w:p>"
                    for l in texte.split("\n"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document><w:body>{corps}</w:body></w:document>')
    return buf.getvalue()


class TestLecture:
    def test_valeurs_et_alertes(self):
        r = analyser_texte(CPS)
        assert r["delai_execution"]["valeur"] == "6 mois"
        assert r["penalites"]["valeur"].startswith("2/1000") and r["penalites"]["alerte"]
        assert r["plafond_penalites"]["valeur"].startswith("10 %") and not r["plafond_penalites"]["alerte"]
        assert r["caution_definitive"]["valeur"].startswith("3 %")
        assert r["retenue_garantie"]["valeur"].startswith("7 %"), "pas le taux du titre d'article"
        assert r["paiement"]["valeur"] == "90 jours" and r["paiement"]["alerte"]
        assert r["prix"]["valeur"] == "Fermes et non révisables"
        assert sorted(r["alertes"]) == ["paiement", "penalites"]

    def test_chaque_valeur_porte_sa_source(self):
        r = analyser_texte(CPS)
        assert "7%" in r["retenue_garantie"]["source"]

    def test_listes(self):
        r = analyser_texte(CPS)
        assert len(r["pieces"]) == 3 and "CNSS" in r["pieces"][2]
        assert r["criteres"] == ["Moyens humains", "Références techniques"]

    def test_bordereau(self):
        b = bordereau(CPS)
        assert [(l["n"], l["unite"], l["quantite"]) for l in b] == [
            ("1", "m3", "1 200"), ("2", "m3", "45"), ("3", "ml", "320,50")]


class TestFormats:
    def test_pdf(self):
        r = analyser(_pdf(CPS.split("\n")), "cps.pdf")
        assert "erreur" not in r, r
        assert r["delai_execution"]["valeur"] == "6 mois"

    def test_docx(self):
        r = analyser(_docx(CPS), "cps.docx")
        assert r["retenue_garantie"]["valeur"].startswith("7 %")

    def test_archive_du_portail(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("DAO/CPS.docx", _docx(CPS))
            z.writestr("DAO/plans.dwg", b"binaire")
        r = analyser(buf.getvalue(), "dossier.zip")
        assert r["fichiers"] == ["CPS.docx"] and r["delai_execution"]

    def test_pdf_scanne(self):
        assert analyser(_pdf(["page"]), "scan.pdf")["erreur"] == "scanne"

    def test_format_inconnu(self):
        assert analyser(b"MZ\x90\x00binaire", "x.exe")["erreur"] == "format"


class TestParcours:
    def test_depot_affichage_et_csv(self, client, db):
        db.execute("""INSERT INTO members(id,nom,email,phone,company,plan,subscription_status,trial_ends,
                      pw_hash,session_token,actif,secteurs,email_verified)
                      VALUES(1,'Ahmed Alaoui','a@x.ma','0612345678','SIMAC','pro','ACTIVE',?,'x',
                      'jeton-analyse-1',1,'["T101"]',1)""", ((date.today() + timedelta(days=90)).isoformat(),))
        db.execute("""INSERT INTO tenders(id,objet,acheteur,secteur,region,statut,scraped_at,date_limite,
                      type_offre,type_procedure,source) VALUES('ao_5','Voirie','DP','T101','Rabat','actif',
                      '2026-10-01',?,'Public','marche','marchespublics')""",
                   ((date.today() + timedelta(days=20)).strftime("%d/%m/%Y"),))
        db.commit()
        client.cookies.set("_session", "jeton-analyse-1")
        client.get("/tenders/ao_5")
        r = client.post("/tenders/ao_5/analyser", data={"csrf_token": client.cookies.get("_csrf")},
                        files={"fichier": ("cps.docx", _docx(CPS), "application/octet-stream")},
                        follow_redirects=False)
        assert r.status_code == 302 and "analyse=" not in r.headers["location"]
        page = client.get("/tenders/ao_5").text
        assert "Pénalités de retard" in page and "À lire de près" in page
        csv = client.get("/tenders/ao_5/bordereau.csv")
        assert csv.status_code == 200 and "Terrassement en grande masse" in csv.content.decode("utf-8-sig")
        assert "=D2*E2" in csv.content.decode("utf-8-sig")
