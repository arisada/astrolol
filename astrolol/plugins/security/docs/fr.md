# Sécurité

*Module : Sécurité.* Contrôle qui peut voir et piloter le télescope. Tant qu'aucun compte n'est
créé, toute personne qui peut joindre astrolol a un accès complet. C'est acceptable chez soi sur
un réseau privé, mais pas sur un réseau partagé (une star party, un club, un Wi-Fi public).

Utilisez HTTPS quand vous activez la sécurité : en HTTP simple, les mots de passe circulent en
clair sur le réseau. La page vous prévient quand la connexion n'est pas chiffrée. Voir le
[guide de déploiement](../../../../docs/raspberry-pi-deployment.md) (en anglais).

## Niveaux

| Niveau | Peut |
|---|---|
| lecture seule | Tout regarder, ne rien changer. |
| opérateur | Piloter le télescope : pointer, poser, guider, lancer des séquences. |
| admin | Modifier aussi les réglages, les modules, le matériel et les utilisateurs. |

## Activer la sécurité

Sous **Créer le premier compte**, choisissez un nom d'utilisateur et un mot de passe (au moins
8 caractères) puis cliquez sur **Créer le compte et activer la sécurité**. Ce premier compte est
administrateur. Dès lors, tout le monde doit se connecter.

## Gérer les accès

- **Votre compte** : changer votre mot de passe (il faut ensuite se reconnecter).
- **Accès invité** : permet de regarder sans mot de passe, en lecture seule. Pratique pour
  montrer la session à des amis ou sur un second écran.
- **Utilisateurs** (admins seulement) : ajouter des utilisateurs avec un niveau,
  **Réinitialiser le mot de passe**, **Supprimer**. Le seul admin ne peut être ni rétrogradé ni
  supprimé.
- **Jetons d'API** (admins seulement) : permettent à d'autres programmes et scripts d'utiliser
  astrolol sans mot de passe. Donnez au jeton un nom et une validité en jours (ou **Sans
  expiration**), cliquez sur **Créer le jeton** et copiez-le tout de suite : il n'est affiché
  qu'une fois. **Révoquer** l'annule.
- **Origines autorisées** (admins seulement) : les pages web servies depuis ces adresses peuvent
  appeler astrolol depuis un autre site, avec un jeton. Une adresse par ligne.

## Accès perdu ?

Sur l'ordinateur du télescope, avec l'utilisateur qui fait tourner astrolol :

```bash
python -m astrolol.plugins.security list                # lister les utilisateurs
python -m astrolol.plugins.security set-password NOM    # changer le mot de passe d'un utilisateur
python -m astrolol.plugins.security add-admin NOM       # créer un administrateur
python -m astrolol.plugins.security reset               # supprimer tous les comptes : sécurité désactivée
```
