"""Diagnostic : d'où vient le trou des équipes proposées ?

Pour chaque soir, la meilleure équipe pour 240 (celle du verdict « équipes ») est
découpée joueur par joueur :
  trou = (réel - projection finale) + (projection finale - projection au moment du choix)
La projection finale est la dernière faite avant le match du joueur (fichier du
soir où il joue) ; la projection au moment du choix est la moyenne de l'équipe
enregistrée quand elle se fige (mu).

Puis on compare, à niveau d'étoiles égal, les joueurs que l'optimiseur met dans
ses équipes aux autres joueurs du même soir : s'ils ratent plus leur projection,
c'est que l'optimiseur attrape les projections gonflées.

Usage : python src/diag_equipes.py
"""

import json
import math
import statistics as st
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
J = ROOT / "journal"


def load():
    bil, jour = {}, {}
    for f in sorted(J.glob("bilan-*.json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        bil[b["night"]] = {r["slug"]: r for r in b["joueurs"]}
    for f in sorted(J.glob("2026-*.json")):
        jour[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return bil, jour


def nxt(n):
    return (date.fromisoformat(n) + timedelta(days=1)).isoformat()


def slot(bil, jour, night, slug):
    """(soir où il joue, fiche du journal, ligne du bilan) ou None si pas de bilan."""
    for n in (night, nxt(n := night)):
        if slug in bil.get(n, {}):
            return n, jour.get(n, {}).get("players", {}).get(slug, {}), bil[n][slug]
    return None


def mz(xs, sds=None):
    """Moyenne et z (écart-type empirique, ou somme des variances si sds)."""
    if len(xs) < 2:
        return (xs[0] if xs else float("nan")), None
    m = st.mean(xs)
    if sds:
        se = math.sqrt(sum(s * s for s in sds)) / len(xs)
    else:
        se = st.stdev(xs) / math.sqrt(len(xs))
    return m, (m / se if se else None)


def res(p, r):
    """Réel moins projection pondérée par la chance de jouer, et sa variance."""
    pct, e, sd = p.get("pct", 1), p.get("exp", 0), p.get("sd", 0)
    return (r.get("actual") or 0.0) - e * pct, pct * sd * sd + pct * (1 - pct) * e * e


def main():
    bil, jour = load()
    nights = [n for n in sorted(bil) if (jour.get(n, {}).get("teams") or {}).get("list")]

    print("## 1. Meilleure équipe de chaque soir : trou joueur par joueur\n")
    rows, per_player = [], defaultdict(list)
    for n in nights:
        t = max(jour[n]["teams"]["list"], key=lambda t: t["p"]["240"])
        parts = [slot(bil, jour, n, s) for s in t["slugs"]]
        if None in parts:
            print(f"{n} : incomplet (bilan manquant pour {', '.join(nm for nm, x in zip(t['names'], parts) if x is None)})")
            continue
        fin = sum(p.get("exp", 0) * p.get("pct", 1) for _, p, _ in parts)
        act = sum(r.get("actual") or 0.0 for _, _, r in parts)
        later = sum(pn != n for pn, _, _ in parts)
        rows.append({"n": n, "mu": t["mu"], "fin": fin, "act": act, "later": later})
        det = []
        for (pn, p, r), nm in zip(parts, t["names"]):
            d, _ = res(p, r)
            per_player[nm].append(d)
            det.append(f"{nm.split()[-1]} {d:+.0f}{'*' if pn != n else ''}")
        print(f"{n} : réel {act:5.0f}, projection finale {fin:5.0f}, au choix {t['mu']:5.0f} | "
              f"trou {act - t['mu']:+4.0f} = joueurs {act - fin:+4.0f} + glissement {fin - t['mu']:+4.0f} | "
              + ", ".join(det))
    print("\n(* = joue le lendemain du soir où l'équipe se fige)")
    for lab, sel in (("tous les soirs", rows), ("avant le 18/11", [r for r in rows if r["n"] < "2026-11-18"]),
                     ("depuis le 18/11", [r for r in rows if r["n"] >= "2026-11-18"])):
        if sel:
            print(f"- {lab} ({len(sel)} soirs) : trou {st.mean(r['act'] - r['mu'] for r in sel):+.1f}, dont joueurs "
                  f"{st.mean(r['act'] - r['fin'] for r in sel):+.1f} et glissement "
                  f"{st.mean(r['fin'] - r['mu'] for r in sel):+.1f}")

    print("\nJoueurs les plus souvent dans la meilleure équipe (réel - projection finale) :")
    for nm, ds in sorted(per_player.items(), key=lambda kv: sum(kv[1])):
        if len(ds) >= 2:
            print(f"  {nm:24} {len(ds)} fois, {st.mean(ds):+5.1f} en moyenne, total {sum(ds):+5.0f}")

    print("\n## 2. Sélection : joueurs choisis contre joueurs du même niveau d'étoiles\n")
    # Pour chaque soir, joueurs présents dans au moins une des équipes listées (jusqu'à 40),
    # comparés aux autres joueurs du même soir et du même niveau d'étoiles.
    groups = defaultdict(lambda: {"sel": [], "oth": []})
    feats = []
    for n in nights:
        chosen = {s for t in jour[n]["teams"]["list"] for s in t["slugs"]}
        pool = {}
        for night in (n, nxt(n)):
            for s, p in jour.get(night, {}).get("players", {}).items():
                if s in bil.get(night, {}) and p.get("pct", 0) > 0 and s not in pool:
                    pool[s] = (night, p, bil[night][s])
        for s, (pn, p, r) in pool.items():
            d, v = res(p, r)
            key = "sel" if s in chosen else "oth"
            groups[p.get("stars")][key].append(d)
            feats.append({"sel": s in chosen, "d": d, "v": v, "props": p.get("usesProps"), "later": pn != n,
                          "exp": p.get("exp", 0), "stars": p.get("stars"), "n": n,
                          "ratio": p["exp"] / p["hist"] if p.get("hist") else None})
    print(f"{'étoiles':>7} {'choisis':>18} {'autres':>18}")
    for s in sorted(k for k in groups if k is not None):
        g = groups[s]
        f = lambda xs: f"{st.mean(xs):+5.1f} ({len(xs):3d})" if xs else "-"
        print(f"{s:7g} {f(g['sel']):>18} {f(g['oth']):>18}")
    sel = [x for x in feats if x["sel"]]
    oth = [x for x in feats if not x["sel"]]
    for lab, sub in (("choisis", sel), ("autres", oth)):
        m, z = mz([x["d"] for x in sub], [math.sqrt(x["v"]) for x in sub])
        print(f"- {lab} : {m:+.2f} pt par joueur, z = {z:.2f} ({len(sub)} cas joueur-soir)")

    print("\nChez les choisis, par type de projection :")
    cuts = [
        ("avec props", lambda x: x["props"]),
        ("sans props (historique)", lambda x: not x["props"]),
        ("sans props, projeté 25 ou plus", lambda x: not x["props"] and x["exp"] >= 25),
        ("joue le soir où l'équipe se fige", lambda x: not x["later"]),
        ("joue le lendemain", lambda x: x["later"]),
        ("props 20 % ou plus au-dessus de l'historique", lambda x: x["props"] and (x["ratio"] or 0) >= 1.2),
        ("projection 45 ou plus", lambda x: x["exp"] >= 45),
        ("depuis le 18/11", lambda x: x["n"] >= "2026-11-18"),
    ]
    for lab, f in cuts:
        a = [x for x in sel if f(x)]
        b = [x for x in oth if f(x)]
        if len(a) > 2:
            ma, za = mz([x["d"] for x in a], [math.sqrt(x["v"]) for x in a])
            mb, zb = mz([x["d"] for x in b], [math.sqrt(x["v"]) for x in b]) if len(b) > 2 else (float("nan"), None)
            print(f"  {lab:45} choisis {ma:+5.1f} (z {za:+.1f}, {len(a):3d})   autres {mb:+5.1f} "
                  f"(z {zb if zb is None else round(zb, 1)}, {len(b):3d})")


if __name__ == "__main__":
    main()
