# Autofocus

*Module : Autofocus.* Déplace le focuser sur une série de positions, mesure les étoiles à
chacune et va à la position la plus nette. Une caméra et un focuser doivent être connectés.

## Réglages

**Caméra** et **Focuser** : lesquels utiliser. Choisissez un focuser placé devant la caméra dans
le profil.

**Courbe en V**

| Réglage | |
|---|---|
| Mesure de netteté | **HFD** (diamètre à mi-flux) ou **FWHM**. La HFD supporte mieux les étoiles très défocalisées. |
| Algorithme d'ajustement | **parabole** ou **hyperbole**. L'hyperbole suit mieux la forme réelle d'une courbe en V quand le balayage est large. |
| Taille du pas | Pas du focuser entre deux positions. |
| Pas de chaque côté | Positions de chaque côté du départ ; le total est affiché. |
| Position de départ | Centre du balayage. Vide = la position actuelle ; **Utiliser la position actuelle** la remplit. |
| Suivre les mêmes étoiles | Mesurer à chaque pas les étoiles trouvées sur la première pose, plutôt qu'un nouvel ensemble à chaque fois. Résultats plus stables dans un champ pauvre en étoiles. |

Un bon balayage va de nettement flou d'un côté à nettement flou de l'autre. Si la courbe paraît
plate, augmentez la taille du pas ; si les étoiles disparaissent aux extrémités, réduisez-la.

**Pose** : **Durée**, **Binning**, **Gain** (vide = défaut du pilote) et **Filtre** (**Garder
l'actuel** ou une position). Quelques secondes suffisent, de quoi voir une dizaine d'étoiles.

## Lancer

Cliquez sur **Lancer l'autofocus**. Pendant le déroulement :

- l'image du pas en cours est affichée (bascule **Étirement auto** / **Linéaire**) ;
- le graphique **Courbe en V** se remplit point par point (cliquez sur un point pour voir son
  image) ;
- **Progression** donne le pas, la position et le nombre d'étoiles ;
- la barre d'état montre l'opération.

**Interrompre** l'arrête et ramène le focuser à son point de départ.

À la fin, la courbe ajustée est tracée et le focuser va à la **Position optimale**. Le
**Résultat** l'affiche, avec la meilleure HFD/FWHM et l'écart à la position de départ ; la règle
montre le départ, l'optimum et la position actuelle.

Le [Séquenceur](../../sequencer/docs/fr.md) peut lancer l'autofocus avant une cible, après
chaque changement de filtre, après un retournement au méridien, toutes les N minutes ou quand la
température change.
