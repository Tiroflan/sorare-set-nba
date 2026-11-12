"""Phase 0 : avec ma galerie, quelle chance d'atteindre 270 (palier 5) et 290 (palier 6) ?

Méthode volontairement simple et transparente :
- scores d'un joueur = ses 15 derniers scores Sorare (score brut, sans bonus) ;
- un score manquant (null) = match non joué, d'où une proba de jouer ;
- score d'équipe = somme des scores x (1 + bonus d'édition de la carte) ;
- toutes les équipes de 5 joueurs distincts sous 16 étoiles sont classées par
  approximation normale, puis les meilleures sont re-simulées par Monte-Carlo
  en tirant au hasard dans l'historique réel de chaque joueur.

Deux lectures :
- "si les 5 jouent" : le cas où tu as choisi un soir sans incertitude ;
- "avec absences" : on applique le taux de matchs manqués de chacun.

Usage : python src/phase0_faisabilite.py [--cartes rarete1,rarete2] [--set slug]
"""

import argparse
import itertools
import json
import math
import random
from pathlib import Path
from statistics import mean, pstdev

DATA = Path(__file__).resolve().parent.parent / "data"
STAR_CAP = 16.0
TARGETS = (240, 270, 290)
N_SIM = 20000
TOP_K = 300


# L'API publique renvoie power = 1.000 pour les cartes Set : barème confirmé
# dans l'appli (Shiny +5 %, Holo +10 %, variante Shiny +15 %).
EDITION_BONUS = {
    "standard_base": 0.0,
    "shiny_base": 0.05,
    "holo_base": 0.10,
    "shiny_variant_1": 0.15,
}
# Joueurs gardés par niveau d'étoiles avant l'énumération des équipes.
KEEP_PER_STAR_LEVEL = 7


def edition_bonus(edition: str | None) -> float:
    if not edition:
        return 0.0
    for key, bonus in EDITION_BONUS.items():
        if edition.endswith(key):
            return bonus
    return 0.0


def load(rarities: set[str] | None, card_set: str | None) -> list[dict]:
    cards = json.loads((DATA / "gallery.json").read_text(encoding="utf-8"))
    players = {p["slug"]: p for p in json.loads((DATA / "players.json").read_text(encoding="utf-8"))}
    best: dict[str, dict] = {}
    for c in cards:
        if rarities and c["rarityTyped"] not in rarities:
            continue
        if card_set and (c.get("cardSet") or {}).get("slug") != card_set:
            continue
        p = players.get(c["anyPlayer"]["slug"])
        if not p or p.get("setStars") is None:
            continue
        raw = p["rawPlayerGameScores"] or []
        played = [s for s in raw if s is not None]
        if len(played) < 3:
            continue
        # Un joueur déclaré OUT ne peut pas compter : on l'écarte.
        if any(i["status"] == "OUT" for i in p.get("activeInjuries") or []):
            continue
        bonus = edition_bonus(c.get("cardEditionName"))
        if p["slug"] not in best or bonus > best[p["slug"]]["bonus"]:
            best[p["slug"]] = {
                "slug": p["slug"],
                "name": p["displayName"],
                "stars": float(p["setStars"]),
                "bonus": bonus,
                "edition": c.get("cardEditionName") or c["rarityTyped"],
                "scores": played,
                "p_play": len(played) / len(raw) if raw else 1.0,
                "mean": mean(played) * (1 + bonus),
                "sd": pstdev(played) * (1 + bonus),
                "proj": p.get("nextClassicFixtureProjectedScore"),
                "injured": [i["status"] for i in p.get("activeInjuries") or []],
            }
    return list(best.values())


def p_normal(mu: float, sd: float, target: float) -> float:
    if sd == 0:
        return float(mu >= target)
    return 0.5 * math.erfc((target - mu) / (sd * math.sqrt(2)))


def simulate(team: list[dict], with_absences: bool, rng: random.Random) -> dict[int, float]:
    hits = {t: 0 for t in TARGETS}
    for _ in range(N_SIM):
        total = 0.0
        for pl in team:
            if with_absences and rng.random() > pl["p_play"]:
                continue
            total += rng.choice(pl["scores"]) * (1 + pl["bonus"])
        for t in TARGETS:
            hits[t] += total >= t
    return {t: hits[t] / N_SIM for t in TARGETS}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cartes", help="raretés à garder, ex. common,limited")
    ap.add_argument("--set", dest="card_set", help="slug du cardSet à garder")
    args = ap.parse_args()
    rarities = set(args.cartes.split(",")) if args.cartes else None

    pool = load(rarities, args.card_set)
    pool.sort(key=lambda p: -p["mean"])
    print(f"{len(pool)} joueurs exploitables\n")
    print(f"{'joueur':26} {'étoiles':>7} {'bonus':>6} {'moy.':>6} {'écart':>6} {'joue':>5} {'pts/étoile':>10}")
    for p in pool:
        inj = " (" + ",".join(p["injured"]) + ")" if p["injured"] else ""
        print(f"{p['name'][:26]:26} {p['stars']:7.1f} {p['bonus']:6.0%} {p['mean']:6.1f} {p['sd']:6.1f}"
              f" {p['p_play']:5.0%} {p['mean'] / p['stars']:10.1f}{inj}")

    # Élagage : à étoiles égales, on garde les meilleurs en moyenne et en plafond.
    by_level: dict[float, list[dict]] = {}
    for p in pool:
        by_level.setdefault(p["stars"], []).append(p)
    short = {}
    for level, ps in by_level.items():
        for key in (lambda p: -p["mean"], lambda p: -(p["mean"] + p["sd"])):
            for p in sorted(ps, key=key)[:KEEP_PER_STAR_LEVEL]:
                short[p["slug"]] = p
    candidates = sorted(short.values(), key=lambda p: -p["mean"])
    print(f"\n{len(candidates)} joueurs gardés pour composer les équipes")

    teams = []
    for combo in itertools.combinations(candidates, 5):
        if sum(p["stars"] for p in combo) > STAR_CAP:
            continue
        mu = sum(p["mean"] for p in combo)
        sd = math.sqrt(sum(p["sd"] ** 2 for p in combo))
        teams.append((p_normal(mu, sd, TARGETS[0]), mu, combo))
    if not teams:
        print("\nAucune équipe de 5 joueurs possible sous 16 étoiles.")
        return
    teams.sort(key=lambda t: -t[0])
    print(f"\n{len(teams)} équipes possibles sous {STAR_CAP:g} étoiles, simulation des {min(TOP_K, len(teams))} meilleures")

    rng = random.Random(42)
    results = []
    for _, mu, combo in teams[:TOP_K]:
        full = simulate(list(combo), False, rng)
        results.append((full[TARGETS[0]], full, mu, combo))
    results.sort(key=lambda r: -r[0])

    print("\nTop 10 (si les 5 jouent) :")
    for _, full, mu, combo in results[:10]:
        absn = simulate(list(combo), True, rng)
        names = ", ".join(f"{p['name'].split()[-1]} {p['stars']:g}*" for p in combo)
        stars = sum(p["stars"] for p in combo)
        probs = " | ".join(f"P>={t} {full[t]:5.1%}" for t in TARGETS)
        print(f"- moy {mu:5.1f} | {probs} | avec absences P>={TARGETS[0]} {absn[TARGETS[0]]:5.1%}"
              f" | {stars:g}* | {names}")

    best = results[0][1]
    p4 = {t: 1 - (1 - best[t]) ** 4 for t in TARGETS}
    print("\nOrdre de grandeur avec 4 vies (meilleure équipe, essais supposés indépendants) : "
          + ", ".join(f"{t} pts {p4[t]:.0%}" for t in TARGETS))

    # Pour viser plus haut : la meilleure équipe pour chaque cible n'est pas la même.
    for t in TARGETS[1:]:
        r = max(results, key=lambda r: r[1][t])
        names = ", ".join(f"{p['name'].split()[-1]} {p['stars']:g}*" for p in r[3])
        print(f"Meilleure équipe pour {t} : {r[1][t]:.1%} (moy {r[2]:.1f}) | {names}")


if __name__ == "__main__":
    main()
