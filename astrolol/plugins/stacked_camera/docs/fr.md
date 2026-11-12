# Caméra empilée

*Module : Caméra empilée.* Guider et poser longtemps avec la même caméra. Le guideur reçoit une
image courte toutes les quelques secondes, et une pose longue est construite à partir de ces
mêmes images : une seule caméra fait les deux métiers, sans seconde caméra ni lunette de guidage.

## Utilisation

1. Connectez votre caméra dans [Matériel](../../../../docs/fr/equipment.md).
2. Ouvrez **Caméra empilée** et cliquez sur **Utiliser pour guider et photographier** à côté de
   la caméra. Deux caméras apparaissent dans la liste du matériel : celle marquée *prise de vue*
   fait les poses, celle marquée *guidage* donne ses images au guideur.
3. Choisissez la seconde comme caméra de guidage dans le [Guideur](../../guider/docs/fr.md) et
   la première dans [Imagerie](../../../../docs/fr/imaging.md) ou le
   [Séquenceur](../../sequencer/docs/fr.md).

**Ne plus utiliser** déconnecte les deux ; la vraie caméra reste connectée.

## Les garder après un redémarrage

**Utiliser pour guider et photographier** ne connecte les deux caméras que pour la session. Pour
qu'elles soient connectées avec le reste de votre matériel, ajoutez-les à votre
[profil](../../../../docs/fr/profiles.md) :

1. Dans [Matériel](../../../../docs/fr/equipment.md), ajoutez une caméra, choisissez **Autre
   adaptateur**, et indiquez l'adaptateur `stacked_camera_long` (pour la prise de vue) ou
   `stacked_camera_fast` (pour le guidage).
2. Comme **Paramètres de connexion**, donnez l'identifiant de votre vraie caméra, tel qu'il
   apparaît dans Matériel : `{"source_id": "identifiant_de_votre_camera"}`.
3. Placez les deux nouvelles caméras dans l'arbre du matériel du profil, après la vraie caméra,
   pour que celle-ci soit connectée en premier.

## Images courtes

**Durée d'une image courte** est la durée de chaque image. Le guideur corrige une fois par image :
des images plus courtes guident plus vite. Une pose longue est un nombre entier d'images courtes :
300 s avec des images de 2 s font 150 images, et une pose qui n'est pas un multiple est arrondie
au supérieur (le fichier enregistré indique la quantité de lumière réellement collectée). Une
image plus longue ajoute moins de bruit à une pose longue : choisissez la plus longue que votre
guidage permet. Le changement s'applique au prochain démarrage du flux de la caméra.

Réglez la pose du guideur sur la même valeur, pour que ses images de dark correspondent.

## Caméras couleur

À sa connexion, la caméra empilée prend une toute petite photo avec la vraie caméra : les
empilements portent ainsi sa matrice colorée, la taille de ses pixels et son nom, comme ses
propres images. La caméra doit être au repos pour cela : si le guideur diffuse déjà, c'est fait
avant la pose suivante. Les empilements en binning n'ont pas de matrice colorée.

## Pendant l'utilisation

Le cadre **Flux de la caméra** indique si la caméra diffuse des images, combien elle en a
produit, combien ont été perdues en route, et la part du temps où le capteur était en pose
(en dessous de 100 %, la caméra a besoin de temps entre deux images, et ce temps n'est pas
collecté comme lumière). Une pose longue apparaît dans la barre d'état sous *Empilement* avec les
secondes collectées jusqu'ici.

Une pose qui ne peut pas aboutir (la caméra n'envoie plus d'images, ou est débranchée) se termine
par une erreur ; la suivante repart.

## Étalonnage

L'image enregistrée est la simple somme des images courtes, en entiers 32 bits, sans rien
retirer. Prenez les darks de la même façon, bouchon sur l'instrument, avec la même pose et la
même durée d'image courte, et étalonnez comme d'habitude.
