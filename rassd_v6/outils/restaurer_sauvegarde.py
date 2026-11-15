"""Recolle une sauvegarde reçue sur Telegram et la décompresse.

Téléchargez tous les morceaux dans un même dossier, puis:
    py outils\\restaurer_sauvegarde.py <dossier> [fichier de sortie]
Les morceaux s'appellent atlas_AAAAMMJJ_HHMMSS.db.gz.part01of03, ...; une
sauvegarde en un seul morceau s'appelle atlas_....db.gz. Le résultat est une
base SQLite complète (atlas_restauree.db par défaut), vérifiée à la fin.
"""
import gzip, pathlib, re, shutil, sqlite3, sys

dossier = pathlib.Path(sys.argv[1])
sortie = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "atlas_restauree.db")
morceaux = sorted(dossier.glob("*.gz.part*of*"))
if morceaux:
    n = int(re.search(r"of(\d+)$", morceaux[0].name).group(1))
    if len(morceaux) != n:
        sys.exit(f"{len(morceaux)} morceau(x) sur {n}: il en manque.")
    archive = dossier / morceaux[0].name.split(".part")[0]
    with open(archive, "wb") as out:
        for m in morceaux:
            out.write(m.read_bytes())
else:
    gz = sorted(dossier.glob("atlas_*.db.gz"))
    if not gz:
        sys.exit("Aucune sauvegarde trouvée dans ce dossier.")
    archive = gz[-1]
with gzip.open(archive, "rb") as src, open(sortie, "wb") as dst:
    shutil.copyfileobj(src, dst)
db = sqlite3.connect(sortie)
etat = db.execute("PRAGMA integrity_check").fetchone()[0]
n = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
db.close()
print(f"{sortie}: {etat}, {n} marchés")
