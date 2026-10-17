# Système

*Module : Système.* S'occupe de l'ordinateur sur lequel tourne astrolol, typiquement un
Raspberry Pi sur le terrain.

## État de santé

- **Système** : plateforme, disponibilité, charge CPU, mémoire, disque système, température.
- **Alimentation** : si l'ordinateur est ou a été en **sous-tension**, **bridé**, en
  **fréquence limitée** ou à sa **limite de température logicielle**, maintenant et depuis le
  démarrage. Un Raspberry Pi sous-alimenté corrompt des téléchargements et perd des appareils
  USB : la barre d'état affiche alors un indicateur d'alerte. **Surveiller le bridage** écrit
  aussi un avertissement dans les journaux, à l'**Intervalle de vérification** choisi.
- **Stockage** : l'espace libre. À vérifier avant une longue nuit.
- **Périphériques USB** : ce qui est branché, pour vérifier qu'une caméra ou une monture est
  bien vue.

## Réseau

Nécessite NetworkManager sur l'ordinateur.

- La connexion actuelle : **Wi-Fi** (nom du réseau, adresse IP, passerelle), **Hotspot**, ou
  **Hors ligne**.
- **Rechercher des réseaux**, en choisir un, saisir le **Mot de passe** et **Connecter**.
- **Démarrer le hotspot** transforme l'ordinateur en point d'accès Wi-Fi, pour le terrain où il
  n'y a pas de réseau : connectez votre téléphone dessus et ouvrez astrolol. **Arrêter le
  hotspot** revient au réseau habituel. **Réglages du hotspot** : nom du réseau, mot de passe,
  interface.
- **Réseau au démarrage** choisit ce qui se passe sans vous : **Automatique** rejoint un réseau
  Wi-Fi connu (à la maison) et ouvre le hotspot quand aucun n'est à portée (sur le terrain) ;
  **Wi-Fi seul** ne l'ouvre jamais de lui-même ; **Hotspot** l'ouvre toujours. Après chaque
  démarrage, **Wi-Fi d'abord pendant** garde le hotspot fermé pour que votre réseau maison puisse
  toujours se connecter : c'est votre porte d'entrée si le hotspot dysfonctionne. Si le Wi-Fi
  est perdu en cours de route, il attend **Attente après perte du Wi-Fi** avant d'ouvrir le
  hotspot. Une connexion par câble compte comme connectée. Un hotspot que vous avez arrêté
  vous-même n'est pas rouvert tant que vous ne changez pas ce réglage. De retour à la maison,
  redémarrez l'ordinateur ou appuyez sur **Arrêter le hotspot** pour revenir à votre réseau.
- **Connexions WiFi enregistrées** : les réseaux connus, en connexion automatique ou manuelle ;
  supprimez ceux dont vous n'avez plus besoin.

La barre d'état affiche le mode réseau, pour savoir à quel réseau se connecter.

## Nom d'hôte, heure et fuseau horaire

- **Nom d'hôte** : le nom de l'ordinateur sur le réseau (un redémarrage est nécessaire pour
  qu'il prenne pleinement effet).
- **Heure et fuseau horaire** : heure locale, UTC, fuseau horaire et état de la synchronisation
  de l'horloge. Une heure et un fuseau horaire corrects comptent pour tous les calculs du ciel ;
  sur le terrain sans Internet, vérifiez l'heure avant de commencer.

## Commandes

**Redémarrer l'application**, **Redémarrer l'appareil**, **Éteindre l'appareil**. Cliquez une fois
pour armer, une seconde fois pour confirmer. Le redémarrage et l'extinction de l'appareil
nécessitent les permissions listées sous **Permissions sudo**, avec les commandes pour les
configurer.

## Développement

**Git pull** et **Reconstruire l'interface** mettent à jour une installation faite à partir du
code source. Redémarrez ensuite l'application pour exécuter le nouveau code du serveur ;
rechargez la page après une reconstruction de l'interface.
