"""Génère site/index.html : la page téléphone, autonome, avec ses données.

La page embarque les fiches joueurs et le contexte des matchs, et refait la
simulation dans le navigateur quand tu composes ton équipe.

Usage : python src/build_page.py [--nuits 2]
"""

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import journal
import model
from model import SIGMA_MARGIN
import strategie
from soirs import PARIS, STAR_CAP, best_teams, disjoint_sets, load_pool

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "page_template.html"
OUT = ROOT / "site" / "index.html"
# Paliers 1 à 6. 4 à 6 donnés par l'utilisateur ; 1 à 3 repris du guide
# Sorare Tools (chapitre 1 de Divination), à confirmer sur le plateau.
TARGETS = (150, 180, 210, 240, 270, 290)
DEFAULT_TARGET = 240
# Tag « explosif » : projeté à 15 pts ou plus et au moins 28 % de chances de faire 1,4 fois sa projection.
# Rejoué le 16/11 sur 274 joueurs projetés à 15 pts ou plus : les 32 « explosifs » ont fait +12 pts
# ou plus dans 25 % des cas, les autres dans 14 %.
BOOM_CUT = 0.28
# Seuil pour jouer un soir, par palier (chance de la meilleure équipe, telle qu'affichée).
# Calculé le 16/11 en simulant les ~50 soirs restants jusqu'au 6 janvier, avec 4 tentatives par palier
# et retour au palier 1 après 4 échecs : en dessous, mieux vaut attendre un meilleur soir.
# Paliers 1 à 3 : toujours jouer.
PLAY_MIN = {240: 0.15, 270: 0.09, 290: 0.06}
BOOM_MIN_EXP = 15
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def fr_time(tip_utc: str) -> str:
    dt = datetime.fromisoformat(tip_utc.replace("Z", "+00:00")).astimezone(PARIS)
    return f"{JOURS[dt.weekday()]} {dt.day} · {dt:%Hh%M}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nuits", type=int, default=2)
    ap.add_argument("--gabarit", action="store_true", help="réutilise les dernières données, change seulement la page")
    args = ap.parse_args()
    cache = ROOT / "data" / "page_data.json"
    if args.gabarit and cache.exists():
        render(json.loads(cache.read_text(encoding="utf-8")))
        return
    pool, contexts, calib, sched = load_pool(args.nuits)
    live = [p for p in pool if p["pct"] > 0]
    print("Recherche des meilleures équipes...")
    results = best_teams(live, contexts, calib, TARGETS, random.Random(5), top_k=300)
    # Les soirs suivants, à part : sinon les 300 meilleures se figent toutes le premier soir,
    # et on ne peut pas comparer les soirs (une vie perdue par tentative ratée).
    # Aussi les meilleures équipes d'une seule nuit (filtre de l'onglet Équipes : gagner un palier
    # en une nuit pour jouer le suivant le lendemain), sans doublon avec celles déjà trouvées.
    seen = {frozenset(p["slug"] for p in c) for _, _, c in results}
    for night in sorted({p["night"] for p in live}):
        sub = [p for p in live if p["night"] == night]
        if len(sub) >= 5:
            for r in best_teams(sub, contexts, calib, TARGETS, random.Random(5), top_k=40):
                k = frozenset(p["slug"] for p in r[2])
                if k not in seen:
                    seen.add(k)
                    results.append(r)
    results.sort(key=lambda t: -t[0][DEFAULT_TARGET])
    # Équipes sans joueur commun, à jouer en parallèle une même nuit, et combien en jouer.
    parallel, reco = {}, {}
    for night in sorted({p["night"] for p in live}):
        sub = [p for p in live if p["night"] == night]
        if len(sub) < 5:
            continue
        print(f"Équipes en parallèle, nuit {night}...")
        sets = disjoint_sets(sub, contexts, calib, TARGETS, random.Random(7))
        parallel[night] = sets
        reco[night] = strategie.recommend({t: [x[0][t] for x in sets[t]] for t in TARGETS}, night)
    try:  # le journal ne doit jamais empêcher la page de sortir
        journal.record(pool, results[:40], TARGETS, sched=sched, absences=calib.get("espn_out"))
    except Exception as e:
        print(f"Journal non écrit : {e!r}")

    ids = {p["slug"]: i for i, p in enumerate(pool)}
    players = []
    for p in pool:
        players.append({
            "id": ids[p["slug"]], "name": p["name"], "team": p["team"], "opp": p["opp"], "home": p["home"],
            "stars": p["stars"], "bonus": p["bonus"], "pct": p["pct"], "estMin": round(p["est_min"], 1),
            "sdMin": round(p["sd_min"], 1), "role": p["role"], "rates": [round(r, 3) for r in p["rates"]],
            "scale": round(p.get("scale", 1.0), 3), "exp": round(p["exp"], 1), "hist": round(p["hist_exp"], 1),
            "tip": p["tip_utc"], "when": fr_time(p["tip_utc"]), "night": p["night"], "game": p["game_key"],
            "reasons": p["reasons"], "edition": p["edition"].replace("divination_", "").replace("_", " "),
            "comps": p["comps"], "usesProps": p["uses_props"], "pace": round(p["pace"], 3),
            "blow": round(p["blow"], 3), "pctSrc": p["pct_src"], "minRule": p["min_rule"],
            "usualMin": p["usual_min"], "last": p["last"],
            "histVals": {k: round(v, 2) for k, v in p["hist_vals"].items()},
            "upside": round(p["upside"], 3),
            "teamK": round(p.get("team_k", 1.0), 3),
            "volK": round(p.get("vol_k", 1.0), 3),
            "l10": p.get("l10_sorare"),
        })
    games = []
    for g in sorted(sched, key=lambda g: g["tip_utc"]):
        key = f"{g['away']}@{g['home']}:{g['night']}"
        ctx = contexts.get(key)
        games.append({
            "key": key, "away": g["away"], "home": g["home"], "when": fr_time(g["tip_utc"]), "night": g["night"],
            "spreadHome": g["spread_home"], "total": g["total"], "book": g.get("book"),
            "homePts": ctx["home_pts"] if ctx else None, "awayPts": ctx["away_pts"] if ctx else None,
            "spreadUsed": ctx["spread_home"] if ctx else 0,
        })
    teams = []
    for r, mu, combo in results:
        teams.append({
            "ids": [ids[p["slug"]] for p in combo], "mu": round(mu + calib.get("team_offset", 0.0), 1),
            "p": {str(t): round(r[t], 4) for t in TARGETS},
            "p90": round(r.get("p90", 0)),
        })
    data = {
        "generated": datetime.now(PARIS).strftime("%d/%m à %Hh%M"),
        "nights": args.nuits, "targets": TARGETS, "defaultTarget": DEFAULT_TARGET,
        "starCap": STAR_CAP, "sigmaMargin": SIGMA_MARGIN,
        "disp": {"props": model.DISP_PROPS, "hist": model.DISP_HIST}, "playMin": {str(k): v for k, v in PLAY_MIN.items()}, "boomCut": BOOM_CUT, "boomMinExp": BOOM_MIN_EXP,
        "calib": calib, "games": games, "players": players, "teams": teams,
        "parallel": {n: {str(t): [{"ids": [ids[p["slug"]] for p in c], "p": {str(x): round(r[x], 4) for x in TARGETS},
                                    "p90": round(r.get("p90", 0)), "mu": round(mu + calib.get("team_offset", 0.0), 1)}
                                   for r, mu, c in sets[t]] for t in TARGETS} for n, sets in parallel.items()},
        "reco": reco,
        "hypotheses": {
            "Écart final autour du spread (écart-type)": f"{model.SIGMA_MARGIN:g} points",
            "Joueur Day-To-Day chez ESPN, sans autre info": f"{model.P_PLAY_DAY_TO_DAY:.0%} de chances de jouer",
            "Statuts RotoWire Prob / Ques / Doubt sans pourcentage": ", ".join(
                f"{k} {v:.0%}" for k, v in model.P_PLAY_ROTOWIRE.items()),
            "Fin de banc (pas titulaire, moins de 20 min d'habitude)": (
                f"chance de jouer = {model.BENCH_PCT_A:.0%} + {model.BENCH_PCT_B:g} x part de ses 10 derniers matchs "
                "où il est entré en jeu (part brute : 54 % prévus, 63 % joués ; recalage du 17/11 : 55 % prévus, 48 % joués ; "
                "depuis le 24/11, mi-chemin entre les deux)"),
            "Remplaçant promu": f"titulaire ce soir et moins de {model.PROMO_MAX_USUAL_MIN} min d'habitude",
            "Match sans cotes": ("points de chaque équipe estimés d'après ses matchs joués (attaque x défense adverse, "
                                 "avantage du terrain mesuré) ; sur la saison, écart final estimé à 12,2 pts près "
                                 "contre 13,7 en supposant un match nul, total à peine mieux que la moyenne ligue"),
            "Double-double et triple-double": "bonus ignorés dans l'estimation (1 point chacun au plus)",
            "Élargissement de la simulation": (
                f"écarts vers le haut x{model.DISP_PROPS[0]:g} (avec props) et x{model.DISP_HIST[0]:g} (historique), "
                f"vers le bas x{model.DISP_PROPS[1]:g} et x{model.DISP_HIST[1]:g} ; réglé le 16/11 sur 379 joueurs rejoués : "
                "11 % au-dessus du 90e centile simulé et 9 % sous le 10e, au lieu de 18 % et 12 %"),
            "Correction des équipes": (
                f"projections rapprochées de la moyenne de leur niveau d'étoiles (x{model.TEAM_SHRINK:g}), puis "
                f"{calib.get('team_offset', 0.0):+.0f} pts retirés au score simulé des équipes : trou mesuré sur les "
                "équipes proposées, compté pour moitié avec 5 soirs, de plus en plus avec les soirs suivants, "
                "recalculé chaque nuit (établi le 18/11 : 5 soirs sur 5 sous la projection)"),
            "Aléa commun à un match": "testé et écarté : les surprises de coéquipiers ne vont pas ensemble (corrélation -0,03 sur 1 193 paires)",
        },
    }
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    render(data)


def bilans():
    """Bilans des soirs joués, avec le score réel des équipes proposées par la page."""
    jdir = ROOT / "journal"
    out, actual = [], {}
    files = sorted(jdir.glob("bilan-*.json"))
    for f in files:
        b = json.loads(f.read_text(encoding="utf-8"))
        rows = []
        for r in b["joueurs"]:
            actual[(b["night"], r.get("slug"))] = r["actual"] or 0.0
            rows.append({"n": r["name"], "t": r["team"], "o": r["opp"], "s": r["stars"], "b": r["bonus"],
                         "pct": r["pct"], "src": r["pctSrc"], "e": r["exp"], "sd": r["sd"], "h": r["hist"],
                         "pr": r["usesProps"], "em": r["estMin"], "m": r.get("min"), "a": r["actual"],
                         "c": r["comps"], "st": r.get("stats"), "pl": r["played"]})
        out.append({"night": b["night"], "rows": rows, "pending": b.get("pending", []),
                    "games": (b.get("matchs") or {}).get("lignes", []), "pace": b.get("rythme") or {}})
    done = {b["night"] for b in out}
    for b in out:
        j = jdir / f"{b['night']}.json"
        teams = (json.loads(j.read_text(encoding="utf-8")).get("teams") or {}).get("list", []) if j.exists() else []
        nxt = (datetime.fromisoformat(b["night"]) + timedelta(days=1)).date().isoformat()
        b["teams"] = []
        for t in teams:
            pts, ok = [], True
            for slug in t["slugs"]:
                if (b["night"], slug) in actual:
                    pts.append(actual[(b["night"], slug)])
                elif nxt in done:
                    pts.append(actual.get((nxt, slug), 0.0))
                else:
                    ok = False
                    pts.append(None)
            b["teams"].append({"names": t["names"], "p": t["p"], "lock": t["lock"], "pts": pts, "mu": t.get("mu"),
                               "score": round(sum(pts), 1) if ok else None})
    return sorted(out, key=lambda b: b["night"], reverse=True)


def render(data):
    try:
        data["bilans"] = bilans()
    except Exception as e:  # le bilan ne doit jamais empêcher la page de sortir
        print(f"Bilans non chargés : {e!r}")
        data["bilans"] = []
    try:
        import verdicts
        data["verdicts"] = verdicts.compute()
        data["aFaire"] = verdicts.A_FAIRE
    except Exception as e:
        print(f"Verdicts non calculés : {e!r}")
        data["verdicts"] = []
    try:  # fil de nouvelles écrit par la routine du matin et la passe du lundi (METHODE.md)
        news = json.loads((ROOT / "notes" / "nouvelles.json").read_text(encoding="utf-8"))
        data["nouvelles"] = sorted(news, key=lambda n: n["date"], reverse=True)[:30]
    except Exception as e:
        print(f"Nouvelles non chargées : {e!r}")
        data["nouvelles"] = []
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"OK : {OUT} ({len(data['players'])} joueurs, {len(data['teams'])} équipes, {OUT.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
