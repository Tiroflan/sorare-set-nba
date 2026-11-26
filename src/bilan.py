"""Bilan d'un soir : projections du journal contre les vrais scores.

Compare, pour chaque joueur du journal, la dernière projection faite avant son
match au score réellement marqué (recalculé depuis sa feuille de match, bonus
de carte compris). Écrit journal/bilan-<soir>.json et affiche le résumé.

Usage : python src/bilan.py [AAAA-MM-JJ]   (par défaut : le soir US qui vient de finir)
"""

import json
import math
import sys
from datetime import datetime

import espn
import history
from journal import DIR, _tip
from model import sorare_score

STATS = {"pts": "points", "reb": "rebounds", "ast": "assists", "tpm": "threePointsMade",
         "stl": "steals", "blk": "blocks", "tov": "turnovers"}
LABELS = {"pts": "Points", "reb": "Rebonds", "ast": "Passes", "tpm": "Paniers à 3",
          "stl": "Interceptions", "blk": "Contres", "tov": "Balles perdues"}


def find_game(games, tip):
    for g in games:
        d = datetime.fromisoformat(g["basketballGame"]["date"].replace("Z", "+00:00"))
        if abs((d - tip).total_seconds()) < 6 * 3600:
            return g
    return None


def stats(errs):
    n = len(errs)
    if not n:
        return None
    return {"n": n, "biais": sum(errs) / n, "mae": sum(map(abs, errs)) / n,
            "rmse": math.sqrt(sum(e * e for e in errs) / n)}


def games_check(night, games):
    """Nos estimations de la veille contre les cotes finales et le résultat réel."""
    if not games:
        return None
    from datetime import date as _d, timedelta as _td
    import team_ratings
    res = {f"{g['away']}@{g['home']}": g for g in team_ratings.results(_d.fromisoformat(night) + _td(days=1))
           if g["night"] == night}
    rows = []
    for key, g in games.items():
        r = res.get(key)
        if not r:
            continue
        rows.append({"match": key, "est": g.get("est"), "odds": g.get("odds"),
                     "real_spread": r["away_pts"] - r["home_pts"], "real_total": r["home_pts"] + r["away_pts"]})
    mae = lambda xs: round(sum(map(abs, xs)) / len(xs), 1) if xs else None
    both = [x for x in rows if x["est"] and x["odds"]]
    odds = [x for x in rows if x["odds"]]
    return {
        "lignes": rows,
        "n_estimes": len(both),
        "est_vs_cotes": {"ecart": mae([x["est"]["spread_home"] - x["odds"]["spread_home"] for x in both]),
                         "total": mae([x["est"]["total"] - x["odds"]["total"] for x in both])},
        "est_vs_reel": {"ecart": mae([x["est"]["spread_home"] - x["real_spread"] for x in both]),
                        "total": mae([x["est"]["total"] - x["real_total"] for x in both])},
        "cotes_vs_reel": {"ecart": mae([x["odds"]["spread_home"] - x["real_spread"] for x in odds]),
                          "total": mae([x["odds"]["total"] - x["real_total"] for x in odds]), "n": len(odds)},
    }


def run(night):
    j = json.loads((DIR / f"{night}.json").read_text(encoding="utf-8"))
    players = j["players"]
    hist = history.get(list(players), force=True)
    rows, pending = [], []
    for slug, p in players.items():
        g = find_game(hist.get(slug, []), _tip(p["tip"]))
        if g and g["basketballGame"]["statusTyped"] != "played":
            pending.append(p["name"])
            continue
        played = bool(g and (g["minsPlayed"] or 0) > 0)
        row = dict(p, slug=slug, played=played)
        if played:
            row["min"] = g["minsPlayed"]
            row["actual"] = round(sorare_score(g) * (1 + p["bonus"]), 2)
            row["stats"] = {k: g[v] or 0 for k, v in STATS.items()}
        rows.append(row)
    if pending:  # on réessaiera au passage suivant
        print(f"Bilan {night} pas écrit : {len(pending)} matchs pas finis ({', '.join(pending[:5])})")
        sys.exit(2)
    pl = [r for r in rows if r["played"]]

    out = {"night": night, "n": len(rows), "pending": pending}
    out["score"] = stats([r["actual"] - r["exp"] for r in pl])
    out["score_props"] = stats([r["actual"] - r["exp"] for r in pl if r["usesProps"]])
    out["score_hist_meme_joueurs"] = stats([r["actual"] - r["hist"] for r in pl if r["usesProps"]])
    out["score_sans_props"] = stats([r["actual"] - r["exp"] for r in pl if not r["usesProps"]])
    out["minutes"] = stats([r["min"] - r["estMin"] for r in pl])
    # Nous contre la projection officielle Sorare, sans bonus de carte (Sorare ne le compte pas).
    vs = [r for r in pl if r.get("sorare") is not None]
    out["vs_sorare"] = {
        "n": len(vs),
        "nous": stats([r["actual"] / (1 + r["bonus"]) - r["exp"] / (1 + r["bonus"]) for r in vs]),
        "sorare": stats([r["actual"] / (1 + r["bonus"]) - r["sorare"] for r in vs]),
        "nous_plus_proches": sum(abs(r["actual"] - r["exp"]) / (1 + r["bonus"]) < abs(r["actual"] / (1 + r["bonus"]) - r["sorare"]) for r in vs),
    }
    z = [(r["actual"] - r["exp"]) / r["sd"] for r in pl if r["sd"] > 0]
    out["dans_1_ecart_type"] = sum(abs(x) <= 1 for x in z) / len(z) if z else None
    out["composantes"] = {k: stats([r["stats"][k] - r["comps"].get(k, 0) for r in pl]) for k in STATS}
    buckets = {}
    for r in rows:
        b = "sûr (100 %)" if r["pct"] >= 1 else "probable (70-99 %)" if r["pct"] >= 0.7 else "incertain (< 70 %)"
        e = buckets.setdefault(b, {"n": 0, "prevu": 0.0, "joue": 0})
        e["n"] += 1
        e["prevu"] += r["pct"]
        e["joue"] += r["played"]
    out["presence"] = buckets
    out["matchs"] = games_check(night, j.get("games") or {})
    # Rythme : chez les joueurs projetés sur l'historique (rythme appliqué), le réel/prévu
    # doit rester stable d'un groupe à l'autre si l'ajustement est bien dosé.
    rp = {}
    for r in pl:
        if r["usesProps"]:
            continue
        b = "match lent (< 0,97)" if r["pace"] < 0.97 else "match rapide (> 1,03)" if r["pace"] > 1.03 else "rythme moyen"
        e = rp.setdefault(b, {"n": 0, "prevu": 0.0, "reel": 0.0})
        e["n"] += 1
        e["prevu"] += r["exp"]
        e["reel"] += r["actual"]
    out["rythme"] = rp
    out["joueurs"] = sorted(
        ({k: r.get(k) for k in ("slug", "tip", "name", "team", "opp", "stars", "bonus", "pct", "pctSrc", "exp", "sd", "hist",
                                "usesProps", "estMin", "min", "actual", "comps", "stats", "reasons", "played", "sorare")}
         for r in rows), key=lambda r: -(r["actual"] or 0))
    (DIR / f"bilan-{night}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    show(out)
    return out


def show(o):
    f = lambda s: "-" if not s else f"n={s['n']:3d}  biais {s['biais']:+5.1f}  écart moyen {s['mae']:4.1f}"
    print(f"\nBilan du soir {o['night']} : {o['n']} joueurs projetés"
          + (f", {len(o['pending'])} matchs pas finis" if o["pending"] else ""))
    print("Score (avec bonus), réel - projeté :")
    print("  tous            ", f(o["score"]))
    print("  avec props      ", f(o["score_props"]))
    print("    (historique seul sur ces mêmes joueurs)", f(o["score_hist_meme_joueurs"]))
    print("  sans props      ", f(o["score_sans_props"]))
    print("  dans ±1 écart-type :", f"{o['dans_1_ecart_type']:.0%} (attendu ~68 %)" if o["dans_1_ecart_type"] else "-")
    print("Minutes          ", f(o["minutes"]))
    print("Stats, réel - projeté :")
    for k, s in o["composantes"].items():
        print(f"  {LABELS[k]:15s}", f(s))
    m = o.get("matchs")
    if m and m["n_estimes"]:
        print(f"Matchs estimés la veille ({m['n_estimes']}) : à {m['est_vs_cotes']['ecart']} pts des cotes sur l'écart, "
              f"{m['est_vs_cotes']['total']} sur le total ; erreur réelle écart {m['est_vs_reel']['ecart']} "
              f"(cotes : {m['cotes_vs_reel']['ecart']}), total {m['est_vs_reel']['total']} (cotes : {m['cotes_vs_reel']['total']})")
    for b, e in (o.get("rythme") or {}).items():
        print(f"  {b:22s} {e['n']:3d} joueurs à l'historique, réel/prévu {e['reel'] / e['prevu']:.2f}")
    print("Présence :")
    for b, e in o["presence"].items():
        print(f"  {b:20s} {e['n']:3d} joueurs, prévu {e['prevu'] / e['n']:.0%}, ont joué {e['joue'] / e['n']:.0%}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else espn.us_tonight().isoformat())
