# Mise en station

*Module : Mise en station polaire.* Deux façons d'aligner l'axe polaire de la monture sur le pôle
céleste : un réticule de lunette polaire, et un assistant de résolution astrométrique qui mesure
l'erreur et vous guide pendant que vous tournez les vis de réglage. Une monture et une caméra
doivent être connectées, et le site renseigné dans le profil actif.

![Mise en station](polar_align.png)

## Réticule de la lunette polaire

Pour les montures équipées d'une lunette polaire. Le point indique où la Polaire doit se trouver
sur le réticule en ce moment, avec son **Angle**.

1. Arrêtez le suivi.
2. Tournez l'axe AD à la main jusqu'à ce que le réticule de votre lunette polaire soit orienté
   comme le dessin.
3. Avec les vis de hauteur et d'azimut, amenez la Polaire là où est le point.

**Supposer une lunette inverseuse classique** est activé par défaut : la plupart des lunettes
polaires montrent le ciel tourné de 180°. Ne le désactivez que si la vôtre montre le ciel à
l'endroit.

## Assistant de résolution astrométrique

Plus précis, et il fonctionne sans voir le pôle (l'hémisphère sud n'a pas d'étoile polaire
brillante). Il faut que la [résolution astrométrique](../../platesolve/docs/fr.md) soit
configurée.

**Réglages**

- **Caméra**, **Pose**, **Binning** : pour les résolutions. La caméra principale comme la
  caméra de guidage conviennent.
- **Déc (°)** : la déclinaison des trois points. Laissez *Auto* pour que l'assistant en choisisse
  une bonne.
- **Revérifications pendant le réglage** : pose et rayon de recherche utilisés pendant que vous
  tournez les vis. Une pose courte et un petit rayon rendent chaque mesure plus rapide. Le rayon
  s'élargit tout seul quand l'erreur initiale est grande.

**Déroulement**

1. Cliquez sur **Lancer le calcul sur 3 points**. La monture pointe trois positions à la même
   déclinaison, du côté du méridien vers lequel elle pointe, et résout à chacune (*Point 1 / 3*…).
2. Le **Calcul initial** donne l'erreur avec ce qu'il faut faire, sous forme de flèches (haut ou
   bas pour la vis de hauteur, gauche ou droite pour la vis d'azimut, vu de derrière la monture
   en regardant le pôle) avec l'angle à parcourir en degrés, minutes et secondes d'arc, et une
   appréciation (*Excellente*, *Bonne*, *Correcte*, *À améliorer*).
3. Tournez les vis de hauteur et d'azimut dans le sens des flèches. Cliquez ensuite sur
   **Revérifier maintenant** : la **Dernière mesure** montre les flèches de ce qui reste.
   Inutile de repointer. Avec le **Rafraîchissement auto** (toutes les 3 secondes par défaut),
   une mesure est prise sans cliquer ; il continue même si vous fermez la page.
4. Recommencez jusqu'à une appréciation suffisante, puis cliquez sur **Terminé**.

**Vue en direct d'une étoile**

Plus rapide que les revérifications quand l'erreur n'est plus que de quelques minutes d'arc.
Cliquez sur **Lancer la vue en direct** : l'assistant résout le champ une fois, choisit une
étoile brillante et la suit sur la caméra, plusieurs fois par seconde.

- L'**anneau** est l'endroit où l'étoile doit arriver. Tournez les vis jusqu'à ce que l'étoile
  soit dedans.
- La flèche bleue pleine montre comment la vis d'azimut déplace l'étoile, la flèche violette en
  pointillés comment le fait la vis de hauteur. Les flèches sous l'image donnent l'angle restant,
  comme plus haut.
- Quand l'étoile est sur la cible, la page l'indique (à moins de 30″).
- Si des nuages cachent l'étoile, la vue attend et la retrouve à son retour.
- **Pose** est la durée de chaque image : augmentez-la si l'étoile est faible.

Si l'erreur est encore grande, aucune étoile ne reste dans l'image pendant que vous tournez les
vis : la vue le dit. Utilisez les revérifications jusqu'à ce que l'erreur diminue. La vue en
direct et les revérifications partagent la caméra : une seule des deux tourne à la fois.

**Annuler** arrête l'opération ; **Nouveau calcul** recommence (par exemple après avoir déplacé
le trépied).

Conseils : serrez doucement les vis entre les mesures, et ne touchez pas aux embrayages AD ou Dec
pendant l'opération, sinon le calcul n'est plus valable.
