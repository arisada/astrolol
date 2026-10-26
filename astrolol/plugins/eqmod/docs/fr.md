# EQMOD

*Module : Monture EQMOD.* Un pilote pour les montures Sky-Watcher (EQ5, HEQ5, EQ6, AZ-EQ6,
EQ8…) intégré à astrolol. Il se connecte par un câble EQMOD, par le port USB de la monture ou
par un adaptateur Bluetooth, et comprend aussi un simulateur de monture.

## Connecter la monture

Dans [Matériel](../../../../docs/fr/equipment.md), **Charger un pilote** → **Monture** →
**Autre adaptateur** → `eqmod`, avec des paramètres de connexion comme :

```json
{"port": "/dev/ttyUSB0"}
```

Paramètres facultatifs :

- `"baudrate"` : évite la détection de la vitesse (9600 pour un câble EQMOD, 115200 pour l'USB
  intégré de l'AZ-EQ6).
- `"ra_reverse"` / `"dec_reverse"` : `true` si une correction déplace la monture dans le mauvais
  sens.
- `"guide_rate"` : vitesse de guidage en fraction de la vitesse sidérale (0,5 par défaut).

Pour essayer sans monture, choisissez l'adaptateur du simulateur (`eqmod_sim`).

Importez-la ensuite dans l'inventaire et ajoutez-la à votre profil. Le site du profil donne sa
position à la monture ; les limites du méridien et d'horizon se règlent sur la page
[Monture](../../../../docs/fr/mount.md).

## La page EQMOD

Monture connectée, la page montre ce que rapporte la carte moteur : port et vitesse, version de
la carte, état du suivi, vitesse de guidage, limite du méridien et distance à cette limite, site,
position de parcage et décalage de synchronisation. Chaque axe montre sa position en pas codeur
et en degrés depuis l'origine, et son état (*en marche*, *bloqué*…). Utile quand quelque chose
ne bouge pas comme prévu.

## Réglages

- **LED du viseur polaire** : la luminosité de l'éclairage du viseur polaire, sur les montures
  qui en ont un.
- **Proxy de monture INDI** : rend la monture visible des programmes INDI, sous le nom
  *astrolol Mount Proxy* sur le serveur INDI d'astrolol (port 7624).
  - **PHD2** : connectez-vous au serveur INDI de l'ordinateur du télescope, choisissez votre
    caméra de guidage INDI, puis *astrolol Mount Proxy* comme monture.
  - Les pilotes INDI qui lisent la position du télescope (pour les en-têtes FITS, ou le champ
    d'étoiles du simulateur CCD) : réglez leur télescope sur *astrolol Mount Proxy*.
  - Quand astrolol utilise un serveur INDIGO, la monture y apparaît sous le nom
    *astrolol Mount Proxy @ astrolol-indi-mount-proxy*. Le serveur INDIGO ne prend le proxy
    qu'à son démarrage : l'activer ou le désactiver redémarre le serveur, ou attend qu'aucun
    appareil n'y soit connecté. Cela ne fonctionne qu'avec un serveur INDIGO démarré par astrolol.

## Connexion par Bluetooth

Pour un adaptateur Bluetooth à la place du câble : appairez-le d'abord sur la page
[Bluetooth série](../../bluetooth_serial/docs/fr.md), puis choisissez-le ici et cliquez sur
**Appliquer** pour votre monture EQMOD. Reconnectez la monture (ou rechargez le profil) pour que
cela prenne effet.
