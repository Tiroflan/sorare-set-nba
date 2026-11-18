"""Ce qu'on peut conclure, statistiquement, de tout ce que le journal a vu.

Chaque question ouverte est testée avec les bilans des soirs joués : un écart
mesuré, divisé par l'écart qu'on attendrait par simple hasard, donne un score z.
  |z| < 1,5        trop tôt : rien qu'on ne puisse expliquer par le hasard
  1,5 <= |z| < 2,5 tendance : à surveiller, pas encore prouvé
  |z| >= 2,5       on peut conclure (moins d'environ 1 chance sur 80 que ce soit le hasard)
Le seuil de 2,5 (au lieu des 2 habituels) tient compte du nombre de questions
testées en même temps : avec une dizaine de tests, un z de 2 finit par sortir
par hasard sur l'un d'eux.

Quand une question n'est pas tranchée, on estime combien de soirs il faudrait
encore si l'écart actuel se maintient (la précision croît comme la racine du
nombre d'observations).

Pour ne rien oublier : chaque question porte l'action à mener si elle se confirme.
Usage : python src/verdicts.py
"""

import json
import math
import statistics as st
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
J = ROOT / "journal"
SOLID, TREND = 2.5, 1.5
RECAL_DATE = "2026-11-16"  # premier soir projeté avec la simulation élargie
BENCH_RECAL = "2026-11-17"  # premier soir avec la chance de jouer des fins de banc recalée


def _load():
    nights = []
    for f in sorted(J.glob("bilan-*.json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        jf = J / f"{b['night']}.json"
        j = json.loads(jf.read_text(encoding="utf-8")) if jf.exists() else {"players": {}, "teams": None}
        nights.append((b, j))
    return nights


def _verdict(z):
    if z is None:
        return "trop tôt"
    a = abs(z)
    return "on peut conclure" if a >= SOLID else "tendance" if a >= TREND else "trop tôt"


def _remaining(z, n_obs, per_night):
    """Soirs encore nécessaires pour atteindre |z| = 2,5 si l'écart se maintient."""
    if z is None or abs(z) >= SOLID or per_night <= 0:
        return None
    if abs(z) < 0.3:
        return "rien de visible pour l'instant : pas d'écart à confirmer"
    need = n_obs * (SOLID / abs(z)) ** 2 - n_obs
    soirs = math.ceil(need / per_night)
    return f"environ {soirs} soir{'s' if soirs > 1 else ''} de plus si l'écart se maintient" if soirs <= 40 \
        else "plus de 40 soirs : l'écart est trop petit pour être tranché d'ici le 6 janvier"


def _item(key, question, chiffre, z, n_obs, per_night, action):
    return {"key": key, "question": question, "chiffre": chiffre, "z": None if z is None else round(z, 2),
            "verdict": _verdict(z), "reste": _remaining(z, n_obs, per_night), "action": action}


def _var(p):
    """Variance du score d'un joueur, chance de jouer comprise."""
    pct, e, sd = p.get("pct", 1), p.get("exp", 0), p.get("sd", 0)
    return pct * sd * sd + pct * (1 - pct) * e * e


TEAM_PRIOR_NIGHTS = 5  # le trou mesuré compte pour n / (n + 5) : moitié avec 5 soirs, 80 % avec 20


def team_offset():
    """Correction ajoutée au score des équipes dans la simulation : trou moyen des équipes
    proposées (réel - projeté, toutes les équipes complètes d'un soir, moyenné par soir),
    réduit tant qu'il y a peu de soirs. Se recalcule chaque nuit : si le trou n'était que
    de la malchance, la correction s'efface d'elle-même. Renvoie (correction, soirs, trou)."""
    nights = _load()
    actual = {(b["night"], r["slug"]): (r["actual"] or 0.0) for b, _ in nights for r in b["joueurs"]}
    per_night = []
    for b, j in nights:
        nxt = (date.fromisoformat(b["night"]) + timedelta(days=1)).isoformat()
        gaps = []
        for t in (j.get("teams") or {}).get("list") or []:
            pts = [actual.get((b["night"], s), actual.get((nxt, s))) for s in t["slugs"]]
            if None not in pts:
                gaps.append(sum(pts) - t["mu"])
        if gaps:
            per_night.append(st.mean(gaps))
    if not per_night:
        return 0.0, 0, 0.0
    n, gap = len(per_night), st.mean(per_night)
    return gap * n / (n + TEAM_PRIOR_NIGHTS), n, gap


def compute():
    nights = _load()
    out = []
    played = [(b["night"], r, j["players"].get(r["slug"], {})) for b, j in nights for r in b["joueurs"]
              if r["played"] and r.get("actual") is not None]
    n_nights = max(1, len(nights))
    per_night = len(played) / n_nights

    # 1. Équipes proposées : la mieux classée pour 240 de chaque soir (une par soir, indépendantes).
    actual = {(b["night"], r["slug"]): (r["actual"] or 0.0) for b, _ in nights for r in b["joueurs"]}
    jall = {b["night"]: j for b, j in nights}
    zs, gaps = [], []
    for b, j in nights:
        teams = (j.get("teams") or {}).get("list") or []
        if not teams:
            continue
        t = max(teams, key=lambda t: t["p"]["240"])
        nxt = (date.fromisoformat(b["night"]) + timedelta(days=1)).isoformat()
        jn = jall.get(nxt)
        pts, var, ok = 0.0, 0.0, True
        for s in t["slugs"]:
            if (b["night"], s) in actual:
                pts += actual[(b["night"], s)]
                var += _var(j["players"].get(s, {}))
            elif jn and (nxt, s) in actual:
                pts += actual[(nxt, s)]
                var += _var(jn["players"].get(s, {}))
            else:
                ok = False
        if ok and var > 0:
            zs.append((pts - t["mu"]) / math.sqrt(var))
            gaps.append(pts - t["mu"])
    z = sum(zs) / math.sqrt(len(zs)) if zs else None
    out.append(_item(
        "equipes", "Les équipes proposées font-elles leur projection ?",
        f"meilleure équipe de chaque soir : {st.mean(gaps):+.0f} pts en moyenne sur {len(gaps)} soirs "
        f"({sum(g < 0 for g in gaps)} sous la projection)" if gaps else "pas encore de soir complet",
        z, len(zs), 1,
        "chercher quels joueurs ou quel type de projection l'optimiseur surestime, puis corriger le choix des équipes"))

    # 2. Fourchette depuis l'élargissement : 68 % des joueurs dans ±1 écart-type.
    rec = [(r, p) for n, r, p in played if n >= RECAL_DATE and p.get("sd", 0) > 0]
    if rec:
        k = sum(abs(r["actual"] - p["exp"]) <= p["sd"] for r, p in rec)
        frac = k / len(rec)
        z = (frac - 0.68) / math.sqrt(0.68 * 0.32 / len(rec))
        out.append(_item(
            "fourchette", "La fourchette ±1 écart-type est-elle bien réglée (68 %) ?",
            f"{frac:.0%} dans la fourchette sur {len(rec)} joueurs depuis le {RECAL_DATE[8:]}/{RECAL_DATE[5:7]}",
            z, len(rec), len(rec) / max(1, len({n for n, _, _ in played if n >= RECAL_DATE})),
            "relancer python src/calib_check.py sur les soirs depuis le recalage et réajuster DISP_PROPS, DISP_HIST, SD_WIDEN"))

    # 3. Biais global : les projections sont-elles trop basses ou trop hautes ?
    d = [r["actual"] - p["exp"] for _, r, p in played if "exp" in p]
    if len(d) > 2:
        z = st.mean(d) / (st.stdev(d) / math.sqrt(len(d)))
        out.append(_item(
            "biais", "Nos projections sont-elles trop basses ou trop hautes en moyenne ?",
            f"{st.mean(d):+.1f} pt par joueur sur {len(d)} joueurs", z, len(d), per_night,
            "corriger le niveau moyen des projections (par source : props ou historique)"))

    # 4. Props contre historique (mêmes joueurs).
    pr = [abs(r["actual"] - p["hist"]) - abs(r["actual"] - p["exp"]) for _, r, p in played
          if p.get("usesProps") and "hist" in p]
    if len(pr) > 2:
        z = st.mean(pr) / (st.stdev(pr) / math.sqrt(len(pr)))
        out.append(_item(
            "props", "Les props des bookmakers font-elles mieux que l'historique ?",
            f"props plus proches du réel de {st.mean(pr):.2f} pt en moyenne sur {len(pr)} joueurs",
            z, len(pr), len(pr) / n_nights, "rien à changer si oui (on les utilise déjà) ; si non, revoir leur conversion"))

    # 5. Grosses projections sans props (le cas Gafford, Hyland).
    big = [(r["actual"] - p["exp"], p) for _, r, p in played if not p.get("usesProps") and p.get("exp", 0) >= 25]
    if len(big) > 2:
        z = sum(x for x, _ in big) / math.sqrt(sum(p["sd"] ** 2 for _, p in big))
        out.append(_item(
            "hist25", "Les projections de 25 pts ou plus sans props sont-elles trop hautes ?",
            f"{st.mean(x for x, _ in big):+.1f} pts en moyenne sur {len(big)} joueurs", z, len(big), len(big) / n_nights,
            "rabaisser ces projections (souvent des remplaçants promus estimés sur leurs meilleurs matchs)"))

    # 6. Chance de jouer des incertains (moins de 70 %).
    unc = [r for b, _ in nights if b["night"] >= BENCH_RECAL for r in b["joueurs"] if 0 < r["pct"] < 0.7]
    if not unc:
        out.append(_item("presence", "La chance de jouer des incertains est-elle juste ?",
                         "règle des fins de banc recalée le 17/11 : pas encore de soir joué avec la nouvelle règle", None, 0, 1,
                         "réajuster BENCH_PCT_A et BENCH_PCT_B"))
    if unc:
        exp_ = sum(r["pct"] for r in unc)
        obs = sum(bool(r["played"]) for r in unc)
        z = (obs - exp_) / math.sqrt(sum(r["pct"] * (1 - r["pct"]) for r in unc))
        out.append(_item(
            "presence", "La chance de jouer des incertains est-elle juste ?",
            f"{exp_ / len(unc):.0%} prévu, {obs / len(unc):.0%} ont joué ({len(unc)} joueurs)", z, len(unc),
            len(unc) / n_nights, "réajuster BENCH_PCT_A et BENCH_PCT_B (recalage des fins de banc du 17/11)"))

    # 7. Rythme : les joueurs à l'historique des matchs rapides et lents sont-ils bien dosés ?
    fast, slow = [], []
    for _, r, p in played:
        if p.get("usesProps") or not p.get("sd") or "pace" not in p:
            continue
        zz = (r["actual"] - p["exp"]) / p["sd"]
        (fast if p["pace"] > 1.03 else slow if p["pace"] < 0.97 else []).append(zz)
    if len(fast) > 2 and len(slow) > 2:
        z = (st.mean(fast) - st.mean(slow)) / math.sqrt(1 / len(fast) + 1 / len(slow))
        out.append(_item(
            "rythme", "L'effet rythme est-il bien dosé (matchs rapides contre lents) ?",
            f"écart réduit {st.mean(fast):+.2f} en match rapide ({len(fast)} joueurs), {st.mean(slow):+.2f} en match lent ({len(slow)})",
            z, len(fast) + len(slow), (len(fast) + len(slow)) / n_nights,
            "les matchs rapides font mieux que prévu par rapport aux lents : augmenter la pente du rythme (pace_slope)" if z > 0
            else "les matchs lents font mieux que prévu par rapport aux rapides : réduire la pente du rythme (pace_slope)"))

    # 8. Tag explosif : les joueurs repérés font-ils plus souvent +12 pts ?
    tag, oth = [], []
    for _, r, p in played:
        if "upside" in p and p.get("exp", 0) >= 15:
            (tag if p["upside"] >= 0.28 else oth).append(r["actual"] - p["exp"] >= 12)
    if tag and oth:
        p1, p2 = sum(tag) / len(tag), sum(oth) / len(oth)
        pp = (sum(tag) + sum(oth)) / (len(tag) + len(oth))
        se = math.sqrt(pp * (1 - pp) * (1 / len(tag) + 1 / len(oth))) or 1
        z = (p1 - p2) / se
        out.append(_item(
            "explosif", "Le tag explosif repère-t-il vraiment les grosses soirées ?",
            f"+12 pts ou plus : {p1:.0%} des tagués ({len(tag)}) contre {p2:.0%} des autres ({len(oth)}), depuis le 16/11",
            z, len(tag), len(tag) / max(1, len({n for n, _, p in played if 'upside' in p})),
            "garder le tag" if z > 0 else "retirer le tag, qui repère l'inverse de ce qu'il promet (la simulation, elle, est réglée à part)"))

    # 9. Nos estimations de match (sans cotes) contre les vraies cotes, sur l'écart final.
    gl = [x for b, _ in nights for x in (b.get("matchs") or {}).get("lignes", [])
          if x.get("est") and x.get("odds") and x.get("real_spread") is not None]
    if len(gl) > 2:
        dd = [abs(x["est"]["spread_home"] - x["real_spread"]) - abs(x["odds"]["spread_home"] - x["real_spread"]) for x in gl]
        z = st.mean(dd) / (st.stdev(dd) / math.sqrt(len(dd)))
        out.append(_item(
            "matchs", "Nos estimations de match font-elles aussi bien que les bookmakers ?",
            f"sur l'écart final, {st.mean(dd):+.1f} pt d'erreur en plus que les cotes ({len(dd)} matchs)",
            z, len(dd), len(dd) / max(1, len({b['night'] for b, _ in nights if (b.get('matchs') or {}).get('lignes')})),
            "si nettement moins bien : se méfier des soirs sans cotes (baisser leurs chances affichées)"))
    return out


# Chantiers décidés ou proposés, hors statistiques, pour ne pas les perdre de vue.
A_FAIRE = [
    "Titulaire qui revient le soir même : rabaisser les minutes du remplaçant qui a joué gros pendant son absence "
    "(proposé le 16/11, à faire)",
    "Recaler les projections sur l'historique (réel = 4,3 + 0,83 x prévu au 16/11) : reporté par Romain le 16/11",
    "Équipes surestimées (établi le 18/11) : le diagnostic donne 2,5 pts sur 23 dus à la sélection (pente 0,87 dans un "
    "niveau d'étoiles), le reste aux mêmes stars présentes partout (Wembanyama -8 pts par équipe à lui seul). "
    "Correction appliquée le 18/11 (TEAM_SHRINK et team_offset) : à réévaluer quand le verdict « équipes » "
    "aura 10 soirs depuis le 18/11 ; si le trou disparaît, la correction s'efface d'elle-même",
]


def show(items):
    print("## Ce qu'on peut conclure (statistiquement)\n")
    for it in items:
        print(f"- **{it['question']}** {it['verdict']} (z = {it['z']}) : {it['chiffre']}."
              + (f" Reste : {it['reste']}." if it["reste"] else "")
              + (f" Si confirmé : {it['action']}." if it["verdict"] != "trop tôt" else ""))
    print("\nz mesure l'écart en nombre d'« écarts de hasard » : 2,5 ou plus = conclusion, 1,5 à 2,5 = tendance.")
    print("\n**Chantiers en attente**")
    for a in A_FAIRE:
        print(f"- {a}")


if __name__ == "__main__":
    show(compute())
