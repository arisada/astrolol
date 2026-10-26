# ASCOM Alpaca

Connecte les caméras, montures, focusers, roues à filtres, rotateurs et panneaux de flat
(cover calibrators) qui parlent ASCOM Alpaca par le réseau : les appareils dotés d'Alpaca, les
pilotes ASCOM Windows partagés avec ASCOM Remote, et les simulateurs OmniSim d'ASCOM.

Activez le module dans [Options → Modules](../../../../docs/fr/options.md#modules) (astrolol
redémarre), puis ouvrez **ASCOM Alpaca** dans la partie Équipement du menu.

![La page ASCOM Alpaca](alpaca.jpg)

## Trouver les appareils

La page cherche sur le réseau à son ouverture ; **Chercher à nouveau** recommence. Chaque
serveur Alpaca trouvé est listé avec son nom, son adresse et ses appareils. La recherche atteint
les serveurs du même réseau qu'astrolol ; un serveur ailleurs (un autre sous-réseau, un VPN) peut
être ajouté sous **Serveurs à interroger directement**, sous la forme `hôte` ou `hôte:port`
(port 11111 si aucun n'est indiqué). Ces adresses sont conservées et interrogées à chaque
recherche. Une adresse qui ne répond pas est signalée sous la liste.

Les appareils d'un type qu'astrolol ne gère pas encore (coupoles, interrupteurs, stations météo,
moniteurs de sécurité) sont grisés.

## Connecter un appareil

Chaque appareil a un **ID de l'appareil**, le nom utilisé partout dans astrolol (entrées du
menu, noms de fichiers), et un bouton **Connecter**. L'ID suggéré en gris est utilisé si vous
laissez le champ vide. Une fois connecté, l'appareil affiche **Connecté sous** son ID, et
fonctionne comme tout autre appareil de son type : la caméra sur sa page d'acquisition, la
monture sur la page Monture, etc. Il peut être ajouté à l'inventaire et aux profils depuis la
page [Matériel](../../../../docs/fr/equipment.md), qui le reconnecte de la même façon.

Les appareils peuvent aussi être connectés depuis l'assistant de la page Matériel :
**Autre adaptateur**, l'adaptateur `alpaca_…` de ce type, et où est l'appareil :

```json
{"host": "192.168.1.20", "port": 11111, "device_number": 0}
```

`device_number` distingue plusieurs appareils du même type sur un serveur (0 pour le premier).

## Bon à savoir

- Les caméras Alpaca envoient des pixels et non des fichiers : astrolol écrit le fichier FITS,
  avec la pose, le binning, le gain, la température, la taille des pixels et la matrice de Bayer
  dans son en-tête.
- Les appareils Alpaca ne signalent pas d'eux-mêmes leurs changements : astrolol les interroge,
  une fois par seconde pour la position d'une monture, si bien que l'affichage peut avoir jusqu'à
  une seconde de retard.
- Une monture déplacée à la main est arrêtée quand elle est déconnectée.
