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
BENCH_RECAL = "2026-11-24"  # premier soir avec la règle des fins de banc du 24/11 (mi-chemin)


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
    zs, gaps, split = [], [], []
    for b, j in nights:
        teams = (j.get("teams") or {}).get("list") or []
        if not teams:
            continue
        t = max(teams, key=lambda t: t["p"]["240"])
        nxt = (date.fromisoformat(b["night"]) + timedelta(days=1)).isoformat()
        jn = jall.get(nxt)
        pts, var, fin, ok = 0.0, 0.0, 0.0, True
        for s in t["slugs"]:
            if (b["night"], s) in actual:
                p = j["players"].get(s, {})
                pts += actual[(b["night"], s)]
            elif jn and (nxt, s) in actual:
                p = jn["players"].get(s, {})
                pts += actual[(nxt, s)]
            else:
                ok = False
                continue
            var += _var(p)
            fin += p.get("exp", 0) * p.get("pct", 1)
        if ok and var > 0:
            zs.append((pts - t["mu"]) / math.sqrt(var))
            gaps.append(pts - t["mu"])
            if b["night"] >= "2026-11-18":
                split.append((pts - fin, fin - t["mu"]))
    z = sum(zs) / math.sqrt(len(zs)) if zs else None
    # Découpage (diagnostic du 23/11, src/diag_equipes.py) : joueurs sous leur dernière projection,
    # ou projection revue à la baisse entre le choix et le match (forfait, props plus basses).
    detail = (f" ; depuis la correction du 18/11 ({len(split)} soirs) : {st.mean(a for a, _ in split):+.0f} pts "
              f"de joueurs sous leur dernière projection et {st.mean(g for _, g in split):+.0f} pts de forfaits "
              f"et de projections revues à la baisse après le choix") if split else ""
    out.append(_item(
        "equipes", "Les équipes proposées font-elles leur projection ?",
        f"meilleure équipe de chaque soir : {st.mean(gaps):+.0f} pts en moyenne sur {len(gaps)} soirs "
        f"({sum(g < 0 for g in gaps)} sous la projection){detail}" if gaps else "pas encore de soir complet",
        z, len(zs), 1,
        "relancer python src/diag_equipes.py : si les joueurs sont sous leur dernière projection, renforcer "
        "TEAM_SHRINK ; si ce sont les forfaits après le choix, revoir LATE_NEWS_OUT"))

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

    # 4 bis. Quand les props dépassent nettement l'historique (+20 % ou plus), les bookmakers
    # voient-ils encore trop court ? (intuition de Romain, cas Henderson +43 % le 19/11)
    hi = [(r["actual"] - p["exp"], p) for _, r, p in played
          if p.get("usesProps") and p.get("hist", 0) > 0 and p["exp"] >= 1.2 * p["hist"]]
    if len(hi) > 2:
        d = [x for x, _ in hi]
        z = st.mean(d) / (st.stdev(d) / math.sqrt(len(d)))
        out.append(_item(
            "props_hausse", "Quand les props dépassent l'historique de 20 % ou plus, faut-il viser encore plus haut ?",
            f"ces joueurs font {st.mean(d):+.1f} pts de plus que les props ({len(d)} joueurs)", z, len(d), len(d) / n_nights,
            "(moitié appliquée depuis le 24/11 : ADJ_PROPS_SURGE) passer à l'effet plein" if z > 0
            else "retirer ADJ_PROPS_SURGE (appliqué depuis le 24/11)"))

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
                         "règle des fins de banc revue le 24/11 : pas encore de soir joué avec la nouvelle règle", None, 0, 1,
                         "réajuster BENCH_PCT_A et BENCH_PCT_B"))
    if unc:
        exp_ = sum(r["pct"] for r in unc)
        obs = sum(bool(r["played"]) for r in unc)
        z = (obs - exp_) / math.sqrt(sum(r["pct"] * (1 - r["pct"]) for r in unc))
        out.append(_item(
            "presence", "La chance de jouer des incertains est-elle juste ?",
            f"{exp_ / len(unc):.0%} prévu, {obs / len(unc):.0%} ont joué ({len(unc)} joueurs)", z, len(unc),
            len(unc) / n_nights, "réajuster BENCH_PCT_A et BENCH_PCT_B (règle des fins de banc du 24/11)"))

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

    # 10. Nous contre la projection officielle Sorare (enregistrée depuis le 18/11).
    vs = [(r, p) for _, r, p in played if p.get("sorare") is not None]
    if len(vs) > 2:
        dd = [abs(r["actual"] - p["sorare"] * (1 + p["bonus"])) - abs(r["actual"] - p["exp"]) for r, p in vs]
        z = st.mean(dd) / (st.stdev(dd) / math.sqrt(len(dd))) if st.stdev(dd) > 0 else None
        out.append(_item(
            "sorare", "Faisons-nous mieux que la projection officielle de Sorare ?",
            f"nous plus proches du réel de {st.mean(dd):+.2f} pt en moyenne ({sum(d > 0 for d in dd)} joueurs sur {len(dd)})",
            z, len(dd), len(dd) / max(1, len({n for n, _, p in played if p.get('sorare') is not None})),
            "on fait mieux : rien à changer" if (z or 0) > 0 else "Sorare fait mieux : chercher pourquoi et s'en servir comme repère"))
    else:
        out.append(_item("sorare", "Faisons-nous mieux que la projection officielle de Sorare ?",
                         "projection Sorare enregistrée depuis le 18/11 : premier bilan demain", None, 0, 1, ""))

    # 11 et 12. Pistes de l'analyse du 24/11 (« qu'est-ce qui annonce une explosion ? ») : matchs à petit
    # total et équipes très outsiders. Écart au projeté, en écarts-types, contre tous les autres joueurs.
    jg = {b["night"]: (j.get("games") or {}) for b, j in nights}
    def ctx(n, p):
        g = jg.get(n, {}).get((p.get("game") or "").split(":")[0], {})
        line = g.get("odds") or g.get("est") or {}
        sh = line.get("spread_home")
        home = (p.get("game") or "@").split(":")[0].split("@")[-1] == p.get("team")
        return line.get("total"), (None if sh is None else (sh if home else -sh))
    # Trouvées en fouillant 26 critères sur les nuits du 12 au 23/11 : jugées seulement sur les nuits suivantes,
    # qui n'ont pas servi à les trouver (sinon un z de 2,5 peut sortir par hasard).
    zz = [((r["actual"] - p["exp"]) / p["sd"], ctx(n, p)) for n, r, p in played if p.get("sd") and n >= "2026-11-24"]
    allz = [z_ for z_, _ in zz]
    for key, question, f, act in (
            ("petit_total", "Les joueurs des matchs à petit total (220 ou moins) font-ils moins que prévu ?",
             lambda c: c[0] is not None and c[0] <= 220, "(moitié appliquée depuis le 24/11 : ADJ_LOW_TOTAL) si l'écart reste négatif, passer à l'effet plein ; s'il s'inverse, retirer"),
            ("outsider", "Les joueurs d'une équipe outsider de 8 pts ou plus font-ils mieux que prévu ?",
             lambda c: c[1] is not None and c[1] >= 8, "(moitié appliquée depuis le 24/11 : ADJ_UNDERDOG) si l'écart reste positif, passer à l'effet plein ; s'il s'inverse, retirer")):
        g = [z_ for z_, c in zz if f(c)]
        o = [z_ for z_, c in zz if not f(c)]
        if len(g) <= 10 or len(o) <= 10:
            out.append(_item(key, question, "piste du 24/11 (sur les nuits passées : petit total -0,9 pt, z -2,6 ; outsider +1,8 pt, z +2,3), "
                             "à confirmer sur les nuits suivantes", None, 0, 1, act))
        else:
            z = (st.mean(g) - st.mean(o)) / math.sqrt(st.pvariance(allz) * (1 / len(g) + 1 / len(o)))
            out.append(_item(key, question, f"écart moyen {st.mean(g):+.2f} écart-type contre {st.mean(o):+.2f} pour les autres ({len(g)} joueurs)",
                             z, len(g), len(g) / n_nights, act))

    # 9. Nos estimations de match (sans cotes) contre les vraies cotes, sur l'écart final.
    gl = [x for b, _ in nights for x in (b.get("matchs") or {}).get("lignes", [])
          if x.get("est") and x.get("odds") and x.get("real_spread") is not None]
    if len(gl) > 2:
        per = len(gl) / max(1, len({b['night'] for b, _ in nights if (b.get('matchs') or {}).get('lignes')}))
        win = lambda sp, real: (sp < 0) == (real < 0)
        w_est = sum(win(x["est"]["spread_home"], x["real_spread"]) for x in gl)
        w_odd = sum(win(x["odds"]["spread_home"], x["real_spread"]) for x in gl)
        dd = [abs(x["est"]["spread_home"] - x["real_spread"]) - abs(x["odds"]["spread_home"] - x["real_spread"]) for x in gl]
        z = st.mean(dd) / (st.stdev(dd) / math.sqrt(len(dd)))
        out.append(_item(
            "matchs", "Nos estimations de match font-elles aussi bien que les bookmakers ?",
            f"sur l'écart final, {st.mean(dd):+.1f} pt d'erreur en plus que les cotes ({len(dd)} matchs) ; "
            f"vainqueur trouvé {w_est / len(gl):.0%} des fois, contre {w_odd / len(gl):.0%} pour les cotes",
            z, len(dd), per,
            "si nettement moins bien : se méfier des soirs sans cotes (baisser leurs chances affichées)"))
        dt = [abs(x["est"]["total"] - x["real_total"]) - abs(x["odds"]["total"] - x["real_total"]) for x in gl]
        zt = st.mean(dt) / (st.stdev(dt) / math.sqrt(len(dt)))
        out.append(_item(
            "matchs_total", "Notre total de points d'un match vaut-il celui des bookmakers ?",
            f"{st.mean(dt):+.1f} pt d'erreur en plus que les cotes ({len(dt)} matchs ; notre estimation date de la veille, "
            f"les cotes du coup d'envoi)", zt, len(dt), per,
            "rapprocher nos totaux de la moyenne de la ligue (SHRINK_GAMES plus grand dans team_ratings.py)" if zt > 0
            else "rien à changer"))

    # 11. Report de minutes : un titulaire (24 min ou plus d'habitude) absent ce soir alors qu'il jouait
    # au match d'avant. Ses coéquipiers projetés sur l'historique (sans props) font-ils mieux que prévu ?
    fresh = _fresh_absences(nights)
    if len(fresh) > 2:
        d = [x for x in fresh]
        z = st.mean(d) / (st.stdev(d) / math.sqrt(len(d)))
        out.append(_item(
            "report", "Quand un titulaire vient de se blesser, ses coéquipiers sans props font-ils mieux que prévu ?",
            f"{st.mean(d):+.1f} pts au-dessus de leur projection ({len(d)} joueurs, absences suivies depuis le 18/11)",
            z, len(d), len(d) / max(1, len({b['night'] for b, j in nights if j.get('absences')})),
            "coder le report : ajouter des minutes aux coéquipiers sans props (mesuré le 23/11 : +4,5 min en moyenne)"
            if z > 0 else "rien à faire : l'historique récent suffit"))
    # Banc d'essai face aux paris : affiché seulement une fois concluant (python src/verdicts.py --paris pour tout voir).
    out += [it for it in compute_paris(nights) if it["verdict"] == "on peut conclure"]
    return out


# ---------- Banc d'essai face aux paris (side project, décidé le 23/11) ----------
# Paris fictifs, 1 unité par pari, règles figées le 23/11 : ne pas les retoucher en cours de route.
# Cotes stockées dans le journal à partir du 24/11 (dernier passage avant chaque match). Point prévu vers le 23/12.
SIGMA_MARGIN = 12.0  # même valeur que model.SIGMA_MARGIN : écart final autour du spread
VALUE_EDGE = 0.03    # on ne parie que si notre proba x cote décimale dépasse 1,03
PROP_GAP = 0.15      # props : seulement si notre historique s'écarte de la ligne d'au moins 15 % (et 1 unité)


def _dec(american):
    a = 100.0 if str(american).upper() == "EVEN" else float(american)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def _implied(american):
    return 1 / _dec(american)


def compute_paris(nights=None):
    from statistics import NormalDist
    nights = nights if nights is not None else _load()
    out = []

    # Vainqueur : notre proba (estimation de la veille, sans cotes) contre celle de la cote Pinnacle.
    rows = []
    for b, _ in nights:
        for x in (b.get("matchs") or {}).get("lignes", []):
            o, e = x.get("odds") or {}, x.get("est") or {}
            if o.get("ml_home") is None or e.get("spread_home") is None or x.get("real_spread") in (None, 0):
                continue
            ih, ia = _implied(o["ml_home"]), _implied(o["ml_away"])
            rows.append((b["night"], NormalDist().cdf(-e["spread_home"] / SIGMA_MARGIN), ih / (ih + ia),
                         x["real_spread"] < 0, o["ml_home"], o["ml_away"]))
    if len(rows) > 2:
        d = [(pm - y) ** 2 - (po - y) ** 2 for _, po, pm, y, _, _ in rows]
        sd = st.stdev(d)
        z = st.mean(d) / (sd / math.sqrt(len(d))) if sd > 0 else None
        bets = []
        for _, po, _, y, mh, ma in rows:
            if po * _dec(mh) > 1 + VALUE_EDGE:
                bets.append(_dec(mh) - 1 if y else -1)
            elif (1 - po) * _dec(ma) > 1 + VALUE_EDGE:
                bets.append(_dec(ma) - 1 if not y else -1)
        b_our = st.mean((po - y) ** 2 for _, po, _, y, _, _ in rows)
        b_mkt = st.mean((pm - y) ** 2 for _, _, pm, y, _, _ in rows)
        roi = f", {sum(bets):+.1f} unités ({sum(bets) / len(bets):+.0%} par pari)" if bets else ""
        out.append(_item(
            "paris_vainqueur", "Notre probabilité de victoire bat-elle celle de la cote Pinnacle ?",
            f"erreur de probabilité (Brier, plus bas = mieux) : nous {b_our:.3f}, cote {b_mkt:.3f} sur {len(rows)} matchs ; "
            f"paris fictifs quand on voit {VALUE_EDGE:.0%} de valeur : {len(bets)} paris{roi}",
            z, len(rows), len(rows) / max(1, len({n for n, *_ in rows})),
            "nous faisons mieux que la cote : la question des paris sur le vainqueur se pose" if (z or 0) > 0
            else "la cote fait mieux : se fier aux cotes, pas de pari"))
    else:
        out.append(_item("paris_vainqueur", "Notre probabilité de victoire bat-elle celle de la cote Pinnacle ?",
                         "cotes de victoire stockées depuis le 24/11 : pas encore de match joué", None, 0, 1, ""))

    # Props : quand notre historique (ajusté rythme et blowout) s'écarte nettement de la ligne,
    # le côté qu'il désigne passe-t-il plus souvent que ne le dit la cote (marge retirée) ?
    hits, exp_, var, profit, n = 0, 0.0, 0.0, 0.0, 0
    nights_with = set()
    for b, j in nights:
        rows_b = {r["slug"]: r for r in b["joueurs"]}
        for slug, p in j["players"].items():
            r = rows_b.get(slug)
            if not p.get("lines") or not r or not r.get("played") or not r.get("min") or not r.get("stats"):
                continue
            for k, ls in p["lines"].items():
                hist, actual = (p.get("histComps") or {}).get(k), r["stats"].get(k)
                if hist is None or actual is None or not ls:
                    continue
                h, po, over, under = min(ls, key=lambda l: abs(l[1] - 0.5))  # ligne principale
                if abs(hist - h) < max(PROP_GAP * h, 1.0) or actual == h:
                    continue
                is_over = hist > h
                ps = po if is_over else 1 - po
                win = actual > h if is_over else actual < h
                hits += win
                exp_ += ps
                var += ps * (1 - ps)
                profit += _dec(over if is_over else under) - 1 if win else -1
                n += 1
                nights_with.add(b["night"])
    if n > 2:
        z = (hits - exp_) / math.sqrt(var)
        out.append(_item(
            "paris_props", "Quand notre historique s'écarte nettement des props, a-t-il raison contre la cote ?",
            f"côté désigné par l'historique gagnant {hits / n:.0%} des fois, la cote en promettait {exp_ / n:.0%} "
            f"({n} lignes, écart de {PROP_GAP:.0%} ou plus) ; paris fictifs : {profit:+.1f} unités ({profit / n:+.0%} par pari)",
            z, n, n / max(1, len(nights_with)),
            "l'historique voit quelque chose que la cote rate : s'en servir pour corriger les props dans Sorare, "
            "et la question des paris sur les props se pose" if z > 0
            else "la cote a raison : coller aux props, ne pas parier contre"))
    else:
        out.append(_item("paris_props", "Quand notre historique s'écarte nettement des props, a-t-il raison contre la cote ?",
                         "prix des props stockés depuis le 24/11 : pas encore de match joué", None, 0, 1, ""))
    return out


def _fresh_absences(nights):
    """Écarts réel - projection des joueurs sans props dont un titulaire vient de se déclarer absent."""
    usual, absn, played = {}, {}, set()
    for b, j in nights:
        for p in j["players"].values():
            usual[p["name"]] = max(usual.get(p["name"], 0), p.get("estMin", 0))
        played |= {(b["night"], r["name"]) for r in b["joueurs"] if r["played"]}
        if not j.get("absences"):
            continue
        for k in j.get("games") or {}:
            for t in k.split("@"):
                absn[(t, b["night"])] = set(j["absences"].get(t, []))
    by_team = {}
    for t, n in sorted(absn, key=lambda x: x[1]):
        by_team.setdefault(t, []).append(n)
    out = []
    for b, j in nights:
        n = b["night"]
        rows = {r["slug"]: r for r in b["joueurs"]}
        for t, ns in by_team.items():
            if n not in ns or ns.index(n) == 0:
                continue
            before = absn[(t, ns[ns.index(n) - 1])]
            new_out = {x for x in absn[(t, n)] - before if usual.get(x, 0) >= 24}
            back = {x for x in before - absn[(t, n)] if usual.get(x, 0) >= 24 and (n, x) in played}
            if not new_out or back:
                continue
            for s, p in j["players"].items():
                r = rows.get(s)
                if p["team"] == t and r and r["played"] and not p.get("usesProps") and p["pct"] > 0:
                    out.append(r["actual"] - p["exp"])
    return out


# Chantiers décidés ou proposés, hors statistiques, pour ne pas les perdre de vue.
# Échéancier (règles dans METHODE.md). Une échéance est due quand sa date est passée OU quand le verdict
# nommé atteint « on peut conclure ». Le jour venu, la routine du matin fait l'analyse décrite, écrit le
# résultat dans CONNAISSANCES.md, puis retire l'échéance d'ici ou la redate. Une correction du modèle qui
# en découle attend la passe du lundi (sauf bug).
ECHEANCES = [
    {"date": "2026-11-30", "verdict": None, "sujet": "Équipes surestimées : correction",
     "contexte": "diagnostic du 25/11 (12 soirs) : trou -32,3 pts par soir = joueurs -13,0 (biais de sélection : "
                 "choisis -1,78 pt contre leur projection, z -1,93, autres +0,72) + glissement -19,2 ; "
                 "LATE_NEWS_OUT 3 % n'a qu'un soir mesuré (23/11, glissement 0)",
     "analyse": "renforcer TEAM_SHRINK (0,87) : remesurer la pente sur les soirs depuis le 18/11 pour que les joueurs "
                "choisis tombent sur leur projection, appliquer si le test hors échantillon confirme ; relancer "
                "python src/diag_equipes.py et relire le glissement des soirs depuis le 23/11 avant de toucher "
                "LATE_NEWS_OUT (garder 3 % si trop peu de soirs)"},
    {"date": "2026-11-30", "verdict": None, "sujet": "Trois pistes appliquées à moitié le 24/11",
     "contexte": "petit total -2 %, outsider +4 %, élan props +7 % (model.py ADJ_*)",
     "analyse": "relire les verdicts props_hausse, petit total et outsider sur les nuits depuis le 24/11 : "
                "garder, pousser à l'effet plein ou retirer ; redater au lundi suivant si trop tôt"},
    {"date": "2026-12-05", "verdict": "explosif", "sujet": "Irrégularité rapprochée de la moyenne (VOL_SHRINK)",
     "contexte": "le tag explosif en dépend",
     "analyse": "si le verdict explosif ne fait toujours pas mieux que le hasard, retirer le tag"},
    {"date": None, "verdict": "report", "sujet": "Report de minutes après une blessure",
     "contexte": "mesuré le 23/11 : +4,5 min pour les coéquipiers sans props d'un titulaire qui vient de se blesser",
     "analyse": "coder le report de minutes"},
    {"date": "2026-12-23", "verdict": None, "sujet": "Banc d'essai face aux paris",
     "contexte": "règles figées le 23/11, ne pas les retoucher",
     "analyse": "python src/verdicts.py --paris : faire le point sur paris_vainqueur et paris_props"},
]


def _due(e, today, concluded):
    return (e["date"] is not None and e["date"] <= today) or (e["verdict"] in concluded)


def echeances(items=None, today=None):
    """Échéances dues aujourd'hui (date passée ou verdict tranché), puis les autres."""
    today = today or date.today().isoformat()
    concluded = {it["key"] for it in (items or []) if it["verdict"] == "on peut conclure"}
    due = [e for e in ECHEANCES if _due(e, today, concluded)]
    return due, [e for e in ECHEANCES if e not in due]


def _label(e):
    quand = []
    if e["date"]:
        quand.append(f"le {e['date'][8:]}/{e['date'][5:7]}")
    if e["verdict"]:
        quand.append(f"dès que le verdict « {e['verdict']} » est tranché")
    return f"{e['sujet']} ({' ou '.join(quand)}) : {e['analyse']}"


A_FAIRE = [_label(e) for e in ECHEANCES]  # lu par build_page.py
# Chantiers fermés, pour ne pas les rouvrir sans nouvelles données :
# - 23/11, titulaire qui revient : ses coéquipiers sans props ne font pas moins que prévu (22 joueurs, -0,2 min,
#   +0,5 pt). Pas de correction.
# - 23/11, recalage global des projections sur l'historique : testé hors échantillon (appris du 12 au 16/11, testé
#   sur 325 joueurs ensuite), pas de gain net (erreur moyenne 7,13 -> 7,32, écart quadratique 9,34 -> 9,28).
#   Le seul vrai défaut est la queue haute, suivie par le verdict « hist25 ».


def show(items):
    print("## Ce qu'on peut conclure (statistiquement)\n")
    for it in items:
        print(f"- **{it['question']}** {it['verdict']} (z = {it['z']}) : {it['chiffre']}."
              + (f" Reste : {it['reste']}." if it["reste"] else "")
              + (f" Si confirmé : {it['action']}." if it["verdict"] != "trop tôt" else ""))
    print("\nz mesure l'écart en nombre d'« écarts de hasard » : 2,5 ou plus = conclusion, 1,5 à 2,5 = tendance.")
    due, later = echeances(items)
    if due:
        print("\n**Échéances dues : analyse à faire maintenant**")
        for e in due:
            print(f"- {_label(e)}. Contexte : {e['contexte']}")
    print("\n**Échéancier**")
    for e in later:
        print(f"- {_label(e)}")


if __name__ == "__main__":
    import sys
    show(compute_paris() if "--paris" in sys.argv else compute())
