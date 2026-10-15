# Assistants IA

*Module : Assistants IA.* Permet à Claude et à d'autres assistants IA de regarder votre
installation et de la piloter. Vous demandez en langage courant : « que fait la monture ? »,
« centre sur M31 et fais une pose test de 30 s », « fais la mise au point, lance le guidage et
exécute la liste de ce soir ». L'assistant appelle les outils d'astrolol, vous montre ce qu'il a
trouvé et vous rend compte.

Un assistant peut faire exactement ce que permet le compte qu'il utilise (voir
[Sécurité](../../security/docs/fr.md)) :

| Niveau d'accès | Ce que l'assistant peut faire |
|---|---|
| Lecteur | Regarder : état, images, événements. Rien ne bouge. |
| Opérateur | Piloter : pointer, parquer, poser, mettre au point, guider, lancer le séquenceur. |

Quand la sécurité est désactivée, l'assistant a l'accès opérateur complet, comme n'importe qui sur
votre réseau. Activez la sécurité et donnez à l'assistant son propre jeton **lecteur** pour qu'il
puisse regarder sans rien toucher.

## Connexion

Ouvrez cette page : elle affiche l'adresse à donner à votre assistant et, pour Claude Code, une
commande à copier. Elle ressemble à ceci :

```
claude mcp add --transport http astrolol http://astrolol.local:8000/plugins/mcp
```

Avec la sécurité activée, ajoutez le jeton d'accès (créé dans la page Sécurité, **Jetons d'API**) :

```
claude mcp add --transport http astrolol http://astrolol.local:8000/plugins/mcp \
  --header "Authorization: Bearer <jeton>"
```

Les autres assistants qui acceptent les serveurs MCP distants prennent la même adresse, et le même
en-tête s'ils permettent d'en définir un. L'ordinateur qui fait tourner l'assistant doit pouvoir
joindre astrolol ; aucun programme n'est à installer dessus.

## Le skill

**Télécharger SKILL.md** donne un court guide pour Claude : le déroulé d'une nuit, les unités
(coordonnées en degrés, états en heures), et les bons réflexes (arrêter le guidage avant de
pointer, parquer à la fin, demander avant de lancer une longue série). Enregistrez-le sous le nom
`SKILL.md` dans un dossier `astrolol-observing`, à l'intérieur de votre dossier de skills (par
exemple `~/.claude/skills/`). L'assistant fonctionne sans, mais se trompe moins avec.

## Ce qu'il peut faire

La liste en bas de la page montre chaque outil et s'il est en lecture seule. En bref :

- **Regarder :** une vue d'ensemble de tous les appareils, la position de la monture, l'état de la caméra et du focuseur, les derniers événements, n'importe quelle page de l'API en lecture seule.
- **Pointer :** chercher un objet, savoir quand il est visible, pointer, centrer par résolution astrométrique, parquer.
- **Photographier :** faire une pose et voir un aperçu, refroidir la caméra, changer de filtre.
- **Mettre au point et guider :** mise au point automatique, démarrer/arrêter le guidage, dithering.
- **Mener une nuit :** construire la file du séquenceur, la vérifier, la lancer, la mettre en pause, l'arrêter.
- **Tout arrêter :** un seul appel arrête la monture, la caméra, le focuseur, le guidage et le séquenceur.

Les outils d'une fonction n'apparaissent que si son module est activé. Les pointages, le parcage et la
mise au point attendent leur fin, l'assistant n'a donc pas à redemander sans cesse.

## À savoir

- L'activation ou la désactivation du module prend effet après un redémarrage.
- L'assistant voit les images sous forme de petits aperçus, suffisants pour juger la mise au point, les traînées et l'exposition. Les données complètes restent sur la machine d'astrolol.
- Consultez **Logs** (verbosité : Assistants IA) si un appel d'outil échoue.
