# Итоговый проект архитектуры бэкенда ЭВГА — `saq-evga-backend`

Автор: главный архитектор (агент). Дата: 2026-09-23. Статус: итоговый проект, синтез трёх предложений (A «prof-first», B «legacy-first», C «simplest-for-devs») с решениями руководителя по спорным пунктам.

Источники: три предложения (`reports/design-A-prof-first.md`, `design-B-legacy-first.md`, `design-C-simplest-for-devs.md`), отчёты фазы 1 как первоисточник при расхождениях (`prof-backend-style.md`, `prof-frontend-integration.md`, `evga-domain-model.md`, `evga-workflows.md`, `evga-ui-actions.md`, `evga-docs-requirements.md`, `n8n-cases-documents.md`, `n8n-references-auth-notify.md`, `bpmn-processes.md`, `tor-and-common-requirements.md`), исходники `src/prof/saq-prof-control-demo` (эталон), `src/evga/saq-evga-test` (фронт), `src/n8n_old` (n8n + BPMN).

Обозначения: prof — эталонный бэкенд `saq-prof-control-demo/backend` (Django 5 + DRF + PostgreSQL + MinIO + Keycloak); фронт — SPA `saq-evga-test`; legacy — n8n-воркфлоу + схема `surfk.*` + 72 BPMN Camunda 8; ОА — объект аудита; КК — контроль качества; ЗКК — заключение КК; КВГА — подтверждающее лицо комитета; РГ — рабочая группа; АК — апелляционная комиссия; ЕРСОП — единый реестр субъектов и объектов проверок. Пути prof — относительно `backend/`, фронта — относительно `src/`. Идентификаторы кода — как в исходниках (`DocumentTransitionError`, `HasDomainLevel`, `surfk.evga_case_documents`, `M7-POR`, `kvga_confirm`). Пометка **«не подтверждено»** означает, что утверждение о старой системе или заказчике не имеет первоисточника в отчётах фазы 1 и требует проверки.

Содержание: 1. Резюме и ключевые решения · 2. Размещение · 3. Состав приложений и пофайловая карта · 4. Модель данных · 5. Сервисный слой и автоматы · 6. API-контракт · 7. Auth/RBAC · 8. Интеграции · 9. Справочники и seed · 10. Перевод фронта и деплой · 11. План работ и тесты · 12. Риски и открытые вопросы · 13. Журнал решений · Приложение. Список «не подтверждено».

---

## 1. Резюме и ключевые решения

Ключевой тезис (совпадает у всех трёх предложений): prof уже содержит всё сквозное — auth/сессии/Keycloak, RBAC, вложения + MinIO, журнал, нумерацию, конверт ошибок, пагинацию, сиды, docker-compose. Домен ЭВГА отличается тремя вещами: **версии документов, многошаговый маршрут согласования и 105 видов форм**. Итоговый проект берёт каркас и сквозные приложения prof буквально (A), модель данных фронта с типизированными под-состояниями (A), реестр действий с единой точкой применения (C) и легаси-коды/контракты как формат объявления и словари соответствия (B). Camunda/Zeebe и n8n как рантаймы не переносятся (`bpmn-processes.md` §10).

| # | Решение | Обоснование | Откуда взята лучшая деталь |
|---|---|---|---|
| 1 | **Отдельный репозиторий `saq-evga-backend`**, созданный копированием каркаса prof (`config/`, `apps/core`, `apps/accounts`, `apps/catalogs`, `apps/subjects`, `Dockerfile`, `docker/entrypoint.sh`, `docker-compose.yml`, `deploy/`, `pyproject.toml`, `requirements/`) с правилом «общие приложения меняются только аддитивно» (новые поля `null/default`, новые choices, новые файлы, миграции `00NN_evga_*`). Слияние в монорепо SAQ позже сводится к переносу папок `apps/evga_*`. | Независимый стенд и CI для раннего демо, отсутствие риска сломать prof; структура идентична prof, поэтому слияние механическое. | C §2.1 (рекомендация B), A §2.1 (вариант B2 «форк с прицелом на слияние»: правила аддитивности и миграций `00NN_evga_*`) |
| 2 | **Фронт — отдельный SPA `saq-evga-test`**, деплой same-origin через nginx (`location /evga/` + `location /api/`), Vercel убирается; лаунчер prof ссылается на `/evga/cases`. | Cookie `saq_session` имеет `SameSite=Lax` и не переживёт чужой домен; слияние SPA (Tailwind/Paraglide/react-router) не приближает демо. | A §2.2 (F1), `prof-frontend-integration.md` §4.5 |
| 3 | **Восемь приложений `apps/evga_*` + `apps/notifications`** по чек-листу prof (§12 `prof-backend-style.md`): `evga_cases`, `evga_documents`, `evga_workflow`, `evga_execution`, `evga_appeals`, `evga_ersop`, `evga_cabinet`, `notifications`. Структура каждого: `models.py, admin.py, api/{views,serializers,urls,filters}.py, services/*.py, management/commands/seed_*.py, tests/`. | Один шаблон на все приложения, префикс `evga_` изолирует их в будущем монорепо. | A §3.1 |
| 4 | **Документ = `AuditDocument` (шапка) + `DocumentVersion` (статус, владелец, `values` JSONField по `FormSchema`, `print_context`, `row_version`) + `EvgaDocumentType` (105 видов: `code` = kind фронта, `legacy_code` = M-код, флаги) + `FormSchema` + `WorkingPaperTemplate`.** Под-состояния с FK на пользователей/версии, по которым строятся инбокс/уведомления/ЕРСОП — типизированные таблицы: `VersionParticipant`, `DocumentSignature`, `DocumentSourceVersion`, `ErsopRegistration`, `DocumentDelivery` (+ `Acknowledgement`), `KvgaConfirmation`, `RegistryConfirmation`, `InformationRequestRound`, `ApprovalRoute/Stage/Participant/Event`. Реляционные проекции строк JSON — только `Violation`, `PrescriptionItem`, `Recommendation`, `ResponseMeasure` (+ при необходимости `AuditQuestion`, `RiskObject`). | 105 видов × ≈900 полей описаны декларативно во фронте; `*Details`-таблицы на каждый вид = 40+ моделей и переписывание 25 тыс. строк форм. FK-под-состояния нужны для SQL-выборок инбокса и уникальностей («Ваша подпись уже сохранена»). | A §4.7, §4.13 (типизированные под-состояния и проекции); C §1 п.1 (JSONB `values` + `FormSchema`); B §4.5 (`RowProjection`, идея «проекция пересобирается сервисом») |
| 5 | **Сериализатор версии отдаёт форму `DocumentVersion` фронта (`types.ts`)**: `registration`, `delivery`, `informationRequest`, `preparation`, `main`, `mainQuality`, `approvalRoutes`, `signatures`, `sourceVersions`, `history` собираются сервером из типизированных таблиц; `evgaAdapter` на фронте минимален. | Формы и печать не трогаются; сервер остаётся владельцем правил. | C §4.4 (форма фронта как контракт), A §6.2 (состав read-сериализатора) |
| 6 | **`DocumentStatus` — `TextChoices` в стиле prof**: UPPER_CASE код, русская подпись = точная строка `DocStatus` (11 значений). Коды старой системы (`draft`, `pending_approval`, `revision`, `active`…) — таблица соответствия `LEGACY_STATUS_MAP` для отчётности/ЕРСОП, не основной enum. Регистрация ЕРСОП, доставка ОА, подтверждения — отдельные enum'ы на связанных таблицах. | Фронт продолжает показывать свои строки (`status_label`); 45 легаси-статусов — специализации доставки/регистрации/КК, а не статусы документа (`bpmn-processes.md` §2.1, §9.1). | A §4.7 (`DocumentStatus`, `_STATUS_LABEL_OVERRIDES`), B §4.14 (таблица «фронт ↔ legacy ↔ поглощённые статусы» → `LEGACY_STATUS_MAP`) |
| 7 | **API в стиле prof — отдельный `APIView` на действие с явными URL** (`…/submit/`, `…/approve/`, `…/return/`…), но с общим базовым классом `DocumentActionView` и **реестром `ACTIONS`** из `ActionSpec(code, service, domain/levels, roles, workflows, statuses, requires_comment, payload_serializer, legacy_codes)`. Реестр даёт единый `expected_version → 409`, единый журнал, единый расчёт `available_actions`/`permissions` для фронта. Действия дела — отдельные `APIView`. Чтение — `GenericViewSet` + mixins, агрегат `workspace`. | Явные URL документируются в Swagger и совпадают со стилем prof (`ApproveDocumentView`); реестр убирает 30 одинаковых тел view и даёт фронту готовые кнопки (аналог `get_available_actions` n8n). | C §5.3 (`ActionSpec`, `apply_action`, `available_actions`), A §6.3 (явные URL и уровни прав), `n8n-cases-documents.md` §4.4 (правило роль ∧ назначение) |
| 8 | **Движок переходов: таблицы переходов объявляются в коде** — константы Python по семействам BPMN T0–T9 → `EvgaDocumentType.workflow ∈ {route, preparation, main, quality, direct}` (T2 доставка, T3 ЕРСОП, T7 требования — ортогональные под-автоматы на связанных таблицах). Формат объявления — структура полей `surfk.evga_status_transitions` (`from_status, action_code, to_status, required_role_code, assignment_type, requires_signature, requires_comment, is_automatic`), но **не таблица в БД**. Гейты (`check-docs-status`, `creationBlock`, `dependencies`) — вычислением. | Guard/effect ссылаются на Python-функции и покрываются pytest; сид таблицы из кода (B) — лишний слой; событийные `prev_approved/doc_approved` давали «потерянные сообщения». | B §4.5/§5.2 (структура `StatusTransition` как формат), C §5.4/§5.5 (вычисляемые блоки), `bpmn-processes.md` §10.3 |
| 9 | **Сервисы — функции-модули, порт TS-функций фронта 1:1** (`documentStateMachine.ts`, `workflow.ts`, `preparationWorkflow.ts`, `mainWorkflow.ts`, `informationRequests.ts`, `appeals.ts`, `amendments.ts`, `thirdParties.ts`, `qualityAssignment.ts`, `executionItems.ts`, `deadlines.ts`, `approvalRoute.ts`) с сохранением русских текстов ошибок. `DocumentTransitionError → 400`, `StaleVersionError → 409`, `PermissionDenied → 403`. | Тексты закреплены 218 тестами фронта — они становятся pytest-сценариями. | A §5.1, C §5.1 |
| 10 | **КК: `QualityAssignment(case, stage, expert, assigned_by, reason)`** с историей замен в `AuditEvent`; заключения КК — документы `quality1/2/3`; маршрут «КК КВГА» (`qc_route = "KK KVGA"`) не реализуется, зарезервированы флаг `BasisKind.qc_route_kvga` и поле `QualityAssignment.route`. | Модель фронта проще и согласована с заказчиком; в legacy правила `qc_route` не переданы (`bpmn-processes.md` §11 п.5). | C §4.6 (`QualityAssignment`), B §4.7 (`QcRoute` как резерв), A §4.6 |
| 11 | **RBAC — prof `Role/RolePermission/RoleAssignment/HasDomainLevel/ScopedQuerySetMixin` без изменений кода**; домены `evga_cases, evga_quality, evga_registry, evga_appeals, evga_execution, evga_cabinet, evga_admin` (+ `dsp` как permission-домен); уровень `CONFIRM` добавляется; роли — 10 ролей фронта + `qc-head`, `kvga-kk-head`, `kvga-kk-expert`, `appeal-commission-chair`, `appeal-commission-member`, `observer`, `evga-admin`; таблица маппинга на Keycloak-роли старой системы (старый `approver` = фронтовый `reviewer`, старый `confirmer` = фронтовый `approver`) и синхронизация из `realm_access.roles` при входе. Адресные назначения — таблицы + проверки в сервисах. | `HasDomainLevel` проверяет `level__in` — новые значения ничего не ломают; инверсия терминов зафиксирована `bpmn-processes.md` §9.3. | A §7 (домены, уровень `CONFIRM`, объектные проверки), B §7.1/§7.3 (синхронизация `User Login Sync`, полный список Keycloak-ролей), C §7.1 (маппинг на `Account` фронта) |
| 12 | **Кабинет ОА — копия `apps/cabinet` prof** (`IsSubjectRepresentative`, `_assert_subject_owns`, контекст `{"cabinet": True}`, download-view); представитель = `User.is_subject_representative + subject FK` на объект аудита (= `subjects.Subject`, расширенный аддитивно). | Роль `object` «в том же браузере» — демо-механика; ТЗ 2.12 и prof требуют отдельного типа пользователя. | A §7.6, `tor-and-common-requirements.md` §2.7 |
| 13 | **Нумерация — `core.NumberSequence`/`issue_number`**, шаблоны настраиваются сидом: дело `{org}-{yy}-{seq:05d}` (совпадает и с фронтом `30101-YY-NNNNN`, и с legacy `CONCAT(code,'-',YY,'-',LPAD(seq,5,'0'))`), документ `{case}/{seq:02d}`, встречное дело `{parent}/ВП-{seq}`, регистрационные номера ЕРСОП — форматы старой системы `standard`/`with_org` за адаптером, регистрация-заглушка `УЧ-{yyyy}-{seq:05d}`. | Готовый gapless/идемпотентный механизм с тестами конкурентности; `COUNT(*)+1` legacy не воспроизводится. | B §4.12 (legacy-форматы), A §4.15 (ключи/scope), `n8n-cases-documents.md` §2.6 |
| 14 | **Журнал — `core.AuditEvent` расширяется** (`case` FK, `action_code`, `source ∈ user/system/ersop/timer`, `metadata`) и **реально пишется** из каждого перехода через `core/services/audit.py::record_event`. `HistoryEntry` фронта = проекция. | В prof модель есть, но не используется (0 записей из сервисов); ТЗ табл. 49 требует журнал; четыре журнала legacy сводятся к одному. | A §4.2, `n8n-references-auth-notify.md` §6.7 |
| 15 | **Таймеры — management command `process_deadlines`** по cron (compose-сервис `scheduler`); просрочки требований вычисляются на чтение; автоподпись отчёта по `P10D` и автосоздание документов при создании дела не реализуются (флаги `EVGA_AUTO_SIGN_REPORT_AFTER_DAYS=None`, `EVGA_AUTOCREATE_PREPARATION_DOCS=False`). | В prof планировщика нет; таймеров три вида; ответы заказчика Q08 (ручное создание) и решения фронта (`evga-docs-requirements.md` §3.4). | C §5.6, B §1 п.16 (флаги вместо спора), A §5.5 |
| 16 | **Интеграции — по образцу `ersop/services/stub_exchange.py` + лог обмена**: `ErsopRegistration` на версию + `ErsopExchange`, адаптеры `stub`/`soap` с контрактом `M_TYPE_STARTED…FINISHED` из n8n; ГБД ЮЛ/ФЛ — `subjects/services/gbd.py` (`stub`/`gateway`); ЭЦП — `DocumentSignature.provider=stub` с интерфейсом под NCALayer; уведомления — in-app `apps/notifications`. PDF на первом этапе клиентский (pdfmake). | ТЗ SAQ допускает заглушки; реальный контракт берётся из `ERSOP - Build and Send from Document`/`SEND_REQ_TO_ERSOP`. | A §8, B §8.1 (состав payload `Started`, маппинг `confirmstatusid`), C §8 (интерфейс адаптера) |
| 17 | **Фронт: контракт `AuditCaseRepository.load/save` заменяется на `EvgaGateway` (`apiGateway`/`localGateway`) + `evgaAdapter`**; формы не трогаются; страйглер в 6 этапов; демо-роли/IndexedDB/`demoScenario` удаляются (сценарии → `seed_evga_demo_cases`). | План `prof-frontend-integration.md` §4; `save(cases)` целиком делает клиент источником истины. | C §10.1 (интерфейс `EvgaGateway`), A §10.2 (этапы и требуемые итерации бэкенда) |
| 18 | **План: демо на сервере как можно раньше** — каркас → справочники/объекты → дела → документы/версии/черновики → маршрут/инбокс/уведомления (≈36 чел.-дн.), далее этапы процесса по порядку; оценки по блокам; тесты — pytest 1:1 по ~218 сценариям `tests/*.test.ts`. | Ранний сервер снимает риск «двойной логики»; сценарии фронта — готовая спецификация. | A §11 (порядок итераций), C §11 (ранние демо-вехи), B §11 (тесты движка и legacy-совместимости) |
| 19 | **Из legacy берутся только данные и контракты**: коды статусов/действий/M-коды как `legacy_code`/`LEGACY_STATUS_MAP`/`ActionSpec.legacy_codes`, состав колонок `surfk.*` как чек-лист полей, справочники, контракт ЕРСОП/ГБД, правило `get_available_actions` (роль ∧ назначение), паттерн `check-docs-status` как вычисляемый гейт. Camunda/Zeebe/n8n-роутер, `workflow_state.available_actions` в БД, `isReactivation`, дубли «номерного поколения», дефектные ожидания — не переносятся. | `bpmn-processes.md` §10.5, `n8n-cases-documents.md` §6. | B §1 п.1–4, A §5.4 |
| 20 | **Часовой пояс**: глобальную настройку prof (`TIME_ZONE="UTC"`) не менять; в `deadlines.py` и ЕРСОП-адаптере явно `ZoneInfo("Asia/Almaty")`; при слиянии в монорепо обсудить переход всего SAQ. | Аддитивность общих приложений (решение 1) важнее локального удобства; фронт уже считает `localDate` в `Asia/Almaty`. | A §12 п.4 |

### 1.1 Где буквальное копирование prof ломается и что придётся изменить

| Паттерн prof | Почему не подходит ЭВГА | Консервативное расширение |
|---|---|---|
| `ControlDocument` с `UniqueConstraint(list_entry, document_type)` и одним `status` | 19 повторяемых видов; статус живёт на версии; прошлые версии неизменяемы | `AuditDocument` (шапка без статуса) + `DocumentVersion(status, values, row_version)`, `UniqueConstraint(document, version)`; «один документ на неповторяемый вид» — проверка в `create_document` под `select_for_update(case)` |
| `*Details` OneToOne на тип + `DETAILS_SERIALIZERS` | 105 видов, ≈900 полей, схемы меняются вместе с НПА | `values` JSONField + `FormSchema` (сид из `forms/documentForms.ts`); `DETAILS_SERIALIZERS` → `values` как есть + 4 проекции строк |
| Три action-view `Approve/Sign/Send` с диспетчером по коду типа | ~35 действий; переходы зависят от семейства маршрута | тот же приём «`APIView` на действие», но тело view — базовый класс `DocumentActionView` + `ActionSpec`; ключ диспетчеризации — `EvgaDocumentType.workflow` |
| Ссылка документов на строку перечня (`list_entry`) | Дело первично, перечень — основание планового аудита | `AuditDocument.case` FK; `subjects.AnnualPlanEntry` — только для валидации «плановый объект в перечне» (Q03) |
| `ControlCase.status` вычисляется | В ЭВГА `status` хранится (Открыто/Закрыто), `execution_state` хранится, вычисляются `quality[3]`, этап, `progress` | `AuditCase.status`/`execution_state` — поля; `quality_stage_passed` — колонка-кеш, пересчитываемая в транзакции коммита (`compute_quality`); `stage` — property |
| `ErsopPackage` на дело + позиции пакета | ЭВГА регистрирует отдельные документы (М11/М14/М26 и встречные) | `ErsopRegistration` OneToOne на `DocumentVersion`; `ErsopExchange` — копия |
| `Acknowledgement(document, channel)` | Ознакомление — часть «доставки» с решением ОА | `Acknowledgement` переиспользуется (FK на версию) + `DocumentDelivery` с `decision` |
| `execution.PrescriptionItem` FK на `CaseChecklistViolation` | Нарушения — строки JSON реестра | `PrescriptionItem`/`ResponseMeasure` — проекции, пересобираемые при активации версии; `status` — `@property` |
| `PermissionDomain` = 3 домена, уровни без `CONFIRM` | Подтверждение КВГА/реестра — отдельное полномочие | 7 доменов `evga_*` + `dsp`, уровень `CONFIRM` (аддитивно) |
| `_assert_department_in_scope` в `documents/api/views.py` | Импорт из prof-домена нежелателен | Копия в `accounts/querysets.py::assert_department_in_scope` (аддитивно; prof-функция остаётся) |
| `AuditEvent.action` — 7 значений, не пишется | ~35 кодов действий, привязка к делу, источник | `AuditAction` +13, `action_code`, `case`, `source`, `metadata`; `record_event()` |

---

## 2. Размещение

### 2.1 Бэкенд: сравнение вариантов и принятое решение

| Критерий | B1. `apps/evga_*` внутри prof-бэкенда (монорепо SAQ) | **B2. Отдельный репозиторий `saq-evga-backend` — копия каркаса prof (принято)** | B3. Отдельный проект, общий только Keycloak |
|---|---|---|---|
| Auth/сессия | один cookie `saq_session`, один `/api/auth/me`, лаунчер без SSO-перескоков | второй `/api/auth/*` и второй `AuthSession`; при общем Keycloak — SSO через realm, при локальном входе — вход дважды | как B2 |
| Переиспользование `core/accounts/catalogs/subjects` | 100 %, без дублирования | копия в момент форка; расхождения контролируются правилом аддитивности и миграциями `00NN_evga_*` | копия без правил |
| Риск сломать prof | правки общих apps в общей миграционной истории; `entrypoint.sh` гоняет все сиды | нет | нет |
| Скорость демо | нужны права коммитить в prof и согласование стенда | независимый стенд, свой `docker compose`, свой CI | как B2 |
| Слияние в монорепо | уже там | перенос папок `apps/evga_*` + добавление в `INSTALLED_APPS`/`urls.py`/`entrypoint.sh`; аддитивные правки общих apps переносятся как отдельные миграции | требует выделения `saq_platform`-пакета |
| Тесты/CI | общий `pytest backend` | раздельно | раздельно |

**Принято B2.** Обоснование (одним абзацем): демо на сервере нужно раньше, чем стабилизируется prof и появятся права на его репозиторий; каркас prof стабилен (по `prof-backend-style.md` `core` не менялся с миграции 0002), поэтому копия не «разъедется» за время проекта, если общие приложения меняются только аддитивно. Лучшая деталь — из A §2.1 (запасной вариант «форк с прицелом на слияние»: отдельные миграции `00NN_evga_*`, новые файлы вместо правки существующих, `core/accounts/catalogs/subjects` считаются «чужими») и C §2.1 (правило «`config/`, `core`, `accounts`, `catalogs` — не редактировать, только расширять»).

Правила сосуществования с prof (обязательны для слияния):

1. В общих приложениях (`core`, `accounts`, `catalogs`, `subjects`) допускаются только: новые значения `TextChoices`, новые поля с `null=True`/`default`, новые модели, новые файлы (`services/audit.py`, `querysets.py::assert_department_in_scope`, `api/catalogs_views.py`), новые management-команды `seed_evga_*`. Существующие функции, сигнатуры, миграции и тесты prof не меняются; prof-тесты этих приложений продолжают проходить в CI ЭВГА.
2. Миграции общих приложений именуются `00NN_evga_<что>.py` и не зависят от prof-доменных приложений (`documents`, `cases`, `ersop`, `cabinet`, `execution`, `checklists`, `reporting`, `risk`, `semiannual`), которые в `saq-evga-backend` **не включаются** в `INSTALLED_APPS` (папки не копируются).
3. ЭВГА-приложения импортируют только из `apps.core`, `apps.accounts`, `apps.catalogs`, `apps.subjects`; из prof-доменных приложений — ничего (нужные строки копируются: `Acknowledgement`, `DocumentTransitionError`, `attach_file`, `_assert_subject_owns`, шаблоны view).
4. `config/settings/base.py`: `INSTALLED_APPS` = prof-общие + `apps.notifications, apps.evga_cases, apps.evga_documents, apps.evga_workflow, apps.evga_execution, apps.evga_appeals, apps.evga_ersop, apps.evga_cabinet` (порядок зависимостей); `config/urls.py`: `path("api/evga/…")`, `api/notifications/`, `api/catalogs/`; `SPECTACULAR_SETTINGS.TITLE = "SAQ ЭВГА API"`. Настройки ЭВГА — только с префиксом `EVGA_*`, `ERSOP_*`, `GBD_*`, `KEYCLOAK_ROLE_MAP`, `KEYCLOAK_SYNC_ROLES`, `SIGNING_PROVIDER`.
5. `docker/entrypoint.sh`: к prof-сидам общих приложений (`seed_catalogs`, `seed_roles`, `seed_number_sequences`) добавляются `seed_evga_*` (§9); в `docker-compose.yml` — сервис `scheduler` (§5.7).
6. Коды ролей `evga-*`, ключи последовательностей `evga-*`, домены `evga_*`, `AttachmentKind` со значениями `evga_*`-семантики — так в монорепо не будет коллизий с prof.

**Опция B1 (монорепо), если команда владеет обоими репозиториями**: те же папки `apps/evga_*` кладутся в `backend/apps/` prof-репозитория (он же становится монорепо SAQ: `backend/`, `frontend/` (prof), `frontend-evga/`, `deploy/`); `INSTALLED_APPS`, `urls.py`, `entrypoint.sh`, nginx получают ЭВГА-блоки; общие миграции `00NN_evga_*` применяются к общей БД; лаунчер prof `config/saqModules.ts` переключается на `{id: "evga", type: "internal", url: "/evga/cases"}`. Единственная техническая разница — один `AuthSession` и один `MeSerializer.roles` со всеми ролями SAQ. Решение о B1 принимается после Демо-1.

### 2.2 Фронт

| Критерий | **F1. Отдельный SPA `saq-evga-test` под `/evga/` того же origin (принято)** | F2. Единый SPA (prof-фронт + модуль ЭВГА) |
|---|---|---|
| Объём правок фронта сейчас | минимальный: `BrowserRouter basename="/evga"`, `api/client.ts` (копия prof), `AuthContext`, `EvgaGateway`, `evgaAdapter` | + миграция на Tailwind/Paraglide/общие компоненты, объединение `package.json` |
| Cookie/SSO | same-origin через nginx: `location /evga/ { alias …/saq-evga/; try_files $uri /evga/index.html; }`, `location /api/ → backend` | то же |
| Лаунчер prof | `config/saqModules.ts`: `{id: "evga", type: "external", url: "/evga/cases"}` (сейчас — Vercel-ссылка с `#/cases`) | `type: "internal"` |
| Стили | ЭВГА уже использует `saq-theme.css` (копия оболочки prof) — визуально едино | единый CSS |

F2 — после перевода ЭВГА на API (этап 6 страйглера). Vercel отключается: cookie `SameSite=Lax` не отправляется с чужого домена, а `SameSite=None` + CORS с credentials — ослабление безопасности (`prof-frontend-integration.md` §4.5).

### 2.3 Топология стенда

```
nginx (host)                                     docker compose (saq-evga)
  /evga/  → /var/www/saq-evga (Vite dist ЭВГА)     postgres:16 · minio (+minio-init, бакет saq-evga-attachments)
  /       → /var/www/saq (prof, если на том же хосте) backend (gunicorn :8000): entrypoint = migrate → collectstatic → seed_* → gunicorn
  /api/, /admin/, /static/ → 127.0.0.1:8000        scheduler (тот же образ): python manage.py process_deadlines --loop 300
  client_max_body_size 50m
```

Обновление стенда: `git pull → docker compose up --build -d → npm ci && npm run build (saq-evga-test) → rsync dist/ /var/www/saq-evga/`. Переменные (`deploy/.env.example`): prof-набор + `ERSOP_ADAPTER=stub`, `GBD_ADAPTER=stub`, `SIGNING_PROVIDER=stub`, `KEYCLOAK_SYNC_ROLES=false`, `KEYCLOAK_ROLE_MAP` (JSON, §7.4), `EVGA_DEFAULT_CONTROLLING_BODY=30101`, `EVGA_AUTO_SIGN_REPORT_AFTER_DAYS=`, `EVGA_AUTOCREATE_PREPARATION_DOCS=false`, `EVGA_SIGNATURE_REQUIRED=false`, `EVGA_DEMO_PASSWORD`.

---

## 3. Состав Django-приложений

### 3.1 Приложения, ответственность, порядок создания

Порядок в `INSTALLED_APPS` и порядок реализации совпадают (зависимости моделей идут сверху вниз). Структура каждого ЭВГА-приложения — по чек-листу `prof-backend-style.md` §12: `apps.py` (`name="apps.<name>"`, `label`, русский `verbose_name`), `models.py`, `admin.py`, `api/{views,serializers,urls,filters}.py`, `services/*.py` (по модулю на агрегат/автомат), `management/commands/seed_*.py`, `tests/test_*.py`, `migrations/`.

| № | Приложение (`label`) | Ответственность | Происхождение | Ключевые модели | Ключевые сервисы |
|---|---|---|---|---|---|
| 1 | `core` | базовая модель, вложения, журнал, нумерация, ошибки, пагинация | **prof как есть + аддитивно** | `TimeStampedModel`, `Attachment`(+`slot`), `AuditEvent`(+4 поля), `NumberSequence`, `IssuedNumber` | `services/{files,numbering}.py` (как есть), новый `services/audit.py::record_event`, новый `exceptions.py::ConflictError` |
| 2 | `catalogs` | общие справочники prof + справочники ЭВГА, read-only API | **prof как есть + аддитивно** | prof: `Region`, `Department`, `GovernmentBody`, `NormativeAct`; новые: `BilingualCodeNamedModel` (абстракт), `AuditType`, `InspectionType`, `BasisKind`, `Initiator`, `LegalForm`, `RiskLevel`, `RiskObjectType`, `ViolationType`, `ConsequenceType`, `RemediationStatus`, `AuditIndicator`, `SamplingMethod`, `ResponseMeasureKind`, `AuditQuestion`, `ControllingBody`, `Position`, `DeadlineRule`, `ProductionCalendarDay`, `LegalBasisAudit`, `QueryCheckNpa` | `seed_catalogs` (prof), новые `seed_evga_catalogs`, `seed_evga_calendar`, `seed_evga_deadline_rules`; новый `api/views.py::CatalogViewSet` |
| 3 | `accounts` | пользователи, сессии, Keycloak, роли/уровни/скоуп | **prof как есть + аддитивно** | `User`(+`iin`), `Role`, `RolePermission`, `RoleAssignment`, `AuthSession`, `OidcAuthRequest`, `FederatedIdentity`(+`origin_subject`) | `services/{keycloak,sessions}.py` (+6 строк в `provision_user_from_claims`), новый `services/role_sync.py`, `querysets.py` (+`assert_department_in_scope`), `seed_evga_roles`, новый `api/users_views.py::UserDirectoryViewSet` |
| 4 | `subjects` | объект аудита (= `Subject` расширенный), перечень на год, ГБД | **prof как есть + аддитивно** | `Subject`(+7 полей), `SubjectPerson` (не используется), новая `AnnualPlanEntry` | `validators.py` (как есть), новый `services/gbd.py`, новый `api/views.py::SubjectLookupView`, `seed_evga_audit_objects` |
| 5 | `notifications` | in-app уведомления | **новое** | `Notification` | `services/notify.py::notify, recipients_for_version` |
| 6 | `evga_cases` | дело, основания, рабочая группа, соавторы, назначения КК, календарь, доп. поручения, сроки, ход исполнения, реестр дел, агрегат `workspace`, реестр КК | **новое по шаблону `cases`** | `AuditCase`, `CaseBasis`, `CaseParticipant`, `CaseCoauthor`, `QualityAssignment`, `CaseCalendarDay`, `CaseAmendment` | `services/{cases,case_status,quality_assignment,deadlines,progress,amendments,workspace,quality_registry,exceptions}.py`, `seed_evga_number_sequences`, `seed_evga_users`, `seed_evga_demo_cases` |
| 7 | `evga_documents` | типы/схемы/шаблоны, документы, версии, черновики, валидация, автоматы документа, реестр действий, подписи, источники, доставка, подтверждения, требования сведений, печатный контекст, проекция нарушений | **новое по шаблону `documents`** | `EvgaDocumentType`, `FormSchema`, `WorkingPaperTemplate`, `AuditDocument`, `DocumentVersion`, `VersionParticipant`, `DocumentSignature`, `DocumentSourceVersion`, `Acknowledgement`(копия), `DocumentDelivery`, `KvgaConfirmation`, `RegistryConfirmation`, `InformationRequestRound`, `Violation`, `AuditQuestionRow` (опц.), `RiskObjectRow` (опц.) | `workflows/{route,preparation,main,quality,direct}.py` (константы переходов), `services/{exceptions,factory,drafts,validation,actions,state_machine,revisions,preparation,main,quality,registry,delivery,information_requests,attachments,print_context,permissions,commit,gates}.py`, `seed_evga_document_types`, `seed_evga_form_schemas`, `seed_evga_working_papers`, `process_deadlines` |
| 8 | `evga_workflow` | маршруты согласования, задачи (инбокс) | **новое (порт `shared/workflow/approvalRoute.ts`)** | `ApprovalRoute`, `ApprovalStage`, `ApprovalParticipant`, `ApprovalEvent` | `services/{routes,tasks,candidates}.py` |
| 9 | `evga_ersop` | регистрация в ЕРСОП/КПСиСУ, журнал обмена, заглушка, SOAP-адаптер | **копия `ersop` с заменой агрегата** | `ErsopRegistration`, `ErsopExchange` | `services/{registration,payload,stub_exchange,soap_exchange}.py` |
| 10 | `evga_execution` | пункты предписания/рекомендации, меры ответа, реестр исполнения | **новое по шаблону `execution`** | `PrescriptionItem`, `Recommendation`, `ResponseMeasure` (проекции) | `services/{items,responses}.py` |
| 11 | `evga_appeals` | возражения/апелляция, третьи лица | **новое** | `Appeal`, `AppealArgument`, `ThirdPartyNotice`, `ThirdPartyEvent` | `services/{appeals,third_parties}.py` |
| 12 | `evga_cabinet` | API представителя ОА | **копия `cabinet` с заменой агрегата** | — | — (view + сериализаторы с контекстом `cabinet`) |

Порядок создания (итерации §11): `core/accounts/catalogs/subjects` (аддитивно) → `notifications` → `evga_cases` → `evga_documents` → `evga_workflow` → `evga_ersop` → `evga_cabinet` → `evga_execution` → `evga_appeals`.

Домены прав ↔ приложения не совпадают 1:1 (как и в prof, где домен `cases` используется view'ами `documents`): `evga_cases` — дела, документы, маршруты, доставка, ЕРСОП; `evga_quality` — назначение экспертов, реестр КК, подпись/отправка КК2; `evga_registry` — подтверждающий реестра и КВГА (уровень `CONFIRM`); `evga_appeals` — апелляция, третьи лица (чтение); `evga_execution` — реестр исполнения; `evga_cabinet` — действия представителя ОА; `evga_admin` — стенд-действия (`ersop/register/`, `close/`); `dsp` — доступ к делам с `dsp=True`.

### 3.2 Пофайловая карта: копируется как есть / адаптируется / пишется заново

| Файл prof (`backend/`) | Вердикт | Что делаем в `saq-evga-backend` |
|---|---|---|
| `manage.py`, `pyproject.toml` (ruff 120, pytest `--reuse-db`), `requirements/{base,local,production}.txt` | **как есть** | + `httpx` уже есть; `weasyprint` — только в итерации серверного PDF |
| `config/settings/{base,local,production}.py`, `config/{urls,wsgi,asgi}.py` | **как есть + add** | `INSTALLED_APPS`/URL ЭВГА, `SPECTACULAR_SETTINGS.TITLE`, блок настроек `EVGA_*`; `TIME_ZONE` не трогаем |
| `Dockerfile`, `docker/entrypoint.sh`, `docker-compose.yml`, `deploy/README.md`, `deploy/.env.example`, `deploy/nginx.conf` | **как есть + add** | сиды ЭВГА в entrypoint; сервис `scheduler`; nginx-блок `/evga/`; `client_max_body_size 50m`; бакет `saq-evga-attachments` |
| `apps/core/models.py` | **как есть + add** | `AttachmentKind` +11 значений; `Attachment.slot CharField(128, blank)`; `AuditAction` +13; `AuditEvent` +`case`, `action_code`, `source`, `metadata` (миграция `core/000N_evga_audit_event.py`) |
| `apps/core/{middleware,views,pagination,admin}.py`, `services/{files,numbering}.py`, `tests/*` | **как есть** | 0 правок |
| `apps/core/exceptions.py` | **как есть + add** | новый класс `ConflictError(APIException)` (`status_code=409`, `default_code="stale_version"`); `exception_handler` не меняется |
| `apps/core/services/audit.py` | **новый** | `record_event()` |
| `apps/core/management/commands/seed_number_sequences.py` | **как есть** | ЭВГА-последовательности — отдельная команда `seed_evga_number_sequences` в `evga_cases` (тот же шаблон `define_sequence`) |
| `apps/accounts/models.py` | **как есть + add** | `User.iin`; `FederatedIdentity.origin_subject`; `PermissionDomain` +8; `PermissionLevel` +`CONFIRM` |
| `apps/accounts/{authentication,permissions,schema}.py`, `services/sessions.py`, `api/{keycloak_views,local_views,serializers,urls}.py` | **как есть** | `MeSerializer` дополняется полями `iin`, `account` через наследник `EvgaMeSerializer` в `evga_cases/api/serializers.py`? — нет: `MeSerializer` расширяется аддитивно двумя полями (`iin`, `position` уже есть); `account` формирует фронт (`accountFromUser`) |
| `apps/accounts/services/keycloak.py::provision_user_from_claims` | **как есть + 6 строк** | `iin` из `preferred_username` (`^\d{12}$`, `iin_validator`), `first_name/last_name`, `origin_subject` из `origin_user_id`; вызов `role_sync.sync_role_assignments_from_claims` под флагом `KEYCLOAK_SYNC_ROLES` |
| `apps/accounts/services/role_sync.py` | **новый** | порт `User Login Sync` (§7.4) |
| `apps/accounts/querysets.py` | **как есть + add** | `assert_department_in_scope(user, department)` (копия `_assert_department_in_scope` из `documents/api/views.py`), константа `READ_LEVELS` |
| `apps/accounts/management/commands/seed_roles.py` | **как есть** | роли ЭВГА — отдельная `seed_evga_roles` (тот же `update_or_create`) |
| `apps/accounts/api/users_views.py` | **новый** | `GET /api/accounts/users/?role=&department=&search=` (справочник сотрудников для РГ/маршрутов/назначений) |
| `apps/catalogs/models.py`, `seed_catalogs.py`, `tests/*` | **как есть + add** | абстракт `BilingualCodeNamedModel`; модели §4.4; prof-специфичные `SubjectTypeRef`, `BusinessCategory`, `ViolationSeverity`, `RiskDegree`, `InspectionSubjectMatter`, `ControlEligibilityRule` остаются (не используются, не удаляются — аддитивность) |
| `apps/catalogs/api/{views,serializers,urls}.py` | **новый** | read-only `CatalogViewSet` по slug → модель (§6.10) |
| `apps/subjects/{models,validators,admin}.py`, `api/*`, `tests/*` | **как есть + add** | `Subject` +`name_kk, director, legal_form_ref, abp, risk_level, risk_score, controlling_body`; `AnnualPlanEntry`; `services/gbd.py`; `api/views.py` +`SubjectLookupView`, `PreviousAuditsView`, `PlanEntryViewSet` |
| `apps/documents/models.py::DocumentType` + `seed_document_types.py` | **адаптировать (копия в `evga_documents`)** | `EvgaDocumentType` с флагами ЭВГА; сид из `data/evga/document_types.json` |
| `apps/documents/models.py::DocumentStatus`, `_STATUS_LABEL_OVERRIDES`, `document_status_label` | **адаптировать (копия)** | 11 статусов ЭВГА + `LEGACY_STATUS_MAP` |
| `apps/documents/models.py::Acknowledgement`, `services/acknowledgement.py` | **копия** | FK на `DocumentVersion`; `record_acknowledgement(version, *, channel, by, acknowledged_on, proof_ref, attachment)` |
| `apps/documents/services/{exceptions,attachments}.py` | **копия** | `DocumentTransitionError`, `StaleVersionError`; `attach_version_file`/`version_attachments`/`delete_version_attachment` |
| `apps/documents/api/views.py` (шаблон `ApproveDocumentView`, `DownloadAttachmentView`, `_READ_LEVELS`) | **копия шаблона** | базовый `DocumentActionView` + ~35 наследников по одному на действие |
| `apps/documents/api/serializers.py` (`AttachmentSerializer`, request-сериализаторы, контекст `cabinet`) | **копия шаблона** | `AttachmentRefSerializer`, `DocumentVersionSerializer`, `DocumentSerializer`, request-сериализаторы действий |
| `apps/cases/api/{views,filters}.py` (`CaseRegistryViewSet`, `CaseRegistryFilter.filter_search`, `CaseWorkspaceView`) | **копия шаблона** | реестр дел ЭВГА, `workspace`; фильтр по статусу — по колонкам, а не Python-проходом |
| `apps/cases/services/case_status.py` | **копия паттерна** | `compute_quality`, `compute_stage`, `completion_block` |
| `apps/semiannual/models.py::SemiannualListVersion` | **копия паттерна** | `DocumentVersion` (номер версии, `*_at/*_by`, неизменяемость) |
| `apps/ersop/models.py`, `services/{stub_exchange,package_1}.py`, `api/*` | **копия с заменой агрегата** | `ErsopRegistration` вместо `ErsopPackage`; `fake_register_document` вместо `fake_register_package` |
| `apps/cabinet/api/{views,serializers,urls}.py` | **копия с заменой агрегата** | `_assert_subject_owns`, `CabinetCaseViewSet`, `CabinetDocumentViewSet` (версии с `DocumentDelivery.sent_at`), download-view с `{"cabinet": True}`; действия ОА — те же `DocumentActionView` с `cabinet=True` |
| `apps/execution/models.py` (`PrescriptionItem.status` property, `PrescriptionItemFilter`) | **копия паттерна** | проекции + `execution_items` |
| `apps/checklists/*`, `apps/reporting/*`, `apps/risk/*`, `apps/semiannual/*`, `apps/documents/*`, `apps/cases/*`, `apps/ersop/*`, `apps/cabinet/*`, `apps/execution/*` | **не копируются** | prof-домен; нужные строки скопированы точечно (см. выше) |
| `apps/*/tests/*` общих приложений | **как есть** | продолжают проходить; хелперы `_user_with_cases_role`, `_department` копируются в `apps/evga_cases/tests/helpers.py` как `_user_with_role(code, department=None)` |
| `backend/saq-cookies.txt` | **не копировать** | артефакт curl с реальной cookie (`prof-backend-style.md` §11 п.2); добавить в `.gitignore` |

---

## 4. Модель данных

### 4.1 Соглашения (из prof, применяются без исключений)

* Все доменные модели наследуют `core.TimeStampedModel` (UUID pk, `created_at/updated_at/created_by`); `created_by` передаётся явно из сервиса.
* Статусы — `models.TextChoices`, значение UPPER_SNAKE, label по-русски (там, где есть строка фронта — она дословно). Числовые — `IntegerChoices` (`Stage`).
* FK на актора — `null=True, blank=True, on_delete=SET_NULL, related_name="+"`; на справочник — `PROTECT`; ребёнок → агрегат — `CASCADE`; сущность процесса → сущность процесса — `PROTECT`.
* Натуральные ключи — `UniqueConstraint(name="<app>_<model>_natural_key")`; `__str__` через ` · `; `Meta.ordering`; индексы только под реальные фильтры.
* Вложения — `GenericRelation("core.Attachment")`; файлы в JSON не хранятся — только ссылки `AttachmentRef {id, name, type, size, url}` (форма `Upload` фронта без `data`).
* Вычисляемое — `@property` + функция в `services/*_status.py`; денормализованный кеш допустим, если пересчитывается в той же транзакции.
* Snapshot-поля ФИО/должности (`full_name`, `position`) хранятся рядом с FK, как в legacy (`case_participants.user_iin` + `evga_users_with_roles.user_fullname`), чтобы печатные формы не менялись после кадровых изменений.

### 4.2 `core` — аддитивные изменения

```python
# apps/core/models.py (добавления; prof-значения не трогаем)
class AttachmentKind(models.TextChoices):
    ...  # 7 значений prof без изменений
    DOCUMENT_FILE = "document_file", "Вложение документа"                # DocumentVersion.attachments (Upload[] версии)
    FORM_ROW_FILE = "form_row_file", "Файл строки формы"                 # values.<section>[].files, IrpiRow.files, permissionFiles (slot = "values:<section>:<row_id>")
    BASIS_DOCUMENT = "basis_document", "Документ-основание"             # Basis.attachments; surfk.case_base_attachments
    CASE_FILE = "case_file", "Вложение дела"                             # AuditCase.attachments
    OBJECT_RESPONSE = "object_response", "Ответ объекта аудита"         # delivery.attachments
    REFUSAL_PROOF = "refusal_proof", "Подтверждение отказа/возражений"  # delivery.decisionAttachments
    REQUEST_RESPONSE = "request_response", "Сведения по требованию"      # informationRequest.rounds[].response.attachments
    APPEAL_FILE = "appeal_file", "Материалы апелляции"                  # appeal.admission.files, notify files, arguments.rows[].files
    THIRD_PARTY_FILE = "third_party_file", "Материалы третьего лица"    # thirdParties[].*Files
    PRINT_FORM = "print_form", "Печатная форма (PDF)"                    # серверный PDF (итерация 11)
    SIGNED_PDF = "signed_pdf", "Подписанный PDF (CMS)"                   # ЭЦП NCALayer (позже)

class AuditAction(models.TextChoices):
    ...  # create, approve, sign, send, acknowledge, decide, exchange — как в prof
    SUBMIT = "submit", "Направление на согласование"
    RETURN = "return", "Возврат на доработку"
    REJECT = "reject", "Отклонение"
    RECALL = "recall", "Отзыв"
    ACTIVATE = "activate", "Активация"
    CONFIRM = "confirm", "Подтверждение"
    ASSIGN = "assign", "Назначение"
    REGISTER = "register", "Регистрация"
    DELIVER = "deliver", "Направление объекту"
    QUALITY = "quality", "Контроль качества"
    NEW_VERSION = "new_version", "Новая версия"
    DELETE = "delete", "Удаление"
    UPDATE = "update", "Изменение"

class AuditEventSource(models.TextChoices):                  # surfk.evga_audit_log.source: user|zeebe|system|ersop|timer
    USER = "user", "Пользователь"; SYSTEM = "system", "Система"; ERSOP = "ersop", "ЕРСОП"; TIMER = "timer", "Таймер"

class Attachment(models.Model):
    ...  # prof без изменений
    slot = models.CharField(max_length=128, blank=True)      # "values:violations:<row_id>" | "delivery" | "delivery.decision" | "information-request:<round_order>"

class AuditEvent(models.Model):
    ...  # поля prof без изменений (content_object, action, status_from/to, actor, actor_role, occurred_at, reason, attachment, exchange_id)
    case = models.ForeignKey("evga_cases.AuditCase", null=True, blank=True, on_delete=models.SET_NULL, related_name="events", db_index=True)  # surfk.evga_audit_log.case_id
    action_code = models.CharField(max_length=64, blank=True)    # точный код действия из ACTIONS (submit, kvga-decide, ersop-send…) + legacy-код в metadata
    source = models.CharField(max_length=16, choices=AuditEventSource.choices, default=AuditEventSource.USER)
    metadata = models.JSONField(default=dict, blank=True)        # {"version": n, "legacy_code": "kvga_confirm", "field_changes": [...]} = surfk.evga_audit_log.field_changes/metadata
```

`core/services/audit.py`:

```python
def record_event(target, *, action: str, actor=None, action_code: str = "", status_from: str = "", status_to: str = "",
                 reason: str = "", case=None, source: str = AuditEventSource.USER, metadata: dict | None = None,
                 attachment=None, exchange_id: str = "") -> AuditEvent:
    """Единственная точка записи журнала (ТЗ табл. 49). Вызывается из каждой transition-функции после save()."""
```

Соответствие: `HistoryEntry {id, at, actor, action, comment}` фронта = `id, occurred_at, actor.full_name (или actor_role)`, `reason` (человекочитаемое действие), `metadata.comment`; журналы legacy `surfk.evga_audit_log`, `evga_document_workflow_history`, `evga_document_approvals`, `case_status_history`, `case_activity_log` — все сводятся к этой таблице (лента «согласований» = выборка событий с `action in {approve, sign, return, reject, confirm}`).

### 4.3 `accounts` — аддитивные изменения

```python
class User(AbstractUser):
    ...
    iin = models.CharField(max_length=12, blank=True, null=True, unique=True, validators=[iin_validator])  # surfk.users.iin = preferred_username

class FederatedIdentity(models.Model):
    ...
    origin_subject = models.CharField(max_length=64, blank=True)   # claim origin_user_id (surfk.users.origin_user_id)

class PermissionDomain(models.TextChoices):
    SEMIANNUAL, CASES, EXECUTION                                    # prof, не трогаем
    EVGA_CASES = "evga_cases", "ЭВГА: дела и документы"
    EVGA_QUALITY = "evga_quality", "ЭВГА: контроль качества"
    EVGA_REGISTRY = "evga_registry", "ЭВГА: подтверждение КВГА и реестра"
    EVGA_APPEALS = "evga_appeals", "ЭВГА: возражения и апелляция"
    EVGA_EXECUTION = "evga_execution", "ЭВГА: исполнение"
    EVGA_CABINET = "evga_cabinet", "ЭВГА: кабинет объекта аудита"
    EVGA_ADMIN = "evga_admin", "ЭВГА: администрирование"
    DSP = "dsp", "Доступ к документам ДСП"                          # permission-домен, не роль (Keycloak dsp_access)

class PermissionLevel(models.TextChoices):
    NONE, VIEW, EDIT, APPROVE, SIGN, DECIDE                         # prof
    CONFIRM = "confirm", "Подтверждение"                            # подтверждающий КВГА / реестра (legacy evga_roles.can_confirm_documents)
```

`User.is_subject_representative` + `User.subject` (FK на `subjects.Subject`) — без изменений: представитель объекта аудита. `Role`, `RolePermission`, `RoleAssignment`, `RoleAssignmentQuerySet.active()`, `HasDomainLevel`, `IsSubjectRepresentative`, `ScopedQuerySetMixin` — без изменений кода.

### 4.4 `catalogs` — справочники ЭВГА

Абстракт (новый, рядом с `CodeNamedModel`): `BilingualCodeNamedModel(code unique, name_ru, name_kk, order, is_active)`; сериализатор отдаёт `name` по `Accept-Language`, всегда `name_ru/name_kk` (суффикс `kk`, как в prof `Region`, а не `kz`, как в `surfk`).

| Модель | Поля сверх базовых | Источник (`surfk.*` / фронт) |
|---|---|---|
| `AuditType` | `is_financial: bool`, `ersop_code` | `audit_types(code, name_ru, name_kz, ersop_code)`; legacy id 7 — соответствие, 8 — фин. отчётность; BPMN `auditTypeCode` `"15"`/`"16"`; фронт `auditTypeOptions` |
| `InspectionType` | `is_planned: bool` | `inspection_types(code '1'/'2')`, `PLANNED_CODES = ['1','scheduled']`; фронт `checkTypeOptions` (+ «Встречная проверка») |
| `InspectionKind` | — | `inspection_kind_id` 24 «Совместная проверка» / 25 «Параллельная проверка» (захардкожено в `Get Case Detail`); фронт `checkKind` |
| `BasisKind` | `qc_route_kvga: bool = False` (резерв, решение 10) | `control_reasons_types(code, name_ru, name_kz)`; фронт `basisOptions` (6); коды `13/14` → `qc_route = 'KK KVGA'` (`Get Case Bases`) — семантика **не подтверждена** |
| `Initiator` | — | `check_initiators`; фронт `initiatorOptions` (14) |
| `LegalForm` | `gbd_code` | `organizational_legal_forms(code, name_ru, name_kz)`; ГБД `orgFormCode` |
| `RiskLevel` | `order` | `risk_levels`; фронт `Высокая/Средняя/Низкая` |
| `RiskObjectType` | `legacy_aliases JSON` | `risk_object_types` (`PPContractItem, PICustomer, PPContractHeader, PPPlanItem, QGAccountBalances, BudgetExpenditure, FinancialReporting`; маппинг из `violations`); фронт `riskFields.riskType` (7) |
| `ViolationType` | `parent FK(self)`, `is_group`, `level_ru/kk`, `sort_key` (натуральная сортировка `1.2.10` после `1.2.9`) | `offense_type(type_code, parent_code, offence_name_ru/kz, level_ru/kz)`; endpoint `/tree/` |
| `ConsequenceType` | — | `dictionaries[dic_name='type_cons_offence']`; фронт `consequence` (7) |
| `RemediationStatus` | — | `dictionaries[dic_name='status_offense']`; фронт `remediation` («Не устранено / Устранено частично / Устранено / Не подлежит устранению») — единый список |
| `AuditIndicator` | — | фронт `questionFields.indicator` (4) |
| `SamplingMethod` | — | `sampling_methods`; фронт `method` |
| `ResponseMeasureKind` | — | `response_measures` |
| `AuditQuestion` | `theme_ru/kk, sub_theme_ru/kk, program_ru/kk, npa` | `evga_audit_questions(code_id, reg_number, theme_ru/kz, sub_theme_ru/kz, program_ru/kz, npa)` |
| `ControllingBody` | `bin, parent FK(self), short_name_ru/kk, org_type, org_level, su_code, ersop_organ_code, department OneToOne catalogs.Department` | `controlling_bodies(code, name_ru, name_kz)` + `d_controlling_orgs(code, bin, par_id, org_type_id, org_lvl_id, su_code)`; `30101` — КВГА ЦА; prof `GovernmentBody` остаётся для бланка |
| `Position` | — | `positions(name_ru, name_kz)` |
| `LegalBasisAudit` | — | `evga_legal_basis_audit(code, name_ru, name_kz)` — `legal_basis_id` учётной карточки (ЕРСОП) |
| `QueryCheckNpa` | `query_check_code, npa_code` | `d_query_check_npa` → `checkQuery{checkQueryCode:'0'+code, checkThemeCode:'0'+npa_code}` ЕРСОП |
| `DeadlineRule` | `label, source_act FK NormativeAct, days, calendar ∈ {business, calendar}, anchor, completion, applies_when` | `deadlines.ts::auditDeadlines` (15 правил) + `qualityDays` |
| `ProductionCalendarDay` | `date unique, is_working, note` + `ProductionCalendarYear(year unique, is_confirmed)` | глобальный календарь РК (во фронте — `AuditCase.calendar`) |

`Region`, `Department`, `GovernmentBody`, `NormativeAct` — prof как есть (в `NormativeAct` сидируются № 392, 413, 113, 272, 873, 480, 162, Закон о госаудите, `V1700015209`, `V2200026715`).

### 4.5 `subjects` — объект аудита и перечень

Объект аудита — `subjects.Subject` prof, расширенный аддитивно (в тексте документа и в DTO фронта он называется `AuditObject`; для читаемости в `evga_cases/models.py` допустим `class AuditObject(Subject): class Meta: proxy = True`).

```python
class Subject(TimeStampedModel):          # prof: bin (unique, bin_validator), name, subject_type, business_category, legal_form, registration_*, actual_region, department, gbd_synced_at
    ...
    name_kk = models.CharField(max_length=500, blank=True)                       # AuditObject.kz; surfk.audit_objects.name_kz
    director = models.CharField(max_length=255, blank=True)                      # AuditObject.director; surfk.audit_objects.director
    legal_form_ref = models.ForeignKey("catalogs.LegalForm", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")  # opf; surfk.org_legal_form_id
    abp = models.CharField(max_length=500, blank=True)                           # AuditObject.abp
    risk_level = models.ForeignKey("catalogs.RiskLevel", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")   # risk; surfk.risk_level_id
    risk_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)                                    # score; surfk.risk_value
    controlling_body = models.ForeignKey("catalogs.ControllingBody", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    gbd_payload = models.JSONField(default=dict, blank=True)                     # нормализованный ответ ГБД ЮЛ (Map to JSON)

    def as_snapshot(self) -> dict: ...    # {bin, ru, kz, director, opf, abp, address, region, risk, score} — форма AuditObject фронта

class AnnualPlanEntry(TimeStampedModel):  # surfk.annual_plans + plan_objects; фронт catalogue/plannedDemoObjects/plannedBasisFor
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="plan_entries")
    year = models.PositiveSmallIntegerField()
    plan_title_ru = models.CharField(max_length=500, blank=True)
    plan_order_number = models.CharField(max_length=64, blank=True); plan_order_date = models.DateField(null=True, blank=True)
    audit_type = models.ForeignKey("catalogs.AuditType", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    coverage_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    coverage_by_year = models.JSONField(default=dict, blank=True)   # {"2023": …} (plan_data.coverage_2023..2025)
    score_by_year = models.JSONField(default=dict, blank=True)      # score_2023..2025, score_3_years, max_score, risk_level_gu/abp, risk_probability
    class Meta: constraints = [UniqueConstraint(fields=["subject", "year"], name="subjects_annualplanentry_natural_key")]
```

Физлицо для встречной проверки — поля на `AuditCase` (`person_type`, `person_iin`, `person_name`, `person_birth_date`, `entrepreneur_name`); `SubjectPerson` prof не используется (объект встречной проверки-ЮЛ — тот же `Subject`).

### 4.6 `evga_cases`

```python
# apps/evga_cases/models.py
class CaseStatus(models.TextChoices):
    OPEN = "OPEN", "Открыто"; CLOSED = "CLOSED", "Закрыто"           # surfk.case_statuses: open | closed

class ExecutionState(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", "Проводится"; SUSPENDED = "SUSPENDED", "Приостановлено"; CANCELLED = "CANCELLED", "Отменено"

class CheckKind(models.TextChoices):
    NONE = "", "—"; JOINT = "JOINT", "Совместная"; PARALLEL = "PARALLEL", "Параллельная"; COUNTER = "COUNTER", "Встречная"

class PersonType(models.TextChoices):
    LEGAL = "LEGAL", "Юридическое лицо"; NATURAL = "NATURAL", "Физическое лицо"

class Stage(models.IntegerChoices):
    PREPARATION = 0, "Подготовительный этап"; MAIN = 1, "Основной этап"; FINAL = 2, "Заключительный этап"
    # surfk.evga_document_stages: 1 «Планирование аудита», 2 «Проведение аудита», 3 «Документы по результатам…» → legacy_stage_id = stage + 1

class AuditCase(TimeStampedModel):                                   # surfk.cases; types.ts AuditCase
    number = models.CharField(max_length=32, unique=True)            # 30101-YY-NNNNN / {parent}/ВП-N (issue_number); surfk.cases.registration_number
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="counter_cases")  # parentCaseId; surfk.cases.parent_id (sub_case_type='counter_control')
    department = models.ForeignKey("catalogs.Department", on_delete=models.PROTECT, related_name="+")   # орган контроля (prof-скоуп), из RoleAssignment автора
    controlling_body = models.ForeignKey("catalogs.ControllingBody", on_delete=models.PROTECT, related_name="+")  # surfk.cases.controlling_body_id; org в номере
    subject = models.ForeignKey("subjects.Subject", on_delete=models.PROTECT, related_name="audit_cases")  # object.bin; surfk.audit_object_id
    subject_snapshot = models.JSONField(default=dict)                # AuditObject на момент создания (Q01)
    joint_subject = models.ForeignKey("subjects.Subject", null=True, blank=True, on_delete=models.PROTECT, related_name="+")  # jointObject; surfk joint_inspection_bin
    plan_entry = models.ForeignKey("subjects.AnnualPlanEntry", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")  # surfk.plan_object_id
    audit_type = models.ForeignKey("catalogs.AuditType", on_delete=models.PROTECT, related_name="+")
    inspection_type = models.ForeignKey("catalogs.InspectionType", on_delete=models.PROTECT, related_name="+")   # checkType
    inspection_kind = models.ForeignKey("catalogs.InspectionKind", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    check_kind = models.CharField(max_length=16, choices=CheckKind.choices, blank=True)
    electronic = models.BooleanField(default=False); dsp = models.BooleanField(default=False)   # is_electronic_audit, is_dsp
    purpose_ru = models.TextField(); purpose_kk = models.TextField()  # audit_goal_ru/kz
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")  # author (ФИО во фронте → FK; author_iin в legacy)
    author_name = models.CharField(max_length=255)                   # снимок ФИО
    status = models.CharField(max_length=16, choices=CaseStatus.choices, default=CaseStatus.OPEN)
    execution_state = models.CharField(max_length=16, choices=ExecutionState.choices, default=ExecutionState.IN_PROGRESS)
    closed_at = models.DateTimeField(null=True, blank=True)
    schedule_start = models.DateField(null=True, blank=True); schedule_end = models.DateField(null=True, blank=True)   # schedule; surfk start_date/end_date
    period_from = models.DateField(null=True, blank=True); period_to = models.DateField(null=True, blank=True)
    quality_stage_passed = models.JSONField(default=three_false)     # quality[3] — кеш, пересчёт compute_quality() в транзакции коммита
    document_sequence = models.PositiveIntegerField(default=0)       # documentSequence фронта (номера удалённых не переиспользуются)
    calendar_confirmed_years = models.JSONField(default=list)        # calendar.confirmedYears
    # встречная проверка (CounterChecks.tsx; surfk sub_case_data)
    person_type = models.CharField(max_length=8, choices=PersonType.choices, blank=True)
    person_iin = models.CharField(max_length=12, blank=True); person_name = models.CharField(max_length=255, blank=True)
    person_birth_date = models.DateField(null=True, blank=True); entrepreneur_name = models.CharField(max_length=255, blank=True)
    counter_question = models.TextField(blank=True)
    # третьи лица: «проверено, затронутых нет» (thirdPartiesReviewed)
    third_parties_reviewed_at = models.DateTimeField(null=True, blank=True)
    third_parties_reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    third_parties_none = models.BooleanField(null=True, blank=True); third_parties_reason = models.TextField(blank=True)
    is_deleted = models.BooleanField(default=False); deleted_at = models.DateTimeField(null=True, blank=True)   # surfk soft delete
    attachments = GenericRelation("core.Attachment", content_type_field="content_type", object_id_field="object_id")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["department", "status"]), models.Index(fields=["subject"]), models.Index(fields=["parent"])]

    @property
    def stage(self) -> int: ...            # compute_stage() по quality_stage_passed
    @property
    def is_registered(self) -> bool: ...   # registered(audit): account/counter-account с ErsopRegistration.status == REGISTERED
    def document(self, kind: str) -> "AuditDocument | None": ...   # кэш по коду вида (как ControlCase.document(code)); для repeatable — последний неудалённый

class CaseBasis(TimeStampedModel):                                   # Basis[]; surfk.case_bases
    case = models.ForeignKey(AuditCase, on_delete=models.CASCADE, related_name="bases")
    kind = models.ForeignKey("catalogs.BasisKind", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    kind_text = models.CharField(max_length=500)                     # basis_ru (снимок; для приказов из additional: order.basisRu || reason || type)
    kind_text_kk = models.CharField(max_length=500, blank=True)      # basis_kz
    initiator = models.ForeignKey("catalogs.Initiator", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    initiator_text = models.CharField(max_length=500, blank=True)    # initiator_ru
    number = models.CharField(max_length=128); date = models.DateField(); order = models.PositiveSmallIntegerField(default=0)   # number, basis_date, sort_order
    source_version = models.ForeignKey("evga_documents.DocumentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")  # additional-<docId>-v<n>
    attachments = GenericRelation("core.Attachment", ...)            # kind=basis_document; surfk.case_base_attachments

class CaseParticipant(TimeStampedModel):                             # group: Person[]; surfk.case_participants
    case = models.ForeignKey(AuditCase, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")   # user_iin → FK (Person.id = User.id — условие подписей РГ)
    full_name = models.CharField(max_length=255); position = models.CharField(max_length=255, blank=True); organization = models.CharField(max_length=255, blank=True)
    is_leader = models.BooleanField(default=False)                   # is_lead
    is_invited_specialist = models.BooleanField(default=False)       # роль invited-specialist / member_role_code='invited_specialist'
    order = models.PositiveSmallIntegerField(default=0)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_active = models.BooleanField(default=True); removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    class Meta:
        constraints = [UniqueConstraint(fields=["case", "user"], condition=Q(is_active=True), name="evga_cases_caseparticipant_natural_key"),
                       UniqueConstraint(fields=["case"], condition=Q(is_leader=True, is_active=True), name="evga_cases_caseparticipant_single_leader")]

class CaseCoauthor(TimeStampedModel):                                # coauthors[] (legacy: нет)
    case = models.ForeignKey(AuditCase, on_delete=models.CASCADE, related_name="coauthors")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    class Meta: constraints = [UniqueConstraint(fields=["case", "user"], name="evga_cases_casecoauthor_natural_key")]

class QualityRoute(models.TextChoices):
    KK = "kk", "Контроль качества"; KK_KVGA = "kk_kvga", "Контроль качества КВГА"   # резерв (решение 10), не активируется

class QualityAssignment(TimeStampedModel):                           # qualityAssignments[stage]; surfk.case_qc_expert_assignments (+ case_qc_assignments для руководителя КК → роль)
    case = models.ForeignKey(AuditCase, on_delete=models.CASCADE, related_name="quality_assignments")
    stage = models.PositiveSmallIntegerField(choices=Stage.choices)
    expert = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.TextField(blank=True)                            # причина замены (обязательна при повторном назначении)
    route = models.CharField(max_length=8, choices=QualityRoute.choices, default=QualityRoute.KK)
    unassigned_at = models.DateTimeField(null=True, blank=True)      # история assigned/unassigned (legacy action)
    class Meta: constraints = [UniqueConstraint(fields=["case", "stage"], condition=Q(unassigned_at__isnull=True), name="evga_cases_qualityassignment_active")]

class CaseCalendarDay(TimeStampedModel):                             # calendar.holidays / workingDates — переопределения по делу
    case = models.ForeignKey(AuditCase, on_delete=models.CASCADE, related_name="calendar_days")
    date = models.DateField(); is_working = models.BooleanField()
    class Meta: constraints = [UniqueConstraint(fields=["case", "date"], name="evga_cases_casecalendarday_natural_key")]

class CaseAmendment(TimeStampedModel):                               # amendments[]
    case = models.ForeignKey(AuditCase, on_delete=models.CASCADE, related_name="amendments")
    order_version = models.ForeignKey("evga_documents.DocumentVersion", on_delete=models.PROTECT, related_name="+")
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    targets = models.JSONField(default=list)                         # [{document_id, from_version, to_version}]
    class Meta: constraints = [UniqueConstraint(fields=["order_version"], name="evga_cases_caseamendment_natural_key")]  # «версия ещё не применялась»
```

### 4.7 `evga_documents`

```python
# apps/evga_documents/models.py
class Workflow(models.TextChoices):                 # семейство автомата = ключ диспетчеризации переходов (BPMN T0–T9 → 5 семейств + ортогональные под-автоматы)
    ROUTE = "route", "Общий маршрут"                 # T1: submit → reviewers → signer → ACTIVE (vap, additional, measurement, forward-*, reply-up/-abp, claim-*, conclusion, prescription, response, completion, objection-result, counter-act, counter-additional)
    PREPARATION = "preparation", "Подготовительный этап"   # T1 + T4 (КВГА) + T5 (РГ задания) + КК1: irpi, program, plan, assignment, instruction, counter-instruction
    MAIN = "main", "Основной этап"                   # T5 (РГ отчёта) + T1 + реестр/подтверждение + КК2: report, violations, evidence
    QUALITY = "quality", "Заключение КК"             # T6: quality1/quality3 — ROUTE с ограничениями; quality2 — подпись эксперта → руководитель КК
    DIRECT = "direct", "Прямая активация"            # T0: claim-decisions, reply-law, obstruction, counter-obstruction, objections, weekly, account, counter-account, notification, counter-notification, рабочие формы
    # T2 (доставка ОА), T3 (ЕРСОП), T7 (требования сведений), T8 (владелец object), T9 (комиссия) — ортогональные признаки типа/таблицы, а не семейство

class OwnerRole(models.TextChoices):
    AUDITOR = "auditor", "Аудитор"; QUALITY = "quality", "Эксперт КК"; OBJECT = "object", "Объект аудита"; APPEAL_EXPERT = "appeal-expert", "Сотрудник апелляции"

class RegNumberFormat(models.TextChoices):          # surfk.evga_document_types.reg_number_format
    NONE = "", "—"; STANDARD = "standard", "ГГГГ/ММ/ДД – NNNNN"; WITH_ORG = "with_org", "Префикс-орган-ГГ-NNNNNN/дело"

class EvgaDocumentType(TimeStampedModel):           # documents.DocumentType prof + флаги ЭВГА; surfk.evga_document_types; data/documentMatrix.ts
    code = models.CharField(max_length=32, unique=True)                 # kind фронта: irpi, program, …, counter-act, financial-rd-05
    legacy_code = models.CharField(max_length=16, blank=True)           # M-код старой системы: M5-IPI, M7-POR, M18-RNS … (пусто, если кода нет)
    legacy_id = models.PositiveIntegerField(null=True, blank=True)      # surfk.evga_document_types.id (1=M5-IPI, 2=M6-PA-S, 47=M6-PA-F, 3=M8-PLAN, 4=M9-AZ, 5=M7-POR, 7=ЗКК, 37=КК2, 46=КК3, 51=M20-VOZ)
    legacy_root_table = models.CharField(max_length=64, blank=True)     # evga_doc_preliminary_study … (для миграции данных)
    name_ru = models.CharField(max_length=255); name_ru_financial = models.CharField(max_length=255, blank=True); name_kk = models.CharField(max_length=255, blank=True)
    display_code = models.CharField(max_length=16, blank=True)          # "12", "55", "РД-5" (не уникален)
    stage = models.PositiveSmallIntegerField(choices=Stage.choices); order = models.PositiveSmallIntegerField(default=0)   # DOC_PLACEMENT → order
    workflow = models.CharField(max_length=16, choices=Workflow.choices)
    default_owner_role = models.CharField(max_length=16, choices=OwnerRole.choices, default=OwnerRole.AUDITOR)   # creator_roles
    requires_quality = models.BooleanField(default=False)               # requiresQuality(kind)
    is_repeatable = models.BooleanField(default=False)                  # repeatableKinds / allow_multiple
    is_deliverable = models.BooleanField(default=False)                 # deliverable(kind) / sends_to_audit_object (T2)
    is_registrable = models.BooleanField(default=False)                 # performRegistration (T3)
    ersop_message_type = models.CharField(max_length=32, blank=True)    # M_TYPE_STARTED (account) / M_TYPE_FINISHED (notification) / по order.type (additional)
    is_information_request = models.BooleanField(default=False)         # request, counter-request (T7)
    is_counter = models.BooleanField(default=False)                     # counter-*
    is_working_paper = models.BooleanField(default=False)               # financial-rd-*/compliance-rd-*
    audit_type_filter = models.CharField(max_length=16, blank=True)     # "" | financial | compliance (paperApplies; surfk audit_type_codes)
    has_working_group = models.BooleanField(default=False)              # form.group
    has_signer = models.BooleanField(default=True)                      # False для assignment, report
    dependencies = models.ManyToManyField("self", symmetrical=False, blank=True)   # workflow.ts dependencies / depends_on_document
    amendment_target = models.BooleanField(default=False)               # amendmentTargets
    print_context_source = models.BooleanField(default=False)           # printContext.sources
    reg_number_format = models.CharField(max_length=16, choices=RegNumberFormat.choices, blank=True, default="")   # legacy standard/with_org
    reg_number_prefix = models.CharField(max_length=16, blank=True)     # legacy reg_number_prefix
    normative_act = models.ForeignKey("catalogs.NormativeAct", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_implemented = models.BooleanField(default=True)                  # False — M21-AKO, M38…M57, приказы (сидируются для полноты)
    class Meta: ordering = ["stage", "order"]

class FormSchema(TimeStampedModel):                 # forms/documentForms.ts + referenceForms.ts + irpiForm.ts как данные; surfk.evga_document_mappings.form_schema
    document_type = models.ForeignKey(EvgaDocumentType, on_delete=models.CASCADE, related_name="schemas")
    audit_type = models.ForeignKey("catalogs.AuditType", null=True, blank=True, on_delete=models.PROTECT, related_name="+")  # null = любой; вариант для АФО
    version = models.PositiveSmallIntegerField(default=1); effective_from = models.DateField()
    schema = models.JSONField()                     # {sources, group, tabs, sections:[{key,title,collection,min,attachments,total,tab,fields:[{key,label,type,required,options,suggestions,when,sourceKind}]}]}
    projections = models.JSONField(default=dict)    # {"violations": "Violation", "financial": "PrescriptionItem", …} — какие коллекции проецируются в таблицы
    class Meta: constraints = [UniqueConstraint(fields=["document_type", "audit_type", "version"], name="evga_documents_formschema_natural_key")]

class WorkingPaperTemplate(TimeStampedModel):       # data/workingPapers.json (62)
    document_type = models.OneToOneField(EvgaDocumentType, on_delete=models.CASCADE, related_name="paper_template")
    number = models.PositiveSmallIntegerField(); act = models.ForeignKey("catalogs.NormativeAct", on_delete=models.PROTECT, related_name="+")   # V1700015209 | V2200026715
    title = models.CharField(max_length=500); blocks = models.JSONField()   # [{type:"text",text} | {type:"table",rows,dataStart}]

class DocumentStatus(models.TextChoices):           # DocStatus фронта (label = строка фронта дословно)
    DRAFT = "DRAFT", "Проект"
    QUALITY_REVIEW = "QUALITY_REVIEW", "Направлен на согласование КК"
    IN_REVIEW = "IN_REVIEW", "На согласовании"
    IN_APPROVAL = "IN_APPROVAL", "На утверждении"
    AGREED = "AGREED", "Согласован"
    PENDING_KVGA = "PENDING_KVGA", "На подтверждении КВГА"
    PENDING_REGISTRY = "PENDING_REGISTRY", "На подтверждении реестра"
    GROUP_SIGNING = "GROUP_SIGNING", "На подписании рабочей группой"
    RETURNED = "RETURNED", "Возвращен на доработку"
    REJECTED = "REJECTED", "Отклонен"
    ACTIVE = "ACTIVE", "Активный"

_STATUS_LABEL_OVERRIDES: dict[tuple[str, str], str] = {}    # напр. ("report", "AGREED"): "Согласован (ожидает направления объекту)" — по требованию фронта
def document_status_label(document_type_code: str, status: str) -> str: ...   # копия prof

class QualityDecision(models.TextChoices):
    NO_REMARKS = "NO_REMARKS", "Без замечаний"; WITH_REMARKS = "WITH_REMARKS", "С замечаниями"

class AuditDocument(TimeStampedModel):              # AuditDocument (шапка); surfk.evga_case_documents (шапка)
    case = models.ForeignKey("evga_cases.AuditCase", on_delete=models.PROTECT, related_name="documents")
    document_type = models.ForeignKey(EvgaDocumentType, on_delete=models.PROTECT, related_name="+")
    stage = models.PositiveSmallIntegerField(choices=Stage.choices)   # копия из типа (рабочие формы: number>8 → MAIN)
    number = models.CharField(max_length=64)                           # {case.number}/NN (issue_number scope=case)
    sequence = models.PositiveSmallIntegerField()                      # NN
    registration_number = models.CharField(max_length=64, blank=True)  # legacy-формат standard/with_org — только для типов с reg_number_format (при активации)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")   # author_iin
    author_name = models.CharField(max_length=255)
    parent_document = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")   # reply-* → forward-*; objections → report (legacy parent_document_id)
    is_deleted = models.BooleanField(default=False); deleted_at = models.DateTimeField(null=True, blank=True)   # soft delete (surfk is_deleted)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    class Meta:
        ordering = ["case", "sequence"]
        constraints = [UniqueConstraint(fields=["case", "sequence"], name="evga_documents_auditdocument_natural_key")]
    @property
    def kind(self) -> str: return self.document_type.code
    @property
    def active_version(self) -> "DocumentVersion": ...   # versions.order_by("-version").first()  (activeVersion(doc))

class DocumentVersion(TimeStampedModel):            # DocumentVersion; surfk.evga_document_versions + статусные колонки evga_case_documents + evga_doc_* (содержимое)
    document = models.ForeignKey(AuditDocument, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    owner_role = models.CharField(max_length=16, choices=OwnerRole.choices, default=OwnerRole.AUDITOR)   # ownerRole
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")   # ownerId (эксперт КК, эксперт АК)
    form_schema = models.ForeignKey(FormSchema, on_delete=models.PROTECT, related_name="+")
    values = models.JSONField(default=dict)         # содержимое формы по FormSchema (+ paper, calculationInputs_*, calculationResult_*, registrySchemaVersion); файлы — AttachmentRef
    print_context = models.JSONField(default=dict)  # снимок дела для печати (printContext без sources — источники через DocumentSourceVersion)
    row_version = models.PositiveIntegerField(default=0)   # оптимистичная блокировка черновика (expected_row_version)
    # результат КК по этой версии (saveDocument п.8)
    quality_decision = models.CharField(max_length=16, choices=QualityDecision.choices, blank=True)
    quality_conclusion = models.TextField(blank=True)
    quality_conclusion_version = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")   # какая версия quality* дала заключение
    # отметки маршрутов подготовительного/основного этапа (preparation.*, main.*, mainQuality.*)
    agreed_at = models.DateTimeField(null=True, blank=True)
    group_requested_at = models.DateTimeField(null=True, blank=True)
    quality_requested_at = models.DateTimeField(null=True, blank=True)
    approval_requested_at = models.DateTimeField(null=True, blank=True)
    expert_signed_at = models.DateTimeField(null=True, blank=True)
    expert = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")   # mainQuality.expertId
    expert_submitted_at = models.DateTimeField(null=True, blank=True)
    # актор терминальных переходов (как approved_by/signed_by/sent_by в prof); legacy submitted_at/approved_at/confirmed_at/activated_at
    submitted_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    returned_comment = models.TextField(blank=True); rejected_comment = models.TextField(blank=True)   # legacy return_comment
    revision_reason = models.CharField(max_length=32, blank=True)   # returned|rejected|quality-remarks|quality|main|preparation|response|renew-quality|amendment|reassign
    frozen_at = models.DateTimeField(null=True, blank=True)          # версия заморожена (создана следующая) — «Предыдущие версии документов доступны только для чтения»
    attachments = GenericRelation("core.Attachment", ...)            # kind=document_file / form_row_file (slot)
    class Meta:
        ordering = ["document", "version"]
        constraints = [UniqueConstraint(fields=["document", "version"], name="evga_documents_documentversion_natural_key")]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["owner", "status"])]
    @property
    def version_id(self) -> str: return f"{self.document_id}:v{self.version}"     # documentVersionId фронта

class VersionParticipant(TimeStampedModel):         # version.group (снимок рабочей группы версии); surfk.evga_doc_rc_work_group / cma_work_group / seed_doc_work_group()
    version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    full_name = models.CharField(max_length=255); position = models.CharField(max_length=255, blank=True); organization = models.CharField(max_length=255, blank=True)
    is_leader = models.BooleanField(default=False); order = models.PositiveSmallIntegerField(default=0)
    member_role_code = models.CharField(max_length=32, blank=True)   # '', invited_specialist, invited_expert (legacy member_role_code)

class SignatureKind(models.TextChoices):             # surfk.evga_document_signatures.signature_type (+ значения фронта)
    ROUTE = "route", "Решение по маршруту"           # legacy approve (виза) / confirm
    GROUP = "work_group", "Подпись участника рабочей группы"   # legacy work_group_signed / invited_specialist_signed
    ACTIVATION = "activation", "Подписано и активировано"       # legacy sign (автор)
    EXPERT = "qc_expert", "Подпись эксперта КК"                  # legacy sign_zkk
    OBJECT = "object", "Подпись объекта аудита"                   # legacy oa_acknowledge / sign_with(out)_objection
    KVGA = "kvga_confirm", "Подтверждение КВГА"                  # legacy kvga_confirm
    REGISTRY = "registry_confirm", "Подтверждение реестра"       # legacy reestr_confirm

class SignatureProvider(models.TextChoices):
    STUB = "stub", "Демонстрационная"; NCALAYER = "ncalayer", "ЭЦП НУЦ РК (CMS)"

class DocumentSignature(TimeStampedModel):          # signatures[], preparation.groupSignatures, main.groupSignatures; surfk.evga_document_signatures
    version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, related_name="signatures")
    signer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    signer_name = models.CharField(max_length=255); signer_organization = models.CharField(max_length=255, blank=True)   # signer_name, signer_organization
    role = models.CharField(max_length=32)                             # роль в момент подписи (signatures[].role)
    kind = models.CharField(max_length=20, choices=SignatureKind.choices)
    signed_at = models.DateTimeField()
    provider = models.CharField(max_length=16, choices=SignatureProvider.choices, default=SignatureProvider.STUB)
    cms_payload = models.TextField(blank=True); cert_subject = models.CharField(max_length=500, blank=True); document_hash = models.CharField(max_length=64, blank=True)   # legacy signature (base64), document_hash
    class Meta: constraints = [UniqueConstraint(fields=["version", "signer", "kind"], name="evga_documents_documentsignature_natural_key")]  # «Ваша подпись уже сохранена»; legacy partial unique (case_document_id, signer_iin, signature_type)

class SourceRole(models.TextChoices):
    SOURCE = "source", "Источник"; CONFIRMATION = "confirmation", "Комплект подтверждения реестра"; AMENDMENT = "amendment", "Цель доп. поручения"

class DocumentSourceVersion(TimeStampedModel):      # sourceVersions[]; confirmation.sourceVersions; legacy source_document_id/snapshot_taken_at встроенных документов
    version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, related_name="sources")
    source_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name="dependants")
    role = models.CharField(max_length=16, choices=SourceRole.choices, default=SourceRole.SOURCE)
    content_snapshot_hash = models.CharField(max_length=64, blank=True)   # contentSnapshot (additional) → SHA-256 от JSON {values, group}
    class Meta: constraints = [UniqueConstraint(fields=["version", "source_version", "role"], name="evga_documents_documentsourceversion_natural_key")]

class Acknowledgement(TimeStampedModel):            # копия prof documents.Acknowledgement, FK на версию (delivery.acknowledgedAt); legacy acknowledge_document(notification_id, …)
    version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, related_name="acknowledgements")
    channel = models.CharField(max_length=16, choices=AcknowledgementChannel.choices)   # portal | manual
    acknowledged_on = models.DateField(); proof_ref = models.CharField(max_length=255, blank=True)
    attachment = models.ForeignKey("core.Attachment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    class Meta: constraints = [UniqueConstraint(fields=["version", "channel"], name="evga_documents_acknowledgement_natural_key")]

class DeliveryDecision(models.TextChoices):         # delivery.decision фронта ↔ legacy signed_oa / signed_with_objection / (отказ — только фронт)
    SIGNED = "SIGNED", "Подписан"; SIGNED_WITH_OBJECTIONS = "SIGNED_WITH_OBJECTIONS", "Подписан с возражениями"; REFUSED = "REFUSED", "Отказ от подписания"

class DocumentDelivery(TimeStampedModel):           # delivery; surfk.evga_audit_object_notifications + evga_case_documents.audit_object_acknowledged_at/by; send_document_to_audit_object()
    version = models.OneToOneField(DocumentVersion, on_delete=models.CASCADE, related_name="delivery")
    sent_at = models.DateTimeField(); sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    requires_acknowledgment = models.BooleanField(default=True); expires_at = models.DateTimeField(null=True, blank=True)   # legacy expires_days=5
    acknowledged_at = models.DateTimeField(null=True, blank=True)     # дублирует первый Acknowledgement для guard'ов
    response_text = models.TextField(blank=True); responded_at = models.DateTimeField(null=True, blank=True)
    decision = models.CharField(max_length=24, choices=DeliveryDecision.choices, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True); decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    grounds = models.TextField(blank=True)
    objection_due_on = models.DateField(null=True, blank=True)        # appealFilingDue: sent_at + 10 раб. дней (BPMN P10D календарных — см. §12)
    attachments = GenericRelation("core.Attachment", ...)              # kind OBJECT_RESPONSE (slot "delivery") / REFUSAL_PROOF (slot "delivery.decision")

class ConfirmationStatus(models.TextChoices):
    PENDING = "PENDING", "Ожидает"; CONFIRMED = "CONFIRMED", "Подтверждено"; RETURNED = "RETURNED", "Возвращено"

class KvgaConfirmation(TimeStampedModel):           # preparation.kvga; surfk.evga_case_documents.kvga_confirmer_iin/fullname, kvga_confirmed_at; approvals kvga_confirmed/kvga_returned
    version = models.OneToOneField(DocumentVersion, on_delete=models.CASCADE, related_name="kvga_confirmation")
    confirmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=12, choices=ConfirmationStatus.choices, default=ConfirmationStatus.PENDING)
    decided_at = models.DateTimeField(null=True, blank=True); comment = models.TextField(blank=True)

class RegistryConfirmation(TimeStampedModel):       # main.confirmation (violations); legacy send_to_reestr_confirmer / reestr_confirm (M18)
    version = models.OneToOneField(DocumentVersion, on_delete=models.CASCADE, related_name="registry_confirmation")
    confirmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=12, choices=ConfirmationStatus.choices, default=ConfirmationStatus.PENDING)
    decided_at = models.DateTimeField(null=True, blank=True); comment = models.TextField(blank=True)
    # confirmation.sourceVersions → DocumentSourceVersion(role=CONFIRMATION) на все main-документы текущих версий

class ReviewDecision(models.TextChoices):           # round.review.decision ↔ legacy accept_info / reject_info / resend_to_oa / mark_refused
    ACCEPTED = "accepted", "Принято"; REJECTED = "rejected", "Отклонено"; RESEND = "resend", "Повторно направлено"; REFUSED = "refused", "Отказ"

class InformationRequestRound(TimeStampedModel):    # informationRequest.rounds[]; surfk.evga_doc_info_request + evga_doc_ir_questions (колонки в экспорте не видны)
    version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, related_name="request_rounds")
    order = models.PositiveSmallIntegerField()
    sent_at = models.DateTimeField(); deadline = models.DateTimeField()   # taskVariable.deadlineDatetime; обязателен и позже sent_at
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    response_at = models.DateTimeField(null=True, blank=True); response_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    response_text = models.TextField(blank=True); response_refused = models.BooleanField(default=False)
    review_started_at = models.DateTimeField(null=True, blank=True); review_at = models.DateTimeField(null=True, blank=True)
    review_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    review_decision = models.CharField(max_length=12, choices=ReviewDecision.choices, blank=True); review_comment = models.TextField(blank=True)
    overdue_marked_at = models.DateTimeField(null=True, blank=True)   # проставляет process_deadlines (для журнала/уведомления); state всегда вычисляется request_state(version, now)
    attachments = GenericRelation("core.Attachment", ...)            # kind REQUEST_RESPONSE (slot "information-request:<order>")
    class Meta: constraints = [UniqueConstraint(fields=["version", "order"], name="evga_documents_informationrequestround_natural_key")]

class ViolationKind(models.TextChoices):
    FINANCIAL = "FINANCIAL", "Финансовые нарушения"; PROCEDURAL = "PROCEDURAL", "Процедурные нарушения"

class Violation(TimeStampedModel):                  # проекция values.violations[] реестра; surfk.evga_doc_vrc_violations / evga_doc_vrfn_violations
    version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, related_name="violations")
    row_id = models.CharField(max_length=64)        # id строки в values (на неё ссылаются evidence/objections/prescription/response/третьи лица/КК)
    result_row_id = models.CharField(max_length=64, blank=True); risk_row_id = models.CharField(max_length=64, blank=True); question_row_id = models.CharField(max_length=64, blank=True)
    kind = models.CharField(max_length=16, choices=ViolationKind.choices)
    violation_type = models.ForeignKey("catalogs.ViolationType", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"); violation_type_text = models.CharField(max_length=500, blank=True)
    consequence = models.ForeignKey("catalogs.ConsequenceType", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    remediation = models.ForeignKey("catalogs.RemediationStatus", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0); remaining = models.DecimalField(max_digits=18, decimal_places=2, default=0)   # violation_amount, remainder_amount
    paragraph = models.CharField(max_length=32, blank=True); description_ru = models.TextField(blank=True); description_kk = models.TextField(blank=True)
    class Meta: constraints = [UniqueConstraint(fields=["version", "row_id"], name="evga_documents_violation_natural_key")]

# опциональные проекции (включаются, когда потребуются SQL-выборки/отчётность): AuditQuestionRow (values.questions[] программы ↔ evga_doc_ap_questions),
# RiskObjectRow (values.risks[] поручения/реестра ↔ evga_doc_ao_risk_objects / vrc_risk_objects). Формат — тот же RowProjection(version, row_id, sequence).
```

Проекция `Violation` пересобирается сервисом `registry.rebuild_violation_projection(version)` при каждом сохранении черновика реестра и при активации; `effective_violations(case)` (учёт «Отменено/Отменено частично» из активного `objection-result`) — функция над проекцией.

### 4.8 `evga_workflow` (порт `shared/workflow/approvalRoute.ts`)

```python
class ApprovalMode(models.TextChoices): SEQUENTIAL = "sequential", "Последовательно"; PARALLEL = "parallel", "Параллельно"   # Q06: по умолчанию и единственный включённый — sequential
class SignerAction(models.TextChoices): SIGN = "sign", "Подписать"; APPROVE = "approve", "Утвердить"
class ApprovalRouteStatus(models.TextChoices):
    REVIEW = "review", "На согласовании"; SIGNING = "signing", "На подписании"; COMPLETED = "completed", "Завершён"
    RETURNED = "returned", "Возвращён"; REJECTED = "rejected", "Отклонён"; SUPERSEDED = "superseded", "Заменён"
class ApprovalParticipantStatus(models.TextChoices):
    WAITING = "waiting", "Ожидает"; PENDING = "pending", "Активно"; APPROVED = "approved", "Согласовано"; SIGNED = "signed", "Подписано"
    RETURNED = "returned", "Возвращено"; REJECTED = "rejected", "Отклонено"; CANCELLED = "cancelled", "Отменено"
class RouteEventAction(models.TextChoices):
    SUBMITTED = "submitted", "Направлено"; APPROVE = "approve", "Согласовано"; SIGN = "sign", "Подписано"; RETURN = "return", "Возвращено"
    REJECT = "reject", "Отклонено"; SUPERSEDE = "supersede", "Заменено"; REPLACE = "replace", "Замена участника"   # replace = BPMN change_approver/change_confirmer

class ApprovalRoute(TimeStampedModel):              # approvalRoutes[]; surfk.evga_document_approvals (лента) + approver_iin/confirmer_iin шапки
    version = models.ForeignKey("evga_documents.DocumentVersion", on_delete=models.CASCADE, related_name="approval_routes")
    initiator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    mode = models.CharField(max_length=12, choices=ApprovalMode.choices, default=ApprovalMode.SEQUENTIAL)
    signer_action = models.CharField(max_length=8, choices=SignerAction.choices, default=SignerAction.APPROVE)
    status = models.CharField(max_length=12, choices=ApprovalRouteStatus.choices, default=ApprovalRouteStatus.REVIEW)
    signer_activated = models.BooleanField(default=False)   # «Согласован» = все reviewers approved, signer ещё waiting (prep/main) — evga-workflows.md §9 п.3
    superseded_by = models.ForeignKey("evga_documents.DocumentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    returned_comment = models.TextField(blank=True); rejected_comment = models.TextField(blank=True)
    class Meta: ordering = ["version", "created_at"]

class ApprovalStage(TimeStampedModel):
    route = models.ForeignKey(ApprovalRoute, on_delete=models.CASCADE, related_name="stages")
    order = models.PositiveSmallIntegerField(); mode = models.CharField(max_length=12, choices=ApprovalMode.choices)
    class Meta: constraints = [UniqueConstraint(fields=["route", "order"], name="evga_workflow_approvalstage_natural_key")]

class ApprovalParticipant(TimeStampedModel):        # reviewers[] + signer
    route = models.ForeignKey(ApprovalRoute, on_delete=models.CASCADE, related_name="participants")
    stage = models.ForeignKey(ApprovalStage, null=True, blank=True, on_delete=models.CASCADE, related_name="participants")   # null = signer
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approval_participations")
    full_name = models.CharField(max_length=255); position = models.CharField(max_length=255, blank=True)   # снимок ApprovalPerson
    is_signer = models.BooleanField(default=False); order = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=12, choices=ApprovalParticipantStatus.choices, default=ApprovalParticipantStatus.WAITING)
    activated_at = models.DateTimeField(null=True, blank=True); decided_at = models.DateTimeField(null=True, blank=True); comment = models.TextField(blank=True)
    replaced_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")   # BPMN change_* → replace_participant
    class Meta:
        constraints = [UniqueConstraint(fields=["route", "user"], condition=Q(replaced_by__isnull=True), name="evga_workflow_approvalparticipant_natural_key")]  # «Согласующие не должны повторяться»
        indexes = [models.Index(fields=["user", "status"])]   # инбокс

class ApprovalEvent(models.Model):                  # route.history[] — append-only (как core.AuditEvent)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.ForeignKey(ApprovalRoute, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(max_length=12, choices=RouteEventAction.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"); actor_name = models.CharField(max_length=255)
    occurred_at = models.DateTimeField(default=timezone.now); comment = models.TextField(blank=True)
    new_version = models.ForeignKey("evga_documents.DocumentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
```

`ApprovalTask` — не таблица: `services/tasks.py::approval_tasks(user)` и `process_tasks(user)` (КВГА/реестр/подписи РГ/решение ОА/назначение КК) — порт `getApprovalTasks` + `ApprovalTasks.tsx`.

### 4.9 `evga_execution` (проекции; по образцу `execution.PrescriptionItem`)

```python
class PrescriptionItem(TimeStampedModel):           # prescription.values.financial[]/procedural[] активной версии; prof PrescriptionItem; legacy — только BPMN M25-PRED
    version = models.ForeignKey("evga_documents.DocumentVersion", on_delete=models.CASCADE, related_name="prescription_items")
    row_id = models.CharField(max_length=64); violation_row_id = models.CharField(max_length=64, blank=True)
    section = models.CharField(max_length=16)       # financial | procedural
    text = models.TextField(blank=True); due_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0); recover = ...; restore_work = ...; restore_accounting = ...
    class Meta: constraints = [UniqueConstraint(fields=["version", "row_id"], name="evga_execution_prescriptionitem_natural_key")]
    @property
    def status(self) -> str: ...                    # claimed/confirmed из services/items.py (open|in_review|partial|completed|not_remediable — контракт shared/execution)

class Recommendation(TimeStampedModel):             # conclusion.values.recommendations[]
    version = FK(DocumentVersion, related_name="recommendations"); row_id = CharField(64); text_ru = TextField(); text_kk = TextField(blank=True); deadline = DateField(null=True)

class ResponseMeasure(TimeStampedModel):            # response.values.measures[]/recommendations[]; surfk.response_measures (справочник мер) / evga_doc_oar_violations — не то же; legacy-таблицы мер нет
    version = FK(DocumentVersion, related_name="measures"); row_id = CharField(64)
    violation_row_id = CharField(64, blank=True); recommendation_row_id = CharField(64, blank=True)
    remediation = FK("catalogs.RemediationStatus", null=True)     # «Не устранено / Устранено частично / Устранено / Не подлежит устранению»
    accepted = Decimal; date = DateField(null=True); letter_number = CharField(64, blank=True); letter_date = DateField(null=True); done = BooleanField(default=False)
```

`ExecutionItem` (контракт `shared/execution/execution.ts`) — вычисляемая проекция `services/items.py::execution_items(cases, *, user)`; продления (`extensions`) — из `values.general.extension/deadline/extensionReason` утверждённой редакции ответа (`effective_execution_response_version`). `ExecutionDecision` prof (RELEASE/EXTEND) — резерв.

### 4.10 `evga_appeals`

```python
class AdmissionDecision(models.TextChoices): ACCEPTED = "ACCEPTED", "Принято к рассмотрению"; REFUSED = "REFUSED", "Отказ в рассмотрении"

class Appeal(TimeStampedModel):                     # AuditCase.appeal; legacy — дело с активным M20-VOZ + surfk.case_appeal_expert_assignments
    case = models.OneToOneField("evga_cases.AuditCase", on_delete=models.CASCADE, related_name="appeal")
    objection_version = models.ForeignKey("evga_documents.DocumentVersion", on_delete=models.PROTECT, related_name="+")   # активная версия objections
    received_at = models.DateTimeField(); filing_due_on = models.DateField(null=True, blank=True)   # appealFilingDue
    expert = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")   # appeal-expert (актуальное; история — AuditEvent action=assign)
    admission_decision = models.CharField(max_length=12, choices=AdmissionDecision.choices, blank=True)
    admission_at = models.DateTimeField(null=True, blank=True); admission_by = FK(User); admission_reason = models.TextField(blank=True); admission_notified_at = models.DateTimeField(null=True, blank=True)
    arguments_at = models.DateTimeField(null=True, blank=True); arguments_by = FK(User)
    arguments_submitted_at = models.DateTimeField(null=True, blank=True); arguments_signed_at = models.DateTimeField(null=True, blank=True)
    arguments_signed_by = FK(User); arguments_comment = models.TextField(blank=True)
    attachments = GenericRelation("core.Attachment", ...)   # kind APPEAL_FILE (slot "admission" | "admission.notify")

class AppealArgument(TimeStampedModel):             # arguments.rows[]
    appeal = models.ForeignKey(Appeal, on_delete=models.CASCADE, related_name="arguments")
    violation_row_id = models.CharField(max_length=64); text_ru = models.TextField(blank=True); text_kk = models.TextField(blank=True)
    attachments = GenericRelation("core.Attachment", ...)
    class Meta: constraints = [UniqueConstraint(fields=["appeal", "violation_row_id"], name="evga_appeals_appealargument_natural_key")]

class ThirdPartyNotice(TimeStampedModel):           # thirdParties[] (legacy: нет)
    case = models.ForeignKey("evga_cases.AuditCase", on_delete=models.CASCADE, related_name="third_parties")
    name = models.CharField(max_length=500); identification = models.CharField(max_length=12, blank=True)
    violation_row_ids = models.JSONField(default=list)
    notice_at = models.DateField(); recorded_by = FK(User)
    attachments = GenericRelation("core.Attachment", ...)   # kind THIRD_PARTY_FILE, slot "notice"

class ThirdPartyEvent(TimeStampedModel):            # receipt | response | forward — строго по порядку, с файлами
    notice = models.ForeignKey(ThirdPartyNotice, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=12, choices=[("receipt", "Получение уведомления"), ("response", "Позиция третьего лица"), ("forward", "Передача в орган аудита")])
    date = models.DateField(); text = models.TextField(blank=True); recorded_by = FK(User)
    attachments = GenericRelation("core.Attachment", ...)
    class Meta: constraints = [UniqueConstraint(fields=["notice", "event"], name="evga_appeals_thirdpartyevent_natural_key")]
```

### 4.11 `evga_ersop` (копия `ersop` с заменой агрегата)

```python
class ErsopMessageType(models.TextChoices):         # SEND_REQ_TO_ERSOP::Switch по messageType (n8n)
    STARTED = "M_TYPE_STARTED", "Начало проверки"; PROLONGED = "M_TYPE_PROLONGED", "Продление"; PERIOD_CHANGED = "M_TYPE_PERIOD_CHANGED", "Изменение периода"
    RESUMED = "M_TYPE_RESUMED", "Возобновление"; SUSPENDED = "M_TYPE_SUSPENDED", "Приостановление"; STOPED = "M_TYPE_STOPED", "Прекращение"
    EXECUTORS_CHANGED = "M_TYPE_EXECUTORS_CHANGED", "Изменение исполнителей"; FINISHED = "M_TYPE_FINISHED", "Завершение (талон)"

class ErsopRegistrationStatus(models.TextChoices):  # registration.status фронта (label) ↔ BPMN T3 (legacy_code)
    DRAFT = "DRAFT", "Не направлена"                         # —
    SENT = "SENT", "Отправлена"                              # sent_to_ersop
    PENDING = "PENDING", "Отправлена (на рассмотрении)"      # pending_for_consideration (ersop_accepted)
    REGISTERED = "REGISTERED", "Зарегистрирована"            # registered_ersop (confirmstatusid '1')
    REJECTED = "REJECTED", "Возвращена (отказ)"              # rejected_ersop ('2')
    RETURNED = "RETURNED", "Возвращена"                      # sent_revision_ersop ('3')
    ERROR = "ERROR", "Ошибка обмена"                         # ersop_error (successful=0)

class ErsopRegistration(TimeStampedModel):          # registration; ErsopPackage prof на версию документа
    version = models.OneToOneField("evga_documents.DocumentVersion", on_delete=models.CASCADE, related_name="registration")
    message_type = models.CharField(max_length=32, choices=ErsopMessageType.choices)
    status = models.CharField(max_length=12, choices=ErsopRegistrationStatus.choices, default=ErsopRegistrationStatus.DRAFT)
    request_id = models.UUIDField(default=uuid.uuid4, unique=True)     # requestId (UUID v4, n8n); docId = document_id
    submitted_at = models.DateTimeField(null=True, blank=True); submitted_by = FK(User)
    registration_number = models.CharField(max_length=64, blank=True); registration_date = models.DateField(null=True, blank=True)
    confirm_status_id = models.CharField(max_length=8, blank=True)   # confirmstatusid '1'|'2'|'3'
    return_comment = models.TextField(blank=True); last_checked_at = models.DateTimeField(null=True, blank=True); check_attempts = models.PositiveSmallIntegerField(default=0)

class ErsopExchange(TimeStampedModel):              # копия prof ErsopExchange; legacy acc_100.rspns_msg_rsp
    registration = models.ForeignKey(ErsopRegistration, on_delete=models.CASCADE, related_name="exchanges")
    direction = models.CharField(max_length=3, choices=ErsopExchangeDirection.choices)   # IN | OUT
    exchange_id = models.CharField(max_length=64, blank=True)
    request_payload = models.JSONField(default=dict, blank=True); response_payload = models.JSONField(default=dict, blank=True); raw_xml = models.TextField(blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
```

### 4.12 `notifications`

```python
class NotificationEventType(models.TextChoices):    # legacy portal.notifications.event_type (FREE_TEXT_NOTIFICATION_EVENT) + типы ЭВГА
    ROUTE_TASK = "route_task", "Задача по маршруту"; STATUS = "status", "Изменение статуса"; ASSIGNMENT = "assignment", "Назначение"
    DELIVERY = "delivery", "Направлен документ"; APPEAL = "appeal", "Апелляция"; DEADLINE = "deadline", "Срок"; FREE_TEXT = "free_text", "Произвольное"

class Notification(TimeStampedModel):               # AuditCase.notifications[] (одна строка на получателя); legacy portal.notifications(user_id, title, message, event_type, notification_type, meta_data, status UNREAD|READ, channel WEB, read_at)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="evga_notifications")
    case = models.ForeignKey("evga_cases.AuditCase", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    document = models.ForeignKey("evga_documents.AuditDocument", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    event_type = models.CharField(max_length=16, choices=NotificationEventType.choices, default=NotificationEventType.STATUS)
    title = models.CharField(max_length=255); message = models.TextField(blank=True); meta = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    class Meta: ordering = ["-created_at"]; indexes = [models.Index(fields=["recipient", "read_at"])]
```

### 4.13 Сопоставление: модель ↔ тип фронта (`types.ts`) ↔ таблица `surfk.*` ↔ код BPMN / M-код

| Django-модель | Фронт (`types.ts`) | Старая система `surfk.*` | BPMN / M-код / действие |
|---|---|---|---|
| `evga_cases.AuditCase` | `AuditCase` | `cases` (+`case_statuses`, `parent_id/sub_case_type='counter_control'/sub_case_data`; `workflow_state`, `zeebe_process_instance_id` — не переносятся) | `CaseProcessV1`; статусы дела `open/closed` хранятся, `control/awaiting_objections/reviewing_objections/audit_materials_implementation/qc_approved` — вычисляемая фаза |
| `CaseBasis` | `Basis` | `case_bases`, `case_base_attachments` | — |
| `CaseParticipant` | `Person` в `group` | `case_participants (user_iin, is_lead, is_active, removed_at)` | `assignment_type=workgroup/workgroup_lead` |
| `CaseCoauthor` | `coauthors[]` | нет | — |
| `QualityAssignment` | `qualityAssignments[stage]` | `case_qc_expert_assignments` (+`case_qc_assignments` для руководителя КК → роль), `cases.qc_expert_iin/qc_head_iin` | `assign_qc_expert(_stage2/_stage3)`, `change_qc_expert`, `change_qc_head` |
| `CaseCalendarDay`, `catalogs.ProductionCalendarDay` | `calendar` | — | — |
| `CaseAmendment` | `amendments[]` | — | — |
| `subjects.Subject` (+поля) | `AuditObject` | `audit_objects` (upsert по `bin`), `evga_audit_object.object_data` | `SubjectInfo{subjectId, bin}` ЕРСОП |
| `subjects.AnnualPlanEntry` | `catalogue`, `plannedBasisFor` | `annual_plans`, `plan_objects`, `subj_sched_insp` | — |
| `EvgaDocumentType` | `docKinds`, `counterDocKinds`, `workingDocKinds` | `evga_document_types` (`code`, флаги), `evga_document_stages`, `evga_available_document_types` | `zeebe_process_id → prc_*` (`bpmn-processes.md` §3.10, реконструкция) |
| `FormSchema` | `formFor(kind, auditType)` | `evga_document_mappings.form_schema` | — |
| `WorkingPaperTemplate` | `workingPapers.json` | — (в legacy нет) | — |
| `AuditDocument` | `AuditDocument` | `evga_case_documents` (шапка: `registration_number`, `author_*`, `parent_document_id`, `is_deleted`) | — |
| `DocumentVersion` | `DocumentVersion` | `evga_case_documents.status_id/version/*_at` + `evga_document_versions.data_snapshot` + `evga_doc_*` (содержимое) | `workflow-update newStatus` (`LEGACY_STATUS_MAP`) |
| `VersionParticipant` | `version.group` | `evga_doc_rc_work_group`, `evga_doc_cma_work_group`, `seed_doc_work_group()` | `faces[]` ЕРСОП |
| `DocumentSignature` | `signatures[]`, `groupSignatures` | `evga_document_signatures (signature_type)` | `requires_signature` действий |
| `DocumentSourceVersion` | `sourceVersions[]`, `confirmation.sourceVersions` | `source_document_id/snapshot_taken_at` встроенных документов | — |
| `Acknowledgement`, `DocumentDelivery` | `delivery` | `evga_audit_object_notifications`/`oa_notifications`, `audit_object_acknowledged_at/by`, `send_document_to_audit_object()`, `acknowledge_document()` | T2: `send_to_audit_object`, `audit_object_acknowledged`, `sign_without_objection`, `sign_with_objection`; `M21-AKO` (не документ) |
| `KvgaConfirmation` | `preparation.kvga` | `kvga_confirmer_iin/fullname`, `kvga_confirmed_at`; approvals `kvga_confirmed/kvga_returned/kvga_rejected` | T4: `send_to_kvga`, `kvga_confirm`, `kvga_return`, `kvga_reject`, `change_kvga_confirmer` |
| `RegistryConfirmation` | `main.confirmation` | `confirmer_iin` (M18) | `send_to_reestr_confirmer`, `reestr_confirm`, `reject`, `change_reestr_confirmer` |
| `InformationRequestRound` | `informationRequest.rounds[]` | `evga_doc_info_request`, `evga_doc_ir_questions` (колонки не видны) | T7: `provide_info`, `refuse_info`, `review_info`, `accept_info`, `reject_info`, `resend_to_oa`, `mark_refused`, `overdue` |
| `Violation` | `values.violations[]` | `evga_doc_vrc_violations`, `evga_doc_vrfn_violations` (+`vrc_results`, `vrc_risk_objects` — в JSON) | `M18-RNS`/`M18-RNAFO`; `qcs2/violations` |
| `ApprovalRoute/Stage/Participant/Event` | `ApprovalRoute` (`shared/workflow`) | `evga_document_approvals`, `approver_iin/confirmer_iin` шапки, `evga_status_transitions` (формат) | `submit`, `approve`, `confirm`, `return`, `reject`, `change_approver`, `change_confirmer` |
| `PrescriptionItem`, `Recommendation`, `ResponseMeasure` | `prescription.financial/procedural`, `conclusion.recommendations`, `response.measures` | нет (только BPMN `M25-PRED`, `M24-AZK`, `M28-OPM`) | — |
| `Appeal`, `AppealArgument` | `Appeal` | `case_appeal_expert_assignments`; документ `M23-RVO` (`evga_doc_objection_appeal_result`, `evga_doc_oar_violations`) | T9: `assign_qc_expert_appeal`, `create_resultat_vozrazhenie` |
| `ThirdPartyNotice/Event` | `ThirdPartyNotice[]` | нет | — |
| `ErsopRegistration`, `ErsopExchange` | `registration` | `acc_100.rspns_msg_rsp`; approvals `sent_to_ersop/registered_ersop/rejected_ersop/sent_revision_ersop/ersop_accepted/ersop_error` | T3: `send_to_ersop`, `check_status`, `ersop_*`; `M11`, `M14`, `M26-TU`, `M44-VK-UK`, `M47-VK-TU`, `M54-VK-DOP-POR` |
| `Notification` | `notifications[]` | `portal.notifications` | — |
| `core.AuditEvent` (+поля) | `history[]` | `evga_audit_log`, `evga_document_workflow_history`, `evga_document_approvals`, `case_status_history`, `case_activity_log` | все `action_code` |
| `core.NumberSequence` | `nextCaseNumber`, `documentSequence` | `get_next_case_sequence`, `get_next_doc_sequence('standard'\|'with_org'\|'PRIKAZ')` | — |
| `accounts.User/Role/RoleAssignment` | `Account`, `Role` | `users`, `evga_roles`, `evga_user_roles`, `evga_users_with_roles`, Keycloak realm `efc` | `allowed_roles` |

Соответствие `kind` ↔ M-код (сидируется в `legacy_code`; пусто там, где в legacy кода нет): `irpi`=`M5-IPI`, `program`=`M6-PA-S`/`M6-PA-F` (по `audit_type.is_financial`), `plan`=`M8-PLAN`, `assignment`=`M9-AZ`, `instruction`=`M7-POR`, `quality1`=`M10-QC1` (ЗКК, legacy id 7), `quality2`=legacy id 37 (`evga_doc_37_kk2`, M-кода нет), `quality3`=legacy id 46 (`evga_doc_46_kk3`), `account`=`M11`, `vap`=`M13`, `additional`=`M14`, `request`=`M15`, `obstruction`=`M16` (в legacy также «акт об отказе в сведениях» под `M15` — второй тип не заводим), `report`=`M17-AO-S`/`M17-AO-F`, `violations`=`M18-RNS`/`M18-RNAFO`, `evidence`=`M19-AD`, `objections`=`M20-VOZ`, `objection-result`=`M23-RVO`, `conclusion`=`M24-AZK`, `prescription`=`M25-PRED`, `notification`=`M26-TU`, `response`=`M28-OPM`, `counter-instruction`=`M43-VK-POR`, `counter-account`=`M44-VK-UK`, `counter-request`=`M45-VK-TREB`, `counter-act`=`M46-VK-AKT`, `counter-notification`=`M47-VK-TU`, `counter-additional`=`M54-VK-DOP-POR`, `counter-obstruction`=`M56-VK-AKT-VOS`; `weekly` (BPMN 2.4 `evga_doc_weekly_report`), `measurement` (`evga_doc_control_measurement_act`), `forward-*`, `reply-*`, `claim-*`, `completion` — M-кода нет, хранится только `legacy_process_id` в `metadata` сида (**не подтверждено**: справочник `evga_document_types` не выгружен). Legacy-only виды (`M21-AKO`, `M38…M42/M48…M53/M57 -ADM-*`, `M55-VK-AKT-OSM`, `evga_doc_prikaz`) сидируются с `is_implemented=False`.

### 4.14 JSONField vs таблицы — обоснование

| Данные | Решение | Почему |
|---|---|---|
| Содержимое форм (`values` по `formFor(kind, auditType)`) | `DocumentVersion.values` JSONField + серверная валидация по `FormSchema` | 105 видов × ≈900 полей; фронт рендерит по декларативной схеме; в prof JSON уже используется для форм отчётности (`reporting.DfoExtract.values`); legacy хранила «через маппинг» динамическим SQL по 40 таблицам `evga_doc_*` — самое хрупкое место (`n8n-cases-documents.md` §6) |
| Идентификация, статус, владелец, отметки маршрутов, актор терминальных переходов | колонки `DocumentVersion` | фильтры инбокса/реестра КК, индексы, FK на пользователей — как `ControlDocument.approved_by/signed_by/sent_by` |
| Под-состояния с FK на пользователей/версии (РГ версии, подписи, `sourceVersions`, регистрация, доставка, подтверждения КВГА/реестра, раунды требования, маршруты) | типизированные таблицы | FK на `User`/`DocumentVersion`, уникальности («Ваша подпись уже сохранена», «Ознакомление уже зафиксировано»), инбокс (`ApprovalParticipant(user, status=pending)`, `KvgaConfirmation.confirmer`), уведомления, ЕРСОП (`faces[]` из `VersionParticipant`) |
| Строки, на которые ссылаются другие документы (`violations`, `financial/procedural`, `recommendations`, `measures`) | JSON канонично; проекции `Violation`, `PrescriptionItem`, `Recommendation`, `ResponseMeasure` пересобираются сервисом | реестр исполнения/КК2/третьи лица/апелляция делают SQL-запросы; целостность `violation_row_id` проверяется сервисом; аналог prof — `PrescriptionItem` + `CaseChecklistViolation` |
| `risks`, `results`, `questions`, `evidence` строки | только JSON (проекции `AuditQuestionRow`, `RiskObjectRow` — опционально) | ссылаются только внутри дела; `formLinks` отдаётся сервисом из JSON |
| `printContext` (снимок дела) | `print_context` JSONField без `sources` | данные дела мутируют; снимки документов заменены FK на неизменяемые версии |
| `paper` (ячейки РД), `calculationInputs_*/Result_*`, `registrySchemaVersion` | внутри `values` | не фильтруются; сервер пересчитывает и сверяет |
| `Upload` | `core.Attachment` (MinIO); в JSON — `AttachmentRef {id, name, type, size, url}`; `Attachment.slot` для строк | checksum, права, download через view; `assertAttachmentRetention` → запрет `DELETE` вложения вне `DRAFT` |
| `history` дела/версии | `core.AuditEvent` | append-only, ТЗ табл. 49 |
| `notifications` | `Notification` (строка на получателя) | `readBy` = `read_at` |
| `calendar` | `ProductionCalendarDay` + `CaseCalendarDay` (переопределения) + `calendar_confirmed_years` | во фронте на дело только из-за отсутствия сервера |
| `quality[3]` | колонка-кеш `quality_stage_passed` + пересчёт в транзакции коммита | как во фронте (`useAuditCases` пересчитывает при загрузке); фильтр реестра КК по колонке, а не Python-проходом |
| `ExecutionItem`, `Deadline`, `ApprovalTask`, `InformationRequestState`, `stage`, `progress`, `available_actions`, `permissions` | вычисляются сервисами | во фронте — проекции; в prof — `PrescriptionItem.status` property; legacy хранила `workflow_state.available_actions` в БД — не переносится |

### 4.15 Нумерация (`seed_evga_number_sequences`, механизм `core.NumberSequence`/`issue_number` без изменений)

| key | scope | pattern | context | target / кто выдаёт |
|---|---|---|---|---|
| `evga-case` | `<controlling_body.code>` | `{org}-{yy}-{seq:05d}` | `org=30101`, `yy` | `AuditCase.number` в `create_case`; фронт `30101-YY-NNNNN`, legacy `CONCAT(code,'-',YY,'-',LPAD(seq,5,'0'))` через `get_next_case_sequence(year)`; стартовое `current_value` — `--start` (фронт 52970; из старой БД — при миграции) |
| `evga-counter-case` | `<parent uuid>` | `{parent}/ВП-{seq}` | `parent=number` | дочерний `AuditCase` (`create_counter_case`); legacy-паттерн `[ВП-]{org}-{yy}-{seq:06d}/{case_tail}` доступен сидом как альтернативный `pattern` |
| `evga-document` | `<case uuid>` | `{case}/{seq:02d}` | `case=number` | `AuditDocument.number` в `create_document`; `AuditCase.document_sequence` дублирует `current_value` для чтения; номера удалённых не переиспользуются |
| `evga-doc-standard` | `""` | `{yyyy}/{mm}/{dd} – {seq:05d}` | | `AuditDocument.registration_number` при активации типа с `reg_number_format=standard` (legacy `get_next_doc_sequence('standard', year)`) — за адаптером `numbering.issue_registration_number` |
| `evga-doc-with-org` | `""` | `{prefix}-{org}-{yy}-{seq:06d}/{case_tail}{v}` | `v="_1"` | то же для `with_org` (legacy `Create Case Document`) |
| `evga-ersop-registration` | `""` | `УЧ-{yyyy}-{seq:05d}` | `yyyy` | `ErsopRegistration.registration_number` только в stub-адаптере (фронт: `УЧ-<number с / → ->`) |

Для scope-последовательностей `issue_number` вызывается после `NumberSequence.objects.get_or_create(key, scope, defaults=pattern из «шаблонной» строки key/scope="")` — 4 строки в `evga_cases/services/numbering.py::scoped_sequence(key, scope_obj)`; сам `issue_number` не меняется. Номер приказа legacy (`{doc}_P_{seq}`, `get_next_doc_sequence('PRIKAZ')`) — не нужен (приказы вне объёма).

### 4.16 `LEGACY_STATUS_MAP` — соответствие статусов старой системы

Константа `apps/evga_documents/legacy.py::LEGACY_STATUS_MAP: dict[str, tuple[str, str]]` («legacy-код → (сущность, значение)»); используется отчётностью, ЕРСОП-адаптером (`statusName` в ответах), сидами и тестом полноты «каждый код из каталога `bpmn-processes.md` §2.1 либо отображён, либо явно в `DROPPED_LEGACY_STATUSES`».

| Legacy-код (`evga_document_statuses.code` / BPMN `newStatus`) | Куда отображается |
|---|---|
| `draft` | `DocumentStatus.DRAFT` |
| `sent_to_qc` (на уровне дела) | `DocumentStatus.QUALITY_REVIEW` (для `requires_quality` вне prep/main) |
| `pending_approval` | `IN_REVIEW` |
| `approved` | `AGREED` (prep/main); для T1 — промежуточное состояние маршрута (`ApprovalRoute.status=review`, все reviewers approved) |
| `pending_confirmation` | `IN_APPROVAL` |
| `pending_kvga`, `kvga_confirmed` | `PENDING_KVGA` / `AGREED` + `KvgaConfirmation.status` |
| `pending_reestr_confirmation` (M18 `pending_kvga`) | `PENDING_REGISTRY` + `RegistryConfirmation` |
| `pending_work_group_approval`, `pending_invited_specialist_sign` | `GROUP_SIGNING` |
| `revision`, `return`, `sent_revision_ersop` | `RETURNED` (+ `ErsopRegistration.status=RETURNED`) |
| `rejected`, `rejected_ersop` | `REJECTED` / `ErsopRegistration.status=REJECTED` |
| `active`, `confirmed`, `signed`, `registered`, `sent`, `sent_to_court`, `sent_to_law_enforcement`, `closed`, `completed`, `accepted` | `ACTIVE` (+ факт подписи/регистрации/внешней отправки в связанных таблицах или `metadata`) |
| `sent_to_ersop`, `pending_for_consideration`, `registered_ersop` | `ErsopRegistrationStatus.SENT / PENDING / REGISTERED` |
| `sent_to_audit_object`, `sent_to_oa`, `delivered_to_oa`, `oa_acknowledged`, `audit_object_acknowledged`, `signed_oa`, `signed_by_oa`, `signed_without_objection_oa`, `signed_with_objection`, `signed_automatically`, `awaiting_objections`, `reviewing_objections` | `DocumentDelivery` (`sent_at`, `acknowledged_at`, `decision`) |
| `awaiting_info`, `sent_by_audit_object`, `under_review`, `send_to_auditor`/`sent_to_auditor`, `overdue`, `info_accepted`, `info_refused` | `request_state(version, now)` ∈ `sent/awaiting/received/review/overdue/accepted/refused` |
| `open` (Дело КК), `qc_acknowledged`, `expert_assigned`, `qc_approved`, `sent_to_ak`, `pending_oa_confirmation`, `oa_confirmed`, `control`, `audit_materials_implementation`, `inactive` | `DROPPED_LEGACY_STATUSES` с причиной (фаза дела/КК вычисляется; `sent_to_ak` = активация `objections`; «не создан» = отсутствие записи) |

Смысл id статусов legacy `1, 2` («черновые»), `3, 22` (исключаются как неактивные), `49` (`sent_to_ak`), `11, 12` (дело «на КК») — **не подтверждено** (справочник не выгружен).

---

## 5. Сервисный слой

### 5.1 Принципы

Форма — как в prof: модули функций, первый позиционный аргумент — агрегат, остальное keyword-only, актор именованно (`by=`), `@transaction.atomic` при нескольких записях, `select_for_update`, `save(update_fields=[..., "updated_at"])`, первые строки — проверки типа/статуса с русским текстом, `IntegrityError → DocumentTransitionError`. Дополнение к prof: каждая transition-функция после `save()` вызывает `record_event(...)` и `notify(...)` (через `commit_version`).

**Порт 1:1**: имя TS-функции → snake_case; сигнатура `(audit, doc, actor, …)` → `(version_or_document, *, by, …)`, дело берётся из `document.case`; тексты ошибок и сообщения истории — дословно из TS (это же ожидаемые строки тестов). Все «блоки» фронта (`creationBlock`, `preparationSubmissionBlock`, `mainApprovalBlock`, `completionBlock`, `amendmentBlock`, `appealSubmissionBlock`…) переносятся как функции `*_block(...) -> str | None` и используются и в guard'ах действий, и в `available_actions`/`available_documents` (одна реализация — и для запрета, и для подсказки фронту). Гейты legacy (`check-docs-status` → `gates.documents_in_status(case, kinds, status)`, `check_document_submit_allowed`, `check_document_creation_condition`) выражаются теми же функциями.

Исключения (`apps/evga_documents/services/exceptions.py`, копия prof + 2 класса): `DocumentTransitionError(Exception)` → 400 `code="invalid"`; `StaleVersionError(DocumentTransitionError)` → 409 `code="stale_version"` (через `core.exceptions.ConflictError`); `ValidationBlockError(DocumentTransitionError, errors: list[str])` → 400 `code="validation"` + `errors[]`; `ApprovalWorkflowError(DocumentTransitionError, code)` с кодами фронта `INVALID_ROUTE, FORBIDDEN, STALE_VERSION, INVALID_STATUS, ALREADY_DECIDED, COMMENT_REQUIRED`; доступ — `django.core.exceptions.PermissionDenied` → 403 (`CaseTransitionError` в `evga_cases/services/exceptions.py` — наследник `DocumentTransitionError` для единообразного маппинга).

### 5.2 Модули и сигнатуры

**`apps/core/services/audit.py`** — `record_event(...)` (§4.2).

**`apps/evga_cases/services/`**

| Модуль | Функции (порт из фронта / legacy) |
|---|---|
| `exceptions.py` | `class CaseTransitionError(DocumentTransitionError)` |
| `cases.py` | `create_case(*, created_by, subject_bin, subject_payload, audit_type, inspection_type, inspection_kind=None, check_kind, electronic, dsp, purpose_ru, purpose_kk, joint_subject_bin=None, group: list[dict], bases: list[dict]) -> AuditCase` (порт `validateCase` + `CaseForm.save` + upsert объекта по БИН как в `Create Case v4`; номер `issue_number("evga-case", scope=controlling_body.code)`; `subject_snapshot`; `record_event(action=CREATE, action_code="case_created")`); `update_case(case, *, by, **fields)` («Изменены сведения дела»; основания — только для внепланового, как `Case Update (Extended)`); `set_group(case, *, members, by)` (один лидер; `Person.id = User.id`); `assign_coauthor(case, *, user, by)` («Соавтора назначает руководитель органа аудита»); `save_calendar(case, *, holidays, working_dates, confirmed_years, by)`; `create_counter_case(parent, *, created_by, person_type, subject_bin=None, person_iin="", person_name="", person_birth_date=None, entrepreneur_name="", question, group)` («Учетная карточка основного дела должна быть зарегистрирована в КПСиСУ»); `close_case(case, *, by, reason)`; `assert_case_open(case)` («Дело закрыто»); `assert_author_or_coauthor(case, user)` (`canAuthorCase`) |
| `case_status.py` | `quality_passed(case, stage) -> bool`; `compute_quality(case) -> list[bool]` (пересчёт `quality_stage_passed`); `stage_available(case, stage)`; `compute_stage(case)`; `completion_block(case) -> str \| None`; `is_registered(case) -> bool`; `is_active(case, kind)`; `effective_violations(case) -> list[dict]` |
| `quality_assignment.py` | `assign_quality_expert(case, *, stage, expert, by, reason="") -> QualityAssignment` (только `evga-qc-head`; эксперт не в `case.participants`; при подписанном `quality2` — `revisions.revise_main_quality` без чужой подписи; при направленном — `supersede_route`; закрывает старое назначение `unassigned_at`; `record_event(action=ASSIGN, action_code="assign_quality_expert", metadata={"legacy_code": "assign_qc_expert"})`); `quality_assignment_block(case, stage, user) -> str \| None` («Руководитель КК должен назначить эксперта на N этап» / «Заключение оформляет назначенный эксперт КК: <имя>»); `quality_expert(case, stage) -> User \| None` |
| `quality_registry.py` | `quality_registry(*, user, search, page)` (строки `QualityRegistry.tsx`), `quality_case_view(case)` (`stages[]` с `label/detail/sources/block/outdated`) |
| `deadlines.py` | `working_date(d, case)`, `add_working_days(d, n, case)` (календарь = `ProductionCalendarDay` ⊕ `CaseCalendarDay`, `ZoneInfo("Asia/Almaty")`), `quality_days(case, version)` (2/5/7/10/3/20), `audit_deadlines(case, today=None) -> list[Deadline]` (15 правил `DeadlineRule`), `appeal_filing_due(case)` |
| `progress.py` | `execution_stages(case)`, `next_execution_step(case, user)`, `document_next_action(case, kind)` (порт `executionProgress.ts`) |
| `amendments.py` | `amendment_block(case, version, user) -> str \| None`, `apply_amendment(version, *, by) -> AuditCase` (новые версии всех `amendment_target`, перенос полей, `CaseAmendment`, дело: `purpose_*`, `group`, `schedule_*`; `quality_stage_passed=[F,F,F]`) |
| `workspace.py` | `build_workspace(case, user) -> dict` (агрегат §6.2) |
| `numbering.py` | `scoped_sequence(key, scope_obj)`; `issue_case_number(case)`, `issue_counter_case_number(parent)` |

**`apps/evga_documents/services/`**

| Модуль | Функции |
|---|---|
| `factory.py` | `creation_access_block(case, kind, user)` (auditor-автор/соавтор; `quality` — назначенный эксперт; `object` — objections/response; `appeal-expert` — назначенный по апелляции), `creation_block(case, kind)` (зависимости, `is_registered`, `quality_stage_passed`, `execution_state`, `paper_applies`, `counter-*`/`parent`), `available_document_types(case, user) -> list[dict]` (= legacy `get_available_document_types_for_case` + `Get Available Document Types`), `initial_values(case, kind) -> dict` (порт `formValues.initialValues`), `create_document(case, *, kind, created_by) -> AuditDocument` (`select_for_update(case)`; «Документ уже создан.» для неповторяемых; номер `issue_number("evga-document", scope=case)`; версия v1; `VersionParticipant` из `case.participants` или эксперт КК; `DocumentSourceVersion` для quality*/additional/objection-result/response; `print_context`; событие «Создана версия v1»), `create_working_papers(case, *, created_by) -> int`, `delete_document(document, *, by)` (порт `deleteDocument` §2.13; soft delete) |
| `drafts.py` | `assert_can_edit(version, user)` (`canEdit`), `save_draft(version, *, values, group=None, expected_row_version, by) -> DocumentVersion` (`select_for_update`; `row_version += 1`; `assert_attachment_retention`; `assert_execution_response_save` для `response`; `registry.rebuild_violation_projection`; `print_context`; «Сохранены изменения»), `assert_attachment_retention(version, new_values)` |
| `validation.py` | `validate_values(schema, values, *, audit_type) -> list[str]` (порт `fieldError/datesError`, `section.min`, `when`), `validate_document(case, version) -> None \| raise ValidationBlockError` (порт `validateDocument`, `validateIrpiForReview`, `validateWorkingPaper`, `registryValidation`, правила по видам `evga-domain-model.md` §5.2) |
| `gates.py` | `documents_in_status(case, kinds, statuses) -> GateResult(all_matched, all_existing_matched, found_count, docs)` (порт `check-docs-status`), блоки `preparation_*_block`, `main_*_block` (перечень §5.4), `submit_allowed_block(version)` (= legacy `check_document_submit_allowed`) |
| `actions.py` | `ACTIONS: dict[str, ActionSpec]`, `apply_action(document, *, spec, actor, payload, expected_version=None, expected_row_version=None, now=None) -> ActionResult(document, version, case, returns_case)`, `available_actions(document, user) -> list[ActionInfo]`, `document_permissions(document, user) -> dict` (`can_edit, can_submit, can_decide, decision_label, can_send_quality, can_delete, can_activate, is_owner`) |
| `state_machine.py` | `can_edit(version, user)`, `can_submit(document, user)`, `can_decide(document, user)`, `send_to_quality(version, *, by)`, `submit(version, *, by, stages, signer=None, comment="", mode="sequential")`, `approve(version, *, by, expected_version, comment="")`, `return_for_revision(version, *, by, comment, expected_version)`, `reject(version, *, by, comment, expected_version)`, `recall(version, *, by)`, `activate(version, *, by, signature=None)` — каждая диспетчеризует по `document_type.workflow` в `preparation.py`/`main.py`/`quality.py` за дополнительными guard'ами |
| `revisions.py` | `create_revision(document, *, reason, by, owner=None) -> DocumentVersion` (диспетчер по `reason`) и порты `create_next_version`, `create_returned_revision`, `create_rejected_revision`, `revise_main_document`, `revise_preparation_document`, `revise_main_quality`, `create_response_revision`, `renew_quality`, `reassign_returned_document(document, *, new_owner, by)`; старая версия получает `frozen_at`, маршрут — `supersede_route` |
| `preparation.py` | блоки `preparation_current_block`, `preparation_submission_block`, `preparation_references_block`, `preparation_quality_block(case)`, `preparation_approval_block(case, version)`; переходы `send_instruction_to_kvga(version, *, by, confirmer)`, `decide_instruction_kvga(version, *, by, decision, comment, expected_version)`, `request_preparation_quality(version, *, by)`, `send_preparation_for_approval(version, *, by)`, `sign_assignment_group(version, *, by, expected_version, signature=None)`, `approve_assignment_group(version, *, by, expected_version)` |
| `main.py` | блоки `main_current_block`, `main_preparation_block(case)`, `main_submission_block`, `main_references_block`, `main_confirmation_block(case)`, `main_quality_block(case)`, `main_quality_conclusion_block(case)`, `main_approval_block(case, version)`, `main_delivery_block(case, version)`; переходы `request_report_group_signatures`, `sign_report_group`, `send_registry_to_confirmer(version, *, by, confirmer)`, `decide_registry_confirmation(version, *, by, decision, comment, expected_version)`, `request_main_quality`, `request_main_approval` |
| `quality.py` | `quality_sources(case, stage)`, `main_quality_version_block(case, version)`, `sign_main_quality(version, *, by, signature=None)`, `submit_main_quality_to_head(version, *, by)`, `apply_quality_conclusion(version)` (при `ACTIVE` заключения: `quality_decision/quality_conclusion` в версии-источники + `compute_quality`) |
| `registry.py` | `rebuild_violation_projection(version)`, `form_links(case, version) -> dict` (варианты `violationId/riskId/questionId/resultId/transfer/claim`) |
| `delivery.py` | `deliverable(kind)`, `deliver(version, *, action, by, text="", attachment_ids=(), grounds="", signature=None) -> DocumentDelivery` (`send\|acknowledge\|respond\|sign\|object\|refuse`), `record_acknowledgement(version, *, channel, by, acknowledged_on=None, proof_ref="", attachment=None)` (копия prof) |
| `information_requests.py` | `request_state(version, now) -> str`, `available_request_actions(case, version, user, now)`, `transition_request(version, *, action, by, text="", attachment_ids=(), deadline=None, now=None)`, `process_overdue(now) -> int` (планировщик) |
| `attachments.py` | `attach_version_file(version, *, kind, uploaded_file, uploaded_by, slot="")`, `version_attachments(version, *, kind=None, slot=None)`, `delete_version_attachment(version, attachment, *, by)` (только `DRAFT`), `attachment_ref(attachment) -> dict` |
| `print_context.py` | `build_print_context(case, version) -> dict` (снимок дела; `sources` — по `DocumentSourceVersion`) |
| `permissions.py` | `assert_owner(version, user)`, `assert_route_participant(route, user, phase)`, `assert_assigned(kind, obj, user)`, `assert_group_member(version, user)`, `assert_leader(version, user)`, `actor_role(user) -> str` (роль в терминах фронта, кэш на запрос) |
| `commit.py` | `commit_version(version, *, by, now)` — побочные эффекты `saveDocument` §2.12 (п. 7–13 `evga-workflows.md`): `Appeal` при `ACTIVE objections`; `apply_quality_conclusion`; эффекты регистрации `additional` (`execution_state`, `CaseBasis`, `schedule_end`, закрытие); `compute_quality`; закрытие по `completion`/`counter-notification`; `record_event`; `notify(recipients_for_version(version))` |
| `legacy.py` | `LEGACY_STATUS_MAP`, `DROPPED_LEGACY_STATUSES`, `LEGACY_ACTION_MAP` (код `ActionSpec` → BPMN/n8n `action_code`), `DROPPED_LEGACY_ACTIONS` |

**`apps/evga_documents/workflows/`** — `base.py` (`Transition`, `TRANSITIONS_BY_WORKFLOW`, `find_transition`), `route.py`, `preparation.py`, `main.py`, `quality.py`, `direct.py`, `delivery.py` (T2), `ersop.py` (T3), `information_request.py` (T7) — константы §5.4.

**`apps/evga_workflow/services/`**: `routes.py` — `create_route(version, *, initiator, stages: list[dict], signer=None, signer_action="approve", mode="sequential", now=None) -> ApprovalRoute`, `decide_route(route, *, actor, action, comment="", expected_version, now=None)`, `supersede_route(route, *, actor, new_version)`, `activate_signer(route)`, `replace_participant(route, *, old, new, by)` (BPMN `change_approver/change_confirmer/change_head/change_kvga_confirmer/change_reestr_confirmer`), `current_route(version)`, `has_active_route(version)`; `candidates.py` — `route_reviewer(kind, user)`, `route_approver(kind, user)`, `route_candidates(document, user) -> {reviewers, signers, signer_required}`; `tasks.py` — `approval_tasks(user, *, tab, case=None, status=None)`, `sent_routes(user)`, `process_tasks(user)`.

**`apps/evga_appeals/services/`**: `appeals.py` — `get_or_create_appeal(case)`, `assign_expert(case, *, by, expert)`, `record_admission(case, *, by, decision, reason, attachment_ids)`, `notify_admission(case, *, by, attachment_ids)`, `save_arguments(case, *, by, rows, submit)`, `decide_arguments(case, *, by, approve, comment="")`, `appeal_submission_block(case)`; `third_parties.py` — `record_no_third_parties(case, *, by, reason)`, `add_third_party(case, *, by, name, identification, violation_row_ids, notice_at, attachment_ids)`, `record_third_party_event(notice, *, by, event, date, text, attachment_ids)`, `assert_past_date(...)`.

**`apps/evga_execution/services/`**: `items.py` — `rebuild_prescription_items(version)`, `rebuild_recommendations(version)`, `rebuild_response_measures(version)`, `execution_items(*, cases, user, filters) -> list[dict]`; `responses.py` — `effective_response_version(document)`, `assert_execution_response_save(previous, next)`, `response_confirms_source_version(response_doc, source_version)`.

**`apps/evga_ersop/services/`**: `registration.py` — `registration_block(version) -> list[str]`, `submit_registration(version, *, by, signature=None) -> ErsopRegistration`, `poll_registration(registration, *, source="user") -> ErsopRegistration`, `apply_registration_result(registration, result: dict, *, source="ersop")` (`REGISTERED` → `commit_version`; `RETURNED/REJECTED` → версия `RETURNED`); `payload.py` — `build_started(version)`, `build_prolonged/…/build_finished` (порт `Build ERSOP Body` + XML-сборщиков `SEND_REQ_TO_ERSOP`); `stub_exchange.py` — `fake_send(registration) -> dict`, `fake_check_status(registration) -> dict` (копия `fake_register_package`); `soap_exchange.py` — `send_message(xml) -> dict`, `get_status(request_id) -> dict` (httpx).

**`apps/notifications/services/notify.py`**: `notify(recipients, *, title, message="", event_type, case=None, document=None, meta=None)`, `recipients_for_version(version) -> set[User]` (правило §2.12 п. 13 `evga-workflows.md`).

**`apps/subjects/services/gbd.py`**: `lookup_legal_entity(bin) -> dict | None`, `lookup_person(iin) -> dict | None`, `upsert_subject_from_gbd(bin, *, by) -> Subject`; адаптеры `StubGbdAdapter` (`data/evga/gbd_stub.json`), `GatewayGbdAdapter` (REST `camel-gateway/api/out-integrations/gbdul|gbdfl`), `ShepSoapAdapter` (`getJurInfoByBin`).

**`apps/accounts/services/role_sync.py`**: `sync_role_assignments_from_claims(user, claims) -> None` (§7.4).

### 5.3 Движок: формат объявления переходов и реестр действий

Формат объявления — структура `surfk.evga_status_transitions` (`document_type_id/workflow_code, from_status_id, action_code, to_status_id, action_name_ru/kz, required_role_code, assignment_type, requires_signature, requires_comment, is_automatic`) как **Python-константы**, не таблица в БД:

```python
# apps/evga_documents/workflows/base.py
@dataclass(frozen=True)
class Transition:
    workflow: str                       # Workflow.ROUTE | PREPARATION | MAIN | QUALITY | DIRECT (или "delivery"/"ersop"/"info_request" для ортогональных под-автоматов)
    from_status: str                    # DocumentStatus (для под-автоматов — состояние связанной таблицы)
    action: str                         # код ActionSpec ("submit", "kvga-decide", …)
    to_status: str | None               # None = без смены статуса (петля)
    roles: frozenset[str]               # роли фронта: {"auditor"}, {"reviewer","approver"}, {"kvga"}, {"object"} …
    assignment: str = ""                # author | owner | route_participant | route_signer | kvga_confirmer | registry_confirmer | workgroup | workgroup_lead | qc_expert | qc_head | appeal_expert | object
    requires_signature: bool = False    # BPMN requires_signature (ЭЦП) — проверяется только при EVGA_SIGNATURE_REQUIRED
    requires_comment: bool = False
    is_automatic: bool = False          # таймер / ответ ЕРСОП (source=timer|ersop)
    guard: str = ""                     # имя функции *_block в gates/preparation/main/quality (пусто = только проверки сервиса)
    kinds: frozenset[str] = ALL         # сужение на виды внутри семейства (instruction, assignment, report, violations, quality2 …)
    legacy_code: str = ""               # BPMN/n8n action_code
    name_ru: str = ""; name_kk: str = ""

TRANSITIONS_BY_WORKFLOW: dict[str, tuple[Transition, ...]] = {Workflow.ROUTE: route.TRANSITIONS, …}
def find_transition(workflow: str, status: str, action: str, kind: str) -> Transition | None: ...
def transitions_from(workflow: str, status: str, kind: str) -> list[Transition]: ...
```

Реестр действий (из C, адаптирован под явные view prof):

```python
# apps/evga_documents/services/actions.py
@dataclass(frozen=True)
class ActionSpec:
    code: str                            # "submit" — совпадает с сегментом URL …/submit/
    label: str                           # «Направить на согласование»
    service: Callable                    # state_machine.submit / preparation.send_instruction_to_kvga / …
    domain: str = PermissionDomain.EVGA_CASES
    levels: frozenset[str] = frozenset({PermissionLevel.EDIT})     # для HasDomainLevel
    roles: frozenset[str] = ALL          # роли фронта, кому действие вообще показывается
    workflows: frozenset[str] = ALL      # Workflow, где действие имеет смысл (грубый фильтр; точная таблица — Transition)
    statuses: frozenset[str] = ALL
    requires_comment: bool = False
    requires_expected_version: bool = True
    payload_serializer: type[Serializer] | None = None
    audit_action: str = AuditAction.DECIDE
    legacy_codes: tuple[str, ...] = ()   # BPMN/n8n: ("submit",), ("kvga_confirm", "kvga_return"), ("send_to_ersop",) …
    returns_case: bool = False           # ответ — workspace (изменилось несколько документов)
    cabinet: bool = False                # действие доступно представителю ОА через /api/evga/cabinet/

ACTIONS = registry(
    ActionSpec("send-to-quality", "Направить на контроль качества", state_machine.send_to_quality, roles={"auditor"}, workflows={ROUTE}, statuses={DRAFT, RETURNED}, audit_action=QUALITY, legacy_codes=("send_to_qc",)),
    ActionSpec("submit", "Направить на согласование", state_machine.submit, roles={"auditor","quality","appeal-expert","object"}, statuses={DRAFT, RETURNED, QUALITY_REVIEW}, payload_serializer=SubmitSerializer, audit_action=SUBMIT, legacy_codes=("submit","send_to_approval","resubmit")),
    ActionSpec("approve", "Согласовать / Утвердить", state_machine.approve, levels={APPROVE, SIGN}, roles={"reviewer","approver"}, statuses={IN_REVIEW, IN_APPROVAL}, audit_action=APPROVE, legacy_codes=("approve","confirm","qc_confirm")),
    ActionSpec("return", "Вернуть на доработку", state_machine.return_for_revision, levels={APPROVE, SIGN}, roles={"reviewer","approver"}, statuses={IN_REVIEW, IN_APPROVAL}, requires_comment=True, audit_action=RETURN, legacy_codes=("return","return_from_approval","return_from_confirmation","return_for_revision","qc_return")),
    ActionSpec("reject", "Отклонить", state_machine.reject, levels={APPROVE, SIGN}, roles={"reviewer","approver"}, statuses={IN_REVIEW, IN_APPROVAL}, requires_comment=True, audit_action=REJECT, legacy_codes=("reject",)),
    ActionSpec("recall", "Отозвать с согласования", state_machine.recall, domain=EVGA_APPEALS, roles={"appeal-expert"}, statuses={IN_REVIEW}, audit_action=RECALL),
    ActionSpec("activate", "Подписать и активировать", state_machine.activate, levels={EDIT, SIGN}, roles={"auditor","object"}, workflows={DIRECT}, statuses={DRAFT, RETURNED}, audit_action=ACTIVATE, legacy_codes=("activate","sign","signed","send_to_ak"), cabinet=True),
    ActionSpec("revise", "Создать новую редакцию", revisions.create_revision, roles=ANY_OWNER, payload_serializer=ReviseSerializer, requires_expected_version=False, audit_action=NEW_VERSION, legacy_codes=("new_version",)),
    ActionSpec("kvga-send", "Направить на подтверждение КВГА", preparation.send_instruction_to_kvga, roles={"auditor"}, workflows={PREPARATION}, statuses={AGREED}, payload_serializer=ConfirmerSerializer, audit_action=SEND, legacy_codes=("send_to_kvga",)),
    ActionSpec("kvga-decide", "Решение КВГА", preparation.decide_instruction_kvga, domain=EVGA_REGISTRY, levels={CONFIRM}, roles={"kvga"}, statuses={PENDING_KVGA}, payload_serializer=DecisionSerializer, audit_action=CONFIRM, legacy_codes=("kvga_confirm","kvga_return","kvga_reject")),
    ActionSpec("request-quality", "Направить комплект на КК", preparation.request_preparation_quality | main.request_main_quality, roles={"auditor"}, workflows={PREPARATION, MAIN}, statuses={AGREED}, audit_action=QUALITY, legacy_codes=("send_to_qc","send_to_qc_stage2")),
    ActionSpec("request-approval", "Направить на окончательное утверждение", preparation.send_preparation_for_approval | main.request_main_approval, roles={"auditor"}, workflows={PREPARATION, MAIN}, statuses={AGREED}, audit_action=SEND, legacy_codes=("send_to_confirmation","send_to_work_group")),
    ActionSpec("group-request", "Направить на подписание РГ", main.request_report_group_signatures, roles={"auditor"}, workflows={MAIN}, statuses={DRAFT}, legacy_codes=("send_to_work_group",)),
    ActionSpec("group-sign", "Подписать участником РГ", preparation.sign_assignment_group | main.sign_report_group, levels={VIEW, EDIT, SIGN}, roles={"auditor","invited-specialist"}, statuses={GROUP_SIGNING}, audit_action=SIGN, legacy_codes=("sign_work_group",)),
    ActionSpec("group-approve", "Утвердить руководителем РГ", preparation.approve_assignment_group, roles={"auditor"}, statuses={GROUP_SIGNING}, audit_action=SIGN, legacy_codes=("approve_work_group",)),
    ActionSpec("registry-send", "Направить реестр на подтверждение", main.send_registry_to_confirmer, roles={"auditor"}, workflows={MAIN}, statuses={AGREED}, payload_serializer=ConfirmerSerializer, legacy_codes=("send_to_reestr_confirmer",)),
    ActionSpec("registry-decide", "Решение подтверждающего реестра", main.decide_registry_confirmation, domain=EVGA_REGISTRY, levels={CONFIRM}, roles={"reestr-confirmer"}, statuses={PENDING_REGISTRY}, payload_serializer=DecisionSerializer, audit_action=CONFIRM, legacy_codes=("reestr_confirm","reestr_return","reestr_reject")),
    ActionSpec("quality-sign", "Подписать заключение", quality.sign_main_quality, domain=EVGA_QUALITY, levels={EDIT, SIGN}, roles={"quality"}, workflows={QUALITY}, statuses={DRAFT}, audit_action=SIGN, legacy_codes=("sign_zkk","sign")),
    ActionSpec("quality-submit-to-head", "Направить руководителю КК", quality.submit_main_quality_to_head, domain=EVGA_QUALITY, roles={"quality"}, statuses={DRAFT}, legacy_codes=("submit_confirm","send_to_confirmation")),
    ActionSpec("ersop-send", "Направить на регистрацию в ЕРСОП", ersop.submit_registration, roles={"auditor"}, statuses={ACTIVE, RETURNED}, audit_action=EXCHANGE, legacy_codes=("send_to_ersop","register_ersop")),
    ActionSpec("ersop-check-status", "Проверить статус регистрации", ersop.poll_registration, roles={"auditor"}, statuses={ACTIVE}, requires_expected_version=False, audit_action=EXCHANGE, legacy_codes=("check_status",), returns_case=True),
    ActionSpec("ersop-register", "Учесть ответ ЕРСОП (стенд)", ersop.apply_registration_result, domain=EVGA_ADMIN, levels={DECIDE}, roles={"auditor","evga-admin"}, statuses={ACTIVE}, payload_serializer=RegistrationResultSerializer, requires_expected_version=False, audit_action=REGISTER, legacy_codes=("ersop_registered","ersop_rejected","ersop_revision"), returns_case=True),
    ActionSpec("deliver", "Направить объекту аудита", delivery.deliver_send, roles={"auditor","appeal-expert"}, statuses={ACTIVE, AGREED}, audit_action=DELIVER, legacy_codes=("send_to_audit_object","send_to_oa")),
    ActionSpec("deliver-acknowledge", "Ознакомлен", delivery.deliver_acknowledge, domain=EVGA_CABINET, roles={"object"}, statuses={ACTIVE}, audit_action=ACKNOWLEDGE, legacy_codes=("audit_object_acknowledged","oa_acknowledge","acknowledge"), cabinet=True),
    ActionSpec("deliver-respond", "Предоставить ответ", delivery.deliver_respond, domain=EVGA_CABINET, roles={"object"}, statuses={ACTIVE}, payload_serializer=ResponseSerializer, cabinet=True),
    ActionSpec("deliver-sign", "Подписать без возражений", delivery.deliver_sign, domain=EVGA_CABINET, roles={"object"}, statuses={ACTIVE}, audit_action=SIGN, legacy_codes=("sign_without_objection","accept"), cabinet=True),
    ActionSpec("deliver-object", "Подписать с возражениями", delivery.deliver_object, domain=EVGA_CABINET, roles={"object"}, statuses={ACTIVE}, payload_serializer=GroundsSerializer, audit_action=SIGN, legacy_codes=("sign_with_objection","objection"), cabinet=True),
    ActionSpec("deliver-refuse", "Зафиксировать отказ от подписания", delivery.deliver_refuse, roles={"object","auditor"}, statuses={ACTIVE}, payload_serializer=GroundsSerializer, cabinet=True),
    ActionSpec("manual-acknowledgement", "Нарочное ознакомление (скан)", delivery.record_manual_acknowledgement, roles={"auditor"}, statuses={ACTIVE}, payload_serializer=ManualAckSerializer, audit_action=ACKNOWLEDGE, legacy_codes=("acknowledge_case_document",)),
    ActionSpec("ir-send", …), ActionSpec("ir-acknowledge", …, cabinet=True), ActionSpec("ir-provide", …, cabinet=True), ActionSpec("ir-refuse", …, cabinet=True),
    ActionSpec("ir-review", …), ActionSpec("ir-accept", …), ActionSpec("ir-reject", …, requires_comment=True), ActionSpec("ir-resend", …), ActionSpec("ir-mark-refused", …, requires_comment=True),
        # все ir-* → information_requests.transition_request(action=…); legacy_codes: send_to_audit_object, acknowledge, provide_info, refuse_info, review_info, accept_info, reject_info, resend_to_oa, mark_refused
    ActionSpec("apply-amendment", "Применить дополнительное поручение", amendments.apply_amendment, roles={"auditor"}, statuses={ACTIVE}, audit_action=UPDATE, returns_case=True, legacy_codes=("apply_amendment",)),
    ActionSpec("validate", "Проверить форму", validation.validate_only, roles=ANY, requires_expected_version=False, audit_action=""),
)
```

Единая точка применения:

```python
@transaction.atomic
def apply_action(document, *, spec, actor, payload, expected_version=None, expected_row_version=None, now=None) -> ActionResult:
    case = AuditCase.objects.select_for_update().get(pk=document.case_id)          # сериализует все действия по делу
    document = AuditDocument.objects.select_related("document_type").get(pk=document.pk)
    version = document.active_version
    assert_case_open(case)                                                            # «Дело закрыто»
    if spec.requires_expected_version and expected_version != version.version:
        raise StaleVersionError("Открыта устаревшая версия документа. Обновите дело")       # → 409
    if expected_row_version is not None and expected_row_version != version.row_version:
        raise StaleVersionError("Документ изменился. Обновите дело перед сохранением решения")
    if version.status not in spec.statuses or document.document_type.workflow not in spec.workflows:
        raise DocumentTransitionError(f"Действие «{spec.label}» недоступно из статуса «{version.get_status_display()}»")
    if actor_role(actor) not in spec.roles: raise PermissionDenied(...)              # → 403; адресные проверки — внутри сервиса
    if spec.requires_comment and not (payload.get("comment") or "").strip(): raise DocumentTransitionError("Укажите замечание.")
    status_from = version.status
    result = spec.service(version, by=actor, now=now, **payload)                      # порт TS-функции: сама проверяет блоки/статусы/назначения
    version.refresh_from_db(); version.row_version += 1; version.save(update_fields=["row_version", "updated_at"])
    commit_version(version, by=actor, now=now)                                        # эффекты saveDocument + compute_quality + notify
    record_event(version, action=spec.audit_action, action_code=spec.code, actor=actor, case=case,
                 status_from=status_from, status_to=version.status, reason=payload.get("comment", ""),
                 metadata={"version": version.version, "legacy_codes": spec.legacy_codes})
    return ActionResult(document=document, version=version, case=case, returns_case=spec.returns_case)
```

`available_actions(document, user)` — тот же реестр: фильтр по роли/workflow/статусу + `transitions_from(...)` + вызов соответствующего `*_block`/`can_*` для `enabled`/`blocked_reason`. Ответ фронту — тот же JSON, что BPMN отдавал через `workflow-update` (`code, name_ru, name_kk, requires_signature, requires_comment, enabled, blocked_reason`), но **вычисленный** (правило `get_available_actions` n8n §4.4: для `workgroup/workgroup_lead` достаточно назначения, для прочих `assignment` — роль ∧ назначение, без `assignment` — роль).

Тест-инвариант движка: для каждого `Transition` существует `ActionSpec` с тем же `action`; для каждого `ActionSpec.code` есть URL и `DocumentActionView`; каждый код из каталога `bpmn-processes.md` §6/§7 либо присутствует в `legacy_codes`/`LEGACY_ACTION_MAP`, либо в `DROPPED_LEGACY_ACTIONS` с причиной.

### 5.4 Таблицы переходов документа по семействам

Обозначения: роли — фронтовые (`auditor` = автор/соавтор дела или владелец версии; `reviewer` = согласующий (legacy `approver`); `approver` = утверждающий (legacy `confirmer`)); `expected_version` обязателен у всех решений; `now` — единый в транзакции; в колонке «Legacy» — BPMN/n8n `action_code` и семейство T0–T9 (`bpmn-processes.md` §2.3, §6). Все таблицы — порт `evga-workflows.md` §2.3–§2.11 без изменений семантики.

**5.4.1 Общий маршрут (`Workflow.ROUTE`; также `QUALITY` для quality1/quality3 с ограничениями `route_candidates`) — T1**

| Из | Действие (сервис) | В | Роль / назначение | Guard | Эффекты | Legacy |
|---|---|---|---|---|---|---|
| — | `create_document` | `DRAFT` v1 | по `creation_access_block` | `creation_block`; неповторяемый вид — «Документ уже создан.» | номер, `initial_values`, `VersionParticipant`, `DocumentSourceVersion`, событие «Создана версия v1» | `create` (`Docs: CRUD`) |
| `DRAFT`, `RETURNED` | `save_draft` (PATCH) | — | владелец, `can_edit` | `expected_row_version`; `assert_attachment_retention` | `values/group/print_context`, проекции, «Сохранены изменения» | `save`, `update` |
| `DRAFT`, `RETURNED` | `send_to_quality` | `QUALITY_REVIEW` | владелец, `can_edit` | `requires_quality`; не prep («Сначала согласуйте подготовительные документы…»), не main («Сначала согласуйте основной комплект и подтвердите реестр…»); `validate_document` | `quality_decision=""`; уведомление всем `quality` | `send_to_qc` (дело) |
| `DRAFT`, `RETURNED`, `QUALITY_REVIEW` | `submit` | `IN_REVIEW` | владелец; prep/main — автор/соавтор; quality* — назначенный эксперт | `can_submit`; `requires_quality` ⇒ `quality_decision == NO_REMARKS`; стадии непусты, участники без повторов, инициатор не среди согласующих; signer обязателен кроме `assignment`/`report`; `route_candidates` (quality* → signer = `evga-qc-head` («Заключение КК утверждает руководитель контроля качества»); objection-result → комиссия/председатель; иначе не qc-head и не комиссия); `quality2` → «Подпишите заключение и направьте непосредственно руководителю КК» | если `RETURNED` и есть маршрут → `create_returned_revision`; `create_route`; prep: `DocumentSourceVersion` = `preparation_references`; main: `main_references`; `submitted_at`; событие «Направлено на последовательное согласование» | `submit`, `send_to_approval`, `resubmit` (T1) |
| `IN_REVIEW` | `approve` (согласующий) | `IN_REVIEW` (остались pending) / `IN_APPROVAL` (signer активирован) / `AGREED` (prep/main: все approved, signer `waiting`) / `ACTIVE` (нет signer, не prep/main) | `ApprovalParticipant(status=pending)` роли `reviewer` | `expected_version`; prep: `preparation_current/references_block`; main: `main_current/references_block`; quality2: `main_quality_version_block` | `decide_route(approve)`; `DocumentSignature(kind=ROUTE)`; prep/main → `agreed_at`; событие «Согласовано» | `approve` (`approved`) |
| `IN_APPROVAL` | `approve` (signer) | `ACTIVE` | signer маршрута роли `approver` | prep: `preparation_approval_block`; main: `main_approval_block`; quality2: `main_quality_version_block` | `activated_at/by`; `DocumentSignature(ROUTE)`; `issue_registration_number` (если `reg_number_format`); `commit_version` | `confirm` (`active`/`confirmed`) |
| `IN_REVIEW`, `IN_APPROVAL` | `return_for_revision` | `RETURNED` | текущий pending участник | `comment` («Укажите замечание.») | `decide_route(return)`; остальные `cancelled`; `quality_decision=""`; `returned_comment`; задача `revise` инициатору | `return` (`revision`) — T1b |
| `IN_REVIEW`, `IN_APPROVAL` | `reject` | `REJECTED` | текущий pending участник | `comment` («Укажите причину отклонения.») | маршрут `rejected`; `rejected_comment` | нет в BPMN (только у КВГА/реестра) |
| `IN_REVIEW`, `IN_APPROVAL` | `replace_participant` (`POST /tasks/routes/{id}/replace-participant/`) | — | инициатор (автор) | участник ещё `pending/waiting` | `ApprovalParticipant.replaced_by`, событие `replace` | `change_approver`, `change_confirmer`, `change_head` |
| `IN_REVIEW` | `recall` | `DRAFT` | владелец-эксперт (`objection-result`) | ни одного решения («Отзыв доступен исполнителю до первого согласования») | `supersede_route`, участники `cancelled` | — |
| `RETURNED` | `revise(reason="returned")` | `DRAFT` v+1 | владелец (= инициатор; quality* — и новый эксперт) | `status == RETURNED` | старый маршрут `superseded`, старая версия `frozen_at`; сброс подписей/маршрутов/КК/регистрации/доставки/раундов; событие «Создана версия vN для доработки» | `shouldCreateVersion:true` |
| `REJECTED` | `revise(reason="rejected")` | `DRAFT` v+1 | владелец | | как выше, «Создана новая версия vN после отклонения» | |
| `ACTIVE`/`QUALITY_REVIEW`/`AGREED` с `quality_conclusion` | `revise(reason="quality-remarks")` (`create_next_version`) | `DRAFT` v+1 | `auditor` | «Новая версия доступна после заключения контроля качества.» | копирует `values/attachments/group` | Q07 |

**5.4.2 Прямая активация (`Workflow.DIRECT`) — T0**

| Из | Действие | В | Роль | Guard | Эффекты | Legacy |
|---|---|---|---|---|---|---|
| `DRAFT`, `RETURNED` | `activate` | `ACTIVE` | владелец (`object` для objections), `can_submit`, `owner` совпадает | `directActivation(kind)`; `validate_document`; `creation_block` пуст | `DocumentSignature(kind=ACTIVATION, provider=stub)`; `activated_at/by`; `issue_registration_number`; `commit_version` (objections → `Appeal`; для account/notification — далее T3) | `activate`, `sign`, `signed` (`evga_doc_51`), `send_to_ak` (M20-VOZ) |

**5.4.3 Подготовительный этап (`Workflow.PREPARATION`: irpi, program, plan, assignment, instruction, counter-instruction) — T1 + T4 + T5 + КК1** (порт `preparationWorkflow.ts`, `evga-workflows.md` §2.4)

Блоки: `preparation_current_block` (версия/состояние совпадает — на сервере заменён `expected_version` + `select_for_update`), `preparation_submission_block` (дело `OPEN`, не `SUSPENDED`; все `preceding` по `sequence` irpi→program→plan→assignment→instruction согласованы — «Сначала согласуйте: …»; план/задание учитываются только если созданы), `preparation_references_block` («Изменился состав или версия предыдущих документов. Создайте новую редакцию и повторите согласование»), `preparation_quality_block(case)` (есть irpi, program, instruction — «Подготовьте документ: …»; все согласованы; `KvgaConfirmation.status == CONFIRMED` — «Получите подтверждение поручения назначенным сотрудником КВГА»), `preparation_approval_block(case, version)` («Сначала завершите согласование документа»; counter-instruction — только КВГА; иначе `quality1` `ACTIVE` `NO_REMARKS` по актуальным версиям — «Получите утверждённое заключение КК подготовительного этапа без замечаний» / «Заключение КК относится к предыдущим версиям. Проведите повторный контроль качества»; все `preceding` уже `ACTIVE` — «Сначала утвердите: …»).

| Из | Действие | В | Роль / назначение | Guard | Эффекты | Legacy |
|---|---|---|---|---|---|---|
| `DRAFT`/`RETURNED` | `submit` | `IN_REVIEW` | автор/соавтор | `preparation_submission_block` | `sources := preparation_references`; маршрут без signer у `assignment` | `submit` + гейт `prev_approved`/`check-docs-status [M8-PLAN, M6-PA-*] approved` (вычисляется) |
| `IN_REVIEW` → все approved | `approve` | `AGREED` | reviewer | `preparation_references_block` | `agreed_at`; `route.signer_activated=False` | `approve` → `approved` |
| `AGREED` (instruction, counter-instruction) | `kvga-send` (`send_instruction_to_kvga(confirmer)`) | `PENDING_KVGA` | автор/соавтор | `isPreparationAgreed`; kvga ещё не `CONFIRMED`; `preparation_references_block`; `confirmer` — роль `evga-kvga` | `KvgaConfirmation(PENDING)`; «Поручение направлено на подтверждение КВГА» | `send_to_kvga` (T4) |
| `PENDING_KVGA` | `kvga-decide(confirm)` | `AGREED` | назначенный `KvgaConfirmation.confirmer` | `expected_version`; референсы | `status=CONFIRMED`, `DocumentSignature(KVGA)`; «Поручение подтверждено КВГА» | `kvga_confirm` → `kvga_confirmed`; `ready_send_to_qc` делу — не нужен (вычисляется) |
| `PENDING_KVGA` | `kvga-decide(return)` | `RETURNED` (instruction) / `AGREED` (counter-instruction) | назначенный | comment («Укажите причину возврата») | `status=RETURNED`, `comment`; «Поручение возвращено КВГА»; legacy `publish_case_message(closed)` **не выполняется** | `kvga_return`, `kvga_reject` |
| `AGREED` (instruction) | `request-quality` (`request_preparation_quality`) | — | автор | `preparation_quality_block` пуст; ещё не направлен («Комплект уже направлен на КК») | `quality_requested_at`; «Согласованный комплект подготовительного этапа направлен на КК»; открывает `creation_block(quality1)` | `send_to_qc` (дело S1) |
| `AGREED` (prep, кроме assignment) | `request-approval` (`send_preparation_for_approval`) | `IN_APPROVAL` | автор | `preparation_approval_block` пуст | `activate_signer(route)`, `approval_requested_at`; «Направлено на окончательное утверждение» | `send_to_confirmation` (после `ready_kvga_confirmed`/`prev_approved` — вычисляется) |
| `AGREED` (assignment) | `request-approval` | `GROUP_SIGNING` | автор | группа непуста, ровно один лидер, id уникальны («Укажите рабочую группу и одного руководителя группы») | `DocumentSignature`-ожидания не создаются (вычисляется по `VersionParticipant`); «Направлено на подписание рабочей группой» | `send_to_work_group` (T5) |
| `GROUP_SIGNING` (assignment) | `group-sign` (`sign_assignment_group`) | — | участник `VersionParticipant` роли `auditor`/`invited-specialist` | `preparation_approval_block`; не подписывал («Ваша подпись уже сохранена») | `DocumentSignature(GROUP)`; «Аудиторское задание подписано участником рабочей группы» | `sign_work_group` (`work-group-approval sign`) |
| `GROUP_SIGNING` (assignment) | `group-approve` (`approve_assignment_group`) | `ACTIVE` | лидер (`is_leader`) | все не-лидеры подписали («Дождитесь подписей всех участников рабочей группы») | подпись лидера; `activated_at`; `commit_version` | `approve_work_group` |
| `IN_APPROVAL` | `approve` (signer) | `ACTIVE` | signer | `preparation_approval_block` | `commit_version` | `confirm` |
| `AGREED`/`IN_APPROVAL`/`GROUP_SIGNING`/`ACTIVE` (prep) | `revise(reason="preparation")` | `DRAFT` v+1 | автор | статус из перечня | `supersede_route`; новая версия без preparation/sources/маршрута/подписей/КК/registration/delivery; «Создана новая редакция vN; требуется повторное согласование и КК»; инвалидирует `quality_stage_passed[0]` | `shouldCreateVersion` |

**5.4.4 Основной этап (`Workflow.MAIN`: report, violations, evidence) — T5 + T1 + подтверждение реестра + КК2** (порт `mainWorkflow.ts`, §2.5)

Блоки: `main_current_block`, `main_preparation_block(case)` («Завершите актуальную подготовку и КК подготовительного этапа»), `main_submission_block` (report: ссылки на program/instruction актуальны — «Изменились подготовительные документы. Создайте новую редакцию отчёта»; группа непуста; `group_requested_at`; все подписали — «Получите подписи всех участников рабочей группы под отчётом»; violations/evidence: отчёт `isMainAgreed` — «Сначала подпишите рабочей группой и согласуйте отчёт»; evidence: реестр `isMainAgreed` — «Сначала согласуйте реестр нарушений»), `main_references_block` («Изменились исходные документы. Создайте новую редакцию и повторите согласование»), `main_confirmation_block(case)` («Подготовьте отчёт и реестр нарушений»; «Сначала согласуйте …»), `main_quality_block(case)` («Получите подтверждение реестра назначенным сотрудником»; «Комплект изменился после подтверждения реестра. Повторите подтверждение»), `main_quality_conclusion_block(case)` («Получите утверждённое заключение КК основного этапа без замечаний»; «Заключение КК относится к предыдущим версиям. Проведите повторный контроль качества»), `main_approval_block(case, version)` (report — всегда блок: «Отчёт согласуется после подписей рабочей группы; отдельное утверждение не предусмотрено»; evidence: «Сначала утвердите реестр нарушений»), `main_delivery_block(case, version)` («Сначала утвердите реестр и все существующие аудиторские доказательства»), `main_quality_version_block(case, version)` («Комплект изменился. Создайте актуальную редакцию заключения КК»; «Автор дела должен направить комплект на КК»).

| Из | Действие | В | Роль / назначение | Guard | Эффекты | Legacy |
|---|---|---|---|---|---|---|
| `DRAFT` (report) | `group-request` (`request_report_group_signatures`) | `GROUP_SIGNING` | автор/соавтор | `main_preparation_block`; нет `group_requested_at`; группа корректна («Проверьте участников рабочей группы…») | `sources := main_references`; `group_requested_at`; «Отчёт направлен на подпись всем участникам рабочей группы» | `send_to_work_group` (`m18_m19_auto_create`) |
| `GROUP_SIGNING` (report) | `group-sign` (`sign_report_group`) | `DRAFT` когда подписали все, иначе — | участник РГ | `main_preparation_block`; ссылки актуальны; не подписывал | `DocumentSignature(GROUP)`; при полном комплекте → `DRAFT` (редактирование запрещено: `group_requested_at`) | `sign_work_group` → `work_group_complete` → `signed` |
| `DRAFT` (report, все подписи) | `submit` (без signer) | `IN_REVIEW` | автор | `main_submission_block` | маршрут без signer | `submit` |
| `DRAFT` (violations/evidence) | `submit` | `IN_REVIEW` | автор | `main_submission_block` (`is_registered`; report `isMainAgreed`; evidence: реестр agreed) | `sources := main_references` | `submit` + гейт `prev_approved` (вычисляется) |
| `IN_REVIEW` → все approved | `approve` | `AGREED` | reviewer | `main_references_block` | `agreed_at` | `approve` → `approved` |
| `AGREED` (violations) | `registry-send` (`send_registry_to_confirmer(confirmer)`) | `PENDING_REGISTRY` | автор | `main_confirmation_block`; confirmer роли `evga-reestr-confirmer` | `RegistryConfirmation(PENDING)` + `DocumentSourceVersion(role=CONFIRMATION)` на все main текущих версий; `quality_requested_at := None`; «Реестр направлен назначенному подтверждающему» | `send_to_reestr_confirmer` → `pending_kvga` (M18) |
| `PENDING_REGISTRY` | `registry-decide(confirm)` / `(return)` | `AGREED` / `RETURNED` | назначенный `RegistryConfirmation.confirmer` | `main_confirmation_block`; `sources(CONFIRMATION)` актуальны («Комплект изменился. Повторно направьте реестр на подтверждение»); return требует comment | `status/comment/decided_at`; `DocumentSignature(REGISTRY)`; «Реестр подтверждён»/«Реестр возвращён на доработку» | `reestr_confirm` → `kvga_confirmed`; `reject`; `ready_send_to_qc_2` делу — вычисляется |
| `AGREED` (violations, confirmed) | `request-quality` (`request_main_quality`) | — | автор | `main_quality_block`; не направлен | `quality_requested_at`; «Согласованный и подтверждённый комплект основного этапа направлен на КК»; открывает `creation_block(quality2)` | `send_to_qc_stage2` (дело S5) |
| `AGREED` (violations, evidence) | `request-approval` (`request_main_approval`) | `IN_APPROVAL` | автор | `main_approval_block` | `approval_requested_at`; `activate_signer`; «Документ направлен на окончательное утверждение после КК» | `send_to_confirmation` (после `ready_send_confirmation` — вычисляется) |
| `IN_APPROVAL` (violations/evidence) | `approve` (signer) | `ACTIVE` | signer | `main_approval_block` (повторно на commit) | `commit_version` | `confirm` → `active`; `doc_approved` отчёту — вычисляется |
| `AGREED` (report) | `deliver` (`deliver_send`) | `ACTIVE` + `DocumentDelivery.sent_at` | автор/соавтор | `main_delivery_block` | отчёт не имеет отдельного утверждения; уведомление всем `object`; `objection_due_on` | `send_to_audit_object` → дело `awaiting_objections` (вычисляется) |
| любой (main) | `revise(reason="main")` (`revise_main_document`) | `DRAFT` v+1 | автор | не «`DRAFT` без `main`» («Редактируйте существующий проект») | сброс `main`-полей, `sources`, маршрута, подписей, КК, delivery, registration; «Создана редакция vN; требуется повторное подписание и согласование» | |

**5.4.5 Заключения КК (`Workflow.QUALITY`) — T6**

КК1 (`quality1`) и КК3 (`quality3`) — общий маршрут §5.4.1 с ограничениями: создать/редактировать/отправить может только эксперт, назначенный руководителем КК на этап (`quality_assignment_block`); `submit` требует signer = `evga-qc-head`; `validate_document` — `sourceVersions` обязательны, `values.quality.level ∈ {Первый уровень, Второй уровень}`, участники `version.group` не входят в `case.participants` («Контроль качества проводит сотрудник, не участвовавший в этом аудите»), для stage 0 — `coverage[].assessmentRu`; `renew_quality` (`revise(reason="renew-quality")`) — только назначенный эксперт, версия `ACTIVE`, `creation_block` пуст → новая версия `DRAFT`, `values = {quality: old.values.quality}`, `sources = qualitySources` (+ активный `objection-result` для stage 1); «Начат повторный контроль качества».

КК2 (`quality2`) — особый маршрут без согласующих:

| Из | Действие | В | Роль / назначение | Guard | Эффекты | Legacy |
|---|---|---|---|---|---|---|
| — (дело) | `assign_quality_expert(stage, expert, reason)` | `QualityAssignment` | `evga-qc-head` | эксперт не участник дела; при замене — `reason`; подписанный `quality2` → `revise_main_quality` без чужой подписи; направленный → `supersede_route` | `unassigned_at` у старого; уведомление эксперту; `AuditEvent(assign)` | дело `assign_qc_expert*`, `change_qc_expert` (S2/S6/S14) |
| — | `create_document(quality2)` | `DRAFT` v1 (`owner` = эксперт) | назначенный эксперт | `creation_block`: `main_quality_block` + `violations.quality_requested_at` («Автор дела должен направить комплект на КК») | `sources = quality_sources(1)` | `create_qc_conclusion_stage2` |
| `DRAFT` | `quality-sign` (`sign_main_quality`) | `DRAFT` + `expert_signed_at` | назначенный эксперт (`owner`) | `main_current_block`, `main_quality_version_block`, `quality_assignment_block(case, 1, user)`; `values.conclusion.decision` и `textRu` заполнены | `DocumentSignature(EXPERT)`; содержимое заморожено (`can_edit=False`) | `sign_zkk`/`sign` → `signed` |
| `DRAFT` (подписан) | `quality-submit-to-head` | `IN_APPROVAL` | эксперт-подписант | ещё не `expert_submitted_at` | `create_route(stages=[], signer=evga-qc-head)`; `expert_submitted_at`; «Подписанное заключение направлено непосредственно руководителю КК» | `submit_confirm`/`send_to_confirmation` |
| `IN_APPROVAL` | `approve` / `return` / `reject` | `ACTIVE` / `RETURNED` / `REJECTED` | `evga-qc-head` (signer) | `main_quality_version_block` (в т.ч. повторно на commit) | `apply_quality_conclusion`: `quality_decision/quality_conclusion` в версии-источники (только текущие, не `ACTIVE` для main), `compute_quality` | `confirm`/`qc_confirm`; `return`/`qc_return` |
| `RETURNED`/`REJECTED`/подписан/устарел | `revise(reason="quality")` (`revise_main_quality`) | `DRAFT` v+1 | назначенный эксперт | `main_quality_block` | `sources` = main + активный `objection-result`; сброс `expert_*`, подписей, маршрута; «Создана актуальная редакция заключения КК vN; требуется подпись эксперта и решение руководителя» | `resubmit_to_qc_stage2` (S12) |

**5.4.6 Регистрация в ЕРСОП (ортогональный под-автомат на `ErsopRegistration`; `is_registrable`: account, counter-account, notification, counter-notification, additional, counter-additional) — T3**

| Из (документ / регистрация) | Действие | Регистрация → | Роль | Guard | Эффекты | Legacy |
|---|---|---|---|---|---|---|
| `ACTIVE` / нет или `RETURNED`/`REJECTED`/`ERROR` | `ersop-send` (`submit_registration`) | `SENT` | `auditor` | `status == ACTIVE` («Сначала утвердите документ»); не отправлен («Документ уже направлен на регистрацию»); `registration_block` (участники УК, `ersop_organ_code`, `AuditType.ersop_code`; additional: `order.type` → `message_type`) | `ErsopExchange(OUT, request_payload=build_*)`; адаптер `send`; «Учёт регистрации: Отправлена» | `send_to_ersop` [ЭЦП] → `sent_to_ersop` |
| `SENT`, `PENDING` | `ersop-check-status` (`poll_registration`) | `PENDING` / `REGISTERED` / `REJECTED` / `RETURNED` / `ERROR` | `auditor` (и планировщик, `source=ersop`) | | `apply_registration_result`: `ErsopExchange(IN)`; `REGISTERED` → `registration_number/date`, `commit_version` (account → `is_registered`; additional → эффекты приказа; counter-notification → закрытие дела); `RETURNED/REJECTED` → версия `RETURNED` + `return_comment` (фронт «Возвращена», `can_edit` снова true) | `check_status` → `ersop_accepted/ersop_registered/ersop_rejected/ersop_revision/ersop_error` |
| `SENT` (стенд) | `ersop-register` (`apply_registration_result(result)`) | `REGISTERED` / `RETURNED` | `auditor` на стенде, в проде — `evga-admin` / callback | `registration.status == SENT` («Документ не ожидает ответа ЕРСОП»); return требует comment («Укажите причину возврата») | как выше | фронт `performRegistration accept/return` («Тестовый ответ») |

**5.4.7 Направление объекту (ортогональный под-автомат на `DocumentDelivery`; `is_deliverable`) — T2**

| Из | Действие | Delivery → | Роль | Guard | Эффекты | Legacy |
|---|---|---|---|---|---|---|
| `ACTIVE` (report: `AGREED`) без `delivery` | `deliver` | `sent_at` | `auditor`; `objection-result` — `appeal-expert`-владелец; report/violations — автор/соавтор | instruction/counter-instruction: `is_registered(case)` («Поручение направляется объекту после регистрации учетной карточки»); additional: `REGISTERED`; report/violations: `main_delivery_block` | `DocumentDelivery(sent_at, expires_at, objection_due_on)`; report `AGREED → ACTIVE`; уведомление всем представителям ОА | `send_to_audit_object` (`send_document_to_audit_object(requires_acknowledgment, expires_days=5)`) |
| после send | `deliver-acknowledge` | `acknowledged_at` | `object` (кабинет) | ещё не ознакомлен («Ознакомление уже зафиксировано») | `Acknowledgement(channel=portal, proof_ref=cabinet:{user.id}:{iso})`; `DocumentSignature(OBJECT)`; «Объект аудита ознакомлен» | `audit_object_acknowledged` [ЭЦП] → `oa_acknowledged` |
| после send | `manual-acknowledgement` | `acknowledged_at` | `auditor` (нарочно, скан) | как prof `record_acknowledgement(manual)`: обязателен `Attachment(kind=acknowledgement_scan)` | `Acknowledgement(channel=manual)` | `acknowledge_case_document` |
| после send | `deliver-respond` | `response_text/attachments/responded_at` | `object` | не для report/violations («По документу требуется явное решение объекта: подпись или отказ»); текст или файл | «Получен ответ объекта» | `oa_respond` (номерное поколение) |
| после send, report/violations/counter-act, нет `decision` | `deliver-sign` | `decision=SIGNED` | `object` | report: `acknowledged_at` («Сначала подтвердите ознакомление объекта с отчётом») | `decided_at/by`; `DocumentSignature(OBJECT)` | `sign_without_objection` [ЭЦП] → `signed_oa` |
| то же | `deliver-object` | `decision=SIGNED_WITH_OBJECTIONS` | `object` | `grounds` («Укажите обоснование»); report — после ознакомления | `grounds`, `decisionAttachments`; разрешает `objections` | `sign_with_objection` → `signed_with_objection` |
| то же | `deliver-refuse` | `decision=REFUSED` | `object` или `auditor` (автор/соавтор) | `grounds` + вложения («Приложите подтверждение отказа и передачи отчёта через канцелярию») | | нет в BPMN (только фронт) |
| после send (report), без решения, `now > objection_due_on` | (таймер) | — | система | `EVGA_AUTO_SIGN_REPORT_AFTER_DAYS` не задан → только `Notification(DEADLINE)` автору | автоподпись **не** реализуется | `signed_automatically` (P10D, `evga_doc_51`) |

**5.4.8 Требование о предоставлении сведений (`is_information_request`: request, counter-request; состояния — на `InformationRequestRound`, документ `ACTIVE`) — T7** (порт `informationRequests.ts`, §2.9)

| Состояние раунда (`request_state`) | Действие | → | Роль | Guard / эффект | Legacy |
|---|---|---|---|---|---|
| нет цикла | `ir-send` | request: `sent`; counter-request: `awaiting` | автор/соавтор | `deadline` из `values.general.deadline` обязателен и позже `now` («Укажите срок предоставления сведений», «Срок предоставления сведений должен быть позже времени отправки»); `DocumentDelivery(sent_at)`; новый `InformationRequestRound` | `send_to_audit_object` (+`deadlineDatetime`) |
| `sent` | `ir-acknowledge` | `awaiting` | `object` | `acknowledged_at` — старт таймера для обычного требования | `acknowledge` → `audit_object_acknowledged` |
| `awaiting` | `ir-provide` | request: `review`; counter: `received` | `object` | текст или файл; `response_at/by/text/attachments` | `provide_info` → `send_to_auditor` / `sent_by_audit_object` |
| `awaiting` | `ir-refuse` | `refused` | `object` | обоснование; `response_refused=True` | `refuse_info` → `info_refused` |
| `received` | `ir-review` | `review` | автор | `review_started_at` (только counter-request) | `review_info` → `under_review` |
| `review` | `ir-accept` / `ir-reject` / `ir-resend` | `accepted` / `refused` / новый раунд (`sent` для request, `awaiting` для counter) | автор | reject/resend: comment; resend: новый `deadline`; старый раунд `review_decision=resend` | `accept_info` [ЭЦП] / `reject_info` [ЭЦП] / `resend_to_oa` |
| `awaiting`, `now >= deadline` | (вычисляемое) | request: `overdue`; counter: `refused` (авто-отказ) | — | `request_state(version, now)`; `process_deadlines` пишет `overdue_marked_at` + `AuditEvent(source=timer)` + уведомление | таймер `deadlineDatetime` → `overdue` / `info_refused` |
| `overdue` | `ir-resend` / `ir-mark-refused` | новый раунд / `refused` | автор | comment | `resend_to_oa`, `mark_refused` |
| `review` | просрочка не наступает | | | | |

Общий guard (`assert_current`): дело открыто, документ — требование, версия `ACTIVE`, `expected_version`. Legacy: старый `delivery.response` мигрирует в цикл как `received` с `response.legacy=true`.

**5.4.9 Ответ о принятых мерах (`response`, `Workflow.ROUTE`) — T8/3.3** (порт `executionDecision.ts`)

Создаёт `auditor` или `object` (`owner_role=object`, если создал объект); `sources` = активные версии `prescription`/`conclusion`; `values.measures` копируют пункты предписания (`violationId`, `amount`, `accepted="0"`), `values.recommendations` — рекомендации заключения. Переходы — §5.4.1 (submit → reviewers → signer → `ACTIVE`). Дополнительные guard'ы: `assert_execution_response_save(previous, next)` в `save_draft` («Изменение направленного ответа требует новой редакции и нового согласования.», «Утверждённый ответ сохранён в истории…», «Результат исполнения применяется после завершения согласования и утверждения ответа.»); `revise(reason="response")` (`create_response_revision`/`reviseExecutionResponse`) — новая версия с перепривязкой строк к текущим активным prescription/conclusion; действующая редакция — `effective_response_version(document)` (последняя `ACTIVE` с маршрутом `completed`); продление срока — `values.general.extension/deadline/extensionReason` только в утверждённой редакции. Legacy-цепочка ОА → `oa_confirmer` → аудитор (`verification`, `oa_confirm`, `with_auditor`, `review_decision`, `accepted`) не переносится (один тип с `owner_role` по создателю; шаг `oa_confirm` — как подпись `OBJECT` без статуса) — **решение по умолчанию до ответа на Q17**.

**5.4.10 Возражения и апелляция (`objections` — `DIRECT` с владельцем `object`; `objection-result` — `ROUTE` с комиссией) — T8/T9** (порт `appeals.ts`, §2.10, §3.7)

| Действие | Роль | Guard | Эффект | Legacy |
|---|---|---|---|---|
| `activate(objections)` | `object` | `creation_block`: report `ACTIVE` с `delivery`; валидация: ссылки на `effective_violations` без повторов и с исходными суммами, дата подачи не в будущем, «По почте» требует вложение | `commit_version` → `get_or_create_appeal(case)` (`received_at` = подпись, `filing_due_on`) | `signed`/`send_to_ak` → `ready_send_to_appeal` (S8→S9) |
| `assign_expert(case, expert)` | `evga-appeal-head` | эксперт роли `evga-appeal-expert`; нет отказа в рассмотрении; `objection-result` в `DRAFT`/`RETURNED` («Дождитесь возврата результатов с согласования перед сменой исполнителя») | `Appeal.expert`; если результат `RETURNED` другому — `reassign_returned_document` (v+1, `owner` = новый эксперт) + уведомление; `AuditEvent(assign, "appeal_assign_expert")` | `assign_qc_expert_appeal` (S9→S10; `case_appeal_expert_assignments` assigned/unassigned) |
| `record_admission(decision, reason, files)` | `evga-appeal-commission-chair` | reason и files обязательны; решения ещё нет; результат не направлен | `admission_*` | нет в legacy |
| `notify_admission(files)` | `evga-appeal-head` или назначенный эксперт | files; решение есть, `admission_notified_at` нет | `admission_notified_at` | нет |
| `save_arguments(rows, submit)` | автор/соавтор | не submitted/signed; при submit — по каждому оспоренному пункту ровно одна строка с `text_ru/text_kk/files` | `AppealArgument[]`, `arguments_submitted_at` | нет |
| `decide_arguments(approve, comment)` | `evga-approver` (руководитель подразделения; см. §7 — открытый вопрос) | `arguments_submitted_at` есть, не подписано; отказ требует comment | `arguments_signed_at/by` или сброс `submitted_at` + comment | нет |
| `create_document(objection-result)` | назначенный `appeal-expert` («Результаты оформляет назначенный сотрудник управления апелляции») | `admission != REFUSED` | `owner=expert`, `sources` = версия objections | `create_resultat_vozrazhenie` (S10→S11) |
| `submit(objection-result)` | владелец | `appeal_submission_block` (назначен исполнитель, `admission=ACCEPTED`, обоснования подписаны); reviewers — только `evga-appeal-commission-member`, signer — только `evga-appeal-commission-chair`; валидация: каждое оспоренное нарушение ровно один раз, суммы (`Подтверждено` → cancelled 0; `Отменено` → cancelled = amount; `Отменено частично` → 0 < cancelled < amount) | маршрут | `send_to_confirmation` (legacy: `appeal_expert → appeal_head`, комиссии нет) |
| `recall` | владелец-эксперт | `IN_REVIEW`, нет решений | маршрут `superseded` | нет |
| `deliver(objection-result)` | `appeal-expert`-владелец | `ACTIVE` | `DocumentDelivery`; после ознакомления ОА — доступен повторный КК2 (`revise_main_quality` со ссылкой на результат) | `send_to_audit_object` → `audit_object_acknowledged` → S12 `resubmit_to_qc_stage2` |

Третьи лица (`thirdParties.ts`, §3.8): все действия — `object`, дело открыто, отчёт ознакомлен (`report.delivery.acknowledged_at`); `record_no_third_parties(reason)`; `add_third_party({name, identification (12 цифр или пусто), violation_row_ids ⊂ реестр, notice_at (прошлая дата ≥ ознакомления), files})`; `record_third_party_event(notice, receipt|response|forward, date, text, files)` — строго по порядку, даты не раньше предыдущего и не в будущем (`assert_past_date`), файлы обязательны.

### 5.5 Автомат дела

Хранимое: `status ∈ {OPEN, CLOSED}`, `execution_state`, `closed_at`, `schedule_*`, кеш `quality_stage_passed`. Вычисляемое: `stage` (по `quality_stage_passed`), `is_registered`, `progress` (`execution_stages`/`next_execution_step`), `deadlines`, `can_edit` (автор/соавтор ∧ `OPEN`), фаза для отчётности (`compute_phase`: `preparation → ready_qc1 → qc1 → registration → control → awaiting_objections → reviewing_objections → qc2 → audit_materials_implementation → qc3 → closed` — коды `CaseProcessV1`/`case-workflow-update`, только для `LEGACY_STATUS_MAP` дела и дашборда; во фронт не отдаётся).

| Из | Событие (где) | В |
|---|---|---|
| — | `create_case` | `OPEN`, `execution_state=IN_PROGRESS`, `quality=[F,F,F]` («Создано дело») |
| `OPEN` | регистрация `additional`/`counter-additional` с `values.order.type` (`commit_version` п.9) | «Приостановление проверки» → `SUSPENDED`; «Возобновление проверки» → `IN_PROGRESS`; «Отмена проверки» → `CANCELLED` + `CLOSED` + `closed_at`; «Продление проверки» с `order.extendDate` → `schedule_end`; всегда — новое `CaseBasis(source_version)` и «Зарегистрировано дополнительное поручение: <type>» |
| `OPEN` | `completion` → `ACTIVE` (`commit_version` п.11) | `CLOSED` |
| `OPEN` (встречное) | `counter-notification` → `REGISTERED` | `CLOSED` |
| любое | активация `qualityN` / новая версия источника / `apply_amendment` (`[F,F,F]`) / `assign_quality_expert` подписанного quality2 (`[1]=False`) | пересчёт `quality_stage_passed` (`compute_quality`) |
| любое | `objections` → `ACTIVE` | `Appeal` создаётся/обновляется |
| `SUSPENDED` | `creation_block` разрешает только `additional`/`counter-additional` («Проверка приостановлена. Оформите дополнительное поручение о возобновлении»); prep/main-переходы блокируются («Проверка приостановлена») | |
| `CLOSED` | любая мутация | `DocumentTransitionError("Дело закрыто")` |
| `CLOSED` | `reopen_case` (`evga-admin`, стенд) | `OPEN` + `AuditEvent` — резерв, не в UI |

`quality_passed(case, stage)` — порт `qualityPassed`: stage 1 при наличии main-документов с `main`-отметками — `!main_quality_conclusion_block(case)` и все `quality_sources(1)` готовы; иначе — документ `quality{stage+1}` существует, версия `ACTIVE`, `values.conclusion.decision === "Без замечаний"`, `sources` непусты и покрывают все `quality_sources(stage)`, и каждая ссылка указывает на текущую версию источника в статусе `ACTIVE` (рабочие формы исключены из проверки актуальности). Действия дела (§6.1) — `create_case`, `update_case`, `set_group`, `assign_coauthor`, `save_calendar`, `create_counter_case`, `assign_quality_expert`, `apply_amendment`, апелляция/третьи лица, `close_case` (стенд).

### 5.6 Где применяются коды действий BPMN/n8n

* `ActionSpec.legacy_codes` и `LEGACY_ACTION_MAP` — точные коды BPMN `availableActions[].code` (`bpmn-processes.md` §6) и n8n `action` (`n8n-cases-documents.md` §3.4): `submit, approve, confirm, return, reject, activate, sign, send_to_kvga, kvga_confirm, kvga_return, kvga_reject, change_kvga_confirmer, send_to_reestr_confirmer, reestr_confirm, change_reestr_confirmer, send_to_work_group, sign_work_group, approve_work_group, send_to_audit_object, audit_object_acknowledged, oa_acknowledge, sign_without_objection, sign_with_objection, send_to_ersop, check_status, register, provide_info, refuse_info, review_info, accept_info, reject_info, resend_to_oa, mark_refused, sign_zkk, submit_confirm, change_approver, change_confirmer, change_head, create_zkk, send_to_ak, create_objection_doc, close_case, apply_amendment`; пишутся в `AuditEvent.metadata.legacy_codes` для отчётности и сверки со старой БД.
* Коды дела (`case-workflow-update`): `add_document` → `available_document_types`; `send_to_qc/send_to_qc_stage2/send_to_qc_stage3` → `request-quality` (флаг `quality_requested_at`); `assign_qc_expert*`, `change_qc_expert`, `change_qc_head` → `assign_quality_expert`; `create_qc_conclusion*` → `create_document(qualityN)`; `resubmit_to_qc_stage2` → `revise(reason="quality")`; `assign_qc_expert_appeal` → `assign_expert`; `create_resultat_vozrazhenie` → `create_document(objection-result)`; `send_to_qc_kvga/assign_qc_expert_kvga/create_qc_conclusion_kvga` → `DROPPED_LEGACY_ACTIONS` (маршрут КК КВГА не реализуется).
* Системные коды (`prev_approved`, `doc_approved`, `ersop_registered`, `ready_kvga_confirmed`, `zkk_confirmed`, `ready_send_confirmation`, `create_qc_conclusion_stage3`, `ready_send_to_qc*`, `ready_send_to_appeal`, `work_group_complete`, `default`, `status_change`) — заменены вычислением предпосылок (`gates.py`, `*_block`); `signed_automatically` — за флагом; `ersop_accepted/registered/rejected/revision/error` — результат `poll_registration` (`AuditEvent.source=ersop`); `overdue` — `process_deadlines` (`source=timer`).
* `EvgaDocumentType.legacy_code` — M-коды для ЕРСОП/отчётности/сверки; `EvgaDocumentType.legacy_id` — id `evga_document_types`; `DocumentSignature.kind` — `signature_type` legacy.
* Семейства T0–T9 (`bpmn-processes.md` §2.3) отображены на `Workflow` и под-автоматы: T0 → `DIRECT`, T1 → `ROUTE`, T4/T5 → `PREPARATION` (T5 отчёта → `MAIN`), T6 → `QUALITY`, T2 → `delivery.py`/`DocumentDelivery`, T3 → `evga_ersop`, T7 → `information_requests.py`, T8 → `owner_role=object` + кабинет, T9 → `evga_appeals` + `route_candidates`.
* Роли `allowed_roles` BPMN (§8) → роли фронта через таблицу §7.3 (`approver→reviewer`, `confirmer→approver`, `qc_expert→quality`, `qc_head→qc-head`, `kvga_confirmer→kvga`, `reestr_confirmer→reestr-confirmer`, `audit_object*/oa_*→object`).

### 5.7 Таймеры

Management command `apps/evga_documents/management/commands/process_deadlines.py` (`--loop N` для контейнера `scheduler`, иначе cron каждые 5–15 мин); идемпотентна; под `transaction.atomic` + `select_for_update(skip_locked=True)`:

1. **Требования сведений**: `InformationRequestRound` в состоянии `awaiting` с `deadline < now` и без `overdue_marked_at` → `overdue_marked_at=now`, `record_event(action_code="ir-overdue", source=TIMER, metadata={"legacy_code": "overdue"})`; для `counter-request` — `review_decision=REFUSED` (авто-отказ по BPMN `m45_vk_treb`), событие «Отказ по истечении срока»; уведомление автору. `request_state` и без этого считает `overdue` на чтение — команда нужна для журнала и уведомлений.
2. **Срок возражений**: `DocumentDelivery` отчёта с `objection_due_on < today` без `decision` и без активных `objections` → `Notification(DEADLINE)` автору/соавторам «Срок подачи возражений истёк» (однократно, дедуп по `meta.deadline_key`). Автоподпись `signed_automatically` (BPMN `P10D`) — только если `EVGA_AUTO_SIGN_REPORT_AFTER_DAYS` задан (по умолчанию `None` — не реализуется).
3. **Опрос ЕРСОП**: `ErsopRegistration(status in {SENT, PENDING}, last_checked_at < now - 10 мин)` → `poll_registration(source="ersop")` (для `stub` — имитация ответа).
4. **Нормативные сроки** (`audit_deadlines`, 15 правил) и сроки исполнения (`PrescriptionItem.due_date`): `Notification(DEADLINE)` за N дней и по факту просрочки (дедуп по `meta.deadline_key = rule+anchor`); статусы не меняются.
5. **Ознакомление ОА** (`DocumentDelivery.expires_at`, legacy `expires_days=5`) — уведомление автору «объект не ознакомился».

Никаких статусных переходов по таймеру, кроме п. 1 — всё остальное вычисляется на чтение. Celery/Redis не вводятся до реального ЕРСОП (команда написана так, что становится `beat`-задачей).

### 5.8 Оптимистичная блокировка

* Черновик: `DocumentVersion.row_version`; `PATCH …/versions/{n}/` требует `expected_row_version`; несовпадение → `StaleVersionError` → 409 `{"code": "stale_version", "detail": "Документ изменился. Обновите дело перед сохранением решения"}`.
* Решения: `expected_version` (номер версии) → «Открыта устаревшая версия документа. Обновите дело» (409); дополнительно `ApprovalWorkflowError(STALE_VERSION)` из `decide_route`.
* Каждое действие над документом делает `AuditCase.objects.select_for_update().get(pk=case_id)` в начале транзакции — это заменяет JSON-сравнения `mainCurrentBlock/preparationCurrentBlock/assertCurrent/saveDocument` фронта (сериализация действий по делу) и снимает гонки между документами одного дела; кросс-документные guard'ы выполняются **внутри** транзакции после блокировки — это и есть «commit повторно проверяет комплект» фронта (тест `bpmn-main-workflow`: «commit повторно проверяет комплект (аудитор и руководитель КК)»).
* `IssuedNumber`, `UniqueConstraint`'ы (`DocumentSignature`, `ApprovalParticipant`, `Acknowledgement`, `CaseCoauthor`, `QualityAssignment` active) — `IntegrityError → DocumentTransitionError` с текстами фронта («Ваша подпись уже сохранена», «Ознакомление уже зафиксировано», «Согласующие не должны повторяться», «Соавтор уже назначен»).
* Идемпотентность: `issue_number` (prof), `submit_registration` (повтор при `SENT` → 400), `poll_registration` (без изменений при том же `confirm_status_id`), `create_working_papers` (`get_or_create`), таймеры (по `*_marked_at`/дедуп уведомлений).

### 5.9 Транзакции и порядок коммита

`apply_action` (§5.3) — одна транзакция: блокировка дела → проверки `expected_*` → грубый фильтр `ActionSpec` → сервис (порт TS: блоки, назначения, переходы, связанные таблицы) → `row_version += 1` → `commit_version(version, by)` (побочные эффекты п. 7–13 `evga-workflows.md` §2.12: кросс-документные предусловия по актуальному делу (`main_quality_version_block`, `main_preparation_block`, актуальность `sources`, «Исходные документы изменились перед сохранением решения», «Комплект изменился перед сохранением подтверждения реестра»), `Appeal`, `apply_quality_conclusion`, эффекты регистрации `additional`, `compute_quality`, закрытие дела, `record_event`, `notify(recipients_for_version)`) → `record_event` самого действия. Проекции (`Violation`, `PrescriptionItem`, `Recommendation`, `ResponseMeasure`) пересобираются в `save_draft` и при `ACTIVE`. `save_draft` — та же транзакция без `commit_version` (только «Сохранены изменения»). Уведомления — записи в той же транзакции (нет внешних каналов), обмен с ЕРСОП — сначала `ErsopExchange(OUT)` в транзакции, затем HTTP-вызов адаптера вне `select_for_update` (в `stub` — синхронно).

---

## 6. API-контракт

Общие правила (prof): префикс `/api/evga/` (справочники — `/api/catalogs/`, уведомления — `/api/notifications/`, объекты — `/api/subjects/`, сотрудники — `/api/accounts/users/`); cookie-сессия `saq_session` (`SessionCookieAuthentication`); read — `GenericViewSet` + mixins с `filterset_class`, `search_fields`, `ordering_fields`, `ScopedQuerySetMixin`; действия — `APIView` с `required_domain/required_levels`, `get_permissions() → [IsAuthenticated(), HasDomainLevel()]`; ответ действия — полный read-сериализатор (`Document`, либо `CaseWorkspace`, если `returns_case`); списки — `{count, next, previous, results}` (`page`, `page_size ≤ 200`); `@extend_schema` на каждом методе (описание перехода, `Transition`-таблица в `description`). Уровни ниже: `R` = `READ_LEVELS` (`VIEW, EDIT, APPROVE, SIGN, DECIDE, CONFIRM`); домен по умолчанию `evga_cases`; `D:E` = `evga_cases: EDIT`, `Q:D` = `evga_quality: DECIDE`, `G:C` = `evga_registry: CONFIRM`, `A:*` = `evga_appeals`, `X:V` = `evga_execution: VIEW`, `C` = кабинет (`IsSubjectRepresentative`), `ADM` = `evga_admin: DECIDE`. Объектные права (владелец, участник маршрута, назначенный, представитель ОА) — в сервисах (§7.5). Файлы — `multipart/form-data`, скачивание через download-view (`FileResponse`), не presigned URL.

Порядок в view действия (базовый класс):

```python
class DocumentActionView(APIView):
    spec: ActionSpec                                   # класс-наследник задаёт только spec (и при необходимости переопределяет get_payload)
    @property
    def required_domain(self): return self.spec.domain
    @property
    def required_levels(self): return self.spec.levels
    def get_permissions(self): return [IsAuthenticated(), HasDomainLevel()]
    def post(self, request, pk):
        document = get_object_or_404(AuditDocument.objects.select_related("case__department"), pk=pk, is_deleted=False)
        assert_department_in_scope(request.user, document.case.department)           # national видит всё
        body = (self.spec.payload_serializer or EmptySerializer)(data=request.data); body.is_valid(raise_exception=True)
        try:
            result = apply_action(document, spec=self.spec, actor=request.user, payload=body.validated_data,
                                  expected_version=request.data.get("expected_version"), expected_row_version=request.data.get("expected_row_version"))
        except StaleVersionError as exc: raise ConflictError(str(exc))                 # 409
        except DocumentTransitionError as exc: raise serializers.ValidationError({"detail": str(exc), "code": getattr(exc, "code", "invalid")})  # 400
        return Response(CaseWorkspaceSerializer(...).data if result.returns_case else DocumentSerializer(result.document, context={"request": request}).data)

class SubmitDocumentView(DocumentActionView): spec = ACTIONS["submit"]
# urls.py: path("<uuid:pk>/submit/", SubmitDocumentView.as_view(), name="evga-document-submit"), …
```

### 6.1 Дела (`apps/evga_cases/api/urls.py`)

| Метод и путь | Тело → ответ | Права | Сервис / порт |
|---|---|---|---|
| `GET /api/evga/cases/` | фильтры §6.14 → `Paginated<CaseListItem>` (`id, number, subject{bin,name,name_kk,legal_form}, audit_type, audit_type_label, inspection_type, check_kind, electronic, dsp, author{id,full_name}, group[{id,full_name,is_leader}], created_at, status, status_label, execution_state, stage, quality_stage_passed[3], parent, can_edit`) | R; `ScopedQuerySetMixin(scope_department_field="department")`; `dsp=True` — только с доменом `dsp` | `CaseRegistryViewSet`; `caseSearch.matchesFilters`; legacy `Cases - List` |
| `POST /api/evga/cases/` | `{subject_bin, subject?{ru,kz,director,opf,abp,address,region,risk,score}, joint_subject_bin?, audit_type, inspection_type, inspection_kind?, check_kind, electronic, dsp, purpose_ru, purpose_kk, group:[{user_id, is_leader, is_invited_specialist?}], bases:[{kind, initiator, number, date, attachment_ids[]}]}` → 201 `CaseWorkspace` | D:E (роль `auditor`) | `create_case` (`CaseForm.save`, `validateCase`, `Create Case v4`) |
| `GET /api/evga/cases/{id}/` | → `Case` (детально: `bases[]`, `participants[]`, `coauthors[]`, `quality_assignments[]`, `subject`, `subject_snapshot`, `schedule_*`, `calendar`, `execution_state`, `third_parties_reviewed`) | R | |
| `PATCH /api/evga/cases/{id}/` | те же поля, что при создании (частично) → `CaseWorkspace` | D:E (автор/соавтор, `OPEN`) | `update_case` |
| `GET /api/evga/cases/{id}/workspace/` | → агрегат §6.2 | R (или C для своего объекта в кабинетной проекции) | `build_workspace` |
| `PUT /api/evga/cases/{id}/group/` | `{members:[{user_id, is_leader, is_invited_specialist?}]}` → `CaseWorkspace` | D:E | `set_group` (`WorkingGroup.onChange`) |
| `POST /api/evga/cases/{id}/coauthors/` · `DELETE …/coauthors/{user_id}/` | `{user_id}` → `CaseWorkspace` | D:D (`evga-approver`, руководитель органа) | `assign_coauthor` |
| `PUT /api/evga/cases/{id}/calendar/` | `{holidays[], working_dates[], confirmed_years[]}` → `CaseWorkspace` | D:E (автор) | `save_calendar` (`RegulatoryPanel`) |
| `GET /api/evga/cases/{id}/deadlines/?today=` | → `[{label, source, due, completed, estimated, rule}]` | R | `audit_deadlines` |
| `GET /api/evga/cases/{id}/progress/` | → `{stages:[ExecutionStage], next:{…}, completion_block}` | R | `execution_stages`, `next_execution_step` |
| `GET /api/evga/cases/{id}/history/?page=&document=&action_code=` | → `Paginated<HistoryEntry>` (`id, at, actor, action, comment, action_code, status_from, status_to, source, target{type,id,label}`) | R | `AuditEvent(case=X)` |
| `POST /api/evga/cases/{id}/attachments/` · `GET/DELETE …/attachments/{aid}/` | multipart `{file, kind=case_file}` → `AttachmentRef` / файл / 204 | D:E / R / D:E | `attach_file` |
| `GET /api/evga/cases/{id}/available-documents/` | → `[{kind, name, display_code, stage, blocked_reason, access_reason, can_create}]` | R | `available_document_types` (`creationBlock`, `creationAccessBlock`; legacy `Get Available Document Types`) |
| `POST /api/evga/cases/{id}/documents/` | `{kind}` → 201 `Document` (+`permissions`, `available_actions`) | D:E (доступ по `creation_access_block`); 400 `creation_blocked` | `create_document` |
| `POST /api/evga/cases/{id}/documents/bulk-working-papers/` | → `{created, workspace}` | D:E | `create_working_papers` («Создать доступные рабочие формы») |
| `GET /api/evga/cases/{id}/form-links/?key=` | → `{violationId[], riskId[], questionId[], resultId[], transfer[], claim[]}` | R | `form_links` |
| `POST /api/evga/cases/{id}/counter-cases/` | `{person_type, subject_bin? \| person_iin, person_name, person_birth_date, entrepreneur_name, question, group[]}` → 201 `CaseWorkspace` (дочернего дела) | D:E; `is_registered(parent)` | `create_counter_case` (`CounterChecks.create`; legacy `Sub Cases create counter_control`) |
| `GET /api/evga/cases/{id}/counter-cases/` | → `[CaseListItem]` | R | legacy `Sub Cases list` |
| `POST /api/evga/cases/{id}/quality-assignments/` | `{stage, expert_id, reason?}` → `CaseWorkspace` | Q:D (`evga-qc-head`) | `assign_quality_expert` |
| `POST /api/evga/cases/{id}/close/` · `POST …/reopen/` | `{reason}` → `CaseWorkspace` | ADM (стенд) | `close_case`, `reopen_case` |
| `DELETE /api/evga/cases/{id}/` | → 204 (soft delete) | ADM | legacy `Cases - Delete` |

### 6.2 Агрегат `workspace` (аналог `CaseWorkspaceView` prof)

```json
{ "case": Case, "subject": Subject, "parent_case": CaseListItem|null, "counter_cases": [CaseListItem],
  "documents": [ { "id", "kind", "legacy_code", "name", "stage", "number", "registration_number", "author", "created_at", "is_deleted",
                   "versions": [ {"version", "status", "status_label", "created_at", "frozen_at"} ],
                   "active_version": DocumentVersion,                 // полная версия §6.3
                   "permissions": {...}, "available_actions": [...] } ],
  "available_documents": [...], "quality_stage_passed": [bool,bool,bool], "quality_assignments": [...],
  "appeal": Appeal|null, "third_parties": [...], "amendments": [...], "deadlines": [...], "registrations": [...],
  "history": [HistoryEntry × 50], "notifications_unread": n,
  "permissions": {"can_edit", "can_create_counter", "can_assign_coauthor", "can_assign_quality": [bool,bool,bool]} }
```

`DocumentVersion` (read, форма фронта `types.ts`): `version, status, status_label, owner_role, owner{id,name}, values, print_context, row_version, group[{id,name,position,organization,leader}], attachments[AttachmentRef], signatures[{person, personId, at, role, kind, provider}], source_versions[{documentId, version, kind, number, is_current, contentSnapshotHash}], approval_routes[ApprovalRoute в форме shared/workflow], registration{status(label), number, date, comment}|null, delivery{sentAt, acknowledgedAt, response, attachments, decision(label), decidedAt, decidedBy, grounds, decisionAttachments, acknowledgements[]}|null, information_request{state, rounds[]}|null, preparation{agreedAt, qualityRequestedAt, kvga{confirmerId, status, at, by, comment}, groupSignatures[]}|null, main{agreedAt, groupRequestedAt, groupSignatures[], confirmation{confirmerId, status, comment, decidedAt, sourceVersions[]}, qualityRequestedAt, approvalRequestedAt}|null, main_quality{expertSignedAt, expertId, submittedAt}|null, quality_decision(label), quality_conclusion, history[HistoryEntry], created_at`. Именно из этого `evgaAdapter` собирает `AuditDocument/DocumentVersion` фронта; статус приходит кодом + `status_label` (адаптер кладёт `status_label` в `version.status`).

### 6.3 Документы (`apps/evga_documents/api/urls.py`; `path()` раньше `router.urls`)

| Метод и путь | Тело → ответ | Права | Сервис (`ActionSpec.code`) / порт |
|---|---|---|---|
| `GET /api/evga/documents/?case=&kind=&status=&stage=&owner=` | `Paginated<DocumentSummary>` | R (`scope_department_field="case__department"`) | `AuditDocumentViewSet` |
| `GET /api/evga/documents/{id}/?version=n` | `Document` + `active_version` (или запрошенная) + `permissions` + `available_actions` | R (C — только доставленные своему объекту) | `document_permissions`, `available_actions` (= legacy `get_available_actions`) |
| `GET /api/evga/documents/{id}/versions/{n}/` | `DocumentVersion` (read-only для `n < active`) | R | |
| `PATCH /api/evga/documents/{id}/versions/{n}/` | `{values, group?, expected_row_version}` → `Document` | D:E (владелец, `can_edit`); 409 | `save_draft` (`persist` + `saveDocument`; legacy `update`) |
| `DELETE /api/evga/documents/{id}/` | → 204 | D:E (владелец) | `delete_document` |
| `POST /api/evga/documents/{id}/validate/` | → `{errors[]}` | R | `validate` (`validateDocument`) |
| `POST /api/evga/documents/{id}/send-to-quality/` | `{expected_version}` | D:E | `send-to-quality` |
| `GET /api/evga/documents/{id}/route-candidates/` | → `{reviewers:[User], signers:[User], signer_required}` | R | `route_candidates` (`routeReviewer/routeApprover`, `ReviewRouteDialog`) |
| `POST /api/evga/documents/{id}/submit/` | `{stages:[{mode, reviewer_ids[]}] \| reviewer_ids[], mode, signer_id?, comment?, expected_version}` | D:E | `submit` |
| `POST /api/evga/documents/{id}/approve/` | `{expected_version, comment?, signature?}` | D: `APPROVE` (reviewer) / `SIGN` (signer); участие в маршруте — в сервисе | `approve` |
| `POST /api/evga/documents/{id}/return/` · `…/reject/` | `{comment, expected_version}` | D: `APPROVE`/`SIGN` | `return`, `reject` |
| `POST /api/evga/documents/{id}/recall/` | `{expected_version}` | A:E | `recall` |
| `POST /api/evga/documents/{id}/activate/` | `{expected_version, signature?}` | D:E/`SIGN` (по `owner_role`; `object` — C) | `activate` |
| `POST /api/evga/documents/{id}/revisions/` | `{reason: returned\|rejected\|quality-remarks\|quality\|main\|preparation\|response\|renew-quality}` → 201 `Document` | D:E (владелец) | `revise` (8 функций редакций) |
| `POST /api/evga/documents/{id}/group-signatures/request/` · `…/sign/` · `…/approve/` | `{expected_version}` / `{expected_version, signature?}` / `{expected_version}` | D:E / участник группы (`evga-invited-specialist` — VIEW + участие) / лидер | `group-request`, `group-sign`, `group-approve` |
| `POST /api/evga/documents/{id}/kvga-confirmation/request/` · `…/decide/` | `{confirmer_id, expected_version}` / `{decision: confirm\|return, comment?, expected_version, signature?}` | D:E / G:C (назначенный) | `kvga-send`, `kvga-decide` |
| `POST /api/evga/documents/{id}/registry-confirmation/request/` · `…/decide/` | `{confirmer_id, expected_version}` / `{decision, comment?, expected_version, signature?}` | D:E / G:C (назначенный) | `registry-send`, `registry-decide` |
| `POST /api/evga/documents/{id}/request-quality/` | `{expected_version}` (ветвление: instruction → prep, violations → main) | D:E | `request-quality` |
| `POST /api/evga/documents/{id}/request-approval/` | `{expected_version}` (prep: `send_preparation_for_approval`; main: `request_main_approval`) | D:E | `request-approval` |
| `POST /api/evga/documents/{id}/quality/sign/` · `…/quality/submit-to-head/` | `{expected_version, signature?}` / `{expected_version}` | Q:E/`SIGN` (назначенный эксперт) | `quality-sign`, `quality-submit-to-head` |
| `POST /api/evga/documents/{id}/ersop/send/` · `…/ersop/check-status/` | `{expected_version, signature?}` / — → `Document` | D:E | `ersop-send`, `ersop-check-status` |
| `POST /api/evga/documents/{id}/ersop/register/` | `{result: registered\|returned\|rejected, number?, date?, comment?}` → `CaseWorkspace` | ADM (стенд; на демо — также `auditor`) | `ersop-register` (`performRegistration accept/return`) |
| `POST /api/evga/documents/{id}/deliver/` | `{expected_version}` → `Document` | D:E (автор/соавтор; `appeal-expert` для objection-result) | `deliver` |
| `POST /api/evga/documents/{id}/deliver/refuse/` | multipart `{grounds, files[], expected_version}` | D:E (автор/соавтор) или C | `deliver-refuse` |
| `POST /api/evga/documents/{id}/deliver/manual-acknowledgement/` | multipart `{acknowledged_on, attachment}` | D:E | `manual-acknowledgement` (`AcknowledgeDocumentView` prof) |
| `POST /api/evga/documents/{id}/information-request/{send\|review\|accept\|reject\|resend\|mark-refused}/` | `{comment?, deadline?, expected_version}` | D:E (автор/соавтор) | `ir-*` |
| `POST /api/evga/documents/{id}/apply-amendment/` | `{expected_version}` → `CaseWorkspace` | D:E | `apply-amendment` |
| `POST /api/evga/documents/{id}/versions/{n}/attachments/` · `GET/DELETE …/{aid}/` | multipart `{file, kind=document_file\|form_row_file, slot?}` → `AttachmentRef` | D:E / R / D:E (только `DRAFT`, `assert_attachment_retention`) | `attach_version_file` |
| `GET /api/evga/documents/{id}/versions/{n}/print-context/` | → `{print_context, sources{kind→values}}` | R | `build_print_context` |
| `GET /api/evga/documents/{id}/versions/{n}/print/?lang=ru\|kk&format=html\|pdf` | HTML/PDF (итерация серверного PDF; до неё — 501) | R | |
| `GET /api/evga/document-types/` · `GET /api/evga/form-schemas/{kind}/?audit_type=` · `GET /api/evga/working-papers/{kind}/` | справочник видов с флагами и `legacy_code`; `FormSchema.schema`; шаблон РД | IsAuthenticated | сиды §9 |

### 6.4 Маршруты и задачи (`/api/evga/tasks/`, `apps/evga_workflow`)

| Метод и путь | Ответ / тело | Права |
|---|---|---|
| `GET /api/evga/tasks/?tab=incoming\|sent&case=&status=&search=&page=` | `{process_tasks:[{kind: kvga\|registry\|work_group\|object_decision\|quality_assign\|quality_conclusion\|appeal_assign, case, document, action, label, due}], tasks: Paginated<ApprovalTask>, routes: [ApprovalRoute]}` (форма `shared/workflow`) | IsAuthenticated (только свои) |
| `GET /api/evga/tasks/routes/{route_id}/` | `ApprovalRoute` с `participants[]`, `stages[]`, `events[]` | R |
| `POST /api/evga/tasks/routes/{route_id}/replace-participant/` | `{old_user_id, new_user_id}` → `ApprovalRoute` (BPMN `change_*`) | D:E (инициатор) |

### 6.5 Контроль качества (`/api/evga/quality/`)

| Метод и путь | Ответ | Права |
|---|---|---|
| `GET /api/evga/quality/?search=&stage=&expert=&page=` | реестр КК: `Paginated<{case, stages:[{stage, status_label, expert, outdated, block}]}>` (`QualityRegistry.tsx`; legacy `list-qc-cases`) | Q:V |
| `GET /api/evga/quality/{case_id}/` | `{case, stages:[{stage, document?, label, detail, sources[], block, assignment}]}` (`QualityAssignmentPanel`; legacy `get_qc_tasks`) | Q:V |

### 6.6 Апелляция и третьи лица (`/api/evga/appeals/`)

| Метод и путь | Тело → ответ | Права |
|---|---|---|
| `GET /api/evga/appeals/?expert=&search=&page=` · `GET /api/evga/appeals/{case_id}/` | реестр дел с возражениями / `Appeal` (+`filing_due_on`, `submission_block`) | A:V (legacy `Appeals - Cases list`) |
| `POST /api/evga/appeals/{case_id}/assign/` | `{expert_id}` → `CaseWorkspace` | A:D (`evga-appeal-head`) |
| `POST /api/evga/appeals/{case_id}/admission/` | multipart `{decision, reason, files[]}` → `CaseWorkspace` | A:`SIGN` (`evga-appeal-commission-chair`) |
| `POST /api/evga/appeals/{case_id}/admission/notify/` | multipart `{files[]}` → `CaseWorkspace` | A:E/D (`appeal-head` или назначенный эксперт) |
| `PUT /api/evga/appeals/{case_id}/arguments/` | `{rows:[{violation_row_id, text_ru, text_kk, attachment_ids[]}], submit}` → `CaseWorkspace` | D:E (автор/соавтор) |
| `POST /api/evga/appeals/{case_id}/arguments/decide/` | `{approve, comment?}` → `CaseWorkspace` | D:D (`evga-approver`) |
| `POST /api/evga/appeals/{case_id}/third-parties/` · `…/third-parties/none/` · `POST /api/evga/appeals/third-parties/{tp_id}/events/` | multipart `{name, identification, violation_row_ids[], notice_at, files[]}` / `{reason}` / `{event: receipt\|response\|forward, date, text, files[]}` | C (представитель ОА дела); чтение — R |

### 6.7 Исполнение (`/api/evga/execution/`)

`GET /api/evga/execution/items/?case=&status=&responsible=&document_kind=&deadline=&search=&page=` → `Paginated<ExecutionItem>` (контракт `shared/execution/execution.ts`: `id = execution:evga:<caseId>:<docId>:<docVersionId>:<itemId>`, `claimedStatus`, `confirmedStatus`, `originalDueDate`, `dueDate`, `extensions[]`, `evidence[]`, `responses[]`, `history[]`) — X:V; для кабинета — `GET /api/evga/cabinet/execution/items/?case=`.

### 6.8 Уведомления (`/api/notifications/`)

`GET /api/notifications/?unread=&case=&page=` → `Paginated<{id, at, case{id,number}, document_id, event_type, title, message, read}>`; `GET /api/notifications/unread-count/` → `{count}`; `POST /api/notifications/{id}/read/` → 204; `POST /api/notifications/read-all/` → `{marked}`. Только свои (`recipient=request.user`); чужое → 404. Realtime — polling `unread-count` (legacy WS-сервис портала не переносится).

### 6.9 Кабинет объекта аудита (`/api/evga/cabinet/`, permission `IsSubjectRepresentative`, `_assert_subject_owns`)

| Метод и путь | Тело | Порт |
|---|---|---|
| `GET /api/evga/cabinet/cases/` · `GET /api/evga/cabinet/cases/{id}/workspace/` | дела своего объекта (`subject == user.subject` или `parent.subject`), документы с `DocumentDelivery.sent_at` (или `response`/`objections` объекта); сериализация с `context={"cabinet": True}` скрывает внутренние вложения, маршруты и печатные контексты КК | legacy `OA get case` |
| `GET /api/evga/cabinet/documents/?case=` · `GET …/{id}/` · `GET …/{id}/versions/{n}/` | документы, направленные объекту | `CabinetDocumentViewSet` prof |
| `POST /api/evga/cabinet/documents/{id}/acknowledge/` | `{expected_version, signature?}` (канал `portal`) | `deliver-acknowledge` (`oa/acknowledge`, `acknowledge_document`) |
| `POST /api/evga/cabinet/documents/{id}/respond/` | multipart `{text, files[], expected_version}` | `deliver-respond` |
| `POST /api/evga/cabinet/documents/{id}/decision/` | multipart `{decision: sign\|object\|refuse, grounds?, files[], expected_version, signature?}` | `deliver-sign` / `deliver-object` / `deliver-refuse` (`sign_without_objection`/`sign_with_objection`) |
| `POST /api/evga/cabinet/documents/{id}/information-request/{acknowledge\|provide\|refuse}/` | multipart `{text?, files[], comment?, expected_version}` | `ir-acknowledge`/`ir-provide`/`ir-refuse` (`provide_info`/`refuse_info`) |
| `POST /api/evga/cabinet/cases/{id}/documents/` | `{kind: objections\|response}` → 201 `Document` | `create_document` (`create_objection_doc`) |
| `PATCH /api/evga/cabinet/documents/{id}/versions/{n}/` · `POST …/activate/` · `POST …/submit/` | как §6.3 для владельца `object` | `submit_objection` |
| `POST /api/evga/cabinet/cases/{id}/third-parties/` · `…/none/` · `POST /api/evga/cabinet/third-parties/{id}/events/` | §6.6 | `thirdParties.ts` |
| `GET /api/evga/cabinet/execution/items/?case=` | пункты предписания объекта | |
| `GET /api/evga/cabinet/attachments/{aid}/` | download-view с контекстом `{"cabinet": True}` | prof |

Кабинетные действия используют те же `DocumentActionView` (`spec.cabinet=True`) с permission `IsSubjectRepresentative` вместо `HasDomainLevel` и проверкой `_assert_subject_owns(user, document.case)`.

### 6.10 Справочники, объекты, сотрудники, служебное

| Метод и путь | Ответ | Права / порт |
|---|---|---|
| `GET /api/catalogs/{slug}/?search=&page=&page_size=` (`audit-types, inspection-types, inspection-kinds, basis-kinds, initiators, legal-forms, risk-levels, risk-object-types, violation-types, violation-types/tree, consequence-types, remediation-statuses, audit-indicators, sampling-methods, response-measures, audit-questions, controlling-bodies, regions, departments, positions, legal-basis-audit, query-check-npa, deadline-rules, calendar/{year}`) | `Paginated<{id, code, name_ru, name_kk, name, order, …}>`; дерево — `{code, name, group, children[]}` | IsAuthenticated; legacy `EVGA: * - Get` (20 воркфлоу), `offense-type/tree` |
| `GET /api/subjects/?search=&region=&risk_level=&year=&page=` | `Paginated<Subject + plan_entry>` (`ObjectsRegistry`) | R; legacy `Audit Objects - Get` |
| `GET /api/subjects/lookup/?bin=&year=` | `{found, subject, in_plan, plan_entry, source: local\|gbd}` (при отсутствии — адаптер ГБД и создание `Subject`) | R; legacy `Audit Object - Search by BIN`, `findJurByBin` |
| `GET /api/subjects/{bin}/previous-audits/?before=` | `[ReferenceIrpiRow]` (другие дела с тем же БИН) | R; legacy `listPreAudits` |
| `GET /api/subjects/persons/lookup/?iin=` | ГБД ФЛ (для встречной проверки ФЛ) | R; legacy `gbdfl` |
| `GET /api/accounts/users/?role=&department=&search=&page=` | `Paginated<{id, iin, full_name, position, department{…}, roles[]}>` (`PeoplePicker`, выбор КВГА/реестра/экспертов/комиссии) | IsAuthenticated; legacy `Employees - Get`, `qc/heads`, `qc/experts`, `appeals/heads`, `appeals/experts` |
| `GET /api/auth/me` · `POST /api/auth/local/login` · `…/logout` · `GET /api/auth/keycloak/login?redirect_to=` · `…/callback` · `POST …/logout` · `POST /api/auth/local/register` | prof без изменений; `Me` += `iin` | |
| `GET /api/evga/audit-events/?case=&document=&action_code=&actor=&date_from=&date_to=` | `Paginated<HistoryEntry>` | R; legacy `activity-log` |
| `GET /api/schema/`, `GET /api/docs/` | drf-spectacular | |

### 6.11 Файлы и печать

Загрузка — только через владельца цели (`POST …/attachments/` на деле, версии, апелляции, третьем лице); `AttachmentUploadSerializer` проверяет размер (≤ 50 МБ) и allow-list MIME (`pdf, doc(x), xls(x), jpg, png, zip, cms/sig`); ответ — `AttachmentRef {id, name, type, size, url}` (`url` = `reverse("evga-document-attachment-download")`, для кабинета — кабинетный маршрут). Скачивание — `FileResponse` со своими проверками прав. В `values` файл строки хранится как `AttachmentRef` c `slot="values:<section>:<row_id>"`. Печать: `print-context` отдаёт данные для клиентского pdfmake (`pdfExport.ts`); серверный `print/?format=pdf` — отдельная итерация (WeasyPrint по шаблонам `ReferencePrintForm.tsx`), нужен для ЕРСОП (`files[].fileBase64`) и ЭЦП.

### 6.12 `permissions` и `available_actions` для фронта

`permissions` (на документе): `{can_edit, can_submit, can_decide, decision_label ("Согласовать"|"Утвердить"|"Подписать"), can_send_quality, can_delete, can_activate, is_owner, view_default}` — порт `canEdit/canSubmit/canDecideDocument/creationAccessBlock`. `available_actions`: `[{code, label, name_kk, enabled, blocked_reason, requires_comment, requires_signature, payload_schema}]` — из реестра `ACTIONS` × `Transition` × `*_block` (§5.3). На переходный период фронт может игнорировать `available_actions` и использовать свои функции как подсказки; после этапа 3 страйглера кнопки рисуются по данным сервера.

### 6.13 Формат ошибок

Конверт prof (`core/exceptions.py`): `{"type": "about:blank", "title", "status", "detail", "code", …field errors}`. Коды `code` для ЭВГА (совпадают с `ApprovalWorkflowError` фронта, где есть):

```json
{"type":"about:blank","title":"Bad Request","status":400,"code":"invalid","detail":"Сначала утвердите: Программа аудита"}
{"type":"about:blank","title":"Bad Request","status":400,"code":"creation_blocked","detail":"Завершите контроль качества предыдущего этапа"}
{"type":"about:blank","title":"Bad Request","status":400,"code":"validation","detail":"Заполните обязательные поля перед согласованием","errors":["general.purpose: Заполните поле","questions: добавьте не менее 1 записей"]}
{"type":"about:blank","title":"Bad Request","status":400,"code":"comment_required","detail":"Укажите замечание."}
{"type":"about:blank","title":"Forbidden","status":403,"code":"forbidden","detail":"Заключение оформляет назначенный эксперт КК: Иванов И. И."}
{"type":"about:blank","title":"Conflict","status":409,"code":"stale_version","detail":"Открыта устаревшая версия документа. Обновите дело"}
```

Маппинг: `DocumentTransitionError` → 400 `invalid` (или `creation_blocked`/`validation`/`comment_required`/`invalid_route`/`invalid_status`/`already_decided` по `exc.code`), `StaleVersionError` → 409 `stale_version` (`core.exceptions.ConflictError`), `PermissionDenied` → 403 `forbidden`, чужой скоуп/объект — 404. Фронтовый `errorMessage()` prof-клиента читает `detail` без изменений.

### 6.14 Реестр дел: пагинация и фильтры (`CaseRegistryFilter`, порт `caseSearch.ts` + legacy `Cases - List`)

`search` (номер/наименование/БИН — `filter_search` через `Q`), `number`, `bin`, `name`, `created_on`, `audit_type`, `inspection_type`, `check_kind`, `format=traditional|electronic`, `legal_form`, `controlling_body`, `department`, `author`, `coauthor`, `status=OPEN|CLOSED`, `execution_state`, `stage`, `quality_passed=<stage>`, `has_document=<kind>`, `parent` (`null` по умолчанию — без встречных), `qc_expert`, `appeal_expert`, `ordering` (`-created_at`, `number`), `page`, `page_size` (≤ 200, по умолчанию 25). `rnn` — не реализуется (нет данных). Фильтры по вычисляемым полям (`stage`, `quality_passed`) — по колонке-кешу `quality_stage_passed`, не Python-проходом.

### 6.15 Покрытие мутаций фронта

Все функции `evga-workflows.md` §7 и таблица `evga-ui-actions.md` §3.2 отображены: дело — §6.1 (`создание/изменение дела`, `assignCoauthor`, календарь, `CounterChecks.create`, `assignQualityExpert`, `applyAmendment` → `…/documents/{id}/apply-amendment/`, апелляция ×5 и третьи лица ×3 — §6.6, уведомления — §6.8, read-модели `auditDeadlines/executionStages/executionItemsForCases/getApprovalTasks` — §6.1/§6.7/§6.4); документ — §6.3 (`createDocument`, `saveDocument` → `PATCH versions/{n}/`, `deleteDocument`, `sendDocumentToQuality`, `submitDocument`, `approveDocument`, `returnDocument`, `rejectDocument`, `activateDocument`, 8 функций редакций → `revisions/`, `recallDocument`, `sendInstructionToKvga/decideInstructionKvga` → `kvga-confirmation/*`, `requestPreparationQuality/requestMainQuality` → `request-quality/`, `sendPreparationForApproval/requestMainApproval` → `request-approval/`, `requestReportGroupSignatures/signReportGroup/signAssignmentGroup/approveAssignmentGroup` → `group-signatures/*`, `sendRegistryToConfirmer/decideRegistryConfirmation` → `registry-confirmation/*`, `signMainQuality/submitMainQualityToHead` → `quality/*`, `performRegistration` → `ersop/*`, `deliverDocument` → `deliver/*` + кабинет §6.9, `transitionInformationRequest` → `information-request/*` + кабинет, `validateDocument` → `validate/`; реестр нарушений (`saveRiskSelection`, `removeRegistryRisk`, `assignRegistryResult`, `repairRegistry`, `linkedViolation`, `finalizeRegistry`) — клиентские преобразования `values`, сервер валидирует `registryValidation` при `PATCH`/`submit`); `addQualityConclusion` (legacy-путь) — не переносится. Демо-функции (`createDemoCase`, `advanceDemoCase`, `prepareDemoMainStage`, `workflowSampleCases`, `preparedCases`…) — не API, а `seed_evga_demo_cases`.

---

## 7. Auth / RBAC

### 7.1 Аутентификация (prof без изменений)

`SessionCookieAuthentication` (cookie `saq_session`), `AuthSession`, `OidcAuthRequest`, `FederatedIdentity`, локальный вход `/api/auth/local/*` (стенд, представители ОА), Keycloak Authorization Code + PKCE `/api/auth/keycloak/*`, `MeSerializer` (`roles[{code,name,scope,department}]`, `is_subject_representative`, `subject`; += `iin`). Legacy-параметры Keycloak (realm `efc`, issuer `https://account-{dev,test}.…/realms/efc`, клиент `web-ui-service`, `preferred_username` = ИИН, `realm_access.roles[]`, `origin_user_id`) — конфигурация `KEYCLOAK_*` prof. Изменения `provision_user_from_claims` (6 строк): `User.iin` из `preferred_username` при `^\d{12}$` (сервисные аккаунты без ИИН допускаются — в отличие от legacy `invalid_iin`, отказ не нужен), `first_name/last_name`, `FederatedIdentity.origin_subject` ← `origin_user_id`; `is_active=False` → 403 `user_blocked` (prof уже проверяет в `SessionCookieAuthentication`).

### 7.2 Домены и уровни

`PermissionDomain` += `evga_cases, evga_quality, evga_registry, evga_appeals, evga_execution, evga_cabinet, evga_admin, dsp`; `PermissionLevel` += `CONFIRM`. Уровни неиерархичны (prof) — view перечисляет допустимые явно (например, `ApproveDocumentView.required_levels = {APPROVE, SIGN}` с последующей проверкой «участник маршрута» в сервисе). `READ_LEVELS = {VIEW, EDIT, APPROVE, SIGN, DECIDE, CONFIRM}` — константа в `accounts/querysets.py`.

### 7.3 Роли ЭВГА (`seed_evga_roles`) и маппинг

| `Role.code` (Django) | Название | scope | Фронт `Role` / особый `account.id` | Keycloak старой системы (`SUBSYSTEM_SCOPE_CONFIG.evga.assignableRoles`) | BPMN `allowed_roles` | Права (`domain: level`) |
|---|---|---|---|---|---|---|
| `evga-auditor` | Аудитор | territorial | `auditor` (`auditor`, `coauthor`, `people[]`) | `auditor` | `auditor` | `evga_cases: EDIT`, `evga_execution: EDIT`, `evga_quality: VIEW`, `evga_appeals: EDIT` (обоснования) |
| `evga-invited-specialist` | Приглашённый специалист | territorial | `invited-specialist` | `invited_specialist` | `invited_specialist` | `evga_cases: VIEW` (подпись РГ — по участию в `VersionParticipant`) |
| `evga-reviewer` | Согласующее лицо | territorial | `reviewer` (`reviewer-1/2`) | **`approver`** (инверсия терминов) | `approver` («Согласовать») | `evga_cases: APPROVE` |
| `evga-approver` | Утверждающее лицо / руководитель органа аудита | territorial | `approver` (`approver`: `assignCoauthor`, `decideArguments`) | **`confirmer`** (инверсия) | `confirmer` («Утвердить») | `evga_cases: SIGN, DECIDE`; `evga_appeals: DECIDE` |
| `evga-quality` | Эксперт КК | national | `quality` (`quality`, `quality-2`) | `qc_expert` | `qc_expert` | `evga_quality: EDIT, SIGN`; `evga_cases: VIEW` |
| `evga-qc-head` | Руководитель КК | national | `account.id === "quality-head"` (роль `approver`) | `qc_head` | `qc_head` | `evga_quality: DECIDE, SIGN`; `evga_cases: VIEW` |
| `evga-kvga-kk-head` | Руководитель КК КВГА | national | — | `kvga_kk_head_approver` (role_id 4/28 — **не подтверждено**) | `kvga_kk_head_approver` | как `evga-qc-head` (резерв маршрута `kk_kvga`) |
| `evga-kvga-kk-expert` | Эксперт КК КВГА | national | — | `kvga_kk_expert` (role_id 5/30 — **не подтверждено**) | `kvga_kk_expert` | как `evga-quality` (резерв) |
| `evga-kvga` | Подтверждающий КВГА | national | `kvga` | `kvga_confirmer` | `kvga_confirmer` | `evga_registry: CONFIRM`; `evga_cases: VIEW` |
| `evga-reestr-confirmer` | Подтверждающий реестра | national | `reestr-confirmer` | `report_manager` / `report_manager_kvga` — **не подтверждено** | `reestr_confirmer` | `evga_registry: CONFIRM`; `evga_cases: VIEW` |
| `evga-appeal-head` | Руководитель управления апелляции | national | `appeal-head` | `appeal_head` | `appeal_head` | `evga_appeals: DECIDE, EDIT`; `evga_cases: VIEW` |
| `evga-appeal-expert` | Сотрудник управления апелляции | national | `appeal-expert` (`appeal-expert(-2)`) | `appeal_expert` | `appeal_expert` | `evga_appeals: EDIT`; `evga_cases: VIEW` |
| `evga-appeal-commission-member` | Член апелляционной комиссии | national | `commission-1/2` (`reviewer`, `area: appeal`) | — (нет в старой) | — | `evga_appeals: APPROVE`; `evga_cases: VIEW` |
| `evga-appeal-commission-chair` | Председатель апелляционной комиссии | national | `commission-chair` (`approver`, `area: appeal`) | — (нет) | — | `evga_appeals: SIGN`; `evga_cases: VIEW` |
| `observer` (prof) | Наблюдатель | national | — | `reader_ga` | — | все `evga_*: VIEW` (добавить `RolePermission`) |
| `evga-admin` | Администратор ЭВГА | national | — | `admin_evga` (+`portal_admin`) | — | все домены `DECIDE` + `evga_admin: DECIDE` + `is_staff` |
| — (permission) | Доступ к ДСП | — | — | `dsp_access` | — | `dsp: VIEW` — назначается `RolePermission` нужным ролям или отдельной ролью `evga-dsp` |
| представитель ОА | — | — | `object` | `audit_object_signer` (+ `audit_object`, `oa_responsible`, `oa_confirmer` → одна сущность) | `audit_object*`, `oa_*` | `User.is_subject_representative=True` + `subject`; `IsSubjectRepresentative`; ролей нет |

Роли legacy без соответствия во фронте (`lawyer_head`, `lawyer`, `report_manager`, `report_manager_kvga`, `superuser_ga_rk`) сидируются как `RolePermission`-наборы только при подтверждении заказчиком (по умолчанию — в `KEYCLOAK_ROLE_MAP` как `observer`/не маппятся). Базовая роль входа `evga_user` (`surfk_user`) → пользователь считается пользователем ЭВГА, если у него есть хотя бы одно активное `RoleAssignment` с доменом `evga_*`.

Маппинг на фронтовую `Account` (`accountFromUser` в `evgaAdapter`): `role` = первая активная роль по приоритету `[auditor, reviewer, approver, quality, kvga, reestr-confirmer, invited-specialist, appeal-head, appeal-expert]`; `evga-qc-head` → `{role: "approver", id: "quality-head"}`; `evga-appeal-commission-chair` → `{role: "approver", area: "appeal"}`; `evga-appeal-commission-member` → `{role: "reviewer", area: "appeal"}`; представитель ОА → `{role: "object"}`; `label = position || roles[0].name` — так весь код фронта, проверяющий `account.role`/`account.id`/`area`, продолжает работать до переноса проверок на `permissions` с сервера.

### 7.4 Синхронизация ролей из Keycloak (порт `User Login Sync`)

`accounts/services/role_sync.py::sync_role_assignments_from_claims(user, claims)` — вызывается из `provision_user_from_claims` при `KEYCLOAK_SYNC_ROLES=True` и наличии ключа `realm_access.roles` (если ключа нет — роли не трогаются, как в legacy): `roles = set(realm_access.roles) ∩ KEYCLOAK_ROLE_MAP.keys()` → для активных `RoleAssignment` с ролями `evga-*`, отсутствующих в наборе, ставится `valid_to=now` (не удаляем — история; legacy делала `DELETE`); для новых создаётся `RoleAssignment(role, department)`, где `department` — из claim `departments[]` (`Department.code`), иначе `Department` центрального аппарата (legacy жёстко писала орган `'30101'`). `KEYCLOAK_ROLE_MAP` (JSON в env) по умолчанию = таблица §7.3 (`{"auditor": "evga-auditor", "approver": "evga-reviewer", "confirmer": "evga-approver", "qc_expert": "evga-quality", "qc_head": "evga-qc-head", "kvga_kk_head_approver": "evga-kvga-kk-head", "kvga_kk_expert": "evga-kvga-kk-expert", "kvga_confirmer": "evga-kvga", "appeal_head": "evga-appeal-head", "appeal_expert": "evga-appeal-expert", "invited_specialist": "evga-invited-specialist", "reader_ga": "observer", "admin_evga": "evga-admin"}`); `audit_object_signer` + атрибут БИН → `is_subject_representative=True`, `subject=Subject.objects.get(bin=claims["bin"])` (атрибут в claims — **не подтверждено**). При `KEYCLOAK_SYNC_ROLES=False` (по умолчанию) роли назначаются в admin (как prof). Keycloak Admin API legacy (`Keycloak Subsystem Access`, `Users V2`) не переносится.

### 7.5 Объектные права (сервисный слой)

Проверяются в сервисах (порт TS и фильтра `get_available_actions` n8n), не в `HasDomainLevel`:

| Проверка фронта / legacy `assignment_type` | Данные на сервере (`evga_documents/services/permissions.py`) |
|---|---|
| `canAuthorCase` (`audit.author === actor.name` или `coauthors ∋ id`) / `author` | `case.author_id == user.id or CaseCoauthor(case, user)` — `assert_author_or_coauthor` |
| `ownerId`/`ownerRole` версии / `author` | `DocumentVersion.owner/owner_role` — `assert_owner` (для `auditor` — автор/соавтор) |
| участник маршрута `pending` / `approver`, `confirmer` | `ApprovalParticipant(user, status=pending, is_signer)` — `assert_route_participant(route, user, phase)` |
| `preparation.kvga.confirmerId` / `kvga_confirmer`; `main.confirmation.confirmerId` / `reestr_confirmer` | `KvgaConfirmation.confirmer`, `RegistryConfirmation.confirmer` — `assert_assigned` |
| `qualityAssignments[stage].expertId` / `qc_expert`; `quality-head` / `qc_head` | `QualityAssignment.active(case, stage).expert`; роль `evga-qc-head` |
| `appeal.expertId` / `appeal_expert`; `appeal_head` | `Appeal.expert`; роль `evga-appeal-head` |
| участник РГ (`version.group[].id`) / `workgroup`; `leader` / `workgroup_lead` | `VersionParticipant.user` (или `CaseParticipant`) — `assert_group_member`; `is_leader` — `assert_leader`; роль не требуется (правило legacy) |
| представитель объекта (`role === "object"`) / `audit_object` | `user.is_subject_representative and user.subject_id in {case.subject_id, case.parent.subject_id}` — `_assert_subject_owns` |

Порядок в view: `get_object_or_404 → assert_department_in_scope(user, case.department) → RequestSerializer → apply_action (роль по ActionSpec, адресные проверки в сервисе) → except DocumentTransitionError → 400 / StaleVersionError → 409 / PermissionDenied → 403`.

### 7.6 Скоупинг

`AuditCase.department` — орган контроля (ЦА КВГА или `DVGA-<REGION>`), проставляется из `RoleAssignment.department` автора; national-роли видят всё, territorial — свои `department` (`scope_department_field = "department"` / `"case__department"` / `"version__document__case__department"`). `dsp=True` фильтруется из выборок, если у пользователя нет `RolePermission(domain=dsp, level=VIEW)` (миксин `DspFilterMixin` поверх `ScopedQuerySetMixin`). На первом стенде все роли могут быть назначены на ЦА (`30101`) — скоуп работает без изменений кода.

### 7.7 Кабинет объекта аудита

Пользователь-представитель регистрируется по БИН (`POST /api/auth/local/register` prof без изменений; `Subject` по `bin`) либо провижинится из Keycloak (§7.4). Все объектные действия — только через `/api/evga/cabinet/` (§6.9); сериализаторы с `context={"cabinet": True}` скрывают внутренние вложения и маршруты. Переключатель «Переключиться на объект» во фронте удаляется (этап 6); для демо `seed_evga_users` создаёт `object@demo` (`subject` = объект демо-дела).

---

## 8. Интеграции

Принцип prof: `services/stub_<system>.py` возвращает dict «как от внешней системы», обмен логируется в `*Exchange` (JSON), реальный клиент — `httpx` за тем же интерфейсом (таймаут 10 с, `raise_for_status`, свои `*UnavailableError`), выбирается настройкой; замена заглушки не меняет API. Каждый обмен — `record_event(action=EXCHANGE, exchange_id=…, source=ERSOP)` (ТЗ табл. 49 «идентификатор обмена»).

### 8.1 ЕРСОП / КПСиСУ (`evga_ersop`)

* **Контракт (из n8n `ERSOP - Build and Send from Document`, `SEND_REQ_TO_ERSOP`, `EVGA ERSOP Workflow`)**: `payload.build_started(version)` собирает JSON `{systemId: "10002", requestId (UUID v4), docId (document_id), requestDate, messageType: "M_TYPE_STARTED", message: {started: {number (≤21), organCode (ControllingBody.ersop_organ_code), typeCheckCode (inspection_kind), typeAuditCode (AuditType.ersop_code), checkDate, beginDate, endDate, periodBegin, periodEnd, oraganCodeKPSSU, shortFabula/shortFabulaKz, faces[] (VersionParticipant → iin, lastName, firstName, middleName, positionRU/KK/QAZ, organizationNameRU/KK/QAZ, phone, mobile), checkQuery {checkQueryCode: "0"+QueryCheckNpa.query_check_code, checkThemeCode: "0"+npa_code}, files[{fileName, mimeType: "application/pdf", fileLang: "kz", fileDesc, fileBase64}] (Attachment kind=print_form|signed_pdf), SubjectInfo {subjectId, bin}, ObjectInfo {objId}, userCreate, userSign}}}`; `userCreate/userSign` — из `AuditDocument.author`/`DocumentSignature(kind=ACTIVATION).signer`, **не** MOCK-константы legacy. Остальные типы — по XML-сборщикам `SEND_REQ_TO_ERSOP`: `Prolonged{CheckId, ProlongBegin, ProlongEnd, ReasonProlongCode, Note, FilesContent, UserSign}`, `PeriodChanged{PeriodBegin/End}`, `Resumed{ResumeDate}`, `Suspended{SuspendDate, ReasonSuspendCode}`, `Stoped{Reason*Code, Who*Code}`, `ExecutorsChanged{Faces/Experts}`, `Finished{FactBeginDate, FactEndDate, ResultCheckCode, Ammount*, SendCourtCode, LawOrgCode, SendDate, TalonQuery{CheckQueryCode, CheckThemeCode}}`. Даты — `YYYY-MM-DD+05:00` (`ZoneInfo("Asia/Almaty")`).
* **Цепочка (T3)**: `submit_registration` → `ErsopRegistration.status=SENT`, `ErsopExchange(OUT)`; `poll_registration` → адаптер `get_status(request_id)` → `confirmstatusid`: `'1'` → `REGISTERED`, `'2'` → `REJECTED`, `'3'` → `RETURNED`; ответ без решения → `PENDING`; `successful=0`/ошибка → `ERROR`; нет ответа → без изменений; `apply_registration_result` пишет `ErsopExchange(IN)`, `AuditEvent(source=ersop)` и запускает эффекты документа (§5.4.6). Callback ЕРСОП (если появится) — `POST /api/evga/ersop/callback/` с permission `IsErsopGateway` (shared secret) → `apply_registration_result`.
* **Адаптеры**: `ERSOP_ADAPTER = "stub"` — `stub_exchange.fake_send` (успех `'oK!'`), `fake_check_status` (первый опрос → `PENDING`, второй → `REGISTERED` с номером `issue_number("evga-ersop-registration")`; стенд-эндпоинт `ersop/register/` позволяет вернуть `'2'/'3'` — аналог кнопок «Учесть регистрацию/возврат» фронта); `"soap"` — `soap_exchange.py`: SOAP `SI_SUR2ERSOP_RequestSubjectAsync` (ns `http://minfin.kz/ERSOP`, basic auth, `ERSOP_SOAP_BASE_URL`), `getErsop?requestId=`; успех отправки — подстрока `'oK!'` в ответе (как legacy).
* **Готовность (`registration_block`)**: версия `ACTIVE`; есть печатная форма PDF (сервер) или загруженный `signed_pdf`; для account — участники УК, `LegalBasisAudit`, `QueryCheckNpa`, `ControllingBody.ersop_organ_code`, `AuditType.ersop_code`; для additional — `values.order.type` → `message_type` («Приостановление» → `M_TYPE_SUSPENDED`, «Возобновление» → `M_TYPE_RESUMED`, «Отмена» → `M_TYPE_STOPED`, «Продление» → `M_TYPE_PROLONGED`, «О внесении дополнений» → `M_TYPE_EXECUTORS_CHANGED`/`M_TYPE_PERIOD_CHANGED` по содержимому — **не подтверждено**); для notification — `M_TYPE_FINISHED`. Реальные `organCode`, `SubjectInfo.subjectId/ObjectInfo.objId`, транспорт (SOAP PI vs REST-шлюз) — **не подтверждено** (§12).

### 8.2 ГБД ЮЛ / ГБД ФЛ (`subjects/services/gbd.py`)

`lookup_legal_entity(bin) -> dict | None` в нормализованном формате legacy `Map to JSON`: `{bin, regStatus, regStatusCode, regDate, fullName{ru,kz}, shortName{ru,kz}, orgForm, orgFormCode, FormOfLaw, ownership, head{iin, fullName}, address{country, region, district, city, street, house}, activityKinds, founders[]}`; `lookup_person(iin)` — ФЛ для встречной проверки. Адаптеры: `StubGbdAdapter` (`data/evga/gbd_stub.json` — объекты `demoData.objectRegistry` + `catalogue`), `GatewayGbdAdapter` (REST `camel-gateway/api/out-integrations/gbdul` / `gbdfl`, заголовок `X-API-TOKEN` из env `GBD_API_TOKEN`), `ShepSoapAdapter` (SOAP `SI_GBD_JL_PIWS_OS getJurInfoByBin`, basic auth). Результат сохраняется в `Subject` (`gbd_payload`, `gbd_synced_at`, `legal_form_ref` по `gbd_code`); `SubjectLookupView` при отсутствии в базе вызывает адаптер и создаёт `Subject`. Выбор — `GBD_ADAPTER = "stub" | "gateway" | "shep"`.

### 8.3 Keycloak

prof `accounts/services/keycloak.py` как есть (discovery, PKCE, `decode_id_token`, `provision_user_from_claims` + §7.1/§7.4). Локальный вход остаётся для стенда и представителей ОА. Admin API legacy не переносится.

### 8.4 ЭЦП (НУЦ РК / NCALayer)

`DocumentSignature.provider ∈ {stub, ncalayer}`. В MVP `SIGNING_PROVIDER=stub`: действие «Утвердить/Подписать/Активировать» создаёт запись без криптографии (как prof «Утвердить вместо ЭЦП»), `document_hash = sha256(canonical_json({values, group}))`. `Transition.requires_signature` (из BPMN: `approve`, `confirm`, `sign*`, `kvga_confirm`, `reestr_confirm`, `send_to_ersop`, `audit_object_acknowledged`, `sign_with/without_objection`, `accept_info/reject_info`) проверяется только при `EVGA_SIGNATURE_REQUIRED=True`: фронт присылает `signature` (CMS из NCALayer, как параметр `signature` в n8n), `evga_documents/services/signing.py::verify_cms(cms, document_hash)` проверяет подпись (библиотека — на промышленном этапе), `cms_payload/cert_subject` сохраняются, CMS-файл — `Attachment(kind=signed_pdf)`. `userSign` для ЕРСОП берётся из подписи `ACTIVATION`/`ROUTE(signer)`. Требует серверного PDF (итерация 11).

### 8.5 Уведомления (`notifications`)

`notify()` пишет `Notification` получателям, вычисленным `recipients_for_version(version)` по правилам `saveDocument` п.13 (`evga-workflows.md` §2.12): quality*/objections → `ACTIVE`: автор/соавторы + все `quality` (+ `appeal-head` для objections); `IN_REVIEW`: pending-участники маршрута; `PENDING_REGISTRY`/`PENDING_KVGA`: назначенный confirmer; `GROUP_SIGNING`: участники группы без подписи; `IN_APPROVAL`: signer; `QUALITY_REVIEW`: все `quality`; появился `delivery`: все представители ОА; `objection-result` `ACTIVE`: автор/соавторы + quality + object + area appeal; иначе — `owner` либо все аккаунты `owner_role` (для auditor — автор/соавторы); плюс события дела (создание, назначения КК/АК, соавтор). Каналы: только in-app + polling `unread-count`; e-mail (`send_mail` при `NOTIFY_EMAIL=true`) и WebSocket — не в первом релизе (в legacy `send-notification-with-recipients` из бизнес-процессов не вызывался ни разу).

### 8.6 Прочее

* ИС ВАП (`vap`), АИС ОИП/суд (`claim-*`), ИС ПО (`forward-law`), ЕРАП — документы создаются/активируются без обмена; `AuditEvent(action=EXCHANGE)` не пишется; при необходимости — `ExternalExchange` по тому же паттерну (legacy `send_to_vap`, `send_to_court`, `send_to_law_enforcement`, `sendRequestErap`). Для внеплановой проверки legacy считала «зарегистрировано» также после отправки в ВАП (`ersop_registered` от `evga_doc_vap_notification`) — во фронте `registered(audit)` только по `account`; принимаем фронт (открытый вопрос §12).
* Печать/PDF: этап 1 — клиентский pdfmake по `print-context`; итерация 11 — Django-шаблоны по `ReferencePrintForm.tsx` → WeasyPrint → `Attachment(kind=print_form)` при активации (нужен для ЕРСОП и ЭЦП).
* Публичная верификация (`EVGA Document Verify (Public)`, legacy — по `docId`, баг `d.id = 2854`) — не в объёме; при необходимости `GET /api/evga/public/verify/<token>/` по непредсказуемому `DocumentVersion.public_token` после серверного PDF.

---

## 9. Справочники и seed-команды

Шаблон prof: константы данных → `update_or_create` под `@transaction.atomic` → `self.style.SUCCESS`; команды идемпотентны (тест двойного вызова), порядок — в `docker/entrypoint.sh`. Данные для сидов лежат в `backend/data/evga/*.json` и генерируются скриптом фронта `scripts/export-reference-data.mts` (по образцу `tmp_evga_domain/dump_forms.mts`), чтобы фронт и бэкенд не расходились.

| Порядок | Команда | Что заполняет | Ключ | Источник данных |
|---|---|---|---|---|
| 1 | `seed_catalogs` (prof) | `Region`(20), `Department`(21), `GovernmentBody`, `NormativeAct` | `code` | prof |
| 2 | `seed_evga_catalogs` | `AuditType`(2: соответствие `15`/фин. отчётность `16`, `is_financial`, `ersop_code`), `InspectionType`(`'1'` плановый, `'2'` внеплановый, + «Встречная проверка»), `InspectionKind`(24, 25), `BasisKind`(6), `Initiator`(14), `LegalForm`, `RiskLevel`(3), `RiskObjectType`(7, `legacy_aliases`), `ViolationType` (дерево), `ConsequenceType`(7), `RemediationStatus`(4), `AuditIndicator`(4), `SamplingMethod`(2), `ResponseMeasureKind`, `AuditQuestion`, `ControllingBody` (`30101` КВГА + 20 ДВГА, связь с `Department`), `Position`, `LegalBasisAudit`, `QueryCheckNpa`, `NormativeAct` (№ 392, 413, 113, 272, 873, 480, 162, Закон о госаудите, `V1700015209`, `V2200026715`) | `code` | `data/evga/references.json` из фронта (`basisOptions`, `initiatorOptions`, `auditTypeOptions`, `checkTypeOptions`, опции `riskType/consequence/indicator/violationType.suggestions/remediation`, `caseSearch.ts`); коды и полные списки — `surfk.*` после получения `pg_dump --data-only` (**не подтверждено**: дампа нет) |
| 3 | `seed_evga_calendar` | `ProductionCalendarDay`/`ProductionCalendarYear` на 2025–2027 (выходные, праздники РК, переносы) | `date` | `data/evga/calendar_<year>.json` (источник — открытый вопрос; до него — праздники из `npa-compliance.test.ts`) |
| 4 | `seed_evga_deadline_rules` | 15 `DeadlineRule` + сроки КК | `code` | `deadlines.ts::auditDeadlines`, `qualityDays` |
| 5 | `seed_evga_roles` | 17 ролей §7.3 + `RolePermission` (+ `observer` дополняется `evga_*: VIEW`) | `code`, `(role, domain)` | `types.ts::Role`, `demoData.accounts`, `SUBSYSTEM_SCOPE_CONFIG.evga.assignableRoles` |
| 6 | `seed_evga_number_sequences` | 6 последовательностей §4.15 (`--start` для переноса счётчика) | `(key, scope)` | `caseRules.ts`, `documentFactory.ts`, `n8n-cases-documents.md` §2.6 |
| 7 | `seed_evga_document_types` | 105 `EvgaDocumentType` (36 + 7 + 62) с флагами + legacy-only виды с `is_implemented=False` | `code` | `data/evga/document_types.json`: `documentMatrix.ts` (`kind, name, stage, code`), классификаторы `workflow.ts`/`documentStateMachine.ts`/`mainWorkflow.ts`/`preparationWorkflow.ts`/`amendments.ts`/`printContext.ts`, `workingPapers.json`; `legacy_code/legacy_id/legacy_root_table` — из `n8n-cases-documents.md` §5, `bpmn-processes.md` §3.10 |
| 8 | `seed_evga_form_schemas` | `FormSchema` для 43 видов × {любой, АФО} + ИРПИ (`irpiForm.ts`) + `projections` для 4 проецируемых коллекций | `(document_type, audit_type, version)` | `data/evga/forms.json` = дамп `formFor(kind, auditType)` |
| 9 | `seed_evga_working_papers` | 62 `WorkingPaperTemplate` | `document_type` | `data/evga/working_papers.json` (копия `data/workingPapers.json`) |
| 10 | `seed_evga_audit_objects` (стенд) | `Subject` (+поля) + `AnnualPlanEntry` (перечень на 2026, основание «По перечню объектов…») | `bin`, `(subject, year)` | `data/evga/objects.json` (`catalogue`, `objectRegistry`, `plannedDemoObjects`) + `gbd_stub.json` |
| 11 | `seed_evga_users` (стенд, `--if-empty`) | локальные пользователи по `accounts[]`/`people[]` фронта (`auditor`, `reviewer-1/2`, `approver`, `quality`, `quality-2`, `quality-head`, `kvga`, `reestr-confirmer`, `invited-specialist`, `coauthor`, `object` (`is_subject_representative`, `subject` = объект демо-дела), `appeal-head`, `appeal-expert(-2)`, `commission-1/2`, `commission-chair`, `ivanov/smirnov/suvorov/petrov/daulet`) + `admin`, пароль из `EVGA_DEMO_PASSWORD`, `RoleAssignment` на ЦА | `email` | `data/evga/people.json` (`demoData.accounts/people`, `config.ts::DEMO_USER`) |
| 12 | `seed_evga_demo_cases` (стенд, `--scenario`) | демо-дела «С нуля», «Полностью заполнено», «Основные документы», «Половина процесса», реестр нарушений, плановые — **через сервисы** (`create_case → create_document → apply_action …`), т.е. интеграционный тест | `number` | `data/evga/demo_scenarios.json` + порт `demoScenario.ts` (`workflowSampleCases`, `preparedCases`, `addRegistrySampleCases`, `prepareDemoMainStage`, `financialDemoValues.ts`) |
| — | `process_deadlines` | не seed; планировщик §5.7 | — | — |

Read-only API справочников — `catalogs/api/CatalogViewSet` (§6.10), чего в prof нет; фронт на этапе 1 страйглера заменяет константы `data/*` на `api.catalogs.*` (поля совпадают по построению).

---

## 10. План перевода фронта на API и деплой

Принято решение `prof-frontend-integration.md` §4.3: контракт `AuditCaseRepository.load()/save(cases)` **не адаптировать**, а заменить гранулярным шлюзом `EvgaGateway` с двумя реализациями (`apiGateway` через копию `api/client.ts` prof и временный `localGateway` поверх чистых функций + IndexedDB), переключаемыми `VITE_EVGA_DATA_MODE=local|api`. Формы (25 тыс. строк), печать, `types.ts` не трогаются.

### 10.1 Целевая архитектура и шлюз

`main.tsx → ErrorBoundary → App.tsx` (копия prof: `checkSession()` → `api.auth.maybeMe()`, тосты `saq:api-error`, `BrowserRouter basename="/evga"`, `AuthProvider{user, logout}`) → `EvgaModule` (`useEvgaRouting` на react-router; `gateway = useEvgaGateway()`; хуки `useCaseList/useCase/useDocument/useTasks/useNotifications`). Файлы: `src/api/client.ts` (копия prof + пространства `api.evga.*`, `api.catalogs.*`, `api.notifications.*`, `api.cabinet.*`), `src/api/types.ts` (DTO snake_case), `src/api/evgaAdapter.ts`, `src/services/evgaGateway.ts`, `src/auth/AuthContext.tsx` (копия prof), `src/auth/roles.ts::accountFromUser`.

```ts
export interface EvgaGateway {
  me(): Promise<User>;
  listCases(q: CaseQuery): Promise<Paginated<AuditCaseSummary>>;
  getCase(id: string): Promise<CaseWorkspace>;                                  // /cases/{id}/workspace/
  createCase(p: CaseInput): Promise<CaseWorkspace>; updateCase(id: string, p: Partial<CaseInput>): Promise<CaseWorkspace>;
  caseAction(id: string, action: CaseAction, payload?: object): Promise<CaseWorkspace>;   // group | coauthors | calendar | quality-assignments | counter-cases | appeal/* | third-parties/* | bulk-working-papers
  createDocument(caseId: string, kind: string): Promise<AuditDocument>;
  getDocument(id: string, version?: number): Promise<AuditDocument & { permissions; availableActions }>;
  saveDraft(id: string, version: number, values: Record<string, unknown>, group: Person[], expectedRowVersion: number): Promise<AuditDocument>;
  action(id: string, action: DocumentAction, expectedVersion: number, payload?: object): Promise<AuditDocument | { document; workspace }>;   // POST /documents/{id}/<action>/
  deleteDocument(id: string): Promise<void>;
  upload(target: AttachmentTarget, files: File[], slot?: string): Promise<AttachmentRef[]>; deleteAttachment(target: AttachmentTarget, id: string): Promise<void>;
  tasks(q), notifications(q), markRead(id), markAllRead(), executionItems(q), quality(q), qualityCase(id),
  catalogs(name, q), subjectsSearch(bin, year), previousAudits(bin), employees(q), routeCandidates(docId), formLinks(caseId), printContext(docId, version)
}
```

`evgaAdapter.ts`: `toAuditCase(workspace)`, `toAuditDocument(dto)` — почти identity, т.к. `DocumentVersion` отдаётся в форме фронта (§6.2); `DocStatus` ← `status_label`; `Upload` ← `AttachmentRef` (`data` → `url`, `href` в `<a download>`); `Account` ← `accountFromUser(user)` (§7.3); `expected_version` ← `versionNumber`, `expected_row_version` ← `row_version` последнего GET. Регламент: после любой мутации — рефетч агрегата (`getCase`), как `reloadCase` prof; в `apiGateway` нельзя импортировать чистые функции правил; клиентские `*Block`/`canEdit` — только подсказки (`disabled`), сервер — единственный судья; текст ошибок — `detail` из конверта в существующий `toast`.

### 10.2 Этапы страйглера (переключение по `VITE_EVGA_DATA_MODE`)

| Этап | Фронт | Требует от бэкенда (итерация §11) | Удаляется |
|---|---|---|---|
| 0. Каркас | `api/client.ts`, `api/types.ts`, `AuthContext`, `App.tsx`, `LoginPage` (email/пароль + кнопка Keycloak), `vite.config.ts` proxy `/api`, `.env.example`, `react-router` (маршруты те же без `#`), редирект `#/…` → `/evga/…`, `EvgaGateway` + `localGateway` | I0 (`/api/auth/*`, `seed_evga_users/roles`) | `useDemoSession`, `config.ts::DEMO_USER`, `vercel.json` |
| 1. Справочники и реестры | `ObjectsRegistry`, `ObjectLookup`, `PeoplePicker`, `BasisForm`, `AdvancedSearch` → `api.catalogs/subjects/accounts.users`; `CasesList` → серверная пагинация (`Pagination(count)` есть) | I1, I2 | `demoData.catalogue/objectRegistry/people/basisOptions/initiatorOptions` из рантайма |
| 2. Дела | `CaseForm.onSave → createCase/updateCase`; `WorkingGroup`, соавторы, календарь, вложения дела, история; номер от сервера | I2 | `nextCaseNumber`; `caseRules.validateCase` остаётся подсказкой |
| 3. Документы и действия | `getCase → workspace`; `createDocument/saveDraft/action/upload`; `DocumentWorkspace`, `DocumentActions`, `PreparationActions`, `MainActions`, `ReviewRouteDialog` (`routeCandidates`, `submit`), `InformationRequestPanel` — `onAction(() => gateway.action(...))`; `readOnly/eligible/canSubmit` ← `permissions`; `FileAttachments` получает проп `target` и `href={f.url}`; кнопки — по `availableActions` | I3, I4, I5, I6, I7 | `Upload.data` base64; `saveDocument`-stale-логика (→ 409); вызовы `documentStateMachine/workflow/*` из UI (файлы остаются для `localGateway`) |
| 4. Задания и уведомления | `ApprovalTasks`/`ApprovalInbox` ← `/tasks/`; `Notifications` ← `/api/notifications/`; счётчик ← `unread-count` | I4 | `approvalTasks.ts`, `caseApprovalRoutes`, `migrateLegacyApprovalRoutes`, пересчёт `quality[]` на клиенте |
| 5. Исполнение, КК, апелляции, третьи лица, требования, поручения, встречные, кабинет | `ExecutionRegistryPage` ← `/execution/items/`; `QualityRegistry`/`QualityAssignmentPanel` ← `/quality/`; `AppealPanel`, `ThirdPartiesPanel`, `AmendmentsPanel`, `CounterChecks` → API; кабинет ОА — маршруты `/evga/cabinet/*` и `api.cabinet.*` вместо «Переключиться на объект» | I8, I9, I10 | `qualityAssignment.ts`, `appeals.ts`, `thirdParties.ts`, `amendments.ts`, `executionItems.ts` из UI; `portalAccount`-переключение |
| 6. Зачистка | удалить `localGateway`, `indexedDbCaseRepository.ts`, `auditCaseRepository.ts`, `demoScenario.ts`, `financialDemoValues.ts`, `sampleScenario`/`isDemoCase`-фильтры, `useDemoSession.ts`, переключатель ролей в `AppShell` (`accounts[]`, `localStorage saq.evga.account.v1`), `readUploads`, `nextCaseNumber`, `documentSequence`; `data/demoData.ts` — только текстовые константы; `tests/*.test.ts` бизнес-правил помечаются «спецификация, перенесена в pytest» | I11 | IndexedDB, base64-вложения |

### 10.3 Деплой

`docker-compose.yml` prof + сервис `scheduler` (тот же образ, `command: ["python", "manage.py", "process_deadlines", "--loop", "300"]`, без портов); nginx (по `deploy/README.md`): `location /evga/ { alias /var/www/saq-evga/; try_files $uri $uri/ /evga/index.html; }`, `location /api/ { proxy_pass http://127.0.0.1:8000; }`, `location /admin/`, `location /static/`, `client_max_body_size 50m` (PDF/сканы). `deploy/.env.example` +`ERSOP_ADAPTER=stub`, `GBD_ADAPTER=stub`, `SIGNING_PROVIDER=stub`, `NOTIFY_EMAIL=false`, `EVGA_DEMO_PASSWORD`. Лаунчер prof: `saqModules.ts` → `url: "/evga/cases"` (тот же хост) или `https://<evga-host>/evga/cases`. Обновление: `git pull → docker compose up --build -d → npm ci && npm run build --prefix saq-evga-test → rsync dist/ /var/www/saq-evga/`.

---

## 11. План работ по итерациям и тестовая стратегия

Оценки — человеко-дни (чел.-дн.) одного бэкенд-разработчика, знакомого с prof; фронт — параллельно вторым разработчиком (этапы §10.2). Цель — Демо-1 на сервере после I4 (≈36 чел.-дн. бэкенда; при двух разработчиках ≈ 4 недели), далее этапы процесса по порядку.

| # | Итерация | Содержание | Бэкенд | Фронт |
|---|---|---|---|---|
| I0 | Каркас | копия каркаса prof в `saq-evga-backend`, `apps/evga_*` пустые с `apps.py`, `INSTALLED_APPS`/`urls`, аддитивные миграции `core/accounts` (`AuditEvent`, `Attachment.slot`, `User.iin`, домены/уровень `CONFIRM`), `record_event`, `ConflictError`, `assert_department_in_scope`, `seed_evga_roles`, `seed_evga_number_sequences`, compose (`scheduler`)/nginx `/evga/`, CI `pytest` + `ruff` (prof-тесты общих apps зелёные) | 4 | 3 (этап 0) |
| I1 | Объекты и справочники | `Subject` +поля, `AnnualPlanEntry`, `catalogs` ЭВГА + `BilingualCodeNamedModel` + `CatalogViewSet`, `seed_evga_catalogs/calendar/deadline_rules`, `seed_evga_audit_objects`, `SubjectLookupView` (stub ГБД), `GET /api/accounts/users/`; скрипт `export-reference-data.mts` | 6 | 3 (этап 1) |
| I2 | Дела | `AuditCase` и дочерние, `create_case/update_case/set_group/assign_coauthor/save_calendar`, `CaseRegistryViewSet` + `CaseRegistryFilter`, `workspace` (без документов), вложения дела, `history`, `seed_evga_users`; тесты `workflow.test.ts` Q01/Q03 | 7 | 4 (этап 2) |
| I3 | Типы, схемы, документы, версии, черновики | `EvgaDocumentType`, `FormSchema`, `WorkingPaperTemplate` + сиды; `AuditDocument/DocumentVersion/VersionParticipant/DocumentSourceVersion`; `factory.py` (`creation_block`, `initial_values`, номер), `drafts.py` (`row_version`, вложения версии/строк, `AttachmentRef`), `validation.py`, `available-documents`, `form-links`, `print-context`, `delete_document`; тесты `full-process` («все 105 видов имеют формы/секции»), `violation-registry` | 10 | — |
| I4 | Маршрут, общий автомат, реестр действий, инбокс, уведомления | `evga_workflow` (порт `approvalRoute.ts` — 27 сценариев), `workflows/route.py` + `direct.py`, `ACTIONS`/`apply_action`/`DocumentActionView`, `state_machine.py` (`send_to_quality/submit/approve/return/reject/recall/activate`), `revisions.py`, `permissions.py`, `commit_version` (базовые эффекты + `record_event` + `notify`), `/tasks/`, `notifications`; тесты `workflow.test.ts` (Q05–Q08), `evga-integration` (маршруты, редакции, legacy signerAction) | 9 | 6 (этапы 3–4) |
| **Демо-1** | «Дело → документы → согласование → инбокс → уведомления → история» на сервере | | **36** | **16** |
| I5 | Подготовительный этап и КК1 | `workflows/preparation.py`, `preparation.py` (блоки, КВГА, подписи РГ задания), `quality.py` (`quality_sources`, `apply_quality_conclusion`, `renew_quality`), `QualityAssignment` + `quality_assignment.py`, `compute_quality`, реестр КК `/quality/`; тесты `bpmn-preparation` (13), `bpmn-quality-assignment` (7), `npa-compliance` (сроки КК) | 8 | 2 |
| I6 | ЕРСОП (stub), доставка объекту, кабинет | `evga_ersop` (stub + `payload.build_started`), эффекты регистрации доп. поручения, `delivery.py`, `Acknowledgement`, `evga_cabinet` (§6.9), представитель ОА; тесты `full-process` (регистрация, возврат ЕРСОП, ознакомление) | 8 | 3 |
| **Демо-2** | подготовительный этап целиком + регистрация + поручение объекту (порт `bpmn-preparation.test.ts`) | | | |
| I7 | Основной этап и КК2 | `workflows/main.py` + `quality.py`, `main.py` (подписи РГ отчёта, реестр, `RegistryConfirmation`, КК2), `registry.py` (`Violation` проекция, `effective_violations`), `main_delivery_block`, решения ОА; тесты `bpmn-main-workflow` (16), `bpmn-main-assignment` (4), `bpmn-main-validation` (4) | 10 | 3 |
| I8 | Требования сведений, сроки, таймеры | `information_requests.py`, `deadlines.py` (`DeadlineRule`, календарь, `qualityDays`), `progress.py`, `process_deadlines` + сервис `scheduler`; тесты `bpmn-information-requests` (10), `npa-compliance` (календарь), `execution-progress` (3) | 6 | 2 |
| **Демо-3** | основной этап + возражения + требования (порт `bpmn-main-workflow.test.ts`) | | | |
| I9 | Заключительный этап и исполнение | заключение/предписание/талон/ответ/справка, `evga_execution` (проекции, `execution_items`, `responses.py`), `completion_block`, закрытие дела; тесты `evga-integration` (реестр исполнения, продления, `completion`), `shared-execution` (16), `npa-compliance` (предписание, завершение) | 8 | 3 |
| I10 | Возражения, апелляция, третьи лица, доп. поручения, встречные проверки | `evga_appeals`, `recall/reassign`, `amendments.py`, `create_counter_case` + `counter-*`; тесты `appeals-amendments` (8), `full-process` (встречная), `npa-compliance` (возражения, продление) | 10 | 3 |
| **Демо-4** | сквозной процесс до закрытия дела (порт `full-process.test.ts`) | | | |
| I11 | Печать/PDF, промышленные адаптеры, зачистка | `print-context` для всех видов, серверный PDF (WeasyPrint) как `Attachment(print_form)`, `soap_exchange`, `GatewayGbdAdapter`, `KEYCLOAK_SYNC_ROLES`, `seed_evga_demo_cases`, `docs/` бэкенда (`document-matrix.md`, `status-matrix.md`, `api-actions.md`, `project-decisions.md`, `integrations.md`), лимиты файлов, admin | 8 | 4 (этап 6) |
| | **Итого** | | **≈94** | **≈36** |

Порядок приложений: `core/accounts/catalogs/subjects` (аддитивно) → `notifications` → `evga_cases` → `evga_documents` → `evga_workflow` → `evga_ersop` + `evga_cabinet` → `evga_execution` → `evga_appeals`. Миграция данных из `surfk.*` (по `legacy_id/legacy_root_table`) — отдельная оценка после получения дампа.

### 11.1 Тестовая стратегия

* pytest-django, как в prof: `apps/evga_*/tests/test_*.py`, `pytestmark = pytest.mark.django_db`, хелперы-функции без фабрик (`_user_with_role(code, department=None)`, `_case(**overrides)`, `_document(case, kind)`), `APIClient().force_authenticate(user)`; общий модуль `apps/evga_cases/tests/scenarios.py` — фикстуры «дело на этапе N» через сервисы (порт `demoScenario.ts`).
* **Сценарии фронта → pytest 1:1** (названия тестов сохраняются как имена функций/докстринги; тексты ошибок — `pytest.raises(DocumentTransitionError, match=...)` с теми же строками):

| Файл фронта (сценариев) | pytest-модуль | Уровень |
|---|---|---|
| `workflow.test.ts` (7), `full-process.test.ts` (10) | `evga_documents/tests/test_workflow_basics.py`, `evga_cases/tests/test_full_process.py` (сквозной через `apply_action`) | сервисы + API |
| `bpmn-preparation.test.ts` (13) | `evga_documents/tests/test_preparation.py` | сервисы |
| `bpmn-main-workflow.test.ts` (16), `bpmn-main-assignment.test.ts` (4), `bpmn-main-validation.test.ts` (4) | `evga_documents/tests/test_main_stage.py`, `test_main_validation.py` | сервисы |
| `bpmn-quality-assignment.test.ts` (7) | `evga_cases/tests/test_quality_assignment.py` | сервисы |
| `bpmn-information-requests.test.ts` (10) | `evga_documents/tests/test_information_requests.py` (параметр `now`) | сервисы |
| `shared-approval-workflow.test.ts` (27) | `evga_workflow/tests/test_route_contract.py` (коды `ApprovalWorkflowError`) | сервисы |
| `evga-integration.test.ts` (18) | `evga_execution/tests/test_execution.py`, `evga_workflow/tests/test_routes.py`, `evga_appeals/tests/test_reassign.py` | сервисы |
| `shared-execution.test.ts` (16), `execution-progress.test.ts` (3) | `evga_execution/tests/test_execution_deadlines.py`, `evga_cases/tests/test_progress.py` | сервисы |
| `appeals-amendments.test.ts` (8) | `evga_appeals/tests/test_appeals.py`, `evga_cases/tests/test_amendments.py`, `evga_documents/tests/test_calculations.py` | сервисы |
| `npa-compliance.test.ts` (16) | `evga_documents/tests/test_npa_rules.py`, `evga_cases/tests/test_deadlines.py` | сервисы |
| `violation-registry.test.ts` (11) | `evga_documents/tests/test_registry_validation.py` | сервисы |
| `quality-conclusion.test.ts` (4), `reference-data.test.ts` (3) | `evga_documents/tests/test_quality_print.py`, `test_print_context.py` | сервисы |
| `planned-demo.test.ts`, `demo-readiness.test.ts` | `evga_cases/tests/test_seed_demo.py` (`call_command("seed_evga_demo_cases")` дважды — идемпотентность) | команды |
| — | `evga_documents/tests/test_actions_api.py`: для каждого `ActionSpec` — 401 без cookie, 403 чужая роль/участник, 404 чужой department, 400 недопустимый статус с русским `detail`, 409 `stale_version`; `test_engine_invariants.py`: каждый `Transition` ↔ `ActionSpec` ↔ URL; каталог кодов BPMN/n8n ↔ `LEGACY_ACTION_MAP`/`DROPPED_LEGACY_ACTIONS`; каталог статусов ↔ `LEGACY_STATUS_MAP`/`DROPPED_LEGACY_STATUSES` | API / движок |
| — | `accounts/tests` и `core/tests` prof как есть; `test_rbac_scoping.py`-подобные тесты на `evga_*` домены и `dsp` | RBAC |

* Конкурентность (как `core/tests/test_numbering.py`): `django_db(transaction=True)` + `threading` для `issue_number` и для двух одновременных `approve` одной версии (ожидание: один 200, один 409); номера дел/документов без пропусков.
* Интеграции: stub-адаптеры — юнит; SOAP/REST — `httpx.MockTransport` с XML/JSON-фикстурами из `SEND_REQ_TO_ERSOP`/`Map to JSON`.
* Seed: идемпотентность двойного вызова каждой `seed_evga_*`; `seed_evga_demo_cases` — фактически e2e-тест сервисного слоя, запускается в CI как smoke.
* Фронт: контрактный тест `tests/evga-adapter.test.ts` на JSON-снимках `workspace` из pytest (`json.dump` фикстур в `saq-evga-test/tests/fixtures/`); `tests/navigation.test.ts` остаётся.
* Производительность агрегата: `CaptureQueriesContext` для `workspace` (как prof `test_list_does_not_prefetch…`), `select_related/prefetch_related` под сериализатор.

---

## 12. Риски и открытые вопросы (с решениями по умолчанию)

| # | Риск / вопрос | Кому | Решение по умолчанию |
|---|---|---|---|
| 1 | Нет дампа `surfk.*` (тела функций `check_*`, `send_case_to_qc`, `get_next_*_sequence`; содержимое `evga_document_types` с `zeebe_process_id`, `evga_document_mappings`, справочников, `case_statuses`) | прежняя команда | правила — из фронта и BPMN; сиды — из фронта; запросить `pg_dump --schema-only surfk` и `--data-only` справочников; при получении — сверить `legacy_code/legacy_id` и дополнить `seed_evga_catalogs` |
| 2 | Формат номеров: `30101-YY-NNNNN` (фронт) совпадает с legacy `CONCAT(code,'-',YY,'-',LPAD(seq,5,'0'))`; документы — legacy `standard/with_org` vs фронт `{case}/NN`; встречное дело `{parent}/ВП-n` vs legacy `ВП-{org}-{yy}-{seq:06d}/{tail}`; стартовое значение счётчика | заказчик | оба номера документа (`number` всегда, `registration_number` — для типов с `reg_number_format`); встречное дело — паттерн фронта (legacy доступен сидом); `--start` для переноса счётчика |
| 3 | `TIME_ZONE`: prof `UTC`, ЭВГА/ЕРСОП `Asia/Almaty`, сроки в рабочих днях | команда | глобальную настройку не менять (аддитивность); в `deadlines.py` и ЕРСОП-адаптере явно `ZoneInfo("Asia/Almaty")`; при слиянии в монорепо обсудить переход SAQ |
| 4 | ЭЦП обязательна по ПЗ при согласовании/утверждении; legacy хранила подпись без проверки | заказчик, ИБ | `SIGNING_PROVIDER=stub`, `EVGA_SIGNATURE_REQUIRED=false`; модель и интерфейс `verify_cms` готовы |
| 5 | Серверный PDF нужен для ЕРСОП (`files[].fileBase64`) и ЭЦП | команда | клиентский pdfmake до I11; затем WeasyPrint по шаблонам `ReferencePrintForm.tsx` |
| 6 | Keycloak-роли: `reestr-confirmer` ↔ `report_manager`/`report_manager_kvga`; `kvga_kk_*` (role_id 4/28, 5/30); роли комиссии по апелляции и «руководителя органа» (`assignCoauthor`, `decideArguments`) отсутствуют в legacy; атрибут БИН у `audit_object_signer`; обязателен ли `evga_user` для входа | заказчик/ИБ | `KEYCLOAK_SYNC_ROLES=false`, роли из `RoleAssignment` (admin); руководитель органа = `evga-approver` с `DECIDE` (при необходимости выделить `evga-department-head`); комиссия — роли без Keycloak-маппинга |
| 7 | Последовательное vs параллельное/многоэтапное согласование (Q06 «пока только последовательное») | заказчик | модель поддерживает `parallel`/`stages`; UI и `route_candidates` по умолчанию `sequential` |
| 8 | Срок возражений: 10 календарных (BPMN `P10D`) vs 10 рабочих дней (фронт) | заказчик | рабочие дни (`DeadlineRule.calendar=business`), правило — одна строка сида |
| 9 | Автосоздание документов при создании дела (n8n `Create Case v4`: 5 документов; BPMN `m18_m19_auto_create`, `audit_conclusion` → `M25-PRED`) vs ручное (Q08) | заказчик | ручное; `EVGA_AUTOCREATE_PREPARATION_DOCS=false`; `create_working_papers` — единственное массовое создание |
| 10 | Автоподпись отчёта по таймеру (`signed_automatically`) и автозакрытие дела при `kvga_return` (legacy) | заказчик | не реализуются (`EVGA_AUTO_SIGN_REPORT_AFTER_DAYS=None`; `KvgaConfirmation.RETURNED → RETURNED`); только уведомление |
| 11 | Маршрут «КК КВГА» (`qc_route = "KK KVGA"` при основаниях `13/14` внепланового) — правила не переданы | заказчик, прежняя команда | не реализуется; `BasisKind.qc_route_kvga=False`, `QualityAssignment.route=kk`; роли `evga-kvga-kk-*` сидируются как эквивалент `qc-head/quality` |
| 12 | Кабинет объекта: отдельный тип пользователя vs роль `object` в той же SPA (Q15) | заказчик | отдельный пользователь `is_subject_representative` (как prof/ТЗ 2.12); демо — seed-учётка |
| 13 | Комиссия по апелляциям, отзыв/переназначение результата — только во фронте; legacy: `appeal_expert → appeal_head` | заказчик | реализовать по фронту; зафиксировать в `project-decisions.md` как временное |
| 14 | `report` становится `ACTIVE` при отправке объекту; закрытие дела по `counter-notification`/«Отмена проверки»; `response` создаёт и ОА, и аудитор (Q17); критерии завершения (Q18) | заказчик | как во фронте; `status-matrix.md` |
| 15 | ЕРСОП: реальные `organCode`, `userSign`, `SubjectInfo.subjectId/ObjectInfo.objId`, транспорт (SOAP PI vs REST-шлюз), callback; маппинг `order.type → M_TYPE_*` | КПСиСУ, прежняя команда | stub; поля из `ControllingBody.ersop_organ_code`, подписей; маппинг типов — по смыслу до подтверждения |
| 16 | ГБД ЮЛ/ФЛ: транспорт (`SI_GBD_JL_PIWS_OS` vs `camel-gateway`), учётки/токен (в legacy зашит) | инфраструктура | `GBD_ADAPTER=stub`; оба адаптера за интерфейсом |
| 17 | Производственный календарь РК — источник | заказчик | `seed_evga_calendar` из JSON; `ProductionCalendarYear.is_confirmed` админом; `Deadline.estimated=true` для неподтверждённых годов |
| 18 | Ограничения файлов (размер/MIME/антивирус) — в prof нет | ИБ | 50 МБ, allow-list `pdf, doc(x), xls(x), jpg, png, zip, cms/sig`; nginx `50m`; антивирус — вопрос ИБ |
| 19 | Административное производство (M38–M57), акт осмотра `M55`, приказы (`evga_doc_prikaz`), «Дело КК» как документ, `return_to_draft` программы (`evga_doc_2_pa`) — есть в legacy, нет во фронте | заказчик | вне объёма; типы сидируются `is_implemented=False`; `CaseKind`-расширение зарезервировано |
| 20 | Двойная логика: клиентские правила расходятся с сервером | команда | сервер — единственный судья; клиентские функции — только `disabled`-подсказки; контрактный тест адаптера; тесты правил — в pytest |
| 21 | Производительность агрегата `workspace` (43 вида × версии × маршруты × проекции) и `load` дела на каждое действие | команда | `select_related/prefetch_related`, `history` — 50 последних, `CaptureQueriesContext`-тесты; при росте — кеш проекций; для реестров — серверная пагинация с первого дня |
| 22 | Существующие данные в IndexedDB пользователей стенда; миграция данных из `surfk.*` (версии как «снимок при возврате» vs полноценные редакции) | команда | IndexedDB не мигрируется; миграция `surfk` — отдельная задача после дампа (`legacy_id`, `legacy_root_table`, `revision_reason` предусмотрены) |
| 23 | Повторное открытие закрытого дела, приостановление рассмотрения возражений, судебное обжалование, e-mail/WebSocket-уведомления, публичная верификация документа | заказчик | не реализуются; `reopen_case` — только `evga-admin`; уведомления in-app + polling; верификация — по токену после серверного PDF |
| 24 | Смешанные языки сообщений и дубли статусов устранения («Частично устранено» / «Устранено частично») во фронте | команда | русский язык всех бизнес-ошибок; единый справочник `RemediationStatus`; валидатор принимает оба до чистки форм |

---

## 13. Журнал решений

| Спорный пункт | A (prof-first) | B (legacy-first) | C (simplest) | Принято | Почему |
|---|---|---|---|---|---|
| Размещение бэкенда | B1 монорепо, запасной — B2 форк | монорепо `apps/evga/*` | отдельный проект-копия каркаса | **B2: отдельный `saq-evga-backend`** с правилом аддитивности; B1 — опция | ранний независимый стенд; слияние = перенос папок `apps/evga_*` (A §2.1, C §2.1) |
| Фронт | отдельный SPA `/evga/` (F1), F2 позже | единый SPA после этапа 6 | отдельный SPA на своём хосте | **отдельный SPA под `/evga/` same-origin**, Vercel убран | cookie `SameSite=Lax`; минимум правок (A §2.2) |
| Состав приложений | 8 `evga_*` + `notifications` | 13 `apps/evga/<name>` (`objects`, `quality`, `requests`, `integrations`, `reports`…) | 12 без префикса (`objects`, `audits`, `documents`…) | **8 `evga_*` + `notifications`** | префикс защищает от коллизий при слиянии; меньше приложений — меньше шаблонного кода (A §3.1) |
| Объект аудита | `subjects.Subject` + поля | новая `evga.objects.AuditObject` | новая `objects.AuditObject` | **`subjects.Subject` расширен аддитивно** (+ опц. proxy `AuditObject`) | prof-кабинет уже завязан на `User.subject`; валидаторы БИН/ИИН как есть (A §4.5) |
| Модель документа | шапка + версия + типизированные под-состояния + 4 проекции | шапка (legacy-колонки, `approver/confirmer` FK, `DocumentApproval`) + версия + `RowProjection` ×11 | шапка + версия с JSONB-под-состояниями | **A**: типизированные под-состояния с FK, проекции только `Violation/PrescriptionItem/Recommendation/ResponseMeasure` (+ опц. `AuditQuestionRow/RiskObjectRow`) | инбокс/уведомления/ЕРСОП требуют FK и уникальностей; 11 проекций B — избыточно без отчётности; JSONB-под-состояния C — техдолг для SQL-выборок |
| Статусы документа | 11 UPPER_CASE + русские label | legacy latin-коды (`draft`, `pending_approval`…) + label фронта | 11 UPPER_CASE + `STATUS_BY_LABEL` | **11 `TextChoices` UPPER_CASE** + `LEGACY_STATUS_MAP` | стиль prof; legacy-коды — для отчётности/ЕРСОП (B §4.14 как словарь) |
| Форма API действий | `APIView` на действие с явными URL | один `POST …/actions/{code}/` + типизированные view | один `POST …/actions/` с реестром `ACTIONS` | **`APIView` на действие + базовый `DocumentActionView` + реестр `ActionSpec`** | Swagger/стиль prof + единый `expected_version`/журнал/`available_actions` (C §5.3) |
| Движок переходов | диспетчер по `workflow` внутри сервисов | таблица `StatusTransition` в БД + сид + реестр guard/effect | реестр `ACTIONS`, блоки вычисляются | **константы Python по семействам в формате полей `evga_status_transitions`**, не в БД | guard'ы ссылаются на код, покрываются pytest; сид таблицы — лишний слой (B — формат, C — вычисление) |
| Гейты (`prev_approved`, `check-docs-status`) | вычисление (`*_block`) | вычисление (`gates.documents_in_status`) | вычисление | **вычисление** | событийная модель BPMN давала «потерянные сообщения» (`bpmn-processes.md` §9.4) |
| Сервисы | порт TS 1:1 | порт legacy-действий (`lifecycle.py`, `engine.apply_action`) + TS-блоки | порт TS 1:1 | **порт TS 1:1** с русскими текстами; legacy-коды в `legacy_codes` | 218 тестов фронта — готовая спецификация |
| КК | `QualityAssignment` + документы quality* | `QcRequest` (стадия, `route kk/kk_kvga`, `attempt`, статусы `CaseProcessV1`) + `QcAssignmentEvent` | `QualityAssignment` | **`QualityAssignment(case, stage, expert, assigned_by, reason)`**, история в `AuditEvent`; `route` — резерв, «КК КВГА» не реализуется | модель фронта согласована с заказчиком; правила `qc_route` не переданы |
| RBAC | prof без изменений; 4 домена + `CONFIRM`; 14 ролей `evga-*`; синхронизация — опция | 8 доменов; 22 роли (все legacy Keycloak); синхронизация `User Login Sync` | 4 домена; 15 ролей без префикса; скоуп выключен | **prof без изменений; домены `evga_cases/quality/registry/appeals/execution/cabinet/admin` + `dsp`; `CONFIRM`; 17 ролей `evga-*` + `observer`; синхронизация за флагом** | решение руководителя; таблица маппинга с инверсией `approver↔reviewer`, `confirmer↔approver` |
| Кабинет ОА | копия `apps/cabinet`, отдельный пользователь | копия `cabinet` | тот же SPA и те же action-endpoint'ы, отдельный `/cabinet/` только read | **копия `apps/cabinet`** + те же `DocumentActionView` с `cabinet=True` | ТЗ 2.12; скрытие внутренних данных через контекст `cabinet` |
| Нумерация | `evga-case` `30101-{yy}-{seq:05d}`, `evga-document`, `evga-counter-case`, `УЧ-…` | 7 legacy-форматов (`standard`, `with_org`, `PRIKAZ`, `ВП-…/tail`) | 4 фронтовых | **фронтовые + legacy `standard/with_org` за адаптером для `registration_number`** | дело совпадает у всех; регистрационные номера нужны ЕРСОП/печати |
| Журнал | `AuditEvent` +4 поля, `record_event` | то же + `DocumentApproval`-лента | то же | **`AuditEvent` +`case, action_code, source, metadata`; лента согласований — выборка событий** | один журнал вместо пяти |
| Таймеры | `process_deadlines`, автоподпись не реализуется | `evga_process_timers`, автоподпись за флагом, опрос ЕРСОП | `process_deadlines`, автоподпись выключена | **`process_deadlines` по cron (`scheduler`)**; просрочки на чтение; автоподпись/автосоздание — за флагами | без Celery; решение руководителя |
| ЕРСОП | `ErsopRegistration` + `ErsopExchange`, stub/soap | то же + `confirm_status_id`, `raw_xml`, callback | `ExternalRegistration/ExternalExchange` (общая для систем) | **`ErsopRegistration` на версию + `ErsopExchange`**, контракт `M_TYPE_*` из n8n | образец prof `ersop`; детали payload — B §8.1 |
| Уведомления | `Notification` на получателя | `Notification` (+`notification_type`, `channel`) | `Notification` + `NotificationRead` (M2M) | **строка на получателя** (`recipient`, `read_at`) | проще запросы «мои непрочитанные»; форма `portal.notifications` |
| Фронт-шлюз | `EvgaGateway` + `evgaAdapter`, 6 этапов | то же + адаптер legacy-статусов/ролей | то же, `action(id, action, expectedVersion, payload)` | **`EvgaGateway` (apiGateway/localGateway) + `evgaAdapter`**, формы не трогаются | `prof-frontend-integration.md` §4 |
| Печать/PDF | клиент до I11, затем WeasyPrint | сервер в итерации 7 | клиент, сервер — техдолг | **клиентский pdfmake; серверный — I11** | демо не зависит от PDF; ЕРСОП-stub не требует файла |
| План | I0–I11, демо после I4 (≈92) | 0–8 (≈93), демо №1 после итерации 3 | 0–5 (≈40 + техдолг) | **I0–I11 (≈94 бэкенд + ≈36 фронт), Демо-1 после I4** | ранний сервер; порядок этапов процесса; оценка C занижена из-за отложенных проекций/тестов |

---

## Приложение. Перечень утверждений, помеченных «не подтверждено»

1. Соответствие `zeebe_process_id → prc_*` и M-коды для видов `weekly`, `measurement`, `forward-*`, `reply-*`, `claim-*`, `completion`, `quality2/quality3` — справочник `surfk.evga_document_types` не выгружен; реконструкция `bpmn-processes.md` §3.10.
2. Семантика оснований с кодами `13/14` → `qc_route = 'KK KVGA'` (`Get Case Bases`) и вообще правила маршрута КК КВГА.
3. Keycloak-роль подтверждающего реестра (`report_manager` / `report_manager_kvga`) и соответствие `role_id 4/28, 5/30` ролям `kvga_kk_head_approver`/`kvga_kk_expert`.
4. Атрибут БИН в claims Keycloak для `audit_object_signer` (провижининг представителя ОА).
5. Реальные значения ЕРСОП: `organCode`, `SubjectInfo.subjectId`/`ObjectInfo.objId`, `userCreate/userSign` (в legacy — MOCK), транспорт (SOAP PI vs REST-шлюз), наличие callback; маппинг `values.order.type` → `M_TYPE_*` для доп. поручений.
6. Смысл id статусов legacy `1, 2` (черновые), `3, 22` (неактивные), `49` (`sent_to_ak`), `11, 12` (дело «на КК»); полный справочник `case_statuses`.
7. Состав колонок `surfk.evga_doc_info_request`, `evga_doc_ir_questions`, `evga_qc_requests` (в экспорте видны только имена таблиц/частично).
8. Тела хранимых функций `surfk.check_document_creation_condition`, `check_document_submit_allowed`, `check_transition_condition`, `get_case_blocking_statuses`, `send_case_to_qc`, `assign_qc_expert`, `complete_qc_review`, `send_document_to_audit_object`, `acknowledge_document`, `create_full_document_snapshot`, `get_next_*_sequence`.
9. Содержимое `evga_document_mappings` (`fields_mapping`, `subtables_mapping`, `form_schema`) и значения справочников `surfk.*` (сидируются из фронта до получения дампа).
10. Срок возражений: календарные `P10D` (BPMN) vs рабочие дни (фронт) — выбор фронта не подтверждён заказчиком.
11. Ответы заказчика Q09–Q20 (состав комплектов КК, момент создания предписания, кто создаёт ответ о мерах, критерии завершения, справочники, печатные бланки) — реализованы по временным решениям фронта.
12. Источник производственного календаря РК.
