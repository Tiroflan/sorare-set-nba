"""Lit la galerie NBA publique d'un manager et les infos de ses joueurs.

Usage : python src/fetch_gallery.py <slug-du-manager>
Sortie : data/gallery.json, data/players.json
"""

import json
import sys
from pathlib import Path

from sorare_api import ComplexityError, gql

DATA = Path(__file__).resolve().parent.parent / "data"

CARDS_Q = """
query Gallery($slug: String!, $first: Int!, $after: String) {
  user(slug: $slug) {
    cards(sport: NBA, first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        slug
        rarityTyped
        cardEditionName
        specialEdition
        power
        seasonYear
        cardSet { slug }
        anyPlayer { slug displayName }
      }
    }
  }
}
"""

PLAYERS_Q = """
query Players($slugs: [String!]!) {
  players(slugs: $slugs) {
    slug
    displayName
    setStars: gameplayTierStars(gameMode: SET)
    rawPlayerGameScores(last: 15)
    nextClassicFixtureProjectedScore
    activeInjuries { status kind expectedEndDate }
    ... on NBAPlayer { activeClub { code } }
  }
}
"""


def fetch_cards(slug: str) -> list[dict]:
    cards, after, first = [], None, 20
    while True:
        try:
            data = gql(CARDS_Q, {"slug": slug, "first": first, "after": after})
        except ComplexityError:
            if first == 1:
                raise
            first = max(1, first // 2)
            continue
        conn = data["user"]["cards"]
        cards.extend(conn["nodes"])
        print(f"  {len(cards)} cartes lues (pages de {first})")
        if not conn["pageInfo"]["hasNextPage"]:
            return cards
        after = conn["pageInfo"]["endCursor"]


def fetch_players(slugs: list[str]) -> list[dict]:
    out, i, size = [], 0, 10
    while i < len(slugs):
        batch = slugs[i : i + size]
        try:
            data = gql(PLAYERS_Q, {"slugs": batch})
        except ComplexityError:
            if size == 1:
                raise
            size = max(1, size // 2)
            continue
        out.extend(data["players"])
        i += len(batch)
        print(f"  {len(out)}/{len(slugs)} joueurs lus")
    return out


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage : python src/fetch_gallery.py <slug-du-manager>")
    slug = sys.argv[1]
    DATA.mkdir(exist_ok=True)
    print(f"Galerie NBA de {slug}")
    cards = fetch_cards(slug)
    (DATA / "gallery.json").write_text(json.dumps(cards, indent=1, ensure_ascii=False), encoding="utf-8")
    slugs = sorted({c["anyPlayer"]["slug"] for c in cards if c.get("anyPlayer")})
    print(f"{len(cards)} cartes, {len(slugs)} joueurs distincts")
    players = fetch_players(slugs)
    (DATA / "players.json").write_text(json.dumps(players, indent=1, ensure_ascii=False), encoding="utf-8")
    print("OK : data/gallery.json et data/players.json")


if __name__ == "__main__":
    main()
