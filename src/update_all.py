"""Tout mettre à jour d'un coup, pour la tâche automatique (ou à la main).

- galerie : relue si elle a plus de 20 h ;
- calibration blowout / rythme : refaite si elle a plus de 7 jours ;
- page : toujours régénérée (calendrier, compos, cotes, blessures du moment).

Usage : python src/update_all.py <slug-du-manager> [--nuits 2]
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def age_h(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 3600 if path.exists() else float("inf")


def run(*args):
    print(f"\n$ python {' '.join(args)}", flush=True)
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--nuits", default="2")
    a = ap.parse_args()
    DATA.mkdir(exist_ok=True)
    if age_h(DATA / "players.json") > 20:
        run("src/fetch_gallery.py", a.slug)
    if age_h(DATA / "calibration.json") > 24 * 7:
        run("src/history.py")
        run("src/calibrate.py")
    run("src/build_page.py", "--nuits", a.nuits)


if __name__ == "__main__":
    main()
