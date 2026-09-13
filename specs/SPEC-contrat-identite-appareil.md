# Contrat unique et inerte du fichier d'identité d'appareil (VIB-02 / VIB-03 / VIB-05)

Statut : APPROUVEE

## Contexte

Le fichier `/etc/fleet/device-identity.conf` est le seul fichier de configuration lu par l'agent embarqué. Il est aujourd'hui produit par **trois** voies et consommé par **quatre** scripts, sans définition partagée ni format négocié. Trois findings de `AUDIT-vibecode.md` en découlent, et ils sont chaînés : VIB-03 dépend de VIB-02, VIB-05 dépend de VIB-03.

### Producteur « voie serveur » — `api/`

- `app/routers/devices.py:90` déclare `POST /devices/{device_id}/provision` (préfixe `/api/v1/devices`), `response_model=DeviceIdentity`, donc **sérialisée en JSON** par FastAPI.
- `app/schemas/device.py:74-96` définit `DeviceIdentity` : `DEVICE_ID`, `SITE_ID`, `ZONE_ID`, `DEVICE_ROLE`, `PROFILE`, `FLEET_AGENT_TOKEN`, `REPO_BASIC_TOKEN`, `FLEET_METRICS_URL`, `FLEET_LOGS_URL`, `HEADSCALE_PREAUTH_KEY`, `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`. Son docstring affirme « Written by agent as shell-sourceable env vars », ce que le format JSON ne permet pas.
- `devices.py:144-145` fabrique `https://prometheus.{FLEET_DOMAIN}` et `https://loki.{FLEET_DOMAIN}`. `FLEET_DOMAIN` n'existe pas dans `app/config.py` ; les hôtes réellement exposés par `platform/docker/caddy/Caddyfile:46` et `:57` sont `metrics.{FLEET_DOMAIN}` avec chemin `/api/v1/write` et `logs.{FLEET_DOMAIN}` avec chemin `/loki/api/v1/push`. Ni l'hôte ni le chemin ne correspondent.

### Producteur « voie conteneur » et les quatre consommateurs — `agent/`

- `usr/lib/fleet-agent/firstboot.sh:66` appelle `POST ${API_URL}/api/v1/devices/provision`, **sans identifiant d'appareil dans le chemin**, alors que la route déclarée est `/{device_id}/provision` (VIB-02). Le corps envoyé porte `{"device_id": ...}`, que la route ne lit pas.
- `firstboot.sh:70` écrit la réponse HTTP brute (JSON) dans `IDENTITY_FILE`, puis `:87` fait `source "${IDENTITY_FILE}"` (VIB-05) ; `:134`, `:138`, `:173` relisent le même fichier par `grep '^CLE=' | cut -d'=' -f2-`, soit un troisième mode de lecture, incompatible avec le JSON écrit.
- `usr/lib/fleet-agent/generate-config.sh:27` : `source "${IDENTITY_FILE}"`, puis exige `SITE_ID ZONE_ID DEVICE_ID DEVICE_ROLE FLEET_METRICS_URL FLEET_LOGS_URL FLEET_AGENT_TOKEN` (`:30`), et lit en plus `PROFILE`, `SCRAPE_INTERVAL`, `ENABLE_MQTT_EXPORTER`, `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `ENABLE_PROCESS_EXPORTER`.
- `usr/lib/fleet-agent/heartbeat.sh:27` : `source "${IDENTITY_FILE}"`, exige `FLEET_API_URL`, `FLEET_AGENT_TOKEN`, `DEVICE_ID` (`:29`).
- `container-entrypoint.sh:34-49` écrit lui-même un fichier d'identité en paires `CLE=valeur` à partir de variables d'environnement — troisième producteur, avec sa propre liste de champs.
- `etc/fleet/device-identity.conf.example` et `README.md:169-193` documentent deux listes de champs qui ne coïncident ni entre elles ni avec les producteurs.
- `scripts/postinst.sh:33-38` teste l'existence du fichier et déclenche `generate-config.sh`.
- Les trois scripts tournent sous root (`fleet-firstboot.service`, `fleet-agent.service` `ExecStartPre=`, `fleet-heartbeat.timer`), d'où la sévérité de VIB-05.

### Producteur « voie automatisation » — `platform/`

- `ansible/roles/fleet_agent/templates/device-identity.conf.j2` produit `SITE_ID ZONE_ID DEVICE_ID DEVICE_ROLE PROFILE ENVIRONMENT RING FLEET_METRICS_URL FLEET_LOGS_URL FLEET_API_URL FLEET_AGENT_TOKEN ENABLE_MQTT_EXPORTER MQTT_BROKER_HOST MQTT_BROKER_PORT ENABLE_PROCESS_EXPORTER SCRAPE_INTERVAL`, déployé par `ansible/roles/fleet_agent/tasks/main.yml:39` en mode `0640` — alors que `firstboot.sh:77` et `postinst.sh:34` imposent `600`.
- `ansible/playbooks/collect_diagnostics.yml:46-50` lit le fichier ligne à ligne (`grep -v FLEET_AGENT_TOKEN`) pour produire une copie « expurgée » : consommateur supplémentaire du format, qui ne masque aujourd'hui aucun des autres secrets du contrat.
- `docker/docker-compose.yml:310-335` (`vps-device`) alimente `container-entrypoint.sh` par variables d'environnement et court-circuite entièrement l'enrôlement.

### Divergences de champs constatées, au-delà du chemin d'appel

| Champ | API `DeviceIdentity` | gabarit Ansible | `container-entrypoint.sh` | Exigé par |
|---|---|---|---|---|
| `FLEET_API_URL` | **absent** | présent | présent | `heartbeat.sh:29` (échec fatal) |
| `REPO_BASIC_TOKEN` | présent | **absent** | **absent** | `firstboot.sh:173-174` (échec fatal) |
| `HEADSCALE_PREAUTH_KEY` | présent, toujours `None` (`devices.py:185`) | **absent** | **absent** | `firstboot.sh:88` (facultatif) |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | présents | **absents** | **absents** | `generate-config.sh:71-77` si MQTT actif |
| `ENABLE_MQTT_EXPORTER`, `ENABLE_PROCESS_EXPORTER`, `SCRAPE_INTERVAL` | **absents** | présents | présents | `generate-config.sh` (avec défauts) |
| `ENVIRONMENT`, `RING` | **absents** | présents | présents | aucun script ; pourtant labels obligatoires selon `GUIDELINES.md` §11 |
| `FLEET_METRICS_URL` / `FLEET_LOGS_URL` | `prometheus.` / `loki.`, sans chemin | `metrics.…/api/v1/write` / `logs.…/loki/api/v1/push` | valeurs internes docker | `generate-config.sh:107` exige une URL absolue pour Vector |

### Contraintes posées par le Product Owner

- Le projet **n'a jamais été déployé** : aucun appareil enrôlé, aucune base vivante, aucun consommateur externe. Casser un contrat est gratuit et préférable à une compatibilité de façade.
- **Aucune cohabitation de formats, aucun shim de migration, aucun drapeau de transition, aucun alias de route.** Les quatre producteurs et consommateurs sont réécrits d'un seul coup.
- Le chemin de provisionnement est **aligné franchement** — l'appelant est corrigé, pas la route dupliquée sous un alias.
- Une **migration vers un monorepo est prévue une fois les findings de l'audit soldés**. Les choix de ce cycle doivent survivre à cette fusion sans redécoupage : la définition unique vit dans `api/` (elle deviendra un module partagé), et le harnais de test reste par dépôt (chaque dépôt deviendra un package avec sa propre suite).

### Décisions d'arbitrage retenues

1. **Format inerte** : paires `CLE=valeur`, une par ligne, sans guillemets ni expansion, lues par un analyseur strict à liste blanche. Jamais évaluées par l'interpréteur.
2. **Source de vérité du contrat** : `api/`. `agent/` et `platform/` la dupliquent, la cohérence étant garantie par un test de comparaison d'ensembles de clés.
3. **Adresses de télémétrie** : `FLEET_DOMAIN` est déclaré dans `app/config.py` et les adresses sont construites sur les hôtes et chemins réellement exposés par le `Caddyfile`.
4. **Harnais de test** : `bats` (+ `shellcheck`) pour `agent/` ; vérification du rendu de gabarit pour `platform/`. Un point d'entrée par dépôt.
5. **`ENVIRONMENT` et `RING`** : entrent dans le contrat, sont renvoyés par l'API et **substitués dans les gabarits de télémétrie**, conformément à `GUIDELINES.md` §11.
6. **`HEADSCALE_PREAUTH_KEY`** : reste dans le contrat comme champ facultatif déclaré, valeur vide acceptée par l'analyseur. La branche d'enrôlement Headscale de `firstboot.sh` est conservée en l'état.
7. **Jeton de provisionnement du test de bout en bout** : fourni par une fixture créant directement l'enregistrement `ProvisionToken`. L'absence d'amorce serveur est signalée comme finding distinct, hors périmètre.

## Périmètre

### `api/`

- La route de provisionnement cesse de renvoyer un document JSON et renvoie le fichier d'identité en paires `CLE=valeur`, directement écrivable sur disque par l'appelant.
- Le contrat d'identité devient une définition unique et versionnée, portant exactement les champs dont les consommateurs ont besoin — `FLEET_API_URL`, `ENVIRONMENT` et `RING` inclus, aujourd'hui absents.
- `FLEET_DOMAIN` est déclaré dans `app/config.py` ; les adresses de télémétrie renvoyées désignent des hôtes et chemins effectivement exposés par le routage de `platform/`.
- Tests d'enrôlement de bout en bout ajoutés au jeu existant.

### `agent/`

- `firstboot.sh` appelle le chemin de provisionnement réellement déclaré, identifiant d'appareil compris.
- Les trois consommateurs (`firstboot.sh`, `generate-config.sh`, `heartbeat.sh`) cessent d'évaluer le fichier d'identité par l'interpréteur et le lisent via un analyseur strict commun, validant clés et valeurs.
- `container-entrypoint.sh` produit un fichier d'identité conforme au même contrat unique.
- Les gabarits de télémétrie substituent `ENVIRONMENT` et `RING` en labels.
- Le fichier d'exemple et la documentation d'agent décrivent la liste de champs canonique et unique.
- Un harnais `bats` est mis en place (aucun test n'existe aujourd'hui), avec `shellcheck` en intégration continue.

### `platform/`

- `device-identity.conf.j2` produit un fichier conforme au même contrat unique, avec les mêmes champs et le même mode de fichier que la voie serveur.
- Le service `vps-device` de `docker/docker-compose.yml` reste démarrable après la réécriture du contrat.
- La tâche de collecte de diagnostics expurge **tous** les champs déclarés secrets par le contrat.
- Un harnais de test est mis en place (aucun n'existe aujourd'hui).

### `ui/`

Aucun changement : ce dépôt ne produit ni ne consomme le fichier d'identité.

## Critères d'acceptation

1. Le chemin d'URL construit dans `agent/usr/lib/fleet-agent/firstboot.sh` pour l'appel de provisionnement contient le segment d'identifiant d'appareil et correspond, segment par segment, au chemin déclaré par le décorateur de route de `api/app/routers/devices.py` ; une recherche textuelle dans les trois dépôts ne fait apparaître aucune occurrence de `/devices/provision` sans identifiant. *(agent/, api/)*
2. Aucun fichier de `agent/usr/lib/fleet-agent/` ni `agent/container-entrypoint.sh` ne contient d'instruction `source` ou `.` appliquée au fichier d'identité ; vérifiable par recherche textuelle renvoyant zéro occurrence. *(agent/)*
3. La lecture du fichier d'identité rejette, avec un code de sortie non nul et un message sur la sortie d'erreur, tout fichier contenant une clé absente de la liste blanche du contrat et tout fichier dont une valeur contient un caractère hors du jeu autorisé ; démontré par un test `bats` exécutant chacun des trois consommateurs sur des fixtures malveillantes. *(agent/)*
4. Un test `bats` exécute chacun des trois consommateurs sur un fichier d'identité contenant une valeur conçue pour s'exécuter si le fichier était évalué par l'interpréteur (substitution de commande, point-virgule suivi d'une commande, expansion de variable) ; le test échoue si la commande injectée s'exécute, et vérifie l'absence de son effet observable. *(agent/)*
5. La liste des clés produites par la route de provisionnement de `api/`, celle produite par `platform/ansible/roles/fleet_agent/templates/device-identity.conf.j2`, celle produite par `agent/container-entrypoint.sh` et celle acceptée par la liste blanche de l'analyseur sont identiques ensemble à ensemble ; un test automatisé compare ces quatre ensembles et échoue sur toute différence. *(api/, platform/, agent/)*
6. Le fichier produit par la route de provisionnement contient une clé `FLEET_API_URL` non vide ; `heartbeat.sh` exécuté sur ce fichier atteint l'émission de la requête HTTP sans déclencher son contrôle de variables obligatoires. *(api/, agent/)*
7. Le fichier produit par le gabarit Ansible contient les clés que `firstboot.sh` traite comme fatales lorsqu'elles manquent, ou bien `firstboot.sh` ne les traite plus comme fatales ; aucun des deux fichiers ne référence une clé que l'autre ne peut fournir. *(platform/, agent/)*
8. Les valeurs de `FLEET_METRICS_URL` et `FLEET_LOGS_URL` renvoyées par la route de provisionnement correspondent à un couple hôte + chemin défini dans `platform/docker/caddy/Caddyfile` ; un test compare les valeurs renvoyées aux motifs d'hôte et de chemin déclarés dans le `Caddyfile`. *(api/, platform/)*
9. `FLEET_DOMAIN` est déclaré dans `api/app/config.py` et injecté par `platform/docker/docker-compose.yml` ; démarrer l'API sans ce réglage produit une erreur de configuration explicite au démarrage, et non une erreur à l'exécution de la route. *(api/, platform/)*
10. `FLEET_LOGS_URL` renvoyé par la route de provisionnement satisfait l'expression régulière d'URL absolue appliquée par `generate-config.sh:107` ; vérifié par un test qui passe la valeur renvoyée à la fonction de rendu Vector. *(api/, agent/)*
11. `ENVIRONMENT` et `RING` figurent dans le contrat, sont renvoyés par la route de provisionnement avec des valeurs non vides, et apparaissent comme labels dans la configuration de télémétrie rendue par `generate-config.sh` ; un test inspecte la sortie rendue et échoue si l'un des deux labels manque. *(api/, agent/)*
12. `HEADSCALE_PREAUTH_KEY` est déclaré dans le contrat, accepté vide par l'analyseur, et son absence de valeur ne fait échouer aucun des trois consommateurs ; un test exécute `firstboot.sh` sur un fichier où la clé est présente et vide, et vérifie que la branche Headscale est ignorée sans erreur. *(agent/, api/)*
13. Un test de bout en bout, dans `api/tests/`, part d'un appareil et d'un jeton de provisionnement créés par fixture, appelle la route de provisionnement telle que `firstboot.sh` l'appelle, et vérifie que le corps de réponse est accepté sans erreur par l'analyseur de fichier d'identité de `agent/` ; ce test échoue si le chemin, le format ou la liste de champs diverge. *(api/)*
14. Le dépôt `agent/` contient un point d'entrée de test `bats` exécutable par une commande unique documentée, exécuté par un workflow d'intégration continue de ce dépôt, couvrant au minimum les critères 3, 4, 11 et 12, et accompagné d'une passe `shellcheck` sur tous les scripts du dépôt. *(agent/)*
15. Le dépôt `platform/` contient un point d'entrée de test exécutable par une commande unique documentée, exécuté par un workflow d'intégration continue de ce dépôt, vérifiant que le rendu de `device-identity.conf.j2` avec un jeu de variables d'inventaire d'exemple est accepté par l'analyseur de `agent/`. *(platform/)*
16. Le mode de fichier appliqué au fichier d'identité est identique dans `platform/ansible/roles/fleet_agent/tasks/main.yml`, `agent/usr/lib/fleet-agent/firstboot.sh` et `agent/scripts/postinst.sh` ; vérifiable par inspection des trois fichiers. *(platform/, agent/)*
17. La tâche « Collect device identity (redact token) » de `platform/ansible/playbooks/collect_diagnostics.yml` ne laisse apparaître aucune des clés du contrat désignées comme secrètes dans la définition unique ; vérifié par un test appliquant la commande de redaction à un fichier d'identité complet et cherchant chaque valeur secrète dans la sortie. *(platform/)*
18. `agent/etc/fleet/device-identity.conf.example` contient exactement les clés du contrat, sans clé supplémentaire ni manquante ; comparaison automatisée avec la liste blanche. *(agent/)*
19. Le bloc de référence de `agent/README.md` décrivant le fichier d'identité liste les mêmes clés que le fichier d'exemple ; comparaison mécanique des deux listes. *(agent/)*
20. Le point d'entrée `container-entrypoint.sh` produit, à partir des variables déclarées pour le service `vps-device` dans `platform/docker/docker-compose.yml`, un fichier d'identité accepté par l'analyseur ; vérifié par un test exécutant le point d'entrée hors conteneur sur ces variables. *(platform/, agent/)*
21. Aucun drapeau de configuration, aucune variable d'environnement ni aucun paramètre de requête ne permet de sélectionner l'ancien format ou l'ancien chemin ; l'ancienne route, l'ancien format et toute forme de lecture par `source` ne subsistent nulle part dans les quatre dépôts, vérifiable par recherche textuelle. *(api/, agent/, platform/)*
22. `pre-commit run --all-files` passe sur les trois dépôts modifiés, y compris `gitleaks`, `actionlint`, et pour `api/` `bandit -ll` et `ruff --select S`. *(api/, agent/, platform/)*
23. Les suites de tests des trois dépôts touchés passent : `./.venv/bin/python -m pytest` pour `api/`, `shellcheck` + `bats` pour `agent/`, `docker compose config -q` + `ansible-playbook --syntax-check` + `ansible-lint` + le point d'entrée de test pour `platform/`. *(api/, agent/, platform/)*

## Hors-périmètre

- **VIB-15** — la déclaration de `FLEET_DOMAIN` est traitée ici (critère 9) parce que sans elle la route reste inopérante à l'exécution, mais le reste du finding (audit exhaustif des réglages non déclarés de `app/config.py`) n'est pas couvert.
- **VIB-04** — contrôle de portée absent en création en lot (`devices.py:202`) : même fichier, finding indépendant, non traité.
- **VIB-09** — consommation non atomique du jeton de provisionnement (`devices.py:120`) : même route, finding distinct, non traité.
- **VIB-07** (règles du courtier MQTT) et **VIB-17** (dérive modèles/migrations) : non traités. Le contrat transporte les justificatifs MQTT, mais la génération des règles côté courtier n'est pas modifiée.
- **VIB-14** — couverture de test : seuls les harnais et tests nécessaires aux critères ci-dessus sont créés ; l'extension de la couverture aux autres axes n'est pas dans ce cycle.
- **Amorce de la chaîne d'enrôlement** : aucune route de `api/` n'appelle `create_provision_token` et aucun enregistrement `ProvisionToken` n'est jamais créé. Le test de bout en bout contourne ce défaut par fixture (décision 7). La création de la route d'émission de jeton et la réécriture du simulateur `vps-device` pour qu'il passe par le vrai provisionnement sont **explicitement reportées**.
- **Intégration Headscale réelle** : la clé de pré-authentification reste déclarée et vide ; la faire réellement produire est hors cycle.
- **`ui/`** : aucun changement.
- **Migration vers un monorepo** : hors de ce cycle, mais les choix de structure doivent y survivre sans redécoupage (voir Contexte).
- **Signalés en chemin, non traités** : l'en-tête de `firstboot.sh:18` renvoie vers un parcours « Fleet UI → Device View → [Replace device] » produisant `fleet-provision.json`, absent de `ui/`.
- **Interdit** — `AUDIT-vibecode.md:132` et `:269` : l'inertie du format est ce qui neutralise aujourd'hui le vecteur d'exécution et ce qui a fait rejeter INJ-02. Aucun correctif ne doit rendre le format évaluable, même transitoirement ; VIB-03 et VIB-05 sont livrés dans le même changement.

## Risques

- **Dépendance croisée VIB-03/VIB-05** : livrer le format côté API sans avoir remplacé les trois `source` côté agent ouvrirait l'exécution de code root sur tout appareil à chaque démarrage de service. Le changement doit être cohérent dans les trois dépôts, ce que la structure en quatre dépôts git indépendants ne garantit pas par un commit unique — fenêtre de désynchronisation possible entre dépôts. Atténuation : le critère 5 fait échouer la CI de tout dépôt désynchronisé.
- **Régression sur le rendu de configuration** : `generate-config.sh` substitue les valeurs par `sed` avec `|` comme délimiteur et n'échappe que `MQTT_USERNAME` et `MQTT_PASSWORD` (`:71-72`). Un analyseur qui autoriserait `|`, `&`, `\` ou un saut de ligne dans les autres valeurs transformerait le défaut de robustesse résiduel décrit en `AUDIT-vibecode.md:269` en corruption silencieuse de la configuration générée. Le jeu de caractères autorisé par la liste blanche doit être choisi en conséquence.
- **Chargement de secrets multiples** : le contrat transporte `FLEET_AGENT_TOKEN`, `REPO_BASIC_TOKEN`, `MQTT_PASSWORD` et `HEADSCALE_PREAUTH_KEY`. La redaction actuelle n'en masque qu'un ; élargir la liste blanche sans élargir la redaction exfiltrerait des secrets dans les archives de diagnostic (`GUIDELINES.md` §3).
- **Mode de fichier `0640` vs `600`** : l'alignement (critère 16) peut retirer l'accès au fichier à un groupe qui en dépend dans un rôle Ansible non inspecté.
- **Le test de bout en bout passe par fixture** (décision 7) : il démontre la cohérence du contrat, pas la chaîne d'enrôlement réelle — exactement le motif d'« assertion qui passe pour une bonne raison mais ne couvre pas la vraie voie » que `AUDIT-vibecode.md:214` reproche aux tests existants. Le risque est assumé et le finding reporté est nommé en hors-périmètre.
- **Élargissement aux gabarits de télémétrie** (décision 5) : substituer `ENVIRONMENT` et `RING` touche les gabarits Alloy et Vector, non prévus au périmètre initial de VIB-03. Risque de régression sur le rendu de télémétrie.
- **Aucune compatibilité ascendante à préserver** : le projet n'a jamais été déployé. Le risque réel n'est pas la rupture de contrat mais l'**oubli d'un consommateur secondaire** (`collect_diagnostics.yml`, `postinst.sh`, fichier d'exemple, `README.md`, `docker-compose.yml`).

## Questions ouvertes

Aucune.
