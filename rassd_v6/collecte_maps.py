"""
Collecte Google Maps à lancer depuis un poste local, puis import en production.

Le serveur Railway n'embarque pas de navigateur (Chromium pèse ~400 Mo et
demande des dépendances système), donc la collecte Maps tourne sur votre
machine. Ce script produit un fichier JSON à importer ensuite depuis
/admin/companies.

Utilisation:
    py collecte_maps.py --secteurs T101,T104 --villes Casablanca,Rabat
    py collecte_maps.py --tout                     # les 83 secteurs, 20 villes
    py collecte_maps.py --secteurs T101 --villes Casablanca --sans-email

Prérequis (une seule fois):
    py -m pip install playwright
    py -m playwright install chromium
"""
import argparse
import io
import json
import sys
from datetime import datetime

sys.path.insert(0, ".")


def main():
    ap = argparse.ArgumentParser(description="Collecte d'entreprises depuis Google Maps")
    ap.add_argument("--secteurs", default="", help="codes séparés par des virgules (ex: T101,T104)")
    ap.add_argument("--villes", default="", help="villes séparées par des virgules")
    ap.add_argument("--tout", action="store_true", help="tous les secteurs et toutes les villes")
    ap.add_argument("--max", type=int, default=20, help="fiches max par recherche (défaut 20)")
    ap.add_argument("--sans-email", action="store_true", help="ne pas visiter les sites web")
    ap.add_argument("--visible", action="store_true", help="afficher le navigateur")
    ap.add_argument("--sortie", default="", help="fichier JSON de sortie")
    args = ap.parse_args()

    from app.core.sectors import SECTORS
    from app.services.maps_scraper import VILLES, collecter_requete, requete_secteur, BlocageGoogle
    from app.services.email_finder import find_email

    if args.tout:
        secteurs, villes = list(SECTORS.keys()), VILLES
    else:
        secteurs = [s.strip() for s in args.secteurs.split(",") if s.strip()] or ["T101"]
        villes   = [v.strip() for v in args.villes.split(",") if v.strip()] or ["Casablanca"]

    inconnus = [s for s in secteurs if s not in SECTORS]
    if inconnus:
        print(f"Codes secteur inconnus: {', '.join(inconnus)}")
        return 1

    sortie = args.sortie or f"entreprises_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    print(f"{len(secteurs)} secteur(s) × {len(villes)} ville(s) → {sortie}\n")

    from playwright.sync_api import sync_playwright
    fiches, bloque = [], False
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=not args.visible, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = nav.new_context(
            locale="fr-FR", timezone_id="Africa/Casablanca",
            viewport={"width": 1360, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"))
        page = ctx.new_page()
        try:
            for code in secteurs:
                if bloque:
                    break
                for ville in villes:
                    print(f"▸ {code} · {ville}")
                    try:
                        lot = collecter_requete(page, requete_secteur(code), ville, code,
                                                args.max, lambda m: print(m))
                    except BlocageGoogle as e:
                        print(f"\n⛔ {e}\n")
                        bloque = True
                        break
                    except Exception as e:
                        print(f"  ⚠ {str(e)[:120]}")
                        continue
                    if not args.sans_email:
                        for f in lot:
                            if f.get("website"):
                                email = find_email(f["website"])
                                if email:
                                    f["email"] = email
                    fiches.extend(lot)
                    print(f"✓ {code} · {ville} — {len(lot)} fiche(s) (total {len(fiches)})\n")
        finally:
            ctx.close(); nav.close()

    with io.open(sortie, "w", encoding="utf-8") as fh:
        json.dump(fiches, fh, ensure_ascii=False, indent=2)

    avec_tel   = sum(1 for f in fiches if f.get("phone"))
    avec_email = sum(1 for f in fiches if f.get("email"))
    print(f"\n═══ {len(fiches)} fiches · {avec_tel} téléphones · {avec_email} emails ═══")
    print(f"Fichier écrit : {sortie}")
    print("Importez-le depuis /admin/companies (bouton « Importer un fichier »).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
