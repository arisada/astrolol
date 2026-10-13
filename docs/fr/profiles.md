# Profils

*Un profil est un nom et une arborescence de matériel. Activez-le pour connecter les appareils.*

Vous pouvez avoir un profil par setup, par lieu ou par configuration : *Jardin*,
*Setup nomade*, *Site noir avec le gros télescope*. Un seul profil est actif à la fois.

![Profils](../images/profiles.png)

## Créer un profil

1. Cliquez sur **Nouveau profil**.
2. Saisissez un **Nom du profil** et cliquez sur **Créer le profil**.
3. Dépliez le profil et construisez son **Arborescence du matériel**.

Les éléments viennent de l'[inventaire](equipment.md#inventaire) : ajoutez-y d'abord votre
matériel.

## Arborescence du matériel

L'arborescence reproduit la façon dont votre matériel est physiquement assemblé. **Ajouter à
l'arborescence** ajoute un élément de premier niveau (normalement le site). Le **+** à côté d'un
élément (*Rattacher un élément enfant*) ajoute quelque chose dessous ; *Retirer de
l'arborescence* l'enlève de l'arborescence (il reste dans l'inventaire). Chaque élément de
l'inventaire ne peut figurer qu'une fois dans une arborescence.

Ce qui peut aller sous quoi :

| Élément | Peut contenir |
|---|---|
| Site d'observation | Monture, GPS |
| Monture | Télescope / OTA |
| Télescope / OTA | Caméra, Focuser, Rotateur, Roue à filtres, un autre Télescope (par ex. une lunette de guidage montée en parallèle du principal) |
| Rotateur | Focuser, Roue à filtres, Caméra |
| Focuser | Roue à filtres, Caméra |
| Roue à filtres | Caméra |
| Caméra | rien |

Une arborescence typique avec un télescope principal et une lunette de guidage :

```
Site
└── Monture
    ├── Télescope principal
    │   └── Focuser
    │       └── Roue à filtres
    │           └── Caméra principale
    └── Lunette de guidage
        └── Caméra de guidage
```

Chaque chemin d'un télescope jusqu'à une caméra est un **chemin optique**. astrolol s'en sert
pour :

- afficher, sur la page [Imagerie](imaging.md) d'une caméra, le focuser et la roue à filtres
  placés devant *cette* caméra ;
- connaître la focale devant chaque caméra (échantillonnage pour la résolution astrométrique, le
  guidage et les en-têtes FITS) ;
- savoir quelle roue à filtres le
  [Séquenceur](../../astrolol/plugins/sequencer/docs/fr.md), l'[Autofocus](../../astrolol/plugins/autofocus/docs/fr.md)
  et l'[Assistant de flats](../../astrolol/plugins/flat_wizard/docs/fr.md) doivent piloter pour
  une caméra donnée ;
- donner à la monture sa position et l'heure à partir du site.

## Activer

Cliquez sur **Activer** sur un profil. astrolol :

- connecte chaque appareil de son arborescence et affiche *Profil activé* ou *Activé avec des
  erreurs* (chaque appareil en échec est listé avec la raison) ;
- envoie la position du site à la monture ;
- inscrit le télescope et le site dans les en-têtes FITS de chaque image prise.

Le profil actif est marqué **actif**. Sur le profil actif, le bouton devient **Recharger** : il
reconnecte l'arborescence, pratique après avoir rebranché un appareil.

Au redémarrage, astrolol réactive le dernier profil actif et reconnecte ses appareils.

## Autres actions

- **Modifier** : renommer le profil.
- La corbeille supprime le profil. Les éléments de l'inventaire ne sont pas touchés.
