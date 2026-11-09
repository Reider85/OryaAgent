# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 7.0.x   | ✅ |
| < 7.0   | ❌ |

## Reporting a vulnerability

**Не открывай public issue для security-уязвимости.**

Вместо этого:
1. Зайди на https://github.com/Reider85/OryaAgent/security/advisories/new
2. Опиши проблему, шаги воспроизведения, impact
3. Ожидай ответа в течение 72 часов

или напиши на `team@orya.ai` с темой `[SECURITY] OryaAgent`.

## What to include

- Версия OryaAgent (`pyproject.toml`)
- Версия Python и ОС
- Минимальный PoC
- Возможный impact (RCE / data leak / auth bypass / etc.)

## Disclosure policy

- Получив репорт, мы подтверждаем получение в течение 72 часов
- Патч выпускаем в течение 30 дней (критические — 7 дней)
- После релиза патча публикуем GitHub Security Advisory с credit (если автор хочет)