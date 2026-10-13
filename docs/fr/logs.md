# Journaux

Le **Journal des événements** liste ce qu'astrolol a fait et ce qui a mal tourné, en direct :
connexions d'appareils, poses, pointages, guidage, résolutions astrométriques, autofocus,
erreurs.

## Filtrer

Les pastilles du haut filtrent la liste :

- **Tous** affiche tout.
- Une pastille par composant (INDI, appareils, monture, imagerie, focuser, et les modules
  activés qui ont la leur) n'affiche que ce composant. Sélectionnez-en plusieurs pour les voir
  ensemble.
- **Erreurs** affiche les erreurs.

Le compteur à droite indique combien d'événements correspondent sur combien sont gardés.

Seuls les événements les plus récents sont gardés en mémoire. L'historique complet est dans le
fichier `astrolol.log` sur l'ordinateur du télescope ; joignez-le quand vous signalez un
problème.

## Verbosité

La roue dentée ouvre **Verbosité des journaux** : un interrupteur par composant. Passez un
composant en **debug** pour voir ses messages détaillés pendant que vous cherchez un problème.
Ces interrupteurs sont **réinitialisés au redémarrage**, vous ne pouvez donc pas en oublier un.

Pour voir les échanges bruts avec les pilotes INDI, utilisez *Journal du protocole INDI* dans
les [Options](options.md#serveur-indi).
