# Assistant de flats

*Module : Assistant de flats (nécessite le [Séquenceur](../../sequencer/docs/fr.md)).* Trouve
la bonne pose des flats pour chaque caméra et chaque filtre, puis met les flats en file dans le
séquenceur.

Installez d'abord votre source de flats (un panneau lumineux, un t-shirt sur le pare-buée à
l'aube…) et pointez le télescope dessus.

## Réglages

**Caméras et filtres.** Chaque caméra connectée, avec une ligne par filtre de sa roue à filtres
(d'après le profil ; *Pas de roue à filtres* sinon). Indiquez le nombre d'**images** pour chaque
combinaison voulue (0 = l'ignorer) et le **Gain** (vide = défaut du pilote).

**Panneau de flats** (affiché quand un panneau de flats est connecté). Activez **Utiliser le
panneau de flats** : l'assistant ferme le cache et allume le panneau devant le télescope de
chaque caméra, prend les essais, puis l'éteint et rouvre le cache. Les flats mis en file font de
même à leur exécution. **Luminosité** est le niveau à utiliser (vide = laisser le panneau tel
quel) ; choisissez-en un qui donne des poses d'une seconde ou plus, un panneau très lumineux
imposant des poses très courtes.

**Cible**

- **Puits de potentiel visé (moyenne)** : la luminosité voulue pour les flats, en part de la
  pleine échelle du capteur. Autour de la moitié est le choix habituel.
- **Tolérance** : à quelle distance de cette valeur c'est assez bon.
- **Garde de saturation** : un essai avec plus que cette part de pixels écrêtés est considéré
  comme trop lumineux.

**Poses d'essai** : **Durée initiale**, **Durée max (limite de sécurité)**, **Binning**,
**Essais max**.

## Lancer

Cliquez sur **Résoudre et mettre les flats en file**. Pour chaque caméra et chaque filtre,
l'assistant prend de courtes poses d'essai et ajuste la durée jusqu'à ce que la luminosité soit
dans la cible. **Essais en direct** montre chaque tentative (durée, luminosité, *saturé*) ;
**Résultats** montre la durée trouvée et le nombre d'essais nécessaires.

Chaque combinaison résolue est ajoutée comme tâche à la file du séquenceur (*Mis en file dans le
séquenceur*), avec le nombre d'images choisi. Démarrez le
[Séquenceur](../../sequencer/docs/fr.md) pour les prendre.

**Interrompre** arrête les essais.
