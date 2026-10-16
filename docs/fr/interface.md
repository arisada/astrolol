# L'interface

## Menu

Le menu de gauche est divisé en trois groupes repliables :

- **Équipement** : Matériel, Profils, et les modules liés au matériel (EQMOD, Bluetooth série,
  Stellarium, LX200…).
- **Astronomie** : Cible, Monture, une entrée **par caméra connectée** (au nom de la caméra),
  et les modules d'observation (Résolution astrométrique, Autofocus, Guideur, Séquenceur,
  Visionneuse…).
- **Réglages** : Sécurité, Système, mDNS, Journaux, Options.

Une entrée porte une marque quand il s'y passe quelque chose : un anneau qui pulse doucement
signifie *en cours* (une pose, une séquence, le guidage) ; un point rouge signifie *à vérifier*
(étoile perdue, séquence bloquée). Un groupe replié affiche la marque la plus importante de ses
entrées.

Les flèches en bas du menu le réduisent à ses icônes.

## Barre d'état

La barre du haut affiche en direct l'état de tout ce qui est connecté, par exemple :

```
MOUNT Suivi │ CCD SIMULATOR Inactif │ CCD SIMULATOR Refroidissement -14°C │ GUIDEUR guidage   ADMIN ⇥  EN DIRECT
```

- Un indicateur par appareil : monture (*Pointage*, *Suivi*, *Sans suivi*, *Parquée*), caméra
  (*Inactif*, *Boucle*, *Téléchargement…*, *Refroidissement*), focuser (*Déplacement*),
  rotateur.
- Les modules ajoutent leur propre indicateur quand ils travaillent : séquenceur, guideur,
  autofocus, résolution astrométrique, mise en station, flats, alertes d'alimentation…
- À droite : l'utilisateur connecté (avec un bouton de déconnexion), le bouton **?** de l'aide,
  et l'état de la connexion. **en direct** signifie que les mises à jour arrivent ;
  **reconnexion…** signifie que le navigateur a perdu le serveur et réessaie. Rien n'est perdu
  côté serveur : astrolol continue de travailler même sans navigateur ouvert.

Les états sont toujours écrits en toutes lettres ; la couleur n'est qu'un indice de plus, si bien
que la barre reste lisible avec les palettes rouges de nuit.

## Aide

Le bouton **?** de la barre d'état ouvre ce guide à la page qui décrit l'écran affiché. Les liens
restent dans le panneau d'aide ; **Retour** revient à la page précédente, **Sommaire** à la page
d'accueil du guide, et une icône ouvre la page dans un nouvel onglet.

## Messages

Les erreurs et confirmations s'affichent brièvement en bas de l'écran. Cliquez sur **Fermer**
pour en masquer une ; elle reste masquée après un rechargement de la page.

## Le journal de chaque page

Les pages qui exécutent quelque chose (Imagerie, Monture, Guideur, Séquenceur, PHD2, Résolution
astrométrique) ont une fine bande en bas qui montre la dernière ligne de leur journal. Quand
quelque chose de nouveau est écrit, le journal se déplie par-dessus la page quelques secondes (plus
longtemps pour les alertes et les erreurs) puis se replie ; la page, elle, ne bouge jamais. L'onglet
en bas à gauche le garde ouvert jusqu'à ce que vous le repliez ; chaque page le retient séparément. Glissez son bord supérieur pour
l'agrandir ; il suit la ligne la plus récente sauf si vous remontez, et **Dernier** vous y ramène. La
page [Journaux](logs.md) liste tout.

## Propriétés des appareils

Sur les pages Imagerie et Monture, la petite roue dentée à côté du nom d'un appareil ouvre les
**Propriétés de l'appareil** : tous les réglages exposés par le pilote INDI, groupés comme le
pilote les groupe, ainsi que les **messages** envoyés par le pilote. Servez-vous-en pour tout ce
qu'astrolol n'affiche pas sur ses propres pages (bande passante USB, mode de lecture, options
propres au pilote). Changez une valeur et cliquez sur **Appliquer**.

## Palettes et langues

Options → **Palette** change les couleurs. *Rouge nuit* et *Cramoisi nuit* préservent votre
vision nocturne au télescope. Options → **Langue** bascule entre l'anglais et le français. Les
deux choix sont gardés par le serveur : tous les navigateurs ont le même réglage.

## Téléphones et tablettes

astrolol s'utilise sur un téléphone. Sur un écran étroit, les panneaux latéraux se replient
(la flèche en haut d'un panneau l'ouvre ou le ferme) et le menu devient une rangée d'onglets.

## À plusieurs

Chaque navigateur voit le même état en direct. Si la
[Sécurité](../../astrolol/plugins/security/docs/fr.md) est activée, chacun se connecte avec son
propre niveau : les lecteurs regardent, les opérateurs pilotent le télescope, les
administrateurs changent aussi les réglages, les modules et le matériel.
