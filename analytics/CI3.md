# CI3 — Почему не выходят релизы `Reider85/OryaAgent`

> Источник: `https://github.com/Reider85/OryaAgent` (ветка `main`, инспекция от 2026-11-17).
> Это продолжение `analytics/CI2.md`. Здесь разобраны **только** баги, которые блокируют
> выпуск тегов и релизов при пуше в `main` (или при теге `v*.*.*`).
> Каждый баг снабжён самодостаточным промптом — можно скопировать и применить.

---

## 0. TL;DR — корневая причина

Релизы перестали выходить **с 2026-11-16** после коммита
`eded1e4 — fix(release): parse version via Python tomllib, not grep (B-14)`.
Этот коммит был задуман как замена `grep` на `make version`, но патч случайно
сделал ещё одно изменение: убрал отступ у строки `- name: Read version from pyproject.toml`
в `.github/workflows/release.yml` (стало 0 пробелов вместо 6). В результате весь файл
`release.yml` перестал парситься как YAML — GitHub Actions даже не запускает jobs,
сразу помечает workflow как `failed`.

**Подтверждение из GitHub Actions (последние запуски):**

| Workflow             | Last run  | Result   | Branch / Tag          | Commit   |
|----------------------|-----------|----------|-----------------------|----------|
| `.github/workflows/release.yml` | #62 | **failed**  | main                  | 66a6f18  |
| `.github/workflows/release.yml` | #61 | **failed**  | main                  | 6608b7e  |
| `.github/workflows/release.yml` | #60 | **failed**  | dependabot/langfuse-worker-4 | - |
| `.github/workflows/release.yml` | #59 | **failed**  | dependabot/langfuse-4 | - |
| `.github/workflows/nightly.yml` | #31 | **failed**  | main                  | 66a6f18  |
| `.github/workflows/nightly.yml` | #30 | **failed**  | main                  | 6608b7e  |
| `CI`                          | #64 | **failed**  | main                  | 66a6f18  |
| `CodeQL`                       | #60 | success    | main                  | 66a6f18  |
| `Release Drafter`              | #63 | success    | main                  | 66a6f18  |

**Последний созданный пререлиз:** `v7.0.0-dev.23+6b47fc1` от 2026-11-14 22:22 UTC
(за 2 дня до поломки). После этой даты ни одного нового тега/релиза не появилось,
хотя в `main` было слито 3 PR (`#4`, `#10`, `#11`).

**Воспроизведение локально:**

```bash
git clone https://github.com/Reider85/OryaAgent
cd OryaAgent
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"
# → yaml.parser.ParserError: while parsing a block mapping
#   in ".github/workflows/release.yml", line 1, column 1
#   expected <block end>, but found '-'
#   in ".github/workflows/release.yml", line 33, column 1
```

Строка 33 — это `- name: Read version from pyproject.toml`, которая стоит на
top-level (column 1), тогда как должна быть сдвинута на 6 пробелов под родительский
ключ `steps:`. Без починки этого **единственного** бага релизы не выйдут, какие бы
другие правки ни применялись.

---

## 1. Сводка по корректности

| ID  | Серьёзность | Файл / строка                          | Суть                                                                                                                                                                                                          |
|-----|-------------|----------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **R-01** | 🔴 CRITICAL  | `.github/workflows/release.yml:33`     | YAML не парсится: шаг `- name: Read version from pyproject.toml` стоит на column 1, а должен быть под `steps:` (column 7). Весь `release.yml` disabled — нет ни пререлиза, ни релиза по тегу, ни Docker push. |
| **N-01** | 🔴 CRITICAL  | `.github/workflows/nightly.yml:15`     | Ключ `steps:` стоит на column 1 вместо `nightly-prerelease.steps`. Парсер YAML относит шаги к top-level, а job `nightly-prerelease` остаётся БЕЗ шагов. Ночной релиз не создаётся.                              |
| **R-02** | 🟠 HIGH      | `.github/workflows/release.yml:36`     | Шаг `make version` запускается в `prerelease-on-push` без `setup-uv`. На свежем `ubuntu-latest` нет `uv` → `make version` упадёт с `uv: command not found` даже после починки R-01.                            |
| **N-02** | 🟠 HIGH      | `.github/workflows/nightly.yml:23`     | То же, что R-02, для nightly. `make version` требует `uv`, которого нет на runner без `astral-sh/setup-uv`.                                                                                                     |
| **R-03** | 🟠 HIGH      | `.github/workflows/release.yml:58`     | `gh release list` в шаге `dedup` вызывается без `env: GH_TOKEN`. `gh` CLI в actions не подхватывает `secrets.GITHUB_TOKEN` автоматически — шаг может упасть на auth даже при `permissions: contents: write`.   |
| **R-04** | 🟠 HIGH      | `.github/workflows/release.yml:192`    | В `prerelease-docker` блок `docker/metadata-action` `with:` содержит `labels: ${{ steps.meta.outputs.labels }}` — это **самоссылка** (action не имеет такого input и не отдаёт `steps.meta.outputs.labels`).    |
| **R-05** | 🟠 HIGH      | `.github/workflows/release.yml:200-203`| В `prerelease-docker` блок `docker/build-push-action` `with:` декларирует `labels:` **дважды**. YAML допускает дублирующие ключи, второй выигрывает — `metadata-action` labels молча теряются.                 |
| **R-06** | 🟠 HIGH      | `.github/workflows/release.yml` (root) | `generate_release_notes: true` требует `permissions: pull-requests: read`. Сейчас granted только `contents: write`. Auto-notes не будут включать PR-ссылки, иногда фолбэктят на ошибку.                          |
| **R-07** | 🟡 MEDIUM    | `.github/workflows/release.yml:15-18` | `workflow_dispatch.inputs.prerelease` объявлен, но **нигде** не используется. Пользователь думает, что может отключить пререлиз через manual run, но флаг игнорируется.                                          |
| **R-08** | 🟡 MEDIUM    | `.github/workflows/release.yml:111-113`| В `release-on-tag` body остался literal HTML-комментарий `<!-- Breaking changes or migration notes go here -->`. Он попадает в GitHub Release body как есть.                                                    |
| **R-09** | 🟡 MEDIUM    | `.github/workflows/release.yml`       | `on.push` одновременно фильтрует `branches: [main]` и `tags: ["v*.*.*"]`. Это означает, что push тега `v1.2.3` (даже если он указывает на коммит, где тронут только `.github/**`) всё равно запустит `release-on-tag`. `paths-ignore` не применяется к tag-push. |
| **R-10** | 🟡 MEDIUM    | `.github/workflows/release.yml:125, 165`| `needs: []` (пустой массив) у jobs `docker` и `prerelease-docker` — синтаксически ок, но избыточно. Без `needs` job и так параллельна.                                                                            |
| **R-11** | 🟢 LOW       | `.github/workflows/release.yml` (jobs)| Ни один job не имеет `timeout-minutes` (см. CI2 B-21 — обещано, не применено). Зависший `release-on-tag` будет крутиться 6 ч.                                                                                   |
| **R-12** | 🟢 LOW       | `.github/workflows/release.yml:13`     | `tags: ["v*.*.*"]` не совпадает с собственными пререлиз-тегами вида `v7.0.0-dev.23+6b47fc1`. Если кто-то запушит такой тег вручную, `release-on-tag` не запустится (это желаемое поведение, но стоит явно это задокументировать). |
| **R-13** | 🟢 LOW       | `.github/workflows/release.yml:33-41`  | Версия тега `v${VERSION}-dev.${GITHUB_RUN_NUMBER}+${SHORT_SHA}` использует `+` (build metadata по semver). `+` в Git tag name валиден, но GitHub API местами его не любит (например, в URL `/releases/tag/...`).   |

---

## 2. Промпты на исправление (готовы к копированию)

> Каждый промпт самодостаточен: исполнитель применяет правки в репо `OryaAgent`
> и присылает отдельный PR с названием, указанным в начале блока.
> Стиль: 2-space YAML-отступ, double-quote в `ruff format`.

---

### 🔴 R-01 — Починить YAML-отступ в `release.yml` (root cause)

**PR title:** `fix(release): restore step indentation broken in eded1e4`

```
В файле .github/workflows/release.yml на строке 33 сломан YAML-отступ. Шаг
"- name: Read version from pyproject.toml" стоит на column 1 (top-level), тогда
как должен быть на column 7 — внутри списка steps: job prerelease-on-push.

Это произошло в коммите eded1e4 "fix(release): parse version via Python
tomllib, not grep (B-14)" (2026-11-16): помимо замены grep на make version,
diff случайно убрал 6 пробелов перед "- name:". В результате весь файл
release.yml перестал парситься — GitHub Actions помечает workflow как failed
ещё до запуска любого job. Релизы не выходят с 2026-11-16.

Что сделать:

1. В .github/workflows/release.yml привести строку 33 к виду
       "      - name: Read version from pyproject.toml"
   (ровно 6 пробелов перед дефисом — как у соседних шагов "Compute compare URL"
   на строке 43 и "Skip if release for this SHA exists" на строке 54).

2. Проверить локально:
       python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('YAML OK')"
   Должно вывести "YAML OK". Если всё ещё падает — привести к виду из
   https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#jobsjob_idsteps

3. Проверить структуру: top-level keys должны быть ['name', 'on', 'permissions',
   'jobs']; job 'prerelease-on-push' должен иметь keys ['name', 'if', 'runs-on',
   'steps']; steps[1] должен быть {'name': 'Read version from pyproject.toml',
   'id': 'ver', 'run': '...'}.

4. Не трогать ничего больше. В частности, не "выравнивать" другие шаги —
   они уже корректны.

5. После мерджа убедиться, что следующий push в main действительно создаёт
   пререлиз (см. раздел 4 — чек-лист).

Контрольная проверка (должно сработать после фикса):
    python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/release.yml')); \
      assert 'jobs' in d; \
      assert 'steps' in d['jobs']['prerelease-on-push']; \
      assert d['jobs']['prerelease-on-push']['steps'][1]['name'] == 'Read version from pyproject.toml'; \
      print('OK')"
```

---

### 🔴 N-01 — Починить структуру `steps:` в `nightly.yml`

**PR title:** `fix(nightly): indent steps under nightly-prerelease job`

```
В файле .github/workflows/nightly.yml на строке 15 ключ "steps:" стоит на
column 1 (top-level), а должен быть на column 4 — внутри job nightly-prerelease.

Сейчас парсер YAML относит массив steps к top-level ключу "steps:" (который
в GitHub Actions workflow не валиден), а job nightly-prerelease остаётся
БЕЗ шагов (только 'if' и 'runs-on'). Workflow парсится, но при запуске job
ничего не делает — nightly-релиз не создаётся. Это подтверждается провалом
запусков #28, #29, #30, #31 (все failed с 2026-11-15).

Что сделать:

1. Привести строки 15-44 к виду (4-space отступ для "steps:" и 6-space
   для "- uses:" / "- name:" внутри списка):

       jobs:
         nightly-prerelease:
           if: github.repository == 'Reider85/OryaAgent'
           runs-on: ubuntu-latest
           steps:
             - uses: actions/checkout@v4
               with:
                 fetch-depth: 0

             - name: Resolve tag
               id: ver
               run: |
                 VERSION=$(make version)
                 ...
             - name: Create/update nightly release
               uses: pyTooling/Actions/releaser@5c6a1aec0bb5a0243ad0c6f98a8e1258c019e679
               with:
                 ...

2. Проверить локально:
       python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/nightly.yml')); \
         assert 'steps' in d['jobs']['nightly-prerelease']; \
         assert len(d['jobs']['nightly-prerelease']['steps']) == 3; \
         print('OK')"

3. Дополнительно: top-level keys после правки должны быть ['name', True,
   'permissions', 'jobs'] (ключ "on:" интерпретируется как boolean True —
   это известный YAML 1.1 quirk, GitHub Actions с этим справляется). Top-level
   ключа "steps:" быть НЕ должно.

4. После мерджа вручную запустить nightly через Actions UI (workflow_dispatch)
   и убедиться, что создаётся тег nightly-YYYYMMDD-<short_sha>.
```

---

### 🟠 R-02 — Добавить `setup-uv` в `prerelease-on-push`

**PR title:** `fix(release): install uv before make version in prerelease-on-push`

```
В .github/workflows/release.yml job prerelease-on-push (строки 24-81) вызывает
"make version" на шаге "Read version from pyproject.toml" (строка 36).
Makefile-таргет version:
    version:
        @uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"

То есть "make version" внутренне зовёт "uv run python ...". Но в job
prerelease-on-push НЕТ шага "astral-sh/setup-uv@v7" — а на свежем ubuntu-latest
бинарник uv отсутствует. Шаг упадёт с:
    /usr/bin/bash: line 1: uv: command not found
    make: *** [Makefile:56: version] Error 127

(Заметка: R-01 маскирует эту ошибку, потому что workflow не парсится и шаг
вообще не запускается. После применения R-01 этот баг станет виден.)

Что сделать:

1. После шага "- uses: actions/checkout@v4 ... fetch-depth: 0" (строка 29-31)
   добавить шаг установки uv:
       - uses: astral-sh/setup-uv@v7
         with:
           enable-cache: true
           cache-dependency-glob: "uv.lock"

2. Использовать ту же версию action@v7, что и в остальных jobs release.yml
   (release-on-tag:93, docker — нет, prerelease-docker — нет). Не добавлять
   --frozen, потому что uv sync здесь не нужен — нужен только uv run для
   одной команды в Makefile.

3. После мерджа убедиться, что prerelease-on-push успешно доходит до шага
   "Create prerelease" и создаёт тег вида v7.0.0-dev.N+<short_sha>.

4. Альтернатива (если не хочется тащить uv в пререлизный job): заменить
   "VERSION=$(make version)" на inline-Python без uv:
       VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
   Python 3.12+ на ubuntu-latest есть по умолчанию. Это убирает зависимость
   от uv, но дублирует логику Makefile. Рекомендуется первый вариант
   (setup-uv), чтобы источник правды остался один (Makefile).

Контрольная проверка после фикса R-01 + R-02:
    git push origin main  # запушить пустой коммит или README-правку
    # Открыть Actions → "Release" → последний run
    # Шаг "Read version from pyproject.toml" должен пройти успешно
    # Шаг "Create prerelease" должен создать тег v7.0.0-dev.<N>+<sha>
```

---

### 🟠 N-02 — Добавить `setup-uv` в `nightly.yml`

**PR title:** `fix(nightly): install uv before make version`

```
В .github/workflows/nightly.yml job nightly-prerelease вызывает "make version"
на шаге "Resolve tag" (строка 23). Как и в R-02, Makefile дёргает
"uv run python", но шага astral-sh/setup-uv НЕТ. После применения N-01 шаг
начнёт выполняться и сразу упадёт на "uv: command not found".

Что сделать:

1. Сразу после шага "actions/checkout@v4" (строка 16-18) добавить:
       - uses: astral-sh/setup-uv@v7
         with:
           enable-cache: true
           cache-dependency-glob: "uv.lock"

2. Использовать ту же версию action@v7, что и в release.yml (R-02).

3. После мерджа вручную запустить nightly через workflow_dispatch и убедиться,
   что шаг "Resolve tag" проходит, а "Create/update nightly release" создаёт
   тег nightly-YYYYMMDD-<short_sha>.

Контрольная проверка:
    # В Actions UI: Nightly → Run workflow → Run
    # Дождаться зелёного статуса
    # На странице /releases должна появиться новая "Nightly ..." пререлиз-запись
```

---

### 🟠 R-03 — Передать `GH_TOKEN` в шаг `dedup`

**PR title:** `fix(release): pass GH_TOKEN to dedup step`

```
В .github/workflows/release.yml шаг "Skip if release for this SHA exists"
(строки 54-64) вызывает:
    gh release list --repo "${{ github.repository }}" --json tagName ...

Команда "gh release list" требует авторизации. В GitHub Actions secret
secrets.GITHUB_TOKEN автоматически инжектится в env, но gh CLI его НЕ
подхватывает автоматически — нужно явно прокинуть через env: GH_TOKEN
(или GITHUB_TOKEN). Без этого шаг упадёт с:
    GH_TOKEN' variable not set; log in with "gh auth login"

Что сделать:

1. Добавить к шагу "Skip if release for this SHA exists" блок env:
       - name: Skip if release for this SHA exists
         id: dedup
         env:
           GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
         run: |
           SHORT_SHA=$(git rev-parse --short HEAD)
           SHA_TAG=$(gh release list --repo "${{ github.repository }}" --json tagName \
                     --jq ".[] | select(.tagName|endswith(\"+${SHORT_SHA}\")) | .tagName" | head -1)
           ...

2. Убедиться, что permissions: contents: write уже есть (он есть, строка 21).
   Для "gh release list" достаточно contents: read, но write не вредит —
   он нужен следующему шагу "Create prerelease".

3. После мерджа проверить, что dedup-step проходит (даже если реестр пустой,
   шаг должен выдать exists=false и пропустить к "Create prerelease").

Контрольная проверка:
    # В логе Release workflow шаг "Skip if release for this SHA exists"
    # должен вывести:
    #   exists=false
    # без ошибок про "GH_TOKEN variable not set".
```

---

### 🟠 R-04 + R-05 — Убрать дубль и самоссылку `labels:` в `prerelease-docker`

**PR title:** `fix(release): correct labels in prerelease-docker metadata + build-push`

```
В .github/workflows/release.yml job prerelease-docker (строки 164-203) содержит
две связанные ошибки в блоке labels:.

Ошибка 1 (строка 192): в шаге "Extract metadata" (docker/metadata-action@v5)
блок with: содержит:
    labels: ${{ steps.meta.outputs.labels }}

Это самоссылка: docker/metadata-action не имеет input "labels", который бы
принимал ${{ steps.meta.outputs.labels }} (он сам это и отдаёт). Либо убери
эту строку совсем (тогда metadata-action сгенерит OCI labels автоматически),
либо замени на явный список:
    labels: |
      org.opencontainers.image.title=OryaAgent-Prerelease
      org.opencontainers.image.description=Development build from main branch
      org.opencontainers.image.licenses=MIT

Ошибка 2 (строки 200 и 203): в шаге "Build and push" (docker/build-push-action@v6)
блок with: декларирует labels: ДВАЖДЫ:
    labels: ${{ steps.meta.outputs.labels }}            # строка 200
    labels: org.opencontainers.image.title=OryaAgent-Prerelease,...   # строка 203

YAML допускает дублирующие ключи, но второй выигрывает. Итог: labels из
metadata-action теряются, остаются только title/description. Это и
semantic-bug (два декларированных intent), и cosmetic (missing OCI labels
вроде source / revision / url).

Что сделать:

1. В шаге "Extract metadata" (docker/metadata-action@v5, строки 184-192):
   убрать строку "labels: ${{ steps.meta.outputs.labels }}" полностью.
   metadata-action автоматически отдаст в outputs.labels набор OCI labels
   (image.title, image.description, image.source, image.revision,
   image.version, image.created).

2. В шаге "Build and push" (docker/build-push-action@v6, строки 194-203):
   оставить ОДНУ строку labels:
       labels: ${{ steps.meta.outputs.labels }}
   Удалить вторую (строку 203):
       labels: org.opencontainers.image.title=OryaAgent-Prerelease,org.opencontainers.image.description=Development build from main branch
   Если хочется кастомных labels (title=OryaAgent-Prerelease) — задать их в
   metadata-action (см. ошибку 1), а не в build-push-action.

3. После мерджа проверить, что в GHCR образе есть полный набор OCI labels:
       docker pull ghcr.io/reider85/oryaagent:main
       docker inspect ghcr.io/reider85/oryaagent:main --format '{{ json .Config.Labels }}' | jq

   Ожидаемые ключи: org.opencontainers.image.title, .description, .source,
   .revision, .version, .created, .licenses.

Контрольная проверка:
    python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/release.yml')); \
      job=d['jobs']['prerelease-docker']; \
      meta=[s for s in job['steps'] if s.get('uses','').startswith('docker/metadata-action')][0]; \
      bp=[s for s in job['steps'] if s.get('uses','').startswith('docker/build-push-action')][0]; \
      assert 'labels' not in meta['with'], 'metadata-action не должен содержать labels'; \
      assert 'labels' in bp['with'], 'build-push-action должен содержать labels'; \
      assert list(bp['with'].keys()).count('labels')==1, 'labels должен встречаться 1 раз'; \
      print('OK')"
```

---

### 🟠 R-06 — Добавить `pull-requests: read` для `generate_release_notes`

**PR title:** `fix(release): grant pull-requests:read for auto release notes`

```
В .github/workflows/release.yml шаги "Create prerelease" (строка 67) и
"Create release" (строка 100) используют:
    uses: softprops/action-gh-release@v2
    with:
      generate_release_notes: true

softprops/action-gh-release@v2 для generate_release_notes=true вызывает
GitHub API /repos/{owner}/{repo}/releases/generate-notes, который требует
permission pull-requests: read (чтобы резолвить PR-numbers из commit
messages и из labels). Сейчас в release.yml на top-level granted только
contents: write — auto-notes падают с 403 или молча возвращают пустой body.

Что сделать:

1. Заменить блок permissions в release.yml (строки 20-21):
       permissions:
         contents: write
         pull-requests: read      # для generate_release_notes: true

2. Это даст pull-requests: read ВСЕМ jobs в release.yml: prerelease-on-push,
   release-on-tag, docker, prerelease-docker. Это безопасно — чтение PR-ов
   не эскалирует привилегий.

3. Если хочешь минимальные права per-job: оставить top-level permissions:
   contents: write, а в jobs docker и prerelease-docker добавить явный
   permissions: block (они уже есть и переопределяют contents: read +
   packages: write). Не забыть добавить pull-requests: read в каждый
   job, который использует softprops/action-gh-release.

4. После мерджа проверить тело следующего пререлиза: в нём должны быть
   "What's Changed" с PR-ссылками вида "#11", "#10". Если раздел пустой
   или содержит только commit-сообщения без PR-ов — permission всё ещё
   не работает.

Контрольная проверка:
    python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/release.yml')); \
      assert d['permissions'].get('pull-requests') == 'read'; \
      print('OK')"
```

---

### 🟡 R-07 — Убрать мёртвый `workflow_dispatch.inputs.prerelease` или использовать

**PR title:** `chore(release): wire up or remove workflow_dispatch.prerelease input`

```
В .github/workflows/release.yml на строках 14-18 объявлен input:
    workflow_dispatch:
      inputs:
        prerelease:
          description: "Mark as prerelease"
          default: "true"

Но ни один job не ссылается на ${{ inputs.prerelease }} или
github.event.inputs.prerelease. Это мёртвый input: пользователь думает, что
при manual run может переключать prerelease/stable, но флаг игнорируется.
Все manual runs создают пререлиз (потому что job prerelease-on-push
запускается по условию github.event_name == 'push', а не workflow_dispatch).

Что сделать — выбрать ОДИН из двух вариантов:

ВАРИАНТ A (рекомендуемый): убрать input целиком.
    on:
      push:
        branches: [main]
        ...
        tags: ["v*.*.*"]
      workflow_dispatch:    # без inputs — кнопка "Run workflow" работает
                              # и запускает prerelease-on-push по умолчанию

    Дополнительно в jobs prerelease-on-push расширить if:
        if: |
          (github.event_name == 'push' && github.ref == 'refs/heads/main') ||
          github.event_name == 'workflow_dispatch'

    Тогда manual run действительно что-то делает (создаёт пререлиз на HEAD main).

ВАРИАНТ B: сохранить input и научить jobs его слушать.
    В job prerelease-on-push изменить if:
        if: |
          (github.event_name == 'push' && github.ref == 'refs/heads/main') ||
          (github.event_name == 'workflow_dispatch' && inputs.prerelease == 'true')

    В job release-on-tag (или новый job release-on-dispatch) добавить:
        if: |
          startsWith(github.ref, 'refs/tags/v') ||
          (github.event_name == 'workflow_dispatch' && inputs.prerelease != 'true')

    Тогда manual run с prerelease=true (default) создаёт пререлиз,
    prerelease=false — стабильный релиз. Но это усложняет условие запуска,
    и release-on-tag по сути дублируется. Рекомендуется ВАРИАНТ A.

Контрольная проверка:
    python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/release.yml')); \
      ev=d.get(True, {}); \
      assert 'workflow_dispatch' in ev; \
      if 'inputs' in ev.get('workflow_dispatch', {}): \
        used = any('inputs.prerelease' in str(s) or 'github.event.inputs.prerelease' in str(s) \
                   for s in d['jobs'].values()); \
        assert used, 'inputs.prerelease объявлен, но не используется'; \
      print('OK')"
```

---

### 🟡 R-08 — Убрать literal HTML-комментарий из body `release-on-tag`

**PR title:** `fix(release): drop leftover HTML comment from tag-release body`

```
В .github/workflows/release.yml на строках 109-122 тело релиза (job
release-on-tag) содержит:
    body: |
      ## OryaAgent ${{ github.ref_name }}

      ### Highlights
      <!-- Breaking changes or migration notes go here -->

      ### Installation
      ...

HTML-комментарий <!-- ... --> попадает в GitHub Release body как literal
текст. На странице /releases/tag/vX.Y.Z пользователь видит "### Highlights"
и сразу под ним пустую строку с невидимым комментарием — выглядит как
битый шаблон.

Что сделать:

1. Удалить строку "<!-- Breaking changes or migration notes go here -->"
   целиком. Оставить заголовок "### Highlights" с пустым телом — он будет
   заполнен auto-generated notes (потому что generate_release_notes: true
   уже добавит секцию "What's Changed" ниже body). Либо убрать заголовок
   "### Highlights" целиком, если auto-notes не нужны.

2. Альтернатива: заменить на явный placeholder, который НЕ попадёт в
   финальный релиз. Например, использовать ${{ '...' }} как маркер:
       body: |
         ## OryaAgent ${{ github.ref_name }}

         ### Installation
         ...
   И не оставлять HTML-комментарии — GitHub не рендерит их, но они остаются
   в raw markdown и видны в "Edit release".

3. После мерджа вручную запушить тестовый тег v7.0.3 (или через следующий
   prerelease → promote до stable) и убедиться, что body не содержит
   "<!--" или "-->".

Контрольная проверка:
    python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/release.yml')); \
      body=d['jobs']['release-on-tag']['steps'][-1]['with']['body']; \
      assert '<!--' not in body and '-->' not in body, 'HTML-комментарий остался'; \
      print('OK')"
```

---

### 🟡 R-09 — Разделить триггеры push по branches и tags

**PR title:** `fix(release): split push triggers into two separate events`

```
В .github/workflows/release.yml on:push содержит одновременно:
    branches: [main]
    tags: ["v*.*.*"]

Когда both branches и tags указаны под одним push-событием, GitHub Actions
запускает workflow когда ЛЮБОЕ из условий совпало. Это значит:
- Push в main → workflow запустится, сработает job prerelease-on-push.
- Push тега v1.2.3 → workflow запустится, сработает job release-on-tag.

Но paths-ignore (".github/**", "tests/**", "scripts/**", "docs/**", ...)
применяется ТОЛЬКО к push по branches, НЕ к push по tags. Если кто-то
запушит тег v1.2.3, указывающий на коммит, где тронут только .github/**,
release-on-tag всё равно запустится и соберёт релиз. Это нежелаемое
поведение.

Что сделать:

1. Разделить on:push на два отдельных события:
       on:
         push:
           branches: [main]
           paths-ignore:
             - "**.md"
             - "docs/**"
             - "LICENSE"
             - ".github/**"
             - "tests/**"
             - "scripts/**"
         # tag-push не фильтруется по paths-ignore — это намеренно,
         # потому что тег всегда указывает на уже слитый коммит
         workflow_run:
           workflows: ["CI"]
           branches: [main]
           types: [completed]
         # альтернатива: только ручной триггер для тега
   ⚠️ Вышеприведённое — это пример, не точная замена. Читай ниже.

2. ПРОЩЕ: оставить один push-триггер, но добавить комментарий и
   гарантировать, что paths-ignore намеренно не применяется к tags.
   Заменить on: на:
       on:
         push:
           branches: [main]
           paths-ignore:
             - "**.md"
             - "docs/**"
             - "LICENSE"
             - ".github/**"
             - "tests/**"
             - "scripts/**"
         # Теги v*.*.* обрабатываются отдельным workflow_dispatch или
         # ручным push тега — paths-ignore к tags не применяется
         # (по дизайну GitHub Actions).
       workflow_dispatch:

   И ВЫНЕСТИ tag-trigger в ОТДЕЛЬНЫЙ workflow-файл release-tag.yml:
       # .github/workflows/release-tag.yml
       name: Release (tag)
       on:
         push:
           tags: ["v*.*.*"]
       permissions:
         contents: write
         pull-requests: read
       jobs:
         release-on-tag: ...

3. После рефакторинга в release.yml остаются ТОЛЬКО prerelease-on-push +
   prerelease-docker. release-on-tag + docker переезжают в release-tag.yml.

4. Преимущество: paths-ignore больше не влияет случайно на tag-push; в
   списке Actions видны два отдельных workflow со своей историей.

Контрольная проверка:
    # После рефакторинга:
    python3 -c "import yaml; r=yaml.safe_load(open('.github/workflows/release.yml')); \
      t=yaml.safe_load(open('.github/workflows/release-tag.yml')); \
      assert 'tags' not in r[True]['push'], 'release.yml не должен слушать tags'; \
      assert 'branches' not in t[True]['push'], 'release-tag.yml не должен слушать branches'; \
      print('OK')"
```

---

### 🟡 R-10 — Убрать `needs: []` (избыточная декларация)

**PR title:** `chore(release): drop redundant needs: []`

```
В .github/workflows/release.yml jobs docker (строка 125) и prerelease-docker
(строка 165) содержат:
    needs: []   # параллельно release-on-tag / prerelease-on-push

Это синтаксически валидно, но избыточно: job без needs: и так параллельна
корневым job-ам. needs: [] только добавляет шум и может ввести в заблуждение
("а что тут должно быть?").

Что сделать:

1. Удалить строки "needs: []" из обоих jobs.
2. Если позже захочется явной зависимости (например, build-dist перед
   docker push), добавить needs: [build-dist] или needs: [prerelease-on-push]
   с конкретным именем — НЕ возвращать пустой массив.

Контрольная проверка:
    python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/release.yml')); \
      for name in ('docker','prerelease-docker'): \
        assert 'needs' not in d['jobs'][name] or d['jobs'][name]['needs'], \
          f'job {name} всё ещё имеет needs: []'; \
      print('OK')"
```

---

### 🟢 R-11 — Добавить `timeout-minutes` на каждый job в `release.yml`

**PR title:** `ci(release): add timeout-minutes to all jobs`

```
В .github/workflows/release.yml ни один job не имеет timeout-minutes.
По умолчанию GitHub убивает job через 6 часов. Если зависнет docker build
(например, на ghcr.io rate-limit), job будет крутиться 360 минут, тратя
actions-minutes. Это дубликат CI2 B-21, который так и не был применён к
release.yml.

Что сделать:

1. Добавить timeout-minutes в каждый job:
       prerelease-on-push:  timeout-minutes: 10
       release-on-tag:      timeout-minutes: 15   # uv sync + python -m build
       docker:              timeout-minutes: 20   # docker build/push может быть долгим
       prerelease-docker:   timeout-minutes: 20

2. Это tight-лимиты: если job не укладывается, это сигнал к рефакторингу
   (например, docker layer cache через gha), а не к увеличению лимита.

3. Аналогично для nightly.yml после фикса N-01/N-02:
       nightly-prerelease:  timeout-minutes: 10

Контрольная проверка:
    python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/release.yml')); \
      for name,job in d['jobs'].items(): \
        assert job.get('timeout-minutes'), f'job {name} без timeout-minutes'; \
      print('OK')"
```

---

### 🟢 R-12 — Документировать, что теги `*-dev.N+*` не запускают `release-on-tag`

**PR title:** `docs(release): document tag pattern scope`

```
В .github/workflows/release.yml on:push:tags: ["v*.*.*"] — это glob из
трёх "."-сегментов. Он совпадает с "v7.0.1", "v7.0.2", "v1.2.3", но НЕ
совпадает с собственными пререлиз-тегами вида "v7.0.0-dev.23+6b47fc1"
(там 5 сегментов + build metadata).

Это намеренно хорошо: пререлиз, созданный prerelease-on-push, не должен
повторно запускать release-on-tag. Но нигде это не задокументировано —
новый контрибьютор может подумать, что "v*.*.*" ловит все теги начиная
с "v", и потратить время на дебаг.

Что сделать:

1. Добавить комментарий в on:push:tags:
       on:
         push:
           tags:
             - "v*.*.*"   # только stable: v7.0.1, v7.0.2, v1.2.3
                          # НЕ совпадает с пререлиз-тегами v7.0.0-dev.N+SHA
                          # (это намеренно — пререлиз создаётся отдельной job)

2. В README.md или CONTRIBUTING.md добавить секцию "Release workflow"
   с объяснением, какие теги запускают какой job.

3. Добавить regression-тест в tests/unit/ (например, test_release_yml.py),
   который парсит release.yml и проверяет:
       import yaml, fnmatch
       d = yaml.safe_load(open('.github/workflows/release.yml'))
       tags = d[True]['push']['tags']
       assert any(fnmatch.fnmatch('v7.0.1', p) for p in tags), 'stable tag должен матчиться'
       assert not any(fnmatch.fnmatch('v7.0.0-dev.23+abc1234', p) for p in tags), \
         'prerelease tag НЕ должен матчиться'

Контрольная проверка:
    python3 -c "import yaml,fnmatch; d=yaml.safe_load(open('.github/workflows/release.yml')); \
      tags=d[True]['push']['tags']; \
      assert any(fnmatch.fnmatch('v7.0.1', p) for p in tags); \
      assert not any(fnmatch.fnmatch('v7.0.0-dev.23+abc', p) for p in tags); \
      print('OK')"
```

---

### 🟢 R-13 — Заменить `+` на `-` в pre-release tag (опционально)

**PR title:** `fix(release): use dash instead of plus in prerelease tag name`

```
В .github/workflows/release.yml на строке 38 формируется тег:
    TAG="v${VERSION}-dev.${GITHUB_RUN_NUMBER}+${SHORT_SHA}"

"+" здесь — это semver build metadata (по semver-2.0.0 spec). Но:
1. В Git tag name "+" валиден, но некоторые GitHub API endpoint-ы его
   не любят (например, /releases/tag/v7.0.0-dev.23+abc1234 может вернуть
   404, потому что "+" интерпретируется как URL-encoding для пробела).
2. Docker tag не может содержать "+" — он будет заменён на "_" или
   выброшен. Образ ghcr.io/.../oryaagent:v7.0.0-dev.23+abc1234 не создастся.
3. URL `/compare/v7.0.0-dev.22...v7.0.0-dev.23+abc1234` тоже ненадёжен.

Что сделать:

1. Заменить "+" на "-" в шаблоне тега:
       TAG="v${VERSION}-dev.${GITHUB_RUN_NUMBER}-${SHORT_SHA}"
   Теперь тег выглядит как "v7.0.0-dev.23-6b47fc1" — валиден во всех
   контекстах (Git, GitHub API, Docker, URL).

2. В шаге "Skip if release for this SHA exists" (dedup) обновить endswith:
       --jq ".[] | select(.tagName|endswith(\"-${SHORT_SHA}\")) | .tagName"
   (заменили "+${SHORT_SHA}" на "-${SHORT_SHA}").

3. Проверить, что новый формат не ломает release-drafter.yml и gh workflow.

4. Альтернатива: оставить "+" и добавить URL-encoding в compare-URL шаге
   (steps.cmp.outputs.url). Но это костыль — проще заменить на "-".

Контрольная проверка:
    python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/release.yml')); \
      run=d['jobs']['prerelease-on-push']['steps'][1]['run']; \
      assert '+' not in run, 'в tag-шаблоне остался +'; \
      print('OK')"
```

---

## 3. Принцип 20/80 — что даст максимальный эффект

Применённая логика: для каждого фикса оцениваем **усилие** (S/M/L) и
**влияние на появление релизов** (1–5). В таблице ниже — топ-5 изменений,
которые вместе восстанавливают выход релизов. Сортировка по ratio эффект/усилие.

| #  | Изменение                                          | Усилие    | Эффект | Ratio | Что даёт                                                                                                                                            |
|----|----------------------------------------------------|-----------|--------|-------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| **1** | **Применить R-01** (починить отступ в release.yml:33)            | S (5 мин) | 5      | ⭐⭐⭐⭐⭐ | **Без этого ничего не работает.** workflow снова начнёт парситься, GitHub Actions перестанет помечать run как failed ещё до запуска jobs.             |
| **2** | **Применить N-01** (починить steps: в nightly.yml:15)           | S (5 мин) | 5      | ⭐⭐⭐⭐⭐ | Восстанавливает nightly-релизы. Без этого job выполняется без шагов и ничего не делает.                                                              |
| **3** | **Применить R-02 + N-02** (setup-uv перед make version)         | S (10 мин)| 4      | ⭐⭐⭐⭐  | Без uv на runner-e шаг "make version" падает. Без этого фикса даже после R-01 prerelease-on-push снова упадёт, но уже на шаге версии.                  |
| **4** | **Применить R-03** (GH_TOKEN в dedup step)                       | S (3 мин) | 4      | ⭐⭐⭐⭐  | Шаг "Skip if release for this SHA exists" без токена падает на auth. После фикса dedup корректно пропускает повторные push-и того же SHA.             |
| **5** | **Применить R-04 + R-05** (labels в prerelease-docker)          | S (10 мин)| 3      | ⭐⭐⭐   | Не блокирует релизы напрямую, но приводят к "молчащей" потере OCI labels в GHCR-образе. cosmetic + semantic баг, который легко пофиксить за один PR. |

**Сумма усилий на топ-5:** ~30 минут. **Эффект:** на следующем пуше в main
появится пререлиз v7.0.0-dev.24+<short_sha>, в Actions UI — зелёный статус
Release workflow. Через 24 часа — nightly-релиз.

---

## 4. Чек-лист применения (по приоритету)

```text
[ ] R-01  Починить отступ release.yml:33            # CRITICAL — без него релизов нет
[ ] N-01  Починить структуру steps: в nightly.yml   # CRITICAL — nightly мёртв
[ ] R-02  setup-uv в prerelease-on-push             # HIGH — make version упадёт
[ ] N-02  setup-uv в nightly                        # HIGH — то же для nightly
[ ] R-03  GH_TOKEN в dedup step                     # HIGH — gh release list упадёт
[ ] R-06  pull-requests: read для release notes     # HIGH — auto-notes пустые
[ ] R-04  Убрать labels: из metadata-action         # HIGH — самоссылка
[ ] R-05  Убрать дубль labels: в build-push-action  # HIGH — silently dropped
[ ] R-07  Убрать мёртвый input workflow_dispatch    # MEDIUM — UX
[ ] R-08  Убрать HTML-комментарий из release body   # MEDIUM — cosmetic
[ ] R-09  Разделить push branches / push tags       # MEDIUM — semantic
[ ] R-10  Убрать needs: []                          # MEDIUM — noise
[ ] R-11  timeout-minutes на каждый job             # LOW — discipline
[ ] R-12  Документировать tag-pattern               # LOW — onboarding
[ ] R-13  Заменить + на - в prerelease tag          # LOW — robustness
```

После мерджа в порядке R-01 → N-01 → R-02 → N-02 → R-03 (за один PR или
5 последовательных) следующий push в main создаёт пререлиз. Это и есть
починка «релизы не выходят».

---

## 5. Процедура валидации после применения R-01..R-03 + N-01..N-02

```bash
# 1. Локально: убедиться, что YAML парсится
python3 -c "import yaml; \
  yaml.safe_load(open('.github/workflows/release.yml')); \
  yaml.safe_load(open('.github/workflows/nightly.yml')); \
  print('Both YAML OK')"

# 2. Локально: structure check
python3 -c "import yaml; \
  r=yaml.safe_load(open('.github/workflows/release.yml')); \
  n=yaml.safe_load(open('.github/workflows/nightly.yml')); \
  assert 'steps' in r['jobs']['prerelease-on-push'], 'release.yml: нет steps в prerelease-on-push'; \
  assert 'steps' in n['jobs']['nightly-prerelease'], 'nightly.yml: нет steps в nightly-prerelease'; \
  assert any(s.get('uses','').startswith('astral-sh/setup-uv') for s in r['jobs']['prerelease-on-push']['steps']), 'нет setup-uv в prerelease-on-push'; \
  assert any(s.get('uses','').startswith('astral-sh/setup-uv') for s in n['jobs']['nightly-prerelease']['steps']), 'нет setup-uv в nightly-prerelease'; \
  print('Structure OK')"

# 3. Пуш в main (триггер для Release workflow)
git commit --allow-empty -m "ci: verify release pipeline after R-01..R-03 + N-01..N-02"
git push origin main

# 4. Открыть Actions UI: https://github.com/Reider85/OryaAgent/actions/workflows/release.yml
#    Ожидать: все шаги prerelease-on-push зелёные
#    Включая "Create prerelease" — должен создать тег v7.0.0-dev.<RUN_NUMBER>+<short_sha>
#    (или v7.0.0-dev.<RUN_NUMBER>-<short_sha>, если применён R-13)

# 5. Открыть Releases: https://github.com/Reider85/OryaAgent/releases
#    Должна появиться новая "Pre-release v7.0.0-dev.<N>+<sha>" с auto-generated notes
#    (после применения R-06 — со ссылками на PR #10, #11, ...)

# 6. Дождаться nightly (03:00 UTC) или запустить вручную через workflow_dispatch
#    На странице /releases должна появиться новая "Nightly <date>-<sha>" запись
```

Если после применения R-01..R-03 + N-01..N-02 prerelease всё ещё не выходит:

1. Открыть последний failed run → развернуть шаг "Create prerelease".
2. Проверить, что в логе нет `Error: Resource not accessible by integration`
   (означает нехватку permissions — применить R-06).
3. Проверить, что в логе нет `uv: command not found` (означает, что R-02 не применён).
4. Проверить, что в логе нет `GH_TOKEN variable not set` (означает, что R-03 не применён).

---

## 6. Дополнительные наблюдения (информативные, без обязательства правок)

1. **`release-drafter.yml` успешно работает** (запуски #59..#63 — success). Это
   значит, что Draft Release на странице /releases существует, но он не
   превращается в опубликованный release, потому что `release.yml` сломан.
   Draft — это не релиз, это просто заметка "что будет в следующем релизе".

2. **`CodeQL` успешно работает** (#56..#60). CodeQL-анализ не зависит от
   релизного пайплайна — он анализирует код, а не выпускает артефакты.

3. **`CI` workflow failed** (#60..#64). Отдельная проблема — см. CI2.md
   B-01 (YAML в docker-compose.yml). Этот failed не блокирует релизы напрямую
   (release.yml не зависит от CI через `needs:`), но он маскирует картину:
   "всё красное". После применения CI2 B-01 + CI3 R-01 весь CI/CD станет
   зелёным.

4. **Зависимость от `make version`** — узкое место. Если Makefile сломается
   (например, кто-то заменит tab на пробелы в target `version:`), упадут
   ОБА workflow сразу. Стоит рассмотреть inline-Python в workflow или
   общий composite-action `orya/get-version`, который инкапсулирует логику.

5. **`softprops/action-gh-release@v2`** в обоих шагах (prerelease + release)
   — единственная точка отказа для создания релизов. Если action обновится
   с breaking-change (как было в v1 → v2), оба workflow упадут одновременно.
   Стоит pin к конкретному SHA: `softprops/action-gh-release@<commit-sha>#v2`.

6. **`pyTooling/Actions/releaser@5c6a1aec0bb5a0243ad0c6f98a8e1258c019e679`**
   в nightly.yml — уже SHA-pinned (это было сделано в CI2 B-05). Хорошо.

7. **`docker/build-push-action@v6`** в docker и prerelease-docker — НЕ pinned
   по SHA, только по major tag `@v6`. Это supply-chain risk: если action
   скомпрометируют, ваши Docker-образы тоже. После починки релизов стоит
   SHA-pin все action-ы (см. https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions).

8. **`scripts/audit_gate.py`** в `ci.yml` — отдельная история (CI2 B-11). Не
   влияет на релизы напрямую, но `pip-audit` с `continue-on-error: true`
   формально не блокирует релиз даже при критических CVE. После починки
   релизов стоит вернуться к этому.

---

*Конец документа CI3. Применить R-01 первым — это разблокирует всё остальное.*
