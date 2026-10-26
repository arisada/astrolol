# Options

Des réglages qui valent pour toute l'application. Ils sont gardés sur le serveur : tous les
navigateurs voient les mêmes.

## Langue

**Langue de l'interface** : anglais ou français.

## Palette

**Palette de couleurs** : *Minuit* (par défaut), *Atlas*, *Graphite*, *Vide*, *Nébuleuse*,
*Mono*, *Braise*, et deux palettes pour le télescope qui préservent la vision nocturne :
*Rouge nuit* et *Cramoisi nuit*.

## Enregistrement des images

Où et sous quel nom les images sont enregistrées quand *Enregistrer les poses* est activé (sur la
page [Imagerie](imaging.md)) et par le [Séquenceur](../../astrolol/plugins/sequencer/docs/fr.md).

- **Dossier d'enregistrement** : un modèle de dossier. Par défaut : `~/astrolol_pictures/%D`
  (un dossier par date).
- **Modèle de nom de fichier** : sans extension ; `.fits` est ajouté. Par défaut :
  `%F_%N_%Es_%Gg`.

Un **Exemple** montre ce que donnent les modèles actuels. Cliquez sur **Afficher la liste des
jetons** pour la liste :

| Jeton | Remplacé par |
|---|---|
| `%D` | Date (AAAA-MM-JJ) |
| `%T` | Heure (HHMMSS) |
| `%U` | Dossier personnel |
| `%O` | Nom de l'objet / de la cible |
| `%F` | Type d'image (light/dark/flat/bias) |
| `%N` | Compteur (6 chiffres, par caméra) |
| `%C` | Nom de la caméra (ID de l'appareil) |
| `%f` | Nom du filtre (vide sans roue à filtres) |
| `%E` | Temps de pose (secondes) |
| `%G` | Gain |

Par exemple `%U/astro/%O/%D` avec `%F_%f_%Es_%N` donne
`/home/moi/astro/M 31/2026-10-13/light_Ha_300s_000042.fits`.

## Serveur INDI

- **Serveur** : le serveur qui pilote vos appareils INDI, et s'il est démarré par astrolol. Par
  défaut, astrolol démarre *indiserver* à la connexion du premier appareil. Il peut aussi
  utiliser les pilotes [INDIGO](https://www.indigo-astronomy.org), ou un serveur que vous lancez
  vous-même ; cela se règle là où astrolol est installé (variables d'environnement, par ex. dans
  son fichier de service) et prend effet à son démarrage :
  - `ASTROLOL_INDI_SERVER_KIND=indigo` : INDIGO au lieu d'indiserver (la page Équipement
    propose alors les pilotes INDIGO). `ASTROLOL_INDIGO_SERVER_PATH` si `indigo_server` est
    introuvable.
  - `ASTROLOL_INDI_MANAGE_SERVER=false`, avec `ASTROLOL_INDI_HOST` et `ASTROLOL_INDI_PORT`
    (7624 par défaut) : un serveur que vous démarrez vous-même, éventuellement sur un autre
    ordinateur.
- **Dossier d'exécution** : où le serveur INDI garde ses fichiers de contrôle.
- **Transfert d'images local** : le pilote écrit les images directement sur le disque au lieu de
  les envoyer par la connexion réseau. Plus rapide, surtout avec de grands capteurs. Le
  **Dossier de dépôt** est l'endroit où le pilote les écrit.
- **Journal du protocole INDI** : *Désactivé*, *Balises seulement* ou *XML complet*. Enregistre
  les échanges avec les pilotes dans le [journal](logs.md). Pour le dépannage uniquement ;
  revient à Désactivé au redémarrage.
- **Mode faible mémoire** : traite une image ou une résolution astrométrique à la fois.
  Activez-le sur un Raspberry Pi ou un autre ordinateur avec peu de mémoire, si astrolol est
  tué pendant le téléchargement des images.

## Modules

Liste toutes les fonctions activables, groupées comme le menu (Équipement, Astronomie,
Réglages), avec une description. Cochez ou décochez, puis cliquez sur **Redémarrer
maintenant** : les changements prennent effet après un redémarrage (*Redémarrage nécessaire
pour prendre effet*).

Certains modules en entraînent d'autres : *Cible* a besoin du catalogue d'objets, l'*Assistant
de flats* du *Séquenceur*. Ne choisissez qu'un seul guideur : *Guideur intégré*, *Guidage
PHD2* ou *Simulateur de guidage*.

## Serveur

- **Redémarrer astrolol** : redémarre l'application. Les appareils sont reconnectés via le
  profil actif.
- **Arrêter le serveur INDI** : arrête le serveur INDI (indiserver ou INDIGO) et tous ses
  pilotes. Utile si un pilote est bloqué ; il redémarre à la prochaine connexion d'un appareil
  INDI.
