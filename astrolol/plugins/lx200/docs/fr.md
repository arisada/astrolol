# Serveur LX200

*Module : Serveur LX200.* Se fait passer pour un télescope Meade LX200 sur le réseau, ce que
comprennent presque tous les logiciels de planétarium : SkySafari, Cartes du Ciel, Stellarium,
TheSkyX, Voyager… Le logiciel montre où pointe le télescope et peut l'envoyer vers un objet. Les
coordonnées sont échangées en J2000. Pour Stellarium, vous pouvez aussi utiliser le
[Serveur Stellarium](../../stellarium/docs/fr.md).

Cliquez sur **Démarrer** ; la page affiche le **Port** et les clients connectés.

Remplacez `astrolol-host` ci-dessous par l'adresse de l'ordinateur du télescope.

| Logiciel | Réglages |
|---|---|
| SkySafari | Réglages → Télescope → Configuration. Type **Meade LX200 Classic**, monture **Alt-Az** ou **Équatoriale**, connexion via **WiFi** à `astrolol-host` et au port. |
| Cartes du Ciel | Télescope → Configuration, pilote **Meade LX200**, connexion **TCP**, hôte `astrolol-host`, le port. |
| Stellarium | Contrôle des télescopes → Ajouter un télescope, type **TCP**, hôte `astrolol-host`, le port. |

**GoTo** fait pointer la monture, **Sync** corrige son pointage, **Stop / Abort** interrompt un
pointage.
