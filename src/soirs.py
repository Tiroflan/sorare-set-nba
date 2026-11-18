"""Les meilleures équipes sur une fenêtre de plusieurs soirs, et l'évaluation de la tienne.

Sources : galerie et historique (API publique Sorare), calendrier, cotes et
blessures (ESPN), compos du soir (RotoWire), calibration blowout et rythme
(data/calibration.json, voir calibrate.py).

Règles prises en compte :
- 5 joueurs, 16 étoiles au plus ;
- chaque joueur compte pour son premier match dans la fenêtre ;
- l'équipe est figée au premier coup d'envoi parmi ses 5 joueurs.

Usage :
  python src/soirs.py --nuits 2 --cible 240
  python src/soirs.py --nuits 2 --cible 240 --equipe "Wembanyama,Gilgeous,Wagner,Jenkins,McBride"
"""

import argparse
import itertools
import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import espn
import history
import odds
import rotowire
import team_ratings
from model import (SD_WIDEN_HIST, SD_WIDEN_PROPS, TEAM_SHRINK, upside, breakdown, build_player, context_factors, expected_score, game_context, norm,
                   simulate_team)
from phase0_faisabilite import edition_bonus, p_normal

DATA = Path(__file__).resolve().parent.parent / "data"
STAR_CAP = 16.0
N_SIM = 15000
TOP_K = 250
KEEP_PER_STAR_LEVEL = 6

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # pas de base de fuseaux sur la machine : heure d'hiver
    PARIS = timezone(timedelta(hours=1))


def paris(tip_utc: str) -> str:
    dt = datetime.fromisoformat(tip_utc.replace("Z", "+00:00")).astimezone(PARIS)
    return dt.strftime("%a %d %Hh%M")


def load_pool(nights: int):
    players = json.loads((DATA / "players.json").read_text(encoding="utf-8"))
    gallery = json.loads((DATA / "gallery.json").read_text(encoding="utf-8"))
    calib = json.loads((DATA / "calibration.json").read_text(encoding="utf-8"))

    print("Calendrier ESPN...")
    # Le matin, la nuit US d'hier est finie : on prend un jour de plus et on garde
    # les `nights` premiers soirs qui ont encore des matchs à venir.
    sched = [g for g in espn.schedule(espn.us_tonight(), nights + 1) if g["status"] == "STATUS_SCHEDULED"]
    keep = sorted({g["night"] for g in sched})[:nights]
    sched = [g for g in sched if g["night"] in keep]
    print("Compos RotoWire du soir...")
    try:
        rw = rotowire.fetch()
    except Exception as e:  # la page peut changer : on continue sans
        print(f"  RotoWire indisponible ({e})")
        rw = []
    print("Cotes Pinnacle et Bovada...")
    book_lines, props = odds.fetch_all()
    for s in sched:
        bl = book_lines.get((s["away"], s["home"]))
        if bl:
            s["spread_home"] = bl["spread_home"] if bl["spread_home"] is not None else s["spread_home"]
            s["total"] = bl["total"] or s["total"]
            s["book"] = bl["book"]
        elif s["spread_home"] is not None:
            s["book"] = "ESPN"
    lineups = {}
    for g in rw:
        for team, lu in g["teams"].items():
            lineups[team] = lu
        # Cotes RotoWire si ESPN n'en a pas encore.
        for s in sched:
            if {s["away"], s["home"]} == {g["away"], g["home"]} and s["spread_home"] is None and g["spread"]:
                fav, line = g["spread"].split()
                s["spread_home"] = float(line) if fav == s["home"] else -float(line)
                s["total"] = s["total"] or g["total"]
                s["book"] = "RotoWire"
    # Pas encore de cotes nulle part (souvent le lendemain) : estimation d'après les matchs joués.
    todo = [s for s in sched if s["spread_home"] is None]
    if todo:
        try:
            r = team_ratings.ratings(team_ratings.results(min(date.fromisoformat(s["night"]) for s in sched)))
            for s in todo:
                pr = team_ratings.predict(r, s["home"], s["away"])
                if pr:
                    s["spread_home"], s["total"] = pr
                    s["book"] = "estimation (matchs joués)"
            print(f"  {sum(1 for s in todo if s.get('book'))} matchs sans cotes estimés d'après {r['n']} matchs joués")
        except Exception as e:
            print(f"  estimation des matchs sans cotes impossible ({e})")
    print("Blessures ESPN...")
    inj = espn.injuries()

    first_game = {}
    for g in sorted(sched, key=lambda g: g["tip_utc"]):
        for team in (g["away"], g["home"]):
            first_game.setdefault(team, g)
    tonight = min((g["night"] for g in sched), default="")  # soir des compos RotoWire
    played_night_before = {(t, g["night"]) for g in sched for t in (g["away"], g["home"])}

    in_window = [p for p in players if (p.get("activeClub") or {}).get("code") in first_game]
    print(f"{len(in_window)} joueurs de ta galerie jouent dans la fenêtre, historique...")
    hist = history.get([p["slug"] for p in in_window])

    best_bonus = {}
    for c in gallery:
        b, s = edition_bonus(c.get("cardEditionName")), c["anyPlayer"]["slug"]
        if s not in best_bonus or b > best_bonus[s][0]:
            best_bonus[s] = (b, c.get("cardEditionName") or "")

    contexts, pool = {}, []
    for p in in_window:
        team = p["activeClub"]["code"]
        g = first_game[team]
        lineup = lineups.get(team) if g["night"] == tonight else None
        bonus, edition = best_bonus.get(p["slug"], (0.0, ""))
        pl = build_player(p, hist.get(p["slug"], []), bonus, edition, g, lineup, inj, None)
        if not pl:
            continue
        prev = (datetime.fromisoformat(g["night"]) - timedelta(days=1)).date().isoformat()
        if (team, prev) in played_night_before and "back-to-back" not in pl["reasons"]:
            pl["b2b"] = True
            pl["reasons"].append("back-to-back")
        ctx = contexts.setdefault(pl["game_key"], game_context(g, calib))
        e_sim = expected_score(pl, ctx, calib)  # centre "naturel" de la simulation
        sd_rate = (sum((r - pl["rate"]) ** 2 for r in pl["rates"]) / len(pl["rates"])) ** 0.5
        pl["sd"] = math.hypot(sd_rate * pl["est_min"], pl["rate"] * pl["sd_min"]) * (1 + pl["bonus"])
        pace, blow = context_factors(pl, ctx, calib)
        pl["pace"], pl["blow"] = pace, blow
        # Estimation historique, stat par stat, ajustée au contexte du match.
        hist_comps = breakdown(pl, {}, {})
        pl["hist_exp"] = sum(c["pts"] for c in hist_comps) * pace * blow * (1 + pl["bonus"])
        pl["hist_vals"] = {c["k"]: c["val"] * pace * blow for c in hist_comps}  # comparables aux props
        pl["comps"], pl["uses_props"] = hist_comps, False
        pl["exp"] = pl["hist_exp"]
        prop = props.get(norm(p["displayName"]))
        if prop and espn.code(prop["team"]) == team:
            comps = breakdown(pl, odds.expected_stats(prop), prop["lines"])
            raw = sum(c["pts"] for c in comps)
            # Au moins une stat vraiment tirée des cotes : sinon (marché publié mais
            # inexploitable) on garde l'historique ajusté au match.
            if raw > 0 and any(c["src"] == "Bovada" for c in comps):
                # Les cotes intègrent déjà rythme et blowout : pas de facteur de contexte.
                pl["comps"], pl["uses_props"] = comps, True
                pl["exp"] = raw * (1 + pl["bonus"])
                pl["reasons"].append(f"props {pl['exp'] / pl['hist_exp'] - 1:+.0%} vs historique")
        # La simulation garde la forme de l'historique, recentrée sur l'estimation retenue.
        pl["scale"] = pl["exp"] / e_sim if e_sim > 0 else 1.0
        pl["sd"] *= pl["scale"] * (SD_WIDEN_PROPS if pl["uses_props"] else SD_WIDEN_HIST)
        pl["upside"] = upside(pl)
        pool.append(pl)
    # Correction des équipes (voir TEAM_SHRINK dans model.py).
    levels = {}
    for pl in pool:
        if pl["pct"] > 0:
            levels.setdefault((pl["night"], pl["stars"]), []).append(pl["exp"])
    for pl in pool:
        g = levels.get((pl["night"], pl["stars"]), [])
        m = sum(g) / len(g) if len(g) >= 3 else pl["exp"]
        pl["team_k"] = (m + TEAM_SHRINK * (pl["exp"] - m)) / pl["exp"] if pl["exp"] > 0 else 1.0
    try:
        import verdicts
        calib["team_offset"], n_off, gap = verdicts.team_offset()
        print(f"Correction des équipes : {calib['team_offset']:+.1f} pts (trou de {gap:+.1f} sur {n_off} soirs)")
    except Exception as e:
        calib["team_offset"] = 0.0
        print(f"Correction des équipes non calculée : {e!r}")
    return pool, contexts, calib, sched


def describe(team):
    lock = min(team, key=lambda p: p["tip_utc"])
    names = ", ".join(f"{p['name'].split()[-1]} {p['stars']:g}*" for p in team)
    return f"{sum(p['stars'] for p in team):g}* | figée {paris(lock['tip_utc'])} | {names}"


def evaluate(team, contexts, calib, targets, rng):
    return simulate_team(team, contexts, calib, targets, N_SIM, rng)


def best_teams(live, contexts, calib, targets, rng, top_k=TOP_K):
    """Équipes sous 16 étoiles, présélectionnées par approximation normale puis
    simulées. Renvoie [(probas par cible, moyenne, joueurs)]."""
    by_level = {}
    for p in live:
        by_level.setdefault(p["stars"], []).append(p)
    short = {}
    for ps in by_level.values():
        for key in (lambda p: -p["exp"], lambda p: -(p["exp"] + p["sd"])):
            for p in sorted(ps, key=key)[:KEEP_PER_STAR_LEVEL]:
                short[p["slug"]] = p
    teams = []
    for combo in itertools.combinations(list(short.values()), 5):
        if sum(p["stars"] for p in combo) > STAR_CAP:
            continue
        mu = sum(p["exp"] * p["pct"] * p.get("team_k", 1.0) for p in combo)
        sd = math.sqrt(sum(p["sd"] ** 2 for p in combo))
        off = calib.get("team_offset", 0.0)
        teams.append((sum(p_normal(mu + off, sd, t) for t in targets), mu, combo))
    teams.sort(key=lambda t: -t[0])
    return [(evaluate(list(c), contexts, calib, targets, rng), mu, list(c)) for _, mu, c in teams[:top_k]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nuits", type=int, default=2)
    ap.add_argument("--cible", type=float, default=240)
    ap.add_argument("--equipe", help="5 noms (ou morceaux de noms) séparés par des virgules")
    args = ap.parse_args()
    targets = (args.cible, args.cible + 30)
    pool, contexts, calib, sched = load_pool(args.nuits)
    rng = random.Random(11)

    print("\nMatchs de la fenêtre (heure de Paris) :")
    for g in sorted(sched, key=lambda g: g["tip_utc"]):
        ctx = contexts.get(f"{g['away']}@{g['home']}:{g['night']}")
        line = (f"spread dom. {g['spread_home']:+g}, total {g['total']}, {g.get('book', '?')}"
                if g["spread_home"] is not None else "pas encore de cotes")
        print(f"  {paris(g['tip_utc'])}  {g['away']} @ {g['home']}  ({line})")

    live = [p for p in pool if p["pct"] > 0]
    live.sort(key=lambda p: -p["exp"] / p["stars"])
    print(f"\n{'joueur':24} {'match':12} {'étoiles':>7} {'bonus':>5} {'joue':>5} {'min':>5} {'histo':>6}"
          f" {'estimé':>6} {'pts/étoile':>10}  raisons")
    for p in live[:45]:
        print(f"{p['name'][:24]:24} {p['team'] + ('-' if p['home'] else '@') + p['opp']:12}"
              f" {p['stars']:7.1f} {p['bonus']:5.0%} {p['pct']:5.0%} {p['est_min']:5.1f} {p['hist_exp']:6.1f}"
              f" {p['exp']:6.1f}"
              f" {p['exp'] / p['stars']:10.1f}  {paris(p['tip_utc'])} {', '.join(p['reasons'])}")

    if args.equipe:
        wanted = [norm(x) for x in args.equipe.split(",")]
        team = []
        for w in wanted:
            match = [p for p in pool if w in norm(p["name"])]
            if not match:
                print(f"\nJoueur introuvable dans la fenêtre : {w}")
                return
            team.append(match[0])
        r = evaluate(team, contexts, calib, targets, rng)
        mu = sum(p["exp"] * p["pct"] for p in team)
        print(f"\nTon équipe : moy {mu:.1f} | P>={targets[0]:g} {r[targets[0]]:.1%} | P>={targets[1]:g}"
              f" {r[targets[1]]:.1%} | {describe(team)}")
        for p in team:
            print(f"   {p['name']:24} {p['exp']:5.1f} pts estimés, joue {p['pct']:.0%}, {paris(p['tip_utc'])}"
                  f" {', '.join(p['reasons'])}")
        swaps = []
        for i, out in enumerate(team):
            rest = team[:i] + team[i + 1:]
            budget = STAR_CAP - sum(p["stars"] for p in rest)
            for cand in live:
                if cand in team or cand["stars"] > budget:
                    continue
                new = rest + [cand]
                mu2 = sum(p["exp"] * p["pct"] for p in new)
                if mu2 > mu - 5:
                    swaps.append((mu2, out, cand, new))
        swaps.sort(key=lambda s: -s[0])
        tested = []
        for mu2, out, cand, new in swaps[:25]:
            tested.append((evaluate(new, contexts, calib, targets, rng), out, cand, new))
        tested.sort(key=lambda t: -t[0][targets[0]])
        print("\nRemplacements qui améliorent tes chances (un seul changement) :")
        shown = 0
        for r2, out, cand, new in tested:
            if r2[targets[0]] <= r[targets[0]] + 0.005:
                continue
            print(f"   {out['name']} -> {cand['name']} ({cand['stars']:g}*, {paris(cand['tip_utc'])}) :"
                  f" P>={targets[0]:g} {r2[targets[0]]:.1%}, P>={targets[1]:g} {r2[targets[1]]:.1%}")
            shown += 1
            if shown == 5:
                break
        if not shown:
            print("   aucun remplacement simple ne fait mieux")

    results = best_teams(live, contexts, calib, targets, rng)
    for t in targets:
        print(f"\nMeilleures équipes de la fenêtre pour {t:g} points :")
        for r, mu, combo in sorted(results, key=lambda r: -r[0][t])[:5]:
            print(f"- P>={targets[0]:g} {r[targets[0]]:5.1%} | P>={targets[1]:g} {r[targets[1]]:5.1%}"
                  f" | moy {mu:5.1f} | {describe(combo)}")


if __name__ == "__main__":
    main()
