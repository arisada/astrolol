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

- **Caméra**, **Pose (s)**, **Binning** : pour les résolutions. La caméra principale comme la
  caméra de guidage conviennent.
- **Déc (°)** : la déclinaison des trois points. Laissez *Auto* pour que l'assistant en choisisse
  une bonne.
- **Revérifications pendant le réglage** : pose et rayon de recherche utilisés pendant que vous
  tournez les vis. Une pose plus courte et un petit rayon rendent chaque mesure plus rapide.
  Laissez la pose vide pour reprendre celle du dessus.

**Déroulement**

1. Cliquez sur **Lancer le calcul sur 3 points**. La monture pointe trois positions à la même
   déclinaison, du côté du méridien vers lequel elle pointe, et résout à chacune (*Point 1 / 3*…).
2. Le **Calcul initial** donne l'erreur en minutes d'arc, avec ce qu'il faut faire : *trop haut —
   baissez le réglage en hauteur*, *à l'ouest du vrai nord — augmentez l'azimut*, etc., et une
   appréciation (*Excellente*, *Bonne*, *Correcte*, *À améliorer*).
3. Tournez les vis de hauteur et d'azimut dans le sens indiqué. Cliquez ensuite sur
   **Revérifier maintenant** : la **Dernière mesure** montre l'erreur restante. Inutile de
   repointer. Avec le **Rafraîchissement auto**, une mesure est prise toutes les quelques
   secondes sans cliquer ; il continue même si vous fermez la page.
4. Recommencez jusqu'à une appréciation suffisante, puis cliquez sur **Terminé**.

**Annuler** arrête l'opération ; **Nouveau calcul** recommence (par exemple après avoir déplacé
le trépied).

Conseils : serrez doucement les vis entre les mesures, et ne touchez pas aux embrayages AD ou Dec
pendant l'opération, sinon le calcul n'est plus valable.
