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


def get(slugs: list[str], force: bool = False) -> dict[str, list[dict]]:
    """Renvoie {slug: [matchs du plus récent au plus ancien]}."""
    cache = _load()
    now = time.time()
    todo = [s for s in slugs if force or s not in cache or now - cache[s]["at"] > MAX_AGE_H * 3600]
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
