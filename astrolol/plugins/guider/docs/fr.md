# Guideur

> **Expérimental.** Le guideur intégré a surtout été testé avec des simulateurs et doit encore
> être éprouvé sur du vrai matériel. Surveillez-le pendant vos premières nuits et gardez
> [PHD2](../../phd2/docs/fr.md) sous la main en secours. Les problèmes que vous signalez aident à
> le rendre fiable.

*Module : Guideur intégré.* Garde une étoile au même endroit d'une caméra de guidage pendant que
vous photographiez, en envoyant de petites corrections à la monture. Il n'a besoin d'aucun autre
programme. Ne l'activez pas en même temps que le [Guidage PHD2](../../phd2/docs/fr.md) ou le
[Simulateur de guidage](../../guide_simulator/docs/fr.md).

![Guideur](guider.png)

## Démarrage rapide

1. Dans **Réglages**, choisissez la **Caméra de guidage**.
2. Cliquez sur **Lancer le guidage**.

La première fois, le guideur se calibre : il déplace un peu la monture dans chaque direction pour
apprendre comment bouge l'étoile. Ensuite, il choisit les étoiles de guidage et commence à
corriger. La calibration est conservée et réutilisée, même après un pointage ou un retournement
au méridien.

## La page

**Caméra de guidage.** L'image de guidage en direct. Des cadres marquent l'**Étoile de guidage**
(numérotée), ses **Compagnes** (d'autres étoiles moyennées pour compenser la turbulence), les
**Autres étoiles** et les étoiles **Perdues**. **Afficher la caméra** montre les images sans
guider, pour vérifier la mise au point et le cadrage ; cliquez sur une étoile pour guider dessus,
ou laissez le guideur choisir (**Choisir l'étoile pour moi**). Sous l'image, une ligne donne le
numéro d'image, la pose, le fond, le bruit et le pixel le plus brillant ; un tableau donne pour
chaque étoile la HFD, la FWHM, le RSB et le pic (et la marque *saturée*, *étalée* ou *écartée*).

**Cible.** Où l'étoile est passée pendant la dernière minute, autour du point visé, avec le
**RMS AD**, le **RMS Dec** et le **RMS** total en arcsecondes (ou en pixels quand l'échelle est
inconnue). Moins de 1″ au total est bon pour la plupart des setups.

**Graphique d'erreur de guidage.** L'erreur en AD et en Dec au fil du temps, avec les corrections
en barres. Échelle en **arcsecondes** ou en **pixels**, ou **Auto**.

Cadre **Guidage** : l'état (*Choix d'une étoile*, *Calibration*, *Guidage*, *En pause*…), depuis
combien de temps il guide ou ne guide pas, les pertes d'étoile, la déclinaison et le côté du
pilier, la **dérive** et l'**erreur périodique** mesurées, le RSB de l'étoile.

**Boutons** : **Lancer le guidage**, **Arrêter**, **Pause** / **Reprendre**, **Dithering**
(déplace le point visé de la **Distance du dithering**, puis attend que l'étoile se stabilise),
**Recalibrer**.

## Onglet Réglages

| Réglage | |
|---|---|
| Caméra de guidage | N'importe quelle caméra connectée. |
| Envoyer les corrections par | **Caméra de guidage** (un câble ST4 de la caméra à la monture) ou **Monture** (par le pilote de la monture). |
| Monture | Permet à la calibration de suivre les pointages et les retournements au méridien. Normalement *La monture connectée*. |
| Pose, Gain, Binning | Pour les images de guidage. 1 à 3 s est courant. Un gain vide laisse le gain de la caméra tel quel. |
| Étoiles de guidage | Combien d'étoiles utiliser. Plus d'étoiles moyennent la turbulence. |
| Échelle | Arcsecondes par pixel. Calculée d'après la lunette de guidage et la caméra du profil ; à saisir seulement si elles manquent. |
| Abandonner après | Combien de temps chercher une étoile perdue (derrière un nuage, par exemple). 0 = jusqu'à ce qu'elle revienne. |

## Onglet Corrections

Réglages fins. Les valeurs par défaut conviennent à la plupart des montures ; ne changez qu'une
chose à la fois.

| Réglage | |
|---|---|
| Agressivité AD / Déc | Part de l'erreur corrigée à chaque image. À baisser si l'erreur dépasse sans cesse. |
| Hystérésis AD | Part de la correction précédente conservée, pour lisser les corrections. |
| Déplacement minimum | Les erreurs plus petites sont de la turbulence, pas une dérive, et sont ignorées. **Automatique** ou une valeur fixée. |
| Correction la plus longue | Durée maximale d'une impulsion de correction. |
| Corrections en Déc | **Deux sens**, **Nord seulement**, **Sud seulement** ou **Désactivées**. Un seul sens évite le jeu en Déc sur une monture qui dérive toujours du même côté. |
| Limiter les inversions en Dec | Ne change de sens en Déc que si plusieurs images de suite, ou une grande erreur, le demandent. |
| Compenser le jeu en Dec | Allonge la première correction en Déc après un changement de sens du jeu mesuré à la calibration. |
| Déc après un retournement | Si les impulsions Nord déplacent l'étoile dans l'autre sens après un retournement au méridien. **Automatique** convient : le guidage remarque un mauvais choix et le corrige. |
| Anticiper la dérive | Apprend comment la monture dérive et la corrige à l'avance. |
| Anticiper l'erreur périodique | Apprend l'oscillation régulière des engrenages en AD et la corrige à l'avance. **Période de la vis sans fin AD** : la durée d'un tour de vis, si vous la connaissez, ou **La trouver**. |

## Onglet Calibration

Montre la calibration en cours : **Vitesse AD** et **Vitesse Dec**, **Angle entre les axes**,
**Jeu en Dec** et **Jeu en AD**, **Dérive**, **Dispersion**, **Distance AD / Déc**, où et quand
elle a été faite, et un graphique des mesures (**Voir**). *Les mesures concordent bien*, ou des
avertissements avec des conseils, par exemple :

- *Les mesures sont très dispersées* : un ciel plus calme, une pose plus longue ou une étoile
  plus brillante.
- *L'étoile s'est peu déplacée* : augmentez la **Distance** de calibration.
- *L'AD et la Déc ne sont pas à angle droit* : vérifiez le jeu ou le serrage de la monture.
- *Calibrée près du pôle* : recalibrez plus près de l'équateur céleste.

Réglages : **Pas par direction** et **Distance** (jusqu'où la calibration déplace l'étoile).
**Oublier la calibration** fait recalibrer au prochain lancement.

Calibrez une fois près de l'équateur céleste et près du méridien ; astrolol adapte ensuite la
calibration à l'endroit où pointe la monture.

## Onglet Darks

Les darks retirent les pixels chauds autour de l'étoile de guidage. Couvrez le télescope,
choisissez le nombre d'**images** et cliquez sur **Prendre un dark** : un dark est pris avec la
pose et le gain de l'onglet Réglages. La liste montre les darks existants, avec leur nombre de
pixels chauds, et indique si l'un correspond à la pose et au gain actuels. **Supprimer les
darks** les efface.

## Quand ça se passe mal

Le guideur tient bon face aux nuages passagers, à une étoile perdue, à une correction refusée, à
une caméra qui n'envoie plus d'images un moment ou à un retournement au méridien, et dit pourquoi
il ne guide pas (*étoile perdue*, *la monture refuse les corrections*, *plus d'images de la
caméra*…). L'entrée du menu porte un point rouge tant qu'il demande votre attention. Le
[Séquenceur](../../sequencer/docs/fr.md) attend le retour du guidage avant de prendre l'image
suivante.
