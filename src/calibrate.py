"""Mesure, sur les vrais matchs récents, deux effets du contexte de match.

1. Blowout : minutes jouées / minutes habituelles du joueur, selon l'écart
   final, séparément pour les titulaires (28 min ou plus d'habitude) et les
   remplaçants (20 min ou moins).
2. Rythme : production par minute / production habituelle, selon les points
   marqués par l'équipe ce soir-là / moyenne de la ligue (pente d'une droite).

Sortie : data/calibration.json, lue par la simulation du soir.
Usage : python src/calibrate.py
"""

import json
import statistics as st
from pathlib import Path

from model import sorare_score

DATA = Path(__file__).resolve().parent.parent / "data"
BUCKETS = [(0, 10), (10, 15), (15, 20), (20, 25), (25, 99)]


def bucket(margin: float) -> int:
    return next(i for i, (lo, hi) in enumerate(BUCKETS) if lo <= margin < hi)


def main() -> None:
    hist = json.loads((DATA / "history.json").read_text(encoding="utf-8"))
    rows = []
    team_pts_by_game = {}
    for slug, entry in hist.items():
        games = [g for g in entry["games"] if (g.get("minsPlayed") or 0) > 0
                 and g["basketballGame"]["statusTyped"] == "played"]
        if len(games) < 5:
            continue
        med_min = st.median(g["minsPlayed"] for g in games)
        rates = [sorare_score(g) / g["minsPlayed"] for g in games if g["minsPlayed"] >= 8]
        if not rates or med_min < 8:
            continue
        mean_rate = st.mean(rates)
        for g in games:
            bg = g["basketballGame"]
            team = g["anyTeam"]["slug"]
            home = bg["homeTeam"]["slug"] == team
            pts, opp = (bg["homeScore"], bg["awayScore"]) if home else (bg["awayScore"], bg["homeScore"])
            team_pts_by_game[(bg["id"], team)] = pts
            rows.append({
                "role": "titulaire" if med_min >= 28 else "remplaçant" if med_min <= 20 else "milieu",
                "min_ratio": g["minsPlayed"] / med_min,
                "margin": abs(pts - opp),
                "won": pts > opp,
                "team_pts": pts,
                "rate_ratio": (sorare_score(g) / g["minsPlayed"]) / mean_rate if g["minsPlayed"] >= 8 else None,
            })

    league_pts = st.mean(team_pts_by_game.values())
    margins = []
    seen = set()
    for (gid, _), _pts in team_pts_by_game.items():
        if gid not in seen:
            seen.add(gid)
    print(f"{len(rows)} lignes joueur-match, {len(seen)} matchs, moyenne ligue {league_pts:.1f} pts par équipe\n")

    calib = {"buckets": BUCKETS, "minutes": {}, "league_team_pts": league_pts}
    print("Minutes jouées / minutes habituelles, selon l'écart final :")
    print(f"{'écart':>8} | " + " | ".join(f"{r:>18}" for r in ("titulaire", "milieu", "remplaçant")))
    for i, (lo, hi) in enumerate(BUCKETS):
        cells = []
        for role in ("titulaire", "milieu", "remplaçant"):
            vals = [r["min_ratio"] for r in rows if r["role"] == role and bucket(r["margin"]) == i]
            m = st.mean(vals) if vals else 1.0
            calib["minutes"].setdefault(role, []).append(m)
            cells.append(f"{m:6.2f} (n={len(vals):4d})")
        label = f"{lo}-{hi - 1}" if hi < 99 else f"{lo}+"
        print(f"{label:>8} | " + " | ".join(f"{c:>18}" for c in cells))

    # Pente production par minute ~ points de l'équipe (moindres carrés simples).
    pairs = [(r["team_pts"] / league_pts, r["rate_ratio"]) for r in rows if r["rate_ratio"] is not None]
    mx = st.mean(x for x, _ in pairs)
    my = st.mean(y for _, y in pairs)
    slope = sum((x - mx) * (y - my) for x, y in pairs) / sum((x - mx) ** 2 for x, _ in pairs)
    calib["pace_slope"] = slope
    print(f"\nRythme : +10 % de points pour l'équipe = {slope * 10:+.1f} % de production par minute"
          f" (pente {slope:.2f}, {len(pairs)} lignes)")

    (DATA / "calibration.json").write_text(json.dumps(calib, indent=1, ensure_ascii=False), encoding="utf-8")
    print("OK : data/calibration.json")


if __name__ == "__main__":
    main()
