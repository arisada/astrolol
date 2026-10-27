# Matériel

> **Vous installez astrolol pour la première fois ?** Commencez par les
> [Premiers pas](getting-started.md) : ils vous mènent du premier appareil connecté à un profil
> que vous connectez en un clic.

La page Matériel a deux onglets :

- **connexions** : les appareils connectés en ce moment, et l'assistant pour en connecter
  d'autres.
- **inventaire** : tout ce que vous possédez, connecté ou non. Les profils sont construits à
  partir de lui.

**Actualiser** relit la liste des appareils sur le serveur.

## Connexions

### Connecter un appareil

Cliquez sur **Charger un pilote** et suivez l'assistant.

1. **Que souhaitez-vous connecter ?** Caméra, Monture, Focuser, Roue à filtres, Panneau de flats ou Rotateur.
2. **Comment est-il connecté ?**
   - **Parcourir les pilotes INDI** : presque tout le matériel du commerce. astrolol démarre et
     arrête le serveur INDI tout seul (modifiable dans [Options](options.md#serveur-indi)).
     Quand astrolol utilise INDIGO, le bouton devient **Parcourir les pilotes INDIGO** et
     propose les pilotes INDIGO ; la roue à filtres ou le focuser d'une caméra, qu'INDIGO
     présente comme un appareil à part, se connecte avec la caméra.
   - **Autre adaptateur** : les pilotes fournis par des modules d'astrolol, par exemple
     `eqmod` (le pilote natif Sky-Watcher du module [EQMOD](../../astrolol/plugins/eqmod/docs/fr.md))
     ou son simulateur de monture, et les adaptateurs `alpaca_…` du module
     [ASCOM Alpaca](../../astrolol/plugins/alpaca/docs/fr.md). Si aucun n'est proposé pour le type choisi,
     l'assistant le signale.
3. Pour INDI : **Choisir le fabricant**, puis **Choisir le modèle**. **Saisir manuellement…**
   permet de taper un nom de pilote (`indi_asi_ccd`) et, si besoin, le nom sous lequel le
   pilote annonce l'appareil (utile quand un pilote sert plusieurs appareils identiques).
4. **Configurer et connecter** : le pilote est chargé et les réglages qu'il accepte avant la
   connexion sont listés : port série, vitesse, etc. Laissez-les tels quels sauf si vous savez
   qu'il faut les changer. Si le pilote sert plusieurs appareils, choisissez le **Nom de
   l'appareil INDI**. Avec INDIGO, les réglages propres au serveur INDIGO (ses profils, les
   instances supplémentaires, un mot de passe) sont grisés : ils ne changent pas à la connexion.
5. **ID de l'appareil** (facultatif) : un nom court utilisé partout dans astrolol (entrées du
   menu, noms de fichiers). Lettres, chiffres, `-` et `_`. Laissez vide pour qu'il soit tiré du
   nom de l'appareil.
6. **Connecter**.

Pour un **Autre adaptateur**, l'assistant demande l'adaptateur, un ID facultatif et ses
**Paramètres de connexion (JSON)** (chaque adaptateur documente les siens, par ex.
`{"port": "/dev/ttyUSB0"}`).

### Simulateurs

INDI et INDIGO fournissent tous deux des simulateurs pour essayer astrolol sans matériel, mais
ils ne se comportent pas de la même façon :

- **Le simulateur de caméra d'INDI** dessine les étoiles autour de l'endroit où pointe la
  monture simulée : elles bougent quand vous pointez ailleurs, et la résolution astrométrique
  retrouve la position de la monture. Utilisez-le pour essayer le pointage, le centrage et la
  résolution astrométrique.
- **Le CCD Imager Simulator d'INDIGO** montre toujours la même image (la nébuleuse de la
  Rosette), où que pointe la monture. Avec lui, la résolution astrométrique ne correspond pas à
  la monture. La mise au point fonctionne : l'image devient floue quand son focuser s'éloigne
  de la mise au point. Pour le guidage, utilisez le **CCD Guider Simulator** d'INDIGO, qui
  dessine un champ d'étoiles qui répond aux impulsions de guidage.
- **Le focuser d'INDIGO** (*CCD Imager Simulator (focuser)*) est au point à la position 0
  quand il démarre, et devient flou très vite : à environ 500 pas, les étoiles ont disparu.
  Quand astrolol le connecte, il le règle comme un vrai focuser : il indique 10000 sans bouger,
  et c'est là qu'il est au point, et sa courbe de mise au point est plus large (à 2000 pas, les
  étoiles s'étalent d'environ 4 pixels). Un focuser qui a déjà bougé est laissé tel quel. Les
  deux réglages sont dans ses
  [Propriétés de l'appareil](interface.md#propriétés-des-appareils) : **On position set**
  (**Sync to position** change la position indiquée sans le déplacer) et **Focuser blur
  (steps/px blur)** dans **Focuser Setup**.

### Appareils connectés

Chaque appareil connecté affiche son type, son ID, son pilote et son état (*connecté*,
*connexion*, *occupé*, *erreur*…). Les appareils arrivés avec un autre (une roue à filtres
intégrée à une caméra, par exemple) sont marqués *détecté automatiquement*.

Les boutons de chaque ligne :

| Bouton | Effet |
|---|---|
| Importer dans l'inventaire | Ajoute l'appareil, avec son pilote, à l'inventaire. Grisé s'il y est déjà. |
| Reconnecter | Déconnecte puis reconnecte. À essayer en premier quand un appareil ne répond plus. |
| Déconnecter (garder enregistré) | Déconnecte, mais garde l'appareil dans la liste, prêt à être reconnecté. |
| Supprimer l'appareil | Déconnecte et retire l'appareil de la liste. |

Un appareil qui ne fait pas partie du [profil actif](profiles.md) est marqué **hors profil**.
Il risque de ne pas fonctionner correctement avec le reste d'astrolol, qui s'appuie sur le profil
pour savoir comment il est monté (quel télescope, quels filtres, quel site). Survolez la marque
pour savoir quoi faire : importer l'appareil dans l'inventaire si besoin, puis l'ajouter à
l'arborescence du profil dans la page Profils. Rien n'est marqué tant qu'aucun profil n'est actif.

Juste après la connexion d'un appareil, astrolol propose de l'ajouter à l'inventaire s'il n'y
est pas déjà.

## Inventaire

L'inventaire est la liste de votre matériel. Chaque élément a un type :

| Type | À renseigner |
|---|---|
| Site d'observation | Latitude, longitude, altitude (m), fuseau horaire |
| Monture | Pilote (voir plus bas) |
| Télescope / OTA | Focale (mm), ouverture (mm) |
| Caméra | Pilote, taille de pixel (µm), gain par défaut |
| Roue à filtres | Pilote, noms des filtres (séparés par des virgules, dans l'ordre des positions) |
| Focuser | Pilote |
| Rotateur | Pilote |
| Panneau de flats | Pilote (un panneau lumineux, un cache anti-poussière motorisé, ou les deux) |
| GPS | Pilote |

**Ajouter du matériel** ouvre le formulaire ; chaque élément a des boutons **Modifier** et
**Supprimer**.

Un élément dont l'appareil est enregistré dans l'onglet Connexions (voir [Appareils connectés](#appareils-connectés)) affiche
son état (*connecté*, *occupé*, *erreur*, *déconnecté*…) à côté de son nom. Un élément sans état
n'est pas connecté. Les sites, télescopes et GPS n'en affichent jamais.

Une petite étiquette à côté du nom d'un appareil indique ce qui le pilote : **INDI**, **INDIGO**,
ou le plugin dont il vient (par exemple **ASCOM Alpaca** ou **Monture EQMOD**). C'est utile quand
une installation mélange des appareils de plusieurs sortes. Un appareil dont le plugin est
désactivé affiche sa clé d'adaptateur à la place.

Pour les appareils, le **Pilote INDI** (par ex. `indi_eqmod_telescope`) et le **Nom de
l'appareil INDI** (tel que le pilote l'annonce, par ex. `EQ6 Mount`) indiquent à astrolol comment
le connecter. Pour un adaptateur non INDI, renseignez plutôt la **Clé d'adaptateur** (par ex.
`eqmod`) et ses **Paramètres de connexion (JSON)**. Le plus simple pour ne pas se tromper est de
connecter l'appareil une fois avec l'assistant, puis d'utiliser **Importer dans l'inventaire**.

À renseigner en priorité :

- **Site** : la monture en a besoin pour calculer où sont les objets, et la page
  [Cible](../../astrolol/plugins/target/docs/fr.md) pour les heures de lever et de coucher.
  Tant que l'inventaire n'a pas de site, un rappel propose **Ajouter un site d'observation**.
- **Focale du télescope** et **taille de pixel de la caméra** : elles donnent l'échantillonnage
  utilisé par la [résolution astrométrique](../../astrolol/plugins/platesolve/docs/fr.md) et le
  [guideur](../../astrolol/plugins/guider/docs/fr.md), et sont écrites dans les en-têtes FITS.
- **Gain par défaut** : le gain de départ de la caméra. Le laisser au pilote est risqué :
  certains pilotes démarrent à un gain que vous n'utiliseriez jamais.
- **Noms des filtres** : affichés partout où l'on choisit un filtre, et utilisés dans les noms
  de fichiers.

Ensuite : placez les éléments dans un [profil](profiles.md).
