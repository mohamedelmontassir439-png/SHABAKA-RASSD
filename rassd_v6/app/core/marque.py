# -*- coding: utf-8 -*-
"""Identité visuelle: un seul endroit d'où sort la marque.

Le signe est un globe de méridiens, posé sur un arc, dans un médaillon
cerclé. Il dit ce que fait la plateforme — une couverture nationale, une
veille qui embrasse tout le territoire — là où l'étoile précédente disait
l'orientation. L'étoile sous le nom est celle du drapeau marocain, un
zellige marocain et de l'ancien pavillon chérifien.

Tout est tracé en SVG: le trait reste net du favicon de seize pixels à
l'en-tête imprimé en A4, le fichier pèse quelques kilo-octets et s'insère
sans requête supplémentaire. Les emails font exception, traités plus bas:
Gmail supprime le SVG et bloque les images par défaut.

Le globe est construit, pas dessiné à la main: les méridiens sont des
ellipses de demi-largeur décroissante, les parallèles des ellipses de
demi-hauteur décroissante. Posés au jugé, ils donnent une pelote; calculés,
ils donnent une sphère.
"""
import math

# Teintes de la plateforme.
# Un seul orange sur toute la plateforme. La référence tire vers #e8621f,
# à l'œil indiscernable de celui des pages; en garder deux aurait fait
# jurer la marque contre ses propres boutons.
OR = "#f2662d"          # orange vif — l'accent, identique à --terre
OR_CLAIR = "#ff8c4a"    # orange clair — les reflets
TERRE = "#c94e1f"
ENCRE = "#17120f"       # presque noir, chaud
BRUN = "#3a1e12"        # brun profond du médaillon
CREME = "#f6efe6"


def _rotation(r: float, cle: str, duree: int = 21) -> str:
    """Le mouvement des méridiens, décrit une fois pour les trois.

    Un globe ne tourne pas en pivotant sur l'écran: ses méridiens
    s'amincissent jusqu'au trait quand ils passent de profil, puis
    s'élargissent. On anime donc `rx`, et rien d'autre — les parallèles,
    eux, sont invariants sous une rotation d'axe vertical, et les faire
    bouger trahirait la sphère.

    Les étapes suivent |cos θ| plutôt qu'une interpolation facile: avec un
    `ease-in-out`, le méridien ralentit au moment où il passe de profil,
    là où il devrait aller le plus vite, et le globe se met à respirer au
    lieu de tourner.

    Le style est écrit dans le SVG, non dans la feuille de la page: la
    marque est servie seule — favicon, en-tête de document, image de
    partage — et doit emporter son mouvement avec elle. Les classes portent
    la clé pour la même raison que les dégradés: deux marques sur une page
    ne doivent pas se commander l'une l'autre.

    Sans prise en charge de l'animation des propriétés géométriques, les
    attributs `rx` écrits sur les ellipses tiennent: on retrouve le globe
    immobile et bien composé d'avant.
    """
    pas = 12  # un demi-tour: au-delà, le méridien repasse par où il était
    etapes = "".join(
        # Un plancher, car `rx=0` n'est pas une ellipse plate: c'est une
        # ellipse qui ne se dessine pas. Le méridien disparaîtrait au lieu
        # de se réduire au trait qu'il doit être, vu de profil.
        f"{i * 100 / pas:.4g}%{{rx:{max(0.04, abs(r * math.cos(math.pi * i / pas))):.2f}px}}"
        for i in range(pas + 1))
    return (
        f"<style>"
        f"@keyframes tg{cle}{{{etapes}}}"
        f".mg{cle}{{animation:tg{cle} {duree}s linear infinite}}"
        f".mg{cle}b{{animation-delay:-{duree / 3:.1f}s}}"
        f".mg{cle}c{{animation-delay:-{2 * duree / 3:.1f}s}}"
        f"@media(prefers-reduced-motion:reduce){{.mg{cle}{{animation:none}}}}"
        f"</style>")


def _globe(rayon: float = 30.0, centre: float = 50.0, cle: str = "g",
           anime: bool = True) -> str:
    """La sphère: dégradé, méridiens, parallèles, reflet, liseré.

    Les identifiants sont suffixés pour qu'on puisse poser deux marques sur
    la même page sans que leurs dégradés se confondent.

    `anime` est faux là où le mouvement n'a pas de sens et pèse: le favicon,
    recopié dans l'en-tête de chaque page, et les documents imprimés.
    """
    c, r = centre, rayon
    classes = (f"mg{cle}", f"mg{cle} mg{cle}b", f"mg{cle} mg{cle}c")
    meridiens = "".join(
        f'<ellipse class="{classes[i] if anime else ""}" cx="{c}" cy="{c}" '
        f'rx="{r * f:.2f}" ry="{r}" '
        f'fill="none" stroke="{OR}" stroke-width="{0.9 if f else 1.1}" '
        f'opacity="{0.52 + 0.30 * (1 - f):.2f}"/>'
        for i, f in enumerate((0.80, 0.52, 0.22)))
    paralleles = "".join(
        f'<ellipse cx="{c}" cy="{c + r * d:.2f}" rx="{r * math.sqrt(1 - d * d):.2f}" '
        f'ry="{r * 0.17:.2f}" fill="none" stroke="{OR}" stroke-width="0.8" '
        f'opacity="{0.46 - 0.10 * abs(d):.2f}"/>'
        for d in (-0.55, -0.22, 0.14, 0.48))
    return (
        (_rotation(r, cle) if anime else "")
        + f'<defs>'
        f'<radialGradient id="sph{cle}" cx="36%" cy="28%" r="78%">'
        f'<stop offset="0%" stop-color="#c4702f"/>'
        f'<stop offset="44%" stop-color="#6b3317"/>'
        f'<stop offset="100%" stop-color="#1c100a"/>'
        f'</radialGradient>'
        f'<radialGradient id="ref{cle}" cx="50%" cy="50%" r="50%">'
        f'<stop offset="0%" stop-color="#ffffff" stop-opacity=".55"/>'
        f'<stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>'
        f'</radialGradient>'
        f'<clipPath id="clp{cle}"><circle cx="{c}" cy="{c}" r="{r}"/></clipPath>'
        f'</defs>'
        f'<circle cx="{c}" cy="{c}" r="{r}" fill="url(#sph{cle})"/>'
        f'<g clip-path="url(#clp{cle})">{meridiens}{paralleles}'
        f'<ellipse cx="{c - r * 0.34:.2f}" cy="{c - r * 0.42:.2f}" '
        f'rx="{r * 0.30:.2f}" ry="{r * 0.22:.2f}" fill="url(#ref{cle})"/></g>'
        f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{OR}" '
        f'stroke-width="1" opacity=".85"/>'
        # Pas de point de lumière. Il y en avait un, blanc, posé en haut à
        # droite du liseré: à distance il ne se lisait pas comme un reflet
        # mais comme une poussière sur l'écran. Le dégradé et le voile du
        # quart supérieur gauche suffisent à creuser la sphère.
    )


def _socle(centre: float = 50.0, rayon: float = 30.0) -> str:
    """L'arc sur lequel le globe repose."""
    c, r = centre, rayon
    y = c + r * 1.16
    return (f'<path d="M {c - r * 1.12:.1f} {y:.1f} Q {c} {y + r * 0.26:.1f} '
            f'{c + r * 1.12:.1f} {y:.1f}" fill="none" stroke="{OR}" '
            f'stroke-width="1.6" stroke-linecap="round" opacity=".92"/>')


def _etoile_marocaine(cx: float = 50, cy: float = 50, rayon: float = 44) -> str:
    """Les sommets de l'étoile du drapeau marocain, pour un `points="…"`.

    C'est le pentagramme {5/2}: cinq sommets reliés en sautant l'un sur
    deux, d'un seul trait qui se recroise. Tracé sans remplissage, il donne
    l'étoile entrelacée du drapeau — celle qu'on appelle le sceau de
    Salomon au Maroc.

    Rien à voir avec l'hexagramme qui occupait cette place: deux triangles
    superposés font une étoile à **six** branches, qui n'est pas celle du
    Maroc et se lit tout autrement. L'erreur est restée jusqu'au 05/10/2026.
    """
    sommets = []
    for k in range(5):
        a = math.radians(-90 + k * 144)      # 144° = deux cinquièmes de tour
        sommets.append(f"{cx + rayon * math.cos(a):.1f},{cy + rayon * math.sin(a):.1f}")
    return " ".join(sommets)


def sceau(taille: int = 14, couleur: str = OR) -> str:
    """L'étoile marocaine, d'un seul trait entrelacé."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{taille}" '
            f'height="{taille}" viewBox="0 0 100 100" role="presentation" '
            f'style="flex:none;vertical-align:middle">'
            f'<polygon points="{_etoile_marocaine()}" fill="none" '
            f'stroke="{couleur}" stroke-width="7" stroke-linejoin="miter"/></svg>')


def etoile(taille: int = 40, couleur: str = OR, fond: str = "none",
           anime: bool = True) -> str:
    """La marque seule: le globe dans son médaillon.

    Pour le favicon, l'icône de l'application et le rail d'administration.
    Sous vingt-quatre pixels les méridiens se referment en une tache: on ne
    garde alors que la sphère et son liseré, qui restent reconnaissables.
    """
    petit = taille < 24
    fond_rond = (f'<circle cx="50" cy="50" r="49" fill="{fond}"/>'
                 f'<circle cx="50" cy="50" r="47" fill="none" stroke="{OR}" '
                 f'stroke-width="1.6" opacity=".9"/>') if fond != "none" else ""
    cle = f"{taille}"
    corps = (f'<circle cx="50" cy="50" r="30" fill="#2a160d"/>'
             f'<circle cx="50" cy="50" r="30" fill="none" stroke="{couleur}" '
             f'stroke-width="3"/>') if petit else _globe(30, 50, cle, anime) + _socle()
    return (
        # flex:none et la largeur minimale protègent la marque: dans une barre
        # chargée, « svg { max-width: 100% } » la laissait se réduire à rien.
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{taille}" '
        f'height="{taille}" viewBox="0 0 100 100" role="img" '
        f'style="flex:none;min-width:{taille}px" '
        f'aria-label="Maroc Entrepreneuriat">{fond_rond}{corps}</svg>'
    )


def medaillon(taille: int = 160, fond: str = BRUN) -> str:
    """Le médaillon complet: globe, nom, étoile marocaine, mention.

    Mise en page calculée, pas ajustée à l'œil: le globe est centré à
    (150, 105) avec un rayon de 45, si bien que son arc tombe à y=157 — sous
    la sphère et au-dessus du nom, qu'il traversait auparavant. À 26 px,
    « Entrepreneuriat » mesure environ 218 px; la corde du cercle à cette
    hauteur en fait 240. Il tient, de justesse, et c'est pourquoi le corps
    ne doit pas remonter.

    La mention du bas suit la même contrainte, et elle y échouait: à 12 px
    avec 4 d'interlettrage elle mesurait 236 unités pour une corde de 165 à
    cette hauteur — elle traversait le cercle des deux côtés, et cela ne se
    voyait qu'en grand format. À 8 px avec 2,2 elle en fait 148.

    C'est la forme de couverture: page de garde d'un document, en-tête
    d'une page sombre, image de partage. Le nom y est tracé en SVG plutôt
    qu'en HTML pour que l'ensemble reste solidaire à toute taille.
    """
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{taille}" height="{taille}"
 viewBox="0 0 300 300" role="img" aria-label="Maroc Entrepreneuriat — couverture nationale"
 style="flex:none">
<defs>
  <radialGradient id="mfond" cx="50%" cy="38%" r="70%">
    <stop offset="0%" stop-color="#4a2214"/><stop offset="100%" stop-color="{ENCRE}"/>
  </radialGradient>
</defs>
<circle cx="150" cy="150" r="146" fill="url(#mfond)"/>
<circle cx="150" cy="150" r="143" fill="none" stroke="{OR}" stroke-width="2.4" opacity=".92"/>
<g transform="translate(75,30) scale(1.5)">{_globe(30, 50, "med")}{_socle()}</g>
<text x="150" y="203" text-anchor="middle" fill="{CREME}"
      font-family="Georgia,'Times New Roman',serif" font-weight="700" font-size="26">Maroc</text>
<text x="150" y="231" text-anchor="middle" fill="{OR}"
      font-family="Georgia,'Times New Roman',serif" font-weight="700" font-size="26">Entrepreneuriat</text>
<g transform="translate(143,241) scale(.14)">
  <polygon points="{_etoile_marocaine()}" fill="none" stroke="{OR}" stroke-width="7"/>
</g>
<text x="150" y="270" text-anchor="middle" fill="{CREME}" letter-spacing="2.2"
      font-family="Arial,Helvetica,sans-serif" font-weight="600" font-size="8"
      opacity=".86">COUVERTURE NATIONALE</text>
</svg>'''


def _mot(taille: float, couleur: str, texte: str, espace: float = 0) -> str:
    return (f'<div style="font-family:Georgia,\'Times New Roman\',serif;'
            f'font-weight:700;font-size:{taille:.1f}px;'
            f'letter-spacing:{espace:.2f}px;color:{couleur};'
            f'line-height:1.02;white-space:nowrap">{texte}</div>')


def logo(hauteur: int = 44, couleur: str = OR, couleur_texte: str = CREME,
         baseline: bool = False) -> str:
    """Marque et nom côte à côte.

    Le nom tient sur deux lignes — Maroc au-dessus, Entrepreneuriat en
    dessous, comme sur le médaillon. Sur une seule, vingt-deux lettres
    imposent soit une largeur que la barre n'a pas, soit un corps qui ne se
    lit plus.
    """
    ligne = (f'<div style="display:flex;align-items:center;gap:7px;margin-top:5px">'
             f'{sceau(max(9, round(hauteur * 0.20)), couleur)}'
             f'<span style="font-family:Arial,Helvetica,sans-serif;'
             f'font-size:{hauteur * 0.155:.1f}px;letter-spacing:{hauteur * 0.055:.2f}px;'
             f'color:{couleur_texte};opacity:.72;text-transform:uppercase;'
             f'white-space:nowrap">Couverture nationale</span></div>'
             if baseline else "")
    return (
        f'<span style="display:inline-flex;align-items:center;'
        f'gap:{max(10, round(hauteur * 0.28))}px;vertical-align:middle">'
        f'{etoile(hauteur, couleur)}'
        # Classe nommée: le rail masque le nom sous 1400 px pour rendre sa
        # largeur aux liens, et ne garde que la marque.
        f'<span class="me-logo-nom" style="display:block">'
        f'{_mot(hauteur * 0.40, couleur_texte, "Maroc")}'
        f'{_mot(hauteur * 0.40, couleur, "Entrepreneuriat")}'
        f'{ligne}</span></span>'
    )


def entete_document(hauteur: int = 52) -> str:
    """En-tête des documents qu'un membre imprime et remet.

    Sur papier, le fond est blanc: le nom passe en encre, pas en crème.

    Et la mention « couverture nationale » ne suffit pas ici. Une déclaration
    de sous-traitance part chez un maître d'ouvrage: elle doit dire ce que
    la plateforme couvre, marchés semi-publics compris, sans qu'on le
    demande. Le logo porte la devise, le document porte la phrase.
    """
    return (
        f'<div style="display:flex;flex-direction:column;gap:7px">'
        f'{logo(hauteur, couleur_texte=ENCRE, baseline=True)}'
        f'<div style="font-family:Arial,Helvetica,sans-serif;'
        f'font-size:{hauteur * 0.185:.1f}px;color:#5a4a3e;line-height:1.5">'
        f'Veille des marchés publics, semi-publics et privés au Maroc</div>'
        f'</div>'
    )


def favicon_data_uri() -> str:
    """La marque encodée pour l'attribut href d'une balise <link>."""
    import urllib.parse
    # Sans mouvement: l'icône est recopiée dans l'en-tête de chaque page,
    # et une feuille de style y pèserait pour rien.
    return "data:image/svg+xml," + urllib.parse.quote(
        etoile(32, couleur=OR, fond=ENCRE, anime=False), safe="")


def _entete_email(couleur_texte: str, trait: str) -> str:
    """En-tête d'email, en typographie seule.

    Ni SVG ni image: Gmail supprime le premier et bloque la seconde par
    défaut. Reconstituer le globe en CSS demanderait des dégradés et des
    masques qu'aucun client de messagerie n'interprète. Le nom composé
    entre deux filets rend la même chose partout.
    """
    return (
        f'<div style="text-align:center;padding:2px 0 20px">'
        f'<div style="height:2px;width:52px;background:{trait};'
        f'margin:0 auto 14px"></div>'
        f'<div style="font-family:Georgia,Times New Roman,serif;font-weight:700;'
        f'font-size:21px;color:{couleur_texte};white-space:nowrap">Maroc</div>'
        f'<div style="font-family:Georgia,Times New Roman,serif;font-weight:700;'
        f'font-size:21px;color:{trait};white-space:nowrap">Entrepreneuriat</div>'
        f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;'
        f'letter-spacing:3.4px;color:{couleur_texte};opacity:.7;margin-top:8px;'
        f'white-space:nowrap">COUVERTURE NATIONALE</div>'
        f'<div style="height:2px;width:52px;background:{trait};'
        f'margin:14px auto 0"></div>'
        f'</div>'
    )


def logo_email(largeur: int = 210) -> str:
    """Bandeau des emails posés sur fond clair."""
    return _entete_email(ENCRE, OR)


def logo_email_sombre(largeur: int = 160) -> str:
    """Bandeau des emails posés sur fond encre."""
    return _entete_email(CREME, OR)

# ─── Les motifs du zellige ───────────────────────────────────────────────
#
# Le khatam — l'étoile à huit branches — est la figure de base du zellige
# marocain. Elle n'est pas « une étoile à huit pointes » dessinée au jugé:
# c'est le polygone étoilé {8/3}, celui qu'on obtient en reliant un sommet
# sur trois d'un octogone. Tracée avec deux rayons alternés, elle n'est
# juste que pour un rapport précis — cos(3π/8) / cos(2π/8) = 0,5412. Au-delà
# l'étoile s'arrondit en fleur, en deçà elle se hérisse en scie; dans les
# deux cas l'œil marocain la reconnaît comme fausse.


def _etoile_khatam(cx: float, cy: float, rayon: float, branches: int = 8,
                   saut: int = 3, rotation: float = 0.0) -> str:
    """Les sommets d'un khatam, prêts pour un `points="…"`.

    `saut` dit combien de sommets on enjambe: 3 pour l'étoile à huit
    branches du zellige, 2 pour une étoile plus ouverte.
    """
    creux = rayon * math.cos(saut * math.pi / branches) / math.cos(
        (saut - 1) * math.pi / branches)
    sommets = []
    for i in range(branches * 2):
        angle = math.pi * i / branches + rotation - math.pi / 2
        r = rayon if i % 2 == 0 else creux
        sommets.append(f"{cx + r * math.cos(angle):.2f},{cy + r * math.sin(angle):.2f}")
    return " ".join(sommets)


def _uri(svg: str) -> str:
    """Un SVG prêt pour `background-image`, sans guillemets.

    L'encodage ne laisse ni espace, ni parenthèse, ni apostrophe: l'adresse
    se passe donc de guillemets, et c'est ce qui la rend posable aussi bien
    dans une feuille de style que dans un attribut `style`, où des
    guillemets doubles auraient refermé l'attribut.
    """
    import urllib.parse
    return "url(data:image/svg+xml," + urllib.parse.quote(svg, safe="") + ")"


def trame_zellige(maille: int = 120, opacite: float = 0.13,
                  couleur: str = OR) -> str:
    """La trame de fond: un khatam à chaque nœud, relié par son lacis.

    Le motif se répète sur un carré. Pour qu'il se raccorde sans couture, le
    même khatam est posé au centre **et aux quatre coins**: un dessin qui ne
    toucherait pas ses bords laisserait une grille de vides, et c'est au
    raccord qu'on voit qu'un fond a été fabriqué.
    """
    m = maille
    r = m * 0.26
    etoiles = "".join(
        f'<polygon points="{_etoile_khatam(x, y, r)}"/>'
        for x, y in ((m / 2, m / 2), (0, 0), (m, 0), (0, m), (m, m)))
    # Le lacis: les diagonales qui relient les étoiles, comme les baguettes
    # de plâtre entre deux pièces de faïence.
    lacis = (f'<path d="M0 {m/2:.0f}H{m} M{m/2:.0f} 0V{m}"/>'
             f'<path d="M0 0L{m} {m} M{m} 0L0 {m}"/>')
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{m}' height='{m}'>"
            f"<g fill='none' stroke='{couleur}' stroke-opacity='{opacite:.2f}'"
            f" stroke-width='1'>{etoiles}"
            f"<g stroke-opacity='{opacite * 0.45:.2f}'>{lacis}</g></g></svg>")


def rosace(taille: int = 440, opacite: float = 0.16, couleur: str = OR) -> str:
    """La rosace d'angle: un khatam dans ses couronnes.

    Trois couronnes, pas plus: l'étoile, huit étoiles filles sur un cercle,
    et une bordure crénelée. Les rosaces des medersas en portent davantage,
    mais elles se lisent de près; posée derrière un titre, une rosace trop
    chargée devient une tache grise.
    """
    c = taille / 2
    R = taille * 0.46
    filles = "".join(
        f'<polygon points="{_etoile_khatam(c + R * 0.62 * math.cos(a), c + R * 0.62 * math.sin(a), R * 0.15)}"/>'
        for a in (math.pi * k / 4 for k in range(8)))
    creneaux = "".join(
        f'<line x1="{c + R * 0.90 * math.cos(a):.2f}" y1="{c + R * 0.90 * math.sin(a):.2f}"'
        f' x2="{c + R * 1.00 * math.cos(a):.2f}" y2="{c + R * 1.00 * math.sin(a):.2f}"/>'
        for a in (math.pi * k / 16 for k in range(32)))
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{taille}'"
            f" height='{taille}' viewBox='0 0 {taille} {taille}'>"
            f"<g fill='none' stroke='{couleur}' stroke-opacity='{opacite:.2f}'"
            f" stroke-width='1.2'>"
            f'<polygon points="{_etoile_khatam(c, c, R * 0.40)}"/>'
            # 0,20 et non 0,26: le creux de l'étoile extérieure tombe à
            # 0,40 × 0,5412 = 0,216 de R. Au-delà, les branches de l'étoile
            # intérieure ressortent entre celles de l'autre et les deux
            # figures se brouillent en une tache à seize pointes.
            f'<polygon points="{_etoile_khatam(c, c, R * 0.20, rotation=math.pi / 8)}"/>'
            f"<g stroke-opacity='{opacite * 0.8:.2f}'>{filles}</g>"
            f"<circle cx='{c}' cy='{c}' r='{R * 0.88:.2f}'/>"
            f"<g stroke-opacity='{opacite * 0.7:.2f}'>{creneaux}</g>"
            f"</g></svg>")


def fond_trame(maille: int = 120, opacite: float = 0.13) -> str:
    """La trame, prête pour une propriété `background`."""
    return _uri(trame_zellige(maille, opacite))


def fond_rosace(taille: int = 440, opacite: float = 0.16) -> str:
    """La rosace, prête pour une propriété `background`."""
    return _uri(rosace(taille, opacite))

# ─── Les icônes ──────────────────────────────────────────────────────────
#
# Un emoji n'est pas dessiné par nous: il l'est par le système de celui qui
# regarde. Le même 📡 est bleu et plat sur Windows, rond et dégradé sur
# Android, gris sur iOS. Aucune cohérence n'est possible tant qu'ils sont là,
# quoi qu'on fasse du reste de la page.
#
# Une seule grammaire pour tout le jeu, et c'est elle qui fait l'unité:
#   · une grille de 24, le dessin inscrit entre 2 et 22;
#   · un seul trait, de 1,6, bouts et angles arrondis;
#   · aucun remplissage, aucune couleur propre — `currentColor` prend celle
#     du texte qui l'entoure, si bien qu'une icône posée dans une carte
#     verte est verte sans qu'on ait rien à déclarer.
#
# Deux d'entre elles viennent de la marque elle-même: « favori » est le
# khatam du sceau, et « globe » reprend les méridiens du logo.

_TRACES = {
    # Veille, flux, signal
    "veille":      '<circle cx="5" cy="19" r="1.4"/><path d="M5 13.5a5.5 5.5 0 0 1 5.5 5.5"/>'
                   '<path d="M5 8.5a10.5 10.5 0 0 1 10.5 10.5"/>'
                   '<path d="M5 3.5a15.5 15.5 0 0 1 15.5 15.5"/>',
    "eclair":      '<path d="M13 2.5 4.5 14h6.5l-1 7.5L19 10h-6.5l.5-7.5Z"/>',
    # Classement, dossiers
    "etiquette":   '<path d="M3.5 11.4V4.6a1 1 0 0 1 1-1h6.8a1 1 0 0 1 .7.3l8.1 8.1a1 1 0 0 1 0 1.4'
                   'l-6.8 6.8a1 1 0 0 1-1.4 0L3.8 12.1a1 1 0 0 1-.3-.7Z"/>'
                   '<circle cx="7.6" cy="7.6" r="1.5"/>',
    "dossiers":    '<path d="M9 2.8h5.6L19 7.2V18a1.4 1.4 0 0 1-1.4 1.4H9A1.4 1.4 0 0 1 7.6 18V4.2'
                   'A1.4 1.4 0 0 1 9 2.8Z"/><path d="M14.4 2.8v4.6H19"/>'
                   '<path d="M4.6 6.6V19a2.4 2.4 0 0 0 2.4 2.4h8.4"/>',
    "carnet":      '<path d="M7.4 3h10.2a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H7.4A2.9 2.9 0 0 1 4.5 18.1'
                   'V5.9A2.9 2.9 0 0 1 7.4 3Z"/><path d="M4.5 7.5h3M4.5 12h3M4.5 16.5h3"/>',
    "presse":      '<path d="M9 4.4H7a2 2 0 0 0-2 2V19a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6.4a2 2 0 0 0-2-2h-2"/>'
                   '<rect x="9" y="2.6" width="6" height="3.6" rx="1.2"/>'
                   '<path d="M8.6 11.5h6.8M8.6 15.4h4.6"/>',
    "trombone":    '<path d="M18.9 11.4 11.5 18.8a5 5 0 0 1-7.1-7.1l8.5-8.5a3.4 3.4 0 0 1 4.8 4.8'
                   'l-8.1 8.1a1.8 1.8 0 0 1-2.5-2.5l7.2-7.2"/>',
    # Alertes et canaux
    "cloche":      '<path d="M18.2 9.4a6.2 6.2 0 1 0-12.4 0c0 5-2.1 6.2-2.1 6.2h16.6s-2.1-1.2-2.1-6.2"/>'
                   '<path d="M13.8 19.3a2.1 2.1 0 0 1-3.6 0"/>',
    "courriel":    '<rect x="3" y="5.2" width="18" height="13.6" rx="2"/>'
                   '<path d="M3.6 6.6 12 13l8.4-6.4"/>',
    "bulle":       '<path d="M20.4 11.6a8 8 0 0 1-11.8 7.1L3.6 20.4l1.7-5A8 8 0 1 1 20.4 11.6Z"/>',
    "telephone":   '<path d="M6.2 3.2h2.9l1.9 4.8-2.4 1.5a11.5 11.5 0 0 0 5.1 5.1l1.5-2.4 4.8 1.9v2.9'
                   'a2 2 0 0 1-2.2 2A16.4 16.4 0 0 1 4.2 5.4a2 2 0 0 1 2-2.2Z"/>',
    # Analyse
    "graphique":   '<path d="M4.6 18.6v-6.4M10.2 18.6V5.4M15.8 18.6v-8.8"/><path d="M3 21.2h18"/>',
    "trophee":     '<path d="M8 3.4h8v5.2a4 4 0 0 1-8 0Z"/>'
                   '<path d="M8 4.8H4.8v1.8a3.2 3.2 0 0 0 3.2 3.2"/>'
                   '<path d="M16 4.8h3.2v1.8a3.2 3.2 0 0 1-3.2 3.2"/>'
                   '<path d="M12 12.6v4.6M8.6 20.6h6.8"/>',
    # Un billet, pas un dollar: le symbole $ n'a rien à faire sur une
    # plateforme marocaine, et aucune icône ne peut porter le dirham sans
    # écrire un caractère — ce qu'un tracé ne fait pas.
    "argent":      '<rect x="2.6" y="6.4" width="18.8" height="11.2" rx="2"/>'
                   '<circle cx="12" cy="12" r="2.8"/>'
                   '<path d="M6.2 12h.01M17.8 12h.01"/>',
    "idee":        '<path d="M9.4 18.4h5.2M10.4 21.2h3.2"/>'
                   '<path d="M12 2.8a6.2 6.2 0 0 0-3.6 11.2c.6.5 1 1.3 1 2.1h5.2c0-.8.4-1.6 1-2.1'
                   'A6.2 6.2 0 0 0 12 2.8Z"/>',
    # Lieux, liens, recherche
    "loupe":       '<circle cx="10.8" cy="10.8" r="6.2"/><path d="M15.4 15.4 20.4 20.4"/>',
    "lieu":        '<path d="M12 21.2s7-6.4 7-11.2a7 7 0 1 0-14 0c0 4.8 7 11.2 7 11.2Z"/>'
                   '<circle cx="12" cy="9.8" r="2.7"/>',
    "lien":        '<path d="M10.2 13.1a4.2 4.2 0 0 0 6 .3l3-3a4.2 4.2 0 0 0-6-6l-1.8 1.8"/>'
                   '<path d="M13.8 10.9a4.2 4.2 0 0 0-6-.3l-3 3a4.2 4.2 0 0 0 6 6l1.8-1.8"/>',
    "globe":       '<circle cx="12" cy="12" r="8.6"/><ellipse cx="12" cy="12" rx="4" ry="8.6"/>'
                   '<path d="M3.5 12h17"/>',
    "photo":       '<rect x="3" y="6.4" width="18" height="13.6" rx="2"/>'
                   '<circle cx="12" cy="13.2" r="3.6"/><path d="M8.6 6.4 10 4.2h4l1.4 2.2"/>',
    # États et actions
    "coche":       '<circle cx="12" cy="12" r="8.6"/><path d="M8 12.3 10.9 15.2 16 9.4"/>',
    "croix":       '<circle cx="12" cy="12" r="8.6"/><path d="M9.2 9.2 14.8 14.8M14.8 9.2 9.2 14.8"/>',
    "attention":   '<path d="M12 3.6 2.6 20.4h18.8Z"/><path d="M12 9.8v4.6M12 17.6v.1"/>',
    "verrou":      '<rect x="4.2" y="10.2" width="15.6" height="10" rx="2.2"/>'
                   '<path d="M7.8 10.2V7.4a4.2 4.2 0 0 1 8.4 0v2.8"/>',
    "corbeille":   '<path d="M4.2 6.8h15.6"/>'
                   '<path d="M9.2 6.8V5a1.2 1.2 0 0 1 1.2-1.2h3.2A1.2 1.2 0 0 1 14.8 5v1.8"/>'
                   '<path d="M6.2 6.8 7.1 19a2 2 0 0 0 2 1.8h5.8a2 2 0 0 0 2-1.8l.9-12.2"/>'
                   '<path d="M10.2 10.6v6M13.8 10.6v6"/>',
    "imprimante":  '<path d="M7 9.4V3.8h10v5.6"/>'
                   '<rect x="4" y="9.4" width="16" height="7" rx="2"/>'
                   '<path d="M7 13.8h10v6.4H7Z"/>',
    "drapeau":     '<path d="M5.2 21.2V3.4"/><path d="M5.2 4.6h11l-2.2 3.6 2.2 3.6h-11"/>',
    "couronne":    '<path d="M4 18.8h16"/><path d="M4 15.6 2.9 6.8l5.3 4.1L12 4.4l3.8 6.5 5.3-4.1'
                   '-1.1 8.8Z"/>',
    # Un engrenage plutôt qu'une clé: huit dents calculées se tiennent,
    # là où une clé dessinée à la main penchait toujours d'un côté.
    "outils":      '<circle cx="12" cy="12" r="7.2"/><circle cx="12" cy="12" r="3"/>'
                   '<path d="M19.20 12.00L21.60 12.00"/><path d="M17.09 17.09L18.79 18.79"/><path d="M12.00 19.20L12.00 21.60"/><path d="M6.91 17.09L5.21 18.79"/><path d="M4.80 12.00L2.40 12.00"/><path d="M6.91 6.91L5.21 5.21"/><path d="M12.00 4.80L12.00 2.40"/><path d="M17.09 6.91L18.79 5.21"/>',
    "echange":     '<path d="M4 8.4h14l-3.4-3.4"/><path d="M20 15.6H6l3.4 3.4"/>',
    # Le rail en demandait trois de plus.
    "personne":    '<circle cx="12" cy="8" r="3.8"/>'
                   '<path d="M4.6 20.4a7.4 7.4 0 0 1 14.8 0"/>',
    "immeuble":    '<path d="M4.2 20.6V5.4a1 1 0 0 1 1-1h7.6a1 1 0 0 1 1 1v15.2"/>'
                   '<path d="M13.8 10.6h5a1 1 0 0 1 1 1v9"/>'
                   '<path d="M2.6 20.6h18.8"/>'
                   '<path d="M7 8.4h4M7 12.4h4M7 16.4h4M17 14.4h.01M17 17.6h.01"/>',
    "cible":       '<circle cx="12" cy="12" r="8.4"/><circle cx="12" cy="12" r="4.4"/>'
                   '<circle cx="12" cy="12" r="1"/>',
}


def icone(nom: str, taille: int = 22, trait: float = 1.6) -> str:
    """Une icône du jeu, dans la couleur du texte qui l'entoure.

    `currentColor` plutôt qu'une teinte écrite: posée dans une carte verte
    elle devient verte, dans un bouton blanc elle devient blanche, et aucune
    page n'a à redéclarer la palette.

    Un nom inconnu rend un carré vide plutôt que rien: on voit qu'il manque
    une icône au lieu de chercher pourquoi la ligne a l'air de travers.
    """
    if nom == "favori":                       # le khatam du sceau
        trace = f'<polygon points="{_etoile_khatam(12, 12, 9.2)}"/>'
    else:
        trace = _TRACES.get(nom, '<rect x="4" y="4" width="16" height="16" rx="2"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{taille}" height="{taille}"'
            f' viewBox="0 0 24 24" fill="none" stroke="currentColor"'
            f' stroke-width="{trait}" stroke-linecap="round" stroke-linejoin="round"'
            f' aria-hidden="true" focusable="false"'
            f' style="flex:none;display:inline-block;vertical-align:-.18em">{trace}</svg>')


def icones_connues() -> tuple:
    """Les noms du jeu, pour qu'un test puisse les vérifier tous."""
    return tuple(sorted(_TRACES)) + ("favori",)

def frise(largeur: int = 120, hauteur: int = 30, opacite: float = 0.30,
          couleur: str = OR) -> str:
    """Le bandeau de faïence qui ferme un mur, en bas d'une section sombre.

    Même figure que la trame — le khatam — mais alignée sur une ligne, entre
    deux filets, comme la bande de zellige qui court au bas d'un mur de
    riad. Elle existe pour une raison précise: la couverture est sombre et
    texturée, le corps de la page est clair et lisse, et sans elle les deux
    se touchent sans transition, comme deux sites cousus l'un à l'autre.

    Le motif est posé à gauche, au centre et à droite: sans les deux
    moitiés des bords, le raccord laisse un trou tous les 120 px.
    """
    r = hauteur * 0.34
    y = hauteur / 2
    etoiles = "".join(
        f'<polygon points="{_etoile_khatam(x, y, r)}"/>'
        for x in (0, largeur / 2, largeur))
    losanges = "".join(
        f'<polygon points="{x},{y - r * 0.44:.2f} {x + r * 0.44:.2f},{y} '
        f'{x},{y + r * 0.44:.2f} {x - r * 0.44:.2f},{y}"/>'
        for x in (largeur / 4, 3 * largeur / 4))
    filets = (f'<path d="M0 1.2H{largeur}M0 {hauteur - 1.2:.1f}H{largeur}"/>')
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{largeur}'"
            f" height='{hauteur}'><g fill='none' stroke='{couleur}'"
            f" stroke-opacity='{opacite:.2f}' stroke-width='1'>"
            f"{etoiles}{losanges}"
            f"<g stroke-opacity='{opacite * 0.7:.2f}'>{filets}</g></g></svg>")


def fond_frise(largeur: int = 120, hauteur: int = 30, opacite: float = 0.30) -> str:
    """La frise, prête pour une propriété `background`."""
    return _uri(frise(largeur, hauteur, opacite))
