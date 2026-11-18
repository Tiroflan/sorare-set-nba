"""Combien d'équipes jouer en parallèle ce soir, selon le palier et les vies restantes.

Règles du Set (confirmées par Romain le 16 et le 18/11) : 4 tentatives par palier,
plusieurs équipes en parallèle possibles (sans carte commune), chaque équipe ratée
coûte une vie, 4 échecs renvoient au palier 1. Il suffit qu'une équipe passe pour
monter d'un palier, avec 4 vies neuves. Le set se termine le 6 janvier 2027.

Objectif : maximiser l'espérance de gain (100 € au premier passage de 270, 1000 €
à 290). Programmation dynamique sur les soirs restants. Les chances d'un soir
quelconque sont celles de ce soir multipliées par une « qualité du soir » tirée au
sort (soirs creux ou riches), faute de mieux. Les équipes d'un même soir sont
supposées indépendantes : elles n'ont aucun joueur commun.
"""

from datetime import date
from functools import lru_cache

END = date(2027, 1, 6)
TARGETS = (150, 180, 210, 240, 270, 290)
REWARD = {4: 100.0, 5: 1000.0}   # palier passé (index) -> gain : 270 puis 290
QS = (0.5, 0.7, 0.85, 1.0, 1.15, 1.3)  # qualité d'un soir futur (hypothèse)


def p_pass(ps, m, q=1.0):
    fail = 1.0
    for p in ps[:m]:
        fail *= 1 - min(0.99, p * q)
    return 1 - fail


def recommend(sets_p, night):
    """sets_p : {cible: [p équipe 1, p équipe 2, ...]} pour ce soir (équipes sans joueur commun).
    Renvoie {cible: {vies: {"m": équipes à jouer, "p": chance de passer ce soir}}}."""
    base = [sorted(sets_p.get(t, []), reverse=True) + [0.0] * 4 for t in TARGETS]
    n_left = max(1, (END - date.fromisoformat(night)).days)

    @lru_cache(None)
    def V(n, k, l, got):
        if n == 0:
            return 0.0
        tot = 0.0
        for q in QS:
            best = V(n - 1, k, l, got)  # attendre
            for m in range(1, l + 1):
                pp = p_pass(base[k], m, q)
                best = max(best, pp * win(n, k, got) + (1 - pp) * lose(n, k, l, m, got))
            tot += best
        return tot / len(QS)

    def win(n, k, got):
        r = REWARD.get(k, 0.0) if not (k == 4 and got) else 0.0
        return r if k == 5 else r + V(n - 1, k + 1, 4, got or k == 4)

    def lose(n, k, l, m, got):
        return V(n - 1, k, l - m, got) if l - m >= 1 else V(n - 1, 0, 4, got)

    out = {}
    for k, t in enumerate(TARGETS):
        out[str(t)] = {}
        for l in range(1, 5):
            choice, best = 0, V(n_left - 1, k, l, False)
            for m in range(1, l + 1):
                pp = p_pass(base[k], m)
                ev = pp * win(n_left, k, False) + (1 - pp) * lose(n_left, k, l, m, False)
                if ev > best + 1e-9:
                    choice, best = m, ev
            out[str(t)][str(l)] = {"m": choice, "p": round(p_pass(base[k], choice), 4)}
    return out


if __name__ == "__main__":
    demo = {150: [0.886, 0.79, 0.722, 0.614], 180: [0.65, 0.5, 0.4, 0.3], 210: [0.3, 0.164, 0.095, 0.07],
            240: [0.112, 0.045, 0.022, 0.015], 270: [0.04, 0.012, 0.005, 0.0], 290: [0.012, 0.004, 0.002, 0.0]}
    for t, r in recommend(demo, "2026-11-18").items():
        print(t, {l: (x["m"], f"{x['p']:.0%}") for l, x in r.items()})
