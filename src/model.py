"""Le modèle : du joueur au score d'équipe, sur une fenêtre de plusieurs soirs.

Tout ce qui est hypothèse (pas mesuré sur nos données) est regroupé ici, en
haut du fichier, pour être visible et facile à recalibrer plus tard.
"""

import random
import re
import statistics as st
import unicodedata
from datetime import datetime, timedelta, timezone

# --- Hypothèses (non mesurées, à recalibrer avec le journal des soirs) ---
SIGMA_MARGIN = 12.0       # écart-type de l'écart final autour du spread
DEFAULT_TOTAL = None      # total inconnu : on prend 2 x la moyenne ligue
P_PLAY_DAY_TO_DAY = 0.6   # blessé "Day-To-Day" sans autre info
P_PLAY_ROTOWIRE = {"prob": 0.85, "ques": 0.5, "doubt": 0.2}
PROMO_MAX_USUAL_MIN = 24  # titulaire ce soir mais moins de 24 min d'habitude = promu
MIN_SD_FLOOR = 3.0        # incertitude minimale sur les minutes
# --- Mesuré avec le journal des soirs ---
BENCH_MAX_USUAL_MIN = 20  # sous 20 min d'habitude et pas titulaire : chance de jouer = taux d'apparition récent
# Chance de jouer d'une fin de banc = BENCH_PCT_A + BENCH_PCT_B x taux d'apparition récent.
# Recalé le 17/11 sur 211 cas (5 nuits) : le taux brut prévoyait 54 %, 63 % ont joué ; 21 % prévus -> 41 % joués
# chez les moins présents (matchs manqués sur blessure comptés comme non joués).
# Puis trop généreux : du 17 au 23/11, 55 % prévus, 48 % ont joué (240 cas, z = -2,5). Le 24/11, mi-chemin
# entre la part brute (0 + 1 x taux) et le recalage du 17/11 (0,26 + 0,72 x taux), décidé avec Romain.
BENCH_PCT_A = 0.13
BENCH_PCT_B = 0.86
# Élargissement de la simulation (haut, bas), réglé le 16/11 sur 379 joueurs rejoués
# (src/calib_check.py) : sans lui, 17,7 % des joueurs passaient au-dessus du 90e centile
# simulé et 12,1 % sous le 10e ; avec, 11,3 % et 8,7 %. Les explosions sont plus
# fréquentes que ne le dit l'historique, surtout pour les joueurs sans props.
DISP_PROPS = (1.15, 1.0)
DISP_HIST = (1.6, 1.2)
# Même chose pour l'écart-type affiché (±) : 68 % des joueurs dans ±1 écart-type.
SD_WIDEN_PROPS = 1.1
SD_WIDEN_HIST = 1.4
# Équipes surestimées (établi le 18/11, 5 soirs sur 5 sous la projection) :
# 1. avant de choisir et simuler les équipes, chaque projection est rapprochée de la moyenne de son niveau
#    d'étoiles ce soir-là (pente mesurée 0,87 sur 585 joueurs : les plus hautes projections d'un niveau
#    sont un peu gonflées par hasard, et l'optimiseur les attrape) ;
# 2. le trou restant mesuré sur les équipes proposées est retiré du score simulé (verdicts.team_offset).
TEAM_SHRINK = 0.87
# Pistes de l'analyse du 24/11, appliquées à la MOITIÉ de l'effet mesuré (demande de Romain : ne pas perdre de
# nuits à attendre). Suivies sur les nuits suivantes (verdicts petit_total, outsider, props_hausse) : on les
# garde, on les pousse à l'effet plein si le reste d'écart se confirme, on les retire s'il s'inverse.
ADJ_LOW_TOTAL = 0.98        # match à 220 pts ou moins : mesuré -0,9 pt (environ -4 %)
ADJ_UNDERDOG = 1.04         # équipe outsider de 8 pts ou plus : mesuré +1,8 pt (environ +8 %)
ADJ_PROPS_SURGE = 1.07      # props à +20 % ou plus de l'historique : mesuré +3,4 à +3,9 pts (environ +15 %)
# Forfait tardif (mesuré le 23/11) : un joueur sans info du jour (pas de compo RotoWire, aucun blessé
# signalé) peut encore être déclaré forfait avant son match. Sur 285 joueurs du lendemain projetés
# 25 pts ou plus et sûrs au moment où l'équipe se figeait, 8 n'ont pas joué (2,8 %). Dans les
# meilleures équipes, 3 forfaits de ce type en 10 soirs (Kessler 16/11, Smith 19/11, Towns 20/11).
LATE_NEWS_OUT = 0.03
# Irrégularité de chaque joueur rapprochée de moitié de la moyenne (mesuré le 24/11 sur 1 130 joueurs rejoués) :
# estimée sur 15 matchs, elle exagérait les écarts (réguliers prévus ±35 %, réels ±38 % ; irréguliers prévus ±77 %,
# réels ±60 %). Avec ce rapprochement, chaque tiers retombe près de 10 % au-dessus du 90e centile et sous le 10e.
VOL_MEAN = 0.434   # irrégularité moyenne : hypot(écart-type du rendement / rendement, écart-type des minutes / minutes)
VOL_SHRINK = 0.5


def vol_factor(pl):
    """Coefficient appliqué à l'écart d'un tirage à la projection, pour rapprocher l'irrégularité du joueur de la moyenne."""
    if not pl.get("rates") or not pl.get("rate") or not pl.get("est_min"):
        return 1.0
    sd_rate = (sum((r - pl["rate"]) ** 2 for r in pl["rates"]) / len(pl["rates"])) ** 0.5
    v = (((sd_rate / pl["rate"]) ** 2 + (pl["sd_min"] / max(1, pl["est_min"])) ** 2) ** 0.5)
    return (VOL_MEAN + VOL_SHRINK * (v - VOL_MEAN)) / v if v > 0 else 1.0
# Testé et écarté le 16/11 : un aléa commun aux joueurs d'un même match.
# Corrélation des surprises entre coéquipiers -0,03 (1 193 paires), entre adversaires -0,03.
# -------------------------------------------------------------------------


def sorare_score(g: dict) -> float:
    """Barème Sorare NBA confirmé par l'utilisateur."""
    pts, reb, ast = g["points"] or 0, g["rebounds"] or 0, g["assists"] or 0
    stl, blk, tov, tpm = g["steals"] or 0, g["blocks"] or 0, g["turnovers"] or 0, g["threePointsMade"] or 0
    tens = sum(x >= 10 for x in (pts, reb, ast, stl, blk))
    return (pts + tpm + 1.2 * reb + 1.5 * ast + 3 * stl + 3 * blk - 2 * tov
            + (1 if tens >= 2 else 0) + (1 if tens >= 3 else 0))


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def role_of(median_min: float) -> str:
    return "titulaire" if median_min >= 28 else "remplaçant" if median_min <= 20 else "milieu"


def build_player(p, games_hist, bonus, edition, game, lineup, inj_espn, now_utc):
    """Fiche d'un joueur pour son match dans la fenêtre. None si inexploitable."""
    played = [g for g in games_hist if (g.get("minsPlayed") or 0) > 0]
    if len(played) < 3:
        return None
    mins = [g["minsPlayed"] for g in played]
    scores = [sorare_score(g) for g in played]
    rates = [s / m for s, m in zip(scores, mins) if m >= 8]
    if not rates:
        return None
    usual = st.median(mins[:10])
    recent = st.mean(mins[:5])
    team = (p.get("activeClub") or {}).get("code")
    key = norm(p["displayName"])
    reasons = []

    # Probabilité de jouer : RotoWire (soir même) > ESPN > Sorare.
    starter = mnp = None
    if lineup:
        starter = next((x for x in lineup["starters"] if norm(x["name"]) == key), None)
        mnp = next((x for x in lineup["may_not_play"] if norm(x["name"]) == key), None)
    e = inj_espn.get(p["displayName"])
    if mnp and (mnp["inj"] or "").lower() in ("out", "ofs"):
        pct, pct_src = 0.0, f"RotoWire : {mnp['inj']} ce soir"
        reasons.append(f"RotoWire {mnp['inj']}")
    elif (mnp or starter) and (mnp or starter)["pct_play"] is not None:
        x = mnp or starter
        pct = x["pct_play"]
        pct_src = (f"RotoWire : {'titulaire probable' if starter else 'incertain'}"
                   f"{' (' + x['inj'] + ')' if x['inj'] else ''}, probabilité affichée {pct:.0%}")
    elif mnp:
        pct = P_PLAY_ROTOWIRE.get((mnp["inj"] or "").lower(), 0.5)
        pct_src = f"RotoWire : {mnp['inj']}, converti en {pct:.0%} (hypothèse)"
        reasons.append(f"RotoWire {mnp['inj']}")
    elif e and e["status"] == "Out":
        pct, pct_src = 0.0, f"ESPN : Out. {e['detail']}"
        reasons.append("ESPN Out")
    elif e and e["status"] == "Day-To-Day":
        pct, pct_src = P_PLAY_DAY_TO_DAY, f"ESPN : Day-To-Day, compté {P_PLAY_DAY_TO_DAY:.0%} (hypothèse). {e['detail']}"
        reasons.append("ESPN Day-To-Day")
    elif any(i["status"] == "OUT" for i in p.get("activeInjuries") or []):
        pct, pct_src = 0.0, "Sorare : blessure OUT"
        reasons.append("Sorare OUT")
    else:
        pct = 1.0
        pct_src = ("Aucune blessure signalée (RotoWire, ESPN, Sorare)" if not lineup
                   else "Pas dans la liste des incertains RotoWire, ni blessé chez ESPN")
        # Fin de banc : même en bonne santé, il ne rentre pas à chaque match.
        # Mesuré le 12/11 : taux d'apparition récent 56 %, ont joué 55 %.
        recent_games = [g for g in games_hist
                        if (g.get("basketballGame") or {}).get("statusTyped") == "played"][:10]
        if not starter and usual < BENCH_MAX_USUAL_MIN and recent_games:
            seen = sum((g.get("minsPlayed") or 0) > 0 for g in recent_games)
            if seen < len(recent_games):
                pct = BENCH_PCT_A + BENCH_PCT_B * seen / len(recent_games)
                pct_src += (f". Fin de banc : entré en jeu {seen} fois sur ses {len(recent_games)} derniers matchs, "
                            f"compté {pct:.0%} (recalé sur nos bilans)")
                reasons.append(f"banc, joue {pct:.0%} des matchs")
        if pct >= 1 and not lineup:
            pct = 1 - LATE_NEWS_OUT
            pct_src += f". Pas encore de compo du jour : {LATE_NEWS_OUT:.0%} de risque de forfait tardif (mesuré)"

    promoted = bool(starter) and usual < PROMO_MAX_USUAL_MIN
    top3 = st.mean(sorted(mins, reverse=True)[:3])
    est_min = max(recent, top3) if promoted else recent
    if promoted:
        reasons.append("PROMU titulaire")
        min_rule = (f"Titulaire ce soir (RotoWire) alors qu'il joue d'habitude {usual:g} min : "
                    f"moyenne de ses 3 matchs les plus longs ({top3:.1f} min)")
    else:
        min_rule = f"Moyenne de ses 5 derniers matchs joués ({recent:.1f} min ; médiane sur 10 : {usual:g} min)"

    tip = datetime.fromisoformat(game["tip_utc"].replace("Z", "+00:00"))
    last = datetime.fromisoformat(played[0]["basketballGame"]["date"].replace("Z", "+00:00"))
    prev_tip = last if last < tip else None
    b2b = prev_tip is not None and (tip - prev_tip) < timedelta(hours=30)
    if b2b:
        reasons.append("back-to-back")

    # Production par minute de chaque composante, pour compléter les props.
    tot_min = sum(g["minsPlayed"] for g in played[:10])
    comp = {k: sum((g[f] or 0) for g in played[:10]) / tot_min for k, f in (
        ("pts", "points"), ("reb", "rebounds"), ("ast", "assists"), ("tpm", "threePointsMade"),
        ("stl", "steals"), ("blk", "blocks"), ("tov", "turnovers"))}

    home = game["home"] == team
    return {
        "comp_rates": comp,
        "slug": p["slug"], "name": p["displayName"], "team": team,
        "sorare_proj": p.get("nextClassicFixtureProjectedScore"),  # projection officielle Sorare, pour comparer
        "l10_sorare": p.get("l10"),  # moyenne officielle des 10 derniers matchs joués (missions)
        "opp": game["away"] if home else game["home"], "home": home,
        "night": game["night"], "tip_utc": game["tip_utc"], "game_key": f"{game['away']}@{game['home']}:{game['night']}",
        "stars": float(p["setStars"]), "bonus": bonus, "edition": edition,
        "pct": pct, "starter": bool(starter), "promoted": promoted, "b2b": b2b,
        "role": role_of(usual), "usual_min": usual, "est_min": est_min,
        "sd_min": max(MIN_SD_FLOOR, st.pstdev(mins[:10])),
        "rates": rates, "rate": st.mean(rates), "l5": st.mean(scores[:5]),
        "reasons": reasons, "pct_src": pct_src, "min_rule": min_rule,
        "last": [{"d": g["basketballGame"]["date"][:10], "min": g["minsPlayed"], "s": round(sc, 1)}
                 for g, sc in zip(played, scores)],
    }


def game_context(game, calib):
    """Points attendus de chaque équipe et spread, avec repli neutre si pas de cotes."""
    league = calib["league_team_pts"]
    total = game.get("total") or DEFAULT_TOTAL or 2 * league
    spread_home = game.get("spread_home")
    sh = spread_home if spread_home is not None else 0.0
    # spread_home négatif = domicile favori de |spread| points.
    home_pts = total / 2 - sh / 2
    away_pts = total / 2 + sh / 2
    return {"total": total, "spread_home": sh, "has_odds": spread_home is not None,
            "home_pts": home_pts, "away_pts": away_pts}


def context_factors(pl, ctx, calib):
    """(rythme, blowout) : multiplicateurs moyens appliqués au score historique."""
    team_pts = ctx["home_pts"] if pl["home"] else ctx["away_pts"]
    pace = 1 + calib["pace_slope"] * (team_pts / calib["league_team_pts"] - 1)
    # Minutes moyennes sur la distribution de l'écart final.
    ratios = calib["minutes"][pl["role"]]
    acc, n = 0.0, 4000
    rng = random.Random(1)
    for _ in range(n):
        m = abs(rng.gauss(-ctx["spread_home"], SIGMA_MARGIN))
        acc += ratios[_bucket(m, calib)]
    return pace, acc / n


def expected_score(pl, ctx, calib):
    """Score moyen attendu (bonus compris) au centre de la simulation."""
    pace, blow = context_factors(pl, ctx, calib)
    return pl["rate"] * pace * pl["est_min"] * blow * (1 + pl["bonus"])


WEIGHTS = {"pts": 1, "tpm": 1, "reb": 1.2, "ast": 1.5, "stl": 3, "blk": 3, "tov": -2}
LABELS = {"pts": "Points", "tpm": "Paniers à 3 pts", "reb": "Rebonds", "ast": "Passes",
          "stl": "Interceptions", "blk": "Contres", "tov": "Balles perdues"}


def breakdown(pl, prop_stats, prop_lines, book="Bovada"):
    """Estimation stat par stat, avec sa source. prop_stats/prop_lines peuvent être vides."""
    comps = []
    for k in ("pts", "tpm", "reb", "ast", "stl", "blk", "tov"):
        rate = pl["comp_rates"][k]
        if k in prop_stats:
            val = prop_stats[k]
            lines = [{"h": h, "p": round(p, 3), "over": o, "under": u} for h, p, o, u in sorted(prop_lines[k])]
            src = book
        else:
            val = rate * pl["est_min"]
            lines = []
            src = f"historique : {rate:.2f} par min x {pl['est_min']:.1f} min"
        comps.append({"k": k, "label": LABELS[k], "val": round(val, 2), "w": WEIGHTS[k],
                      "pts": round(val * WEIGHTS[k], 1), "src": src, "lines": lines})
    return comps


def _bucket(margin, calib):
    for i, (lo, hi) in enumerate(calib["buckets"]):
        if lo <= margin < hi:
            return i
    return len(calib["buckets"]) - 1


def widen(x, pl):
    """Écarte le tirage x de la projection : plus vers le haut que vers le bas."""
    c = pl["exp"]
    if c <= 0:
        return x
    up, dn = DISP_PROPS if pl.get("uses_props") else DISP_HIST
    d = (x / c - 1) * pl.get("vol_k", 1.0)
    return c * (1 + (up if d > 0 else dn) * d)


def upside(pl, n=2000, seed=11):
    """Chance de faire 1,4 fois sa projection ou plus, d'après la simulation élargie
    (minutes et production tirées au sort, sans l'effet blowout)."""
    rng = random.Random(seed)
    if pl["exp"] <= 0:
        return 0.0
    hits = 0
    for _ in range(n):
        m = min(48.0, max(0.0, rng.gauss(pl["est_min"], pl["sd_min"])))
        x = rng.choice(pl["rates"]) / pl["rate"] * m / pl["est_min"] * pl["exp"] if pl["est_min"] > 0 else 0.0
        hits += widen(x, pl) >= 1.4 * pl["exp"]
    return hits / n


def simulate_team(team, contexts, calib, targets, n_sim, rng):
    """Probabilité d'atteindre chaque cible. Un tirage d'écart final par match,
    partagé par les joueurs du même match (d'où la corrélation)."""
    hits = {t: 0 for t in targets}
    totals = []
    games = {pl["game_key"] for pl in team}
    league = calib["league_team_pts"]
    for _ in range(n_sim):
        margin = {g: abs(rng.gauss(-contexts[g]["spread_home"], SIGMA_MARGIN)) for g in games}
        total = 0.0
        for pl in team:
            if rng.random() > pl["pct"]:
                continue
            ctx = contexts[pl["game_key"]]
            team_pts = ctx["home_pts"] if pl["home"] else ctx["away_pts"]
            pace = 1 + calib["pace_slope"] * (team_pts / league - 1)
            ratio = calib["minutes"][pl["role"]][_bucket(margin[pl["game_key"]], calib)]
            m = min(48.0, max(0.0, rng.gauss(pl["est_min"] * ratio, pl["sd_min"])))
            x = rng.choice(pl["rates"]) * pace * m * (1 + pl["bonus"]) * pl.get("scale", 1.0)
            total += widen(x, pl) * pl.get("team_k", 1.0)
        total += calib.get("team_offset", 0.0)
        totals.append(total)
        for t in targets:
            hits[t] += total >= t
    out = {t: hits[t] / n_sim for t in targets}
    totals.sort()
    out["p90"] = totals[int(0.9 * (len(totals) - 1))]  # plafond : 1 chance sur 10 de faire mieux
    return out


def now_utc():
    return datetime.now(timezone.utc)
