# Autofocus

*Module : Autofocus.* Déplace le focuser sur une série de positions, mesure les étoiles à
chacune et va à la position la plus nette. Une caméra et un focuser doivent être connectés.

## Réglages

Chaque modification est enregistrée aussitôt, et la page s'ouvre sur la dernière caméra
utilisée. Le [séquenceur](../../sequencer/docs/fr.md) lance son propre autofocus avec ces mêmes
réglages : vous pouvez donc les ajuster pendant une séquence, ils s'appliquent dès le prochain
autofocus.

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
| Suivre les mêmes étoiles | Le balayage commence par son centre (la position de mise au point actuelle) et les étoiles les plus brillantes de cette pose sont mesurées à chaque pas, plutôt qu'un nouvel ensemble à chaque fois. Résultats plus stables dans un champ pauvre en étoiles, ou avec des images faibles en bande étroite où le bruit peut passer pour des étoiles. Partir d'une position proche de la mise au point. |

Un bon balayage va de nettement flou d'un côté à nettement flou de l'autre. Si la courbe paraît
plate, augmentez la taille du pas ; si les étoiles disparaissent aux extrémités, réduisez-la.

**Pose** : **Durée**, **Binning**, **Gain** (vide = défaut du pilote) et **Filtre** (**Garder
l'actuel** ou une position). Quelques secondes suffisent, de quoi voir une dizaine d'étoiles.

**Résultats douteux** : que faire quand la courbe semble peu fiable. Chaque cause a son choix :
**garder** (utiliser le résultat en le signalant), **réessayer** (mesurer à nouveau) ou
**arrêter** (l'opération échoue et le focuser revient à son point de départ).

| Cause | Réessayer signifie |
|---|---|
| Minimum au bord | Balayer à nouveau autour de la meilleure position, jusqu'à deux fois. |
| Courbe plate | Un nouveau balayage avec une pose plus longue, centré sur la meilleure position. |
| Courbe bruitée | Idem. |
| Trop peu d'étoiles | Idem. Un ciel sans aucune étoile n'est pas remesuré ; le séquenceur réessaie plus tard. |

**Nouveaux balayages permis** limite les nouveaux balayages pour les trois dernières causes.
**Pose d'un nouveau balayage** est le multiple de la pose précédente, jusqu'à **Pose maximale**.
Les balayages précédents restent sur le graphique, en gris. Si un résultat ne peut pas du tout être
ajusté, l'opération échoue quel que soit le choix.

## Lancer

Cliquez sur **Lancer l'autofocus**. Pendant le déroulement :

- l'image du pas en cours est affichée (bascule **Étirement auto** / **Linéaire**) ;
- le graphique **Courbe en V** se remplit point par point (cliquez sur un point pour voir son
  image) ;
- **Progression** donne le pas, la position et le nombre d'étoiles ;
- la barre d'état montre l'opération.

Si la position la plus nette n'est pas dans la plage choisie (après un changement de filtre, par
exemple, ou quand la nuit se refroidit), l'autofocus ajoute jusqu'à deux balayages dans cette
direction : le nombre de pas augmente donc pendant l'opération. Le résultat est alors calculé sur
les positions autour de la meilleure. S'il n'est toujours pas trouvé, l'opération s'arrête en
indiquant la direction et le focuser revient à son point de départ : relancez depuis une position
plus proche de la mise au point.

**Interrompre** l'arrête et ramène le focuser à son point de départ.

À la fin, la courbe ajustée est tracée et le focuser va à la **Position optimale**. Le
**Résultat** l'affiche, avec la meilleure HFD/FWHM et l'écart à la position de départ ; la règle
montre le départ, l'optimum et la position actuelle.

Le Résultat dit aussi s'il est digne de confiance : **Fiable**, ou **Douteux** avec la raison :

- le minimum est au bord de la plage mesurée (moins de deux bons points d'un côté), la position
  est donc une estimation ;
- la netteté varie à peine sur le balayage (les étoiles sont probablement trop faibles pour que le
  flou se voie) ;
- les mesures ne suivent pas un V net ;
- plusieurs pas ont trouvé trop peu d'étoiles (nuages, ou cible proche de l'horizon).

**Image de contrôle au résultat** (désactivée par défaut) prend une image de plus au résultat et
compare sa netteté à celle que prédit la courbe : cela teste le résultat, pas seulement
l'ajustement. Une image nettement plus floue, ou sans étoiles, est un résultat douteux en soi, avec
les mêmes choix (par défaut : garder et signaler ; *réessayer* balaie à nouveau autour du
résultat).

Un résultat douteux est utilisé quand même ; le journal du séquenceur en garde le verdict.

Le [Séquenceur](../../sequencer/docs/fr.md) peut lancer l'autofocus avant une cible, après
chaque changement de filtre, après un retournement au méridien, toutes les N minutes ou quand la
température change.
