# Remise à plat de la gestion des mises à jour de dépendances

Statut : APPROUVEE

> **Amendement du 2026-09-22, décidé par le Product Owner après la première passe de vérification.**
> Deux critères étaient mal écrits de ma part et sont corrigés ici.
> **Critère 15** exigeait la fermeture des 13 PR *pendant* le cycle. C'est mal séquencé : dependabot
> ne recrée pas une PR fermée sans merge — il la lit comme un refus pour cette version — donc fermer
> avant que la nouvelle configuration soit sur `main` risquerait de perdre ces treize mises à jour.
> Il devient une **action post-merge**, tracée ci-dessous, et sort des critères d'acceptation.
> **Critère 17** exigeait qu'`actionlint` passe, sans distinguer ses règles propres de son intégration
> shellcheck optionnelle, dont les trois constats sont antérieurs au cycle et hors de son périmètre.
> **Une décision supplémentaire** : les dépendances de test de `ui/` vont dans un fichier séparé.

## Contexte

### Le point de départ

**13 PR dependabot sont ouvertes, dont 12 depuis le 2026-09-13** — huit jours sans avancer. Un workflow d'auto-approbation et d'auto-merge tourne à chaque fois, et échoue à chaque fois, en silence.

`.github/workflows/dependabot-auto-approve.yml` (87 lignes) se déclenche sur `pull_request_target` vers `main`, avec `permissions: pull-requests: write` **et `contents: write`**. Il enchaîne quatre étapes :

- `dependabot/fetch-metadata@v2` — sa sortie n'est **consommée par aucune étape** ; l'étape ne sert à rien ;
- « Wait for CI checks to pass » — boucle jusqu'à 10 minutes. Sa logique est fausse indépendamment des droits : `.every(check => check.conclusion === 'success' || check.status !== 'completed')` compte comme « passé » un check **encore en cours** ;
- « Approve PR » (ligne 68, `continue-on-error: true`) ;
- « Enable auto-merge » (ligne 82, `continue-on-error: true`) — `gh pr merge --squash --auto`.

Réglages du dépôt mesurés : `can_approve_pull_request_reviews = false`, `allow_auto_merge = false`, `default_workflow_permissions = read`. Les deux dernières étapes échouent donc systématiquement — `GitHub Actions is not permitted to approve pull requests` — et les deux `continue-on-error: true` transforment cet échec en run **`success`**.

C'est un vert pour une mauvaise raison, exactement le motif que `AUDIT-vibecode.md` reproche au dépôt en **VIB-14**. Aucun `VIB-xx` ne vise nommément ce workflow : cette spécification n'en clôt aucun, elle en applique la doctrine.

### Ce que personne ne surveille

`.github/dependabot.yml` déclare cinq entrées, toutes `weekly`, sans `groups`, sans `labels`. Constats mécaniques :

- l'entrée `docker` sur `/platform` **ne surveille rien** : il n'existe aucun `Dockerfile` à `platform/`, les treize vrais sont sous `platform/docker/<service>/`, et `directory:` n'est pas récursif ;
- ne sont surveillés par **aucune** entrée : `api/Dockerfile`, `ui/Dockerfile`, `platform/docker/mqtt-exporter/requirements.txt`, et les treize `FROM` de la plateforme — `prom/prometheus:v2.52.0`, `grafana/grafana-oss:11.1.0`, `grafana/loki:3.0.0`, `prom/alertmanager:v0.27.0`, `headscale/headscale:0.23`, `caddy:2.8-alpine`, `postgres:16-alpine`, `debian:12-slim`, `eclipse-mosquitto:2`, `python:3.12-alpine`, `python:3.12-slim` ;
- quatre images épinglées **dans** `platform/docker/docker-compose.yml` ne sont surveillées par personne : `grafana/grafana-oss:11.1.0` (l. 73), `semaphoreui/semaphore:v2.10.22` (102), `prom/node-exporter:v1.8.2` (233), `gcr.io/cadvisor/cadvisor:v0.49.2` (247) ;
- hors de portée dependabot par nature : les `rev:` des quatre `.pre-commit-config.yaml`, et les versions d'outils codées dans les harnais — `SHELLCHECK_IMAGE=koalaman/shellcheck:v0.11.0` (`platform/scripts/run-tests.sh:53`) contre `koalaman/shellcheck:stable` et `bats/bats:latest` (`agent/scripts/run-tests.sh:20-21`), `willhallonline/ansible:latest` et `pipelinecomponents/ansible-lint:latest` (`platform/scripts/run-tests.sh:46-47`), ainsi que les `pip install pip-audit bandit` et `pip install ansible-core ansible-lint` des workflows, tous non épinglés.

### Ce qui valide réellement une montée de version

| Écosystème surveillé | Ce qui s'exécute sur la PR | Valeur |
|---|---|---|
| `pip` `/api` | `api-tests.yml` → `pytest` complet ; `security-regression-stack.yml` → pile compose réelle ; `api-sast-and-deps` → `pip-audit` + `bandit` | **Réelle** |
| `pip` `/ui` | `build-fleet-ui.yml` construit l'image, donc `pip install` doit résoudre ; `ui-sast-and-deps` → `pip-audit` + `bandit` | **Quasi nulle** : `ui/` n'a **aucun test, aucun harnais**. Validé par « l'installation résout » et « aucun CVE connu », jamais par « l'application démarre ». `fleet-ui` n'est même pas démarré par la pile d'intégration |
| `docker` `/agent` | `agent-tests.yml` → shellcheck + bats, qui **ne construisent ni ne lancent l'image** ; le job qui la construit est gardé par `if: startsWith(github.ref, 'refs/tags/v')` | **Nulle** : le saut `ubuntu` 24.04 → 25.10 n'est exercé par rien |
| `docker` `/platform` | — | **Sans objet** : l'entrée ne voit aucun fichier |
| `github-actions` `/` | **Rien** : les filtres `paths:` des quatre suites ne listent que *leur propre* fichier de workflow | **Nulle** : une PR montant `checkout` 4→7 n'exécute rien qui utilise `checkout` |

### Deux pièges déjà armés

- `build-fleet-agent.yml` porte `upload-artifact@v4` (l. 53) face à `download-artifact@v8` (l. 79), sur un chemin `publish-dev` qui **ne s'exécute que sur un tag** : aucune PR ne le révélera, la casse apparaîtra à la première release.
- `api/requirements.txt` documente en tête un jeu de versions **couplées** (`fastapi`, `starlette`, `prometheus-fastapi-instrumentator`, `python-multipart`, `pytest`) : une PR dependabot isolée sur l'un d'eux casse les 89 tests.

### Une affirmation fausse dans un document actif

`pr-security-checklist.yml:13` porte `if: github.actor != 'dependabot[bot]'` : le job est **sauté** pour le bot. Et `.github/PULL_REQUEST_TEMPLATE.md:8` affirme « **For Dependabot PRs:** Security items below are auto-verified by CI. No manual action needed. » Rien n'auto-vérifie ces items. `GUIDELINES.md` §6 interdit de laisser une affirmation de sécurité périmée dans un document actif.

### Décisions d'arbitrage retenues

1. **Aucun merge automatique.** Le mécanisme d'auto-approbation et d'auto-merge **cesse d'exister**, il n'est pas réparé. Les PR de dépendances sont relues et mergées par un humain.
2. **`continue-on-error` n'est pas conservé** : un échec est visible.
3. **Les sauts sont testés**, pas arbitrés sur leur numéro.
4. **Lot en cours** : les 13 PR sont **fermées** avec un motif écrit, la configuration est appliquée, et dependabot rouvre en PR groupées que le nouveau dispositif teste réellement.
5. **Périmètre de surveillance étendu** : l'entrée morte est corrigée, et les treize `Dockerfile` de `platform/docker/*/`, `api/Dockerfile`, `ui/Dockerfile` et `platform/docker/mqtt-exporter/requirements.txt` entrent sous surveillance. Les images du `docker-compose.yml` **n'y entrent pas** : l'écosystème `docker-compose` est en bêta chez GitHub.
6. **Groupes `github-actions`** : mineures et correctifs groupés, **majeures en PR séparée**.
7. **Groupes `pip`** : **un groupe par composant**, tout niveau confondu, pour que le jeu couplé de `api/requirements.txt` bouge d'un bloc.
8. **`ui/`** : un **test de fumée minimal** — importer `server.py` et vérifier que l'application Flask se construit. Proportionné à l'objectif : valider une montée de version, pas couvrir le composant.
9. **Gabarit de PR** : l'affirmation fausse disparaît, le job reste sauté pour le bot. La relecture humaine tient lieu de checklist.
10. **Outils de CI** : on épingle **ce qui porte un cliquet** (`ansible-lint`, `bats`), et on aligne `agent/scripts/run-tests.sh` sur le `koalaman/shellcheck:v0.11.0` de la plateforme.
11. **Cadence** : `weekly` sur les cinq écosystèmes, sans plafond d'ouverture — un plafond atteint masquerait silencieusement les mises à jour suivantes, précisément le vice qu'on corrige.

Le projet n'a jamais été déployé : aucun appareil enrôlé, aucune base vivante. Les risques de ce cycle sont des risques de chaîne de construction, pas de compatibilité. Tout ce qui survit au cycle s'écrit en **anglais** (`GUIDELINES.md` §8) ; seuls `specs/` et `AUDIT-*.md` restent en français.

## Périmètre

### `.github/` (racine) — cœur du changement

- Le mécanisme d'auto-approbation et d'auto-merge n'existe plus. Aucune exécution d'Actions ne crée de revue, n'approuve une PR ni ne demande un merge.
- Plus aucun échec d'étape n'est absorbé.
- La configuration dependabot décrit un périmètre **exact** et produit un volume maîtrisé.
- Une PR ne modifiant que des workflows déclenche au moins une suite de tests réelle.
- Les documents actifs ne prétendent plus qu'une PR dependabot est auto-vérifiée.

### `ui/`

- Un test de fumée exécuté par un workflow déclenché sur `paths: ui/**`, qui échoue si l'application ne se construit pas.

### `agent/`, `platform/`

- Épinglage des images d'outils portant un cliquet ; alignement de `shellcheck` entre les deux harnais. Aucun changement de code applicatif.

### Racine

- Un document, en anglais, énumérant les fichiers porteurs de versions épinglées et leur état de surveillance.

### `api/`

Aucun changement de code applicatif.

## Critères d'acceptation

1. `.github/workflows/dependabot-auto-approve.yml` n'existe plus : `test -e` retourne un code non nul. *(.github/)*
2. `grep -rniE 'createReview|gh pr merge|auto-?merge|auto-?approve|enablePullRequestAutoMerge' .github/` ne retourne aucune ligne, hors mention explicitement historique dans un document. *(.github/)*
3. `grep -rn 'continue-on-error' .github/workflows/` ne retourne aucune ligne. *(.github/)*
4. `grep -rn 'pull_request_target' .github/workflows/` ne retourne aucune ligne, ou chaque occurrence restante porte un commentaire justifiant le besoin de secrets et ne demande pas `contents: write`. *(.github/)*
5. Aucun workflow ne déclare `permissions: contents: write` au niveau du workflow. *(.github/)*
6. Pour chaque entrée de `.github/dependabot.yml`, le répertoire déclaré contient au moins un fichier de l'écosystème déclaré : pour `pip`, un `requirements*.txt` ; pour `docker`, un fichier dont le nom contient `Dockerfile` ; pour `github-actions`, un `.github/workflows/*.yml`. **L'entrée `docker` sur `/platform` telle qu'écrite aujourd'hui fait échouer ce contrôle.** *(.github/, platform/)*
7. `.github/dependabot.yml` surveille, en plus de l'existant : les treize `Dockerfile` de `platform/docker/*/`, `api/Dockerfile`, `ui/Dockerfile`, `platform/docker/mqtt-exporter/requirements.txt`. Vérifiable en comparant les entrées à la sortie de `find . -name 'Dockerfile*' -not -path './.git/*'`. *(.github/)*
8. Les mises à jour `github-actions` sont groupées de sorte que les niveaux `minor` et `patch` produisent une PR commune et que chaque niveau `major` produise une PR distincte ; les mises à jour `pip` sont groupées par composant, tout niveau confondu. Vérifiable par lecture des blocs `groups:`. *(.github/)*
9. Un document versionné du dépôt, **en anglais**, énumère les fichiers porteurs de versions épinglées et indique pour chacun s'il est surveillé par dependabot ou non, avec la raison. L'énumération couvre au minimum : `api/requirements.txt`, `ui/requirements.txt`, `platform/docker/mqtt-exporter/requirements.txt`, `api/Dockerfile`, `ui/Dockerfile`, `agent/Dockerfile.container`, les treize `Dockerfile` de `platform/docker/*/`, les quatre images `image:` de `platform/docker/docker-compose.yml`, les quatre `.pre-commit-config.yaml`, et les variables d'image des deux `run-tests.sh`. *(tous composants)*
10. Toute PR ne modifiant que des fichiers sous `.github/workflows/` déclenche au moins un workflow exécutant une suite de tests : au moins un des workflows `api-tests.yml`, `agent-tests.yml`, `platform-tests.yml` déclare un motif `paths:` couvrant `.github/workflows/**`, et non seulement son propre fichier. *(.github/)*
11. `grep -n 'auto-verified' .github/PULL_REQUEST_TEMPLATE.md` ne retourne aucune ligne, et le gabarit ne contient plus d'affirmation selon laquelle des items de sécurité seraient vérifiés automatiquement pour les PR dependabot. *(.github/)*
12. `ui/` porte un test de fumée qui construit l'application Flask et échoue si l'import ou la construction échoue ; il est exécuté par un workflow déclenché sur `paths: ui/**`, et la commande pour le lancer localement est documentée dans `ui/README.md`. Le test échoue si `ui/server.py` est rendu non importable — vérifié par mutation. *(ui/, .github/)*
13. `agent/scripts/run-tests.sh` et `platform/scripts/run-tests.sh` utilisent la **même** version épinglée de `shellcheck` ; `bats` et `ansible-lint` sont épinglés à une version explicite, jamais `:latest`. Vérifiable par `grep -rn '_IMAGE=' */scripts/run-tests.sh`. *(agent/, platform/)*
14. `upload-artifact` et `download-artifact` de `.github/workflows/build-fleet-agent.yml` sont à des versions majeures compatibles, ou accompagnés d'un commentaire indiquant la contrainte d'appariement. *(.github/)*
15. *(Retiré des critères d'acceptation par l'amendement — voir « Action post-merge » en fin de document.)* La configuration livrée doit permettre à dependabot de rouvrir les mises à jour concernées en lots groupés : vérifiable en confrontant les écosystèmes et répertoires des 13 PR ouvertes aux entrées de `.github/dependabot.yml`, chacune devant être couverte par une entrée et un groupe. *(.github/)*
16. Les suites de tests de chaque composant passent après le cycle : `api/` (`pytest` complet et `-m security`), `agent/` (`./scripts/run-tests.sh`), `platform/` (`./scripts/run-tests.sh`), `ui/` (le test de fumée). *(tous composants)*
17. Les règles propres d'`actionlint` passent sur `.github/workflows/` : `actionlint -shellcheck= -pyflakes=` sort en 0. Son intégration shellcheck optionnelle remonte trois constats (`build-fleet-agent.yml` SC2231, `promote.yml` SC2129, `security-regression-stack.yml` SC2034) **antérieurs au cycle** — le nombre et la nature de ces constats ne doivent pas augmenter, vérifiable en comparant à `git archive HEAD`. *(.github/)*
18. Aucun fichier créé ou modifié par ce cycle hors `specs/` et `AUDIT-*.md` ne contient de texte français. *(tous composants)*
19. Aucun run des workflows modifiés ne se conclut en `success` alors qu'une de ses étapes a échoué. *(.github/)*

20. Les dépendances de test de `ui/` vivent dans un fichier distinct de `ui/requirements.txt`, et `ui/Dockerfile` n'installe que le fichier d'exécution : l'image publiée ne contient pas `pytest`. Vérifiable par lecture du `Dockerfile` et par `grep -c pytest ui/requirements.txt` valant 0. Le nouveau fichier est couvert par une entrée dependabot, ce que le contrôle de couverture exige automatiquement. *(ui/, .github/)*
21. Le contrôle de couverture dependabot détecte un manifeste quelle que soit la casse de son nom, comme le fait dependabot lui-même (`/dockerfile/i`) : un fichier nommé `app.dockerfile` ou `DOCKERFILE` non couvert par une entrée fait échouer le contrôle. Vérifiable en créant un tel fichier dans une copie. *(platform/)*

## Hors-périmètre

- **Aucune modification de la protection de branche** : les six checks obligatoires, `enforce_admins`, `required_approving_review_count: 1` et `require_code_owner_reviews` restent tels quels. Ajouter une suite filtrée par `paths:` à la liste des checks obligatoires rouvrirait le piège documenté en `platform/scripts/apply-branch-protection.sh:71-77` — un check filtré ne rapporte jamais et bloque le merge indéfiniment.
- **Épinglage des actions par SHA** : durcissement légitime de la chaîne d'approvisionnement, mais qui change le mode de fonctionnement de dependabot pour tout le dépôt. Distinct de la remise à plat demandée, non traité.
- **Images du `docker-compose.yml`** : l'écosystème `docker-compose` de dependabot est en bêta. Les quatre images concernées sont documentées comme non surveillées (critère 9), pas mises sous surveillance.
- **Aucune refonte de la couverture de tests.** `VIB-14` reste `A_FAIRE`. Le cycle ne traite la question des tests que là où elle conditionne la validation d'une montée de version, et ne touche ni aux tests existants ni à leurs sauts conditionnels.
- **Aucun autre `VIB-xx` n'est adressé.** En particulier `VIB-17` : aucune montée de `sqlalchemy` ou `alembic` ne doit s'accompagner d'une régénération automatique de migration, ce qui supprimerait l'index d'unicité d'authentification des appareils.
- **Dépendance à ne pas casser** : le contrat d'identité d'appareil (`VIB-02`, `VIB-03`, `VIB-05`, tous `CORRIGE`) est porté par `api/app/contracts/device_identity.py`, `agent/usr/lib/fleet-agent/identity-lib.sh` et `platform/ansible/roles/fleet_agent/templates/device-identity.conf.j2`. Aucune montée de version ne doit produire de diff dans ces trois fichiers ni dans les tests comparant leurs quatre jeux de clés.
- **Signalé, non traité** : `.github/CODEOWNERS` porte des commentaires en français, en contradiction avec `GUIDELINES.md` §8. Et avec un unique `CODEOWNER` plus `enforce_admins: true`, une PR rédigée par ce mainteneur ne peut être approuvée par personne — problème réel, antérieur, sans effet sur les PR dependabot dont l'auteur est le bot.

## Risques

1. **Le vert disparaît là où il masquait du rouge.** Supprimer les deux `continue-on-error` et le workflow fait remonter des échecs jusqu'ici invisibles. C'est l'effet recherché ; il faut s'attendre à des runs rouges dès la première PR.
2. **Ajouter `.github/workflows/**` aux filtres `paths:` déclenche des suites qui n'ont jamais tourné sur ce type de PR**, dont `security-regression-stack.yml` (35 minutes) et les cliquets de `platform/scripts/run-tests.sh`. Ces cliquets s'appuient sur des images `:latest` pour `ansible-lint` : un rouge peut apparaître sans aucun changement du dépôt — c'est précisément ce que la décision 10 vise à supprimer.
3. **Appariement `upload-artifact` / `download-artifact`.** Le groupement des majeures en PR séparées (décision 6) ne garantit pas leur appariement. Le chemin concerné ne s'exécute **que sur un tag** : la casse ne se manifesterait qu'à la première release. D'où le critère 14.
4. **`ubuntu` 24.04 → 25.10 sur `agent/Dockerfile.container`** : passage d'une LTS à une version à support court, sur une image qu'aucune PR ne construit. Le saut peut casser silencieusement l'image `vps-device`, découvert seulement au `docker compose --profile agent up`.
5. **L'extension du périmètre ouvre des CVE aujourd'hui invisibles.** Les treize images de la plateforme sont anciennes. `filesystem-vuln-scan` scanne le système de fichiers, pas les images construites : une fois ces `FROM` surveillés, le volume de PR augmentera nettement d'un coup.
6. **Effet de bord de `pip-audit` en check obligatoire.** Il s'exécute sur les deux `requirements.txt` à chaque PR. Refuser une montée qui ferme un CVE rend rouge un check obligatoire sur **toutes** les PR du dépôt, y compris sans rapport.
7. **Correction qui rouvre un vecteur.** C'est le risque principal : supprimer l'auto-approbation sans retirer la ligne 8 du gabarit laisserait en place « auto-verified by CI, no manual action needed » alors que plus rien ne vérifie — un relecteur pourrait s'y fier pour ne pas relire. Couvert par le critère 11.
8. **Le test de fumée de `ui/` peut donner un faux sentiment de couverture.** Il valide que l'application se construit, rien de plus. La documentation doit dire ce qu'il couvre et ce qu'il ne couvre pas, sous peine de reproduire le motif que ce cycle corrige.

## Questions ouvertes

Aucune.

## Action post-merge (hors critères d'acceptation)

Une fois la présente PR mergée sur `main`, et **seulement après**, les 13 PR dependabot ouvertes
(#17 du 2026-09-20, #2 à #13 du 2026-09-13) sont fermées, chacune avec un motif écrit dans son fil.
L'ordre importe : tant que la nouvelle configuration n'est pas sur `main`, dependabot travaille avec
l'ancienne, et une PR fermée sans merge est lue comme un refus pour cette version — elle ne serait
pas rouverte.

Après fermeture, il faut **vérifier que dependabot rouvre effectivement** des PR groupées contre la
nouvelle configuration, et non que les treize mises à jour ont silencieusement disparu. Si l'une
d'elles ne revient pas, elle est reprise à la main.

Cette action est conduite par l'orchestrateur, pas par le Builder : fermer des pull requests est
visible publiquement et ne s'annule pas d'un clic.
