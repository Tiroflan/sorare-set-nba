"""Points attendus d'un match qui n'a pas encore de cotes, d'après les matchs joués.

Pour chaque équipe : points marqués et encaissés par match cette saison (ESPN),
ramenés vers la moyenne de la ligue tant que l'échantillon est petit. Puis :
  points de A contre B = attaque de A x défense de B / moyenne ligue, +- avantage du terrain.
L'avantage du terrain est mesuré sur les mêmes matchs.

Les résultats d'un soir terminé ne bougent plus : ils sont gardés dans data/espn_scores.json.

Usage direct (contrôle) : python src/team_ratings.py
"""

import json
from datetime import date, timedelta
from pathlib import Path

import espn

DATA = Path(__file__).resolve().parent.parent / "data"
CACHE = DATA / "espn_scores.json"
SEASON_START = date(2026, 10, 20)  # premier soir où chercher des matchs
SHRINK_GAMES = 6  # poids de la moyenne ligue, en matchs, dans l'attaque et la défense d'une équipe


def results(until: date) -> list[dict]:
    """Matchs terminés du début de saison jusqu'à `until` (exclu), avec les cotes d'avant-match d'ESPN."""
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    d = SEASON_START
    changed = False
    while d < until:
        key = d.isoformat()
        if key not in cache:
            data = espn._get(f"{espn.BASE}/scoreboard?dates={d:%Y%m%d}")
            day = []
            for e in data.get("events", []):
                c = e["competitions"][0]
                if e["status"]["type"]["name"] != "STATUS_FINAL":
                    continue
                side = {t["homeAway"]: t for t in c["competitors"]}
                odds = (c.get("odds") or [{}])[0]
                day.append({
                    "night": key, "home": espn.code(side["home"]["team"]["abbreviation"]),
                    "away": espn.code(side["away"]["team"]["abbreviation"]),
                    "home_pts": int(side["home"]["score"]), "away_pts": int(side["away"]["score"]),
                    "book_total": odds.get("overUnder"), "book_details": odds.get("details"),
                })
            cache[key] = day
            changed = True
        d += timedelta(days=1)
    if changed:
        DATA.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return [g for k in sorted(cache) if k < until.isoformat() for g in cache[k]]


def ratings(games: list[dict]) -> dict:
    if not games:
        return {"league": None, "hca": 0.0, "teams": {}, "n": 0}
    league = sum(g["home_pts"] + g["away_pts"] for g in games) / (2 * len(games))
    hca = sum(g["home_pts"] - g["away_pts"] for g in games) / len(games)
    acc = {}
    for g in games:
        for me, opp, pf, pa in ((g["home"], g["away"], g["home_pts"], g["away_pts"]),
                                (g["away"], g["home"], g["away_pts"], g["home_pts"])):
            a = acc.setdefault(me, [0, 0, 0])
            a[0] += pf
            a[1] += pa
            a[2] += 1
    teams = {t: {"off": (pf + SHRINK_GAMES * league) / (n + SHRINK_GAMES),
                 "def": (pa + SHRINK_GAMES * league) / (n + SHRINK_GAMES), "n": n}
             for t, (pf, pa, n) in acc.items()}
    return {"league": league, "hca": hca, "teams": teams, "n": len(games)}


def predict(r: dict, home: str, away: str):
    """(spread_home, total) : spread négatif = domicile favori. None si pas assez de données."""
    if not r["league"] or home not in r["teams"] or away not in r["teams"]:
        return None
    h, a, lg = r["teams"][home], r["teams"][away], r["league"]
    home_pts = h["off"] * a["def"] / lg + r["hca"] / 2
    away_pts = a["off"] * h["def"] / lg - r["hca"] / 2
    return round(away_pts - home_pts, 1), round(home_pts + away_pts, 1)


def book_spread_home(g: dict):
    """Spread domicile des cotes ESPN d'avant-match (« BOS -6.5 »), ou None."""
    det = (g.get("book_details") or "").split()
    if len(det) == 2:
        try:
            line = float(det[1])
        except ValueError:
            return None
        return line if espn.code(det[0]) == g["home"] else -line
    return 0.0 if (g.get("book_details") or "").upper() == "EVEN" else None


if __name__ == "__main__":
    # Contrôle hors échantillon : pour chaque soir, notes calculées sur les soirs d'avant seulement.
    games = results(date.today())
    nights = sorted({g["night"] for g in games})
    rows = []
    for n in nights:
        r = ratings([g for g in games if g["night"] < n])
        if r["n"] < 40:
            continue
        for g in (g for g in games if g["night"] == n):
            pr = predict(r, g["home"], g["away"])
            if pr:
                rows.append((g, pr, r["league"]))
    print(f"{len(games)} matchs joués, {len(rows)} prédits hors échantillon")
    mae = lambda xs: sum(abs(x) for x in xs) / len(xs)
    real_tot = [g["home_pts"] + g["away_pts"] for g, _, _ in rows]
    real_sp = [g["away_pts"] - g["home_pts"] for g, _, _ in rows]
    print(f"Total : notre estimation {mae([p[1] - t for (_, p, _), t in zip(rows, real_tot)]):.1f} pts d'erreur moyenne, "
          f"moyenne ligue {mae([2 * lg - t for (_, _, lg), t in zip(rows, real_tot)]):.1f}")
    print(f"Écart : notre estimation {mae([p[0] - s for (_, p, _), s in zip(rows, real_sp)]):.1f}, "
          f"match nul supposé {mae(real_sp):.1f}")
    bk = [(g, p) for g, p, _ in rows if g["book_total"] and book_spread_home(g) is not None]
    if bk:
        print(f"Sur {len(bk)} matchs avec cotes ESPN : bookmakers total {mae([g['book_total'] - g['home_pts'] - g['away_pts'] for g, _ in bk]):.1f}, "
              f"écart {mae([book_spread_home(g) - (g['away_pts'] - g['home_pts']) for g, _ in bk]):.1f} ; "
              f"nous total {mae([p[1] - g['home_pts'] - g['away_pts'] for g, p in bk]):.1f}, "
              f"écart {mae([p[0] - (g['away_pts'] - g['home_pts']) for g, p in bk]):.1f} ; "
              f"distance aux cotes : total {mae([p[1] - g['book_total'] for g, p in bk]):.1f}, "
              f"écart {mae([p[0] - book_spread_home(g) for g, p in bk]):.1f}")
