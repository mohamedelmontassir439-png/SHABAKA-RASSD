"""
Génère un annuaire d'entreprises en PDF, classé par secteur.

Fonctionne en local, sans rien écrire dans la base du projet: le script lit
un fichier JSON produit par collecte_maps.py (ou, si demandé, la base) et
produit un seul PDF prêt à imprimer.

Le rendu passe par Chromium (déjà installé pour la collecte), ce qui évite
d'ajouter une dépendance PDF au projet et donne une vraie mise en page.

Utilisation:
    py rapport_pdf.py                                  # depuis entreprises_maroc.json
    py rapport_pdf.py --source entreprises_maroc.json --sortie annuaire.pdf
    py rapport_pdf.py --depuis-base                    # depuis la base locale
    py rapport_pdf.py --avec-contact                   # seulement les fiches contactables
    py rapport_pdf.py --par ville                      # classer par ville au lieu du secteur
"""
import argparse
import html
import io
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, ".")

CSS = """
@page { size: A4; margin: 14mm 10mm 16mm 10mm; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", Arial, sans-serif; color: #2b211b; font-size: 9pt; }

.couverture { height: 240mm; display: flex; flex-direction: column; justify-content: center;
              text-align: center; page-break-after: always; }
.couverture h1 { font-size: 30pt; color: #1e1611; letter-spacing: -.5pt; }
.couverture h1 em { font-style: normal; color: #f2662d; }
.couverture .sous { font-size: 13pt; color: #8a7a6a; margin-top: 10mm; }
.couverture .date { font-size: 10pt; color: #b7a896; margin-top: 4mm; }
.resume { display: flex; justify-content: center; gap: 8mm; margin-top: 16mm; flex-wrap: wrap; }
.res-case { border: 1px solid #e8dcc5; border-radius: 3mm; padding: 5mm 7mm; min-width: 32mm; }
.res-n { font-size: 20pt; font-weight: 800; color: #f2662d; }
.res-l { font-size: 8pt; color: #8a7a6a; margin-top: 1.5mm; }
.note-couv { margin: 14mm auto 0; max-width: 130mm; font-size: 8.5pt; color: #8a7a6a;
             line-height: 1.6; border-top: 1px solid #e8dcc5; padding-top: 5mm; }

.groupe { page-break-before: always; }
.groupe:first-of-type { page-break-before: avoid; }
.groupe-titre { font-size: 14pt; font-weight: 700; color: #1e1611; padding-bottom: 2mm;
                border-bottom: 2px solid #f2662d; margin-bottom: 4mm; }
.groupe-titre span { font-size: 9pt; font-weight: 500; color: #8a7a6a; margin-left: 3mm; }

table { width: 100%; border-collapse: collapse; }
thead { display: table-header-group; }   /* en-tête répété à chaque page */
tr { page-break-inside: avoid; }
th { background: #f1e6cf; color: #4a3b32; font-size: 7.5pt; text-transform: uppercase;
     letter-spacing: .3pt; text-align: left; padding: 2mm; border: .3mm solid #e8dcc5; }
td { padding: 2mm; border: .3mm solid #e8dcc5; font-size: 8pt; vertical-align: top;
     word-break: break-word; }
tr:nth-child(even) td { background: #fcfaf5; }
.nom { font-weight: 700; color: #1e1611; }
.cat { color: #8a7a6a; font-size: 7pt; }
.tel { white-space: nowrap; font-weight: 600; }
.mail { color: #c94e1f; }
.vide { color: #d9c7a8; }

.pied { margin-top: 6mm; font-size: 7.5pt; color: #b7a896; text-align: center; }
"""


def charger_json(chemin):
    if not os.path.exists(chemin):
        print(f"Fichier introuvable: {chemin}")
        print("Lancez d'abord: py collecte_maps.py --secteurs T101 --villes Casablanca")
        return None
    with io.open(chemin, encoding="utf-8") as fh:
        return json.load(fh)


def charger_base():
    from app.core.database import get_db
    db = get_db()
    try:
        return [dict(r) for r in db.execute(
            "SELECT * FROM companies ORDER BY legal_name").fetchall()]
    finally:
        db.close()


def libelle_secteur(code):
    from app.core.sectors import SECTORS
    return f"{code} — {SECTORS.get(code, 'Secteur non précisé')}" if code else "Secteur non précisé"


def e(v):
    """Échappe et remplace une valeur vide par un tiret discret."""
    v = (v or "").strip()
    return html.escape(v) if v else '<span class="vide">—</span>'


def construire_html(fiches, par="secteur", titre="Annuaire des entreprises marocaines"):
    groupes = defaultdict(list)
    for f in fiches:
        cle = f.get("sector", "") if par == "secteur" else (f.get("city") or "Ville non précisée")
        groupes[cle].append(f)

    n_tel   = sum(1 for f in fiches if (f.get("phone") or "").strip())
    n_mail  = sum(1 for f in fiches if (f.get("email") or "").strip())
    n_web   = sum(1 for f in fiches if (f.get("website") or "").strip())
    maintenant = datetime.now().strftime("%d/%m/%Y à %H:%M")

    parts = [f"<!DOCTYPE html><html lang='fr'><head><meta charset='UTF-8'>",
             f"<title>{html.escape(titre)}</title><style>{CSS}</style></head><body>"]

    parts.append(f"""
    <div class="couverture">
      <h1>Annuaire des<br><em>entreprises marocaines</em></h1>
      <div class="sous">{len(fiches)} entreprises · {len(groupes)} {'secteurs' if par=='secteur' else 'villes'}</div>
      <div class="date">Document généré le {maintenant}</div>
      <div class="resume">
        <div class="res-case"><div class="res-n">{len(fiches)}</div><div class="res-l">Entreprises</div></div>
        <div class="res-case"><div class="res-n">{n_tel}</div><div class="res-l">Téléphones</div></div>
        <div class="res-case"><div class="res-n">{n_mail}</div><div class="res-l">Emails</div></div>
        <div class="res-case"><div class="res-n">{n_web}</div><div class="res-l">Sites web</div></div>
      </div>
      <div class="note-couv">
        Coordonnées d'établissements publiées publiquement par les entreprises elles-mêmes.
        Un tiret indique une information non publiée, jamais une valeur devinée.
        Vérifiez une coordonnée avant tout usage contractuel.
      </div>
    </div>""")

    def cle_tri(item):
        # Les groupes les plus fournis d'abord, à nombre égal par ordre alphabétique.
        return (-len(item[1]), str(item[0]))

    for cle, lot in sorted(groupes.items(), key=cle_tri):
        entete = libelle_secteur(cle) if par == "secteur" else html.escape(str(cle))
        lot = sorted(lot, key=lambda f: (
            0 if (f.get("phone") or f.get("email")) else 1,
            (f.get("legal_name") or "").lower()))
        parts.append(f'<div class="groupe"><div class="groupe-titre">{entete}'
                     f'<span>{len(lot)} entreprise(s)</span></div>')
        parts.append("<table><thead><tr>"
                     "<th style='width:26%'>Entreprise</th>"
                     "<th style='width:15%'>Téléphone</th>"
                     "<th style='width:22%'>Email</th>"
                     "<th style='width:12%'>Ville</th>"
                     "<th style='width:25%'>Site web / Adresse</th>"
                     "</tr></thead><tbody>")
        for f in lot:
            site = (f.get("website") or "").replace("https://", "").replace("http://", "").rstrip("/")
            adresse = (f.get("address") or "")[:70]
            complement = (f'{html.escape(site)}<br>' if site else "") + \
                         (f'<span class="cat">{html.escape(adresse)}</span>' if adresse else "")
            parts.append(
                "<tr>"
                f'<td><span class="nom">{html.escape((f.get("legal_name") or "")[:60])}</span>'
                + (f'<br><span class="cat">{html.escape((f.get("subsector") or "")[:40])}</span>'
                   if f.get("subsector") else "") + "</td>"
                f'<td class="tel">{e(f.get("phone"))}</td>'
                f'<td class="mail">{e(f.get("email"))}</td>'
                f'<td>{e(f.get("city"))}</td>'
                f'<td>{complement or chr(60) + "span class=" + chr(34) + "vide" + chr(34) + chr(62) + "—</span>"}</td>'
                "</tr>")
        parts.append("</tbody></table></div>")

    parts.append(f'<div class="pied">Annuaire généré le {maintenant} — {len(fiches)} entreprises</div>')
    parts.append("</body></html>")
    return "".join(parts)


def rendre_pdf(contenu_html, sortie):
    from playwright.sync_api import sync_playwright
    chemin_html = os.path.abspath("_annuaire_tmp.html")
    with io.open(chemin_html, "w", encoding="utf-8") as fh:
        fh.write(contenu_html)
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = nav.new_page()
            page.goto("file:///" + chemin_html.replace("\\", "/"), wait_until="load")
            page.pdf(path=sortie, format="A4", print_background=True,
                     margin={"top": "14mm", "bottom": "16mm", "left": "10mm", "right": "10mm"},
                     display_header_footer=True,
                     header_template="<div></div>",
                     footer_template=(
                         "<div style='width:100%;font-size:8px;color:#b7a896;"
                         "padding:0 10mm;display:flex;justify-content:space-between;'>"
                         "<span>Annuaire des entreprises marocaines</span>"
                         "<span>Page <span class='pageNumber'></span> / <span class='totalPages'></span></span>"
                         "</div>"))
            nav.close()
    finally:
        if os.path.exists(chemin_html):
            os.remove(chemin_html)


def main():
    ap = argparse.ArgumentParser(description="Annuaire d'entreprises en PDF")
    ap.add_argument("--source", default="entreprises_maroc.json", help="fichier JSON de collecte")
    ap.add_argument("--depuis-base", action="store_true", help="lire la base du projet au lieu du JSON")
    ap.add_argument("--sortie", default="", help="fichier PDF de sortie")
    ap.add_argument("--par", choices=["secteur", "ville"], default="secteur", help="critère de classement")
    ap.add_argument("--avec-contact", action="store_true", help="ne garder que les fiches avec téléphone ou email")
    args = ap.parse_args()

    fiches = charger_base() if args.depuis_base else charger_json(args.source)
    if fiches is None:
        return 1
    if args.avec_contact:
        fiches = [f for f in fiches if (f.get("phone") or "").strip() or (f.get("email") or "").strip()]
    if not fiches:
        print("Aucune fiche à imprimer.")
        return 1

    sortie = args.sortie or f"annuaire_entreprises_{datetime.now().strftime('%Y%m%d')}.pdf"
    print(f"{len(fiches)} entreprises · classement par {args.par}")
    rendre_pdf(construire_html(fiches, args.par), sortie)
    taille = os.path.getsize(sortie) / 1024
    print(f"PDF écrit : {os.path.abspath(sortie)}  ({taille:.0f} Ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
