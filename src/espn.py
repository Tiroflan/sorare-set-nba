"""Calendrier, cotes et blessures NBA depuis les flux publics d'ESPN.

- calendrier de plusieurs soirs (date au format américain, heure de New York) ;
- spread et total de points quand ESPN les publie (en général le jour même) ;
- blessures de toutes les équipes : Out ou Day-To-Day.
"""

import json
import re
import urllib.request
from datetime import date, datetime, timedelta

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
# ESPN n'écrit pas toujours les codes d'équipe comme Sorare.
ALIASES = {"NY": "NYK", "GS": "GSW", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def code(abbr: str) -> str:
    return ALIASES.get(abbr, abbr)


def schedule(first: date, nights: int) -> list[dict]:
    """Matchs des `nights` soirs à partir de `first` (date du soir aux États-Unis)."""
    games = []
    for k in range(nights):
        d = first + timedelta(days=k)
        data = _get(f"{BASE}/scoreboard?dates={d:%Y%m%d}")
        for e in data.get("events", []):
            c = e["competitions"][0]
            side = {t["homeAway"]: code(t["team"]["abbreviation"]) for t in c["competitors"]}
            odds = (c.get("odds") or [{}])[0]
            spread_home = None
            m = re.match(r"([A-Z]+) ([-+]?[\d.]+)", odds.get("details") or "")
            if m:
                fav, line = code(m.group(1)), float(m.group(2))
                spread_home = line if fav == side["home"] else -line
            elif (odds.get("details") or "").upper() == "EVEN":
                spread_home = 0.0
            games.append({
                "night": d.isoformat(),
                "tip_utc": e["date"],
                "away": side["away"],
                "home": side["home"],
                "spread_home": spread_home,  # négatif = domicile favori
                "total": odds.get("overUnder"),
                "status": e["status"]["type"]["name"],
            })
    return games


def injuries() -> dict[str, dict]:
    """{nom du joueur: {"team": code, "status": "Out" | "Day-To-Day", "date": ...}}"""
    out = {}
    for team in _get(f"{BASE}/injuries").get("injuries", []):
        for i in team.get("injuries", []):
            ath = i.get("athlete") or {}
            t = (ath.get("team") or {}).get("abbreviation")
            out[ath.get("displayName", "")] = {
                "team": code(t) if t else None,
                "status": i.get("status"),
                "date": i.get("date"),
                "detail": (i.get("shortComment") or "")[:160],
            }
    return out


def us_tonight() -> date:
    """Date du soir NBA en cours : avant midi heure de Paris, c'est encore la veille aux États-Unis."""
    now = datetime.now()
    return (now - timedelta(hours=12)).date() if now.hour < 12 else now.date()


if __name__ == "__main__":
    for g in schedule(us_tonight(), 3):
        print(g)
    inj = injuries()
    print(len(inj), "blessés", list(inj.items())[:3])
