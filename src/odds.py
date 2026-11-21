"""Cotes publiques : lignes de match (Pinnacle, puis Bovada) et props joueurs (Bovada).

Lecture seule de flux publics, sans compte. Aucune mise.

Des props on tire, par joueur, l'espérance de 4 stats :
- points : loi normale ajustée sur les seuils "plus de / moins de" ;
- rebonds, passes, paniers à 3 points : loi de Poisson ajustée sur ces seuils.
Chaque seuil donne une probabilité "plus de", après retrait de la marge du
bookmaker (on normalise la paire plus/moins pour qu'elle somme à 1).
Interceptions, contres et balles perdues ne viennent pas des props : Bovada
n'en donne que des cotes "oui" sans contrepartie, marge comprise.
"""

import json
import math
import re
import statistics as st
import time
import urllib.request
from pathlib import Path
from statistics import NormalDist

from model import norm

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
PINNACLE = "https://guest.api.arcadia.pinnacle.com/0.1/leagues/487"
BOVADA = "https://www.bovada.lv/services/sports/event/coupon/events/A/description/basketball/nba"

TEAMS = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}
PROP_STATS = {"Total Points": "pts", "Total Rebounds": "reb", "Total Assists": "ast", "Total Made 3 Points Shots": "tpm"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def implied(american) -> float:
    a = 100.0 if str(american).upper() == "EVEN" else float(american)
    return -a / (-a + 100) if a < 0 else 100 / (a + 100)


# ---------- lignes de match ----------

def pinnacle_lines() -> dict:
    """{(away, home): {"spread_home", "total", "book"}} pour les matchs déjà cotés."""
    matchups = _get(f"{PINNACLE}/matchups")
    markets = _get(f"{PINNACLE}/markets/straight")
    games = {}
    for m in matchups:
        if m.get("type") != "matchup" or m.get("parentId"):
            continue
        side = {p.get("alignment"): TEAMS.get(p.get("name")) for p in m.get("participants", [])}
        if side.get("home") and side.get("away"):
            games[m["id"]] = (side["away"], side["home"])
    out = {}
    for mk in markets:
        g = games.get(mk.get("matchupId"))
        if not g or mk.get("period") != 0 or mk.get("isAlternate"):
            continue
        entry = out.setdefault(g, {"spread_home": None, "total": None, "book": "Pinnacle"})
        for p in mk.get("prices", []):
            if mk["type"] == "spread" and p.get("designation") == "home":
                entry["spread_home"] = p.get("points")
            if mk["type"] == "total" and p.get("designation") == "over":
                entry["total"] = p.get("points")
    return {k: v for k, v in out.items() if v["spread_home"] is not None or v["total"] is not None}


def bovada_events() -> list:
    return [e for grp in _get(BOVADA) for e in grp.get("events", [])]


def _teams_of(event):
    away = home = None
    for c in event.get("competitors", []):
        if c.get("home"):
            home = TEAMS.get(c["name"])
        else:
            away = TEAMS.get(c["name"])
    return away, home


def bovada_lines(events) -> dict:
    out = {}
    for e in events:
        away, home = _teams_of(e)
        if not (away and home):
            continue
        entry = {"spread_home": None, "total": None, "book": "Bovada"}
        for dg in e.get("displayGroups", []):
            if dg.get("description") != "Game Lines":
                continue
            for m in dg.get("markets", []):
                if (m.get("period") or {}).get("description") != "Game":
                    continue
                for o in m.get("outcomes", []):
                    h = o["price"].get("handicap")
                    if m["description"] == "Point Spread" and TEAMS.get(o["description"]) == home and h:
                        entry["spread_home"] = float(h)
                    if m["description"] == "Total" and o["description"] == "Over" and h:
                        entry["total"] = float(h)
        if entry["spread_home"] is not None or entry["total"] is not None:
            out[(away, home)] = entry
    return out


# ---------- props joueurs ----------

def bovada_props(events) -> dict:
    """{nom normalisé: {"name", "team", "lines": {stat: [(seuil, P(plus de))]}}}"""
    out = {}
    for e in events:
        for dg in e.get("displayGroups", []):
            for m in dg.get("markets", []):
                mt = re.match(r"(.+?) - (.+) \(([A-Z]+)\)$", m.get("description", ""))
                if not mt or mt.group(1) not in PROP_STATS:
                    continue
                if (m.get("period") or {}).get("description") != "Game":
                    continue
                stat, name, team = PROP_STATS[mt.group(1)], mt.group(2), mt.group(3)
                pairs = {}
                for o in m.get("outcomes", []):
                    h = o["price"].get("handicap")
                    if h is None or o["description"] not in ("Over", "Under"):
                        continue
                    pairs.setdefault(float(h), {})[o["description"]] = str(o["price"]["american"])
                lines = []
                for h, pr in pairs.items():
                    if "Over" in pr and "Under" in pr:
                        po, pu = implied(pr["Over"]), implied(pr["Under"])
                        # (seuil, P(plus de) sans marge, cote plus, cote moins)
                        lines.append((h, po / (po + pu), pr["Over"], pr["Under"]))
                if lines:
                    p = out.setdefault(norm(name), {"name": name, "team": team, "lines": {}})
                    p["lines"].setdefault(stat, []).extend(lines)
    return out


PINNACLE_STATS = {"Total Points": "pts", "Total Rebounds": "reb", "Total Assists": "ast", "Total Threes Made": "tpm"}


def pinnacle_props() -> dict:
    """Props joueurs de Pinnacle (une ligne par stat), même format que bovada_props.
    Ajouté le 21/11 : Bovada ne répond plus aux serveurs de GitHub. Pinnacle ne dit pas dans
    quelle équipe joue le joueur : on garde les deux équipes du match."""
    matchups = _get(f"{PINNACLE}/matchups")
    markets = _get(f"{PINNACLE}/markets/straight")
    by_id = {}
    for m in matchups:
        sp = m.get("special") or {}
        if m.get("type") != "special" or sp.get("category") != "Player Props":
            continue
        mt = re.match(r"(.+) (Total (?:Points|Rebounds|Assists|Threes Made))$", sp.get("description", ""))
        if not mt:
            continue
        side = {p["id"]: p["name"] for p in m.get("participants", [])}
        teams = tuple(TEAMS.get(p.get("name")) for p in (m.get("parent") or {}).get("participants", []))
        by_id[m["id"]] = (mt.group(1), PINNACLE_STATS[mt.group(2)], side, teams)
    out = {}
    for k in markets:
        info = by_id.get(k.get("matchupId"))
        if not info or k.get("period") != 0 or k.get("type") != "total":
            continue
        name, stat, side, teams = info
        pr = {side.get(x["participantId"]): x for x in k.get("prices", [])}
        if "Over" not in pr or "Under" not in pr:
            continue
        h = float(pr["Over"]["points"])
        po, pu = implied(str(pr["Over"]["price"])), implied(str(pr["Under"]["price"]))
        p = out.setdefault(norm(name), {"name": name, "team": None, "teams": [t for t in teams if t], "lines": {}, "book": "Pinnacle"})
        p["lines"].setdefault(stat, []).append((h, po / (po + pu), str(pr["Over"]["price"]), str(pr["Under"]["price"])))
    return out


def _fit_normal(lines):
    """Seuil h, P(X > h) = p  =>  h = mu + sd * z, avec z = quantile(1 - p)."""
    pts = [(h, NormalDist().inv_cdf(min(max(1 - p, 0.01), 0.99))) for h, p in lines]
    if len(pts) == 1:
        h, z = pts[0]
        sd = max(4.0, 0.3 * h)  # un seul seuil : dispersion typique d'un scoreur
        return h - sd * z
    mz = st.mean(z for _, z in pts)
    mh = st.mean(h for h, _ in pts)
    var = sum((z - mz) ** 2 for _, z in pts)
    sd = sum((z - mz) * (h - mh) for h, z in pts) / var if var > 1e-9 else max(4.0, 0.3 * mh)
    if sd <= 0:
        sd = max(4.0, 0.3 * mh)
    return mh - sd * mz


def _poisson_sf(k_floor, lam):
    """P(X > k_floor) pour une Poisson de moyenne lam (k_floor = partie entière du seuil)."""
    term, cdf = math.exp(-lam), 0.0
    for k in range(int(k_floor) + 1):
        cdf += term
        term *= lam / (k + 1)
    return 1 - cdf


def _fit_poisson(lines):
    best, best_err = None, float("inf")
    lam = 0.05
    while lam <= 25:
        err = sum((_poisson_sf(math.floor(h), lam) - p) ** 2 for h, p in lines)
        if err < best_err:
            best, best_err = lam, err
        lam += 0.05
    return best


def expected_stats(prop) -> dict:
    """Espérance de chaque stat disponible pour un joueur."""
    out = {}
    for stat, lines in prop["lines"].items():
        lines = sorted({(h, p) for h, p, *_ in lines})
        out[stat] = _fit_normal(lines) if stat == "pts" else _fit_poisson(lines)
    return out


PROPS_CACHE = Path(__file__).resolve().parent.parent / "data" / "props_cache.json"
PROPS_MAX_AGE_H = 4


def fetch_all():
    """Lignes de match fusionnées (Pinnacle prioritaire) et props Bovada.

    Bovada renvoie parfois les matchs sans aucun marché joueur : on réessaie,
    puis on reprend les dernières props reçues (moins de 4 h) plutôt que de
    retomber sans prévenir sur l'historique pour tout le monde.
    """
    lines, props = {}, {}
    for attempt in range(3):
        try:
            events = bovada_events()
            lines.update(bovada_lines(events))
            props = bovada_props(events)
        except Exception as e:
            print(f"  Bovada indisponible ({e})")
        if props:
            break
        try:  # diagnostic : que renvoie Bovada quand il n'y a pas de props ?
            descs = [m.get("description", "") for e in events for dg in e.get("displayGroups", []) for m in dg.get("markets", [])]
            print(f"  essai {attempt + 1} : {len(events)} matchs, {len(descs)} marchés, "
                  f"{sum(d.startswith('Total Points - ') for d in descs)} marchés points joueur")
        except Exception:
            pass
        time.sleep(20)
    # Pinnacle en complément (et en secours quand Bovada ne répond pas) : Bovada reste prioritaire
    # joueur par joueur, car il donne plusieurs seuils par stat.
    try:
        pin = pinnacle_props()
        n_bov = len(props)
        props = {**pin, **{k: dict(v, book="Bovada") for k, v in props.items()}}
        print(f"  props Pinnacle : {len(pin)} joueurs ; Bovada : {n_bov}")
    except Exception as e:
        print(f"  props Pinnacle indisponibles ({e})")
    if props:
        PROPS_CACHE.parent.mkdir(exist_ok=True)
        PROPS_CACHE.write_text(json.dumps({"at": time.time(), "props": props}, ensure_ascii=False), encoding="utf-8")
        print(f"  props en tout : {len(props)} joueurs")
    elif PROPS_CACHE.exists():
        c = json.loads(PROPS_CACHE.read_text(encoding="utf-8"))
        age = (time.time() - c["at"]) / 3600
        if age < PROPS_MAX_AGE_H:
            props = {k: dict(v, lines={s: [tuple(x) for x in l] for s, l in v["lines"].items()}) for k, v in c["props"].items()}
            print(f"  props Bovada vides : reprise des props d'il y a {age:.1f} h ({len(props)} joueurs)")
        else:
            print("  props Bovada vides, cache trop vieux : historique pour tout le monde")
    else:
        print("  props Bovada vides : historique pour tout le monde")
    try:
        lines.update(pinnacle_lines())
    except Exception as e:
        print(f"  Pinnacle indisponible ({e})")
    return lines, props


if __name__ == "__main__":
    lines, props = fetch_all()
    for k, v in sorted(lines.items()):
        print(k, v)
    print(f"{len(props)} joueurs avec props")
    for key in list(props)[:6]:
        print(props[key]["name"], props[key]["team"], {s: round(x, 2) for s, x in expected_stats(props[key]).items()})
