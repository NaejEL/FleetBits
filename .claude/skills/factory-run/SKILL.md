---
name: factory-run
description: Lance un cycle de l'usine logicielle (Planner → gate humaine sur la spec → Builder → Verifier avec boucle de correction) sur un besoin ou une spec approuvée.
disable-model-invocation: true
argument-hint: "<besoin | chemin d'une spec approuvée>"
---

Déroule un cycle complet de l'usine logicielle FleetBits sur `$ARGUMENTS`. Suis les étapes dans l'ordre, sans en sauter aucune.

## Contexte permanent du dépôt

`/home/naej/repos/FleetBits` **n'est pas un dépôt git** : c'est une racine de travail contenant quatre dépôts git indépendants — `FleetBits-api` (Python/FastAPI, Alembic, pytest), `FleetBits-ui` (Python/Flask), `FleetBits-agent` (shell, systemd, Alloy/Vector), `FleetBits-platform` (docker-compose, Ansible, scripts) — plus les documents transverses `README.md`, `GUIDELINES.md`, `FEATURE_ROADMAP.md`, `SECURITY_ROADMAP.md`, `AUDIT-vibecode.md`.

Toute commande `git` s'exécute avec `git -C /home/naej/repos/FleetBits/<dépôt>`. Un cycle peut légitimement toucher plusieurs dépôts à la fois — c'est le cas courant pour les contrats entre l'API et l'agent. Les specs et les journaux vivent à la racine (`specs/`, `factory-logs/`), hors de tout dépôt git.

## 1. Entrée

Si `$ARGUMENTS` est le chemin d'un fichier existant sous `specs/` dont la ligne de statut en tête vaut exactement `Statut : APPROUVEE`, **passer directement à l'étape 3** en prenant ce fichier comme spec approuvée.

Sinon, traiter `$ARGUMENTS` comme un **besoin** exprimé par l'utilisateur, et continuer à l'étape 2.

## 2. Phase Plan — gate humaine obligatoire

1. Lancer le sous-agent `factory-planner` (outil `Agent`, `subagent_type: "factory-planner"`) avec le besoin `$ARGUMENTS` en entrée. Si le besoin cite un finding de `AUDIT-vibecode.md` ou un document transverse, le lui signaler explicitement.
2. À son retour, lire la section *Questions ouvertes* de son brouillon. Si elle contient au moins une question, les poser à l'utilisateur avec `AskUserQuestion`, en regroupant autant de questions que possible dans un même appel et en proposant pour chacune les options identifiées par le Planner.
3. Intégrer les réponses au brouillon : chaque réponse fait disparaître la question ouverte correspondante et devient, selon le cas, un critère d'acceptation, une ligne de *Hors-périmètre* ou une contrainte de *Contexte*. La section *Questions ouvertes* de la spec écrite doit se réduire à « Aucune ».
4. Écrire `specs/SPEC-<slug-du-besoin>.md` — slug court, en minuscules, mots séparés par des tirets, dérivé du besoin (ex. `specs/SPEC-contrat-identite-appareil.md`). Le fichier commence par le titre, puis, en deuxième ligne non vide, exactement :

   ```
   Statut : PROPOSEE
   ```

   suivent les sections *Contexte*, *Périmètre*, *Critères d'acceptation*, *Hors-périmètre*, *Risques*, *Questions ouvertes*.
5. Présenter la spec à l'utilisateur et **demander son approbation explicite**. En cas d'approbation, remplacer la ligne de statut par `Statut : APPROUVEE`. En cas de réserve, itérer sur la spec (corriger, re-présenter) et ne passer au statut approuvé qu'après accord franc.
6. **Si aucune interaction n'est possible (exécution headless, `claude -p`), s'arrêter immédiatement en erreur explicite** : « Un cycle CI exige le chemin d'une spec déjà approuvée sous `specs/` portant `Statut : APPROUVEE`. Aucune spec ne sera rédigée sans gate humaine. » Ne rien écrire, ne rien construire.

**Ne jamais construire sans spec approuvée.** L'utilisateur est le Product Owner : aucune exigence n'est décidée à sa place.

## 3. Phase Build

Lancer le sous-agent `factory-builder` (outil `Agent`, `subagent_type: "factory-builder"`, **contexte frais**) en lui passant :

- le chemin absolu de la spec approuvée ;
- la liste des dépôts touchés, telle que la spec les nomme ;
- la consigne d'exécuter build et tests de chaque dépôt touché et de ne rendre la main que s'ils passent.

## 4. Phase Verify — boucle de correction, 3 itérations maximum

Tenir un compteur d'itérations, initialisé à 1.

1. Lancer un sous-agent `factory-verifier` (`subagent_type: "factory-verifier"`, **contexte vierge, indépendant de celui du Builder** — un nouvel agent à chaque itération, jamais une reprise du précédent) avec le chemin absolu de la spec. Récupérer le bloc JSON en fin de sa réponse.
2. Si `verdict` vaut `APPROVED` **et** `tests_passed` vaut `true` : sortir de la boucle, le cycle est un succès. Aller à l'étape 5.
3. Sinon, relancer `factory-builder` (contexte frais) avec le chemin de la spec **et la liste complète des `issues` du Verifier** — `file`, `severity`, `description` de chacune, sans en omettre ni en résumer une — et la consigne de corriger chaque issue sans régresser sur les critères déjà satisfaits. Incrémenter le compteur, puis reprendre à l'étape 1 avec un **nouveau** Verifier.
4. Après la **3e** itération non approuvée, **échouer explicitement** : publier les issues restantes, le nombre d'itérations consommées et l'état de l'arbre de travail de chaque dépôt. **Ne jamais approuver par épuisement** ni déclarer le cycle réussi parce que les issues restantes semblent mineures.
5. **Un Verifier muet n'est pas un Verifier satisfait.** Si le Builder ou le Verifier meurt (erreur d'API, connexion coupée, agent interrompu) ou rend une sortie inexploitable au lieu de son bloc JSON, le relancer **une fois à l'identique**. Si le second essai échoue lui aussi, **échouer explicitement** en le disant : « Le vérificateur n'a rendu aucun verdict exploitable après deux tentatives ; le code produit n'est pas vérifié. » Ne jamais traiter l'absence de verdict comme une approbation, ne jamais consommer une itération du compteur au profit d'un agent mort, ne jamais passer à la suite sur un verdict absent. Un cycle qui livre du code non vérifié parce que son vérificateur est tombé est pire qu'un cycle qui échoue.

## 5. Rapport final

Produire un rapport structuré contenant :

- **Fichiers modifiés**, dépôt par dépôt, obtenus par :

  ```bash
  for r in FleetBits-api FleetBits-ui FleetBits-agent FleetBits-platform; do
    echo "===== $r"; git -C "/home/naej/repos/FleetBits/$r" status --short
  done
  ```

- **Résultat des tests** : pour chaque dépôt touché, la commande exécutée et son exit code (`FleetBits-api` : `./.venv/bin/python -m pytest` ; `FleetBits-ui` : idem si un `tests/` existe ; `FleetBits-agent` : `shellcheck` + `bats` ; `FleetBits-platform` : `docker compose config -q` + `ansible-playbook --syntax-check` + `ansible-lint`).
- **Verdict** final du Verifier et nombre d'itérations consommées.
- **Prochaine action suggérée** : revue du diff par l'utilisateur, dépôt par dépôt (`git -C /home/naej/repos/FleetBits/<dépôt> diff`), puis commit et branche à sa main. **Ne jamais commiter à sa place** — les quatre dépôts sont indépendants et le découpage des commits lui appartient.
