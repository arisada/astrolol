# Visionneuse

*Module : Visionneuse.* Parcourez et prévisualisez toutes les images capturées par astrolol, sans
copier de fichiers depuis l'ordinateur du télescope.

![Visionneuse](viewer.png)

## Parcourir

Les images sont groupées par nuit, cible, filtre, pose, binning et gain
(*IC 1795 · 120s · bin1 · gain200 — 2026-10-01 · 130 images · 4h20m*). Dépliez un groupe pour
voir ses images : heure de capture, nom de fichier, taille, nombre d'étoiles et HFR. Activez
**Liste à plat (non groupée)** pour voir toutes les images dans une seule liste.

Actions sur une image :

- **Voir** l'ouvre en grand. Les flèches du clavier passent à l'image précédente et suivante,
  Échap ferme. Le panneau latéral montre l'objet, le type d'image, l'heure de capture, la pose,
  le gain, le binning, le filtre, la caméra, le télescope, la température du capteur, l'AD / Dec
  et la qualité (étoiles, HFR). L'AD / Dec est la position résolue astrométriquement si l'image a
  été résolue, sinon la position annoncée par la monture. **Télécharger le FITS d'origine**
  enregistre le fichier sur votre appareil.
- **Définir comme cible** (le réticule) fait des coordonnées de l'image la cible de la monture,
  sans pointer ; pratique pour retrouver le même cadrage une autre nuit. Sur un groupe, ce sont
  les coordonnées du groupe.
- **Rejeter** (la corbeille) déplace le fichier dans un dossier `_rejected/`. Il n'est pas
  supprimé.

## Filtres

**Type d'image**, **Objet**, **Recherche (objet ou nom de fichier)**, une plage de dates
**Du** / **Au**. **Effacer les filtres** les remet à zéro.

## Totaux par objet

Le temps d'intégration accumulé sur chaque objet : nombre d'images light, durée totale et nombre
de nuits. Utile pour savoir où en est un projet au long cours.

## Réglages de la bibliothèque

- **Dossier de la bibliothèque** : le dossier indexé par la visionneuse, normalement celui où
  astrolol enregistre les images. Le modifier relance une analyse et oublie les images hors du
  nouveau dossier.
- **Réanalyser la bibliothèque** : prend en compte les fichiers ajoutés ou retirés à la main.
- **Images indexées** et **Disque libre**.
- Images **Rejetées** : **Restaurer** l'une d'elles, ou **Vider les rejetées (définitif)** pour
  toutes les supprimer pour de bon.
