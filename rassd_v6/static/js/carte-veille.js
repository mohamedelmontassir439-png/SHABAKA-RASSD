/* La veille en direct, dessinée: le Maroc en points, un faisceau de radar qui
   le balaie, et chaque région qui s'allume à son passage avec le nombre réel
   de ses marchés ouverts. Les chiffres viennent du serveur (data-regions);
   rien n'est inventé ici, seul le rythme l'est.

   Une toile, aucune dépendance. Le dessin s'arrête quand la section sort de
   l'écran ou que l'onglet est caché; « mouvement réduit » donne une image
   fixe. */
(function () {
  "use strict";
  var boite = document.querySelector(".carte-veille");
  if (!boite) return;
  var toile = boite.querySelector("canvas");
  var ctx = toile.getContext && toile.getContext("2d");
  if (!ctx) return;

  var regions = [];
  try { regions = JSON.parse(boite.getAttribute("data-regions") || "[]"); } catch (e) { regions = []; }
  var modele = boite.getAttribute("data-libelle") || "{n}";
  var rtl = document.documentElement.getAttribute("dir") === "rtl";
  var reduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Le contour du Royaume, provinces du Sud comprises (longitude, latitude).
  var CONTOUR = [
    [-5.92, 35.79], [-5.40, 35.92], [-5.28, 35.69], [-4.85, 35.36], [-4.40, 35.20], [-3.90, 35.23],
    [-3.35, 35.20], [-2.93, 35.28], [-2.60, 35.10], [-2.20, 35.09], [-1.79, 34.75], [-1.70, 34.40],
    [-1.79, 34.00], [-1.68, 33.25], [-1.42, 32.75], [-1.20, 32.40], [-1.30, 32.10], [-2.50, 32.10],
    [-3.00, 31.80], [-3.70, 31.65], [-3.80, 31.20], [-3.65, 30.85], [-4.50, 30.55], [-5.20, 30.00],
    [-5.60, 29.80], [-6.60, 29.60], [-7.60, 29.40], [-8.20, 29.00], [-8.67, 28.70], [-8.67, 27.67],
    [-8.67, 26.00], [-12.00, 26.00], [-12.00, 23.45], [-13.10, 23.00], [-13.10, 21.33], [-16.95, 21.33],
    [-17.05, 20.85], [-16.90, 21.60], [-16.50, 22.30], [-16.20, 22.95], [-15.95, 23.70], [-15.40, 24.30],
    [-14.85, 25.10], [-14.45, 26.10], [-13.55, 26.95], [-13.10, 27.65], [-12.90, 27.95], [-11.70, 28.20],
    [-10.95, 28.70], [-10.20, 29.30], [-9.65, 30.15], [-9.65, 30.45], [-9.85, 30.90], [-9.80, 31.45],
    [-9.30, 32.30], [-8.95, 32.80], [-8.50, 33.25], [-7.60, 33.62], [-6.85, 34.05], [-6.60, 34.45],
    [-6.30, 35.00], [-6.10, 35.50], [-5.92, 35.79]
  ];
  var LON0 = -17.4, LON1 = -0.9, LAT0 = 20.4, LAT1 = 36.3;
  var KX = Math.cos(29 * Math.PI / 180);
  var CENTRE = [-8.6, 29.4];          // le pied du radar, au cœur du territoire
  var PERIODE = 7000;                 // un tour de faisceau, en millisecondes
  var TRAINE = 1.05;                  // largeur de la traîne, en radians

  var ORANGE = [201, 152, 74], CLAIR = [232, 210, 168], CREME = [246, 243, 234];
  var police = (getComputedStyle(boite).fontFamily || "sans-serif");

  var L = 0, H = 0, dpr = 1, echelle = 1, ox = 0, oy = 0, pas = 7;
  var points = [], centre = [0, 0], rayon = 0, lieux = [];
  var allumages = [], fils = [], dernierAngle = 0, dernier = null;

  function proj(lon, lat) {
    return [ox + (lon - LON0) * KX * echelle, oy + (LAT1 - lat) * echelle];
  }
  function inverse(x, y) {
    return [(x - ox) / (KX * echelle) + LON0, LAT1 - (y - oy) / echelle];
  }
  function dedans(lon, lat) {
    var c = false;
    for (var i = 0, j = CONTOUR.length - 1; i < CONTOUR.length; j = i++) {
      var a = CONTOUR[i], b = CONTOUR[j];
      if ((a[1] > lat) !== (b[1] > lat) &&
          lon < (b[0] - a[0]) * (lat - a[1]) / (b[1] - a[1]) + a[0]) c = !c;
    }
    return c;
  }
  function angle(x, y) {
    var a = Math.atan2(y - centre[1], x - centre[0]);
    return a < 0 ? a + 2 * Math.PI : a;
  }

  function mesurer() {
    var r = boite.getBoundingClientRect();
    L = Math.max(200, r.width); H = Math.max(200, r.height);
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    toile.width = Math.round(L * dpr); toile.height = Math.round(H * dpr);
    toile.style.width = L + "px"; toile.style.height = H + "px";
    var marge = L * 0.06;
    echelle = Math.min((L - 2 * marge) / ((LON1 - LON0) * KX), (H - 2 * marge) / (LAT1 - LAT0));
    ox = (L - (LON1 - LON0) * KX * echelle) / 2;
    oy = (H - (LAT1 - LAT0) * echelle) / 2;
    pas = Math.max(4.5, L / 74);
    points = [];
    for (var y = pas / 2; y < H; y += pas) {
      for (var x = pas / 2; x < L; x += pas) {
        var g = inverse(x, y);
        if (dedans(g[0], g[1])) points.push({ x: x, y: y, a: 0, p: Math.random() * 6.28 });
      }
    }
    centre = proj(CENTRE[0], CENTRE[1]);
    rayon = Math.hypot(L, H) * 0.62;
    for (var i = 0; i < points.length; i++) points[i].a = angle(points[i].x, points[i].y);
    var max = 1;
    regions.forEach(function (r) { max = Math.max(max, r.n || 0); });
    lieux = regions.map(function (r) {
      var p = proj(r.lon, r.lat);
      return { x: p[0], y: p[1], a: angle(p[0], p[1]), nom: r.nom, n: r.n || 0,
               poids: Math.sqrt((r.n || 0) / max) };
    });
  }

  function traceContour() {
    ctx.beginPath();
    CONTOUR.forEach(function (c, i) { var q = proj(c[0], c[1]); i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]); });
    ctx.closePath();
  }
  function rgba(c, a) { return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + a.toFixed(3) + ")"; }
  function ecart(faisceau, a) {     // combien de radians le faisceau a dépassé « a »
    var d = faisceau - a;
    d = d % (2 * Math.PI);
    return d < 0 ? d + 2 * Math.PI : d;
  }

  function puce(x, y, titre, ligne, alpha, prises) {
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.direction = rtl ? "rtl" : "ltr";
    var t1 = Math.round(Math.max(11, L * 0.03)), t2 = Math.round(Math.max(10, L * 0.026));
    ctx.font = "700 " + t1 + "px " + police;
    var w1 = ctx.measureText(titre).width;
    ctx.font = "500 " + t2 + "px " + police;
    var w2 = ctx.measureText(ligne).width;
    var pad = 9, l = Math.max(w1, w2) + pad * 2 + 12, h = t1 + t2 + pad * 2 + 4;
    var gauche = x > L * 0.58;
    var bx = gauche ? x - l - 16 : x + 16, by = y - h / 2;
    bx = Math.max(4, Math.min(L - l - 4, bx)); by = Math.max(4, Math.min(H - h - 4, by));
    // Deux puces ne se recouvrent pas: la suivante descend sous la première.
    for (var k = 0; k < prises.length; k++) {
      var o = prises[k];
      if (bx < o[0] + o[2] && bx + l > o[0] && by < o[1] + o[3] + 6 && by + h + 6 > o[1]) {
        by = o[1] + o[3] + 6;
        if (by + h > H - 4) by = o[1] - h - 6;
      }
    }
    prises.push([bx, by, l, h]);
    // Le fil qui relie la puce à son point.
    ctx.strokeStyle = rgba(CLAIR, 0.55); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(gauche ? bx + l : bx, by + h / 2); ctx.stroke();
    // Le cartouche: sombre, translucide, liseré orange.
    var r = 8;
    ctx.beginPath();
    ctx.moveTo(bx + r, by); ctx.arcTo(bx + l, by, bx + l, by + h, r); ctx.arcTo(bx + l, by + h, bx, by + h, r);
    ctx.arcTo(bx, by + h, bx, by, r); ctx.arcTo(bx, by, bx + l, by, r); ctx.closePath();
    ctx.fillStyle = "rgba(24,14,9,.78)"; ctx.fill();
    ctx.strokeStyle = rgba(ORANGE, 0.7); ctx.stroke();
    ctx.fillStyle = rgba(ORANGE, 1);
    var px = rtl ? bx + l - pad - 3 : bx + pad + 3;
    ctx.beginPath(); ctx.arc(px, by + pad + t1 / 2 + 1, 3, 0, 6.29); ctx.fill();
    ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillStyle = rgba(CREME, 1);
    ctx.font = "700 " + t1 + "px " + police;
    ctx.fillText(titre, rtl ? bx + l - pad - 12 - w1 : bx + pad + 12, by + pad);
    ctx.fillStyle = rgba(CLAIR, 0.9);
    ctx.font = "500 " + t2 + "px " + police;
    ctx.fillText(ligne, rtl ? bx + l - pad - 12 - w2 : bx + pad + 12, by + pad + t1 + 4);
    ctx.restore();
  }

  function dessiner(t) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, L, H);
    var faisceau = reduit ? -1 : ((t % PERIODE) / PERIODE) * 2 * Math.PI;

    // Un voile sombre sous le territoire, pour qu'il se détache de la photo.
    traceContour();
    ctx.fillStyle = "rgba(18,10,6,.42)"; ctx.fill();

    // Le radar ne balaie que le territoire: ses cercles et sa traîne sont
    // découpés au contour, sans quoi le bord de la toile se voyait en arêtes droites.
    ctx.save();
    traceContour(); ctx.clip();
    ctx.lineWidth = 1;
    for (var k = 1; k <= 4; k++) {
      ctx.strokeStyle = rgba(CLAIR, 0.07);
      ctx.setLineDash([2, 6]);
      ctx.beginPath(); ctx.arc(centre[0], centre[1], rayon * k / 5.2, 0, 6.29); ctx.stroke();
    }
    ctx.setLineDash([]);

    // La traîne du faisceau: une suite de secteurs de plus en plus pâles.
    if (!reduit) {
      var tranches = 28;
      for (var s = 0; s < tranches; s++) {
        var a0 = faisceau - TRAINE * (s + 1) / tranches, a1 = faisceau - TRAINE * s / tranches;
        ctx.fillStyle = rgba(ORANGE, 0.18 * Math.pow(1 - s / tranches, 1.8));
        ctx.beginPath(); ctx.moveTo(centre[0], centre[1]);
        ctx.arc(centre[0], centre[1], rayon, a0, a1); ctx.closePath(); ctx.fill();
      }
      var g = ctx.createLinearGradient(centre[0], centre[1],
        centre[0] + Math.cos(faisceau) * rayon, centre[1] + Math.sin(faisceau) * rayon);
      g.addColorStop(0, rgba(CLAIR, 0.9)); g.addColorStop(1, rgba(ORANGE, 0));
      ctx.strokeStyle = g; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.moveTo(centre[0], centre[1]);
      ctx.lineTo(centre[0] + Math.cos(faisceau) * rayon, centre[1] + Math.sin(faisceau) * rayon); ctx.stroke();
    }
    ctx.restore();

    // Le trait de côte, puis les points que le faisceau peint en passant.
    traceContour();
    ctx.strokeStyle = rgba(CLAIR, 0.55); ctx.lineWidth = 1.2; ctx.lineJoin = "round"; ctx.stroke();
    var taille = Math.max(1.4, pas * 0.3);
    for (var i = 0; i < points.length; i++) {
      var p = points[i];
      var lueur = reduit ? 0.35 : Math.max(0, 1 - ecart(faisceau, p.a) / TRAINE);
      var scint = 0.5 + 0.5 * Math.sin(t / 900 + p.p);
      var alpha = 0.32 + 0.14 * scint + 0.54 * lueur;
      ctx.fillStyle = lueur > 0.05 ? rgba([
        Math.round(CREME[0] + (ORANGE[0] - CREME[0]) * (1 - lueur) * 0.3),
        Math.round(CREME[1] + (ORANGE[1] - CREME[1]) * (1 - lueur * 0.5)),
        Math.round(CREME[2] + (ORANGE[2] - CREME[2]) * (1 - lueur * 0.5))], alpha) : rgba(CREME, alpha);
      ctx.fillRect(p.x - taille / 2, p.y - taille / 2, taille + lueur * 0.8, taille + lueur * 0.8);
    }

    // Le faisceau atteint une région: elle s'allume, et un fil la relie à la précédente.
    if (!reduit) {
      lieux.forEach(function (l) {
        var avant = ecart(dernierAngle, l.a), apres = ecart(faisceau, l.a);
        if (apres < avant && apres < 0.5) {
          allumages.push({ l: l, t: t });
          if (dernier && dernier !== l) fils.push({ de: dernier, a: l, t: t });
          dernier = l;
        }
      });
      dernierAngle = faisceau;
    }
    allumages = allumages.filter(function (x) { return t - x.t < 3200; });
    fils = fils.filter(function (x) { return t - x.t < 1800; });

    fils.forEach(function (f) {
      var u = (t - f.t) / 1800, mx = (f.de.x + f.a.x) / 2, my = Math.min(f.de.y, f.a.y) - L * 0.12;
      ctx.strokeStyle = rgba(ORANGE, 0.45 * (1 - u)); ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(f.de.x, f.de.y); ctx.quadraticCurveTo(mx, my, f.a.x, f.a.y); ctx.stroke();
      var v = Math.min(1, u * 1.6), q = 1 - v;   // la lumière qui court le long du fil
      var lx = q * q * f.de.x + 2 * q * v * mx + v * v * f.a.x, ly = q * q * f.de.y + 2 * q * v * my + v * v * f.a.y;
      ctx.fillStyle = rgba(CREME, 0.9 * (1 - u));
      ctx.beginPath(); ctx.arc(lx, ly, 2.4, 0, 6.29); ctx.fill();
    });

    // Les capitales régionales: un point toujours là, plus gros où il y a plus de marchés.
    lieux.forEach(function (l) {
      var r = 2.2 + l.poids * 3.2;
      ctx.fillStyle = rgba(ORANGE, 0.95);
      ctx.beginPath(); ctx.arc(l.x, l.y, r, 0, 6.29); ctx.fill();
      ctx.strokeStyle = rgba(CREME, 0.5); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(l.x, l.y, r + 2.5, 0, 6.29); ctx.stroke();
    });

    // Les ondes et les puces des régions qui viennent de s'allumer.
    var prises = [];
    allumages.forEach(function (x, i) {
      var u = (t - x.t) / 3200;
      for (var k = 0; k < 2; k++) {
        var v = Math.min(1, u * 1.8 - k * 0.25);
        if (v <= 0) continue;
        ctx.strokeStyle = rgba(ORANGE, 0.8 * (1 - v)); ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(x.l.x, x.l.y, 4 + v * L * 0.07, 0, 6.29); ctx.stroke();
      }
      var alpha = u < 0.1 ? u / 0.1 : (u > 0.8 ? (1 - u) / 0.2 : 1);
      if (i >= allumages.length - 2) puce(x.l.x, x.l.y, x.l.nom, modele.replace("{n}", x.l.n), alpha, prises);
    });

    // Le pied du radar.
    ctx.fillStyle = rgba(CREME, 0.95);
    ctx.beginPath(); ctx.arc(centre[0], centre[1], 2.6, 0, 6.29); ctx.fill();
  }

  var actif = true, visible = true, demande = 0;
  function boucle(t) {
    demande = 0;
    dessiner(t);
    if (!reduit && actif && visible) demande = requestAnimationFrame(boucle);
  }
  function relancer() {
    if (!demande && !reduit && actif && visible) demande = requestAnimationFrame(boucle);
  }

  mesurer();
  dessiner(performance.now());
  relancer();

  var attente = 0;
  window.addEventListener("resize", function () {
    clearTimeout(attente);
    attente = setTimeout(function () { mesurer(); dessiner(performance.now()); }, 120);
  });
  document.addEventListener("visibilitychange", function () {
    actif = !document.hidden; relancer();
  });
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (e) { visible = e[0].isIntersecting; relancer(); }).observe(boite);
  }
})();
