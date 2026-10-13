# Serveur Stellarium

*Module : Serveur Stellarium.* Montre dans [Stellarium](https://stellarium.org/) où pointe le
télescope, et permet de l'envoyer vers un objet depuis Stellarium. Les coordonnées sont échangées
en J2000. Pour SkySafari, Cartes du Ciel et les autres logiciels, utilisez le
[Serveur LX200](../../lx200/docs/fr.md).

Cliquez sur **Démarrer** ; la page affiche le **Port** et le nombre de **Clients**.

Dans Stellarium (remplacez `astrolol-host` par l'adresse de l'ordinateur du télescope) :

1. **Modules d'extension → Contrôle des télescopes** : activez le module, puis configurez-le.
2. **Ajouter un nouveau télescope**.
3. *Télescope contrôlé par* : **logiciel tiers ou ordinateur distant**.
4. *Type de connexion* : **TCP**. *Hôte* : `astrolol-host`, *Port* : le port affiché dans
   astrolol.
5. Laissez le système de coordonnées sur **J2000** (la valeur par défaut).
6. Enregistrez et connectez-vous. Le réticule du télescope apparaît sur le ciel.

Pour pointer : clic droit sur un objet → *Objet courant* → **Pointer le télescope**.
