# Ce qu'on sait

Registre tenu par la routine du matin et la passe du lundi (voir METHODE.md). Chaque ligne donne la date, le chiffre et la source. Les z du jour sont dans `python src/verdicts.py`.

## Établi (|z| ≥ 2,5)

- **Les props des bookmakers font mieux que l'historique** : plus proches du réel de 0,42 pt en moyenne, 760 joueurs, z = 3,97 (25/11). On les utilise déjà, rien à changer.
- **Nos projections font mieux que la projection officielle de Sorare** : plus proches du réel de 0,50 pt, 786 joueurs, z = 3,07 (25/11).
- **Les équipes proposées font moins que leur projection** : meilleure équipe de chaque soir, -34 pts en moyenne sur 11 soirs, z = -3,12 (25/11). Cause à trancher par l'échéance « Équipes surestimées », due maintenant.

## Réfuté ou sans effet (ne pas rouvrir sans nouvelles données)

- **Aléa commun aux joueurs d'un même match** : corrélation -0,03, idée « regrouper deux joueurs d'un même match » écartée (16/11).
- **Titulaire qui revient de blessure** : ses coéquipiers sans props ne font pas moins que prévu, 22 joueurs, -0,2 min, +0,5 pt (23/11).
- **Recalage global des projections sur l'historique** : pas de gain hors échantillon, appris du 12 au 16/11 et testé sur 325 joueurs (erreur moyenne 7,13 -> 7,32) (23/11).

## En cours (tendance ou trop tôt)

Suivi chaque matin par `src/verdicts.py` : fourchette ±1 écart-type, biais moyen, élan des props, projections de 25 pts ou plus sans props, chance de jouer des incertains, rythme, tag explosif, petit total, outsider, estimations de match, total des matchs, report de minutes après blessure, banc d'essai paris.
