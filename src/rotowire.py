"""Compos probables NBA du soir, lues sur la page publique de RotoWire.

Pour chaque match : heure, équipes, spread, total de points ; pour chaque
équipe : statut de la compo (prévue ou confirmée), les 5 titulaires avec leur
probabilité de jouer, et la liste "may not play" (Ques, Doubt, Out, OFS...).
"""

import html
import re
import urllib.request

URL = "https://www.rotowire.com/basketball/nba-lineups.php"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

# RotoWire et Sorare n'écrivent pas toujours les codes d'équipe pareil.
ALIASES = {"SA": "SAS", "NY": "NYK", "GS": "GSW", "NO": "NOP", "PHO": "PHX", "UTAH": "UTA", "WSH": "WAS"}


def _text(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def fetch_html() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _parse_team(ul: str) -> dict:
    status = "confirmed" if "is-confirmed" in ul else "expected" if "is-expected" in ul else "unknown"
    starters, may_not_play = [], []
    split = ul.find("MAY NOT PLAY")
    for m in re.finditer(r'<li class="lineup__player([^"]*)"[^>]*>(.*?)</li>', ul, re.S):
        cls, inner = m.group(1), m.group(2)
        name = re.search(r'<a title="([^"]+)"', inner)
        if not name:
            continue
        pct = re.search(r"is-pct-play-(\d+)", cls)
        inj = re.search(r'class="lineup__inj">([^<]*)<', inner)
        entry = {
            "name": html.unescape(name.group(1)),
            "pct_play": int(pct.group(1)) / 100 if pct else None,
            "inj": inj.group(1).strip() if inj else None,
        }
        if split != -1 and m.start() > split:
            may_not_play.append(entry)
        else:
            starters.append(entry)
    return {"status": status, "starters": starters, "may_not_play": may_not_play}


def parse(page: str) -> list[dict]:
    games = []
    for block in re.split(r'<div class="lineup is-nba', page)[1:]:
        abbrs = re.findall(r'class="lineup__abbr">([A-Z]+)<', block)
        lists = re.findall(r'<ul class="lineup__list is-(visit|home)"(.*?)</ul>', block, re.S)
        if len(abbrs) < 2 or len(lists) < 2:
            continue
        time = re.search(r'class="lineup__time">([^<]*)<', block)
        odds = _text(block[block.find('class="lineup__odds'):]) if 'class="lineup__odds' in block else ""
        spread = re.search(r"SPREAD\s+([A-Z]+ [-+][\d.]+|PK)", odds)
        total = re.search(r"O/U\s+([\d.]+) Pts", odds)
        away, home = (ALIASES.get(a, a) for a in abbrs[:2])
        teams = {}
        for (side, ul), abbr in zip(lists[:2], (away, home)):
            teams[abbr] = _parse_team(ul)
        games.append({
            "time": time.group(1).strip() if time else None,
            "away": away,
            "home": home,
            "spread": spread.group(1) if spread else None,
            "total": float(total.group(1)) if total else None,
            "teams": teams,
        })
    return games


def fetch() -> list[dict]:
    return parse(fetch_html())


if __name__ == "__main__":
    for g in fetch():
        print(f"{g['time']} {g['away']} @ {g['home']} | spread {g['spread']} | total {g['total']}")
        for abbr, t in g["teams"].items():
            st = ", ".join(f"{p['name']}{' (' + p['inj'] + ')' if p['inj'] else ''}" for p in t["starters"])
            mnp = ", ".join(f"{p['name']} ({p['inj']})" for p in t["may_not_play"])
            print(f"  {abbr} [{t['status']}] {st}")
            if mnp:
                print(f"     absents/incertains : {mnp}")
