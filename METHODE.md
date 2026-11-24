# Méthode de travail

Règles du jeu entre Romain et Claude sur cet outil, posées le 25/11/2026. Toute session (conversation, routine du matin, passe du lundi) les applique.

## 1. Une question n'est pas une commande

Quand Romain pose une question ou lance une intuition :

1. on en discute, Claude creuse les données ;
2. Claude finit par une proposition argumentée : « au vu de X, je propose de faire Y » (ou de ne rien faire) ;
3. Romain dit oui ou non. Rien ne change dans l'outil avant ce oui.

Une intuition qui tient la route n'entre pas dans le modèle : elle entre dans la file des hypothèses suivies (un verdict dans `src/verdicts.py`).

## 2. Le modèle change une fois par semaine, le lundi

Toutes les corrections du modèle (`src/model.py`, les réglages des autres scripts) passent en lot lors de la passe du lundi. But : ne pas coller au bruit de quelques nuits, et savoir quelle correction a produit quel effet.

Exceptions, à faire tout de suite : un bug, une source cassée, une donnée manifestement fausse. L'affichage de la page n'est pas le modèle : il suit seulement la règle 1.

## 3. Ce que Claude fait seul, ce qu'il propose

Claude applique seul, le lundi, une correction quand les trois conditions sont réunies :

- le verdict concerné a atteint « on peut conclure » (|z| ≥ 2,5) ;
- l'action était écrite à l'avance dans ce verdict ou dans l'échéancier ;
- le test hors échantillon (apprendre sur les nuits anciennes, vérifier sur les récentes) confirme, ou au moins ne dégrade pas.

Il le dit alors dans la note du lundi : ce qui a changé, pourquoi, avec quel chiffre.

Tout le reste est proposé et attend le oui de Romain : une nouvelle hypothèse qui tient, une nouvelle règle, une nouvelle source, un changement de page.

Jamais : retoucher les règles du banc d'essai paris (figées le 23/11), rouvrir un chantier fermé sans nouvelles données, acheter, vendre ou composer sur Sorare.

## 4. Chercher sans limite, conclure seulement sur des nuits nouvelles

La passe du lundi formule autant d'hypothèses que les données en suggèrent, et les liste toutes dans la note, y compris celles qui ne tiennent pas. Il n'y a pas de quota.

Le piège est ailleurs : en fouillant les nuits passées, on finit toujours par trouver un écart par hasard, et plus on cherche, plus c'est vrai. Donc une hypothèse trouvée sur le passé n'est jamais une conclusion. Elle devient un verdict suivi, testé seulement sur les nuits qui suivent sa date d'ajout. Elle ne compte comme établie qu'à |z| ≥ 2,5 sur ces nuits-là.

Conséquence pratique : on ne suit activement que les hypothèses dont l'effet est assez gros pour être tranché avant la fin du set. Les autres sont notées, pas suivies.

## 5. L'échéancier se déclenche tout seul

`ECHEANCES` dans `src/verdicts.py` : chaque échéance a une date, ou un verdict qui la déclenche, et l'analyse à faire. Le matin où elle est due, la routine fait l'analyse (elle ne se contente pas de la rappeler), écrit le résultat dans `CONNAISSANCES.md`, puis retire l'échéance ou la redate. Si l'analyse débouche sur une correction, elle attend le lundi (règle 2).

## 6. Ce qu'on sait

`CONNAISSANCES.md` tient le registre : établi, réfuté, en cours. C'est la réponse à « qu'est-ce qui semble vrai et qu'est-ce qui ne l'est pas ». Mis à jour par la routine du matin (échéances) et par la passe du lundi.

## 7. Où Romain lit les nouvelles

- Chaque matin, la routine de 7h30 écrit le briefing. Quand Romain demande « le bilan » dans une conversation, Claude relit ce briefing, la dernière note du lundi et les échéances traitées, au lieu de tout relancer.
- Chaque lundi, la note d'analyse est dans `notes/AAAA-MM-JJ.md`.
- Sur la page, la cloche et la bannière en haut affichent le fil `notes/nouvelles.json`. Chaque routine y ajoute ses nouvelles, en tête du fichier (les plus récentes d'abord) : `{"date": "AAAA-MM-JJ", "type": ..., "titre": ..., "texte": ..., "lien": ...}`. Types : `etabli`, `refute`, `correction` (modèle changé), `proposition` (attend le oui de Romain), `echeance`, `note`, `alerte` (run en échec, source cassée). Un titre court, un texte de 2 ou 3 phrases avec le chiffre, un lien GitHub vers le détail si utile (`https://github.com/Tiroflan/sorare-set-nba/blob/main/...`). Seulement ce qui change quelque chose : pas de nouvelle « rien de neuf ».

## 8. Pour le set suivant

Un nouveau set d'environ 2 mois suit celui-ci. On privilégie ce qui rend le modèle robuste et réutilisable plutôt que les réglages propres au set Divination.
