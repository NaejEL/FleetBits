# Audit vibecode — FleetBits

Généré par /vibecode-audit le 2026-09-13. Axes : sécurité, maintenabilité, évolutivité. Audit complet.

> **Aucun arbitrage humain n'a eu lieu.** Ce rapport a été produit sans interaction possible : l'ordre
> d'attaque ci-dessous est **l'ordre par défaut** (gravité d'abord tous axes confondus, puis pondération
> sécurité > maintenabilité > évolutivité, puis difficulté croissante), et le traitement des motifs
> mineurs suit le défaut (liste courte, non détaillés). Rejouer `/vibecode-audit` dans une session
> interactive permet de choisir un autre ordre — gains rapides d'abord, ou blocage de mise en production
> d'abord — sans refaire le diagnostic.

> **Portée et limites de cet audit.** Diagnostic statique en lecture seule, produit par un modèle de
> langage. Il ne remplace pas une revue de sécurité applicative : aucun accès à l'environnement
> d'exécution, aux identifiants, à la configuration réelle des services tiers ni au trafic ; aucun
> test d'intrusion. L'auditeur partage une partie des angles morts du modèle qui a produit le code —
> l'absence de finding sur une famille ne prouve rien. Les surfaces listées ci-dessous n'ont pas pu
> être auditées du tout.
>
> **Validation.** 42 motifs sur 45 ont passé la validation adversariale. Les 3 autres sont marqués
> `non validé` : ils n'ont pas été réfutés, ils n'ont pas été vérifiés. La validation a rejeté
> 3 motifs et en a scindé 6 : le détail est en fin de rapport.
>
> **Les difficultés sont des ordres de grandeur, pas des estimations.** Elles varient d'un audit à
> l'autre sur le même code. La gravité, elle, est stable : c'est sur elle que repose l'ordre.

> **Mise à jour du 2026-09-14 — ce rapport a vieilli sur deux points.**
>
> *Organisation.* Au moment de l'audit, FleetBits était réparti en quatre dépôts git indépendants
> (`FleetBits-api`, `-ui`, `-agent`, `-platform`) sous une racine non versionnée. Le projet est
> depuis un **monorepo unique** : les chemins de ce rapport ont été réécrits en conséquence
> (`api/`, `ui/`, `agent/`, `platform/`). Les formulations du diagnostic parlent encore de
> « dépôts » là où il faut lire « composants » — le fond reste exact, seule l'organisation a changé.
> Les quatre anciens dépôts sont archivés.
>
> *Findings traités.* **VIB-02, VIB-03 et VIB-05** sont corrigés et mergés ; leur statut détaillé
> dit ce qui a été livré et ce qui ne l'a pas été. **VIB-15** est partiellement traité. Les
> 41 autres motifs sont inchangés, et l'ordre d'attaque ci-dessous reste valable pour eux.
> Ce rapport n'a pas été rejoué : il diagnostique le code tel qu'il était le 2026-09-13.


## Ce que cet audit a trouvé de contre-intuitif

Trois résultats méritent d'être lus avant le tableau, parce qu'ils contredisent ce qu'on attend d'un
projet généré par IA.

1. **Le contrôle d'accès est bon.** C'est l'inverse du défaut typique. Chaque module de routage porte
   son prédicat de portée, la substitution d'identifiant est bloquée, authentification d'appareil et
   authentification humaine sont deux dépendances disjointes, et les tests de frontières de portée
   existent réellement. Il reste trois omissions ponctuelles, pas une absence systémique.
2. **Les contrôles les plus mis en avant sont ceux qui ne fonctionnent pas.** Le cloisonnement des
   requêtes de télémétrie est contournable, et le cloisonnement du bus de messages n'est produit par
   aucun artefact réel — tous deux déclarés clos dans le document de planification.
3. **La chaîne d'enrôlement d'un appareil neuf ne peut pas aboutir**, et rien ne le signale parce
   qu'aucun test ni simulateur ne l'emprunte.

## Surfaces non auditables

| Surface | Pourquoi | Ce qu'il faudrait pour la couvrir |
|---|---|---|
| Vulnérabilités des dépendances | Aucun outil d'audit de dépendances disponible dans l'environnement | Exécuter l'audit du gestionnaire de paquets sur les 3 manifestes, hors ligne si nécessaire |
| Secrets dans l'historique versionné | Aucun détecteur de secrets disponible ; 4 historiques distincts non balayés | Passer un détecteur de secrets sur les 4 historiques complets, pas seulement sur l'état courant |
| Artefacts de distribution | Aucun paquet ni image construit localement ; ce qu'ils embarquent réellement est invisible depuis les sources | Construire puis inspecter le contenu des artefacts — notamment ce qu'une image construite localement embarque du poste du développeur |
| Configuration réelle d'exploitation | Aucun fichier de secrets ou d'environnement présent, seulement les gabarits d'exemple | Auditer les valeurs réellement déployées, hors dépôt |
| Environnement d'exécution | Aucun service démarré : en-têtes réellement servis, règles effectives du courtier, comportement du moteur de requêtes non observables | Audit dynamique sur un environnement représentatif |
| Comportement du courtier face à un fichier de règles invalide | Établi comme non déterminable depuis le dépôt par la validation, et délibérément non deviné | Test d'intégration sur le courtier réel (voir VIB-07) |
| Protections de branche des 4 dépôts | État hors dépôt ; le script d'activation existe mais rien ne prouve qu'il a été exécuté | Interroger la configuration des dépôts distants |

## Par où attaquer

Ordre retenu : **ordre par défaut** (aucun arbitrage humain — voir l'encadré en tête).
45 motifs, 253 occurrences confirmées au total.

| # | ID | Motif | Axe | Sév. | Occ. | Diff. | Risque rég. | Validé | Dépend de | Statut |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | VIB-01 | Le cloisonnement par site des requêtes de télémétrie est appliqué par réécriture textuelle de l'expression, et reste contournable | sécurité | critical | 4 | L | moyen | oui | — | CORRIGE |
| 2 | VIB-02 | Le chemin d'appel de provisionnement utilisé par l'appareil ne correspond à aucune route déclarée | maintenabilité | critical | 1 | XS | faible | oui | — | CORRIGE |
| 3 | VIB-03 | Le contrat du fichier d'identité d'appareil diverge entre ses quatre producteurs et consommateurs | maintenabilité | critical | 3 | S | moyen | oui | VIB-02 | CORRIGE |
| 4 | VIB-04 | La création en lot d'appareils n'applique pas le contrôle de portée présent en création unitaire | sécurité | major | 1 | XS | faible | oui | — | A_FAIRE |
| 5 | VIB-05 | Le fichier d'identité déposé sur l'appareil est évalué comme du code par l'interpréteur, avec les droits les plus élevés | sécurité | major | 3 | S | moyen | oui | VIB-03 | CORRIGE |
| 6 | VIB-06 | Des identifiants non échappés sont concaténés dans des valeurs d'attribut puis injectés dans le document affiché | sécurité | major | 7 | S | faible | oui | — | A_FAIRE |
| 7 | VIB-07 | Le générateur de règles d'autorisation du courtier écrit ses règles dans le journal et installe la réponse brute de l'API à leur place | sécurité | major | 3 | S | faible | oui | — | A_FAIRE |
| 8 | VIB-08 | Des identifiants clients sont concaténés sans encodage dans le chemin d'URL d'un service interne non authentifié | sécurité | major | 6 | M | moyen | oui | — | A_FAIRE |
| 9 | VIB-09 | Vérification d'état puis action non atomique sur des ressources à usage unique ou à transition unique | sécurité | major | 7 | M | moyen | oui | — | A_FAIRE |
| 10 | VIB-10 | Le frein anti-force brute est indexé sur une dimension constante en déploiement réel et conservé en mémoire de processus | sécurité | major | 2 | M | moyen | oui | — | A_FAIRE |
| 11 | VIB-11 | L'interface consomme des champs d'entité inexistants côté serveur et affiche des indicateurs structurellement faux | maintenabilité | major | 7 | S | faible | oui | — | A_FAIRE |
| 12 | VIB-12 | Capture d'exception la plus large suivie d'un retour vide, sans journalisation : une panne amont s'affiche comme une absence de données | maintenabilité | major | 12 | S | moyen | oui | — | A_FAIRE |
| 13 | VIB-13 | Le contenu du journal d'audit n'est pas normalisé, ce qui rend son filtrage par portée partiellement inopérant | maintenabilité | major | 3 | M | moyen | oui | — | A_FAIRE |
| 14 | VIB-14 | Couverture de test concentrée sur un dépôt et un axe, avec une partie des tests silencieusement inertes | maintenabilité | major | 4 | XL | faible | oui | — | A_FAIRE |
| 15 | VIB-15 | Un réglage lu sur le chemin d'enrôlement n'est déclaré nulle part et n'est fourni par aucun environnement | évolutivité | major | 1 | XS | faible | oui | — | A_FAIRE |

Les 30 motifs suivants sont confirmés mais non détaillés dans ce cycle : voir la section dédiée.

**Gains rapides** (XS ou S, de sévérité `major` ou `critical`) : VIB-02, VIB-03, VIB-04, VIB-05,
VIB-06, VIB-07, VIB-11, VIB-12, VIB-15, VIB-16, VIB-17, VIB-18. Signalés comme tels, **sans remonter
dans l'ordre** : un gain rapide reste second par rapport à un motif critique difficile.

**Critiques remontés depuis un autre axe que la sécurité** : VIB-02 et VIB-03 (maintenabilité).
Remontée délibérée — la gravité prime sur l'axe. Ces deux motifs rendent inopérante la mise en service
d'un appareil neuf ; les reléguer derrière l'axe sécurité les aurait enterrés.

**Motif le plus important parmi les non détaillés** : VIB-17. La cible de comparaison des migrations
est dérivée des modèles, qui divergent de l'historique — la prochaine génération automatique de
migration supprimerait l'index d'unicité servant à authentifier les appareils. Difficulté S.

## Motifs détaillés

### VIB-01 — Le cloisonnement par site des requêtes de télémétrie est appliqué par réécriture textuelle de l'expression, et reste contournable

- **Axe / sévérité / difficulté** : sécurité / critical / L — **occurrences** : 4
- **Risque de régression** : moyen — quatre points d'entrée partagent une seule fonction, donc le correctif est localisé, mais toute interface envoyant aujourd'hui des expressions libres devra être adaptée, et les tests existants encodent le comportement permissif *(information, n'entre pas dans l'ordre)*
- **Impact** : un opérateur restreint à un site lit les métriques et les journaux de tous les autres sites. La validation a rejoué l'évasion par commentaire et en a trouvé une seconde, de forme différente, qui survivrait à une rustine anti-commentaire — ce qui établit que le défaut n'est pas une expression régulière à corriger mais l'approche elle-même : aucune réécriture textuelle ne peut cloisonner un langage de requête. La difficulté a été relevée de `M` à `L` pour cette raison.
- **Occurrences** : `api/app/routers/telemetry.py:256`, `:264`, `:280`, `:310`
- **Correction du motif** : ne pas cloisonner par réécriture — soit n'exposer que des points d'entrée paramétrés dont l'expression est construite côté serveur à partir de valeurs validées, comme le fait déjà le module d'observabilité voisin, soit déléguer le cloisonnement au moteur de données lui-même.
- **Statut** : CORRIGE — spec `specs/SPEC-cloisonnement-telemetrie.md`. Les quatre routes de requête à expression libre et la fonction de réécriture `_enforce_site_scope` avec ses deux expressions régulières sont supprimées ; plus aucun point d'entrée de l'API n'accepte d'expression PromQL/LogQL du client, et les lectures d'opérateur passent par les points d'entrée paramétrés d'`observability.py`, dont l'expression est construite côté serveur. Le prédicat de cloisonnement est unifié dans `api/app/routers/_scope.py`, sur la variante la plus stricte de chaque divergence : un jeton porteur d'un `site_scope` est cloisonné quel que soit son rôle, un jeton non-`admin` sans `site_scope` est refusé (403) au lieu d'être servi sur toute la flotte. L'unification porte sur **toute l'API** et non sur la seule télémétrie : les neuf copies locales du prédicat que portaient `audit.py`, `deployments.py`, `devices.py`, `hotfixes.py`, `operations.py`, `overrides.py`, `profiles.py`, `sites.py` et `zones.py` sont remplacées par l'appel unique, de sorte qu'un même jeton ne reçoit plus deux réponses contradictoires à la question « suis-je cloisonné ? » selon la route interrogée. Le durcissement porte sur les chemins de lecture comme de mutation, et chaque bascule est couverte par un test de régression marqué `security`, vérifié par mutation. Les deux évasions établies par la validation — bloc de sélecteur placé dans un commentaire `#`, et bloc placé dans un littéral chaîne d'un argument de `label_replace` — sont couvertes par des tests marqués `security` vérifiés comme échouant sur le code d'avant correction. **Non traité** : Grafana interroge Prometheus et Loki en direct, hors de l'API, donc un opérateur cloisonné lit toujours toute la flotte depuis Grafana Explore ou un tableau de bord. Cette moitié est ouverte sous `SEC-P0-08` et `SEC-P0-09` du `SECURITY_ROADMAP.md` et signalée en commentaire dans `platform/docker/grafana/provisioning/datasources/datasources.yml`.

### VIB-02 — Le chemin d'appel de provisionnement utilisé par l'appareil ne correspond à aucune route déclarée

- **Axe / sévérité / difficulté** : maintenabilité / critical / XS — **occurrences** : 1
- **Risque de régression** : faible — le chemin est actuellement non fonctionnel et non couvert ; le corriger ne peut casser aucun usage en production existant *(information, n'entre pas dans l'ordre)*
- **Impact** : le script de premier démarrage appelle un chemin sans identifiant d'appareil, alors que la route déclarée en porte un. L'enrôlement automatique d'un appareil neuf échoue donc en amont de toute autre logique. Aucun test ni simulateur n'emprunte ce chemin — le simulateur d'intégration continue passe par une route d'émission de jeton différente —, ce qui garantit que la casse reste invisible en intégration.
- **Occurrences** : `agent/usr/lib/fleet-agent/firstboot.sh:66` (route réellement déclarée : `api/app/routers/devices.py:90`)
- **Correction du motif** : aligner le chemin appelé sur la route déclarée, et faire du simulateur d'intégration le consommateur réel de ce chemin pour que toute divergence future casse la chaîne de validation.
- **Statut** : CORRIGE — PR FleetBits-api#23, FleetBits-agent#18, FleetBits-platform#13, mergées le 2026-09-13 (spec `specs/SPEC-contrat-identite-appareil.md`). `agent/usr/lib/fleet-agent/firstboot.sh` appelle le chemin déclaré, identifiant compris ; un test compare les deux segment par segment et une recherche textuelle vérifie qu'aucune occurrence de l'ancien chemin ne subsiste. **Non traité** : le simulateur d'intégration n'emprunte toujours pas ce chemin (il passe par la route d'émission de jeton) — la seconde moitié de la correction reste à faire.

### VIB-03 — Le contrat du fichier d'identité d'appareil diverge entre ses quatre producteurs et consommateurs

- **Axe / sévérité / difficulté** : maintenabilité / critical / S — **occurrences** : 3
- **Risque de régression** : moyen — touche la génération de justificatifs et le démarrage des services embarqués *(information, n'entre pas dans l'ordre)*
- **Impact** : trois divergences distinctes et toutes confirmées, au-delà du chemin d'appel traité en VIB-02. Le serveur renvoie un document structuré là où le consommateur attend un format évaluable par l'interpréteur. Le gabarit d'automatisation fournit une variable d'adresse exigée par le service de battement de cœur, que le contrat serveur ne renvoie pas ; à l'inverse il omet les justificatifs de bus de messages que le contrat serveur, lui, fournit — chaque voie d'installation produit donc un fichier incomplet, mais pas du même côté. Les adresses de télémétrie livrées à l'appareil désignent des noms d'hôte qui ne sont pas exposés par la configuration de routage.
- **Occurrences** : `agent/usr/lib/fleet-agent/firstboot.sh:87`, `platform/ansible/roles/fleet_agent/templates/device-identity.conf.j2:17`, `api/app/routers/devices.py:144`
- **Correction du motif** : déclarer le fichier d'identité comme un contrat unique et versionné — une seule définition de la liste des variables, un seul format de sérialisation négocié entre producteur et consommateur, et un générateur partagé par la voie de provisionnement serveur et la voie d'automatisation.
- **Statut** : CORRIGE — PR FleetBits-api#23, FleetBits-agent#18, FleetBits-platform#13, mergées le 2026-09-13 (spec `specs/SPEC-contrat-identite-appareil.md`). Contrat unique de 20 clés, source de vérité dans `api/app/contracts/device_identity.py`, format `CLE=valeur` inerte, produit à l'identique par la route de provisionnement, le gabarit Ansible et le point d'entrée conteneur ; un test compare les quatre ensembles de clés et échoue sur toute différence. Les adresses de télémétrie pointent désormais sur les hôtes et chemins réellement exposés par le routage.

### VIB-04 — La création en lot d'appareils n'applique pas le contrôle de portée présent en création unitaire

- **Axe / sévérité / difficulté** : sécurité / major / XS — **occurrences** : 1
- **Risque de régression** : faible — ajout d'une garde locale à une seule fonction, sans effet sur les comptes non restreints, et le prédicat à réutiliser existe déjà dans le même fichier *(information, n'entre pas dans l'ordre)*
- **Impact** : un compte restreint à un site crée, en une requête, des appareils rattachés à n'importe quel autre site — opération que l'équivalent unitaire refuse explicitement quelques lignes plus bas. Ces enregistrements deviennent ensuite éligibles à l'enrôlement, aux déploiements et aux opérations à distance du site visé. La suite de tests de frontières de portée, pourtant fournie, ne couvre pas ce point d'entrée.
- **Occurrences** : `api/app/routers/devices.py:202` (comportement correct de référence : `devices.py:269`)
- **Correction du motif** : appliquer la même vérification de portée à chaque élément du lot avant insertion, refuser le lot entier en cas d'élément hors portée, et ajouter le cas au fichier de tests de frontières existant.
- **Statut** : A_FAIRE

### VIB-05 — Le fichier d'identité déposé sur l'appareil est évalué comme du code par l'interpréteur, avec les droits les plus élevés

- **Axe / sévérité / difficulté** : sécurité / major / S — **occurrences** : 3
- **Risque de régression** : moyen — le fichier est consommé par plusieurs scripts et par la voie d'automatisation ; changer son mode de lecture demande de synchroniser producteur et consommateurs *(information, n'entre pas dans l'ordre)*
- **Impact** : le contenu du fichier d'identité est exécuté avec les droits les plus élevés sur chaque appareil, à chaque démarrage du service. L'adresse du service d'enrôlement étant elle-même lue dans un fichier posé sur la partition d'amorçage, le compromis d'un seul point — serveur, résolution de noms, ou accès physique au support — donne l'exécution sur toute la flotte. À noter : la validation a établi que ce vecteur n'est pas aujourd'hui atteignable depuis l'API, précisément parce que le format renvoyé n'est pas évaluable (VIB-03) — corriger VIB-03 sans corriger celui-ci ouvrirait le vecteur.
- **Occurrences** : `agent/usr/lib/fleet-agent/firstboot.sh:87`, `agent/usr/lib/fleet-agent/generate-config.sh:27`, `agent/usr/lib/fleet-agent/heartbeat.sh:27`
- **Correction du motif** : définir un format de données inerte et l'analyser avec un analyseur strict — paires clé/valeur validées ligne par ligne contre une liste blanche de clés et un jeu de caractères autorisé — au lieu de le faire évaluer par l'interpréteur.
- **Statut** : CORRIGE — PR FleetBits-api#23, FleetBits-agent#18, FleetBits-platform#13, mergées le 2026-09-13 (spec `specs/SPEC-contrat-identite-appareil.md`). Les trois consommateurs lisent le fichier par un analyseur strict à liste blanche (`agent/usr/lib/fleet-agent/identity-lib.sh`), jamais par `source` ni `eval` ; le jeu de caractères exclut les métacaractères shell, le verdict est indépendant de la locale et l'octet nul est rejeté. Vérifié par quatre passes adversariales indépendantes, dont environ 70 fixtures hostiles, injection par nom de clé comprise. **Trouvé et corrigé en chemin, hors du motif d'origine** : une valeur d'identité légale valant le nom d'un jeton de substitution faisait partir le jeton porteur de l'appareil en label de télémétrie.

### VIB-06 — Des identifiants non échappés sont concaténés dans des valeurs d'attribut puis injectés dans le document affiché

- **Axe / sévérité / difficulté** : sécurité / major / S — **occurrences** : 7
- **Risque de régression** : faible — réécriture localisée à un seul composant d'affichage *(information, n'entre pas dans l'ordre)*
- **Impact** : un opérateur, y compris restreint à un seul site, crée une ressource dont l'identifiant contient un guillemet ; le script s'exécute ensuite dans le navigateur de tout utilisateur affichant l'arborescence de navigation, administrateurs compris — avec vol de session applicative à la clé. La validation a relevé deux aggravants que l'audit initial avait manqués : le défaut touche trois familles d'identifiants et non une seule, et la fonction d'échappement du même fichier n'échappe pas les guillemets, donc elle ne serait pas sûre en contexte d'attribut même si elle y était appliquée.
- **Occurrences** : `ui/static/js/sidebar-tree.js:196`, `:198`, `:201`, `:217`, `:219`, `:222`, `:236` ; fonction d'échappement défaillante en `:286`
- **Correction du motif** : construire les nœuds par manipulation typée du document plutôt que par concaténation de chaînes de balisage, et corriger la fonction d'échappement pour qu'elle couvre le contexte d'attribut.
- **Statut** : A_FAIRE

### VIB-07 — Le générateur de règles d'autorisation du courtier écrit ses règles dans le journal et installe la réponse brute de l'API à leur place

- **Axe / sévérité / difficulté** : sécurité / major / S — **occurrences** : 3
- **Risque de régression** : faible — correction locale à un script d'amorçage de conteneur, sans dépendance applicative *(information, n'entre pas dans l'ordre)*
- **Impact** : établi octet par octet par une validation dédiée, arbitrant deux validateurs en désaccord. Le groupe qui produit les règles ne porte aucune redirection : ses lignes partent sur la sortie standard, c'est-à-dire le journal du conteneur, et le fichier de règles reçoit à la place le document structuré brut renvoyé par l'API. Le cloisonnement par appareil, que le document de planification déclare clos, n'est donc produit par aucun artefact réel. Le chemin reste toutefois **fermant** et non ouvrant : aucune identité d'appareil n'est jamais ajoutée au fichier de justificatifs du courtier, et les connexions anonymes sont refusées — la conséquence immédiate est une indisponibilité du bus, pas un contournement exploitable. Le rechargement demandé est de surcroît envoyé par un mécanisme d'administration dynamique non activé dans la configuration, avec code de retour supprimé.
- **Occurrences** : `platform/docker/mosquitto/docker-entrypoint.sh:51`, `:71`, `:72`
- **Correction du motif** : rediriger le groupe générateur vers un fichier de sortie et déplacer *ce* fichier vers le fichier de règles, en validant le contenu produit avant remplacement et en restaurant propriétaire et permissions après le déplacement. Corriger indépendamment l'alimentation du fichier de justificatifs en identités d'appareils.
- **Réserve explicite** : la validation n'a pas pu établir depuis le dépôt le comportement du courtier face à un fichier de règles invalide — refus de démarrage, rechargement ignoré, ou règles vides — et a refusé de le deviner. Un test sur le courtier réel est nécessaire pour qualifier la conséquence exacte.
- **Statut** : A_FAIRE

### VIB-08 — Des identifiants clients sont concaténés sans encodage dans le chemin d'URL d'un service interne non authentifié

- **Axe / sévérité / difficulté** : sécurité / major / M — **occurrences** : 6
- **Risque de régression** : moyen — six points d'appel dans un module de plus de mille lignes, plusieurs partagés avec le parcours de promotion ; un durcissement trop strict peut casser des noms existants *(information, n'entre pas dans l'ordre)*
- **Impact** : le service de dépôt interne est joignable sans authentification depuis l'API ; aucune liste blanche n'existe, et la seule validation en place ne contraint que le suffixe de canal, si bien que des segments de remontée de chemin la traversent. La validation a confirmé que la bibliothèque cliente normalise bien ces segments, donc la remontée atteint réellement d'autres opérations d'administration du service — altération possible de paquets distribués à toute la flotte.
- **Occurrences** : `api/app/routers/packages.py:41`, `:83`, `:215`, `:534`, `:678`, `:1023`
- **Correction du motif** : valider chaque identifiant contre une liste blanche dérivée des ensembles déjà connus du module, refuser tout segment hors motif, puis encoder les segments de chemin au lieu de les concaténer. Authentifier par ailleurs les appels sortants vers ce service interne.
- **Statut** : A_FAIRE

### VIB-09 — Vérification d'état puis action non atomique sur des ressources à usage unique ou à transition unique

- **Axe / sévérité / difficulté** : sécurité / major / M — **occurrences** : 7
- **Risque de régression** : moyen — change la forme des requêtes sur sept chemins de mutation ; aucun test de concurrence n'existe pour détecter une régression *(information, n'entre pas dans l'ordre)*
- **Impact** : deux requêtes concurrentes franchissent la même garde. Un jeton d'enrôlement annoncé à usage unique est consommé deux fois, donc deux identités d'appareil sont émises pour un seul jeton ; un déploiement ou une annulation est déclenché deux fois sur le parc. Les tâches d'orchestration étant déclenchées avant la validation de la transaction, les effets externes ne sont pas annulables par retour arrière. Le document de planification déclare le rejeu de jeton clos : le code ne ferme que le cas séquentiel.
- **Occurrences** : `api/app/routers/devices.py:120`, `:474`, `api/app/routers/deployments.py:158`, `api/app/routers/hotfixes.py:164`, `:194`
- **Correction du motif** : remplacer chaque garde par une mise à jour conditionnelle atomique qui consomme l'état de départ dans sa clause de filtrage et ne poursuit que si une ligne a été affectée ; ne déclencher tout effet externe irréversible qu'après validation de la transition.
- **Statut** : A_FAIRE

### VIB-10 — Le frein anti-force brute est indexé sur une dimension constante en déploiement réel et conservé en mémoire de processus

- **Axe / sévérité / difficulté** : sécurité / major / M — **occurrences** : 2
- **Risque de régression** : moyen — introduit une dépendance d'état partagé et peut verrouiller des usages automatisés légitimes si les seuils sont mal calibrés *(information, n'entre pas dans l'ordre)*
- **Impact** : les deux auditeurs se trompaient, et dans le sens qui aggrave. Le serveur d'application ne reçoit pas les en-têtes d'origine et aucun intergiciel ne les lit : en déploiement conteneurisé, toutes les requêtes externes portent l'adresse du terminateur de transport. La dimension d'adresse du compteur est donc constante. Conséquence relevée par la validation et manquée par les deux audits : **n'importe qui peut verrouiller le compte d'un opérateur légitime en cinq échecs**, ce qui transforme une protection en vecteur de déni de service. La pulvérisation sur de nombreux comptes depuis une source unique reste par ailleurs hors d'atteinte du seuil, l'état est perdu à chaque redémarrage, n'est pas partagé entre instances, et croît sans borne puisque la clé est un nom de compte arbitraire. L'adresse enregistrée dans le journal d'audit est celle du terminateur, pas celle de l'appelant.
- **Occurrences** : `api/app/routers/auth.py:166` (état), `:181` (construction de la clé)
- **Correction du motif** : porter le compteur dans un stockage partagé à expiration et le décliner en dimensions indépendantes — par compte, par source réelle, et global — avec des seuils distincts ; faire traverser les en-têtes d'origine pour que la dimension de source redevienne discriminante, condition sans laquelle le reste est sans effet.
- **Statut** : A_FAIRE

### VIB-11 — L'interface consomme des champs d'entité inexistants côté serveur et affiche des indicateurs structurellement faux

- **Axe / sévérité / difficulté** : maintenabilité / major / S — **occurrences** : 7
- **Risque de régression** : faible — les branches concernées sont déjà inertes ; les activer ne modifie qu'un affichage *(information, n'entre pas dans l'ordre)*
- **Impact** : l'indicateur d'appareils en ligne du tableau de bord vaut structurellement zéro et la colonne d'état du journal d'audit reste vide, quelle que soit la réalité du parc, sans aucun signal d'erreur. L'opérateur lit un tableau de bord qui ment. C'est la signature exacte d'une entité décrite différemment de part et d'autre de la frontière réseau, et la conséquence directe de l'absence de contrat de sortie déclaré sur une partie des routes.
- **Occurrences** : `ui/blueprints/inventory.py:141`, `ui/templates/audit.html:76`, et 5 autres branches de classification devenues mortes
- **Correction du motif** : dériver la forme consommée par l'interface du contrat de sortie du serveur plutôt que de la redécrire à la main, et faire échouer bruyamment l'accès à un champ inconnu au lieu de retomber sur une valeur par défaut.
- **Statut** : A_FAIRE

### VIB-12 — Capture d'exception la plus large suivie d'un retour vide, sans journalisation : une panne amont s'affiche comme une absence de données

- **Axe / sévérité / difficulté** : maintenabilité / major / S — **occurrences** : 12
- **Risque de régression** : moyen — les pages reposent aujourd'hui sur le fait que ces fonctions ne lèvent jamais ; rendre l'échec visible peut faire apparaître des erreurs sur des pages qui semblaient fonctionner *(information, n'entre pas dans l'ordre)*
- **Impact** : une panne du service amont, une erreur d'authentification ou une réponse malformée s'affichent comme un parc vide ou zéro paquet — dans un outil de gestion de flotte, c'est l'information la plus trompeuse possible. Le dépôt d'interface n'importe aucun module de journalisation : l'échec ne laisse aucune trace nulle part. La validation a resserré le périmètre : sur 32 sites du même gabarit, 12 seulement relèvent de la capture la plus large ; les 20 autres capturent une exception de domaine étroite et l'un d'eux justifie explicitement la dégradation.
- **Occurrences** : `ui/api_client.py:308`, `:322`, `:332`, `:344`, `:537`, et 7 autres dans le même fichier
- **Correction du motif** : distinguer trois états explicites dans la couche d'appel sortant — données, vide légitime, échec — et journaliser systématiquement l'échec avec sa cause avant de l'afficher comme tel.
- **Statut** : A_FAIRE

### VIB-13 — Le contenu du journal d'audit n'est pas normalisé, ce qui rend son filtrage par portée partiellement inopérant

- **Axe / sévérité / difficulté** : maintenabilité / major / M — **occurrences** : 3
- **Risque de régression** : moyen — normaliser les cibles écrites demande de toucher tous les routeurs producteurs d'événements *(information, n'entre pas dans l'ordre)*
- **Impact** : le filtrage par portée du journal d'audit ne s'applique qu'aux enregistrements portant une clé de site dans leur cible, que la plupart des écritures ne renseignent pas — un opérateur restreint voit donc des événements hors de son périmètre, ou en manque, selon le routeur qui les a produits. Le corps complet de certaines requêtes est par ailleurs recopié tel quel dans l'événement.
- **Occurrences** : `api/app/routers/deployments.py:133`, `api/app/models/audit.py:27`, `api/app/services/audit.py`
- **Correction du motif** : normaliser la structure de la cible d'un événement d'audit et imposer la présence d'une clé de site à l'écriture, pour que le filtrage par portée devienne effectif quel que soit le producteur.
- **Statut** : A_FAIRE

### VIB-14 — Couverture de test concentrée sur un dépôt et un axe, avec une partie des tests silencieusement inertes

- **Axe / sévérité / difficulté** : maintenabilité / major / XL — **occurrences** : 4
- **Risque de régression** : faible — ajouter des tests ne modifie aucun comportement de production *(information, n'entre pas dans l'ordre)*
- **Impact** : trois dépôts sur quatre n'ont aucun test et aucun workflow de test. Le seul dépôt testé l'est exclusivement sur l'axe des frontières de portée : la résolution de configuration effective, cœur métier documenté, n'a aucun test, et aucune route mutante de déploiement n'est exercée. La validation a contesté l'appréciation flatteuse portée par l'audit initial sur la qualité des tests existants et a montré que **treize sauts conditionnels neutralisent silencieusement toute une classe de tests** hors pile conteneurisée vivante, et que plusieurs assertions passent pour de mauvaises raisons — un test d'accès anonyme réussit parce que la route interrogée n'existe pas dans le transport utilisé. C'est précisément cette absence qui a laissé passer VIB-02, VIB-03 et VIB-11, tous invisibles fichier par fichier mais triviaux à détecter par un test de bout en bout.
- **Occurrences** : `api/tests/test_security_package_flow.py`, `api/tests/test_security_telemetry.py`, `api/app/services/resolver.py`, `ui/blueprints/inventory.py`
- **Correction du motif** : ajouter en priorité un test de bout en bout de la chaîne d'enrôlement réelle et un jeu de tests sur la résolution de configuration effective ; faire échouer bruyamment un test sauté plutôt que de le passer sous silence.
- **Statut** : A_FAIRE

### VIB-15 — Un réglage lu sur le chemin d'enrôlement n'est déclaré nulle part et n'est fourni par aucun environnement

- **Axe / sévérité / difficulté** : évolutivité / major / XS — **occurrences** : 1
- **Risque de régression** : faible — le chemin concerné est actuellement rompu, il ne peut que s'améliorer *(information, n'entre pas dans l'ordre)*
- **Impact** : le nom de domaine de la plateforme sert à fabriquer les adresses de télémétrie renvoyées à l'appareil, mais il n'est déclaré dans aucun réglage — les variables non déclarées étant explicitement ignorées — et n'est transmis au service par aucun environnement. L'accès échoue donc à l'exécution. La validation a corrigé la conséquence annoncée par l'audit : le jeton de provisionnement n'est **pas** brûlé, la transaction étant annulée ; l'enrôlement échoue proprement mais totalement. Deux validateurs indépendants ont trouvé ce défaut séparément, par deux chemins différents.
- **Occurrences** : `api/app/routers/devices.py:144` (réglages : `api/app/config.py`)
- **Correction du motif** : déclarer le réglage manquant avec validation au démarrage, le transmettre au service dans l'orchestration, et externaliser les adresses de télémétrie dans un réglage dédié plutôt que de les fabriquer par concaténation de sous-domaines.
- **Statut** : A_FAIRE (partiellement traité) — `FLEET_DOMAIN` est désormais déclaré dans `api/app/config.py` sans valeur par défaut, donc exigé au démarrage plutôt qu'absent à l'exécution, et injecté par la composition ; c'était nécessaire pour corriger VIB-03. Le reste du motif — l'audit exhaustif des autres réglages lus sans être déclarés — n'a pas été traité.

## Motifs non détaillés dans ce cycle

| ID | Motif | Axe | Sév. | Occ. | Diff. | Raison |
|---|---|---|---|---|---|---|
| VIB-16 | Le schéma est créé au démarrage depuis les modèles, en parallèle de l'historique de migration et sans marquage | évolutivité | major | 1 | S | au-delà du plafond |
| VIB-17 | Les modèles divergent de l'historique de migration alors qu'ils servent de cible de comparaison : la prochaine génération automatique supprimerait l'index d'unicité d'authentification des appareils | évolutivité | major | 3 | S | au-delà du plafond |
| VIB-18 | Les identifiants de gabarits d'exécution distante ne sont transmis par aucun environnement conteneurisé : les constantes du code sélectionnent le traitement réellement exécuté sur la flotte | évolutivité | major | 3 | S | au-delà du plafond |
| VIB-19 | Aucune pagination sur les collections destinées à croître, hors journal d'audit | évolutivité | major | 7 | M | au-delà du plafond |
| VIB-20 | Configuration d'infrastructure hors des réglages centralisés validés | évolutivité | major | 2 | M | au-delà du plafond |
| VIB-21 | Filtrage d'autorisation effectué en mémoire par une requête par élément, après lecture intégrale | évolutivité | major | 4 | L | au-delà du plafond |
| VIB-22 | Authentification d'un point d'entrée d'ingestion désactivable par drapeau, sans garde au démarrage | sécurité | minor | 1 | XS | mineur |
| VIB-23 | Directives injectables dans les paramètres de génération de la clé de signature du dépôt | sécurité | minor | 1 | XS | mineur |
| VIB-24 | Nom de fichier téléversé transmis sans normalisation au service de transit | sécurité | minor | 2 | XS | mineur |
| VIB-25 | Aucune exigence de qualité sur les secrets d'authentification acceptés en entrée | sécurité | minor | 3 | XS | mineur |
| VIB-26 | La réécriture d'expression corrompt silencieusement les requêtes légitimes contenant des quantificateurs | sécurité | minor | 1 | S | mineur |
| VIB-27 | Absence de contrainte de format sur les identifiants à la frontière de confiance | sécurité | minor | 1 | S | mineur |
| VIB-28 | Messages d'erreur de composants internes renvoyés littéralement au client | sécurité | minor | 16 | S | mineur |
| VIB-29 | Aucun en-tête de sécurité de réponse au terminateur de transport | sécurité | minor | 2 | S | mineur |
| VIB-30 | Listes d'amorçage machine lisibles par des comptes restreints à un autre périmètre | sécurité | minor | 2 | S | mineur |
| VIB-31 | Champs d'attribution fournis par le client et enregistrés comme faisant foi | sécurité | minor | 3 | S | mineur |
| VIB-32 | Empreinte de clé de dépôt enregistrée telle que déclarée, jamais dérivée du matériel de clé reçu | sécurité | minor | 1 | S | mineur (issu de la validation) |
| VIB-33 | Transition d'état finale appliquée sans vérifier l'état de départ | sécurité | minor | 1 | S | mineur |
| VIB-34 | Aucun jeton anti-rejeu sur les formulaires de mutation | sécurité | minor | 33 | M | mineur |
| VIB-35 | La promotion de paquets n'est liée à aucun plan validé et compare par version seule | sécurité | minor | 1 | M | mineur |
| VIB-36 | Le cloisonnement repose sur un attribut facultatif du compte plutôt que sur le rôle | sécurité | minor | 25 | M | **non validé** |
| VIB-37 | Aucune revendication de type ne distingue les familles de jetons signés | sécurité | minor | 3 | S | **non validé** |
| VIB-38 | Journal d'audit lisible par le rôle le plus faible, sans durée de conservation | sécurité | minor | 3 | S | **non validé** |
| VIB-39 | Copie non référencée d'un module de simulation, conservée à côté de la copie utilisée | maintenabilité | minor | 1 | XS | mineur |
| VIB-40 | Prédicat d'autorisation de portée dupliqué dans onze modules, avec une dérive déjà entamée | maintenabilité | minor | 12 | M | mineur |
| VIB-41 | Une partie des routes ne déclare aucun contrat de sortie | maintenabilité | minor | 21 | M | mineur |
| VIB-42 | Fichiers de gouvernance dupliqués entre les quatre dépôts et dérivés | maintenabilité | minor | 2 | M | mineur |
| VIB-43 | Clients de services externes instanciés dans les routeurs, incohérence avec la couche de services existante | maintenabilité | minor | 3 | M | mineur |
| VIB-44 | Index manquants sur des colonnes de filtrage et de tri | évolutivité | minor | 8 | S | mineur |
| VIB-45 | Traitements longs exécutés dans le cycle de requête, dont un téléversement sans plafond de taille | évolutivité | minor | 4 | L | mineur |

## Motifs rejetés à la validation

| ID | Motif | Raison du rejet |
|---|---|---|
| MNT-04 | Les contrats de mise à jour n'hériteraient d'aucune règle de validation des contrats de création | Cinq occurrences sur six fausses : la validation a trouvé les validateurs que l'audit affirmait absents. La conséquence annoncée — corruption des valeurs servant aux règles de portée — ne tient pas. |
| MNT-07 | Le sous-système de justificatifs du bus de messages serait une piste abandonnée déclarée close à tort | Réfuté sur pièces : la chaîne est branchée de bout en bout — injection des justificatifs à l'enrôlement, consommation par le rendu de configuration sur l'appareil, synchronisation des règles toutes les 300 secondes, application déployée cliente du bus. Le passage du battement de cœur en transport HTTP est un choix de conception documenté, pas un symptôme d'abandon. La remédiation proposée — supprimer le sous-système — aurait été destructrice. |
| INJ-02 | Valeurs interpolées sans échappement dans la génération de configuration sur l'appareil | Rejeté comme motif de sécurité : la prémisse est fausse, les valeurs proviennent de configuration d'exploitant de confiance, et la seule voie venant de l'API n'atteint jamais les substitutions puisque le format n'est pas évaluable (VIB-03). Le comptage annoncé était par ailleurs faux dans les deux termes. Un défaut de robustesse résiduel subsiste — une valeur contenant certains caractères corrompt silencieusement la configuration générée — mais il ne relève d'aucun des trois axes audités. |

## Suite

Ce rapport diagnostique ; il ne remédie pas. Pour en tirer un plan exécutable :
`/legacy-audit "/home/naej/repos/FleetBits"` — qui produit roadmap et specs, et couvre en complément la
dette d'accumulation que le présent audit ne cherche pas.

Deux remarques pour la suite, relevées par la validation hors du périmètre des trois axes et donc non
instruites comme motifs : aucun fichier d'exclusion ne protège la construction d'image, si bien qu'une
image construite localement embarquerait le fichier d'environnement du développeur ; et l'un des quatre
dépôts contient du code d'un langage pour lequel il n'a ni analyse statique en pré-validation ni tâche
d'analyse en intégration continue.
