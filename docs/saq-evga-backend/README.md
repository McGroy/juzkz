# Бэкенд модуля ЭВГА для фронта `saq-evga-test`: анализ и рекомендации

Дата: 23.09.2026. Основание: три переданных архива — `saq-prof-control-demo` (эталон стиля команды, front + back), `saq-evga-test` (фронт ЭВГА без бэкенда), `n8n_old_project_archive` (старая реализация ЭВГА на n8n + Camunda/Zeebe).

**Цель документа** — дать команде разработки достаточно конкретные рекомендации, чтобы начать писать бэкенд ЭВГА «в своём стиле» (как в `saq-prof-control-demo`), переиспользуя уже реализованную бизнес-логику старой системы и не переписывая фронт.

**Как читать.** §1 — резюме и решения; §2 — что есть в трёх исходниках; §3 — целевая архитектура (стек, приложения, модели, сервисы, API, роли, интеграции, справочники); §4 — что и откуда переиспользуем; §5 — перевод фронта на API; §6 — план работ по итерациям; §7 — тесты; §8 — открытые вопросы с решениями по умолчанию; §9 — журнал альтернатив. Детальные инженерные материалы (модели с полями, полный API-контракт, таблицы переходов, каталоги кодов старой системы) — в `design/design-final.md` и в папке `analysis/`.

**Состав папки**

| Файл | Содержание |
|---|---|
| `README.md` (этот файл) | Сводный документ рекомендаций |
| `design/design-final.md` | Итоговый проект архитектуры бэкенда: все модели с полями, сервисы и таблицы переходов, полный API-контракт, RBAC, интеграции, seed-команды, план и оценки |
| `analysis/prof-backend-style.md` | Style guide бэкенда команды по коду `saq-prof-control-demo/backend`; таблица переиспользования приложений |
| `analysis/prof-frontend-integration.md` | Как фронт prof работает с API; план перевода фронта ЭВГА (`EvgaGateway`, страйглер) |
| `analysis/evga-domain-model.md` | Инвентарь сущностей фронта ЭВГА, 105 видов документов, справочники, валидация, эскиз Django-моделей |
| `analysis/evga-workflows.md` | Конечные автоматы документа и дела, маршруты, роли, сроки, ~60 мутаций → эндпоинты, ~180 тестовых сценариев |
| `analysis/evga-ui-actions.md` | Экраны и действия UI → эндпоинты; файлы; демо-механики, которые заменяет сервер; что менять во фронте |
| `analysis/evga-docs-requirements.md` | Постановки и ответы заказчика (Q01–Q20), каталог документов с M-кодами, открытые вопросы |
| `analysis/n8n-cases-documents.md` | Старый бэкенд: схема `surfk.*`, API/коды действий, бизнес-правила SQL/JS, ЕРСОП, соответствие кодов документов |
| `analysis/n8n-references-auth-notify.md` | Старый бэкенд: справочники, Keycloak/роли, уведомления, журнал, апелляции |
| `analysis/bpmn-processes.md` | 72 BPMN-процесса Camunda/Zeebe: шаблон жизненного цикла, каталоги статусов/действий/ролей, процесс дела, рекомендация не переносить Zeebe |
| `analysis/tor-and-common-requirements.md` | ТЗ prof-control, сквозные требования SAQ, соответствие 12 документов prof ↔ ЭВГА, контракт ЕРСОП |

| `analysis/artifacts/evga-forms-dump.json`, `evga-forms-summary.txt`, `evga-dump-forms.mts` | Выгрузка 86 схем форм фронта (43 вида × 2 типа аудита) — готовые данные для сида `FormSchema`; скрипт получения (`node --experimental-strip-types`) |
| `analysis/artifacts/bpmn-catalogs.txt`, `bpmn-parse.py`, `bpmn-aggregate.py` | Сводные каталоги статусов, действий, ролей и таймеров по 72 BPMN-процессам и скрипты их получения |
| `analysis/artifacts/n8n-parse-workflow.py`, `n8n-dump-nodes.py` | Скрипты распечатки узлов n8n-воркфлоу (webhook, SQL, JS, HTTP) для трассировки старой логики |

Примечание: в отчётах `analysis/` встречаются ссылки на временные файлы анализа (`forms_dump.json`, `bpmn_parsed.json`, `digest.txt`); ключевые из них сохранены в `analysis/artifacts/` под именами из таблицы выше, объёмные промежуточные (`bpmn_parsed.json`, `digest.txt`) воспроизводятся скриптами `bpmn-parse.py` / `bpmn-aggregate.py` по папке `n8n_old_project_archive/bpmn`.

---

## 1. Резюме: что рекомендуем

**Вывод.** Фронт ЭВГА (`saq-evga-test`) готов к подключению серверного API: вся бизнес-логика уже вынесена в чистые функции и покрыта ~218 тестами, а хранилище отгорожено контрактом `AuditCaseRepository`. Бэкенд нужно **строить на каркасе prof** (Django 5 + DRF + PostgreSQL + MinIO + Keycloak), а старую n8n/BPMN-систему использовать **как спецификацию** (схема данных, коды статусов/действий/документов, форматы номеров, контракт ЕРСОП, справочники, роли Keycloak), **не перенося** сами n8n, Camunda/Zeebe, PostgREST и RabbitMQ.

Ключевые решения (подробно — §3, журнал альтернатив — §9):

1. **Отдельный репозиторий `saq-evga-backend`**, созданный копированием каркаса prof (`config/`, `apps/core`, `apps/accounts`, `apps/catalogs`, `apps/subjects`, Docker/compose/deploy, pytest/ruff). Общие приложения меняются только аддитивно, чтобы позже слить всё в монорепо SAQ переносом папок `apps/evga_*`. Фронт — тот же `saq-evga-test`, деплой same-origin через nginx (как prof), Vercel убираем.
2. **Восемь новых приложений по шаблону prof**: `evga_cases`, `evga_documents`, `evga_workflow`, `evga_execution`, `evga_appeals`, `evga_ersop`, `evga_cabinet`, `notifications`. Структура каждого — `models / api / services / management / tests`, как в эталоне.
3. **Документ = `AuditDocument` (шапка) + `DocumentVersion`** (статус, владелец, `values` JSONB по декларативной `FormSchema`, `row_version`). Это единственное существенное отличие от модели prof: ЭВГА требует версий (решение заказчика Q07), 19 повторяемых видов и 105 форм (≈900 полей) — 40 таблиц `*Details` означали бы переписать 25 тыс. строк форм фронта. Реляционно выносятся только строки, на которые ссылаются другие документы и отчёты (нарушения, пункты предписания, рекомендации, меры).
4. **Статусы — 11 значений `DocStatus` фронта** как `TextChoices` с русскими подписями; 45 статусов старой системы сводятся к ним и к под-состояниям (регистрация ЕРСОП, доставка объекту, подтверждения КВГА/реестра, раунды требований), коды старой системы хранятся в таблице соответствия.
5. **Маршрут согласования — таблицы** `ApprovalRoute / Stage / Participant / Event` (порт контракта `shared/workflow/approvalRoute.ts`, 27 тестов), инбокс задач — вычисляемая проекция.
6. **Сервисный слой — порт чистых функций фронта 1:1 в Python** с теми же текстами ошибок; таблицы переходов объявляются в коде по семействам BPMN (T0–T9); гейты (`creationBlock`, `dependencies`, `check-docs-status`) — вычислением, не событиями.
7. **API в стиле prof**: `GenericViewSet` для чтения, отдельный `APIView` на каждое действие с явными URL, но с общим базовым классом и реестром действий (единые `expected_version → 409`, журнал, `available_actions` для кнопок фронта). Агрегат `workspace` дела, инбокс, уведомления, реестр исполнения, справочники, кабинет объекта.
8. **RBAC prof без изменений кода**: домены `evga_cases / evga_quality / evga_registry / evga_appeals / evga_execution / evga_cabinet`, уровень `CONFIRM`; 16 ролей (14 `evga-*`, `observer`, `evga-admin`) с таблицей соответствия Keycloak-ролям старой системы (важно: старый `approver` = фронтовый `reviewer`, старый `confirmer` = фронтовый `approver`); адресные назначения (эксперт КК, подтверждающий КВГА/реестра, соавтор) — таблицы + проверки в сервисах.
9. **Журнал `core.AuditEvent` реально пишется** из каждого перехода (в prof модель есть, но не используется); нумерация — `core.NumberSequence` с настраиваемыми шаблонами (формат дела `30101-YY-NNNNN` совпадает у фронта и старой системы).
10. **Интеграции — заглушки за адаптерами** по образцу `ersop/stub_exchange` с журналом обмена: ЕРСОП (реальный контракт SOAP `SI_SUR2ERSOP_RequestSubjectAsync`, типы сообщений `Started…Finished` восстановлены из n8n), ГБД ЮЛ/ФЛ, ЭЦП, уведомления in-app. Таймеры — одна management-команда по cron, без Celery.
11. **Фронт переводится страйглером**: `EvgaGateway` с двумя реализациями (API / локальная), адаптер сохраняет форму `AuditCase`, формы и печать не трогаются; демо-роли, IndexedDB и `demoScenario` удаляются (сценарии → `seed_evga_demo_cases`).
12. **Демо на сервере как можно раньше**: каркас → справочники и объекты → дела → документы/версии/черновики → маршрут/инбокс/уведомления (Демо-1 после ≈36 чел.-дн. бэкенда, при двух разработчиках ≈ 4 недели), далее этапы процесса по порядку с демо после каждого; полный объём ≈ 94 чел.-дн. бэкенда + ≈ 36 чел.-дн. фронта (§6).

Чего в этой рекомендации **нет** и почему: переноса Camunda/Zeebe (в BPMN нет бизнес-логики — каждый шаг лишь вызывает n8n-webhook; 6 базовых статусов, один параллельный шлюз на 72 процесса), административного производства (M38–M57, во фронте отсутствует, ПЗ не передано), автосоздания документов и автоподписи отчёта по таймеру (противоречат ответам заказчика Q08 и решениям команды), серверного PDF на первом этапе (нужен только для ЭЦП, ЕРСОП и публичной верификации — отдельная итерация).

---

## 2. Что у нас есть: три исходника

### 2.1. `saq-prof-control-demo` — эталон стиля команды (front + back)

| Параметр | Значение |
|---|---|
| Назначение | Модуль «Профилактический контроль» SAQ: ДФО → СУР → полугодовой перечень → дела → документы → ЕРСОП → исполнение |
| Бэкенд | Python 3.13, Django 5.2.6, DRF 3.16, django-filter, drf-spectacular, django-environ, django-storages[s3] (MinIO), psycopg 3, PyJWT (Keycloak OIDC + PKCE), argon2, gunicorn, whitenoise; PostgreSQL 16 |
| Объём бэкенда | 12 169 строк Python без миграций, 13 приложений (`core, catalogs, accounts, subjects, reporting, risk, semiannual, cases, documents, checklists, execution, ersop, cabinet`), 26 миграций, 79 pytest-тестов |
| Фронтенд | React 19, TypeScript 5.9, Vite 7, Tailwind 4, react-router 7, Paraglide (ru/kk), lucide; ~20 800 строк TS/TSX |
| Инфраструктура | `docker-compose.yml` (postgres:16, minio + minio-init, backend), nginx на хосте раздаёт `frontend/dist` и проксирует `/api/`, `/admin/`; `deploy/README.md` — пошаговая инструкция для Ubuntu |
| Документация | `docs/tor/Postanovka_obshhaya.docx` (ТЗ, 35 листов), `docs/specs/document-matrix.md` (12 печатных документов дела), `docs/architecture/project-decisions.md`, `docs/release-notes/` |
| Что берём | Архитектурные соглашения (см. §3), инфраструктуру и приложения `core`, `accounts`, `catalogs`, `subjects` почти без изменений; `documents`/`execution`/`ersop`/`cabinet` — как образец |

Ключевые соглашения «стиля prof» (подробно — `analysis/prof-backend-style.md`):

- `apps/<domain>/{models.py, admin.py, api/{views,serializers,urls,filters}.py, services/*.py, management/commands/seed_*.py, tests/}`;
- все модели наследуют `core.TimeStampedModel` (UUID pk, `created_at/updated_at/created_by`), статусы — `models.TextChoices` c UPPER_CASE-кодом и русской подписью, натуральные ключи `UniqueConstraint(name="<app>_<model>_natural_key")`;
- generic-модели `core.Attachment` (файлы в MinIO, SHA-256), `core.AuditEvent` (append-only журнал по табл. 49 ТЗ), `core.NumberSequence` + `IssuedNumber` (идемпотентная нумерация `issue_number()`);
- сервисный слой — функции-модули (`create_*/approve_*/sign_*/send_*`), keyword-only аргументы, `@transaction.atomic`, `select_for_update`, доменная ошибка `DocumentTransitionError("…, сейчас: {status}")`;
- API — `GenericViewSet` + mixins для чтения и **отдельный `APIView` на каждое действие** (`@action` не используется), `get_permissions() → [IsAuthenticated(), HasDomainLevel()]`, атрибуты `required_domain/required_levels`, `ScopedQuerySetMixin`;
- единый конверт ошибок `{type, title, status, detail, code, …}`; бизнес-ошибки → `ValidationError({"detail"})` (HTTP 400);
- RBAC: `Role` → `RolePermission(domain, level)` → `RoleAssignment(user, department, valid_from/to)`; сессия — httpOnly cookie `saq_session`; вход local (email/пароль) и Keycloak;
- интеграции — заглушки без сети (`ersop/services/stub_exchange.py`) + лог обмена `ErsopExchange` с JSON-payload;
- seed-команды `update_or_create` для справочников, ролей, номеров, типов документов; `docker/entrypoint.sh` = `migrate → collectstatic → seed_* → gunicorn`.

Что в эталоне стоит **не** копировать: `AuditEvent` спроектирован, но ни один сервис его не пишет; `_assert_department_in_scope` живёт в `documents/api/views.py` и импортируется отовсюду; фильтр по вычисляемому статусу дела грузит все строки в Python; в репозитории закоммичен `backend/saq-cookies.txt` с сессионной cookie; документооборот (documents/cases/execution/ersop) не покрыт тестами.

### 2.2. `saq-evga-test` — фронт ЭВГА без бэкенда

| Параметр | Значение |
|---|---|
| Назначение | Модуль ЭВГА (электронный внешний государственный аудит): дело → ИРПИ → программа/план/задание/поручение → КК1 → учётная карточка (ЕРСОП) → отчёт, реестр нарушений, доказательства → КК2 → заключение, предписание → КК3 → талон, исполнение, справка о завершении; встречные проверки; возражения и апелляция; третьи лица; требования сведений |
| Стек | React 19.1, TypeScript 5.9, Vite 7.1, pdfmake; **без** роутера, Tailwind, i18n и API. Структура каталогов скопирована с prof-фронта (commit `5bbd21d`, ещё без API) |
| Объём | 25 410 строк TS/TSX в `src/`, 6 222 строки тестов (25 файлов `node --test`, ~210 сценариев на чистых функциях) |
| Хранилище | IndexedDB (`saq-evga-test` / store `state` / key `cases`): при каждом изменении сохраняется **весь массив** `AuditCase[]` через контракт `AuditCaseRepository { load(); save(cases) }` |
| Бизнес-логика | ~6 000 строк чистых функций `src/modules/evga/*.ts` + `src/shared/workflow/approvalRoute.ts` + `src/shared/execution/*`: конечные автоматы документа и дела, маршруты согласования, КК, регистрация ЕРСОП, доставка объекту, требования сведений, апелляции, доп. поручения, третьи лица, сроки по рабочим дням |
| Модель | `AuditCase` (40 полей) → `AuditDocument` (kind, 105 видов: 36 основного дела + 7 встречной проверки + 62 рабочих документа) → `DocumentVersion[]` (11 статусов `DocStatus`, `values` по декларативной схеме `formFor(kind)`, маршруты, подписи, регистрация, доставка, история) |
| Роли | 10 демо-ролей (`auditor, reviewer, approver, quality, kvga, reestr-confirmer, invited-specialist, object, appeal-head, appeal-expert`) + особые аккаунты по id (`approver`, `quality-head`, `commission-chair`…), переключаются в меню; сессия — флаг в `sessionStorage` |
| Имитируется | пользователи и роли, ЕРСОП («Тестовый ответ»), нумерация (`30101-YY-NNNNN` от 52970), ознакомление/подпись объекта в том же браузере, уведомления в памяти, вложения base64 в JSON, ЭЦП |
| Документация | `docs/` — постановки, ответы заказчика (Q01–Q08, Q09–Q20 без ответов), матрицы BPMN-реализации, npa-review, инвентарь Figma/PDF-макетов |
| Что берём | Весь UI и формы — без изменений; чистые функции правил — как **спецификацию** серверных сервисов; тесты — как спецификацию pytest; контракты `shared/workflow` и `shared/execution` — как контракты API |

### 2.3. `n8n_old_project_archive` — старая реализация на другом стеке

| Параметр | Значение |
|---|---|
| Стек | n8n (webhook-воркфлоу с JS-узлами и прямым SQL), PostgreSQL схема `surfk.*`, PostgREST, Keycloak (JWT), RabbitMQ (логирование/события), Camunda 8 / Zeebe (BPMN-процессы документов и дела), внешние сервисы ГБД ЮЛ (SOAP), ЕРСОП |
| Объём | 566 воркфлоу в инстансе n8n, из них 84 отнесены к ЭВГА и выгружены в `n8n_export/workflows/` (10,6 МБ JSON), 72 BPMN-процесса (`bpmn/`), готовые выжимки `analysis/*.txt`, `bpmn_summary/inventory/map.txt` |
| API старой системы | webhooks: `evga/cases` (создание дела с параллельным созданием документов), `evga/documents` (роутер действий), `evga/sub-cases`, `evga/ersop`, `evga/references/*` (≈20 справочников), `evga/audit-object/search`, `evga/document-history`, `evga/documents/verify` (публичная проверка), `keycloak-*`, `activity-log`, `notifications/*`, `appeals/*`, `worktime/*` |
| Данные | `surfk.cases`, `case_statuses`, `case_participants`, `case_bases`, `audit_objects`, `evga_case_documents`, `evga_document_types/statuses/stages/mappings`, `evga_document_versions/approvals/signatures/workflow_history`, `evga_doc_*` (таблицы по видам документов), `case_qc_expert_assignments`, `case_appeal_expert_assignments`, `employees`, `evga_roles/evga_user_roles`, справочники; SQL-функции `get_next_case_sequence`, `get_next_doc_sequence`, `check_sub_case_creation_condition`, `check_document_creation_condition` |
| Процессы | 72 BPMN-процесса: 69 жизненных циклов документов по единому шаблону (`draft → ожидание сообщения TASK_COMPLETE_EVENT → шлюз по actionCode → новый статус + список кнопок availableActions с allowed_roles/requires_signature`), 1 процесс дела `CaseProcessV1` (КК1/КК2/КК3, КВГА, апелляция, назначение эксперта, создание ЗКК), 2 служебных. Бизнес-логики в BPMN нет — каждый шаг лишь вызывает n8n-webhook `workflow-update`. Всего 45 статусов документа (ядро — 6), ~90 кодов действий документа, 18 кодов действий дела, 17 ролей, 3 таймера (`P10D` на возражения, `deadlineDatetime` в требованиях сведений), 1 параллельный шлюз. Два поколения процессов (номерное «2.1/3.9…» и «боевое» M-кодовое) — 12 пар дублей |
| Что берём | Схему данных и коды (M5-IPI … M57, статусы, action codes), форматы номеров, SQL-правила (гейты, нумерация, история), каталог справочников и их источники, модель ролей Keycloak, контракт ЕРСОП/ГБД, каталог уведомлений и журнала. Что **не** берём: сам n8n, Camunda/Zeebe, PostgREST, RabbitMQ — вся логика переезжает в Django-сервисы (подробно — `analysis/n8n-*.md`, `analysis/bpmn-processes.md`) |

---

## 3. Целевая архитектура бэкенда ЭВГА

### 3.1. Стек (ровно как в prof)

| Слой | Технология | Примечание |
|---|---|---|
| Язык / фреймворк | Python 3.13, Django 5.2, DRF 3.16, django-filter, drf-spectacular | версии из `requirements/base.txt` prof |
| БД | PostgreSQL 16, psycopg 3 | JSONB для содержимого форм |
| Файлы | MinIO через django-storages (S3), `core.Attachment` с SHA-256 | локально — `FileSystemStorage` |
| Auth | Собственная сессия `saq_session` (httpOnly cookie) + локальный вход + Keycloak OIDC (PKCE) | `apps/accounts` prof без изменений |
| Планировщик | management-команда `process_deadlines` по cron (compose-сервис `scheduler`) | Celery не вводится |
| Инфраструктура | Dockerfile, `docker/entrypoint.sh` (migrate → collectstatic → seed_* → gunicorn), docker-compose (postgres, minio, minio-init, backend, scheduler), nginx на хосте | `deploy/README.md` prof |
| Качество | pytest-django, ruff (120, `E,F,I,UP,B,DJ`), django-stubs | `pyproject.toml` prof |

### 3.2. Размещение

| Вариант | Плюсы | Минусы | Решение |
|---|---|---|---|
| **B2. Отдельный репозиторий `saq-evga-backend` — копия каркаса prof** | независимая поставка; нет риска сломать prof; команда стартует сразу; слияние потом — перенос папок `apps/evga_*` | вторая сессия/второй `/api/auth/me` до объединения; дублирование `core/accounts/catalogs` до слияния | **принято** |
| B1. Приложения `apps/evga_*` внутри prof-бэкенда (монорепо SAQ) | одна cookie, один Keycloak-клиент, один деплой, общие `core/accounts` без копий | нужны права на коммит в prof, аккуратные аддитивные миграции общих приложений | опция, если команда владеет обоими репозиториями |
| B3. Отдельный проект, общий только Keycloak | полная независимость | ничего не переиспользуется | отклонено |

Правила сосуществования (действуют при любом варианте): общие приложения (`core`, `accounts`, `catalogs`, `subjects`) меняются **только аддитивно** — новые `TextChoices`-значения, новые поля с `null/default`, новые команды, отдельные миграции `00NN_evga_*`; приложения ЭВГА импортируют только из `apps.core`, `apps.accounts`, `apps.catalogs`, `apps.subjects` — из prof-доменов (`documents`, `cases`, `ersop`, `cabinet`, `execution`) **ничего** (нужные строки копируются).

Фронт: отдельный SPA `saq-evga-test` под `/evga/` того же origin (nginx: `location /evga/ { root …; try_files … /evga/index.html; }`, `location /api/ → 127.0.0.1:8000`); в лаунчере prof (`config/saqModules.ts`) ссылка меняется с Vercel на `/evga/cases`. Единый SPA с prof — после перевода ЭВГА на API.

### 3.3. Состав приложений и порядок создания

| # | Приложение | Ответственность | Откуда |
|---|---|---|---|
| 0 | `core` | `TimeStampedModel`, `Attachment` (+виды ЭВГА), `AuditEvent` (+`case`, `action_code`, `source`, `metadata`) и `services/audit.py::record_event`, `NumberSequence/IssuedNumber`, конверт ошибок, пагинация, `TransitionError`/`StaleVersionError` | prof, аддитивно |
| 0 | `accounts` | `User` (+`iin`), сессии, Keycloak, `Role/RolePermission/RoleAssignment`, `HasDomainLevel`, `ScopedQuerySetMixin`, `assert_department_in_scope`; домены `evga_*`, уровень `CONFIRM`; `seed_evga_roles`; синхронизация ролей из Keycloak | prof, аддитивно |
| 0 | `catalogs` | базовые справочники prof + справочники ЭВГА на `BilingualCodeNamedModel` (типы аудита/проверок, инициаторы, основания, органы, ОПФ, уровни риска, типы объектов риска, классификатор нарушений, последствия, меры реагирования, методы выборки, вопросы аудита, показатели, должности, правила сроков, производственный календарь); read-only `CatalogViewSet`; `seed_evga_catalogs`, `seed_evga_calendar` | prof + surfk.* + data/ фронта |
| 0 | `subjects` | объект аудита (`Subject` + `name_kk`, `director`, `legal_form`, `abp`, `risk_level`, `score`), ФЛ для встречной проверки, `AnnualPlanEntry`, валидаторы БИН/ИИН, `services/gbd.py` (stub/gateway), поиск по БИН | prof, адаптировано |
| 1 | `evga_cases` | `AuditCase`, `CaseBasis`, `CaseParticipant`, `CaseCoauthor`, `QualityAssignment`, `CaseCalendarDay`, `CaseAmendment`; сервисы дела, встречных дел, состояния (`quality[3]`, этап, `execution_state`), сроков, прогресса, дополнений; реестр дел с фильтрами, агрегат `workspace` | новое (паттерн `cases` prof) |
| 2 | `evga_documents` | `EvgaDocumentType`, `FormSchema`, `WorkingPaperTemplate`, `AuditDocument`, `DocumentVersion`, `VersionParticipant`, `DocumentSignature`, `DocumentSourceVersion`, `Acknowledgement`, `DocumentDelivery`, `KvgaConfirmation`, `RegistryConfirmation`, `InformationRequestRound`, проекции `Violation` и др.; сервисы: фабрика, черновики, валидация, автоматы (общий, подготовительный, основной, КК, регистрация, доставка, требования), ревизии, права/доступные действия, `commit_version`; реестр действий и `APIView` на действие | новое (паттерн `documents` prof) |
| 3 | `evga_workflow` | `ApprovalRoute/Stage/Participant/Event`, сервисы маршрута (порт `approvalRoute.ts`), инбокс `/api/evga/tasks/` | новое (контракт фронта) |
| 3 | `notifications` | `Notification`, `NotificationRead`, `services/notify.py` с правилами адресатов из `saveDocument`, API unread/read/read-all | новое (по `portal.notifications` старой системы) |
| 4 | `evga_ersop` | `ErsopRegistration` (на версию документа), `ErsopExchange`, адаптеры `stub`/`soap`, опрос статуса | prof `ersop`, адаптировано |
| 4 | `evga_cabinet` | API представителя объекта аудита: документы, ознакомление, решение по отчёту/реестру, ответы на требования, возражения, ответ о принятых мерах, третьи лица | prof `cabinet`, адаптировано |
| 5 | `evga_execution` | проекции `PrescriptionItem`, `Recommendation`, `ResponseMeasure`; статусы исполнения (`claimed/confirmed`), продления, реестр исполнения | prof `execution`, адаптировано |
| 6 | `evga_appeals` | `Appeal`, `AppealArgument`, `ThirdPartyNotice`, `ThirdPartyEvent`; сервисы апелляции и третьих лиц | новое (по `appeals.ts` фронта и `case_appeal_expert_assignments` старой системы) |

### 3.4. Слои и поток данных

```
фронт saq-evga-test ──(EvgaGateway → api.evga.*)──► /api/evga/…  (DRF)
                                                       │
   read:  GenericViewSet + mixins  ──► сериализаторы (форма types.ts фронта, status_label, permissions, available_actions)
   write: APIView на действие ──► реестр ACTIONS ──► services/*.py (порт TS-функций, транзакция, select_for_update дела,
                                                      expected_version → 409, record_event, notify) ──► модели
                                                       │
   интеграции: evga_ersop (stub|soap), subjects/gbd (stub|gateway), signing (stub|ncalayer) — за адаптерами, с логом обмена
   планировщик: manage.py process_deadlines (cron) — просрочки требований, напоминания, опрос ЕРСОП
```

### 3.5. Модель данных (сводка; полные эскизы моделей — `design/design-final.md` §4)

**Дело** (`evga_cases`): `AuditCase` (номер, объект `subjects.Subject`, тип аудита, вид проверки, формат (электронный/ДСП), цель ru/kk, автор, статус `OPEN/CLOSED`, `execution_state`, сроки и период, `parent` для встречных дел, `quality_stage_passed[3]` — кеш, `department` для скоупа), `CaseBasis`, `CaseParticipant` (рабочая группа, лидер), `CaseCoauthor`, `QualityAssignment(case, stage, expert, assigned_by, reason)`, `CaseCalendarDay`, `CaseAmendment`.

**Документ** (`evga_documents`): справочники `EvgaDocumentType` (105 видов: `code` = `kind` фронта, `legacy_code` = M-код, `stage`, `workflow` ∈ `route/preparation/main/quality/direct`, флаги `requires_quality`, `direct_activation`, `repeatable`, `deliverable`, `registrable`, `dependencies`), `FormSchema` (декларативные схемы форм, сид из фронта), `WorkingPaperTemplate` (62 РД); `AuditDocument` (шапка: дело, тип, номер, автор) → `DocumentVersion` (номер версии, `status` из 11 значений, `owner_role/owner`, `values` JSONB, `print_context`, `row_version`, отметки этапов маршрута) + типизированные под-состояния: `VersionParticipant`, `DocumentSignature`, `DocumentSourceVersion`, `Acknowledgement`, `DocumentDelivery`, `KvgaConfirmation`, `RegistryConfirmation`, `InformationRequestRound`; проекции строк JSON `Violation` (+ `PrescriptionItem`, `Recommendation`, `ResponseMeasure` в `evga_execution`).

**Маршрут** (`evga_workflow`): `ApprovalRoute` → `ApprovalStage` → `ApprovalParticipant` (статусы `waiting/pending/approved/signed/returned/rejected/cancelled`) + `ApprovalEvent`; инбокс — вычисляемая проекция.

**Прочее**: `Appeal`, `AppealArgument`, `ThirdPartyNotice/Event` (`evga_appeals`); `ErsopRegistration` (на версию документа, статусы `SENT/PENDING/REGISTERED/RETURNED/REJECTED/ERROR`) + `ErsopExchange` (`evga_ersop`); `Notification` (строка на получателя, `read_at`); `core.AuditEvent` с полями `case`, `action_code`, `source`, `metadata` — единый журнал вместо пяти журналов старой системы.

Почему JSONB, а не таблицы на каждый вид: 105 видов × ≈900 полей описаны декларативно и меняются вместе с НПА; старая система хранила формы через `evga_document_mappings` и динамический SQL по 40 таблицам `evga_doc_*` — самое хрупкое место; prof сам хранит формы отчётности в JSON. Реляционно выносится только то, по чему нужны SQL-выборки и FK-целостность.

**Нумерация** (`core.NumberSequence`, сид `seed_evga_number_sequences`): дело `{org}-{yy}-{seq:05d}` (= `30101-YY-NNNNN`, совпадает у фронта и старой системы), документ `{case}/{seq:02d}`, встречное дело `{parent}/ВП-{seq}`, регистрационные номера ЕРСОП в форматах старой системы `standard` / `with_org` за адаптером, заглушка регистрации `УЧ-{yyyy}-{seq:05d}`.

**Статусы**: `DocumentStatus` — 11 `TextChoices` (`DRAFT`, `QUALITY_REVIEW`, `IN_REVIEW`, `IN_APPROVAL`, `AGREED`, `PENDING_KVGA`, `PENDING_REGISTRY`, `GROUP_SIGNING`, `RETURNED`, `REJECTED`, `ACTIVE`) с подписями = строки `DocStatus` фронта; 45 статусов старой системы отображены в `LEGACY_STATUS_MAP` (в статус, в под-состояние доставки/регистрации/подтверждения/требования или в `DROPPED_LEGACY_STATUSES` с причиной).

### 3.6. Сервисный слой и автоматы (`design/design-final.md` §5)

- **Модули** `services/*.py` — функции с keyword-only аргументами: `factory` (создание документа, `creation_block`, `initial_values`), `drafts` (сохранение черновика с `row_version`), `validation` (порт `fieldError/datesError` и правил по видам), `state_machine` (общий маршрут: `send_to_quality`, `submit`, `approve`, `return`, `reject`, `recall`, `activate`), `revisions` (8 видов новых редакций), `preparation` (цепочка ИРПИ → программа → план/задание → поручение, КВГА, подписи РГ задания), `main` (подписи РГ отчёта, реестр, подтверждение реестра, КК2), `quality` (заключения КК, `quality_passed`, `renew_quality`), `registry` (проекция нарушений, `effective_violations`), `delivery` (направление объекту, ознакомление, решения), `information_requests` (автомат раундов с параметром `now`), `commit` (единая точка побочных эффектов `saveDocument`: пересчёт `quality[3]`, закрытие дела, история, уведомления), `permissions` (`available_actions`, `permissions`), `gates` (аналог `check-docs-status`).
- **Таблицы переходов** объявляются в коде (`workflows/{route,preparation,main,quality,direct}.py`) в формате полей `surfk.evga_status_transitions` (`from_status, action_code, to_status, required_role, assignment_type, requires_signature, requires_comment`); семейства соответствуют BPMN T0–T9; доставка (T2), ЕРСОП (T3) и требования сведений (T7) — ортогональные под-автоматы на связанных таблицах.
- **Реестр действий** `ACTIONS: dict[str, ActionSpec]` (код, сервис, домен/уровни, роли, допустимые `workflow` и статусы, `requires_comment`, сериализатор тела, `legacy_codes`) и функция `apply_action(document, spec, actor, payload, expected_version)` под `transaction.atomic` + `select_for_update` дела; после перехода — `record_event` и `notify`.
- **Автомат дела**: `status` (`OPEN/CLOSED`) и `execution_state` хранятся; этап, `quality[3]`, прогресс, сроки, реестр исполнения, задачи — вычисляются (как `ControlCase.status` в prof).
- **Оптимистичная блокировка**: `expected_version` (номер версии) и `expected_row_version` в каждом действии → `409 stale_version` с текстами фронта («Открыта устаревшая версия документа. Обновите дело»).
- **Таймеры**: `manage.py process_deadlines` (compose-сервис `scheduler`, интервал 5 минут): просрочка требований сведений, автоотказ по встречному требованию, опрос статуса ЕРСОП, напоминания о сроках; автоподпись отчёта по `P10D` и автосоздание документов — за выключенными флагами.

### 3.7. API (`design/design-final.md` §6)

Префиксы: `/api/evga/cases/`, `/api/evga/documents/`, `/api/evga/tasks/`, `/api/evga/quality/`, `/api/evga/appeals/`, `/api/evga/execution/`, `/api/evga/ersop/`, `/api/evga/cabinet/`, `/api/notifications/`, `/api/catalogs/`, `/api/subjects/`, `/api/accounts/users/`, `/api/auth/*` (prof).

| Группа | Эндпоинты (сокращённо) |
|---|---|
| Дела | `GET/POST cases/`, `GET cases/{id}/workspace/` (агрегат: дело + документы + версии + маршруты + история + назначения + апелляция + доступные документы), `PATCH cases/{id}/`, `PUT …/group/`, `POST …/coauthors/`, `PUT …/calendar/`, `POST …/counter-cases/`, `POST …/quality-assignments/`, `GET …/deadlines/`, `GET …/progress/`, `GET …/history/`, `GET …/available-documents/`, `POST …/documents/` (создать по `kind`), `POST …/documents/bulk-working-papers/`, вложения дела |
| Документы | `GET documents/{id}/` (+ `permissions`, `available_actions`), `GET …/versions/{n}/`, `PATCH …/versions/{n}/` (черновик), `DELETE documents/{id}/`, действия: `submit/`, `approve/`, `return/`, `reject/`, `recall/`, `activate/`, `send-to-quality/`, `request-quality/`, `request-approval/`, `revisions/`, `group-signatures/{request,sign,approve}/`, `kvga-confirmation/{request,decide}/`, `registry-confirmation/{request,decide}/`, `quality/{sign,submit-to-head}/`, `ersop/{send,check-status,register}/`, `deliver/{send,acknowledge,respond,sign,object,refuse}/`, `information-request/{send,acknowledge,provide,refuse,review,accept,reject,resend,mark-refused}/`, `apply-amendment/`, `validate/`, `route-candidates/`, `form-links/`, `print-context/`, вложения версии (multipart, `slot` для строк) |
| Маршруты и задачи | `GET tasks/` (инбокс пользователя) |
| КК | `GET quality/`, `GET quality/{case_id}/` |
| Апелляция и третьи лица | `POST appeals/{case}/assign/`, `…/admission/`, `…/admission/notify/`, `PUT …/arguments/`, `POST …/arguments/decide/`; `POST …/third-parties/`, `…/third-parties/none/`, `POST third-parties/{id}/events/` |
| Исполнение | `GET execution/items/` (реестр исполнения по всем делам, фильтры `shared/execution`) |
| Уведомления | `GET notifications/`, `GET …/unread-count/`, `POST …/{id}/read/`, `POST …/mark-all-read/` |
| Кабинет объекта | `GET cabinet/cases/`, `GET cabinet/documents/`, действия объекта (`acknowledge`, `respond`, `sign`, `object`, `refuse`, ответы на требования, `objections`, `response`, третьи лица) — те же `DocumentActionView` в контексте `cabinet` |
| Справочники и служебное | `GET catalogs/{slug}/`, `GET subjects/search/?bin=`, `GET subjects/{bin}/previous-audits/`, `GET accounts/users/?role=&search=`, `GET auth/me` |

Соглашения: ответ действия — полный read-сериализатор документа (или агрегат дела, если действие меняет несколько документов); ошибки — конверт prof `{type, title, status, detail, code}` с кодами `invalid_transition`, `stale_version`, `forbidden`, `comment_required`; списки — `{count, next, previous, results}`, `page_size ≤ 200`; фильтры реестра дел — порт `caseSearch.ts` (`number, bin, name, auditType, checkType, electronic, status, author, dateFrom/To`) по колонкам, не Python-проходом. Покрытие всех ~75 действий UI и ~60 мутаций чистых функций фронта проверено построчно (`design/design-final.md` §6.15).

### 3.8. Роли и права (`design/design-final.md` §7)

- **Механизм prof без изменений**: `Role` → `RolePermission(domain, level)` → `RoleAssignment(user, department, valid_from/to)`, `HasDomainLevel`, `ScopedQuerySetMixin`; аддитивно добавляются домены `evga_cases`, `evga_quality`, `evga_registry`, `evga_appeals`, `evga_execution`, `evga_cabinet`, `evga_admin`, `dsp` и уровень `CONFIRM`.
- **Роли** (`seed_evga_roles`): `evga-auditor`, `evga-invited-specialist`, `evga-reviewer`, `evga-approver`, `evga-quality`, `evga-qc-head`, `evga-kvga`, `evga-reestr-confirmer`, `evga-kvga-kk-head`, `evga-kvga-kk-expert`, `evga-appeal-head`, `evga-appeal-expert`, `evga-appeal-commission-member`, `evga-appeal-commission-chair`, `observer`, `evga-admin`; представитель объекта — `User.is_subject_representative` + `subject`.
- **Маппинг на Keycloak старой системы** (`KEYCLOAK_ROLE_MAP`): `auditor → evga-auditor`, **`approver → evga-reviewer`**, **`confirmer → evga-approver`** (инверсия терминов зафиксирована в BPMN: старый `approver` «Согласовать», старый `confirmer` «Утвердить»), `qc_expert → evga-quality`, `qc_head → evga-qc-head`, `kvga_confirmer → evga-kvga`, `appeal_head/appeal_expert`, `invited_specialist`, `reader_ga → observer`, `admin_evga → evga-admin`; синхронизация из `realm_access.roles` при входе — за флагом `KEYCLOAK_SYNC_ROLES` (порт `User Login Sync`).
- **Объектные права** (кто именно: автор/соавтор, участник маршрута, назначенный эксперт/подтверждающий, участник рабочей группы, представитель объекта) — проверяются в сервисах по таблицам назначений, как `canDecideDocument` во фронте и `get_available_actions` в старой системе (роль ∧ назначение).
- Особые аккаунты фронта (`approver`, `quality-head`, `commission-chair`, `commission-1/2`) становятся ролями; адаптер `accountFromUser` восстанавливает форму `Account` для существующего кода UI.

### 3.9. Интеграции (`design/design-final.md` §8)

| Система | Как в старой системе | Как делаем |
|---|---|---|
| ЕРСОП / КПСиСУ | n8n `EVGA ERSOP Workflow` → `ERSOP - Build and Send` → SOAP `SI_SUR2ERSOP_RequestSubjectAsync` (ns `http://minfin.kz/ERSOP`), сообщения `M_TYPE_STARTED / PROLONGED / PERIOD_CHANGED / RESUMED / SUSPENDED / STOPED / EXECUTORS_CHANGED / FINISHED`, ответы в `acc_100.rspns_msg_rsp`, `confirmstatusid 1/2/3` | `ErsopRegistration` на версию + `ErsopExchange`; адаптеры `stub` (как prof `fake_register_package`, стенд-эндпоинт «учесть регистрацию/возврат») и `soap` (порт n8n) за `ERSOP_ADAPTER`; готовность — `registration_block(version)` |
| ГБД ЮЛ / ФЛ | `Service GDBJL` (SOAP `SI_GBD_JL_PIWS_OS getJurInfoByBin` / REST `camel-gateway … gbdul`) | `subjects/services/gbd.py`: `lookup_legal_entity(bin)`, `lookup_person(iin)`; адаптеры `stub` / `gateway` / `shep` |
| Keycloak | realm `efc`, `preferred_username` = ИИН, роли в `realm_access.roles`, Admin API | prof OIDC + PKCE как есть; `User.iin` из claims; синхронизация ролей за флагом; Admin API не переносится |
| ЭЦП | подпись хранилась текстом без проверки | `DocumentSignature.provider ∈ {stub, ncalayer}`, `document_hash`, интерфейс `verify_cms`; `EVGA_SIGNATURE_REQUIRED=false` до промышленного этапа |
| Уведомления | `portal.notifications` + WebSocket портала | `Notification` in-app + polling; e-mail/WS позже |
| ВАП, АИС ОИП, ИС ПО, ЕРАП | отдельные отправки | документы активируются без обмена; при необходимости — тот же паттерн `*Exchange` |
| PDF | n8n отправлял `fileBase64` | клиентский pdfmake на первом этапе; серверный WeasyPrint по шаблонам `ReferencePrintForm.tsx` — итерация 11 (нужен для ЕРСОП, ЭЦП, публичной верификации) |

### 3.10. Справочники и seed-команды (`design/design-final.md` §9)

Порядок в `docker/entrypoint.sh`: `seed_catalogs` (prof) → `seed_evga_catalogs` (≈20 справочников: типы аудита `15/16`, виды проверок, основания, инициаторы, ОПФ, уровни риска, типы объектов риска, классификатор нарушений, последствия, статусы устранения, показатели, методы выборки, вопросы аудита, органы `30101` + ДВГА, должности, НПА) → `seed_evga_calendar` → `seed_evga_deadline_rules` → `seed_evga_roles` → `seed_evga_number_sequences` → `seed_evga_document_types` (105 видов + legacy-only с `is_implemented=False`) → `seed_evga_form_schemas` (86 схем из `analysis/artifacts/evga-forms-dump.json`) → `seed_evga_working_papers` (62 РД) → стендовые `seed_evga_audit_objects`, `seed_evga_users`, `seed_evga_demo_cases` (сценарии `demoScenario.ts` через сервисы = интеграционный тест). Данные сидов лежат в `backend/data/evga/*.json` и генерируются скриптом фронта `scripts/export-reference-data.mts`, чтобы фронт и бэкенд не расходились; коды и полные списки — из `surfk.*` после получения дампа старой БД.

### 3.11. Что в старой системе есть, а в объём не входит

Административное производство (M38–M57, подчинённое дело `admin_violation`), акт осмотра `M55`, приказы (`evga_doc_prikaz`), маршрут «КК КВГА» (`qc_route`), автосоздание документов при создании дела, автоподпись отчёта по таймеру, автозакрытие дела при возврате КВГА, публичная верификация документа, Keycloak Admin API, портальные модули (worktime, documents, RabbitMQ-лог). Типы документов сидируются с `is_implemented=False`, коды сохранены для совместимости данных.

### 3.12. Чек-лист «как завести новое приложение ЭВГА в стиле prof»

Составлен по фактическому коду `saq-prof-control-demo/backend` (подробный разбор — `analysis/prof-backend-style.md`, §12). Применяется дословно к каждому приложению из §3.3.

1. **Структура.** `apps/<name>/` с `__init__.py`, `apps.py` (`name="apps.<name>"`, русский `verbose_name`), `models.py`, `admin.py`, `api/{__init__,views,serializers,urls,filters}.py`, `services/__init__.py` + по модулю на агрегат, `management/commands/seed_<name>.py` (если есть справочники), `tests/__init__.py`, `migrations/`.
2. **Регистрация.** В `INSTALLED_APPS` — в порядке зависимостей; в `config/urls.py` — `path("api/evga/<name>/", include("apps.<name>.api.urls"))`.
3. **Модели.** Наследовать `core.TimeStampedModel` (UUID pk, `created_at/updated_at/created_by`); статусы — `models.TextChoices` с UPPER_CASE-кодом и русской подписью; FK на акторов — `SET_NULL, related_name="+"`; на справочники — `PROTECT`; `UniqueConstraint(name="<app>_<model>_natural_key")`; `__str__` через ` · `; `Meta.ordering`.
4. **Сервисы.** Только функции-модули: `create_/submit_/approve_/return_/reject_/activate_/register_/deliver_…(obj, *, actor, **fields)`; первые строки — проверка типа и допустимого статуса с `raise DocumentTransitionError("русский текст, сейчас: {status}")`; `@transaction.atomic` при нескольких записях; `select_for_update` на дело при гонках; `save(update_fields=[..., "updated_at"])`; `IntegrityError` → доменная ошибка; после перехода — `record_event(...)` (дополнение к эталону: в prof `AuditEvent` не пишется).
5. **Нумерация.** `define_sequence` в seed + `issue_number(key=..., target=obj, scope=..., context={...})` — идемпотентно, без `COUNT(*)+1`.
6. **Вложения.** `attach_<owner>_file(obj, *, kind, uploaded_file, uploaded_by)` через `core.Attachment` (SHA-256, MinIO); скачивание только через `FileResponse` со своей проверкой прав; ссылки — `reverse(<url-name>)`.
7. **API.** Read — `GenericViewSet` + mixins с `select_related/prefetch_related`, `filterset_class`, `search_fields`, `ordering_fields`, `required_domain`, `required_levels` (`@property` по `self.action`), `get_permissions → [IsAuthenticated(), HasDomainLevel()]`, `ScopedQuerySetMixin` + `scope_department_field`. Действия — `APIView` на каждый переход: `get_object_or_404 → assert_department_in_scope → RequestSerializer → try сервис except TransitionError → ValidationError({"detail"}) → Response(ReadSerializer(obj).data[, 201])`; `@extend_schema(request=, responses=, description=)` на каждый метод. `@action` в prof не используется.
8. **Сериализаторы.** `XxxSerializer` (read, `read_only_fields = fields`, `*_name`, `status_label`), `CreateXxxSerializer`/`SaveXxxSerializer` (request, `serializers.Serializer`, докстринг «Request body of…»), `XxxUpdateSerializer` (PATCH, минимальный `fields`).
9. **Admin.** `list_display/list_filter/search_fields/list_select_related`, inline для детей, `readonly_fields` для системных полей.
10. **Тесты.** `apps/<name>/tests/test_<тема>.py`, `pytestmark = pytest.mark.django_db`, хелперы `_user_with_<domain>_role(scope, level, department)`, `APIClient().force_authenticate`; кейсы: happy path, неверный статус → 400 с `detail`, чужой department → 403/404, 401 без cookie, 409 stale, идемпотентность, конкурентность для номеров (`threading` + `django_db(transaction=True)`).
11. **Seed.** Константы данных → `update_or_create` под `@transaction.atomic` → `self.style.SUCCESS(f"...: {n}")`; команду добавить в `docker/entrypoint.sh` и README; двойной вызов идемпотентен.
12. **Качество.** Ruff 120 символов, `select E,F,I,UP,B,DJ`; аннотации типов в сигнатурах; докстринги по-русски и по делу; сообщения об ошибках — на русском (в prof они смешаны — не повторять).

Что из эталона **не** копировать: приватный helper `_assert_department_in_scope` внутри `documents/api/views.py` (перенести в `accounts/querysets.py`), фильтр по вычисляемому статусу в Python (`CaseRegistryFilter.filter_status`), дублирование `_READ_LEVELS`/`user_display_name`/download-view по приложениям (вынести в `core`), закоммиченный `backend/saq-cookies.txt`, устаревшие флаги `DocumentType.is_implemented`.

---

## 4. Что переиспользуем и откуда

Легенда: **как есть** — копируем без изменений; **адаптировать** — сохраняем смысл и структуру, меняем детали под ЭВГА; **переписать** — берём только требования/образец; **не брать**.

### 4.1. Из бэкенда prof (`saq-prof-control-demo/backend`)

| Приложение / модуль prof | Вердикт | Что именно и как использовать в ЭВГА |
|---|---|---|
| `config/` (settings base/local/production, urls, wsgi/asgi), `Dockerfile`, `docker/entrypoint.sh`, `docker-compose.yml`, `deploy/README.md`, `pyproject.toml` (pytest, ruff), `requirements/` | **как есть** | Переименовать БД/заголовок Swagger, заменить список seed-команд в `entrypoint.sh`; добавить `saq-cookies.txt` в `.gitignore` |
| `apps/core`: `TimeStampedModel`, `Attachment`/`AttachmentKind`, `AuditEvent`/`AuditAction`, `NumberSequence`/`IssuedNumber`, `services/numbering.py`, `services/files.py`, `exceptions.py`, `middleware.py`, `views.py`, `pagination.py` | **как есть** + расширить | Добавить виды вложений ЭВГА (`document_file`, `basis_document`, `evidence_file`, `object_response`, `refusal_proof`, `appeal_argument`, `third_party_notice`, `quality_material`, `signed_pdf`), коды действий журнала (`submit`, `return`, `reject`, `recall`, `activate`, `send_to_quality`, `quality_decision`, `kvga_confirm`, `registry_confirm`, `register`, `deliver`, `object_decision`, `assign`, `new_version`) и поле `source` (`user/system/ersop/timer`); завести `core/services/audit.py::record_event()` и **реально писать журнал из каждого перехода** (в prof модель есть, но не используется); вынести сюда `TransitionError`, `_READ_LEVELS`, `user_display_name` |
| `apps/accounts`: `User`, `AuthProvider`, `AuthSession`, `OidcAuthRequest`, `FederatedIdentity`, `authentication.SessionCookieAuthentication`, `services/keycloak.py` (OIDC + PKCE), `services/sessions.py`, local/keycloak views, `MeSerializer`, `schema.py` | **как есть** | Добавить `User.iin` (из `preferred_username` Keycloak, валидатор ИИН), синхронизацию `RoleAssignment` из `realm_access.roles` при провижининге (`settings.KEYCLOAK_ROLE_MAP`) |
| `apps/accounts`: `Role`, `RolePermission`, `RoleAssignment`, `HasDomainLevel`, `ScopedQuerySetMixin`, `seed_roles` | **адаптировать** | Домены `PermissionDomain` → `cases, quality, registry, appeals, execution, cabinet, admin, dsp`; уровни оставить; роли — 10 ролей фронта + `qc-head`, `kvga-kk-head/expert`, `appeal-commission-chair/member`, `observer`, `evga-admin` (см. §3.8); `_assert_department_in_scope` перенести в `accounts/querysets.py`; объектные права (автор/соавтор, участник маршрута, назначенный эксперт) — в сервисах |
| `apps/catalogs`: `Region`, `Department`, `GovernmentBody`, `NormativeAct`, `CodeNamedModel`/`OrderedCodeNamedModel`, `seed_catalogs` | **адаптировать** | Базовые справочники и шаблон seed оставить; добавить справочники ЭВГА (§3.10) с `name_ru/name_kk` и `ersop_code`; добавить read-only API справочников (в prof его нет — фронт держит копии) |
| `apps/subjects`: `Subject`, `SubjectPerson`, `validators.py` (БИН/ИИН с контрольной суммой), `SubjectViewSet`, тесты | **адаптировать** | Основа для `AuditObject`: + `name_kk`, `director`, `legal_form` (ОПФ), `abp`, `risk_level`, `score`; ФЛ для встречной проверки; upsert по БИН (как в n8n `Insert Audit Object`) |
| `apps/documents`: `DocumentType` (сидируемый справочник с флагами), `Acknowledgement` (portal/manual), `services/attachments.py`, `services/exceptions.py`, шаблон transition-функций, `Create*View`/`Create*Serializer`, реестр `DETAILS_SERIALIZERS`, `document_status_label` | **адаптировать (паттерн)** / **переписать (модели)** | Паттерн «функция-сервис на переход + `APIView` на действие + словарь диспетчеризации по типу» сохранить полностью; модели заменить на `AuditDocument` + `DocumentVersion` (версии, повторяемые виды, `values` JSONB) — `ControlDocument` с `UniqueConstraint(list_entry, document_type)` не подходит |
| `apps/cases`: `ControlCase.status` как `@property` через `compute_status`, `case.document(code)`, `CaseRegistryViewSet` + `CaseRegistryFilter`, `CaseWorkspaceView` | **переписать (паттерн сохранить)** | Дело ПК привязано к строке полугодового перечня; для `AuditCase` — новая модель, но идеи вычисляемого состояния (`quality[]`, `executionState`), реестра с фильтрами и агрегатного `workspace`-эндпоинта берём |
| `apps/execution`: `PrescriptionItem` (вычисляемые `status`, `effective_due_date`), `ExecutionSubmission/Item`, `ExecutionDecision` (RELEASE/EXTEND), сервисы `register_submission`, `decide_item` | **адаптировать** | Почти 1:1 совпадает с контрактом `shared/execution` фронта (`claimedStatus/confirmedStatus`, продления); переименовать статусы под ЭВГА, связать с версией документа `response` |
| `apps/ersop`: `ErsopPackage/Item/Exchange`, `services/stub_exchange.py`, цепочка `build → submit → register`, API `/packages/…/submit|register` | **адаптировать (шаблон интеграции)** | В ЭВГА регистрируется версия документа (`account`, `additional`, `notification`, встречные), а не пакет; `ErsopExchange` (лог обмена с JSON-payload) и заглушка без сети — образец для ЕРСОП, ГБД, ЭЦП; счётчик `package_2_approved_steps` заменить нормальным маршрутом |
| `apps/cabinet`: `IsSubjectRepresentative`, `_assert_subject_owns`, `CabinetDocumentViewSet`, `CabinetAcknowledgeView`, `CabinetRegisterSubmissionView`, download-view с контекстом `{cabinet: True}` | **адаптировать** | Кабинет представителя объекта аудита (роль `object`): ознакомление, подпись/возражение/отказ по отчёту и реестру, ответы на требования сведений, возражения, ответ о принятых мерах, третьи лица |
| `apps/checklists`, `apps/reporting`, `apps/risk`, `apps/semiannual` | **не брать** | Специфика ПК. Заимствуем только приёмы: `assert_*_editable`, дробление нарушения на пункты (прообраз реестра нарушений), валидация структуры до записи (`DfoExtractValidationError`), модель версии перечня как образец `DocumentVersion`, `trigger_*` с `select_for_update` |
| Тесты `apps/core/tests`, `apps/accounts/tests`, `apps/subjects/tests` (`_user_with_cases_role`, RBAC через `APIClient`, конкурентность `threading`) | **как есть** | Шаблон для тестов каждого нового приложения; сервисы переходов покрыть тестами (в prof документооборот не покрыт) |
| Фронт prof: `src/api/client.ts`, `auth/AuthContext.tsx`, `App.tsx` (проверка сессии, тосты), `LoginPage.tsx`, `vite.config.ts` (proxy), `.env.example`, паттерн адаптеров DTO → UI (`profControlAdapter.ts`), Paraglide | **как есть / адаптировать** | Каркас интеграции фронта ЭВГА с API (см. §5) |

### 4.2. Из старой n8n-системы (`n8n_old_project_archive/n8n_export`)

| Элемент старой системы | Вердикт | Как используем |
|---|---|---|
| Схема `surfk.cases`, `case_statuses`, `case_participants`, `case_bases`, `case_base_attachments`, `case_status_history`, `case_qc_expert_assignments`, `case_appeal_expert_assignments`, `audit_objects`, `annual_plans`/`plan_objects` | **адаптировать** | Состав колонок → Django-модели `AuditCase`, `CaseParticipant`, `CaseBasis`, `QualityAssignment`, `AppealExpertAssignment`, `AuditObject`, `AnnualPlanEntry`; дубли `author_id/author_iin/author_keycloak_id` → один FK на `User`; `parent_id/sub_case_type` → `AuditCase.parent` + `kind` (`MAIN`, `COUNTER_CONTROL`, `ADMIN_VIOLATION`) |
| `evga_document_types` (флаги `requires_approval/confirmation/kvga`, `requires_signature`, `sends_to_audit_object`, `allow_multiple`, `is_manually_creatable`, `is_child_only`, `audit_type_codes`, `creator_roles`, `reg_number_format/prefix`, `supports_version`), `evga_document_stages`, `evga_document_statuses`, `evga_document_action_types` | **как есть (коды и флаги)** | Сид `EvgaDocumentType` (105 видов: `kind` фронта + `legacy_code` M-код + флаги), `DocumentStatus` (11 кодов фронта с русскими подписями), `AuditAction` (коды действий) |
| `evga_case_documents` (шапка), `evga_document_versions` (снимок), `evga_document_approvals`, `evga_document_signatures`, `evga_document_workflow_history`, `evga_audit_log` | **адаптировать** | `AuditDocument` + `DocumentVersion` + `ApprovalRoute/Participant/Event` + `DocumentSignature` + единый `core.AuditEvent` (вместо четырёх журналов) |
| `evga_document_mappings` (`root_table`, `fields_mapping`, `subtables_mapping`, `form_schema` JSONB) и динамический SQL в `evga_doc_*` | **переписать** | Подтверждает выбор «содержимое формы = JSON по декларативной схеме»; таблицы `evga_doc_*` — источник колонок для **проекций** (`Violation`, `AuditQuestion`, `RiskObject`, `PrescriptionItem`, `ResponseMeasure`, вопросы требования сведений) |
| Нумерация: `get_next_case_sequence(year)`, `get_next_doc_sequence('standard' \| 'with_org' \| 'PRIKAZ', year)`, форматы `<орган>-<YY>-<00000>`, `YYYY/MM/DD – 00000`, `<prefix>-<орган>-<YY>-<000000>/<хвост дела>[_1]`, `[ВП-]…` для подчинённых дел | **как есть (форматы)**, **адаптировать (механизм)** | Шаблоны в `seed_number_sequences`; механизм — `core.NumberSequence` + `issue_number` (без `COUNT(*)+1`); выбор между форматом старой системы и фронта (`30101-YY-NNNNN`, `{дело}/NN`) — вопрос заказчику, по умолчанию — формат старой системы для преемственности с ЕРСОП |
| Создание дела `Create Case v4` (валидация, upsert объекта по БИН, ≥1 участник и ровно один лидер, автосоздание 5 подготовительных документов) | **адаптировать** | Один транзакционный сервис `create_case()`; автосоздание документов — **отключено** по решению заказчика Q08 (документы создаются вручную из меню «Создать»), оставить флагом |
| Подчинённые дела (`sub-cases`): гейт `check_sub_case_creation_condition`, наследование объекта и автора, первый документ `M43-VK-POR` | **адаптировать** | `create_counter_case()` — совпадает с фронтом (`parentCaseId`, `counter-*`); административное производство (`admin_violation`, M38–M57) — отдельный этап, во фронте нет |
| Роутер действий `evga/documents` (59 action codes: `submit/approve/reject/return/send_to_confirmation/confirm/direct_confirm/activate/register/send_to_kvga/kvga_confirm/kvga_return/send_to_reestr_confirmer/reestr_confirm/send_to_work_group/sign_work_group/send_to_audit_object/acknowledge/submit_objection/send_to_ersop/check_status/…`) | **адаптировать** | Каждый код → функция-сервис + `APIView` в стиле prof; таблица переходов `ALLOWED_TRANSITIONS[(type_group, from_status, action)]`; фильтр доступных действий `get_available_actions` (роль ∧ назначение ∧ `assignment_type`) → серверный `available_actions(version, user)` |
| `check-docs-status` (гейты «все документы типов X в статусе Y»), `Get Available Document Types` (правила создания), `Get Case Documents` (матрица типов × документов) | **как есть (как сервисы)** | `documents/services/gates.py`, `creation.py::available_types(case, user)`, агрегат `workspace` |
| ЕРСОП: `EVGA ERSOP Workflow` (`send_to_ersop`, `check_status`), `ERSOP - Build and Send from Document` (состав `message.started{…}`), `SEND_REQ_TO_ERSOP` (SOAP `SI_SUR2ERSOP_RequestSubjectAsync`, типы `Started/Prolonged/PeriodChanged/Resumed/Suspended/Stoped/ExecutorChanged/Finished`), `acc_100.rspns_msg_rsp`, коды `ersop_accepted/registered/rejected/revision/error` | **адаптировать** | Единственный реальный контракт ЕРСОП: `ExternalRegistration` на версию документа + `ExternalExchange` + адаптеры `stub` (как prof) и `soap` (порт n8n); статусы фронта `Отправлена/Зарегистрирована/Возвращена` |
| Справочники (18 воркфлоу `EVGA: <Name> - Get` → таблицы `audit_types`, `inspection_types`, `check_initiators`, `control_reasons_types`, `evga_control_spheres`, `controlling_bodies`/`d_controlling_orgs`, `risk_levels`, `risk_object_types`, `offense_type` (дерево), `response_measures`, `sampling_methods`, `organizational_legal_forms`, `organ_reg_checks`, `subj_sched_insp`, `audit_results`, `evga_audit_questions`, `dictionaries`, `employees`) | **как есть (данные)** | Модели `catalogs` с `name_ru/name_kk` + `seed_catalogs`; данные экспортировать из старой БД (`pg_dump` схемы `surfk` — нужен доступ) |
| Keycloak: realm `efc`, `preferred_username` = ИИН, 19 назначаемых ролей подсистемы ЭВГА (`SUBSYSTEM_SCOPE_CONFIG.evga`), `User Login Sync` (upsert пользователя по ИИН, роли из `realm_access.roles`) | **адаптировать** | Маппинг Keycloak-ролей → `Role` prof (важно: старый `approver` = фронтовый `reviewer`, старый `confirmer` = фронтовый `approver`); синхронизация ролей при входе |
| Уведомления `portal.notifications` (`title, message, event_type, meta_data, status UNREAD/READ, channel WEB, read_at`), API unread / mark-read / mark-all-read | **адаптировать** | `apps/notifications.Notification` + сервис `notify()` с правилами адресатов из `saveDocument` фронта; e-mail/WebSocket — позже |
| Журнал `surfk.evga_audit_log` (`entity_type`, `action_code`, `status_code`, `field_changes`, `performed_by_iin/name`, `source user/zeebe/system/ersop/timer`), ИБ-лог RabbitMQ | **адаптировать** | Состав полей → расширение `core.AuditEvent` (`source`, `metadata`, `actor_iin/name`); RabbitMQ не нужен |
| Апелляции: `case_appeal_expert_assignments`, `M23-RVO` (`evga_doc_objection_appeal_result` + `oar_violations`) | **адаптировать** | Фронт `appeals.ts` богаче (принятие/отказ комиссии, обоснования аудитора, подпись руководителя) — модель по фронту, коды по старой системе |
| ГБД ЮЛ (`Service GDBJL`: SOAP `SI_GBD_JL_PIWS_OS` / REST `camel-gateway … gbdul`, нормализованный ответ `{bin, regStatus, fullName{ru,kz}, orgForm, head{iin,fullName}, address, founders[]}`) | **адаптировать** | `subjects/services/gbd.py` с адаптерами `stub`/`soap`, эндпоинт поиска по БИН для `ObjectLookup` |
| Публичная верификация документа (`evga/documents/verify`) | **адаптировать** | По непредсказуемому токену/хешу, не по id; требует серверного PDF |
| n8n как таковой, Zeebe-хаб (`evga/zeebe`, `workflow-update`, `case-workflow-update`), `$vars.*_WORKFLOW_ID`-роутинг, `workflow_state.available_actions` как источник правды, SQL с интерполяцией параметров, JWT без проверки подписи, PostgREST, RabbitMQ, крипто-сервис портала, портальные воркфлоу (`documents`, `worktime`, `Keycloak IB Admins`), дубли/выключенные копии, `Info Request API (deprecated)` | **не брать** | Логика переезжает в сервисы Django; из n8n берём только требования |

### 4.3. Из BPMN-процессов Camunda/Zeebe (`n8n_old_project_archive/bpmn`)

| Элемент | Вердикт | Как используем |
|---|---|---|
| Единый шаблон жизненного цикла документа (семейства T0–T9: активация, согласование+утверждение, ознакомление ОА, ЕРСОП, КВГА/реестр, рабочая группа, ЗКК, требование с таймером, документы ОА, апелляция) | **как есть (как спецификация)** | Таблицы переходов сервисного слоя; сверены с автоматами фронта (`documentStateMachine.ts`, `preparationWorkflow.ts`, `mainWorkflow.ts`) — расхождения решаются в пользу фронта и ответов заказчика (Q05–Q08) |
| Каталог `availableActions` (`code`, `name_ru/name_kz`, `icon`, `color`, `requires_signature`, `requires_comment`, `allowed_roles`, `assignment_type`) | **адаптировать** | Справочник действий (сид) и серверный расчёт доступных действий на версию для конкретного пользователя (`GET …/permissions/` или поле `available_actions` в ответе) — фронт сейчас считает это сам |
| Процесс дела `CaseProcessV1` (КК1/КК2/КК3, КК КВГА, апелляция, `assign_qc_expert*`, `create_qc_conclusion*`, `ready_send_to_qc*`, `resubmit_to_qc_stage2`) | **адаптировать** | Вычисляемое состояние дела + сервисы `quality.py`/`appeals.py`; `qc_route` («КК КВГА» vs КК2) — правило не передано, по умолчанию не реализуем |
| Таймеры: `P10D` на возражения объекта (автоподпись отчёта `signed_automatically`), `deadlineDatetime` требований сведений (`overdue`/автоотказ для встречного) | **адаптировать** | Один планировщик дедлайнов (management command по cron/CronJob или celery beat); автоподпись отчёта по таймеру — **не переносить** (решение команды в `bpmn-implementation`), просрочку требований — переносить |
| Гейты через `check-docs-status`, `check-audit-type`, `cases/bases` (`qc_route`), автосоздание `M18/M19/M20/M25` | **частично** | Гейты — как сервисы; автосоздание документов — не переносить (Q08) |
| Сам Camunda/Zeebe, коннекторы `io.camunda:http-json`, сообщения `TASK_COMPLETE_EVENT`, `zeebe_process_id/instance_id` | **не брать** | В BPMN нет бизнес-логики (каждый шаг — HTTP-вызов n8n), процессы последовательные (1 параллельный шлюз на 72 файла), «продвинутый» BPMN не используется. Явные автоматы в Django проще, тестируемее и не требуют ещё одного контура эксплуатации |
| Два поколения процессов (номерное «2.1/3.9…» и M-кодовое) — 12 пар дублей | **брать M-поколение** | Оно связано с делом и соседними документами триггерами; из номерного — отдельные более чистые детали (роль `oa_confirmer`, трёхшаговая доставка ОА в 3.2, назначение эксперта в 3.11) |

### 4.4. Из фронта ЭВГА (`saq-evga-test`)

| Элемент фронта | Вердикт | Как используем |
|---|---|---|
| `src/modules/evga/*.ts`: `documentStateMachine`, `workflow` (`creationBlock`, `dependencies`, `qualityPassed`, `saveDocument`, `performRegistration`, `deliverDocument`, `completionBlock`), `preparationWorkflow`, `mainWorkflow`, `qualityAssignment`, `appeals`, `amendments`, `thirdParties`, `informationRequests`, `executionItems/Progress/Decision`, `deadlines`, `caseAccess`, `caseRules`, `reviewParticipants`, `approvalTasks`, `violationRegistry`, `forms/validation`, `irpiValidation`, `documentFactory`, `printContext`, `history` | **перенести на сервер (порт 1:1 в Python)** | Это готовая спецификация сервисного слоя с русскими текстами ошибок; на клиенте функции остаются только как UI-подсказки (источник истины — сервер) |
| `src/shared/workflow/approvalRoute.ts` (+ README, 27 тестов) и `src/shared/execution/execution.ts` (+ README, 16 тестов) | **как есть (контракт)** | Модели `ApprovalRoute/Stage/Participant/Event` и read-модель `ExecutionItem`; UI-компоненты `ApprovalInbox`, `ApprovalRouteEditor`, `ExecutionRegistry` получают данные с сервера |
| `src/types.ts` | **основа сериализаторов** | Форма `AuditCase/AuditDocument/DocumentVersion` сохраняется в ответах API через адаптер, чтобы не переписывать 25 тыс. строк форм |
| `src/data/documentMatrix.ts` (36+7 видов), `data/workingPapers.json` (62 РД), `forms/documentForms.ts` + `referenceForms.ts` + `schema.ts` (42 схемы форм), `data/irpiForm.ts` | **как есть (данные для seed)** | Экспорт в JSON → `seed_document_types`, `seed_form_schemas`, `seed_working_papers`; схемы форм остаются и на фронте для рендера |
| `data/demoData.ts` (`basisOptions`, `initiatorOptions`, `catalogue`, `objectRegistry`, `people`) | **адаптировать** | Данные для `seed_catalogs`/`seed_evga_demo`; аккаунты → `seed_evga_users` |
| `tests/*.test.ts` (25 файлов, ~218 сценариев) | **как есть (спецификация pytest)** | Каждый сценарий → тест сервисного слоя/API |
| `demoScenario.ts`, `financialDemoValues.ts` | **адаптировать** | Генераторы используют настоящие переходы → фикстуры «дело на шаге N» для интеграционных тестов и `seed_evga_demo_cases` |
| `services/indexedDbCaseRepository.ts`, `useDemoSession.ts`, `config.ts: DEMO_USER`, переключатель ролей в `AppShell`, base64-вложения (`utils/files.ts`), клиентская нумерация (`nextCaseNumber`, `documentSequence`), `vercel.json` | **удалить после миграции** | Заменяются API, `GET /api/auth/me`, `Attachment` + MinIO, серверной нумерацией, nginx-деплоем как в prof |
| `pdfExport.ts` (pdfmake), печатные формы `ReferencePrintForm.tsx`/`QualityPrintForm.tsx`/`DocumentPrintForm.tsx` | **оставить на клиенте** на первом этапе | Серверный PDF нужен только для ЭЦП, ЕРСОП (`fileBase64`) и публичной верификации — отдельная итерация (шаблоны по разметке `ReferencePrintForm`) |

---

## 5. Перевод фронта ЭВГА на серверный API (по образцу prof)

Принцип: **UI и формы не переписываем**. Меняется только слой данных: вместо «посчитать в браузере → сохранить весь массив дел в IndexedDB» — «вызвать действие на сервере → перечитать агрегат дела». Форма объектов `AuditCase / AuditDocument / DocumentVersion` из `src/types.ts` сохраняется на выходе адаптера, поэтому 30 компонентов форм и печати не трогаются.

### 5.1. Целевая архитектура фронта

```
main.tsx ─ ErrorBoundary ─ App.tsx
   ├─ checkSession(): api.auth.maybeMe()        → LoginPage (email/пароль | кнопка Keycloak)
   └─ BrowserRouter ─ AuthProvider{user, logout}
        └─ "/evga/*" → EvgaModule (lazy)
              ├─ useEvgaRouting()                (react-router вместо hash; хелперы utils/navigation.ts остаются)
              ├─ gateway = useEvgaGateway()      (apiGateway | localGateway — переключается VITE_EVGA_DATA_MODE)
              ├─ hooks: useCaseList(query), useCase(id), useTasks(), useNotifications(), useExecutionItems()
              └─ pages/* и modules/evga/components/* — получают AuditCase той же формы через evgaAdapter
src/api/client.ts      ← копия prof (request/ApiError/notifyError/query) + пространства api.auth.*, api.evga.*, api.catalogs.*
src/api/types.ts       ← snake_case DTO бэкенда ЭВГА (Paginated<T>, User, EvgaCase, EvgaDocument, EvgaDocumentVersion, Attachment, ApprovalRouteDto, …)
src/api/evgaAdapter.ts ← toAuditCase(dto), toAuditDocument(dto), toUpload(attachment), accountFromUser(user)
```

### 5.2. Контракт `EvgaGateway` вместо `AuditCaseRepository`

Вариант «`ApiCaseRepository` с тем же `load()/save(cases)`» **отвергается**: сохранение всего массива означает, что клиент — источник истины, сервер не может ни авторизовать действие, ни разрешить конфликт двух пользователей, ни принять файл потоком. У prof каждое действие — отдельный endpoint, состояние перечитывается.

```ts
export interface EvgaGateway {
  listCases(params: { page?, pageSize?, search?, auditType?, checkType?, electronic?, status?, author? }): Promise<Paginated<AuditCaseSummary>>;
  getCase(id: string): Promise<AuditCase>;                       // агрегат = /api/evga/cases/{id}/workspace/
  createCase(payload: CaseInput): Promise<AuditCase>;            // номер выдаёт сервер
  updateCase(id, payload): Promise<AuditCase>; closeCase(id); assignCoauthor(id, userId);
  createDocument(caseId, kind): Promise<AuditDocument>;
  saveDraft(documentId, version, values, expectedRowVersion): Promise<AuditDocument>;
  action(documentId, version, action: DocumentAction, payload?): Promise<AuditDocument | AuditCase>;
  uploadAttachment(target, file, meta?): Promise<Attachment>; deleteAttachment(id);
  listTasks(); listNotifications(); markNotificationRead(id); listExecutionItems(params);
  catalogs(): Promise<Catalogs>; availableDocuments(caseId): Promise<{kind, blockedReason}[]>;
}
```

`localGateway` реализует контракт поверх сегодняшних чистых функций и IndexedDB (страйглер), `apiGateway` — через `api.evga.*`. После завершения бэкенда `localGateway`, `indexedDbCaseRepository` и `demoScenario` удаляются.

### 5.3. Этапы (страйглер, без поломки страниц)

| Этап | Что делаем | Критерий готовности |
|---|---|---|
| 0. Каркас | `api/client.ts`, `api/types.ts`, `auth/AuthContext.tsx`, новый `App.tsx` + `LoginPage`, `vite.config.ts` с proxy `/api`, `.env.example` (`VITE_API_BASE_URL=/api`, `VITE_DEV_API_TARGET`, `VITE_EVGA_DATA_MODE`), react-router вместо hash (маршруты те же, без `#`), `accountFromUser` | Вход через `/api/auth/local/login`, `useAuth().user` в `AppShell` вместо выпадающего списка ролей; deep-link `/evga/cases/:id/documents/:doc` открывается |
| 1. Справочники и реестры (read-only) | `api.catalogs.*` (объекты аудита, сотрудники, органы, типы аудита/проверок, основания/инициаторы, ОПФ, регионы, уровни риска, типы документов), `listCases` с серверной пагинацией и фильтрами `caseSearch.ts` | `ObjectsRegistry`, `CaseForm` (`ObjectLookup`, `PeoplePicker`), `CasesList`/`AdvancedSearch` берут данные с сервера |
| 2. Дела | `createCase/updateCase/closeCase/assignCoauthor`, основания с вложениями (`FormData`), встречные дела, календарь, соавторы; номер дела — от сервера | `CaseForm.onSave → gateway.createCase`; `nextCaseNumber` не используется |
| 3. Документы и действия | `getCase` возвращает агрегат; `createDocument`, `saveDraft`, `action(...)`, `uploadAttachment`; `evgaAdapter.toAuditDocument` сохраняет форму версии (`registration`, `delivery`, `approvalRoutes`, `history`, `signatures`); клиентские `canEdit/canDecideDocument/creationBlock` остаются подсказками, сервер отвечает 400/403/409 с `detail` | Все `onAction(() => pureFn(...))` заменены на `gateway.action(...)`; stale-проверки через `expected_version`/`row_version` (409) |
| 4. Задания и уведомления | `listTasks` (сервер строит из маршрутов), `listNotifications/markRead`; `ApprovalInbox` получает `routes` с сервера | `ApprovalTasks`, `Notifications` без вычислений по всем делам в браузере |
| 5. Исполнение, КК, апелляции, третьи лица, требования сведений, кабинет объекта | Соответствующие действия и списки; `ExecutionRegistry` получает `ExecutionItem[]` с сервера; роль `object` → отдельный вход в кабинет | — |
| 6. Зачистка | Удалить `localGateway`, IndexedDB, `useDemoSession`, переключатель ролей (или спрятать за `VITE_DEMO_ROLES`), `demoScenario` → `manage.py seed_evga_demo_cases`; PDF — оставить на клиенте | `npm run check` зелёный, `tests/` актуализированы |

Правила на каждом этапе: (а) страницы получают тот же `AuditCase`; (б) после любой мутации — рефетч агрегата дела, как `reloadCase` в prof; (в) ошибки — `errorText(e, fallback)` + глобальный тост `saq:api-error`; (г) в `apiGateway` нельзя импортировать чистые функции правил, иначе логика размажется по двум местам.

### 5.4. Файлы, ошибки, деплой

- **Файлы**: `FileAttachments.tsx` вместо `readUploads` (base64) получает `onUpload → FormData` в `…/attachments/`; `Upload.data` → `href` на download-endpoint (не прямые ссылки на MinIO); файлы в строках коллекций (`IrpiRow.files`, реестр) — те же ссылки `{id, name, size, type, href}` в `values`.
- **Ошибки**: конверт бэкенда совпадает с prof (`{type, title, status, detail, code}`), `errorMessage()` из `client.ts` работает без изменений; для 409 (устаревшая версия) сервер возвращает тексты, которые уже есть во фронте («Открыта устаревшая версия документа. Обновите дело» и т.п.).
- **Деплой**: cookie `saq_session` имеет `SameSite=Lax`, поэтому фронт и API должны быть same-origin — nginx на хосте как в prof (`root /var/www/saq-evga`, `location /api/ → 127.0.0.1:8001`), Vercel убрать (либо временно `vercel.json rewrites /api/(.*)` + `API_SESSION_COOKIE_SECURE=true`).
- **i18n**: скопировать настройку Paraglide из prof (`project.inlang`, `messages/ru.json`, добавить `kk.json`) — двуязычие ru/kk для госсистемы фактически обязательно, kz-поля в данных уже есть.

### 5.5. Что на фронте менять, что не трогать

| Категория | Файлы |
|---|---|
| Не трогать | `components/ui.tsx`, `Modal.tsx`, `ErrorBoundary.tsx`, `Sidebar.tsx`, CSS; `forms/*` (схемы, значения, ссылки, валидация как подсказка); `DocumentForm`, `FormFields`, `IrpiForm`, `IrpiRowForm`, `WorkingPaperForm`, `ViolationRegistryForm`, `AuditCalculations`, `BasisForm`; печатные формы и `pdfExport`; `shared/workflow/*`, `shared/execution/*` (UI и контракты); `types.ts` (+ `AttachmentRef`, `permissions`) |
| Менять минимально (замена источника данных) | `EvgaModule.tsx`, `useAuditCases.ts` → серверные хуки, `CasesList.tsx`, `AdvancedSearch.tsx`, `CaseForm.tsx`, `ObjectLookup.tsx`, `PeoplePicker.tsx`, `ObjectsRegistry.tsx`, `CaseWorkspace.tsx`, `DocumentWorkspace.tsx`, `MainActions/PreparationActions/DocumentActions.tsx`, `InformationRequestPanel.tsx`, `ReviewRouteDialog.tsx`, `AppealPanel.tsx`, `ThirdPartiesPanel.tsx`, `AmendmentsPanel.tsx`, `CounterChecks.tsx`, `QualityRegistry.tsx`, `QualityAssignmentPanel.tsx`, `Notifications.tsx`, `ExecutionRegistryPage.tsx`, `ApprovalTasks.tsx`, `ExecutionProgress.tsx`, `RegulatoryPanel.tsx`, `FileAttachments.tsx`, `AppShell.tsx`, `LoginPage.tsx` — всего ~25 файлов |
| Перенести на сервер (на фронте — только подсказки) | `documentStateMachine.ts`, `workflow.ts`, `mainWorkflow.ts`, `preparationWorkflow.ts`, `documentFactory.ts`, `informationRequests.ts`, `appeals.ts`, `amendments.ts`, `thirdParties.ts`, `qualityAssignment.ts`, `qualityConclusion.ts`, `executionItems/Decision/Progress.ts`, `deadlines.ts`, `caseAccess.ts`, `caseRules.ts`, `reviewParticipants.ts`, `approvalTasks.ts`, `violationRegistry.ts`, `forms/validation.ts`, `irpiValidation.ts`, `workingPapers.ts`, `shared/workflow/approvalRoute.ts`, `history.ts`, `printContext.ts` |
| Удалить | `demoScenario.ts`, `financialDemoValues.ts`, большая часть `data/demoData.ts`, `indexedDbCaseRepository.ts`, `useDemoSession.ts`, `vercel.json` |

Объём: ~75 пользовательских действий сводятся к ~45–60 endpoint-ам; существенных правок — 5 файлов (`EvgaModule`, `CaseWorkspace`, `DocumentWorkspace`, `FileAttachments`, `useAuditCases`), ещё ~20 — точечная замена вызовов; ~30 файлов не меняются.

---

## 6. План работ по итерациям

Оценки — человеко-дни одного бэкенд-разработчика, знакомого с prof; фронт — параллельно вторым разработчиком (этапы страйглера §5.3). Цель — **Демо-1 на сервере после I4** (≈36 чел.-дн. бэкенда, при двух разработчиках ≈ 4 недели), затем этапы процесса по порядку. Полная таблица с содержимым каждой итерации — `design/design-final.md` §11.

| # | Итерация | Результат на стенде | Бэкенд | Фронт |
|---|---|---|---|---|
| I0 | Каркас: копия prof, приложения `evga_*` пустые, аддитивные миграции `core/accounts`, `record_event`, `seed_evga_roles/number_sequences`, compose + `scheduler`, nginx `/evga/`, CI | вход по логину/паролю (`/api/auth/*`), пустые реестры | 4 | 3 |
| I1 | Объекты и справочники: `Subject` + поля, `AnnualPlanEntry`, справочники ЭВГА + read-only API, stub ГБД, справочник сотрудников | `ObjectsRegistry`, `ObjectLookup`, `PeoplePicker` с сервера | 6 | 3 |
| I2 | Дела: `AuditCase` и дочерние, создание/изменение, рабочая группа, соавторы, календарь, основания с вложениями, реестр с фильтрами и пагинацией, `workspace` без документов, история | создание и просмотр дел на сервере, номер от сервера | 7 | 4 |
| I3 | Типы, схемы, документы, версии, черновики: `EvgaDocumentType`, `FormSchema`, `WorkingPaperTemplate` + сиды, `AuditDocument/DocumentVersion`, фабрика, черновики с `row_version`, валидация, вложения версии, `available-documents`, `form-links`, `print-context`, удаление | создание и заполнение любого из 105 видов документов | 10 | — |
| I4 | Маршрут, общий автомат, реестр действий, инбокс, уведомления: `evga_workflow` (27 сценариев контракта), `ACTIONS`/`apply_action`/`DocumentActionView`, `submit/approve/return/reject/recall/activate/send-to-quality`, редакции, `permissions`, `commit_version`, `/tasks/`, `Notification` | **Демо-1: дело → документы → согласование → инбокс → уведомления → история** | 9 | 6 |
| I5 | Подготовительный этап и КК1: цепочка ИРПИ → поручение, КВГА, подписи РГ задания, заключения КК, `QualityAssignment`, `quality_passed`, реестр КК | подготовительный этап целиком (порт `bpmn-preparation.test.ts`) | 8 | 2 |
| I6 | ЕРСОП (stub), доставка объекту, кабинет: `evga_ersop`, эффекты регистрации доп. поручения, `delivery`, `Acknowledgement`, `evga_cabinet`, представитель объекта | **Демо-2: регистрация УК + поручение объекту + кабинет** | 8 | 3 |
| I7 | Основной этап и КК2: подписи РГ отчёта, реестр нарушений (проекция `Violation`, `effective_violations`), подтверждение реестра, КК2, решения объекта | основной этап (порт `bpmn-main-workflow.test.ts`) | 10 | 3 |
| I8 | Требования сведений, сроки, таймеры: `information_requests`, `deadlines` (правила, календарь, `qualityDays`), `progress`, `process_deadlines` | **Демо-3: основной этап + возражения + требования** | 6 | 2 |
| I9 | Заключительный этап и исполнение: заключение, предписание, талон, ответ о мерах, справка о завершении, `evga_execution` (проекции, реестр исполнения, продления), `completion_block`, закрытие дела | заключительный этап и закрытие | 8 | 3 |
| I10 | Возражения, апелляция, третьи лица, доп. поручения (`applyAmendment`), встречные проверки | **Демо-4: сквозной процесс до закрытия (порт `full-process.test.ts`)** | 10 | 3 |
| I11 | Печать/PDF (WeasyPrint по `ReferencePrintForm`), SOAP-адаптер ЕРСОП, шлюз ГБД, синхронизация ролей Keycloak, `seed_evga_demo_cases`, документация `docs/` бэкенда (document-matrix, status-matrix, api-actions, project-decisions, integrations), лимиты файлов, admin, зачистка фронта | промышленные адаптеры за флагами, IndexedDB удалён | 8 | 4 |
| | **Итого** | | **≈94** | **≈36** |

Порядок приложений: `core/accounts/catalogs/subjects` (аддитивно) → `notifications` → `evga_cases` → `evga_documents` → `evga_workflow` → `evga_ersop` + `evga_cabinet` → `evga_execution` → `evga_appeals`. Миграция данных из `surfk.*` (по `legacy_id/legacy_root_table`) — отдельная оценка после получения дампа старой БД.

Что нужно от заказчика до старта I5–I6 (иначе — решения по умолчанию из §8): дамп схемы `surfk` (тела функций `check_*`, содержимое `evga_document_types` и `evga_document_mappings`, значения справочников), подтверждение форматов номеров, реквизиты и транспорт ЕРСОП, Keycloak-роли для подтверждающего реестра и комиссии, источник производственного календаря.

---

## 7. Тесты и качество

Главный источник тестов — уже написанные сценарии фронта: 25 файлов `tests/*.test.ts` (~218 сценариев на чистых функциях, `node --test`). Они фиксируют правила процесса и точные тексты ошибок, поэтому переводятся в pytest **сценарий-в-сценарий**, с сохранением названий (как docstring) и текстов (`pytest.raises(DocumentTransitionError, match=...)`).

### 7.1. Маппинг сценариев фронта на pytest-модули

| Файл фронта (сценариев) | Модуль pytest | Уровень |
|---|---|---|
| `workflow.test.ts` (7: Q01–Q08) | `evga_documents/tests/test_workflow_basics.py` | сервисы |
| `full-process.test.ts` (10) | `evga_cases/tests/test_full_process.py` — сквозной через сервисы, тот же код, что `seed_evga_demo_cases` | сервисы + API |
| `bpmn-preparation.test.ts` (13) | `evga_documents/tests/test_preparation.py` | сервисы |
| `bpmn-main-workflow.test.ts` (16), `bpmn-main-assignment.test.ts` (4), `bpmn-main-validation.test.ts` (4) | `evga_documents/tests/test_main_stage.py`, `test_validation_main.py` | сервисы |
| `bpmn-quality-assignment.test.ts` (7) | `evga_cases/tests/test_quality_assignment.py` | сервисы |
| `bpmn-information-requests.test.ts` (10) | `evga_documents/tests/test_information_requests.py` (с параметром `now`) | сервисы |
| `shared-approval-workflow.test.ts` (27) | `evga_workflow/tests/test_route_contract.py` — контракт маршрута 1:1, коды `ApprovalWorkflowError` → коды API | сервисы |
| `evga-integration.test.ts` (18), `shared-execution.test.ts` (16), `execution-progress.test.ts` (3) | `evga_execution/tests/test_execution.py`, `evga_workflow/tests/test_routes.py`, `evga_cases/tests/test_progress.py` | сервисы |
| `appeals-amendments.test.ts` (8) | `evga_appeals/tests/test_appeals.py`, `evga_cases/tests/test_amendments.py` | сервисы |
| `npa-compliance.test.ts` (16) | `evga_documents/tests/test_npa_rules.py`, `evga_cases/tests/test_deadlines.py` (сроки КК 2/5/10/7/3/20, календарь) | сервисы |
| `violation-registry.test.ts` (11) | `evga_documents/tests/test_registry_validation.py` | сервисы |
| `quality-conclusion.test.ts` (4), `reference-data.test.ts` (3) | `evga_documents/tests/test_print_context.py`, `test_quality_print.py` | сервисы |
| `planned-demo.test.ts`, `demo-readiness.test.ts` | `evga_cases/tests/test_seed_demo.py` — `call_command("seed_evga_demo_cases")` дважды, идемпотентность | команды |
| `navigation.test.ts`, `pdf-export.test.ts`, `audit-format.test.ts`, `approval-inbox.test.tsx`, `approval-route-editor.test.tsx`, `document-workspace.test.tsx` | остаются на фронте (UI/навигация/PDF) | фронт |

### 7.2. Что добавить сверх сценариев фронта

- **API-тесты RBAC и конверта** по образцу `apps/subjects/tests/test_api.py` и `apps/core/tests/test_exception_handler.py` prof: 401 без cookie, 403 не участник маршрута / чужой department, 404 чужой объект в кабинете, 409 `stale_version`, 405 `DELETE` там, где запрещён.
- **Тесты реестра действий**: для каждого `ActionSpec` — недопустимый статус → 400 с русским `detail`, чужая роль → 403, `expected_version` не совпал → 409; параметризованный тест «каждый переход в таблице имеет сервис и валидный целевой статус».
- **Совместимость с legacy**: каждый код действия/статуса/M-код из каталогов старой системы (`analysis/bpmn-processes.md`, `analysis/n8n-cases-documents.md`) либо есть в справочниках, либо явно в списке `DROPPED_LEGACY_*` с причиной.
- **Конкурентность** (как `core/tests/test_numbering.py`): два одновременных `approve` одной версии → один 200, один 409; номера без пропусков.
- **Интеграции**: адаптеры-заглушки — юнит; SOAP-адаптер ЕРСОП — `httpx.MockTransport` с XML-фикстурами из n8n `SEND_REQ_TO_ERSOP`.
- **Seed**: идемпотентность двойного вызова каждой `seed_evga_*`; `seed_evga_demo_cases` в CI как smoke-тест сквозного процесса.
- **Контрактный тест адаптера фронта**: `tests/evga-adapter.test.ts` на JSON-снимках `workspace`, выгруженных из pytest-фикстур, чтобы формы не сломались при изменении DTO.

### 7.3. Инструменты

pytest-django (`--reuse-db`), `pytestmark = pytest.mark.django_db`, хелперы-функции без фабрик (`_user_with_role(code)`, `_case(**)`, `_document(case, kind)`), `APIClient().force_authenticate`; ruff `E,F,I,UP,B,DJ`, 120 символов; `python manage.py check`; в CI — `pytest backend` + `ruff check` + `npm run check` фронта. Тесты пишутся **вместе** с портом функции: сценарий TS переводится дословно до написания сервиса.

---

## 8. Открытые вопросы к заказчику и команде (с решениями по умолчанию)

Вопросы сгруппированы по влиянию на бэкенд. Для каждого указано решение, которое закладывается в проект, пока нет ответа — чтобы разработка не останавливалась.

### 8.1. Размещение и стек

| № | Вопрос | Решение по умолчанию |
|---|---|---|
| 1 | Один Django-проект SAQ (приложения ЭВГА рядом с prof) или отдельный бэкенд ЭВГА? | Отдельный репозиторий `saq-evga-backend`, созданный копированием каркаса prof (`config`, `core`, `accounts`, `catalogs`, инфраструктура); общая cookie-сессия `saq_session` и Keycloak позволяют позже объединить |
| 2 | Один SPA SAQ с лаунчером (`/evga/*`) или отдельный фронт ЭВГА со своим хостом? | Отдельный фронт, same-origin деплой через nginx (`/api/` → бэкенд ЭВГА); ссылка в лаунчере prof `saqModules.ts` меняется с Vercel на новый хост |
| 3 | Вход: локальный (email/пароль, как в prof-фронте) или Keycloak (как в старой ЭВГА)? | Оба: локальный для стенда, Keycloak — кнопка SSO (бэкенд prof уже умеет OIDC + PKCE) |
| 4 | Часовой пояс: prof хранит UTC, ЭВГА/ЕРСОП оперируют Asia/Almaty (+05:00), сроки считаются в рабочих днях | `TIME_ZONE = "UTC"` в БД, расчёт рабочих дней и отображение — в Asia/Almaty; производственный календарь РК — справочник на сервере |

### 8.2. Роли и права

| № | Вопрос | Решение по умолчанию |
|---|---|---|
| 5 | Кто в реальной оргструктуре соответствует зашитым во фронте аккаунтам `approver` (назначает соавтора, подписывает обоснования аудитора), `quality-head`, `commission-chair`, `commission-1/2`, `reestr-confirmer`, `kvga`? | Отдельные роли `qc-head`, `appeal-commission-chair`, `appeal-commission-member`, `reestr-confirmer`, `kvga-confirmer`; «руководитель органа аудита» — роль `approver` с доменом `cases: decide` |
| 6 | Источник истины для ролей: `RoleAssignment` в БД (prof) или роли из токена Keycloak (старая ЭВГА, полная перезапись при входе)? | Синхронизация из токена при входе **в** `RoleAssignment` (как `User Login Sync`), ручное назначение через admin остаётся для стенда |
| 7 | Скоупинг по подразделению: в prof — department строки перечня; в ЭВГА дело имеет рабочую группу и объект с регионом | Скоуп по `AuditCase.department` (орган/подразделение автора) + членство в рабочей группе/маршруте для объектных прав |
| 8 | Представитель объекта аудита: отдельный тип пользователя с кабинетом (как `is_subject_representative` в prof) или переключение роли `object` в том же браузере? | Кабинет объекта (`apps/cabinet`) с привязкой пользователя к `AuditObject` по БИН; демо-переключение ролей — только dev-флаг |
| 9 | Автор дела сейчас идентифицируется по ФИО (`audit.author === actor.name`) | На сервере — `user_id`; ФИО хранится как денормализованный снимок для печати |

### 8.3. Документы и процесс

| № | Вопрос | Решение по умолчанию |
|---|---|---|
| 10 | Формат номеров: клиентский (`30101-YY-NNNNN`, `{дело}/NN`, `{дело}/ВП-n`) или старой системы (`<орган>-<YY>-<00000>`, `YYYY/MM/DD – 00000`, `<prefix>-<орган>-<YY>-<000000>/<хвост>`), важно для преемственности с ЕРСОП | Шаблоны конфигурируются в `seed_number_sequences`; по умолчанию — форматы старой системы; фронт номера не генерирует |
| 11 | Последовательное vs параллельное согласование (Q06 «пока только последовательное»; контракт `shared/workflow` поддерживает `parallel` и этапы) | Модель маршрута поддерживает оба режима; `parallel` выключен настройкой |
| 12 | Автосоздание документов при создании дела (старая система создавала 5 подготовительных документов; заказчик Q08 — вручную из меню «Создать») | Вручную (Q08); автосоздание — флаг типа документа, выключен |
| 13 | Состав комплекта КК2/КК3, допустимость согласования исправленного документа без повторного КК (Q13), правило выбора маршрута «КК КВГА» (`qc_route`, правила не переданы) | Как во фронте: КК2 = отчёт + реестр + доказательства, КК3 = заключение (+ предписание); повторный КК после каждой новой версии; `qc_route` не реализуется |
| 14 | Доп. поручение: требуется «Активный» или «Зарегистрирован» (Q10); полное распространение изменений на связанные документы с повторной регистрацией | Как во фронте: активное поручение, `applyAmendment` порождает версии связанных документов после регистрации |
| 15 | «Отчёт становится Активным при направлении объекту (а не при утверждении)», «регистрация доп. поручения "Отмена проверки" закрывает дело», «регистрация встречного талона закрывает встречное дело» — нестандартные переходы фронта | Переносим как есть (зафиксировано тестами фронта), помечаем как требующие подтверждения |
| 16 | Хранение содержимого форм: JSONB `values` по декларативной схеме (фронт, старая `evga_document_mappings.form_schema`) или реляционные `*Details` по каждому из 105 видов (prof)? | JSONB `values` + реляционные **проекции** для строк, на которые ссылаются другие документы и отчёты (нарушения, вопросы, объекты риска, пункты предписания, меры); схемы форм — сид `FormSchema` для серверной валидации |
| 17 | Рабочие формы (62 РД): обязательны ли для КК в проде (во фронте с 09.09.2026 необязательны по запросу заказчика)? | Необязательны; флаг типа документа |
| 18 | Административное производство (M38–M57, подчинённое дело `admin_violation`), приказы (`evga_doc_prikaz`) — входят ли в объём? | Не входят в первый релиз; модель `AuditCase.kind` заранее допускает `ADMIN_VIOLATION` |
| 19 | Дубль справочника статусов устранения: «Частично устранено» и «Устранено частично» | Один код `PARTIALLY_REMEDIATED` с одной подписью |
| 20 | Нужен ли отдельный документ `evidence` (комментарий в коде: «BPMN не предусматривает отдельного документа доказательств») | Оставляем как во фронте (M19-AD в старой системе тоже отдельный документ) |

### 8.4. Интеграции

| № | Вопрос | Решение по умолчанию |
|---|---|---|
| 21 | ЕРСОП: перечень регистрируемых документов и их M-коды (M11, M14, M26; встречные M44/M47 в исходниках не найдены), реальные реквизиты `userCreate/userSign/organCode` (в n8n — MOCK), `SubjectInfo.subjectId/ObjectInfo.objId` | Адаптер `stub` (как prof) до получения контракта; `soap` — порт n8n за интерфейсом; реквизиты — из `GovernmentBody`/профиля пользователя |
| 22 | Кто формирует PDF для ЕРСОП (`fileBase64`), ЭЦП и публичной верификации: сервер или загрузка PDF с фронта (pdfmake)? | Первый релиз — клиентский PDF загружается как `Attachment(kind=signed_pdf)`; серверный рендер — отдельная итерация |
| 23 | ЭЦП (NCALayer/CMS): допустима ли заглушка на первом релизе при требовании ПЗ «согласование и утверждение с ЭЦП»? | `DocumentSignature.provider = stub`; интерфейс под NCALayer заложен (`requires_signature` из BPMN) |
| 24 | ГБД ЮЛ/ФЛ: контракт (SOAP `SI_GBD_JL_PIWS_OS` или REST camel-gateway), токены | Адаптер `stub` с данными из `seed_catalogs`; `soap`/`rest` — порт n8n |
| 25 | Уведомления: только in-app или e-mail/WebSocket (в старой системе — WS портала)? | In-app (`Notification`); каналы — расширение |
| 26 | Ограничения на вложения (размер, MIME, антивирус) — в prof не заданы | 25 МБ (как `client_max_body_size` nginx prof), белый список MIME (pdf, docx, xlsx, jpg, png, zip) |
| 27 | Таймеры: просрочка требований сведений, автоотказ по встречному требованию, сроки исполнения — нужен ли серверный планировщик и внешние напоминания? | Вычисление «на чтение» + одна management-команда `run_deadlines` по cron; celery — при появлении e-mail/WS |

### 8.5. Данные и миграция

| № | Вопрос | Решение по умолчанию |
|---|---|---|
| 28 | Нужен `pg_dump --schema-only surfk` старой БД: тела хранимых функций (`check_*`, `get_next_*_sequence`, `send_case_to_qc`, `create_full_document_snapshot`…), полное содержимое `evga_document_types`/`evga_document_mappings`, `case_statuses` | Без дампа — реконструкция из SQL n8n и фронта (сделано в `analysis/n8n-cases-documents.md`); дамп сократит риски |
| 29 | Переносить ли данные старой системы (дела, документы, зарегистрированные в ЕРСОП номера)? | Не в первом релизе; `legacy_code`/`legacy_id` поля предусмотрены |
| 30 | Что делать с делами стенда в IndexedDB пользователей (base64-вложения)? | Считать тестовыми; демо-сценарии воспроизводятся `seed_evga_demo_cases` |
| 31 | Нужен файл ПЗ ЭВГА для подтверждения кодов разделов 2.6/2.7/3.3/3.9 и трассировки требований | Запросить у заказчика; в проекте используются M-коды и `kind` фронта |

---

## 9. Как принимались решения (журнал альтернатив)

Проект архитектуры готовился так: по каждому исходнику написан отдельный аналитический отчёт (`analysis/`), затем три независимых варианта архитектуры с разными приоритетами — «максимум prof» (A), «максимум старой системы как спецификации» (B), «проще всего для разработчика» (C) — и итоговый синтез с явным выбором по каждому спорному пункту. Полный журнал (20 пунктов с аргументами A/B/C) — `design/design-final.md` §13. Ключевые развилки:

| Спорный пункт | Альтернативы | Принято | Почему |
|---|---|---|---|
| Где живёт бэкенд | монорепо внутри prof (A, B) / отдельный проект-копия каркаса (C) | **отдельный `saq-evga-backend`**, монорепо — опция | ранний независимый стенд без прав на prof; слияние = перенос папок `apps/evga_*` |
| Состав приложений | 8 `evga_*` (A) / 13 `apps/evga/<name>` (B) / 12 без префикса (C) | **8 `evga_*` + `notifications`** | префикс защищает от коллизий при слиянии, меньше шаблонного кода |
| Модель документа | типизированные под-состояния + 4 проекции (A) / legacy-шапка + 11 проекций (B) / JSONB под-состояния (C) | **A** | инбокс, уведомления и ЕРСОП требуют FK и уникальностей; 11 проекций избыточны без отчётности; JSONB под-состояния — техдолг для выборок |
| Коды статусов | UPPER_CASE + русские подписи (A, C) / коды старой системы (B) | **UPPER_CASE + `LEGACY_STATUS_MAP`** | стиль prof; коды старой системы нужны только отчётности и ЕРСОП |
| Форма API действий | `APIView` на действие (A) / один `POST …/actions/` с реестром (C) / гибрид (B) | **`APIView` на действие + базовый класс + реестр `ActionSpec`** | явные URL и Swagger как в prof; единые `expected_version`, журнал, `available_actions` |
| Движок переходов | диспетчер в сервисах (A) / таблица `StatusTransition` в БД (B) / реестр действий (C) | **константы Python в формате полей `evga_status_transitions`** | guard-функции ссылаются на код и покрываются pytest; таблица в БД — лишний слой |
| Гейты | вычисление (все) vs события BPMN (`prev_approved`, `doc_approved`) | **вычисление** | событийная модель давала «потерянные сообщения» |
| КК | `QualityAssignment` (A, C) / `QcRequest` с историей и маршрутом `kk_kvga` (B) | **`QualityAssignment`**, история в `AuditEvent`, `route` — резерв | модель фронта согласована с заказчиком; правила `qc_route` не переданы |
| Роли | 14 ролей (A) / 22 роли из Keycloak (B) / 15 без префикса (C) | **16 ролей: 14 `evga-*` + `observer` + `evga-admin`**, маппинг с инверсией `approver ↔ reviewer`, `confirmer ↔ approver` | покрывает фронт и старую систему; синхронизация за флагом |
| Таймеры | management-команда (A, C) / команда + флаги автоподписи (B) | **`process_deadlines` по cron**; автоподпись и автосоздание — за выключенными флагами | без Celery; ответы заказчика Q08 |
| Печать | клиент до серверной итерации (A, C) / сервер рано (B) | **клиентский pdfmake, серверный — I11** | демо не зависит от PDF; заглушка ЕРСОП файла не требует |
| План | 12 итераций ≈92 (A) / 9 ≈93 (B) / 6 ≈40 + техдолг (C) | **I0–I11 ≈94 + ≈36 фронт, Демо-1 после I4** | оценка C занижена из-за отложенных проекций и тестов |

Что осталось непроверенным первоисточником (12 пунктов, приложение к `design/design-final.md`): соответствие `zeebe_process_id → prc_*` и M-коды для части видов, семантика оснований `13/14` для «КК КВГА», Keycloak-роль подтверждающего реестра, атрибут БИН в claims для представителя объекта, реальные реквизиты и транспорт ЕРСОП, смысл id статусов старой БД, колонки `evga_doc_info_request`/`evga_qc_requests`, тела хранимых функций `surfk.check_*`, содержимое `evga_document_mappings`, календарные vs рабочие дни для срока возражений, ответы заказчика Q09–Q20, источник производственного календаря.
