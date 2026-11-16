"""Briefing du matin : bilan de la nuit + meilleures équipes des 2 prochains soirs.

Lit la page en ligne (mêmes données que sur le téléphone) et affiche un
résumé en Markdown. Aucune écriture, aucun appel à Sorare.

Usage : python src/briefing.py [--local]   (--local : lit site/index.html)
"""

import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from espn import PARIS

URL = "https://tiroflan.github.io/sorare-set-nba/"
LOCAL = Path(__file__).resolve().parent.parent / "site" / "index.html"
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def load(local: bool) -> dict:
    if local:
        html = LOCAL.read_text(encoding="utf-8")
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    start = html.index("const D = ") + len("const D = ")
    return json.JSONDecoder().raw_decode(html[start:])[0]


def when(iso: str) -> str:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PARIS)
    return f"{JOURS[d.weekday()]} {d.day} à {d:%Hh%M}"


def night_label(n: str) -> str:
    d = datetime.fromisoformat(n) + timedelta(days=1)
    return f"nuit du {int(n[8:10])} au {d.day}/{d.month:02d}"


def pct(x: float) -> str:
    return "<1 %" if x < 0.005 else f"{round(x * 100)} %"


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def bilan_block(rows, title):
    pl = [r for r in rows if r["pl"]]
    err = [r["a"] - r["e"] for r in pl]
    inz = mean([abs(r["a"] - r["e"]) <= r["sd"] for r in pl if r["sd"] > 0])
    wp = [r for r in pl if r["pr"]]
    out = [f"**{title}** : {len(rows)} joueurs projetés, {len(pl)} ont joué",
           f"- biais {mean(err):+.1f} pts, écart moyen {mean([abs(e) for e in err]):.1f} pts par joueur",
           f"- dans la fourchette ±1 écart-type : {pct(inz)} (68 % attendu)"]
    if wp:
        better = sum(abs(r["a"] - r["e"]) < abs(r["a"] - r["h"]) for r in wp)
        out.append(f"- props : écart moyen {mean([abs(r['a'] - r['e']) for r in wp]):.1f} contre "
                   f"{mean([abs(r['a'] - r['h']) for r in wp]):.1f} pour l'historique seul "
                   f"(props plus proches pour {better} joueurs sur {len(wp)})")
    sure = [r for r in rows if r["pct"] >= 1]
    unsure = [r for r in rows if 0 < r["pct"] < 1]
    if sure:
        out.append(f"- présence : annoncés sûrs {pct(mean([r['pl'] for r in sure]))} ont joué"
                   + (f" ; incertains {pct(mean([r['pct'] for r in unsure]))} prévu, "
                      f"{pct(mean([r['pl'] for r in unsure]))} ont joué" if unsure else ""))
    return out


def teams_block(B):
    """Les équipes proposées font-elles ce qu'on leur prédit ? En choisissant les plus hautes
    projections, l'outil attrape aussi les joueurs surestimés par hasard : on le surveille."""
    out, nights, sel, oth = [], [], [], []
    for b in sorted(B, key=lambda b: b["night"]):
        done = [t for t in b["teams"] if t["score"] is not None and t.get("mu")]
        if not done:
            continue
        mu, sc = mean([t["mu"] for t in done]), mean([t["score"] for t in done])
        hit, exp = sum(t["score"] >= 240 for t in done), sum(t["p"]["240"] for t in done)
        nights.append((mu, sc, hit, exp))
        out.append(f"- {night_label(b['night'])} : projetées {mu:.0f} pts en moyenne, réel {sc:.0f} ({sc - mu:+.0f}) ; "
                   f"{hit} sur {len(done)} au-dessus de 240 pour {exp:.1f} attendues")
        names = {n for t in b["teams"] for n in t["names"]}
        for r in b["rows"]:
            if r["pl"]:
                (sel if r["n"] in names else oth).append(r["a"] - r["e"])
    if not nights:
        return []
    head = [f"\n**Équipes proposées, projeté contre réel** ({len(nights)} nuits)"]
    tail = [f"- cumul : {mean([n[1] - n[0] for n in nights]):+.0f} pts par équipe et par nuit ; "
            f"{sum(n[2] for n in nights)} au-dessus de 240 pour {sum(n[3] for n in nights):.1f} attendues",
            f"- joueurs retenus dans les équipes : {mean(sel):+.1f} pts contre leur projection ({len(sel)} joueurs), "
            f"les autres {mean(oth):+.1f} ({len(oth)}). Un écart qui se creuse = les équipes sont trop optimistes"]
    return head + out + tail


def main():
    D = load("--local" in sys.argv)
    P = {p["id"]: p for p in D["players"]}
    print(f"# Briefing Set NBA\n\nPage mise à jour le {D['generated']}.\n")

    B = D.get("bilans") or []
    print("## Bilan\n")
    if not B:
        print("Pas encore de bilan.\n")
    else:
        last = B[0]
        print("\n".join(bilan_block(last["rows"], night_label(last["night"]))))
        if len(B) > 1:
            print("\n".join(bilan_block([r for b in B for r in b["rows"]], f"Cumul sur {len(B)} nuits")))
        gl = [x for b in B for x in b.get("games", [])]
        est = [x for x in gl if x.get("est") and x.get("odds")]
        if est:
            m = lambda f: sum(abs(f(x)) for x in est) / len(est)
            print(f"- matchs estimés la veille ({len(est)}, cumul) : à {m(lambda x: x['est']['spread_home'] - x['odds']['spread_home']):.1f} pts "
                  f"des vraies cotes sur l'écart, {m(lambda x: x['est']['total'] - x['odds']['total']):.1f} sur le total")
        top = sorted(last["rows"], key=lambda r: -abs(r["a"] - r["e"]) if r["pl"] else 0)[:5]
        print("- plus gros écarts : " + " ; ".join(
            f"{r['n']} {r['a']:.0f} pour {r['e']:.0f} prévus ({r['em']:.0f} → {r['m']} min)" for r in top if r["pl"]))
        for b in B[:2]:
            done = [t for t in b["teams"] if t["score"] is not None]
            if not done:
                continue
            best = sorted(done, key=lambda t: -t["p"]["240"])[:5]
            print(f"\nÉquipes figées la {night_label(b['night'])}, les 5 mieux classées pour 240 :")
            for t in best:
                print(f"- {t['score']:.1f} pts (prévu {pct(t['p']['240'])}) : "
                      + ", ".join(f"{n.split()[-1]} {x:.0f}" for n, x in zip(t["names"], t["pts"])))
            hit = sum(t["score"] >= 240 for t in done)
            print(f"- {hit} sur {len(done)} ont passé 240, {sum(t['p']['240'] for t in done):.1f} attendues "
                  "(équipes très liées entre elles : à lire comme un seul tirage)")
        print("\n".join(teams_block(B)))
        print()

    print("## Les 2 prochains soirs\n")
    nights = {}
    for g in D["games"]:
        nights.setdefault(g["night"], []).append(g)
    for n, gs in nights.items():
        print(f"**{night_label(n)}** : {len(gs)} matchs, " + ", ".join(
            f"{g['away']}@{g['home']} {g['when'].split(' · ')[-1]}" for g in gs))
        no = [f"{g['away']}@{g['home']}" for g in gs if not g.get("book") or g["book"].startswith("estimation")]
        if no:
            print(f"  sans cotes pour l'instant (estimés d'après les matchs joués) : {', '.join(no)}")
    for t in (240, 270, 290):
        teams = sorted(D["teams"], key=lambda x: -x["p"][str(t)])[:3]
        print(f"\n**Meilleures équipes pour {t} pts**")
        for x in teams:
            ps = [P[i] for i in x["ids"]]
            lock = min(ps, key=lambda p: p["tip"])
            flags = [f"{p['name'].split()[-1]} joue {pct(p['pct'])}" for p in ps if p["pct"] < 1]
            print(f"- {pct(x['p'][str(t)])} : " + ", ".join(f"{p['name']} {p['stars']:g}★" for p in ps)
                  + f" · {sum(p['stars'] for p in ps):g}★ · figée {when(lock['tip'])}"
                  + (f" · attention : {', '.join(flags)}" if flags else ""))
        best = {}
        for x in D["teams"]:
            n = min((P[i] for i in x["ids"]), key=lambda p: p["tip"])["night"]
            best[n] = max(best.get(n, 0), x["p"][str(t)])
        mn = (D.get("playMin") or {}).get(str(t), 0)
        if best:
            print(f"- jouer ? (seuil {pct(mn) if mn else 'aucun'}) : " + " ; ".join(
                f"{night_label(n)} {pct(v)} {'à jouer' if v >= mn else 'soir creux'}" for n, v in sorted(best.items())))


if __name__ == "__main__":
    main()
