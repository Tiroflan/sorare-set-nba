"""Historique des 15 derniers matchs des joueurs, avec le score final du match.

Mis en cache dans data/history.json, relu depuis l'API quand il a plus de
MAX_AGE_H heures, pour ne pas refaire 100 appels à chaque lancement.

Usage direct (toute la galerie) : python src/history.py
"""

import json
import time
from pathlib import Path

from sorare_api import ComplexityError, gql

DATA = Path(__file__).resolve().parent.parent / "data"
CACHE = DATA / "history.json"
MAX_AGE_H = 6
MAX_KEEP_H = 48

Q = """
query Hist($slugs: [String!]!) {
  players(slugs: $slugs) {
    slug
    ... on NBAPlayer {
      games: anyGameStats(last: 15) {
        ... on PlayerGameStatsBasketball {
          minsPlayed points rebounds assists steals blocks turnovers threePointsMade
          anyTeam { slug }
          basketballGame {
            id date homeScore awayScore statusTyped
            homeTeam { slug }
            awayTeam { slug }
          }
        }
      }
    }
  }
}
"""


def _load() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def get(slugs: list[str], force: bool = False, still_fresh=None) -> dict[str, list[dict]]:
    """Renvoie {slug: [matchs du plus récent au plus ancien]}.
    still_fresh(slug, at) : si fourni, une entrée de plus de MAX_AGE_H heures est gardée quand
    il dit qu'aucun match du joueur n'a pu se terminer depuis (au plus MAX_KEEP_H heures)."""
    cache = _load()
    now = time.time()

    def stale(s):
        if force or s not in cache:
            return True
        age = now - cache[s]["at"]
        if age <= MAX_AGE_H * 3600:
            return False
        return not (still_fresh and age <= MAX_KEEP_H * 3600 and still_fresh(s, cache[s]["at"]))
    todo = [s for s in slugs if stale(s)]
    print(f"  {len(todo)} historiques à relire ({len(slugs) - len(todo)} déjà à jour)")
    i, size = 0, 3
    while i < len(todo):
        batch = todo[i : i + size]
        try:
            data = gql(Q, {"slugs": batch})
        except ComplexityError:
            if size == 1:
                raise
            size -= 1
            continue
        for p in data["players"]:
            cache[p["slug"]] = {"at": now, "games": p.get("games") or []}
        i += len(batch)
        if i % 30 < size:
            print(f"  historique : {i}/{len(todo)} joueurs")
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {s: cache[s]["games"] for s in slugs if s in cache}


if __name__ == "__main__":
    players = json.loads((DATA / "players.json").read_text(encoding="utf-8"))
    get([p["slug"] for p in players])
    print("OK : data/history.json")
