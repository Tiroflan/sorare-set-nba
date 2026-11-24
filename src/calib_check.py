"""Banc d'essai de la simulation sur le journal des soirs joués.

Pour chaque joueur projeté puis entré en jeu, on refait sa simulation avec
uniquement les matchs connus avant le coup d'envoi, et on regarde où tombe son
vrai score dans la distribution simulée (rang entre 0 et 1). Si la simulation
est juste, ce rang est uniforme : 10 % des joueurs sous le 10e centile, 10 %
au-dessus du 90e, 68 % dans la bande centrale.

Sert à régler l'élargissement de la simulation (DISP_PROPS, DISP_HIST dans
model.py) à mesure que le journal grossit.

Usage : python src/calib_check.py
"""

import json
import random
import statistics as st
from pathlib import Path

from model import DISP_HIST, DISP_PROPS, sorare_score

ROOT = Path(__file__).resolve().parent.parent
N = 3000


def _ts(iso):
    """Dates comparées en vrai : en texte, « 18:00:00Z » passait avant « 18:00Z » et le match
    lui-même entrait dans l'historique d'avant-match (corrigé le 24/11)."""
    from datetime import datetime
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def cases():
    """Joueurs entrés en jeu, avec ce que le modèle savait au moment de la projection."""
    hist = json.loads((ROOT / "data" / "history.json").read_text(encoding="utf-8"))
    out = []
    for f in sorted((ROOT / "journal").glob("bilan-*.json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        j = json.loads((ROOT / "journal" / f"{b['night']}.json").read_text(encoding="utf-8"))["players"]
        for r in b["joueurs"]:
            p = j.get(r["slug"])
            if not r["played"] or not p or r["actual"] is None:
                continue
            games = [g for g in hist.get(r["slug"], {}).get("games", [])
                     if (g.get("minsPlayed") or 0) > 0 and _ts(g["basketballGame"]["date"]) < _ts(r["tip"])]
            rates = [sorare_score(g) / g["minsPlayed"] for g in games if g["minsPlayed"] >= 8]
            if len(rates) < 3 or not p["estMin"]:
                continue
            out.append({"name": r["name"], "night": b["night"], "exp": p["exp"], "actual": r["actual"],
                        "est_min": p["estMin"], "sd_min": p["sdMin"], "blow": p.get("blow") or 1.0,
                        "rates": rates, "mins": [g["minsPlayed"] for g in games],
                        "props": p["usesProps"], "role": p["role"], "promoted": p.get("promoted"),
                        "starter": p.get("starter"), "pace": p.get("pace") or 1.0})
    return out


def sample(c, rng, disp=None):
    """Un tirage du score, centré sur la projection retenue (comme la simulation du soir).
    disp = ((haut, bas) avec props, (haut, bas) historique) ; None = réglage du modèle."""
    props, hist = disp or (DISP_PROPS, DISP_HIST)
    up, dn = props if c["props"] else hist
    mr = st.mean(c["rates"])
    m = min(48.0, max(0.0, rng.gauss(c["est_min"] * c["blow"], c["sd_min"])))
    d = (rng.choice(c["rates"]) / mr) * (m / (c["est_min"] * c["blow"])) - 1
    return c["exp"] * (1 + (up if d > 0 else dn) * d)


def ranks(cs, disp=None, seed=7):
    rng = random.Random(seed)
    out = []
    for c in cs:
        sims = [sample(c, rng, disp) for _ in range(N)]
        out.append(sum(s < c["actual"] for s in sims) / N)
    return out


def report(rk, label):
    n = len(rk)
    lo = sum(r < 0.1 for r in rk) / n
    hi = sum(r > 0.9 for r in rk) / n
    mid = sum(0.16 <= r <= 0.84 for r in rk) / n
    print(f"{label:28s} n={n}  sous le 10e centile {lo:5.1%}  au-dessus du 90e {hi:5.1%}  bande 68 % : {mid:5.1%}")


def main():
    cs = cases()
    print(f"{len(cs)} joueurs entrés en jeu, rejoués avec l'historique d'avant le match\n")
    report(ranks(cs, ((1, 1), (1, 1))), "sans élargissement")
    report(ranks(cs), f"réglage actuel {DISP_PROPS} / {DISP_HIST}")
    for lab, f in (("avec props", lambda c: c["props"]), ("historique", lambda c: not c["props"])):
        sub = [c for c in cs if f(c)]
        report(ranks(sub), f"  dont {lab}")


if __name__ == "__main__":
    main()
