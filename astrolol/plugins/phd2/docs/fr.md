# Guidage PHD2

*Module : Guidage PHD2.* Permet à astrolol d'utiliser [PHD2](https://openphdguiding.org/) comme
guideur : affiche son état et son graphique de guidage, lance et arrête le guidage, et fait le
dithering entre les images. Ne l'activez pas en même temps que le
[Guideur intégré](../../guider/docs/fr.md) ou le
[Simulateur de guidage](../../guide_simulator/docs/fr.md).

PHD2 est un programme séparé, sur l'ordinateur du télescope ou sur une autre machine. Dans PHD2,
activez **Outils → Activer le serveur** (*Tools → Enable Server*). PHD2 se connecte lui-même à la
caméra de guidage et à la monture ; avec une monture [EQMOD](../../eqmod/docs/fr.md), choisissez
*astrolol Mount Proxy* comme monture dans PHD2.

## Connexion

Ouvrez les réglages (**Réglages du graphique et du débogage**), renseignez l'**Hôte PHD2**
(`localhost` si PHD2 tourne sur l'ordinateur du télescope) et le **Port PHD2** (4400 par
défaut), puis cliquez sur **Connecter**.

## La page

- **État** : *Boucle*, *Calibration*, *Guidage*, *Stabilisation*, *Étoile perdue*, *En pause*,
  *Arrêté*…
- **Graphique d'erreur de guidage** en arcsecondes, avec le **RMS AD**, le **RMS Dec**, le **RMS
  moyen**, le **SNR de l'étoile** et l'**Échelle de pixel**.
- **Guider** lance le guidage (PHD2 se calibre d'abord si besoin), **Pause** / **Reprendre**,
  **Stop**.
- **Un dither** déplace un peu la position de guidage et attend que PHD2 se stabilise.

Réglages : **Échelle verticale du graphique**, **Échantillons affichés**, et **Journal de débogage
PHD2** (enregistre les échanges avec PHD2 pour le dépannage).

Le dithering automatique entre les images se règle sur la page
[Imagerie](../../../../docs/fr/imaging.md) (pendant une boucle) ou dans le
[Séquenceur](../../sequencer/docs/fr.md).
