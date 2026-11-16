"""Journal des projections, pour le bilan du lendemain.

À chaque passage, la projection de chaque joueur dont le match n'a pas
commencé est réécrite dans journal/<soir>.json. Une fois le match lancé, plus
rien ne la touche : il reste la dernière projection faite avant le coup d'envoi,
celle qu'on compare ensuite au vrai score.

Les équipes proposées sont gardées de la même façon, dans le fichier du soir
où elles se figent (premier coup d'envoi parmi les 5).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "journal"


def _tip(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _load(night: str) -> dict:
    f = DIR / f"{night}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"night": night, "players": {}, "teams": None}


def record(pool, results, targets, now=None, sched=None):
    """pool : fiches de soirs.load_pool ; results : sortie de best_teams."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%MZ")
    files = {}
    for p in pool:
        if _tip(p["tip_utc"]) <= now:
            continue
        j = files.setdefault(p["night"], _load(p["night"]))
        j["players"][p["slug"]] = {
            "name": p["name"], "team": p["team"], "opp": p["opp"], "game": p["game_key"], "tip": p["tip_utc"],
            "recorded": stamp, "stars": p["stars"], "bonus": p["bonus"],
            # exp et sd : score avec bonus s'il joue ; pct : chance qu'il joue.
            "pct": p["pct"], "pctSrc": p["pct_src"], "exp": round(p["exp"], 2), "sd": round(p["sd"], 2),
            "raw": round(p["exp"] / (1 + p["bonus"]), 2), "hist": round(p["hist_exp"], 2),
            "usesProps": p["uses_props"], "estMin": round(p["est_min"], 1), "sdMin": round(p["sd_min"], 1),
            "role": p["role"], "starter": p.get("starter"), "promoted": p.get("promoted"), "b2b": p.get("b2b"),
            "pace": round(p["pace"], 3), "blow": round(p["blow"], 3), "reasons": p["reasons"], "upside": round(p.get("upside", 0), 3),
            "comps": {c["k"]: round(c["val"], 2) for c in p["comps"]},
            "histComps": {k: round(v, 2) for k, v in p.get("hist_vals", {}).items()},
        }
    teams_by_night = {}
    for r, mu, combo in results:
        lock = min(combo, key=lambda p: p["tip_utc"])
        if _tip(lock["tip_utc"]) <= now:
            continue
        teams_by_night.setdefault(lock["night"], []).append({
            "slugs": [p["slug"] for p in combo], "names": [p["name"] for p in combo],
            "stars": sum(p["stars"] for p in combo), "lock": lock["tip_utc"], "mu": round(mu, 1),
            "p": {str(t): round(r[t], 4) for t in targets},
        })
    # Matchs : notre dernière estimation tant qu'il n'y avait pas de cotes, puis les
    # dernières vraies cotes avant le coup d'envoi. Le bilan compare les deux.
    for g in sched or []:
        if _tip(g["tip_utc"]) <= now or g.get("spread_home") is None:
            continue
        j = files.setdefault(g["night"], _load(g["night"]))
        e = j.setdefault("games", {}).setdefault(f"{g['away']}@{g['home']}", {"tip": g["tip_utc"]})
        line = {"spread_home": g["spread_home"], "total": g["total"], "book": g.get("book"), "recorded": stamp}
        e["est" if str(g.get("book") or "").startswith("estimation") else "odds"] = line
    for night, teams in teams_by_night.items():
        j = files.setdefault(night, _load(night))
        j["teams"] = {"recorded": stamp, "list": teams}
    DIR.mkdir(exist_ok=True)
    for night, j in files.items():
        (DIR / f"{night}.json").write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
    resume = ", ".join("%s (%d joueurs)" % (n, len(j["players"])) for n, j in sorted(files.items()))
    print("Journal : " + resume)
