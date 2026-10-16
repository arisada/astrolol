# Guide d'utilisation d'astrolol

astrolol tourne sur un petit ordinateur relié à votre télescope (un Raspberry Pi, un mini-PC, un
portable) et pilote la monture, les caméras, le focuser et la roue à filtres. Vous l'utilisez
depuis un navigateur web, sur n'importe quel téléphone, tablette ou ordinateur du même réseau.
Plusieurs personnes peuvent suivre la même session en même temps ; ce que l'une fait s'affiche en
direct chez toutes les autres.

![astrolol sur un téléphone](../images/mobile.jpeg)

## Pour commencer

1. [Premiers pas](getting-started.md) : ouvrir astrolol, connecter un premier appareil,
   constituer l'inventaire, créer un profil.
2. [L'interface](interface.md) : menu, barre d'état, palettes, langues, utilisation sur
   téléphone.

## Écrans principaux

| Écran | À quoi il sert |
|---|---|
| [Matériel](equipment.md) | Connecter les appareils et tenir l'inventaire de tout votre matériel |
| [Profils](profiles.md) | Décrire un setup sous forme d'arborescence et le connecter en un clic |
| [Imagerie](imaging.md) | Une page par caméra : poser, boucler, refroidir, faire la mise au point, changer de filtre |
| [Monture](mount.md) | Position, GoTo, synchronisation, suivi, parcage, limites du méridien et d'horizon, corrections |
| [Journaux](logs.md) | Tout ce qui s'est passé, avec une verbosité réglable par composant |
| [Dock](dock.md) | Panneau latéral qui garde quelques indicateurs sous les yeux sur chaque page |
| [Options](options.md) | Langue, palette, emplacement des images, serveur INDI, modules |

## Fonctions (modules)

La plupart des fonctions sont des modules. Ils sont désactivés tant que vous ne les activez pas
dans [Options → Modules](options.md#modules) puis redémarrez astrolol.

**Observation**

| Page | À quoi elle sert |
|---|---|
| [Cible](../../astrolol/plugins/target/docs/fr.md) | Trouver un objet, voir quand il est visible, y pointer la monture, gérer des favoris |
| [Résolution astrométrique](../../astrolol/plugins/platesolve/docs/fr.md) | Savoir où pointe vraiment le télescope, synchroniser et recentrer |
| [Mise en station](../../astrolol/plugins/polar_align/docs/fr.md) | Réticule du viseur polaire et mise en station en trois points par résolution astrométrique |
| [Autofocus](../../astrolol/plugins/autofocus/docs/fr.md) | Trouver la meilleure mise au point avec une courbe en V |
| [Guideur](../../astrolol/plugins/guider/docs/fr.md) | L'autoguideur intégré |
| [Guidage PHD2](../../astrolol/plugins/phd2/docs/fr.md) | Utiliser PHD2 comme guideur |
| [Séquenceur](../../astrolol/plugins/sequencer/docs/fr.md) | Planifier une nuit : cibles, poses, guidage, dithering, retournements, journal |
| [Assistant de flats](../../astrolol/plugins/flat_wizard/docs/fr.md) | Trouver la bonne pose de flat pour chaque filtre et mettre les flats en file |
| [Visionneuse](../../astrolol/plugins/viewer/docs/fr.md) | Parcourir toutes les images capturées |

**Équipement**

| Page | À quoi elle sert |
|---|---|
| [EQMOD](../../astrolol/plugins/eqmod/docs/fr.md) | Pilote natif pour les montures Sky-Watcher |
| [Bluetooth série](../../astrolol/plugins/bluetooth_serial/docs/fr.md) | Appairer un adaptateur série Bluetooth (par ex. un câble EQMOD sans fil) |
| [Serveur Stellarium](../../astrolol/plugins/stellarium/docs/fr.md) | Suivre et piloter la monture depuis Stellarium |
| [Serveur LX200](../../astrolol/plugins/lx200/docs/fr.md) | Suivre et piloter la monture depuis SkySafari, Cartes du Ciel et d'autres logiciels de planétarium |
| [Simulateur de guidage](../../astrolol/plugins/guide_simulator/docs/fr.md) | Un faux guideur pour répéter sans matériel |

**Réglages**

| Page | À quoi elle sert |
|---|---|
| [Sécurité](../../astrolol/plugins/security/docs/fr.md) | Comptes, accès invité, jetons d'API |
| [Système](../../astrolol/plugins/system/docs/fr.md) | Wi-Fi et point d'accès, température, alimentation, fuseau horaire, redémarrage |
| [mDNS](../../astrolol/plugins/mdns/docs/fr.md) | Permettre aux applications de trouver astrolol sur le réseau local |
| [Assistants IA](../../astrolol/plugins/mcp/docs/fr.md) | Laisser Claude et d'autres assistants IA regarder et piloter l'installation |

## Installation

L'installation d'astrolol sur l'ordinateur du télescope est décrite dans le
[guide de déploiement sur Raspberry Pi](../raspberry-pi-deployment.md) (en anglais).
