# -*- coding: utf-8 -*-
"""Identité visuelle: un seul endroit d'où sort la marque.

Le signe est un globe de méridiens, posé sur un arc, dans un médaillon
cerclé. Il dit ce que fait la plateforme — une couverture nationale, une
veille qui embrasse tout le territoire — là où l'étoile précédente disait
l'orientation. Le sceau à six branches sous le nom est le khatam, motif du
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


def _globe(rayon: float = 30.0, centre: float = 50.0, cle: str = "g") -> str:
    """La sphère: dégradé, méridiens, parallèles, reflet, liseré.

    Les identifiants sont suffixés pour qu'on puisse poser deux marques sur
    la même page sans que leurs dégradés se confondent.
    """
    c, r = centre, rayon
    meridiens = "".join(
        f'<ellipse cx="{c}" cy="{c}" rx="{r * f:.2f}" ry="{r}" '
        f'fill="none" stroke="{OR}" stroke-width="{0.9 if f else 1.1}" '
        f'opacity="{0.52 + 0.30 * (1 - f):.2f}"/>'
        for f in (0.80, 0.52, 0.22))
    paralleles = "".join(
        f'<ellipse cx="{c}" cy="{c + r * d:.2f}" rx="{r * math.sqrt(1 - d * d):.2f}" '
        f'ry="{r * 0.17:.2f}" fill="none" stroke="{OR}" stroke-width="0.8" '
        f'opacity="{0.46 - 0.10 * abs(d):.2f}"/>'
        for d in (-0.55, -0.22, 0.14, 0.48))
    return (
        f'<defs>'
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
        # Le point de lumière, en haut à droite: c'est lui qui fait la sphère.
        f'<circle cx="{c + r * 0.30:.2f}" cy="{c - r * 0.74:.2f}" r="{r * 0.055:.2f}" '
        f'fill="#fff" opacity=".9"/>'
    )


def _socle(centre: float = 50.0, rayon: float = 30.0) -> str:
    """L'arc sur lequel le globe repose."""
    c, r = centre, rayon
    y = c + r * 1.16
    return (f'<path d="M {c - r * 1.12:.1f} {y:.1f} Q {c} {y + r * 0.26:.1f} '
            f'{c + r * 1.12:.1f} {y:.1f}" fill="none" stroke="{OR}" '
            f'stroke-width="1.6" stroke-linecap="round" opacity=".92"/>')


def sceau(taille: int = 14, couleur: str = OR) -> str:
    """Le khatam à six branches: deux triangles équilatéraux superposés.

    Motif du zellige et de l'ancien pavillon chérifien. Tracé, pas approché:
    deux triangles décalés d'un sixième de tour, de même rayon.
    """
    pts = []
    for depart in (0, 60):
        t = [f"{50 + 42 * math.cos(math.radians(depart + i * 120 - 90)):.1f},"
             f"{50 + 42 * math.sin(math.radians(depart + i * 120 - 90)):.1f}"
             for i in range(3)]
        pts.append(f'<polygon points="{" ".join(t)}" fill="none" '
                   f'stroke="{couleur}" stroke-width="7"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{taille}" '
            f'height="{taille}" viewBox="0 0 100 100" role="presentation" '
            f'style="flex:none;vertical-align:middle">{"".join(pts)}</svg>')


def etoile(taille: int = 40, couleur: str = OR, fond: str = "none") -> str:
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
             f'stroke-width="3"/>') if petit else _globe(30, 50, cle) + _socle()
    return (
        # flex:none et la largeur minimale protègent la marque: dans une barre
        # chargée, « svg { max-width: 100% } » la laissait se réduire à rien.
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{taille}" '
        f'height="{taille}" viewBox="0 0 100 100" role="img" '
        f'style="flex:none;min-width:{taille}px" '
        f'aria-label="Maroc Entrepreneuriat">{fond_rond}{corps}</svg>'
    )


def medaillon(taille: int = 160, fond: str = BRUN) -> str:
    """Le médaillon complet: globe, nom, sceau, mention — sur fond sombre.

    Mise en page calculée, pas ajustée à l'œil: le globe est centré à
    (150, 105) avec un rayon de 45, si bien que son arc tombe à y=157 — sous
    la sphère et au-dessus du nom, qu'il traversait auparavant. À 26 px,
    « Entrepreneuriat » mesure environ 218 px; la corde du cercle à cette
    hauteur en fait 240. Il tient, de justesse, et c'est pourquoi le corps
    ne doit pas remonter.

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
  <polygon points="50,8 86,71 14,71" fill="none" stroke="{OR}" stroke-width="7"/>
  <polygon points="50,92 14,29 86,29" fill="none" stroke="{OR}" stroke-width="7"/>
</g>
<text x="150" y="271" text-anchor="middle" fill="{CREME}" letter-spacing="4"
      font-family="Arial,Helvetica,sans-serif" font-weight="600" font-size="12"
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
    return "data:image/svg+xml," + urllib.parse.quote(
        etoile(32, couleur=OR, fond=ENCRE), safe="")


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
