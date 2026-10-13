# Simulateur de guidage

*Module : Simulateur de guidage.* Un guideur sans matériel. Il remplace PHD2 ou le guideur
intégré, pour essayer le [Séquenceur](../../sequencer/docs/fr.md) ou le dithering depuis votre
bureau, et répéter une nuit nuageuse. Ne l'activez pas en même temps qu'un autre guideur.

## Utilisation

**Connecter**, puis **Démarrer le guidage**. Le cadre **État** montre l'état, depuis combien de
temps il guide, le RMS sur la dernière minute et le nombre de pertes. **Dither** se comporte
comme un vrai dithering : le guideur se stabilise avant d'annoncer qu'il a fini.

## Pannes

Des boutons injectent les problèmes d'une vraie nuit :

- **Perdre l'étoile 10 s**, **Perdre l'étoile 2 min**, **Perdre l'étoile jusqu'à annulation** :
  le guidage continue d'essayer et reprend quand l'étoile revient, comme après un nuage.
- **Arrêt du guidage** : comme quand PHD2 abandonne ; il faut relancer le guidage.
- **Échec de la prochaine stabilisation**, **Échec des 3 prochaines stabilisations** : des
  dithers qui ne se stabilisent pas à temps.
- **Effacer les pannes**.

## Réglages

**RMS du guidage**, **Pose de guidage toutes les**, **Temps de stabilisation supplémentaire**,
**Échelle de pixel**, **Échelle de temps** (multiplie toutes les durées simulées : en dessous de
1, la nuit passe plus vite), **Un pointage pendant le guidage fait perdre l'étoile**, et
**Connecté au démarrage**. Cliquez sur **Enregistrer les réglages**.
