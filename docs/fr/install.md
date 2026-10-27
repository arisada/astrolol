# Installer astrolol

astrolol s'installe sous forme de paquet sur l'ordinateur du télescope. Il démarre ensuite tout
seul à chaque mise en route, et vous l'utilisez depuis un navigateur web, sur n'importe quel
téléphone, tablette ou ordinateur du même réseau.

Le paquet est prévu pour **Debian 13**, **Raspberry Pi OS** basé dessus (trixie) et
**Ubuntu 26.04**, sur un Raspberry Pi (système 64 bits) ou un PC. Sur un autre système,
installez astrolol depuis son code source : voir le [README](../../README.md) (en anglais).

## 1. Ajouter le dépôt astrolol

Une seule fois, sur l'ordinateur du télescope :

```bash
sudo curl -fsSL https://apt.astrolol.lol/astrolol.gpg -o /etc/apt/keyrings/astrolol.gpg
sudo tee /etc/apt/sources.list.d/astrolol.sources <<'EOF'
Types: deb
URIs: https://apt.astrolol.lol
Suites: nightly
Components: main
Signed-By: /etc/apt/keyrings/astrolol.gpg
EOF
sudo apt update
```

Pour l'instant, il n'y a que des versions de développement (nightly) : elles suivent le
développement, ont donc les nouveautés en premier et peuvent parfois casser. Mettez à jour
souvent.

## 2. Installer les pilotes des appareils

astrolol communique avec les caméras, montures et focusers par INDI. L'INDI fourni par Debian et
Ubuntu est ancien et compte peu de pilotes : installez-en un récent, avec les pilotes de la
plupart des appareils :

- **Debian 13 et Raspberry Pi OS**, depuis Astroberry :

  ```bash
  curl -fsSL https://astroberry.io/debian/astroberry.asc | sudo gpg --dearmor -o /etc/apt/keyrings/astroberry.gpg
  sudo curl -fsSL https://astroberry.io/debian/astroberry.sources -o /etc/apt/sources.list.d/astroberry.sources
  sudo apt update
  sudo apt install indi-bin indi-3rdparty-drivers
  ```

- **Ubuntu 26.04**, depuis le projet INDI :

  ```bash
  sudo add-apt-repository ppa:mutlaqja/ppa
  sudo apt install indi-bin indi-3rdparty-drivers
  ```

Sans eux, astrolol installe quand même l'INDI de base de votre système. Le matériel qu'astrolol
pilote lui-même (montures Sky-Watcher avec [EQMOD](../../astrolol/plugins/eqmod/docs/fr.md),
appareils ASCOM Alpaca du réseau) n'a besoin d'aucun pilote INDI.

## 3. Installer astrolol

```bash
sudo apt install astrolol
```

astrolol démarre aussitôt. Dans un navigateur, ouvrez `http://<ordinateur du télescope>:8000`,
par exemple `http://raspberrypi.local:8000`, et poursuivez avec les
[Premiers pas](getting-started.md).

Le solveur astrométrique ASTAP est installé avec. Pour la
[Résolution astrométrique](../../astrolol/plugins/platesolve/docs/fr.md), installez aussi sa base
d'étoiles (D05, environ 100 Mo, convient à la plupart des setups) :

```bash
curl -fLo /tmp/d05.deb https://master.dl.sourceforge.net/project/astap-program/star_databases/d05_star_database.deb
sudo apt install /tmp/d05.deb
```

Il peut afficher `chmod: cannot access '/opt/astap/astap'` : c'est sans conséquence.

## En option

| Pour | Installer |
|---|---|
| Le guidage avec [PHD2](../../astrolol/plugins/phd2/docs/fr.md) | `sudo apt install phd2` (Debian et Raspberry Pi OS, depuis Astroberry) |
| Les adaptateurs [série Bluetooth](../../astrolol/plugins/bluetooth_serial/docs/fr.md) | `sudo apt install bluez` |
| Le Wi-Fi et le point d'accès de la page [Système](../../astrolol/plugins/system/docs/fr.md) | `sudo apt install network-manager` (déjà présent sur Raspberry Pi OS) |

Tant que vous n'avez pas activé le module [Sécurité](../../astrolol/plugins/security/docs/fr.md),
n'importe qui sur le réseau peut piloter l'installation : gardez astrolol sur un réseau de
confiance et n'ouvrez jamais son port sur internet. Le paquet sert astrolol en HTTP simple ; le
HTTPS, avec un serveur web devant, est décrit pour une installation depuis le code source dans le
[guide de déploiement sur Raspberry Pi](../raspberry-pi-deployment.md) (en anglais).

## Mettre à jour

```bash
sudo apt update && sudo apt upgrade
```

astrolol redémarre avec la nouvelle version.

## Où se trouvent les fichiers

| Quoi | Où |
|---|---|
| Réglages, profils, utilisateurs, journaux | `/var/lib/astrolol` |
| Images capturées | `/var/lib/astrolol/images` |
| Configuration de démarrage | `/etc/astrolol/astrolol.toml` |

astrolol tourne sous son propre utilisateur, `astrolol`, qui a accès aux ports série et aux
caméras USB. Le fichier de configuration contient les quelques réglages lus au démarrage, comme
un autre dossier pour les images (`images_dir`, par exemple un disque USB où l'utilisateur
`astrolol` peut écrire). Après l'avoir modifié :

```bash
sudo systemctl restart astrolol
```

Pour vérifier qu'astrolol tourne, ou voir ses messages quand il ne démarre pas :

```bash
systemctl status astrolol
journalctl -u astrolol -e
```

## Désinstaller astrolol

```bash
sudo apt remove astrolol
```

Vos réglages, profils et images restent dans `/var/lib/astrolol` ; supprimez ce dossier si vous
n'en avez plus besoin.
