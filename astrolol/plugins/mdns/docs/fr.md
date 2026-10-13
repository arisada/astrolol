# mDNS

*Module : Découverte mDNS.* Annonce astrolol sur le réseau local, pour que les applications
(comme l'application Android) le trouvent sans que vous saisissiez d'adresse IP.

astrolol ne peut pas deviner l'adresse que les clients doivent utiliser, surtout quand il est
derrière un serveur web qui fournit le HTTPS ; vous la renseignez donc ici :

| Réglage | |
|---|---|
| Nom de l'instance | Le nom affiché dans les applications. Par défaut, le nom de l'ordinateur. |
| Hôte annoncé | Une adresse IP ou un nom d'hôte. Laissez vide pour utiliser l'adresse locale de l'ordinateur. |
| Port annoncé | **Obligatoire** : rien n'est annoncé tant qu'il n'est pas défini. 443 derrière un serveur web en HTTPS, 8000 sans. |
| Schéma | `http` ou `https`. |

**Utiliser l'adresse de cette page** remplit les champs à partir de l'adresse utilisée pour
ouvrir astrolol, ce qui est en général correct.

Cliquez sur **Enregistrer**, puis **Redémarrer astrolol** pour que le changement prenne effet.
