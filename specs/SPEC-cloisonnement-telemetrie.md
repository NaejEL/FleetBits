# Cloisonnement par site des requêtes de télémétrie (VIB-01)

Statut : APPROUVEE

> **Amendement du 2026-09-14, décidé par le Product Owner après la première passe de vérification.**
> Le Verifier a établi que le critère 7 était mesurablement faux et que son manquement avait une
> conséquence observable : neuf routeurs hébergent chacun leur propre prédicat de cloisonnement, si
> bien qu'un jeton d'opérateur sans `site_scope` reçoit 403 sur la télémétrie mais 200 avec des
> données couvrant tous les sites sur `/api/v1/devices`, `/api/v1/zones` et `/api/v1/sites`. Le
> périmètre est donc **élargi** à l'unification de ces neuf routeurs, et quatre critères sont
> ajoutés (21 à 24) à partir des constats de cette même passe. Le critère 19 est reformulé : il
> exigeait une commande qui n'existe pas dans ce monorepo.

## Contexte

### Le défaut

`api/app/routers/telemetry.py` expose quatre points d'entrée de **requête** destinés aux opérateurs humains, authentifiés par JWT via `get_current_user` :

| Route | Ligne | Amont |
|---|---|---|
| `GET /telemetry/metrics/query` | 271 | `{PROMETHEUS_URL}/api/v1/query` |
| `GET /telemetry/metrics/query_range` | 286 | `{PROMETHEUS_URL}/api/v1/query_range` |
| `GET /telemetry/logs/query` | 301 | `{LOKI_URL}/loki/api/v1/query` |
| `GET /telemetry/logs/query_range` | 316 | `{LOKI_URL}/loki/api/v1/query_range` |

Les quatre sont identiques : ils copient `dict(request.query_params)`, exigent la présence de `query`, passent cette expression **libre** (PromQL ou LogQL, fournie par le client) à `_enforce_site_scope` (lignes 230-268), puis transfèrent **tous** les paramètres reçus à l'amont.

`_enforce_site_scope` cloisonne par **réécriture textuelle**, au moyen de deux expressions régulières (lignes 225-227) :

```python
_SITE_SELECTOR_RE = re.compile(r'site\s*(=~?|!=|!~)\s*"([^"]*)"')
_SELECTOR_BLOCK_RE = re.compile(r'\{([^}]*)\}')
```

Ces expressions opèrent sur du texte brut, sans analyseur lexical du langage de requête. Elles ne distinguent pas un `{` ou un `"` significatif d'un `{` ou d'un `"` situé dans un commentaire PromQL (`#`) ou dans un littéral chaîne (argument de `label_replace`, filtre de ligne LogQL). Deux familles d'évasion en découlent, qui exploitent le même point : **il suffit qu'un bloc `{...}` inerte portant déjà `site="<mon-site>"` apparaisse quelque part dans le texte** pour que `_SELECTOR_BLOCK_RE.search(query)` soit vrai, que l'injection laisse ce bloc inchangé, et que la branche de repli ligne 268 — la seule qui contraint une expression sans sélecteur — ne s'exécute jamais. L'expression réellement évaluée par le moteur reste non contrainte et couvre toute la flotte.

La validation adversariale de l'audit a rejoué l'évasion par commentaire et en a trouvé une seconde, de forme différente, qui survivrait à une rustine anti-commentaire. **Le défaut n'est pas une expression régulière à corriger, c'est l'approche** : aucune réécriture textuelle ne peut cloisonner un langage de requête. C'est pourquoi la difficulté a été relevée de `M` à `L` par l'audit.

**Impact** : un opérateur restreint à un site lit les métriques et les journaux de tous les autres sites.

### Deux écarts annexes constatés dans le même code

- `_enforce_site_scope` fait dépendre le cloisonnement du seul `site_scope is None`, sans regarder `role`. Le module voisin `api/app/routers/observability.py` utilise, lui, `_is_site_scoped_user(user)` = `user.role != "admin" and bool(user.site_scope)` (lignes 30-31). Les deux modules répondent donc **différemment** pour un utilisateur `role != "admin"` sans `site_scope`, et pour un `admin` porteur d'un `site_scope`. `TokenPayload` (`api/app/services/token.py:30-33`) autorise les deux combinaisons.
- Les quatre routes retransmettent l'intégralité des paramètres entrants à l'amont sans liste d'autorisation, alors que le chemin d'ingestion filtre ses en-têtes (`_extract_forward_headers`, ligne 40).

### Le module de référence

`api/app/routers/observability.py` expose quatre points d'entrée **paramétrés** : `GET /query/service-health`, `GET /query/device-metrics/{device_id}`, `GET /query/recent-logs`, `GET /alerts`. Aucun n'accepte d'expression du client : chacun reçoit des paramètres typés et validés (`_LABEL_VALUE_RE = ^[a-zA-Z0-9_.:-]{1,128}$`, `pattern=` sur les paramètres FastAPI), résolus en base pour vérifier l'appartenance au périmètre (`_get_scoped_device`, `_get_scoped_zone`), puis construit l'expression côté serveur. Il normalise aussi toute panne amont en 502 (`_upstream_get`).

### Qui consomme les quatre routes aujourd'hui

Recherche exhaustive sur le monorepo du motif `telemetry/(metrics|logs)/query` : **les seuls appelants sont les tests** (`api/tests/test_security_telemetry.py`, lignes 718 à 767).

- `ui/` : aucun appel. `ui/api_client.py` ne consomme d'`api/` que `/api/v1/alerts`. Il contient en revanche `prom_query()` (ligne 527) et `prom_targets()` (ligne 542), qui interrogent **directement** `http://prometheus:9090` sans authentification ni cloisonnement ; `prom_query` n'a aucun appelant, `prom_targets` est appelé par `ui/blueprints/monitoring.py:31`.
- `platform/` : les `Caddyfile` ne réécrivent que les chemins d'**ingestion** ; aucune règle ne vise les chemins de requête.
- `agent/` : aucun appel — l'agent pousse, il n'interroge pas.

**Conséquence** : aucun consommateur applicatif ne dépend du contrat actuel de ces quatre routes. Combiné au fait que le projet n'a jamais été déployé, remplacer ce contrat est gratuit.

### Le contournement Grafana, qui borne ce que ce cycle peut prétendre

Grafana (`platform/docker/grafana/provisioning/datasources/datasources.yml`) pointe ses sources de données **directement** sur `http://prometheus:9090` et `http://loki:3100`, sans passer par `api/`. Les six tableaux de bord de `platform/docker/grafana/dashboards/` envoient donc leurs expressions au moteur hors de tout cloisonnement. Un opérateur cloisonné authentifié par le pont `grafana-verify` peut interroger toute la flotte depuis Grafana Explore.

**Corriger VIB-01 ne referme donc qu'une moitié du problème.** Refermer l'autre exige une décision sur le multi-tenant Loki (`platform/docker/loki/loki.yml:6` : `auth_enabled: false`) et sur la politique d'organisations Grafana, ainsi qu'un composant intermédiaire devant Prometheus, qui n'a aucun équivalent natif. C'est un chantier « plateforme » distinct.

### État des tests

`api/tests/test_security_telemetry.py::TestEndToEndTelemetryFlow::test_telemetry_queries_cannot_cross_site_boundaries` (lignes 702-775) **encode effectivement le comportement permissif**, comme l'affirme l'audit :
- lignes 752-762 : une expression libre `up{job="fleet-agent"}` doit être **acceptée** (200), et le texte transmis doit contenir `site="site-a"` et `job="fleet-agent"` ;
- lignes 765-775 : une expression libre `up{site="site-a",job="node"}` doit être acceptée, et `site="site-a"` n'apparaître qu'une fois dans le **texte transmis**.

Ces deux moitiés assertent sur la chaîne réécrite et ne peuvent pas survivre à l'abandon de la réécriture. Les quatre premiers blocs du même test (lignes 716-747) assertent sur le **refus**, qui reste souhaitable, mais dont le code de statut et le message sont susceptibles de changer.

### Règles applicables de `GUIDELINES.md`

- §1 : *Security first — fail closed, least privilege*.
- §3 : *fail-closed defaults*, *explicit authorization checks*, *regression tests for any security-sensitive behavior change*, et « If a security control cannot be validated, mark status as **open** — never claim complete ».
- §6 : « Never leave contradictory security statements in active docs ».
- §8 : *preserve existing public API unless change is intentional and documented* — le changement est ici intentionnel, il doit donc être documenté.
- §11 : libellés canoniques `site`, `zone`, `device_id`, `device_role`, `profile`, `environment`, `ring`, `service`.

### Décisions d'arbitrage retenues

1. **Architecture** : les quatre routes à expression libre sont **supprimées**. Aucun point d'entrée acceptant une expression PromQL ou LogQL du client ne subsiste. La délégation du cloisonnement au moteur de données — seule voie qui refermerait aussi le contournement Grafana — est **inscrite au `SECURITY_ROADMAP.md` comme chantier distinct**, pas traitée ici.
2. **Jeton sans `site_scope`** : **fail closed**, mais pour les rôles que le modèle décrit comme cloisonnables, et eux seuls.
   `api/app/models/user.py` déclare `VALID_ROLES = {admin, operator, technician, viewer, ci_bot}` et documente en toutes lettres que « `site_scope` restricts **operator-role** users to a single site ». Le prédicat suit cette distinction :
   - **Rôles cloisonnables** (`operator`, `technician`) : l'absence de `site_scope` est une anomalie — refus.
   - **Rôles fleet-wide par nature** (`admin`, `ci_bot`, `viewer`) : l'absence de `site_scope` est leur forme normale — pas de refus ; ils restent soumis à leurs contrôles propres (par exemple la restriction ring-0 du `ci_bot`).
   - **Dans tous les cas**, un jeton **porteur** d'un `site_scope` est confiné à ce site, quel que soit son rôle.

   *Amendement du 2026-09-14, second tour :* la formulation initiale disait « non-`admin` sans `site_scope` → refus ». Elle visait les opérateurs humains mais attrapait les rôles de service : un jeton `ci_bot`, émis par défaut sans portée (`api/app/schemas/user.py:69`), perdait la capacité de créer et déclencher des déploiements, rendant mortes les règles ring-0 de `deployments.py`. Un `viewer` fleet-wide perdait toute lecture d'inventaire.
3. **`ui/api_client.py:527 prom_query()`** : **supprimée**. Code mort qui contourne le cloisonnement qu'on répare.
4. **Écart Grafana** : nommé dans `SECURITY_ROADMAP.md` **et** en commentaire dans `datasources.yml`, au plus près de la configuration concernée.

## Périmètre

### `api/`

- Suppression des quatre routes de requête de télémétrie et de la fonction `_enforce_site_scope` avec ses deux expressions régulières.
- Unification du prédicat « cet utilisateur est-il cloisonné par site ? » **dans toute l'API**, sur la variante la plus stricte, avec refus fail-closed pour un non-`admin` sans `site_scope`. Périmètre élargi par l'amendement : outre `telemetry.py` et `observability.py`, les neuf copies locales de `audit.py`, `deployments.py`, `devices.py`, `hotfixes.py`, `operations.py`, `overrides.py`, `profiles.py`, `sites.py` et `zones.py` sont remplacées par un appel au prédicat unique. Ces routeurs portent des chemins de **mutation** : chaque changement d'autorisation doit être couvert par un test de régression.
- Réécriture des tests qui encodent le comportement permissif ; ajout de tests couvrant les deux familles d'évasion, afin qu'elles ne puissent être réintroduites.
- `api/README.md` décrit l'état réel des points d'entrée après changement.

### `ui/`

- Suppression de `prom_query()`.
- Vérification de non-régression : `ui/` n'appelle aucune des routes supprimées et continue de fonctionner à l'identique.

### `platform/`

- Commentaire dans `datasources.yml` nommant l'écart de cloisonnement de Grafana. Aucun changement de comportement.

### Racine

- `SECURITY_ROADMAP.md` : correction de l'affirmation périmée, inscription du chantier de délégation au moteur, et mention de l'écart Grafana.
- `AUDIT-vibecode.md` : statut de VIB-01.

### `agent/`

Non touché.

## Critères d'acceptation

1. Le symbole `_enforce_site_scope` n'existe plus dans `api/app/routers/telemetry.py`, et une recherche de ce motif sur l'ensemble du dépôt ne renvoie aucune occurrence hors `AUDIT-vibecode.md` et `specs/`. *(api/)*
2. `api/app/routers/telemetry.py` ne contient plus aucune expression régulière ni appel de substitution ou de recherche textuelle s'appliquant à une chaîne PromQL ou LogQL issue de la requête cliente : une recherche de `re.compile`, `re.sub`, `.sub(`, `.finditer(`, `.search(` dans ce fichier ne renvoie aucune occurrence dont l'argument dérive de `request.query_params`. *(api/)*
3. Aucun gestionnaire de route de `api/app/routers/telemetry.py` ne lit une clé `query` fournie par le client ni ne la transmet à un appel HTTP amont : une recherche de `params["query"]`, `"query" not in params` et `dict(request.query_params)` dans ce fichier ne renvoie aucune occurrence. *(api/)*
4. Les quatre chemins `/telemetry/metrics/query`, `/telemetry/metrics/query_range`, `/telemetry/logs/query`, `/telemetry/logs/query_range` ne sont plus déclarés : une requête authentifiée sur chacun d'eux renvoie 404 ou 405, vérifié par test. *(api/)*
5. Un test automatisé marqué `@pytest.mark.security` vérifie que, pour chacune des deux expressions d'évasion suivantes envoyée par un porteur de `scoped_token` (périmètre `site-a`), **aucune requête n'atteint l'amont avec une expression non contrainte** : (a) évasion par commentaire — un bloc `{site="site-a"}` placé après un `#`, le nom de métrique nu devant ; (b) évasion par littéral chaîne — un bloc `{site="site-a"}` placé à l'intérieur d'un argument chaîne de `label_replace`, le nom de métrique nu en premier argument. **Ce test doit échouer sur la version actuelle du code et passer sur la version corrigée** ; cette double vérification est exigée et doit être rapportée. *(api/)*
6. Le test `test_telemetry_queries_cannot_cross_site_boundaries` de `api/tests/test_security_telemetry.py` ne contient plus aucune assertion portant sur le contenu textuel d'une expression transmise à l'amont : les assertions `'site="site-a"' in forwarded_query`, `'job="fleet-agent"' in forwarded_query` et `forwarded_query.count('site="site-a"') == 1` ont disparu du fichier. *(api/)*
7. La décision « cet utilisateur est-il cloisonné par site ? » est produite par un **unique prédicat partagé**, dans toute l'API et non dans le seul module de télémétrie : une recherche de `role != "admin"` dans `api/app/routers/` ne renvoie **qu'une seule définition**, celle du module de portée. Les copies locales de `audit.py`, `deployments.py`, `devices.py`, `hotfixes.py`, `operations.py`, `overrides.py`, `profiles.py`, `sites.py` et `zones.py` ont disparu au profit de cet appel unique. *(api/)*
8. Un jeton d'opérateur de rôle non-`admin` **sans** `site_scope` n'obtient **aucune** donnée de télémétrie : tout point d'entrée d'observabilité interrogé avec un tel jeton renvoie une erreur d'autorisation, jamais des données couvrant plusieurs sites. Vérifié par test, sur au moins deux points d'entrée distincts d'`observability.py`. *(api/)*
9. Les tests existants de `api/tests/test_security_scope_boundaries.py` couvrant `observability.py` restent verts, ou leurs changements sont justifiés un par un dans le rapport comme conséquence directe de la décision 2 — jamais comme ajustement d'opportunité. *(api/)*
10. Une recherche des motifs `telemetry/metrics/query` et `telemetry/logs/query` dans `ui/` ne renvoie aucune occurrence. *(ui/)*
11. La fonction `prom_query` n'existe plus dans `ui/api_client.py`, et une recherche de ce motif dans `ui/` ne renvoie aucune occurrence. `prom_targets`, qui a un appelant réel, est conservée inchangée. *(ui/)*
12. `ui/` démarre sans erreur d'import après le changement : `python -c "import server"` depuis `ui/` s'exécute sans `ImportError`, et `python3 -c "import ast; ast.parse(open('ui/api_client.py').read())"` sans erreur. *(ui/)*
13. `api/README.md` contient une ligne pour chaque point d'entrée effectivement déclaré dans `app/routers/telemetry.py` après changement, et **aucune** ligne pour un point d'entrée supprimé : chaque décorateur `@router.get`/`@router.post` du fichier a une ligne correspondante, et réciproquement. *(api/, racine)*
14. `SECURITY_ROADMAP.md` ne porte plus d'affirmation contradictoire sur la validation des expressions de requête : la ligne S0.4 (`Input validation (PromQL/LogQL sanitized)`, aujourd'hui `✅ Complete`) décrit l'état réel post-correction et ne contredit plus la ligne 254 du même fichier (`Partial`). *(racine)*
15. `SECURITY_ROADMAP.md` contient une entrée **non résolue** nommant explicitement que Grafana interroge Prometheus et Loki en direct, sans appliquer le cloisonnement par site de l'API, et une entrée pour le chantier de délégation du cloisonnement au moteur de données. *(racine)*
16. `platform/docker/grafana/provisioning/datasources/datasources.yml` porte un commentaire nommant cet écart et renvoyant à l'entrée correspondante du `SECURITY_ROADMAP.md`. *(platform/)*
17. Dans `AUDIT-vibecode.md`, le statut de VIB-01 passe de `A_FAIRE` à `CORRIGE`, dans le tableau de synthèse **et** dans l'entrée détaillée, en nommant ce qui reste non traité (contournement Grafana). *(racine)*
18. `cd api && pytest -q` et `pytest -q -m security tests` terminent sans échec. Les nouveaux tests portent le marqueur `security`, de sorte que les workflows `api-tests.yml` et `security-regression-stack.yml` les exécutent sans modification de leur commande. *(api/, racine)*
19. Les contrôles de qualité passent, exécutés là où ils existent réellement : ce monorepo n'a **pas** de `.pre-commit-config.yaml` à la racine mais un par composant, de sorte que `pre-commit run --all-files` n'a rien à exécuter depuis la racine. Sont donc exigés : `ruff check --select S api/app` sans erreur, `bandit -r app -ll` sans finding Medium ou High, `gitleaks detect --no-git` sans fuite sur l'arbre entier, et `actionlint` sur les workflows de la racine sans finding **introduit** par ce cycle. Pour `ui/`, le nombre de findings `ruff --select S` doit être inférieur ou égal à celui de `HEAD`. *(racine, api/, ui/)*
20. Aucune migration Alembic n'apparaît dans le diff : aucun modèle ni schéma persisté n'est concerné. Une migration dans le diff est le signal d'une erreur. *(api/)*

21. `user.site_scope` est validé avant d'être interpolé dans une expression construite côté serveur, par le même contrôle que celui appliqué à une valeur de libellé fournie par le client : un `site_scope` valant `site-a",job=~".*` ne produit pas une expression élargie mais une erreur. Vérifié par un test qui échoue si la validation est retirée. *(api/)*
22. Le passage de « permissif » à « cloisonné » pour un jeton `admin` **porteur** d'un `site_scope` — la moitié de la décision 2 que les tests livrés ne couvraient pas — est protégé par un test de régression livré dans le dépôt, conformément à `GUIDELINES.md` §3. Le test couvre au moins un point d'entrée où l'expression construite porte la contrainte de site, et un point d'entrée où une ressource d'un autre site renvoie 404 sans appel amont. *(api/)*
23. Dans `list_alerts`, le rejet inter-site pour un appelant cloisonné (`site != scope`) s'exécute **avant** tout appel amont : une requête `?site=<autre site>` renvoie son erreur sans qu'aucune requête n'ait été émise vers Alertmanager. Vérifié par un test observant les appels amont. *(api/)*
24. Un jeton d'opérateur non-`admin` **sans** `site_scope` reçoit la même réponse fail-closed sur les routes d'inventaire que sur la télémétrie : `GET /api/v1/devices`, `GET /api/v1/zones` et `GET /api/v1/sites` ne renvoient jamais de données couvrant plus d'un site à un tel jeton. Vérifié par test sur les trois routes. *(api/)*

25. Un jeton de rôle `ci_bot` sans `site_scope` — la forme que `api/app/schemas/user.py` émet par défaut — conserve exactement les capacités qu'il avait avant ce cycle : `POST /api/v1/deployments` et `POST /api/v1/deployments/{id}/trigger` aboutissent, et restent soumis à la restriction ring-0 de `deployments.py`, dont les branches ne sont pas du code mort. Un jeton `viewer` sans `site_scope` conserve ses lectures d'inventaire. Vérifié par test sur les deux rôles. *(api/)*
26. Les transitions d'autorisation introduites par l'unification sont couvertes par des tests de régression sur les **chemins de mutation**, et pas seulement en lecture : au minimum, pour un `admin` porteur d'un `site_scope`, la création sur un site autre que le sien et la mutation d'un objet de flotte sans `site_id`. *(api/)*

## Hors-périmètre

- **L'accès direct de Grafana aux sources de données.** Non corrigé ici : demande une décision sur le multi-tenant Loki (`auth_enabled: false`) et la politique d'organisations Grafana, plus un composant intermédiaire devant Prometheus. Documenté comme risque ouvert (critères 15 et 16) plutôt que traité.
- **La délégation du cloisonnement au moteur de données.** Inscrite au `SECURITY_ROADMAP.md` comme chantier distinct (décision 1), pas réalisée.
- **`prom_targets()`** (`ui/api_client.py:542`, appelé par `ui/blueprints/monitoring.py:31`) : accès direct non authentifié à Prometheus, mais il retourne l'état des cibles de collecte de la plateforme, pas des séries d'appareils. Conservé inchangé.
- **Le chemin d'ingestion** (`/telemetry/metrics/write`, `/telemetry/logs/push`, `app/services/telemetry_rewrite.py`, réécritures Caddy). **Dépendance à ne pas casser** : les tests d'ingestion et de canonicalisation de libellés de `api/tests/test_security_telemetry.py` (lignes 146-700) doivent rester verts à l'identique, ainsi que le scénario de pile complet de `security-regression-stack.yml`.
- **Création de routes paramétrées de remplacement.** L'option a été écartée : aucun consommateur n'exprime le besoin, et `observability.py` couvre les besoins identifiés. Si un besoin d'interrogation apparaît, il fera l'objet d'un cycle propre.
- **VIB-12** (capture d'exception large, retour vide) : les routes supprimées n'avaient aucun traitement d'erreur amont ; le point disparaît avec elles pour ce module, mais le motif reste ouvert ailleurs.
- **VIB-04, VIB-06, VIB-08, VIB-13** : findings de sécurité voisins, non traités.
- **VIB-14** : l'absence totale de harnais de test dans `ui/` reste un manque documenté par ce finding. Ce cycle ne crée pas de harnais `ui/`, la décision 1 n'en faisant pas un consommateur de nouveaux points d'entrée.
- **Compatibilité ascendante** : sans objet. Aucun appareil enrôlé, aucune base vivante, aucun consommateur externe. Les routes sont supprimées sèchement, sans dépréciation.

## Risques

- **Faux sentiment de clôture.** C'est le risque principal. Corriger VIB-01 sans mentionner l'accès Grafana direct reproduirait exactement le motif que l'audit dénonce en tête de rapport : « les contrôles les plus mis en avant sont ceux qui ne fonctionnent pas, déclarés clos dans le document de planification ». D'où les critères 14, 15, 16 et 17 : le chemin corrigé et le chemin non corrigé doivent être déclarés **séparément**.
- **Perte de capacité d'interrogation ad hoc via l'API.** Aucun consommateur ne l'utilise aujourd'hui, mais la capacité disparaît. Atténuation constatée : Grafana reste disponible — ce qui déplace le problème vers le chantier hors-périmètre sans le résoudre, et c'est précisément pourquoi ce chantier est inscrit.
- **Régression sur la suite `security`.** `test_telemetry_queries_cannot_cross_site_boundaries` est un test unique de 74 lignes couvrant six scénarios ; le découper mal ferait disparaître silencieusement la couverture du refus inter-site. Le critère 5 impose que les nouveaux tests **échouent sur le code actuel**, ce qui garantit qu'ils testent quelque chose.
- **Fail-open à l'unification du prédicat (critère 7).** Un `admin` porteur d'un `site_scope` est aujourd'hui cloisonné par `telemetry.py` et non cloisonné par `observability.py`. Unifier sur la variante permissive élargirait l'accès. La décision 2 impose la variante stricte ; le critère 9 exige que tout test d'`observability.py` qui bascule soit justifié un par un.
- **Aucun risque de migration.** Aucun modèle SQLAlchemy, aucun schéma persisté concerné. À rapprocher de **VIB-17** : une autogénération Alembic supprimerait l'index d'unicité servant à authentifier les appareils — ne pas en exécuter dans ce cycle (critère 20).

## Questions ouvertes

Aucune.
