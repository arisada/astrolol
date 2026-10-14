# mDNS

*Module : Découverte mDNS.* Annonce astrolol sur le réseau local, pour que les applications
(comme l'application Android) le trouvent sans que vous saisissiez d'adresse IP.

Le serveur est annoncé sous le nom de cet ordinateur (`<nom>.local`). Il ne reste à régler que
le port et le schéma, qui changent quand un serveur web fournit le HTTPS devant astrolol :

| Réglage | |
|---|---|
| Nom de l'instance | Le nom affiché dans les applications. Par défaut, le nom de l'ordinateur. |
| Port annoncé | Laissez vide pour le port d'astrolol (8000). Mettez 443 derrière un serveur web en HTTPS. |
| Schéma | `http` ou `https`. |

**Utiliser l'adresse de cette page** remplit le port et le schéma à partir de l'adresse utilisée pour
ouvrir astrolol, ce qui est en général correct.

Cliquez sur **Enregistrer**, puis **Redémarrer astrolol** pour que le changement prenne effet.
