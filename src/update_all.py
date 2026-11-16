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
from datetime import datetime, timedelta
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
    # Galerie relue à chaque passage : les cartes des packs ouverts dans la journée
    # comptent dès la mise à jour suivante.
    run("src/fetch_gallery.py", a.slug)
    if age_h(DATA / "calibration.json") > 24 * 7:
        run("src/history.py")
        run("src/calibrate.py")
    # Bilans des soirs finis qui n'en ont pas encore. Heure de Paris, de 7h à 20h :
    # tous les matchs de la nuit US sont terminés. Rattrape jusqu'à 3 soirs manqués.
    sys.path.insert(0, str(ROOT / "src"))
    from espn import PARIS
    now = datetime.now(PARIS)
    if 7 <= now.hour < 20:
        for k in (3, 2, 1):
            night = (now - timedelta(days=k)).date().isoformat()
            j = ROOT / "journal"
            if (j / f"{night}.json").exists() and not (j / f"bilan-{night}.json").exists():
                try:
                    run("src/bilan.py", night)
                except Exception as e:  # le bilan ne doit jamais empêcher la page de sortir
                    print(f"Bilan {night} non fait : {e}")
    run("src/build_page.py", "--nuits", a.nuits)


if __name__ == "__main__":
    main()
