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
from soirs import PARIS, STAR_CAP, best_teams, load_pool

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "page_template.html"
OUT = ROOT / "site" / "index.html"
# Paliers 1 à 6. 4 à 6 donnés par l'utilisateur ; 1 à 3 repris du guide
# Sorare Tools (chapitre 1 de Divination), à confirmer sur le plateau.
TARGETS = (150, 180, 210, 240, 270, 290)
DEFAULT_TARGET = 240
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
    results.sort(key=lambda t: -t[0][DEFAULT_TARGET])
    try:  # le journal ne doit jamais empêcher la page de sortir
        journal.record(pool, results[:40], TARGETS)
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
            "ids": [ids[p["slug"]] for p in combo], "mu": round(mu, 1),
            "p": {str(t): round(r[t], 4) for t in TARGETS},
        })
    data = {
        "generated": datetime.now(PARIS).strftime("%d/%m à %Hh%M"),
        "nights": args.nuits, "targets": TARGETS, "defaultTarget": DEFAULT_TARGET,
        "starCap": STAR_CAP, "sigmaMargin": SIGMA_MARGIN,
        "calib": calib, "games": games, "players": players, "teams": teams,
        "hypotheses": {
            "Écart final autour du spread (écart-type)": f"{model.SIGMA_MARGIN:g} points",
            "Joueur Day-To-Day chez ESPN, sans autre info": f"{model.P_PLAY_DAY_TO_DAY:.0%} de chances de jouer",
            "Statuts RotoWire Prob / Ques / Doubt sans pourcentage": ", ".join(
                f"{k} {v:.0%}" for k, v in model.P_PLAY_ROTOWIRE.items()),
            "Fin de banc (pas titulaire, moins de 20 min d'habitude)": (
                "chance de jouer = part de ses 10 derniers matchs où il est entré en jeu "
                "(vérifié le 12/11 : 56 % prévu, 55 % ont joué)"),
            "Remplaçant promu": f"titulaire ce soir et moins de {model.PROMO_MAX_USUAL_MIN} min d'habitude",
            "Match sans cotes": ("points de chaque équipe estimés d'après ses matchs joués (attaque x défense adverse, "
                                 "avantage du terrain mesuré) ; sur la saison, écart final estimé à 12,2 pts près "
                                 "contre 13,7 en supposant un match nul, total à peine mieux que la moyenne ligue"),
            "Double-double et triple-double": "bonus ignorés dans l'estimation (1 point chacun au plus)",
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
        out.append({"night": b["night"], "rows": rows, "pending": b.get("pending", [])})
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
            b["teams"].append({"names": t["names"], "p": t["p"], "lock": t["lock"], "pts": pts,
                               "score": round(sum(pts), 1) if ok else None})
    return sorted(out, key=lambda b: b["night"], reverse=True)


def render(data):
    try:
        data["bilans"] = bilans()
    except Exception as e:  # le bilan ne doit jamais empêcher la page de sortir
        print(f"Bilans non chargés : {e!r}")
        data["bilans"] = []
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"OK : {OUT} ({len(data['players'])} joueurs, {len(data['teams'])} équipes, {OUT.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
