# План дистрибуции OryaAgent

**Документ:** distribution-plan
**Дата:** 20 октября 2026
**Статус:** Draft v0.1
**Связанные документы:** [README.md](../README.md), [enterprise-features.md](enterprise-features.md), [risk-register.md](risk-register.md)

---

## 0. Назначение

Написать код — половина дела. Доставить его пользователю — вторая половина, часто более сложная. Этот документ фиксирует:

- Каналы дистрибуции: PyPI, pipx, Homebrew, Docker, binary releases
- Release process: версионирование, release notes, testing
- Migration strategy: обновление между версиями, breaking changes
- Discovery: как пользователи узнают о OryaAgent
- Onboarding: first-run experience, документация
- Enterprise distribution: self-hosted, on-premise, package managers
- Community growth: contributors, advocates, ecosystem

Без distribution plan — даже отличный код останется невидимым. Это не «будем распространять через pip», это strategy охвата целевой аудитории.

## 1. Принципы

### 1.1. Multi-channel

Не одна точка дистрибуции, а несколько — под разные аудитории:
- **PyPI** — primary для Python-разработчиков
- **pipx** — recommended для CLI tools
- **Homebrew** — для macOS users
- **Docker** — для enterprise / CI
- **Binary releases** — для не-Python users
- **AUR** — для Arch Linux users

### 1.2. Stable, predictable releases

- Semver strict (no surprises)
- Release-candidates для major versions
- Deprecation policy — 2 minor versions warning перед removal
- LTS для enterprise (v1.0+)

### 1.3. Backward compatibility

- Session format — версионированный, миграции при load
- Configuration — backward compatible (новые поля optional)
- API (HTTP в v0.2.0) — backward compatible в рамках major version

### 1.4. Zero-config first-run

`pip install orya && orya` — должно работать. Никаких обязательных конфигов,env vars, длительных setup-ов. Optional configuration — для advanced users.

## 2. Каналы дистрибуции

### 2.1. PyPI — primary

**Target:** все Python-разработчики

```bash
pip install orya-agent
orya
```

PyPI package `orya-agent` (имя `orya` зарезервировано). Wheel + sdist.

**Setup:**
- `pyproject.toml` с PEP 621 metadata
- `hatchling` как build-backend (быстрый, современный)
- CI через GitHub Actions: tag → build → TestPyPI → PyPI
- Trusted Publishers (PEP 721) вместо API tokens

**Версионирование:** Semver
- 0.x.y — pre-alpha / alpha / beta
- 1.0.0 — first stable
- Major bumps — breaking changes

### 2.2. pipx — recommended for CLI

**Target:** разработчики, использующие OryaAgent как CLI tool

```bash
pipx install orya-agent
orya
```

`pipx` создаёт isolated Python environment, не конфликтует с system Python. Это recommended installation path для end-users.

Документация в README:
```bash
# Recommended (isolated environment)
pipx install orya-agent

# Or with pip
pip install orya-agent

# Or from source
git clone https://github.com/Reider85/OryaAgent.git
cd OryaAgent
pip install -e .
```

### 2.3. Homebrew — macOS

**Target:** macOS users (Anna — primary persona)

```bash
brew install orya-agent
```

Через homebrew tap: `reider85/tap`.

```bash
brew tap reider85/tap
brew install orya-agent
```

Или напрямую:
```bash
brew install reider85/tap/orya-agent
```

**Setup:**
- `homebrew-orya-agent` tap repository
- Formula обновляется автоматически при release (через GitHub Actions)
- Поддержка: macOS Intel + ARM (Apple Silicon)

### 2.4. AUR (Arch User Repository)

**Target:** Arch Linux users

```bash
yay -S orya-agent-bin
# or
yay -S orya-agent
```

Два пакета:
- `orya-agent-bin` — prebuilt binary (через PyOxidizer или Nuitka)
- `orya-agent` — из исходников

**Setup:**
- AUR-репозиторий: `orya-agent-bin`, `orya-agent`
- Maintainer: core team + community volunteer

### 2.5. Docker

**Target:** enterprise, CI/CD, users wanting isolation

```bash
docker run --rm -it -v $(pwd):/workspace -v ~/.orya:/root/.orya orya/orya-agent
```

**Images:**
- `orya/orya-agent:latest` — latest stable
- `orya/orya-agent:0.1` — minor version
- `orya/orya-agent:0.1.0` — specific patch
- `orya/orya-agent:alpine` — Alpine-based, smaller

**Setup:**
- Multi-arch: linux/amd64, linux/arm64
- Build через Docker Hub automated builds или GitHub Container Registry
- Image size target: <200MB (alpine — <100MB)

### 2.6. Binary releases

**Target:** non-Python users, корпоративные users без pip

```bash
curl -L https://github.com/Reider85/OryaAgent/releases/latest/download/orya-linux-x64 -o orya
chmod +x orya
./orya
```

**Build:**
- `PyOxidizer` или `Nuitka` — single executable
- Targets: linux-x64, linux-arm64, macos-x64, macos-arm64, windows-x64
- Размер: ~30-50MB (включает Python runtime)

**Limitations:**
- Larger download чем pip
- Slower to update (нужно скачивать новый binary)
- Без auto-update (требуется package manager)

### 2.7. GitHub Releases

**Target:** source-users, package maintainers

Каждый release включает:
- Source tarball (sdist)
- Wheel packages (multi-arch)
- Binary releases
- SHA256 checksums
- Signature (GPG, если будет demand)
- Release notes (autogenerated + manual edits)

### 2.8. conda-forge

**Target:** scientific community (Dmitry — primary persona)

```bash
conda install -c conda-forge orya-agent
```

**Setup:**
- conda-forge feedstock
- Maintainer: community volunteer from conda-forge
- Recipe обновляется при release

## 3. Release process

### 3.1. Versioning policy

**Semver 2.0:**
- MAJOR (1.0 → 2.0) — breaking changes
- MINOR (0.1 → 0.2) — new features, backward compatible
- PATCH (0.1.0 → 0.1.1) — bug fixes

Pre-release versions:
- `0.1.0-alpha.1` — internal testing
- `0.1.0-beta.1` — public beta
- `0.1.0-rc.1` — release candidate
- `0.1.0` — final

### 3.2. Release workflow

```
1. Branch off develop → release/0.1.0
2. Update version in pyproject.toml
3. Update CHANGELOG.md
4. Run full test suite
5. Smoke test with real LLM API
6. Create PR to main
7. After merge: tag v0.1.0
8. CI: build → TestPyPI publish
9. Smoke install from TestPyPI, verify
10. Promote to PyPI
11. Update Homebrew tap
12. Update AUR package
13. Update Docker Hub images
14. Create GitHub Release with artifacts
15. Announce: blog post, HN, Reddit, Twitter, Discussions
```

### 3.3. CHANGELOG.md

Format: [Keep a Changelog](https://keepachangelog.com/)

```markdown
## [Unreleased]

## [0.1.0] - 2026-12-15

### Added
- LLM provider seam with OpenAI-compat and Anthropic adapters
- 5 base tools: read, write, edit, bash, grep
- Append-only JSONL session log with projection
- Permission engine with ask/auto modes
- CLI/TUI with rich rendering
- Audit log for all permission decisions

### Changed
- N/A (initial release)

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- Sensitive file detection
- Deny-list for dangerous bash patterns

## [0.0.1] - 2026-10-15
- Initial pre-alpha, internal testing
```

### 3.4. Release notes template

```markdown
# Release 0.1.0 — First public release

We're excited to announce OryaAgent 0.1.0, the first public release of
the open-source coding agent for terminal-native developers.

## Highlights

- ✨ Provider-agnostic: OpenAI, Anthropic, Ollama, OpenRouter out of the box
- 🔒 Security-first: ask-mode by default, sensitive file protection
- 📝 Event-sourced sessions: crash recovery, full audit trail
- 🐍 Python-native: built with asyncio + Pydantic

## Installation

\`\`\`bash
pipx install orya-agent
\`\`\`

## What's included

- 5 base tools: read, write, edit, bash, grep
- OpenAI-compat + Anthropic LLM adapters
- Append-only JSONL session format
- Permission engine with allow/deny lists
- Audit log for all actions

## Known limitations

- No MCP support (planned for v0.2.0)
- No subagents (planned for v0.3.0)
- No IDE plugins (planned for v0.4.0)

## What's next

See our [roadmap](README.md#roadmap) for v0.2.0+ plans.

## Thanks

Thanks to our contributors: [list]

## Feedback

- [Issues](https://github.com/Reider85/OryaAgent/issues)
- [Discussions](https://github.com/Reider85/OryaAgent/discussions)
```

### 3.5. Release cadence

| Version | Target | Cadence |
|---|---|---|
| 0.1.0 — 0.4.0 | Monthly | 4-6 weeks между minor |
| 0.x patch | As needed | Bug fixes, security patches |
| 1.0.0+ | Quarterly | Major releases каждые 3 months |
| LTS (v1.0+) | Annual | Long-term support для enterprise |

### 3.6. Backward compatibility

| Component | v0.1 → v0.2 | v0.x → v1.0 | v1.x → v2.0 |
|---|---|---|---|
| CLI args | backward compatible | deprecation warnings | breaking |
| Config YAML | backward compatible | new optional fields | schema migration |
| Session JSONL | migration framework | migration framework | migration framework |
| Python API | backward compatible | backward compatible | breaking changes |
| HTTP API (v0.2+) | backward compatible | backward compatible | versioned endpoints |

Deprecation policy:
- Field/function deprecated в minor version
- Warning при use
- Removed в next major version
- Documentation: «deprecated since X, removed in Y»

## 4. Migration strategy

### 4.1. Session format migrations

Каждое событие в session-log имеет `schema_version`. При load — применяются миграции:

```python
MIGRATIONS = [
    Migration("0.9", "1.0", migrate_0_9_to_1_0),
    Migration("1.0", "1.1", migrate_1_0_to_1_1),
    # ...
]
```

Migration:
- Read-only на исходном файле (создаёт `.migrated.jsonl`)
- Idempotent
- Logged в audit log
- Tested с golden + property tests

Если migration падает — backup оригинала сохраняется, пользователь получает понятную ошибку.

### 4.2. Config migrations

Config YAML — backward compatible. Если поле удалено в новой версии:
- Старое поле игнорируется (с warning)
- New equivalent documented

Если значение изменено semantic-и (например, default `mode: ask` → `mode: strict`):
- В release notes — prominently
- При первом запуске после upgrade — explicit warning
- Documentation: migration guide

### 4.3. CLI args migrations

Если CLI arg удаляется/переименовывается:
- Old name работает с deprecation warning
- `--help` показывает оба с пометкой deprecated
- Removed в next major version

### 4.4. Major version upgrade guide

Для v1.0.0 (и каждого major):
- `UPGRADE-v1.md` — detailed migration guide
- Breaking changes — prominent section
- Migration tools: `orya migrate --from=0.4 --to=1.0`
- Office hours в Discussions для Q&A

## 5. Discovery — как пользователи узнают

### 5.1. Launch channels

**v0.1.0 launch (target: December 2026):**
1. **Show HN** — Hacker News post
2. **Reddit** — r/programming, r/Python, r/MachineLearning
3. **Twitter/X** — tagging AI dev accounts
4. **LinkedIn** — professional network
5. **Mastodon** — fediverse (Python community)
6. **Dev.to / Medium** — technical blog post
7. **Podcasts** — подкасты про AI tools (Latent Space, Practical AI)
8. **YouTube** — review запросы к AI-обзорщикам

### 5.2. Ongoing content

- **Blog posts** на oryaagent.dev — weekly, deep dives
- **Tutorials** — how-to для типичных задач
- **Comparison posts** — vs Cursor, vs Claude Code, vs Aider
- **Video demos** — YouTube канал

### 5.3. SEO

- Website: oryaagent.dev
- Documentation: docs.oryaagent.dev (mkdocs)
- Keywords: «open source coding agent», «CLI AI coding tool», «provider agnostic coding agent»
- Structured data для documentation

### 5.4. Community

- **GitHub Discussions** — primary community hub
- **Discord server** — для real-time chat (опционально)
- **Contributor office hours** — weekly call для contributors
- **Conference talks** — PyCon, EuroPython, etc.

### 5.5. Partnership

- **Anthropic** — listing в app directory (если будет)
- **OpenAI** — listing в integration directory
- **Ollama** — recommended в ecosystem
- **Cursor alternatives** — community list (awesome-cursor-alternatives)

## 6. Onboarding experience

### 6.1. First-run

```bash
$ pipx install orya-agent
$ orya

Welcome to OryaAgent v0.1.0!

To get started, I need to know which LLM provider you want to use.

Available providers:
  1. Anthropic (Claude) — best for general coding
  2. OpenAI (GPT-4o, GPT-4o-mini) — wide compatibility
  3. Ollama (local) — privacy-first, free
  4. OpenRouter — 200+ models via single API
  5. Configure later

Choose [1-5]: _

# If 1 (Anthropic):
You'll need an Anthropic API key.
Get one at: https://console.anthropic.com/

Enter API key (or set ANTHROPIC_API_KEY env var): _

# Setup complete:
✓ Provider configured: Anthropic (claude-3-5-sonnet)
✓ Created ~/.orya/config.yml
✓ Created ~/.orya/permissions.yml (ask-mode default)

Type your question below. Type /help for commands.

> _
```

### 6.2. Documentation

**Structure:**
```
docs.oryaagent.dev/
├── /                  — landing page
├── /quickstart        — 5-minute guide
├── /guide/            — step-by-step tutorials
│   ├── installation
│   ├── first-session
│   ├── customizing
│   ├── providers
│   ├── tools
│   ├── permissions
│   ├── sessions
│   └── troubleshooting
├── /reference/        — API reference
│   ├── cli
│   ├── config
│   ├── providers
│   └── tools
├── /advanced/         — deep-dives
│   ├── enterprise
│   ├── custom-providers
│   ├── custom-tools
│   └── ci-cd
├── /community/
│   ├── faq
│   ├── recipes
│   └── showcase
└── /blog/             — blog posts
```

**Tech:** mkdocs-material + griffe для API auto-docs.

### 6.3. Quick start (5 minutes)

```markdown
# Quick start

## 1. Install

\`\`\`bash
pipx install orya-agent
\`\`\`

## 2. Run

\`\`\`bash
orya
\`\`\`

First run will ask for LLM provider. Choose one (Anthropic recommended).

## 3. Try

\`\`\`
> what does main.py do?
> add a function to calculate fibonacci
> run the tests
\`\`\`

## 4. Customize

Edit `~/.orya/permissions.yml` to add your allow-list.

## 5. Next

- [Customizing providers](guide/providers.md)
- [Sessions and history](guide/sessions.md)
- [Security model](guide/permissions.md)
```

### 6.4. FAQ

Top questions (predicted):
- **Q: How is this different from Claude Code?**
  A: Open-source, provider-agnostic, CLI-native, Python-based. See [competitors-extra.md](analytics/competitors-extra.md).

- **Q: Can I use local models?**
  A: Yes, Ollama is supported out of the box. See [guide/providers](docs/guide/providers.md).

- **Q: Is my code sent to cloud?**
  A: Only if you choose cloud LLM. With Ollama — fully local. Audit log is local. See [SECURITY.md](SECURITY.md).

- **Q: Can I use this in CI/CD?**
  A: Yes, `orya --auto` mode for non-interactive usage. See [guide/ci-cd](docs/guide/ci-cd.md).

- **Q: How much does it cost?**
  A: OryaAgent itself is free. LLM API costs depend on your usage (~$0.01-0.50 per session with Claude Sonnet).

- **Q: Can I contribute?**
  A: Yes! See [CONTRIBUTING.md](CONTRIBUTING.md). We welcome LLM adapters, tools, docs, tests.

## 7. Enterprise distribution

### 7.1. Self-hosted

Enterprise customers могут self-host:
- **On-premise deployment** — без external dependencies
- **Private PyPI** — через DevPi или Artifactory
- **Internal mirror** — компании mirror PyPI, OryaAgent доступен internally
- **Docker registry** — `registry.corp.example.com/orya-agent:1.0`

### 7.2. Enterprise license

Apache 2.0 — для всех. Дополнительные enterprise features (SSO, MDM, audit forwarding) — open-source, no commercial license.

**Enterprise support:**
- **Tier 1 (free):** community support, GitHub Issues
- **Tier 2 (paid):** priority response, dedicated CSM, custom features (v1.0+)
- **Tier 3 (paid):** on-premise support, SLA, training (v1.0+)

Pricing model (target v1.0.0):
- $20/seat/month — Tier 2
- Custom — Tier 3 (negotiated)

### 7.3. Compliance packages

- **SOC 2 Type II** — v1.0+ (после external audit)
- **ISO 27001** — v1.0+ (если будет demand)
- **HIPAA** — v1.0+ (healthcare customers)
- **FedRAMP** — v2.0+ (US government)

### 7.4. Procurement-friendly

- **Single-throat:** enterprise contract через одну компанию (если будет создана)
- **Public security audit:** SECURITY.md + audit reports
- **Insurance:** cyber liability insurance (если будет company)
- **Indemnification:** Apache 2.0 + optional commercial indemnification (Tier 3)

## 8. Community growth

### 8.1. Contributors

**Pipeline:**
1. **User** — устанавливает, использует
2. **Issue reporter** — открывает Issue, помогает debug
3. **PR submitter** — small fixes, documentation
4. **Feature contributor** — implements new features
5. **Maintainer** — review PRs, merge, release

**Onboarding:**
- `good first issue` — метка для simple tasks
- `CONTRIBUTING.md` — clear setup
- Office hours — weekly call для onboarding
- Mentorship — pairing с existing maintainer

**Targets:**
- v0.1.0: 5 contributors (core team + early adopters)
- v0.5.0: 50 contributors
- v1.0.0: 200 contributors
- v2.0.0: 500+ contributors

### 8.2. Advocates

- **Conference talks** — sponsor или support для speakers
- **Blog posts** — guest posts на dev.to, Medium
- **Video tutorials** — YouTube collaborations
- **Twitter presence** — @oryaagent, founder account

### 8.3. Ecosystem

- **Custom LLM adapters** — community-contributed (Cohere, Mistral, Gemini)
- **Custom tools** — через Python subclass
- **Skills** — community-shared через `orya skills install`
- **Recipes** — `.orya/` directory в репозиториях

### 8.4. Recognition

- **CONTRIBUTORS.md** — все contributors
- **Release notes** — significant contributions mentioned
- **Annual contributor awards** — top contributors highlighted
- **Swag** — stickers, t-shirts для active contributors

## 9. Metrics

### 9.1. Distribution metrics

- **PyPI downloads** — weekly, monthly
- **GitHub stars** — growth rate
- **Homebrew installs** — installs per month
- **Docker pulls** — per month
- **Discord/Slack members** — community growth

### 9.2. Usage metrics

- **Active users** — based on local metrics (anonymous, opt-in v2)
- **Session count** — from local stats
- **Tool usage distribution** — which tools most used
- **Provider distribution** — which providers popular

### 9.3. Quality metrics

- **Issue response time** — median time to first response
- **PR merge time** — median time to merge
- **Bug report quality** — % reports with reproducer
- **Documentation helpfulness** — survey after v0.2.0

### 9.4. Targets (12 months post v0.1.0)

- 10,000 PyPI downloads/month
- 1,000 GitHub stars
- 100 active contributors
- 50 community recipes
- 5 conference talks
- 1 enterprise customer (Tier 2)

## 10. Risk mitigation

### 10.1. Distribution risks

| Risk | Mitigation |
|---|---|
| PyPI package name squatting | Register early, before announcement |
| Homebrew tap maintenance | Automate via GitHub Actions |
| Docker image bloat | Multi-stage builds, Alpine variant |
| Binary size | PyOxidizer optimizations, strip symbols |
| Bandwidth costs | Use GitHub Releases (free CDN) |

### 10.2. Adoption risks

| Risk | Mitigation |
|---|---|
| User can't configure LLM | First-run wizard, clear docs |
| First session too expensive | Default to gpt-4o-mini or Ollama |
| Crash on first use | Comprehensive smoke tests |
| Negative comparison to Claude Code | Honest comparison docs, focus on differentiators |

## 11. Открытые вопросы

1. **Website hosting:** oryaagent.dev — кто hosting? GitHub Pages (free) или Vercel (better DX)?
2. **Discord vs Slack:** Discord — для community (free, voice), Slack — для enterprise (paid, integrations)?
3. **Sponsorship:** GitHub Sponsors для core team? Open Collective для expenses?
4. **Commercial entity:** Создать company для enterprise support? Или остаться pure open-source?
5. **Trademark:** Register «OryaAgent» trademark? Cost vs benefit.

---

**Следующие шаги:**

1. Зарегистрировать PyPI package name `orya-agent` (early)
2. Зарегистрировать GitHub Container Registry namespace `orya`
3. Купить домен oryaagent.dev
4. Настроить mkdocs-material для docs
5. Создать Homebrew tap repository
6. Написать launch announcement draft
7. Связаться с Ollama team для ecosystem listing
