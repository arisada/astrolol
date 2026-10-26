# Premiers pas

Cette page vous mène d'une installation toute neuve à un setup que vous connectez en un clic.
Elle suppose qu'astrolol est déjà installé et lancé sur l'ordinateur du télescope (voir le
[guide de déploiement sur Raspberry Pi](../raspberry-pi-deployment.md), en anglais).

L'idée en bref :

- **Matériel → connexions** : les appareils connectés en ce moment.
- **Matériel → inventaire** : la liste de tout ce que vous possédez : télescopes, caméras,
  montures, votre site d'observation…
- Un **profil** prend des éléments de l'inventaire et les dispose comme ils sont montés
  physiquement (site → monture → télescope → focuser → roue à filtres → caméra). Activer le
  profil connecte tous ses appareils.

Vous ne le faites qu'une fois ; ensuite, une soirée commence par un clic sur **Activer**.

## 1. Ouvrir astrolol

Dans un navigateur, allez à l'adresse de l'ordinateur du télescope, par exemple
`http://astrolol.local:8000`, ou `https://astrolol.local` s'il est derrière un serveur web. Si
vous avez activé le module [mDNS](../../astrolol/plugins/mdns/docs/fr.md), les applications le
trouvent toutes seules sur le réseau.

La première page est **Imagerie**. Sans rien de connecté, elle affiche *Aucune caméra
connectée.* Le menu de gauche liste les écrans ; la barre du haut montre l'état de chaque
appareil, et **en direct** quand le navigateur reçoit les mises à jour (voir
[L'interface](interface.md)).

Si la [Sécurité](../../astrolol/plugins/security/docs/fr.md) est activée, il faut d'abord se
connecter.

## 2. Activer les fonctions voulues

Allez dans **Options → Modules** et cochez les fonctions qui vous intéressent, par exemple
*Cible*, *Résolution astrométrique*, *Autofocus*, *Séquenceur*, *Visionneuse* et un guideur
(*Guideur intégré* ou *Guidage PHD2*, pas les deux). Cliquez ensuite sur **Redémarrer
maintenant**. Les nouvelles pages apparaissent dans le menu.

Vous pouvez revenir à cette liste à tout moment. Voir [Options](options.md#modules).

## 3. Connecter un appareil

Allez dans **Matériel** et restez sur l'onglet **connexions**. Cliquez sur **Charger un
pilote** et répondez aux questions :

1. **Que souhaitez-vous connecter ?** Caméra, Monture, Focuser, Roue à filtres ou Rotateur.
2. **Comment est-il connecté ?**
   - **Parcourir les pilotes INDI** pour presque tous les appareils du commerce. astrolol
     démarre le serveur INDI pour vous.
   - **Autre adaptateur** pour les pilotes fournis par des modules d'astrolol, comme le pilote
     natif [EQMOD](../../astrolol/plugins/eqmod/docs/fr.md) des montures Sky-Watcher, ou pour les
     appareils [ASCOM Alpaca](../../astrolol/plugins/alpaca/docs/fr.md) du réseau.
3. **Choisir le fabricant**, puis **Choisir le modèle**. Si votre appareil n'est pas dans la
   liste, choisissez **Saisir manuellement…** et tapez le nom de son pilote INDI (par exemple
   `indi_asi_ccd`).
4. **Configurer et connecter.** astrolol affiche les réglages que propose le pilote avant la
   connexion : port série, vitesse, etc. La plupart des appareils fonctionnent avec les valeurs
   par défaut. Vous pouvez aussi donner à l'appareil un **ID de l'appareil** court ; laissez-le
   vide pour qu'il soit tiré de son nom.
5. Cliquez sur **Connecter**.

L'appareil apparaît sous **Connectés**. Certains pilotes apportent plusieurs appareils : par
exemple une caméra avec une roue à filtres intégrée. Ceux-là sont marqués *détecté
automatiquement*.

> Astuce : pour essayer astrolol sans matériel, choisissez le fabricant INDI *Simulators* : il
> y a un simulateur de télescope, de caméra CCD, de focuser et de roue à filtres.

## 4. L'ajouter à l'inventaire

Dès qu'un appareil est connecté, astrolol demande *« … est connecté — l'ajouter à votre
inventaire ? »*. Cliquez sur **Importer dans l'inventaire** (ou **Plus tard**). Vous pouvez
aussi le faire plus tard avec le bouton d'import sur la ligne de l'appareil ; un appareil déjà
présent est marqué *Déjà dans l'inventaire*.

L'inventaire retient le pilote utilisé par l'appareil, pour qu'un profil puisse le reconnecter
plus tard sans passer par l'assistant.

Faites-le pour chaque appareil : monture, caméra principale, caméra de guidage, focuser, roue à
filtres.

## 5. Ajouter ce qui ne se connecte pas

Une partie du matériel n'a pas de pilote, mais astrolol doit quand même la connaître. Ouvrez
l'onglet **inventaire** et cliquez sur **Ajouter du matériel** :

- **Site d'observation** : nom, latitude, longitude, altitude, fuseau horaire. Sans site,
  astrolol ne peut ni pointer la monture ni vous dire quand les objets se lèvent et se couchent ;
  l'inventaire vous le rappelle tant qu'il n'y en a pas.
- **Télescope / OTA** : focale et ouverture. Elles donnent l'échantillonnage utilisé par la
  résolution astrométrique et le guidage. Ajoutez aussi la lunette de guidage.

Tant que vous y êtes, modifiez les caméras pour renseigner la **taille de pixel** et un **gain
par défaut**, et la roue à filtres pour donner les **noms des filtres** (séparés par des
virgules, dans l'ordre des positions : `L, R, G, B, Ha`). Ces noms apparaissent partout où l'on
choisit un filtre.

## 6. Créer un profil

Allez dans **Profils**, cliquez sur **Nouveau profil**, donnez-lui un nom (*Setup du jardin*)
et cliquez sur **Créer le profil**. Dépliez le profil et construisez son **arborescence du
matériel** avec **Ajouter à l'arborescence**, puis le **+** à côté de chaque élément pour y
rattacher ce qui est monté dessous :

```
Site d'observation
└── Monture
    ├── Télescope principal
    │   └── Focuser
    │       └── Roue à filtres
    │           └── Caméra principale
    └── Lunette de guidage
        └── Caméra de guidage
```

![Un profil et son arborescence du matériel](../images/profiles.png)

L'arborescence n'est pas décorative : elle indique à astrolol quel focuser et quelle roue à
filtres vont avec quelle caméra (la page Imagerie de la caméra principale montre donc ce
focuser et cette roue), quel télescope donne quel échantillonnage, et où se trouve la monture
sur Terre. Voir [Profils](profiles.md) pour les règles.

## 7. Activer le profil

Cliquez sur **Activer**. astrolol connecte chaque appareil de l'arborescence et affiche *Profil
activé* (ou *Activé avec des erreurs*, avec la raison pour chaque appareil en échec). Le profil
reste actif : au redémarrage, astrolol le reconnecte tout seul.

Vous êtes prêt. Une première soirée typique :

1. [Monture](mount.md) : déparquer, vérifier le suivi.
2. [Mise en station](../../astrolol/plugins/polar_align/docs/fr.md) si la monture vient d'être
   installée.
3. [Cible](../../astrolol/plugins/target/docs/fr.md) : trouver un objet, **Pointer la cible**.
4. [Résolution astrométrique](../../astrolol/plugins/platesolve/docs/fr.md) : **Poser et
   résoudre** avec *Synchroniser et pointer* pour le centrer.
5. [Autofocus](../../astrolol/plugins/autofocus/docs/fr.md).
6. [Guideur](../../astrolol/plugins/guider/docs/fr.md) ou
   [PHD2](../../astrolol/plugins/phd2/docs/fr.md) : lancer le guidage.
7. [Imagerie](imaging.md) pour des poses isolées, ou le
   [Séquenceur](../../astrolol/plugins/sequencer/docs/fr.md) pour la nuit.
