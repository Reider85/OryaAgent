# Enterprise Features

**Документ:** enterprise-features
**Дата:** 20 октября 2026
**Статус:** Draft v0.1
**Связанные документы:** [README.md](../README.md), [05-security-model.md](spec/05-security-model.md), [07-observability-spec.md](spec/07-observability-spec.md), [distribution-plan.md](distribution-plan.md), [product/personas.md](product/personas.md)

---

## 0. Назначение

OryaAgent — open-source проект, доступный всем. Но enterprise adoption требует дополнительных возможностей, которых нет в community-версии. Этот документ описывает:

- Что входит в enterprise layer (поверх core OryaAgent)
- Как enterprise features интегрируются с core (не fork)
- Compliance и audit capabilities
- SSO, MDM, RBAC
- Enterprise support модель
- Pricing strategy

Enterprise layer — не отдельный продукт. Это optional features, активируемые через конфигурацию и enterprise license. Все enterprise features — open-source (Apache 2.0), но enterprise support — paid.

## 1. Принципы

### 1.1. Open-core, not proprietary

Все enterprise features — open-source. Любой может их использовать без оплаты. Paid — только enterprise support: SLA, dedicated CSM, custom feature development, training.

### 1.2. Layered architecture

Enterprise layer — над core. Не fork, не patch. Core OryaAgent не знает про enterprise features. Enterprise features — через extension points (config, custom tools, observability hooks).

### 1.3. Compliance-first

Enterprise features в первую очередь про compliance, security, audit. Не про «убрать ограничения free-версии». Free-версия — fully functional, без arbitrary limits.

### 1.4. Self-hosted

Enterprise deployment — on-premise или private cloud. No data leaves corporate network без explicit user action. Cloud SaaS — out of scope (community может создать).

## 2. Enterprise feature matrix

| Feature | Status | Version | Description |
|---|---|---|---|
| **SSO (SAML 2.0)** | Spec | v1.0.0 | Corporate identity integration |
| **SSO (OIDC)** | Spec | v1.0.0 | Modern OAuth/OIDC support |
| **Kerberos** | Spec | v1.0.0 | For Windows Active Directory |
| **MDM-managed config** | Spec | v1.0.0 | IT-managed configuration |
| **RBAC** | Spec | v1.0.0 | Role-based access control |
| **Audit log forwarding** | Spec | v0.2.0 | SIEM integration (OTel, syslog, CEF) |
| **Cost budgets per team** | Spec | v1.0.0 | Team-based cost control |
| **Sandbox enforcement** | Spec | v1.0.0 | Mandatory sandbox mode |
| **Permission mode lock** | Spec | v1.0.0 | Disable `--auto` for production |
| **Restricted providers list** | Spec | v1.0.0 | Corporate-approved LLM providers only |
| **Custom LLM gateway** | Spec | v1.0.0 | Internal LLM gateway integration |
| **Enterprise support** | Plan | v1.0.0 | Paid support with SLA |
| **Custom feature dev** | Plan | v1.0.0 | Sponsored feature development |
| **Training & onboarding** | Plan | v1.0.0 | Team training sessions |
| **Compliance packs** | Plan | v1.0.0+ | SOC 2, ISO 27001, HIPAA, FedRAMP |

## 3. SSO (Single Sign-On)

### 3.1. SAML 2.0

**Use case:** Corporate identity provider (Okta, Azure AD, Ping Identity, OneLogin).

```yaml
# /etc/orya/managed-config.yml
sso:
  enabled: true
  provider: saml
  metadata_url: https://idp.corp.example.com/metadata
  entity_id: orya-agent
  acs_url: https://orya.corp.example.com/saml/acs
  cert_file: /etc/orya/sso-cert.pem
  key_file: /etc/orya/sso-key.pem
  
  # Attribute mapping
  attributes:
    user_id: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
    email: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
    groups: "http://schemas.xmlsoap.org/claims/Group"
```

**Implementation:**
- `python3-saml` library (SAML 2.0 protocol)
- Token caching в OS keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- Session timeout: 8 hours (configurable)
- Group-based RBAC (см. раздел 5)

### 3.2. OIDC (OpenID Connect)

**Use case:** Modern cloud-native identity providers (Auth0, Keycloak, Google Workspace, AWS Cognito).

```yaml
sso:
  enabled: true
  provider: oidc
  issuer_url: https://keycloak.corp.example.com/realms/corp
  client_id: orya-agent
  client_secret_env: OIDC_CLIENT_SECRET
  redirect_uri: http://localhost:11434/callback
  scopes:
    - openid
    - profile
    - email
    - groups
```

**Implementation:**
- `authlib` library (OIDC client)
- PKCE flow (no client secret in browser)
- Refresh tokens (long sessions)
- Group claims → RBAC roles

### 3.3. Kerberos

**Use case:** Windows Active Directory environments.

```yaml
sso:
  enabled: true
  provider: kerberos
  realm: CORP.EXAMPLE.COM
  kdc: dc01.corp.example.com
  service_principal: orya/corp.example.com
  keytab_file: /etc/orya/orya.keytab
```

**Implementation:**
- `gssapi` library (Kerberos V5)
- Service tickets validation
- No interactive login (uses TGT from OS)

### 3.4. Token management

Tokens хранятся в OS keychain:
- **macOS:** Keychain Access (data protection class: `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`)
- **Windows:** Credential Manager (Windows Vault)
- **Linux:** Secret Service (via `gnome-keyring` или `kwallet`)

Никогда не записываются в plaintext config. Если keychain недоступен — fallback на encrypted file с passphrase (PBKDF2 + AES-256).

### 3.5. Session management

```python
class Session:
    user_id: str  # from SSO
    user_email: str
    user_groups: list[str]
    token: str  # opaque to OryaAgent
    token_expires_at: datetime
    refresh_token: str | None

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.token_expires_at - timedelta(minutes=5)

    async def refresh(self) -> None:
        if self.refresh_token:
            new_token = await self._provider.refresh(self.refresh_token)
            self.token = new_token.access_token
            self.token_expires_at = datetime.utcnow() + timedelta(
                seconds=new_token.expires_in
            )
            self._store.save(self)
```

При истечении session:
- TUI показывает «Session expired, refresh? [Y/n]»
- При yes — refresh flow (без перелогина)
- При no — logout, агент останавливается

## 4. MDM (Managed Device Management)

### 4.1. Configuration precedence

Конфигурация загружается в порядке (позже — выше приоритет):

1. **Built-in defaults** (в коде)
2. **System-wide config** (`/etc/orya/config.yml` на Linux, `/Library/Application Support/OryaAgent/config.plist` на macOS, Group Policy на Windows)
3. **User config** (`~/.orya/config.yml`)
4. **Project config** (`.orya/config.yml` в working dir)
5. **CLI args** (`orya --config /tmp/override.yml`)

Enterprise-managed поля — помечены в system-wide config. Если user-config пытается их переопределить — warning + system-value wins.

### 4.2. Managed policy fields

```yaml
# /etc/orya/managed-config.yml

# LLM providers — restricted list
providers:
  allowed:
    - anthropic
    - azure-openai  # corporate gateway
  denied:
    - openai        # no direct OpenAI
    - openrouter    # no third-party aggregators
    - ollama        # no local models (compliance)

# Permissions
permissions:
  mode: ask  # always ask, never auto
  mode_lock: true  # cannot be overridden
  deny_list_additions:
    - tool: bash
      pattern: "ssh\\s+.*"  # no SSH from agent
    - tool: bash
      pattern: "scp\\s+.*"  # no SCP
    - tool: bash
      pattern: "curl\\s+.*"  # no outbound HTTP

# Sensitive files
sensitive_files_additions:
  - ".corp-secrets/*"
  - "/etc/corp/*"
  - "*.production.env"

# Audit
audit:
  enabled: true
  forward_to:
    - kind: otel
      endpoint: http://otel-collector.corp:4317
  local_retention_days: 90

# Observability
observability:
  metrics:
    enabled: true
    export_to:
      - kind: otel
        endpoint: http://otel-collector.corp:4317

# Sandbox (v2)
sandbox:
  enabled: true
  enforced: true  # cannot be disabled

# Budget
budget:
  per_session_usd: 5.00
  per_day_usd: 20.00
  per_month_usd: 200.00
  hard_limit_action: stop

# Disabled features
disabled_features:
  - auto_mode  # no --auto flag
  - export_sessions  # no session export (compliance)
  - custom_providers  # no custom LLM adapters
  - custom_tools  # no custom tools
```

### 4.3. Config audit

Все config changes логируются в audit log:

```json
{
  "ts": "...",
  "event": "config_changed",
  "key": "permissions.mode",
  "old_value": "auto",
  "new_value": "ask",
  "changed_by": "managed_config",
  "reason": "system policy override"
}
```

Это позволяет forensics: кто, когда, почему изменил config.

### 4.4. Platform-specific MDM

#### Linux

- System config: `/etc/orya/config.yml` (root-owned, 0644)
- Managed config: `/etc/orya/managed-config.yml` (root-owned, 0640)
- Audit log: `/var/log/orya/audit.jsonl` (root-owned, 0600, append-only via `chattr +a`)

#### macOS

- System config: `/Library/Application Support/OryaAgent/config.plist`
- Managed via MDM (Jamf, Workspace ONE, etc.)
- Configuration Profile: `com.oryaagent.config`
- Restrictions enforced via signed profile

#### Windows

- System config: `C:\ProgramData\OryaAgent\config.json`
- Group Policy: `HKLM\SOFTWARE\OryaAgent\`
- MSI installer for enterprise deployment
- SCCM/Intune integration

### 4.5. Detection of managed environment

При запуске OryaAgent проверяет, есть ли managed-config:

```python
async def detect_managed() -> bool:
    paths = [
        "/etc/orya/managed-config.yml",
        "/Library/Application Support/OryaAgent/managed-config.plist",
        "C:\\ProgramData\\OryaAgent\\managed-config.json",
    ]
    for p in paths:
        if Path(p).exists():
            return True
    return False


if managed := detect_managed():
    logger.info(f"Managed environment detected: {managed}")
    config = merge_configs(defaults, system_managed, user_config, project_config)
    config.validate_managed_compliance()
```

В managed environment:
- Banner в TUI: «⚠️ Managed environment (corporate policy active)»
- Audit log entry при запуске
- Restricted features — disabled с clear messages

## 5. RBAC (Role-Based Access Control)

### 5.1. Roles

```yaml
rbac:
  roles:
    - name: developer
      permissions:
        - orya.session.create
        - orya.session.resume_own
        - orya.tool.execute:*
        - orya.llm.call
      denied:
        - orya.session.resume_others
        - orya.config.edit
    
    - name: senior_developer
      inherits: developer
      permissions:
        - orya.session.resume_others
        - orya.config.edit_own
    
    - name: admin
      inherits: senior_developer
      permissions:
        - orya.config.edit_managed
        - orya.audit.view
        - orya.user.manage
    
    - name: compliance_officer
      permissions:
        - orya.audit.view
        - orya.audit.export
        - orya.config.view
      denied:
        - orya.session.create
        - orya.tool.execute:*
```

### 5.2. Group mapping

Группы из SSO маппятся на roles:

```yaml
rbac:
  group_mapping:
    "corp-engineers": developer
    "corp-senior-engineers": senior_developer
    "corp-it-admins": admin
    "corp-compliance-team": compliance_officer
```

### 5.3. Permission checks

Перед каждым action — permission check:

```python
class PermissionChecker:
    def __init__(self, rbac: RBACConfig, user: Session):
        self.rbac = rbac
        self.user = user

    def check(self, action: str, resource: str = None) -> bool:
        for role in self.user.roles:
            if self.rbac.has_permission(role, action, resource):
                if not self.rbac.is_denied(role, action, resource):
                    return True
        return False


# Usage
if not checker.check("orya.tool.execute", "bash"):
    raise PermissionDenied("You don't have permission to execute bash tool")
```

### 5.4. Per-tool RBAC

```yaml
rbac:
  tool_access:
    developer:
      allow: [read, write, edit, grep, glob]
      deny: [bash]  # no bash for junior developers
    senior_developer:
      allow: [read, write, edit, bash, grep, glob]
    admin:
      allow: ["*"]
```

Junior developers не могут использовать bash-инструмент — это enforced на tool-registry level, не на permission-engine.

## 6. Audit log forwarding

### 6.1. SIEM integration

```yaml
audit:
  forward_to:
    - kind: otel
      endpoint: http://otel-collector.corp:4317
      format: otel_logs
      batch_size: 100
      flush_interval: 30s
    
    - kind: syslog
      host: siem.corp.example.com
      port: 514
      format: rfc5424
      facility: authpriv
      severity: info
    
    - kind: splunk
      endpoint: https://splunk.corp:8088/services/collector
      token_env: SPLUNK_HEC_TOKEN
      format: hec_json
      batch_size: 50
    
    - kind: cef  # ArcSight, QRadar
      host: arcsight.corp.example.com
      port: 514
      format: cef
```

### 6.2. Audit events

Все audit events описаны в [05-security-model.md](spec/05-security-model.md) раздел 7. Enterprise добавляет:

```json
{
  "ts": "2026-10-20T14:32:01.123Z",
  "event": "user_authenticated",
  "user_id": "anna@corp.example.com",
  "user_groups": ["corp-engineers"],
  "auth_method": "saml",
  "ip_address": "10.20.30.40",
  "session_id": "orya-abc123"
}

{
  "ts": "2026-10-20T14:35:15.456Z",
  "event": "permission_denied",
  "user_id": "anna@corp.example.com",
  "call_id": "tool-def456",
  "tool": "bash",
  "reason": "rbac: tool not allowed for role developer",
  "session_id": "orya-abc123"
}

{
  "ts": "2026-10-20T14:40:22.789Z",
  "event": "sensitive_file_access",
  "user_id": "anna@corp.example.com",
  "path": "/etc/corp/production.env",
  "approved_by": "user",
  "approved_at": "2026-10-20T14:40:20Z",
  "session_id": "orya-abc123"
}
```

### 6.3. Tamper-evidence

Audit log — append-only с SHA256 hash chain:

```python
class AuditLog:
    def __init__(self, path: Path):
        self._path = path
        self._prev_hash = self._load_last_hash()

    async def append(self, event: dict) -> None:
        event_with_hash = {
            **event,
            "prev_hash": self._prev_hash,
            "this_hash": self._compute_hash(event, self._prev_hash),
        }
        async with aiofiles.open(self._path, "a") as f:
            await f.write(json.dumps(event_with_hash) + "\n")
        self._prev_hash = event_with_hash["this_hash"]

    def _compute_hash(self, event: dict, prev_hash: str) -> str:
        canonical = json.dumps(event, sort_keys=True)
        return hashlib.sha256(f"{prev_hash}{canonical}".encode()).hexdigest()
```

Каждое событие содержит хэш предыдущего. Удаление или изменение любого события ломает chain — детектируется при verification.

### 6.4. Audit log retention

- **Local retention:** 90 дней (configurable)
- **After 90 days:** archive в `.zst`, store 1 year
- **After 1 year:** delete (или longer if compliance requires)
- **Enterprise:** может require 7 years retention (HIPAA, SOX)

### 6.5. Audit queries

```bash
# Query audit log
orya audit show --since="2 hours ago" --user=anna@corp
orya audit show --event=sensitive_file_access --from=2026-10-01
orya audit show --tool=bash --outcome=denied

# Export
orya audit export --from=2026-10-01 --to=2026-10-31 --format=cef > audit.cef
orya audit export --format=json | jq '.[] | select(.event=="sensitive_file_access")'

# Verification (tamper-evidence)
orya audit verify  # проверяет hash chain
```

## 7. Cost management

### 7.1. Team budgets

```yaml
budget:
  teams:
    - name: backend
      budget_per_month_usd: 500.00
      members: [anna, bob, charlie]
      alert_at: 80%
      hard_limit_at: 100%
    
    - name: ml
      budget_per_month_usd: 1000.00
      members: [dmitry, eva]
      alert_at: 80%
      hard_limit_at: 100%
    
    - name: devops
      budget_per_month_usd: 300.00
      members: [maria]
      alert_at: 70%
      hard_limit_at: 90%
```

### 7.2. Cost tracking

Cost хранится per session, aggregated per user, per team:

```python
class CostTracker:
    async def record_session_cost(
        self, user_id: str, team: str, session_id: str, cost_usd: Decimal
    ):
        # Update per-user, per-team monthly totals
        await self._store.increment(
            key=f"cost:user:{user_id}:{year_month}", value=cost_usd
        )
        await self._store.increment(
            key=f"cost:team:{team}:{year_month}", value=cost_usd
        )

    async def check_budget(self, user_id: str, team: str) -> BudgetStatus:
        user_spent = await self._store.get(f"cost:user:{user_id}:{year_month}")
        team_spent = await self._store.get(f"cost:team:{team}:{year_month}")
        team_budget = self._config.get_team_budget(team)

        return BudgetStatus(
            user_spent=user_spent,
            team_spent=team_spent,
            team_budget=team_budget,
            team_remaining=team_budget - team_spent,
            hard_limit_hit=team_spent >= team_budget * self._config.hard_limit_at,
            alert_threshold_hit=team_spent >= team_budget * self._config.alert_at,
        )
```

### 7.3. Budget alerts

- **80% threshold:** TUI warning, email to user
- **100% threshold:** agent stops, requires manager approval to continue
- **Email notifications:** daily summary, weekly trend

### 7.4. Cost dashboard

```bash
$ orya cost dashboard --month=2026-10

Cost Dashboard — October 2026
==============================

Total: $487.23 / $1,800 budget (27%)

By team:
  backend:  $234.50 / $500 (47%) ████████░░░░░░░░░░░░
  ml:       $201.30 / $1000 (20%) ████░░░░░░░░░░░░░░░░
  devops:   $51.43 / $300 (17%)  ███░░░░░░░░░░░░░░░░░

By provider:
  anthropic: $390.21 (80%)
  azure-openai: $97.02 (20%)

By user (top 5):
  anna@corp:    $98.45
  dmitry@corp:  $87.30
  bob@corp:     $76.20
  maria@corp:   $51.43
  eva@corp:     $48.50

Forecast (based on current rate):
  End of month: $1,456 / $1,800 (81%)
  Projected to hit 100%: 2026-10-28
```

## 8. Custom LLM gateway

### 8.1. Corporate gateway

Многие enterprises требуют все LLM-calls через corporate proxy:

```yaml
providers:
  azure-openai:
    base_url: https://gateway.corp.example.com/azure-openai
    api_key_env: CORP_LLM_GATEWAY_KEY
    custom_headers:
      X-Corp-User: "${USER_ID}"
      X-Corp-Team: "${USER_TEAM}"
      X-Corp-Audit-Id: "${SESSION_ID}"
    allowed_models:
      - gpt-4o
      - gpt-4o-mini
  
  anthropic-via-gateway:
    base_url: https://gateway.corp.example.com/anthropic
    api_key_env: CORP_LLM_GATEWAY_KEY
    custom_headers:
      X-Corp-User: "${USER_ID}"
    allowed_models:
      - claude-3-5-sonnet-20241022
```

### 8.2. Gateway features

- **Rate limiting** per user, per team
- **Request logging** для audit
- **Content filtering** (compliance)
- **Token quotas** per team
- **Model routing** (e.g., gpt-4o-mini for simple tasks, gpt-4o for complex)
- **Cost attribution** per user

OryaAgent просто использует gateway как обычный LLM provider. Gateway добавляет enterprise features.

### 8.3. PII filtering

Gateway может фильтровать PII перед отправкой в LLM:

```yaml
gateway:
  pii_filtering:
    enabled: true
    patterns:
      - kind: email
        regex: '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        replacement: "<EMAIL>"
      - kind: phone
        regex: '\+?\d{10,15}'
        replacement: "<PHONE>"
      - kind: ssn
        regex: '\d{3}-\d{2}-\d{4}'
        replacement: "<SSN>"
      - kind: credit_card
        regex: '\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}'
        replacement: "<CREDIT_CARD>"
```

PII фильтруется перед отправкой в LLM, что обеспечивает compliance с GDPR, CCPA, HIPAA.

## 9. Compliance packs

### 9.1. SOC 2 Type II

**Requirements:**
- Audit log с tamper-evidence (см. раздел 6.4) ✅
- Access controls (RBAC) ✅
- Change management (managed config) ✅
- Encryption at rest (v1.1: session log encryption)
- Incident response (SECURITY.md) ✅
- 1-year log retention ✅

**Audit support:**
- `orya compliance soc2 export` — генерирует audit report
- Mapping controls → evidence
- External auditor access (read-only)

### 9.2. ISO 27001

**Requirements:**
- Information security policy (SECURITY.md) ✅
- Risk assessment (risk-register.md) ✅
- Access control (RBAC, MDM) ✅
- Cryptography (encryption at rest — v1.1)
- Operations security (audit log, observability) ✅
- Compliance monitoring (audit forwarding) ✅

### 9.3. HIPAA

**Requirements:**
- Audit log (all access to PHI) ✅
- Access controls (RBAC, unique user IDs) ✅
- Encryption at rest and in transit ✅
- Breach notification (incident response procedure) ✅
- Business associate agreement (если OryaAgent обрабатывает PHI — нужен BAA с LLM-провайдером)

**Note:** HIPAA compliance зависит не только от OryaAgent, но и от того, как пользователь настраивает LLM-провайдера. Если используется corporate gateway с BAA — covered.

### 9.4. GDPR

**Requirements:**
- Data subject access: `orya export-user-data <user_id>` — экспорт всех данных пользователя
- Right to erasure: `orya delete-user-data <user_id>` — удаление всех данных
- Data portability: export в machine-readable format (JSON)
- Consent management: opt-in для telemetry
- Data residency: local-first, no data leaves by default

### 9.5. FedRAMP

**Status:** v2.0+ target

Requires:
- FIPS 140-2 cryptography
- Continuous monitoring
- Incident response
- Authorized third-party assessment

## 10. Enterprise support

### 10.1. Support tiers

| Tier | Cost | Response time | Features |
|---|---|---|---|
| **Community (free)** | $0 | best-effort | GitHub Issues, Discussions |
| **Tier 2 (paid)** | $20/seat/month | 1 business day (critical: 4h) | Priority support, dedicated CSM |
| **Tier 3 (paid)** | Custom | 4h (critical: 1h) | On-premise support, SLA, custom features |

### 10.2. SLA

**Tier 2:**
- Critical bugs: 4 hours first response, 1 business day fix
- High bugs: 1 business day first response, 3 business days fix
- Medium bugs: 3 business days first response, 1 week fix
- Low bugs: best-effort

**Tier 3:**
- Critical: 1 hour first response, 4 hours workaround, 1 day fix
- High: 4 hours first response, 1 business day fix
- Medium: 1 business day first response, 3 business days fix
- Low: best-effort

### 10.3. Dedicated CSM

Tier 2 и Tier 3 — dedicated Customer Success Manager:
- Onboarding sessions
- Quarterly business reviews
- Feature roadmap input
- Direct Slack/email channel

### 10.4. Custom feature development

Tier 3 — sponsored feature development:
- Customer sponsors feature, core team implements
- Feature становится open-source (Apache 2.0)
- Customer получает early access
- Roadmap alignment

### 10.5. Training

- **Team onboarding:** 2-hour session, $500 (free for Tier 2+)
- **Advanced training:** 1-day workshop, $2000 (free for Tier 3)
- **Train-the-trainer:** для large enterprises

## 11. Deployment models

### 11.1. Local installation (default)

```bash
# Each developer installs on their machine
pipx install orya-agent
```

Managed via MDM, SSO via corporate IdP.

### 11.2. Shared server

```bash
# On a shared dev-server
docker run -d --restart=always \
  -p 8080:8080 \
  -v /shared/orya:/data \
  -v /etc/orya:/etc/orya:ro \
  orya/orya-agent:1.0 serve
```

Developers SSH на shared server, используют через TUI или web client (v0.4.0+).

### 11.3. On-premise self-hosted

```bash
# On internal infrastructure
docker run -d \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_KEY \
  -e SSO_CONFIG=/etc/orya/sso.yml \
  -v /etc/orya:/etc/orya:ro \
  -v /var/orya:/var/orya \
  registry.corp.example.com/orya-agent:1.0
```

Internal Docker registry, internal PyPI mirror. No external network dependencies.

### 11.4. Air-gapped

Для high-security environments (gov, defense, finance):
- Offline installation via tarball
- No telemetry, no external API calls
- Local LLM (Ollama) — no cloud dependencies
- Audit log на local SIEM

## 12. Pricing

### 12.1. Open-source (free)

Apache 2.0 license. Все features доступны. Community support через GitHub.

### 12.2. Tier 2 — Team

**$20/seat/month** (min 5 seats)

Includes:
- Priority GitHub support
- Dedicated CSM
- Quarterly business reviews
- Team cost dashboard
- Onboarding session (free)
- Slack channel access

### 12.3. Tier 3 — Enterprise

**Custom pricing** (typically $50-200/seat/month)

Includes:
- SLA with penalties
- On-premise support
- Custom feature development (sponsored)
- Advanced training
- Compliance audit support
- Direct line to core team
- 24/7 critical bug response

### 12.4. Non-profit / education

Free Tier 2 для:
- Educational institutions
- Non-profits
- Open-source projects (other)

Apply through GitHub Discussions.

## 13. Roadmap

### 13.1. v0.2.0 (Q2 2026)
- Audit log forwarding (OTel, syslog)
- Local observability dashboard

### 13.2. v0.3.0 (Q3 2026)
- Sandbox (bubblewrap, sandbox-exec)
- Cost budgets per user

### 13.3. v1.0.0 (Q1 2027)
- SSO (SAML, OIDC, Kerberos)
- MDM-managed configuration
- RBAC
- Cost budgets per team
- Enterprise support launch

### 13.4. v1.1.0 (Q2 2027)
- Session log encryption at rest
- PII filtering in custom gateway
- HIPAA compliance pack

### 13.5. v2.0.0 (Q3 2027)
- FedRAMP readiness
- Advanced sandbox (network egress filtering)
- Multi-region deployment support

## 14. Открытые вопросы

1. **Commercial entity:** Создать company (OryaAgent Inc.) для enterprise contracts? Или оставаться pure open-source через Open Collective? Решение: до v1.0.0.
2. **Liability insurance:** Professional liability insurance для Tier 3 customers? Cost: $5-15k/year.
3. **Customer data:** Если Tier 3 customer делится PII для support — нужна DPA. Standard template?
4. **Audit firm:** Кто будет external auditor для SOC 2? Big 4 (PwC, Deloitte) — дорого, mid-tier — приемлемо.

---

**Вывод:** Enterprise layer OryaAgent — опциональные features поверх open-source core. Все features open-source, paid только support и SLA. Целевая аудитория — Maria (DevOps lead) и Pavel (Engineering manager), которым нужен governance, compliance, audit-trail.
