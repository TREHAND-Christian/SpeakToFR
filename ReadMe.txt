SpeakToFR - Cahier des charges
==============================

1. Objectif
-----------

SpeakToFR est une application Windows de lecture vocale assistee par traduction.
Elle permet a l'utilisateur de selectionner du texte dans n'importe quelle
application, d'appuyer sur Ctrl + Alt + Entree, puis d'entendre le contenu en
francais avec une voix Windows OneCore.

L'application fonctionne principalement en arriere-plan, depuis la zone de
notification Windows. Elle doit rester rapide, discrete et utilisable sans
interrompre le travail courant.


2. Public vise et cas d'usage
-----------------------------

Public vise :
- utilisateurs francophones qui lisent regulierement des textes en anglais ou
  dans une autre langue ;
- personnes qui preferent ecouter un texte plutot que le lire ;
- utilisateurs qui copient des extraits depuis un navigateur, un IDE, un PDF,
  une messagerie ou un outil bureautique.

Cas d'usage principal :
1. L'utilisateur lance SpeakToFR.
2. L'application place une icone dans la zone de notification.
3. L'utilisateur selectionne du texte dans une application.
4. Il appuie sur Ctrl + Alt + Entree.
5. SpeakToFR copie la selection, prepare le texte, traduit vers le francais si
   necessaire, affiche une fenetre de controle et lance la lecture.

Cas d'usage secondaire :
- lecture d'un texte deja en francais sans retraduction ;
- lecture de contenu HTML copie depuis un navigateur ;
- navigation phrase par phrase ;
- changement de voix ou de vitesse pendant la lecture ;
- lancement automatique au demarrage de Windows.


3. Fonctionnalites obligatoires
-------------------------------

3.1 Application en arriere-plan

- L'application demarre sans fenetre principale permanente.
- Une icone est affichee dans la zone de notification Windows.
- Le menu de l'icone permet :
  - de mettre le service en pause (raccourci + lecture auto Claude Desktop) ;
  - d'activer ou desactiver la lecture auto de Claude Desktop ;
  - d'afficher ou masquer la barre flottante ;
  - d'activer ou desactiver le demarrage automatique Windows ;
  - d'ouvrir les options (clic sur l'icone aussi) ;
  - d'ouvrir l'aide locale ;
  - de quitter l'application.
- Une seule instance doit pouvoir tourner a la fois.

3.2 Raccourci global

- Le raccourci par defaut est Ctrl + Alt + Entree.
- Quand il est detecte, l'application copie la selection active.
- La copie utilise AutoHotkey si disponible, sinon un fallback Windows simule
  Ctrl + C.
- Si aucun texte n'est selectionne, l'application affiche et lit le message :
  "veuillez selectionner un texte".

3.3 Presse-papiers

- L'application surveille le presse-papiers pour detecter les contenus marques
  comme venant de son raccourci.
- Le texte utile est restaure dans le presse-papiers apres detection.
- Le format HTML du presse-papiers Windows doit etre prefere au texte brut
  quand il est disponible.

3.4 Traduction

- Le texte doit etre traduit vers le francais avec googletrans.
- Si la traduction echoue, le texte source est conserve.
- Les textes longs peuvent etre decoupes en morceaux.
- Une preference permet d'eviter la retraduction des textes deja en francais.
- Une preference permet de forcer la traduction meme si le texte semble deja
  francais.

3.5 Traitement texte et HTML

- Les commentaires HTML sont ignores.
- Les balises utiles sont conservees pour l'affichage quand possible.
- Les blocs script, style et head ne doivent pas etre lus.
- Les blocs pre/code doivent rester lisibles visuellement.
- Les blocs pre majoritairement techniques doivent etre exclus de la lecture
  vocale et du surlignage principal.
- Les URLs, chemins Windows, acronymes et ponctuations techniques doivent etre
  prepares pour une lecture TTS plus claire.
- Les phrases doivent etre decoupees avec leurs positions pour permettre le
  surlignage et la navigation.

3.6 Synthese vocale

- Le moteur cible est Windows OneCore via winsdk.
- Les voix disponibles sont listees depuis le systeme.
- La voix par defaut est Microsoft Paul si elle existe, sinon la premiere voix
  disponible.
- La lecture se fait phrase par phrase.
- La lecture doit pouvoir etre arretee rapidement.
- La pause coupe la phrase en cours et la reprise relance depuis la phrase
  courante.

3.7 Barre flottante et options (modele CodexAudio)

- Une barre flottante, toujours au-dessus, reprend celle de CodexAudio :
  lecture/pause, stop, muet, fenetre texte, options.
- Bordure verte = service actif, rouge = service en pause.
- La barre n'est normale que quand Claude Desktop est au premier plan ; elle
  est grisee dans toute autre appli (dans VS Code, c'est la barre CodexAudio
  qui est active). Elle reprend ses couleurs au survol et reste cliquable.
  Option "Griser la barre..." (bar_dim_unfocused, actif par defaut).
- Le bouton lecture bascule Lecture/Pause des qu'une lecture est demandee
  (traduction comprise). Le bouton Stop est grise quand rien n'est en lecture.
- Quand une conversation est ouverte ou changee dans Claude Desktop (titre du
  document "Titre - Claude"), sa derniere reponse est chargee sans etre lue :
  le prochain Play la lit. Sinon Play relit la derniere lecture.
- Le bouton fenetre texte affiche/masque la fenetre texte ; hors lecture, elle
  montre la derniere reponse chargee et reste ouverte en fin de lecture.
- La barre se deplace en la glissant (boutons compris) ; sa position est
  memorisee (bar_x / bar_y). Elle peut s'afficher au demarrage (bar_start).
- La fenetre Options (theme sombre, comme le panneau CodexAudio) regroupe :
  - Principal : pause du service, muet, lecture auto Claude Desktop, voix,
    vitesse (50-200 %), volume (0-100 %), tester la voix ;
  - Interface : barre flottante, barre au demarrage, demarrage Windows ;
  - Fenetre texte : affichage pendant la lecture, ne pas retraduire le
    francais, forcer la traduction, fichiers HTML de debug.
- Le volume et le muet ne touchent que SpeakToFR (volume de session audio
  Windows via waveOutSetVolume), pas le volume general.

3.8 Fenetre texte

- La fenetre texte n'apparait que si l'option "Afficher la fenetre texte" est
  cochee (bouton fenetre de la barre) ; sinon la lecture se fait avec la barre
  seule, sans voler le focus.
- La fenetre est flottante, toujours au-dessus et de style compact.
- Elle affiche le texte lu, avec surlignage de la phrase courante.
- Elle fournit :
  - pause/reprise ;
  - fermer ;
  - choix de la voix ;
  - reglage de la vitesse ;
  - aller a la premiere phrase ;
  - phrase precedente ;
  - phrase suivante ;
  - derniere phrase.
- La position de la fenetre est memorisee.

3.9 Preferences

Les preferences sont stockees en JSON et doivent contenir au minimum :
- voice : voix choisie ;
- speed : vitesse de lecture ;
- x / y : position de la fenetre ;
- auto_detect_french : booleen ;
- force_translate : booleen ;
- debug_html : booleen ;
- show_text : fenetre texte affichee pendant la lecture ;
- bar_x / bar_y / bar_start : barre flottante ;
- volume (0-100) / muted : son ;
- claude_auto_read : lecture auto Claude Desktop.

3.10 Aide et packaging

- Une page d'aide locale doit etre fournie.
- Un script de build doit produire un executable avec PyInstaller.
- Une configuration Inno Setup doit produire un installateur Windows.
- L'installateur doit pouvoir configurer le demarrage automatique.


4. Architecture cible pour CopyToSpeak
--------------------------------------

La reecriture doit utiliser Python et PySide6.

Modules attendus :
- main.py : point d'entree, application Qt, instance unique, tray menu.
- copytospeak/core/ : etat applicatif, preferences et moteur TTS.
- copytospeak/services/ : presse-papiers, raccourci global, autostart,
  traduction.
- copytospeak/text/ : detection HTML, nettoyage, decoupage en phrases,
  preparation TTS.
- copytospeak/ui/ : fenetre de controle et dialogue de preferences.
- requirements.txt : dependances.
- build_release.ps1, CopyToSpeak.spec, SetupCopyToSpeak.iss : packaging.

La nouvelle base doit eviter les noms historiques CodexTTS dans les messages,
les titres et les logs.


5. Contraintes techniques
-------------------------

- Systeme cible : Windows.
- UI : PySide6.
- TTS : winsdk Windows OneCore.
- Presse-papiers : pywin32.
- Raccourci global : API Win32 RegisterHotKey.
- Traduction : googletrans, avec fallback sur le texte original.
- AutoHotkey v2 est optionnel et utilise uniquement si disponible.
- L'application doit rester utilisable sans PySide6-WebEngine, avec fallback
  QTextEdit.


6. Limites connues de l'application actuelle
-------------------------------------------

- googletrans utilise un backend non officiel et peut echouer selon le reseau
  ou les changements du service distant.
- Le raccourci n'est pas configurable dans l'interface.
- Le chemin AutoHotkey (core/config.py) pointe encore vers
  C:\Program Files\CodexTTS ; le fallback Ctrl+C simule fonctionne sans.
- STATE reste un singleton global (voir core/state.py), mais ses attributs sont
  regroupes (STATE.playback, STATE.ui) et tous declares.

Fait lors du refactoring :
- preferences deplacees dans %APPDATA%\SpeakToFR\prefs.json (migration auto de
  l'ancien window_prefs.json) ;
- logs dans %APPDATA%\SpeakToFR\speaktofr.log (fichier tournant) ;
- html_utils, ui_main et window decoupes en modules plus petits ;
- fichiers morts supprimes ; tests automatises dans tests/ (pytest).

Tests : pip install -r requirements-dev.txt puis python -m pytest tests


7. Ameliorations proposees pour une version ulterieure
------------------------------------------------------

Ces ameliorations sont recommandees mais ne font pas partie de la premiere
reecriture de CopyToSpeak sans validation supplementaire :

- raccourci clavier configurable ;
- historique local des textes lus ;
- choix du moteur de traduction ;
- mode hors-ligne ou degradation plus explicite en cas d'erreur reseau ;
- panneau de logs consultable depuis les preferences ;
- indicateur d'etat plus detaille : copie, traduction, lecture, erreur ;
- preferences enrichies avec chemin de stockage utilisateur ;
- tests automatises sur decoupage phrase, HTML et preparation TTS ;
- meilleure separation entre contenu affiche et contenu lu ;
- icone applicative definitive et signature du build.


8. Criteres d'acceptation
-------------------------

La reecriture est consideree conforme si :
- CopyToSpeak se lance sur Windows avec une icone de zone de notification ;
- Ctrl + Alt + Entree copie la selection et lance la lecture ;
- un texte anglais est traduit et lu en francais ;
- un texte francais peut etre lu sans retraduction ;
- les controles pause, reprise, stop, voix, vitesse et navigation fonctionnent ;
- les preferences principales persistent entre deux lancements ;
- le menu tray permet aide, preferences, autostart et quitter ;
- le projet fournit les fichiers necessaires au build executable/installateur.


9. Plan de test manuel
----------------------

- Lancer l'application deux fois et verifier qu'une seule instance reste active.
- Selectionner du texte simple puis utiliser Ctrl + Alt + Entree.
- Utiliser le raccourci sans selection et verifier l'alerte.
- Copier un extrait HTML avec listes, liens, code inline et bloc pre.
- Tester pause, reprise, fermeture.
- Changer de voix et de vitesse pendant une lecture.
- Naviguer entre premiere, precedente, suivante et derniere phrase.
- Passer en modes complet, options et mini.
- Fermer puis relancer et verifier position, voix, vitesse et mode.
- Activer/desactiver le demarrage automatique dans le menu tray.
- Lancer build_release.ps1 si PyInstaller et Inno Setup sont installes.
