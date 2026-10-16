# Le dock

Le dock est un panneau latéral, à droite, qui garde quelques indicateurs sous les yeux quelle que
soit la page : où pointe la monture, comment se porte le guidage, etc. Il ne modifie jamais la page
sur laquelle vous travaillez.

## L'ouvrir

Cliquez sur la petite languette au bord droit de l'écran (en bas de l'écran sur un téléphone tenu à la verticale, où le dock s'ouvre en feuille par-dessus le bas de la page). Sur un grand écran, la page lui laisse la
place ; sur un écran plus étroit, le dock glisse par-dessus la page (appuyez sur **Échap** ou sur le
bouton de fermeture pour le ranger). Chaque navigateur retient s'il est ouvert.

## Choisir ce qu'il affiche

1. Cliquez sur **Modifier le dock** (le crayon) en haut du dock.
2. Choisissez des widgets dans la liste **Ajouter un widget**. Un widget qui montre un seul appareil,
   comme un focuseur ou une roue à filtres, est proposé une fois par appareil connecté : on peut donc
   épingler deux focuseurs.
3. Les flèches changent l'ordre, **×** retire un widget. Cliquez sur **Terminer** quand vous avez fini.

Cliquez sur le titre d'un widget pour aller à sa page, ou sur le chevron pour le replier.

La disposition est enregistrée avec vos autres réglages : elle vous suit sur votre téléphone ou un autre
ordinateur. Un spectateur qui n'a pas le droit de modifier les réglages peut organiser le dock, mais
celui-ci revient à l'état enregistré au rechargement de la page.

## Widgets disponibles

| Widget | Provenance | Affiche |
|---|---|---|
| Position | [Monture](mount.md) | Coordonnées et monture sur le ciel |
| Horizon | [Monture](mount.md) | La monture au-dessus de l'horizon local |
| État de la monture | [Monture](mount.md) | Parquée, en déplacement ou en suivi, côté du pilier, temps avant le méridien |
| Focuseur | [Imagerie](imaging.md) | Position du focuseur sur une règle |
| Roue à filtres | [Imagerie](imaging.md) | Le filtre dans le faisceau |
| Alertes | [Journaux](logs.md) | Alertes et erreurs de tous les composants |
| Séquence | [Séquenceur](../../astrolol/plugins/sequencer/docs/fr.md) | Tâche en cours, images faites, temps restant |
| Courbe de focus | [Autofocus](../../astrolol/plugins/autofocus/docs/fr.md) | La courbe en V et la meilleure position trouvée |
| Guidage | [Guideur](../../astrolol/plugins/guider/docs/fr.md) | Guidage actif ou perdu, signal de l'étoile, dernière correction |
| Visibilité de la cible | [Cible](../../astrolol/plugins/target/docs/fr.md) | Quand la cible actuelle est visible cette nuit |
| Dernière résolution | [Résolution astrométrique](../../astrolol/plugins/platesolve/docs/fr.md) | Dernière position résolue et son écart avec la monture |
| État du système | [Système](../../astrolol/plugins/system/docs/fr.md) | Processeur, mémoire, disque, température, alimentation |

Les widgets d'une fonction désactivée ne sont pas proposés.
