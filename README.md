# Sorare Set NBA, outil perso

Lecture seule : données publiques Sorare (sans connexion), ESPN, RotoWire, Pinnacle et Bovada (lignes de match et props joueurs, sans compte, sans mise). Aucun achat, aucune vente, aucune compo n'est faite par l'outil.

## Commandes

1. Mettre à jour la galerie (quand tu as de nouvelles cartes) :
   `python src/fetch_gallery.py mrpropre-df54316e-2166-4431-9042-a68f901b1132`
2. Recalibrer blowout et rythme (une fois par semaine suffit) :
   `python src/history.py` puis `python src/calibrate.py`
3. Meilleures équipes sur les 2 prochains soirs, et évaluation de la tienne :
   `python src/soirs.py --nuits 2 --cible 240 --equipe "Wembanyama,Gilgeous,Wagner,Jenkins,McBride"`

4. Page téléphone : `python src/build_page.py --nuits 2` génère `site/index.html` (autonome). `--gabarit` refait seulement la page avec les dernières données.

À relancer juste avant de composer : compos, blessures et cotes bougent jusqu'au coup d'envoi.

## Fichiers

- `src/model.py` : le modèle, avec toutes les hypothèses non mesurées regroupées en haut.
- `src/soirs.py` : fenêtre de plusieurs soirs, meilleures équipes, remplacements.
- `src/espn.py`, `src/rotowire.py`, `src/sorare_api.py`, `src/history.py` : les sources.
- `src/calibrate.py` : mesure blowout et rythme sur les vrais matchs.
- `src/phase0_faisabilite.py` : faisabilité globale des paliers.
