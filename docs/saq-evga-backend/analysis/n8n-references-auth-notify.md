# Старый бэкенд ЭВГА на n8n: справочники, авторизация/Keycloak, уведомления, журнал, апелляции, прочее

Отчёт аналитика по области «справочники, авторизация/Keycloak, уведомления, журнал активности, апелляции, прочее»
старой реализации ЭВГА (n8n-воркфлоу + PostgreSQL `surfk.*` / `portal.*` + Keycloak + Camunda 8/Zeebe).
Цель — дать команде prof-стиля (Django 5 + DRF + PostgreSQL + Keycloak) полную картину того, что было, и
предложение, как это положить в Django-бэкенд для фронта `saq-evga-test`.

Все утверждения ниже основаны на реальных файлах:

* `src/n8n_old/n8n_export/workflows/*.json` — 84 воркфлоу, отобранных как «EVGA»;
* `src/n8n_old/n8n_export/all_workflows_raw.json` — полный экспорт (566 воркфлоу), из него дополнительно
  вытащены портальные/НСИ воркфлоу, на которые ссылаются EVGA-воркфлоу (`Rabbit MQ logger`, `EVGA Docs: Roles`,
  `Appeals - Experts list`, `get-qc-heads/experts`, `Get unread notifications`, `Mark notification as read`,
  `NSI BNS Integration *`, `GetNsiAttr*`, `Create Permission`, `Decrypt Users`, `Zeebe: Start Process` и др.);
* `src/n8n_old/n8n_export/analysis/{references,notif_log_appeals,remaining_domains}_raw_dump.txt`;
* `src/n8n_old/bpmn/bpmn_summary.txt` (для `allowed_roles` и процесса возражений);
* фронт `src/evga/saq-evga-test/src/{types.ts, data/demoData.ts, modules/evga/appeals.ts, components/Notifications.tsx, history.ts}`;
* эталон `src/prof/saq-prof-control-demo/backend/apps/{accounts,catalogs,core}/models.py`,
  `apps/accounts/{services/keycloak.py, authentication.py, permissions.py, management/commands/seed_roles.py}`.

Скрипты разбора: `scratchpad/tmp_n8n_refs/dump_nodes.py` (дамп узлов: webhook path/method, SQL, jsCode с
свёрнутым JWT-guard, httpRequest url/headers/body, credentials, Set/Switch/If) и `dump_raw.py` (то же по
`all_workflows_raw.json`). Результаты в `scratchpad/tmp_n8n_refs/out/*.txt`.

Обозначения: «активен» = `active: true` в экспорте; путь `/webhook/<path>` — публичный URL n8n
(`$vars.N8N_WEBHOOK_BASE_URL/webhook/...`).

---

## 0. Резюме (TL;DR)

1. **Справочники ЭВГА — это локальные таблицы `surfk.*`**, отдаваемые 20 однотипными воркфлоу
   `EVGA: <Name> - Get` (`GET /webhook/evga/references/<slug>?search&limit&offset&lang`). Никакой автоматической
   синхронизации ЭВГА-справочников с внешним НСИ **нет**: воркфлоу `Sync reference (API → PostgREST → merge)`
   архивирован и пуст (`isArchived: true`, 0 узлов). Внешние источники в системе есть только для
   *портальных* справочников (`acc_100.*` через SOAP eStat/BNS «getSprav», расписание `0 20 * * 0-5`) и для
   ГБД ЮЛ (поиск по БИН, SOAP `SI_GBD_JL_PIWS_OS` / REST `camel-gateway/api/out-integrations/gbdul`).
   → В Django: 18 справочников как модели `catalogs` + `seed_catalogs`-стиль команды; ГБД ЮЛ — прокси-сервис;
   ЕНСИ (КАТО/ОКЭД) — не нужны ЭВГА напрямую.
2. **Пользователи/роли**: Keycloak realm `efc` (issuer `https://account-{dev,test}.…/realms/efc`),
   клиент `web-ui-service` (azp), `preferred_username` = ИИН (12 цифр). Роли — realm-роли Keycloak;
   для подсистемы ЭВГА зафиксирован список из 19 назначаемых ролей (`SUBSYSTEM_SCOPE_CONFIG.evga.assignableRoles`
   в `Keycloak Subsystem Access`), базовая роль `evga_user`/`surfk_user`, админ подсистемы `admin_evga`,
   глобальный `portal_admin`, ИБ-админ `ib_admin`. При логине `User Login Sync` (`POST /webhook/user-login-surfk`)
   апсертит `surfk.users` по ИИН и **полностью перезаписывает** `surfk.evga_user_roles` ролями из токена
   (по коду в `surfk.evga_roles`, орган жёстко `'30101'`). Роли для выборок (руководители/эксперты КК и апелляции)
   берутся из вью `surfk.evga_users_with_roles` по `role_id` (4/28 — руководители КК, 5/30 — эксперты КК,
   7 — `appeal_head`, 8 — `appeal_expert`).
   → В prof-стиле: `User(auth_provider=keycloak)` + `FederatedIdentity(iss, sub)` уже есть; добавить `iin`,
   `position`; роли → `Role`/`RoleAssignment` с seed из таблицы §4.8; синхронизацию ролей из claims
   `realm_access.roles` делать в `provision_user_from_claims`.
3. **Уведомления** — портальный сервис, а не ЭВГА-специфичный: таблица `portal.notifications`
   (`user_id, title, message, event_type, notification_type, meta_data jsonb, status UNREAD/READ, channel 'WEB',
   read_at, deleted_at`), создание по списку e-mail получателей (`POST /webhook/send-notification-with-recipients`),
   чтение непрочитанных, отметка прочитанным (одно/все), плюс push через кастомный узел
   `CUSTOM.notificationService` → `{APP_BASE_URL}/api/notifications/notifications` (WebSocket-сервис портала).
   Каналов email/SMS **нет**. Есть ещё legacy-таблица `notifications.web_notifications` (jsonb `object_data`).
   → В Django: `apps/notifications` с моделью `Notification` (§5.5), API unread/mark-read/mark-all-read,
   сервис `notify()`; WebSocket — отложить.
4. **Журнал**: три разных лога: `surfk.evga_audit_log` (`POST /webhook/activity-log`, «пользовательские»
   действия по делу/документу), `surfk.case_status_history` (`POST /webhook/evga/case-workflow-log` из Zeebe),
   `surfk.evga_document_workflow_history` (переходы документов, пишется в SQL действий), плюс
   ИБ-лог в RabbitMQ (JSON schemaVersion 1, `eventType` DATA_ACCESS/DATA_CHANGE/AUTH_FAILURE/ACCESS_DENIED/…).
   `GET /webhook/activity-log` (воркфлоу `get logs`) неактивен и читает *другую* таблицу `surfk.activity_log`.
   → В Django: расширить `core.AuditEvent` (§6.6): `action` → свободный код + `action_name_ru`, добавить
   `case` FK (денормализация), `metadata` JSON, `ip_address`, `source` (`user|system|zeebe`), `actor_iin/actor_name`.
5. **Апелляции**: старая модель — назначение эксперта апелляции по делу
   (`surfk.case_appeal_expert_assignments`, история `assigned/unassigned`), список дел с активным документом
   `M20-VOZ` (возражения), документ результата возражений `M23-RVO` (`surfk.evga_doc_objection_appeal_result` +
   `surfk.evga_doc_oar_violations`) с действиями `get/update/sign/send_to_confirmation/confirm/return_for_revision/
   change_confirmer/activate/get_actions`; в BPMN — `appeal_expert` готовит, `appeal_head` утверждает; срок
   возражений объекта — таймер `P10D`. Фронт `appeals.ts` богаче: решение о принятии/отказе (председатель
   комиссии), аргументированные обоснования аудитора с подписью руководителя, 10 рабочих дней от вручения отчёта.
   → В Django: `apps/appeals` (§7.4) — `Appeal`, `AppealExpertAssignment`, `AppealAdmission`, `AppealArgument`;
   документ результата — через `documents`.
6. **Прочее**: Worktime — портальный модуль отсутствий (`portal.time_requests`), к ЭВГА не относится → не
   переносить. `EVGA Info Request API (deprecated)` — заглушка («deprecated as of migration 122; InfoRequest
   (type_id=10) uses universal DynamicForm + Zeebe») → не переносить. ГБД ЮЛ → прокси. ЭЦП: подписи хранятся как
   текст в `surfk.evga_document_signatures.signature`, серверной проверки в n8n нет.
7. **Не переносить**: n8n-webhook-роутинг, `{{ }}`-интерполяция строк в SQL (SQL-инъекции повсеместно),
   декод JWT без проверки подписи (`// без верификации для dev`), дублирующиеся активные/неактивные копии,
   ИБ-лог в RabbitMQ, крипто-сервис blind-index/шифрования ПДн портала, `CUSTOM.*` узлы, PostgREST (в
   EVGA-воркфлоу его фактически нет — везде прямой SQL), `Cache-Control: public, max-age=3600` на справочниках
   с ролями/сотрудниками.

---

## 1. Инвентарь воркфлоу области

| Воркфлоу (id) | active | Метод и путь `/webhook/…` | Таблицы / внешние вызовы | Вердикт |
|---|---|---|---|---|
| Sync reference (API → PostgREST → merge) (`8paoT84HwJbJhvYT`) | нет, `isArchived` | — | нет узлов | drop (пустой) |
| EVGA: Dictionaries - Get (`3n3RvBa8OHIKMa01`) | нет | GET `evga/references/dictionaries?dic_name` | `surfk.dictionaries` | adapt → `catalogs.Dictionary` |
| EVGA: Evga Audit Type - Get (`94ryVnoisyTFkfn9` акт., `dJYWOoVwOyzcJP8a` неакт.) | да/нет | GET `evga/references/evga-audit-type` | `surfk.audit_types` | adapt |
| EVGA: Evga Check Type - Get (`ExW3o2jnTq7qvhzB`) | нет | GET `evga/references/evga-check-type` | `surfk.inspection_types` | adapt |
| EVGA: Evga Check Initiator - Get (`7Aj2QT1LVTXzUm7v` акт., `04Cibm4rFz3Wq3zT`) | да/нет | GET `evga/references/evga-check-initiator` | `surfk.check_initiators` | adapt |
| EVGA: Evga Controlling Org - Get (`d9vJa7yUNZLQAORi`) | нет | GET `evga/references/evga-controlling-org` | `surfk.controlling_bodies` | adapt |
| EVGA: Evga Risk Category - Get (`bXMRDDNR76RXz9Ds`) | да | GET `evga/references/evga-risk-category` | `surfk.risk_levels` | adapt |
| EVGA: Control Reasons Type - Get (`dov9GY00d150epAH`) | да | GET `evga/references/control-reasons-type` | `surfk.control_reasons_types` | adapt |
| EVGA: Control Spheres - Get (`axlE7a7ITvX16wq5`) | да | GET `evga/references/control-spheres` | `surfk.evga_control_spheres` | adapt |
| EVGA: Offense Type - Get (`439laH39s1Q5bzgB`) | нет | GET `evga/references/offense-type` | `surfk.offense_type` | adapt |
| Get offense-type-tree (`0IOo9XfdiioGbZTL`) | да | GET `evga/references/offense-type/tree?lang` | `surfk.offense_type` (рекурсивный CTE) | adapt (дерево) |
| EVGA: Response Measure - Get (`DXCxozK2ekbpuv8s` акт., `CUcYxpcvYVw1slVz`) | да/нет | GET `evga/references/response-measure` | `surfk.response_measures` | adapt |
| EVGA: Risk Object Type - Get (`AcdVDPyHIUCKOwLO`) | да | GET `evga/references/risk-object-type` | `surfk.risk_object_types` | adapt |
| EVGA: Sampling Methods - Get (`6M1QmkoL05vqZvvd`) | да | GET `evga/references/sampling-methods` | `surfk.sampling_methods` | adapt |
| EVGA: Organizational Legal Forms - Get (`csYhv3msgPXyBi5M`) | нет | GET `evga/references/organizational-legal-forms` | `surfk.organizational_legal_forms` | adapt |
| EVGA: Organ Reg Check - Get (`fhBbMqPlssBvgaxQ`) | да | GET `evga/references/organ-reg-check` | `surfk.organ_reg_checks` | adapt |
| EVGA: Subj Sched Insp - Get (`bCNlWrWTjc99dQRI`) | да | GET `evga/references/subj-sched-insp` | `surfk.subj_sched_insp` | adapt |
| EVGA: Audit Result - Get (`8iFZuofJCHUAEuYx` акт., `0MnIhYQ2wt0BjkTT`) | да/нет | GET `evga/references/audit-result` | `surfk.audit_results` | adapt |
| EVGA: Evga Audit Questions - Get (`ceqhcaYV9ZpKEZs8` акт., `bfvMim1hQNrfjP4x`) | да/нет | GET `evga/references/evga-audit-questions` | `surfk.evga_audit_questions` | adapt |
| d-controlling-orgs (`cRho46I2q0Kpvx70`) | да | GET `evga/references/d-controlling-orgs` | `surfk.d_controlling_orgs` (`status = 1`) | adapt |
| EVGA: Employees - Get (`7Tp12ioqWtBv5KAf` акт., `CXm2pFtLWNvgPkKY`) | да/нет | GET `evga/references/employees?department_id` | `surfk.employees` + `departments` + `positions` | adapt → `accounts.User`/`catalogs.Department` |
| EVGA: Audit Objects - Get (`9Y8jINu42un2pYSj`) | да | GET `evga/audit-objects?search&account_id&state` | `surfk.evga_audit_object` (jsonb `object_data`) | rewrite → `subjects`-подобная модель |
| EVGA: Audit Object - Search by BIN (`7iyk59la1TjP16ku`) | нет | GET `evga/audit-object/search?bin&year&lang` | `surfk.audit_objects` + `plan_objects` + `annual_plans` + … | adapt (карточка объекта + перечень) |
| EVGA Check Audit Type (Planned/Unplanned) (`FYuuTCkkeRJB255u`) | да | POST `evga/check-audit-type` {caseId} | `surfk.cases` ⨝ `inspection_types` | rewrite → метод модели |
| Service GDBJL surfk (`FffOVw8qDHSRYDF0`) | нет | POST `findJurByBin` | SOAP `prodpi1.emf.minfin.kz:50000 … SI_GBD_JL_PIWS_OS` | adapt → прокси ГБД ЮЛ |
| Get Keycloak Users (`cJ1xF7MxEVtgiGI6`) | да | GET `keycloak-users?page&limit&search&enabled&withoutMeaningfulRoles` | Keycloak Admin API `/admin/realms/{realm}/users`, `/users/count`, `/users/{id}/role-mappings/realm`; `portal.roles/permissions` | adapt (админка) |
| Keycloak IB Admins (`G6kjdQpvAyG2s4VX`) | да | GET/POST/DELETE `keycloak-ib-admins` | `/roles/ib_admin/users`, role-mappings | drop (портальная ИБ) |
| Keycloak Subsystem Access (`4iPxdu8ogatbs5PZ`) | да | GET `keycloak-subsystem-access/{groups,roles,user,attributes}`; PUT/DELETE `…/user-groups`; POST/DELETE `…/user-roles`, `…/user-attributes` (`?subsystemKey=evga`) | Keycloak Admin API groups/roles/users | adapt (список ролей ЭВГА, назначение) |
| Keycloak Subsystem Users V2 (`7WTPe1Hfc3SlNHYJ`) | да | GET/POST/DELETE `keycloak-subsystem-users-v2?role=evga_user&userId` | `/roles/{role}/users`, role-mappings | adapt (доступ к подсистеме) |
| User Login Sync (`dFGgZ79UW3AJ0pYW`) | да | POST `user-login-surfk` (Bearer) | `surfk.users`, `surfk.evga_roles`, `surfk.evga_user_roles`, `surfk.controlling_bodies` | adapt → `provision_user_from_claims` |
| create new 2 auth (`Fv5Au1MNNVWMahbf`) | нет | POST `create_new_report` | `igo.*` (другая подсистема ИГО) | drop |
| keycloak (`8HsKR3t3sg00Jvij`) | нет | ручной триггер | CRUD-песочница узла `CUSTOM.keycloak` | drop |
| notification service / copy (`5uZolavVfDnaAalo`, `Fonl2vusmVyltVFy`) | нет | ручной триггер (тест) | `portal.notifications`, `CUSTOM.notificationService` | drop (тест) |
| create notification by recipients (`eWWfnxbNcUGAAHic`) | да | POST `send-notification-with-recipients` | `portal.users` (blind-index e-mail через крипто-сервис), `portal.notifications`, WebSocket push, RabbitMQ | adapt (сервис `notify`) |
| notifications/mark-all-read (`cuHBnizrZZumLmt4`) | да | PUT `notifications/mark-all-read` | `portal.notifications` | adapt |
| update_notification_status (`BN38VeEWly0MajAR`) | да | PATCH `update_status?id=` | `notifications.web_notifications` (legacy) | drop |
| Get unread notifications / get unread notification (raw) | нет/да | GET `notifications/unread?page&limit` | `portal.notifications` | adapt |
| Mark notification as read (raw) | да | PUT `:id/mark-read` | `portal.notifications` | adapt |
| Log Activity (`5hGWswMfKbzjYGZD`) | да | POST `activity-log` | `surfk.evga_audit_log` | adapt → `AuditEvent` |
| get logs (`CBh9VqXtOmhG2x1f`) | нет | GET `activity-log?feature&entity_id&…` | `surfk.activity_log` (другая таблица!) | adapt (API чтения) |
| EVGA Case Workflow Log (Zeebe → PostgreSQL) (`6Ge3jrKwsxPQwAzk`) | да | POST `evga/case-workflow-log` | `public.users`, `surfk.case_status_history` | rewrite (внутренний вызов) |
| Appeals - Assign Expert (`7opHE5W2RZTxZOQH`) | да | POST `assign-appeal-expert/cases/:caseId/assign-appeal-expert` | `surfk.case_appeal_expert_assignments`; → `evga/zeebe`, `activity-log` | adapt |
| Appeals - Cases list (`0DzdV8OgRgY6s8ab`) | да | GET `appeals/cases?page&limit&search&status_id&controlling_body_code&appeal_head_iin&appeal_expert_iin&lang` | `surfk.cases`, `case_statuses`, `controlling_bodies`, `audit_objects`, `evga_case_documents` (`M20-VOZ`) | adapt |
| Appeals - Heads list (`FHngaPfJ2bLF7Hw8`), Appeals - Experts list (raw `OyjEDQEShrwsUcqb`) | да | GET `appeals/heads`, GET `appeals/experts` | `surfk.evga_users_with_roles` (`role_id = 7` / `= 8`) | adapt |
| EVGA - Appeal Result (M23-RVO) actions (`EnwlzmUegk0ZsWI3`) | да | POST `evga/appeal-result` {action, params} | `surfk.evga_doc_objection_appeal_result`, `evga_doc_oar_violations`, `evga_document_signatures`, `evga_document_workflow_history`, `evga_status_transitions` | adapt (в `documents`) |
| EVGA Info Request API (deprecated) (`3qkoem1fA0uuqmUu`) | да | POST `evga/info-request` | — (возвращает `success:false`) | drop |
| Worktime - Create Time Request (`akoW0unmIuiYQJnv`) + 9 raw `Worktime - *` | да | POST `worktime/requests`, PATCH `worktime/requests/:id/{cancel,manager/approve,…}`, GET `worktime/requests/{my,manager,director}`, GET `worktime/journal` | `portal.time_requests`, `portal.time_request_status_history` | drop (портал) |
| My workflow 31 (`Ct0H9kLN7saxeZwc`) | да | POST `evga-case-status/update` {case_id,status_id} | `surfk.cases` (прямой UPDATE статуса без истории) | drop |

---

## 2. Общий паттерн `EVGA: <Name> - Get` (все справочники)

Все 18 справочных воркфлоу — копии одного шаблона (например `EVGA_Evga_Audit_Type_-_Get__94ryVnoisyTFkfn9.json`):

```
Webhook (GET evga/references/<slug>) → Parse Query Parameters → [Get Reference Data ∥ Get Total Count] → Merge → Format Response → Respond Success
                                                                                                          ↘ Format Error → Respond Error (500, code 'REFERENCE_ERROR')  (только у части)
```

Узел `Parse Query Parameters` (jsCode):

* `search` (ILIKE по `name_ru|name_kz` в зависимости от `lang` **или** по `code`), `limit` (default 100), `offset` (0),
  `lang` (`'ru'` | `'kk'`; `nameField = lang === 'kk' ? 'name_kz' : 'name_ru'`);
* защита от инъекций — только `escapeSql = str.replace(/'/g, "''")`, после чего строка **склеивается в SQL**
  (`{{ $json.whereClause }}`, `LIMIT {{ $json.limit }}`). Сам `nameField` подставляется в SELECT как имя колонки.

SQL:

```sql
SELECT id, code as code, {{nameField}} as name, name_ru, name_kz, created_at, updated_at
FROM surfk.<table> {{whereClause}} ORDER BY id LIMIT {{limit}} OFFSET {{offset}}
```

Ответ (`Format Response`):

```json
{ "success": true,
  "data": [ { "id": 1, "code": "…", "name": "…", "name_ru": "…", "name_kz": "…", "created_at": "…", "updated_at": "…" } ],
  "total": 42, "limit": 100, "offset": 0, "lang": "ru" }
```

Заголовки успеха: `Content-Type: application/json; charset=utf-8`, у большинства
`Cache-Control: public, max-age=3600` (у `employees`, `audit-objects`, `dictionaries` — без кэша). Ошибка:
`{ "success": false, "error": "<message>", "code": "REFERENCE_ERROR" }`, HTTP 500.

Авторизации на справочниках **нет** (`auth=None`, Authorization не читается).

---

## 3. Каталог справочников

### 3.1 Сводная таблица

Колонки записи по умолчанию (☐): `id, code, name_ru, name_kz, created_at, updated_at`. Отклонения перечислены.

| # | Справочник (RU) | Endpoint `/webhook/evga/references/…` | Таблица | Поля записи | Источник / синхронизация | Примеры кодов, известные из кода |
|---|---|---|---|---|---|---|
| 1 | Тип аудита | `evga-audit-type` | `surfk.audit_types` | ☐ | локальная таблица, ручное наполнение | `'16'` — аудит финансовой отчётности (BPMN: `if processData.auditTypeCode = "16" then "M17-AO-F" else "M17-AO-S"`; `Zeebe: Start Process` передаёт `auditTypeCode`); у типов документов есть `audit_type_codes text[]` (`Get Available Document Types`). Фронт: `auditTypeOptions = ["Соответствие", "Фин. отчетность"]` (`caseSearch.ts`) |
| 2 | Вид проверки (плановая/внеплановая) | `evga-check-type` (неакт.) | `surfk.inspection_types` | ☐ | локальная | `EVGA Check Audit Type`: `PLANNED_CODES = ['1', 'scheduled']` сравнивается с `inspection_types.code` (комментарий в коде: «Укажи реальные коды плановых проверок из таблицы audit_types» — код так и не уточнили). BPMN: `Gateway_AuditTypeCheck … COND: =auditTypeCheckResult.body.isPlanned = true` |
| 3 | Инициатор проверки | `evga-check-initiator` | `surfk.check_initiators` | ☐ | локальная | используется в `EVGA: Create Case v4` при формировании оснований: `(SELECT name_ru FROM surfk.check_initiators WHERE code = '${initiatorCode}')` — сохраняется *название*, не FK |
| 4 | Тип основания контроля | `control-reasons-type` | `surfk.control_reasons_types` | ☐ | локальная | `Create Case v4`: `(SELECT name_ru FROM surfk.control_reasons_types WHERE code = '${typeCode}')` |
| 5 | Сферы контроля | `control-spheres` | `surfk.evga_control_spheres` | ☐ + `daa_id` | локальная (`daa_id` — ссылка на внешний ДАА-идентификатор, вероятно ЕНСИ) | — |
| 6 | Орган контроля (ЭВГА) | `evga-controlling-org` (неакт.) | `surfk.controlling_bodies` | ☐ | локальная | `'30101'` — жёстко в `User Login Sync` как орган всех ролей (`controlling_body_code = '30101'`) |
| 7 | Органы контроля (справочник d_) | `d-controlling-orgs` | `surfk.d_controlling_orgs` | `id, code, bin, par_id, name, name_ru, name_kz, short_name_ru, short_name_kz, org_type_id, org_lvl_id, su_code`; фильтр `status = 1`; поиск и по `bin` | локальная копия внешнего справочника органов (иерархия `par_id`, уровни `org_lvl_id`) | — |
| 8 | Категория/уровень риска | `evga-risk-category` | `surfk.risk_levels` | ☐ | локальная | `audit_objects.risk_level_id`, `risk_value` |
| 9 | Тип объекта риска | `risk-object-type` | `surfk.risk_object_types` | ☐ | локальная | коды: `PPContractItem, PICustomer, PPContractHeader, PPPlanItem, QGAccountBalances, BudgetExpenditure, FinancialReporting` (маппинг в `violations`: `gz_contract_subject→PPContractItem, control_object→PICustomer, gz_contract→PPContractHeader, …plan_item→PPPlanItem, financial_activity→QGAccountBalances, budget_expense→BudgetExpenditure, financial_report→FinancialReporting`) |
| 10 | Типы правонарушений (дерево) | `offense-type` (плоско, неакт.), `offense-type/tree` (акт.) | `surfk.offense_type` | `id, type_code, parent_code, type_name_ru/kz` (плоский), `offence_name_ru/kz, level_ru/kz` (дерево); `is_group = level_ru IS NOT NULL OR level_kz IS NOT NULL` | локальная; дерево строится рекурсивным CTE с натуральной сортировкой кода (`1.2.10` после `1.2.9`) | узел дерева `{code, name, group, children?}`; `violations` связывает `v.violation_type_code = ot.type_code` |
| 11 | Меры реагирования | `response-measure` | `surfk.response_measures` | ☐ | локальная | — |
| 12 | Методы выборки | `sampling-methods` | `surfk.sampling_methods` | ☐ | локальная | — |
| 13 | ОПФ | `organizational-legal-forms` (неакт.) | `surfk.organizational_legal_forms` | `id, code, name_ru, name_kz, created_at` (без `updated_at`) | локальная; ГБД ЮЛ отдаёт `orgForm`, `orgFormCode`, `FormOfLaw` | — |
| 14 | Орган, зарегистрировавший проверку | `organ-reg-check` | `surfk.organ_reg_checks` | ☐ | локальная | — |
| 15 | Субъект плановой проверки | `subj-sched-insp` | `surfk.subj_sched_insp` | ☐ | локальная | — |
| 16 | Результат аудита | `audit-result` | `surfk.audit_results` | ☐ | локальная | — |
| 17 | Вопросы аудита (программа) | `evga-audit-questions` | `surfk.evga_audit_questions` | `id, code_id→code, theme_ru/kz (→name), sub_theme_ru/kz, program_ru/kz, npa, created_at, updated_at`; поиск по `theme_*`/`code_id` | локальная | `violations`: `aq.code_id = v.control_question`, текст вопроса = `COALESCE(aq.sub_theme_ru, v.control_theme)` |
| 18 | Универсальный словарь | `dictionaries?dic_name=` (неакт.) | `surfk.dictionaries` | `id, dic_name, code, name_ru, name_kz, created_at, updated_at`; сортировка `dic_name, code` | локальная | известные `dic_name`: `'status_offense'` (статус нарушения; `cons_d.code = UPPER(v.violation_status_code)`), `'type_cons_offence'` (тип последствий нарушения; `= v.consequence_type_code`) |
| 19 | Сотрудники | `employees?department_id` | `surfk.employees` ⨝ `departments` ⨝ `positions` | `id, user_id, iin, fullname, email, work_phone, mobile_phone, department{id,code,name,name_ru,name_kz,short_name}, position{id,code,name,name_ru,name_kz}, employment_status, hire_date, is_active`; фильтры `e.is_active`, `dept.is_active`, `pos.is_active`, `employment_status='active'` | локальная кадровая таблица (без синхронизации в экспорте) | — |
| 20 | Объекты аудита (реестр ЭВГА) | `/webhook/evga/audit-objects?search&account_id&state=ACTIVE` | `surfk.evga_audit_object` | `id, account_id, object_data jsonb {bin, name_ru, name_kz, region, district_name, legal_address, fact_address, justification}, state, created_time, updated_time, created_by, updated_by, app_name` | «model-objects»-стиль портала (jsonb `object_data`, `state`, `app_name`) | — |
| 21 | Объект аудита по БИН + перечень | `/webhook/evga/audit-object/search?bin&year=2025&lang` (неакт.) | `surfk.audit_objects` ⨝ `organizational_legal_forms` ⨝ `regions` ⨝ `controlling_bodies` ⨝ `risk_levels` ⨝ `plan_objects` ⨝ `annual_plans` ⨝ `audit_types` ⨝ `inspection_types` | `audit_object_id, bin, object_name(_ru/_kz), address_ru/kz, opf_id/opf_name, region_id/name, controlling_body_*, risk_level_*, risk_value, in_registry, plan_data{plan_object_id, plan_id, plan_title_ru, plan_order_number, plan_order_date, audit_type_*, inspection_type_*, audit_event_name, coverage_start_date, coverage_end_date, coverage_amount, coverage_2023..2025, score_2023..2025, score_3_years, max_score, risk_level_gu, risk_probability, risk_level_abp, last_audit_date, last_audit_type, subject_type, has_republican_budget}` | локальные таблицы (перечень объектов на год) | БИН валидируется: 12 цифр |

Дополнительно встречаются в SQL, но без собственного endpoint: `surfk.regions` (`id, name_ru, name_kz`),
`surfk.case_statuses` (`id, code, name_ru, name_kz`), `surfk.evga_document_types` (`code`, `zeebe_process_id`,
`requires_approval/confirmation/kvga_confirmation/signature`, `sends_to_audit_object`, `creator_roles jsonb`,
`audit_type_codes text[]`, `allow_multiple`, `stage_id`), `surfk.evga_document_statuses` (`code`: `draft,
pending_approval, approved, pending_confirmation, confirmed, revision, signed, active, signed_with_objection,
pending_invited_specialist_sign, pending_work_group_approval, completed`), `surfk.evga_status_transitions`
(`document_type_id, from_status_id, to_status_id, action_code, action_name_ru/kz, requires_signature,
requires_comment, required_role_code, is_automatic`) — это домен документов, здесь только для полноты.

### 3.2 Синхронизация: что реально есть

| Механизм | Где | Что делает | Относится ли к ЭВГА |
|---|---|---|---|
| `Sync reference (API → PostgREST → merge)` | `workflows/Sync_reference_API_PostgREST_merge___8paoT84HwJbJhvYT.json` | **пусто**, архив (2025-11-03) | нет |
| `NSI BNS Integration Timer OKED` (raw, active) | cron `0 20 * * 0-5` → саб-воркфлоу `NSI — NSI BNS Integration` (`UTohIq2kk7L67YIt`, не в экспорте) с `version_id: 4855, name_ru: "классификатор ОКЭД", exec_type: "auto"` | SOAP `SI_Eminfin2eStat_getSprav_OS` (`http://minfin.kz/ESTAT_API`, ns `http://estat.gov.kz/klass/KLASS_ESTAT_SPRAV_new`, `getSpravRequest{version_id,name_ru,name_kz}`), basic auth `WS_USER_NSI`; ответ `responseList[]` → `POST {APP_BASE_URL}/api/model-objects/objects/NSI_DEMO?schemaId=kato_all` (портальный «model-objects» API), лог в `acc_100.nsi_bns_log` | нет (портальные ЕНСИ: КАТО `version_id 213`, ОКЭД 4855) |
| `GetNsiAttr`, `GetNsiAttrFKR`, `GetNsiAttrCBR` (raw) | POST `get_nsi_attr`, `get_nsi_attr_cbr` | читают `acc_100.nsi_attribute`, `nsi_attribute_value`, `fkr_attribute`, `cbr_attr*` (jsonb `object_data`) | нет (ИГО/бюджет) |
| `spravochniki (cgo, main)` (raw, active) | GET `get_bud_cur_dev`, `get_gov_level`, `get_bud_realiz`, `get_bud_soderj`, `get_goals`, `get_ogu`, `get_org`, `get_regions`, `get_rgp` | читают `acc_100.curr_impr`, `bud_prog_gov_level`, `bud_prog_realiz`, `bud_prog_soderj`, `kgip1`, `regions` («Данные из справочника ЕНСИ») | нет (ЦГО/ИГО) |
| ГБД ЮЛ | `Service GDBJL surfk` (неакт.), `Service GDBJL` (raw, 3 копии, 2 активны: `jur/findJurByBin`, `jur/findJurByBinNew`), `gbdul_test` | см. §8.3 | да — поиск ЮЛ по БИН при создании дела/объекта |

Вывод: **все ЭВГА-справочники (`surfk.*`) — статичные локальные таблицы без автоматической синхронизации**;
периодичность — «никогда, руками через БД». Единственные внешние данные ЭВГА — ГБД ЮЛ (on-demand по БИН).

### 3.3 Предложение для Django (`apps/catalogs`)

В prof справочники — это модели-наследники `CodeNamedModel`/`OrderedCodeNamedModel` (`code`, `name`, `order`) в
`apps/catalogs/models.py` и одна команда `seed_catalogs` с константами-списками (`REGIONS`, `SUBJECT_TYPES`, …) через
`update_or_create` по `code`. Для ЭВГА нужна двуязычность → предлагаю абстракт
`BilingualCodeNamedModel(code, name_ru, name_kk, order, is_active)` (у prof `Region` уже имеет `name_ru/name_kk`;
использовать суффикс `kk`, как в prof, а не `kz`, как в surfk; сериализатор отдаёт `name` по `Accept-Language`).

| Django-модель (`catalogs`) | Из surfk | Поля сверх базовых | Сид | Прокси/внешний |
|---|---|---|---|---|
| `AuditType` | `audit_types` | `is_financial: bool` (вместо магического `'16'`) | `seed_evga_catalogs` | — |
| `InspectionType` (вид проверки) | `inspection_types` | `is_planned: bool` (вместо `PLANNED_CODES`) | сид | — |
| `CheckInitiator` | `check_initiators` | — | сид | — |
| `ControlReasonType` | `control_reasons_types` | — | сид | — |
| `ControlSphere` | `evga_control_spheres` | `daa_id` | сид | — |
| `ControllingBody` | `controlling_bodies` + `d_controlling_orgs` | `bin, parent FK, short_name_ru/kk, org_type, org_level, su_code, is_active` — объединить в одну модель; prof `GovernmentBody` («пока только КВГА») расширить или заменить | сид (КВГА `30101` + территориальные) | — |
| `RiskLevel` | `risk_levels` | `order` | сид | — |
| `RiskObjectType` | `risk_object_types` | `legacy_codes: JSON` (маппинг `gz_contract→PPContractHeader`…) | сид | — |
| `OffenseType` | `offense_type` | `parent FK(self)`, `is_group`, `level_ru/kk`, `path`/MPTT-подобная сортировка по натуральному коду; endpoint `/tree/` | сид из выгрузки таблицы | — |
| `ResponseMeasure` | `response_measures` | — | сид | — |
| `SamplingMethod` | `sampling_methods` | — | сид | — |
| `OrganizationalLegalForm` | `organizational_legal_forms` | `gbd_code` (для сопоставления с `orgFormCode` ГБД ЮЛ) | сид | ГБД ЮЛ |
| `OrganRegCheck` | `organ_reg_checks` | — | сид | — |
| `ScheduledInspectionSubject` | `subj_sched_insp` | — | сид | — |
| `AuditResult` | `audit_results` | — | сид | — |
| `AuditQuestion` | `evga_audit_questions` | `theme_ru/kk, sub_theme_ru/kk, program_ru/kk, npa`, `code = code_id` | сид (загрузчик из CSV/xlsx как `seed_checklists` в prof) | — |
| `DictionaryEntry` | `dictionaries` | `dic_name` → лучше две модели `OffenseStatus`, `OffenseConsequenceType` (prof предпочитает типизированные справочники, ср. `ViolationSeverity`, `RiskDegree`) | сид | — |
| `Region`, `Department` | `regions`, `departments`, `positions` | prof уже имеет `Region(code, number, name_ru, name_kk)`, `Department(code, name, region, is_central)`; добавить `Position(code, name_ru, name_kk)` | уже есть | — |
| сотрудники | `employees` | → `accounts.User` (`full_name`, `position`, `phone`, `department`) + `iin`; endpoint «сотрудники для выбора в рабочую группу» = `GET /api/accounts/users/?department=&search=` | — | — |
| объекты аудита | `evga_audit_object`, `audit_objects`, `plan_objects`, `annual_plans` | не catalogs; аналог prof `subjects.Subject` + `AnnualPlan`/`PlanObject` (домен «объекты аудита/перечень» — другой агент) | — | ГБД ЮЛ по БИН |

Что **не** делаем: PostgREST, jsonb `object_data`, «model-objects» API, `Cache-Control: public` (справочники
отдавать через DRF с ETag/короткий `max-age`, доступ только аутентифицированным).

Формат API (как в prof): `GET /api/catalogs/<slug>/?search=&page=&page_size=` → DRF-пагинация
`{count, next, previous, results:[{id, code, name_ru, name_kk, name}]}`; для дерева `GET /api/catalogs/offense-types/tree/`.
Фронт `saq-evga-test` сейчас хранит словари в коде (`caseSearch.ts`, `referenceForms.ts`); интеграционный слой —
см. отчёт по фронту.

---

## 4. Пользователи, роли, Keycloak

### 4.1 Keycloak: realm, клиенты, claims

Из `create new 2 auth` (`decode_JWT1`, зашитый образец токена) и переменных n8n:

| Параметр | Значение |
|---|---|
| Realm | `efc` (default в guard: `$vars.KEYCLOAK_REALM || 'efc'`); также встречаются realm `master` (admin-cli), `ecc` (тест), `expresso` (`KEYCLOAK_REALM_IDP`, политика паролей) |
| Issuer | `https://account-dev.emf.minfin.kz/realms/efc` (dev), `https://account-test.efinance.gov.kz/realms/efc` (test; JWKS-кэш в `staticData.__portalJwks`) |
| Клиент фронта | `azp: "web-ui-service"`, `aud: "account"`; ожидаемые аудитории guard: `'account,web-ui-service'` |
| Сервисные клиенты | `notifications-service` (для WebSocket-push), `ZEEBE_CLIENT_ID/SECRET` (client_credentials на `KEYCLOAK_TOKEN_URL` для Zeebe REST), `Keycloak admin` (credential узла `CUSTOM.keycloak`, `resource: token` → Admin API) |
| Scope | `openid roles city profile department-mapper groups email` |
| Claims | `sub` (uuid), `preferred_username` = **ИИН (12 цифр)**, `name`, `given_name`, `family_name`, `email`, `email_verified`, `realm_access.roles[]`, `groups[]` (копия ролей), `departments[]` — пути групп (`"/Platform Admins"`, `"/igo/departments/dos"`), `origin_user_id` (id во внешнем IdP, пишется в `surfk.users.origin_user_id`), `allowed-origins` (`app-dev`, `portal-dev`, `surfk-dev` `.emf.minfin.kz`) |
| Служебные роли, игнорируемые | `uma_*`, `offline_*`, `default-roles-*` (`isIgnoredKeycloakRole` в `Get Keycloak Users`) |

Переменные n8n, связанные с auth: `KEYCLOAK_REALM`, `KEYCLOAK_ADMIN_BASE_URL`, `KEYCLOAK_JWT_ISSUER`,
`KEYCLOAK_JWT_AUDIENCE`, `KEYCLOAK_JWT_CLOCK_TOLERANCE_SEC` (60), `KEYCLOAK_JWKS_URL`, `KEYCLOAK_JWT_JWKS` (pinned),
`KEYCLOAK_JWKS_TLS_INSECURE`, `KEYCLOAK_IDP_BASE_URL`, `KEYCLOAK_REALM_IDP`, `KEYCLOAK_TOKEN_URL`.

### 4.2 Проверка запросов (JWT)

Три поколения в одном экспорте:

1. **`PORTAL JWT GUARD v1`** (вставлен во все портальные воркфлоу и часть EVGA: `create notification by recipients`,
   `notifications/mark-all-read`, `Get Keycloak Users`, `Keycloak IB Admins`, `Keycloak Subsystem Access`,
   `Worktime`, `Get User Profile`, `Get Password Policy`, `Create Permission`, …): парсит `Authorization: Bearer`,
   требует `alg RS256` + `kid`, нормализует issuer (`http→https`, без хвостового `/`), проверяет `iss`, `aud`/`azp`,
   `exp` (+tolerance), `nbf`, `sub`, `typ==='Bearer'`, тянет JWKS (`/realms/{realm}/protocol/openid-connect/certs`,
   кэш 10 мин в `$getWorkflowStaticData('global')`, fallback `skipSslCertificateValidation`), проверяет RSA-подпись
   (`crypto.subtle` или чистая реализация RSASSA-PKCS1-v1_5 + SHA-256 на BigInt). Ошибки 401/502/503.
   **Важно**: guard срабатывает только если заголовок присутствует (`if (__auth !== undefined … )`), после него
   идёт собственный код узла, который часто просто декодирует payload.
2. **`verifyKeycloakJwt`** (Keycloak-воркфлоу): без подписи, локальная проверка `iss/aud/exp/sub`, выдаёт
   `callerUserId`, `callerRoles = realm_access.roles`, `username`, `email` (комментарий: «userinfo отключён:
   helpers.httpRequest падает на self-signed CA Keycloak»).
3. **Голый decode** (`User Login Sync`, `Log Activity` — вообще без токена, все `EVGA: * - Get`, `Appeals - *`,
   `EVGA - Appeal Result`, `update_notification_status` через узел `n8n-nodes-base.jwt` c cred `JWT Auth account 2`,
   `operation: decode`): «NB: подпись и exp здесь не проверяются (отдельная задача)», «Декодируем JWT (без
   верификации для dev)». Идентичность пользователя для EVGA-действий приходит **в теле запроса** (`user_iin`,
   `user_fullname`, `user_keycloak_id`, `performed_by_iin`) — т.е. подделываема.

### 4.3 Синхронизация пользователя при логине — `User Login Sync` (`POST /webhook/user-login-surfk`)

```
Webhook → Parse JWT Token → Token Valid? → Sync User (SQL) → Is Active? → Format Response → 200
                               ↘ 403 {error:'invalid_token', reason}         ↘ 403 {error:'user_blocked', message:'Доступ запрещён: пользователь заблокирован администратором'}
```

* `Parse JWT Token`: `sub` обязателен; `preferred_username` должен быть ИИН `^[0-9]{12}$`, иначе `invalid_iin`
  («Сервисные/внешние аккаунты без 12-значного ИИН для системы невалидны -> 403»); `fullname = name ||
  family_name + given_name`; `has_roles = realm_access.roles` присутствует как ключ (если ключа нет — роли в БД не
  трогают; если есть, пусть пустой — **полная перезапись** ролей органа `30101`).
* `Sync User` (параметризованный SQL `$1..$10`):
  ```sql
  INSERT INTO surfk.users (keycloak_user_id, origin_user_id, iin, fullname, given_name, family_name, email, email_verified, last_login_at)
  VALUES (...) ON CONFLICT (iin) DO UPDATE SET keycloak_user_id=…, origin_user_id=…, fullname=…, …, last_login_at=now()
  RETURNING id, keycloak_user_id, iin, fullname, given_name, family_name, email, email_verified, is_active, last_login_at;
  -- token_roles: surfk.evga_roles r WHERE r.is_active AND r.code IN (jsonb_array_elements_text($9))
  -- del: DELETE FROM surfk.evga_user_roles WHERE user_id=u.id AND controlling_body_code='30101' AND role_id NOT IN token_roles
  -- ins: INSERT INTO surfk.evga_user_roles (user_id, role_id, controlling_body_code) SELECT u.id, tr.role_id, '30101' ... ON CONFLICT (user_id, role_id) DO NOTHING
  ```
  Ключевые факты: уникальность пользователя — по **ИИН**; `evga_user_roles` уникален по `(user_id, role_id)`;
  орган контроля роли — константа `'30101'`; `is_active` — флаг блокировки администратором (не из Keycloak).
* Ответ 200:
  ```json
  { "id": "12", "keycloakUserId": "uuid", "username": "<ИИН>", "email": "...", "firstName": "...", "lastName": "...",
    "fullNameRu": "...", "iin": "...", "controlling_body_code": "30101", "lastLoginAt": "...", "isActive": true,
    "isVerified": true, "controllingBodyNameKz": "...", "controllingBodyNameRu": "...",
    "roles": [ { "code": "auditor", "name_ru": "...", "name_kz": "...", "role_level": 10 } ] }
  ```
  (роли отсортированы `ORDER BY role_level DESC`).
* Старая версия `user login` (raw, неакт.) писала в `portal.users` и генерировала e-mail `'<ИИН>@gmail.com'`
  — не переносить.

### 4.4 Модель ролей в БД surfk

| Объект | Поля / сигнатура | Источник |
|---|---|---|
| `surfk.users` | `id, keycloak_user_id uuid, origin_user_id uuid, iin (unique), fullname, given_name, family_name, email, email_verified, is_active, last_login_at` | `User Login Sync`; в других воркфлоу также `full_name_ru` (`EVGA Docs: CRUD`: `u.full_name_ru as author_fullname`) — схема менялась |
| `surfk.evga_roles` | `id, code, name_ru, name_kz, description_ru, role_level, can_create_documents, can_approve_documents, can_confirm_documents, can_sign_documents, is_active` | `EVGA Docs: Roles::Get Roles`, `evga_users_with_roles` |
| `surfk.evga_user_roles` | `user_id, role_id, controlling_body_code`; PK/unique `(user_id, role_id)`; в `EVGA Additional Actions` фильтр `ur.user_iin` (есть и колонка `user_iin`) | `User Login Sync`, `Get Available Actions` |
| view `surfk.evga_users_with_roles` | `id, user_iin, user_fullname, user_position, controlling_body_code, controlling_body_id, controlling_body_name_ru, role_id, role_code, role_name_ru, role_name_kz, role_level, can_create_documents, can_approve_documents, can_confirm_documents, can_sign_documents` | `EVGA Docs: Roles::Get All User Roles`, `Appeals - Heads list` |
| `surfk.check_user_role(iin, role_code, controlling_body_code|NULL) → bool` | SQL-функция | `EVGA Docs: Roles`, `EVGA Documents Router` |
| `surfk.get_user_roles(iin)` | SQL-функция (набор ролей) | `EVGA Docs: Roles::Get User Roles` |
| Числовые `role_id`, зашитые в воркфлоу | `4, 28` → руководители КК (`get-qc-heads`), `5, 30` → эксперты КК (`get-qc-experts`), `7` → `appeal_head` (`Appeals - Heads list`), `8` → `appeal_expert` (`Appeals - Experts list`) | пары `4/28`, `5/30` — вероятно КК КВГА (`kvga_kk_head_approver`/`kvga_kk_expert`) дублируют `qc_head`/`qc_expert` |
| `surfk.employees` / `case_participants` | `case_participants(case_id, employee_id, user_iin, is_lead, assigned_at, is_active)`; роль участника в рабочей группе через `evga_users_with_roles` (`ORDER BY role_level DESC LIMIT 1`) | `EVGA: Get Case Detail` |
| `surfk.evga_doc_cma_work_group` | `member_iin, member_role_code = 'invited_specialist'` | `EVGA_ Invited Specialist` |

### 4.5 Роли Keycloak подсистемы ЭВГА (единственный полный список в коде)

`Keycloak Subsystem Access::Parse Route / Process Subsystem Access`, `SUBSYSTEM_SCOPE_CONFIG.evga`:

```js
evga: { adminRole: 'admin_evga', groupPathPrefix: '/evga', roleNamePrefix: 'surfk_', protectedRoles: ['admin_evga'],
        hiddenRoles: ['surfk_user'],
        assignableRoles: ['auditor','audit_object_signer','qc_head','qc_expert','kvga_kk_head_approver','kvga_kk_expert',
                          'approver','confirmer','kvga_confirmer','appeal_head','appeal_expert','invited_specialist',
                          'lawyer_head','lawyer','report_manager','report_manager_kvga','superuser_ga_rk','reader_ga','dsp_access'] }
```

* `Keycloak Subsystem Users V2`: `ALLOWED_USER_ROLES = ['igo_user','evga_user','ensi_user','jur_user','kk_user','mb_user']`,
  `USER_TO_ADMIN_ROLE = { evga_user: 'admin_evga', … }`; POST/DELETE требует у вызывающего `portal_admin` или
  `admin_evga`; GET `/roles/evga_user/users` — список пользователей подсистемы (`max=10000`).
  Т.е. **вход в подсистему** = realm-роль `evga_user` (в скоупе — `surfk_user`, legacy-имя), **админ подсистемы** =
  `admin_evga`, **функциональные роли** = 19 выше.
* `ROLE_CLEANUP_CONFIG`: снятие `surfk_user` или `admin_evga` удаляет все `assignableRoles` пользователя.
* Группы Keycloak (`/evga/...`) для evga **не используются** (`groupsEnabled` только у `igo`), атрибуты — тоже.
* `ib_admin` — ИБ-администратор портала (`Keycloak IB Admins`), к ЭВГА не относится.
* Проверка прав на сами эти админ-операции — через таблицы портала `portal.roles / portal.role_permissions /
  portal.permissions` (`p.code IN ('keycloak.users.search','keycloak.ib_admins.read|manage',
  'keycloak.subsystem_access.read|manage','admin.permissions.manage','admin.roles.manage','subsystems.update')`,
  `rp.conditions->'subsystemKeys' ? $3`), где `r.code = ANY(realm_access.roles)`.

Роли, которые реально проверяет процесс (BPMN `allowed_roles` в `bpmn_summary.txt`): `auditor`, `approver`
(«Согласовать»), `confirmer` («Утвердить»), `qc_head`, `qc_expert`, `appeal_expert`, `appeal_head`,
`audit_object` (объект аудита — «Подписать» возражения). Типы документов: `creator_roles @> '["auditor"]'`.

### 4.6 Endpoints пользователей/ролей (старые)

| Метод/путь | Вход | Выход | Назначение |
|---|---|---|---|
| POST `/webhook/user-login-surfk` | Bearer | профиль + `roles[]` (см. 4.3) | логин/синхронизация |
| GET `/webhook/keycloak-users?page&limit(≤100)&search&enabled&withoutMeaningfulRoles` | Bearer + право `keycloak.users.search` | `{data:[{id,username,email,firstName,lastName,fullName,enabled,emailVerified,createdTimestamp}], pagination{page,limit,total,totalPages,hasNext,hasPrev}}` (вызывающий исключён) | админ: поиск пользователей Keycloak |
| GET `/webhook/keycloak-subsystem-access/roles?subsystemKey=evga` | Bearer + `keycloak.subsystem_access.read` | `{data:[{id,name,description}]}` в порядке `assignableRoles` | список ролей ЭВГА |
| GET `/webhook/keycloak-subsystem-access/user?subsystemKey=evga&userId=` | то же | `{user, groups:[], roles:[{id,name,description}], attributes:[], hasUserRole}` (`hasUserRole` = есть `surfk_user`) | карточка доступа |
| POST/DELETE `/webhook/keycloak-subsystem-access/user-roles` `{subsystemKey,userId,roleName}` | `keycloak.subsystem_access.manage` | `{success:true}` / 403 `Role is outside subsystem scope` | назначить/снять роль |
| GET/POST/DELETE `/webhook/keycloak-subsystem-users-v2?role=evga_user[&userId]` | Bearer; POST/DELETE — `portal_admin` или `admin_evga` | GET `{data:[user…]}`; POST/DELETE `{success:true}` | доступ к подсистеме |
| GET `/webhook/qc/heads`, `/webhook/qc/experts`, `/webhook/appeals/heads`, `/webhook/appeals/experts` (`?controlling_body_code` — фильтр закомментирован) | — | `{success:true, data:[{id,user_iin,user_fullname,user_position,code,controlling_body_code,controlling_body_name}]}` | выбор исполнителей по роли |
| саб-воркфлоу `EVGA Docs: Roles` (через `EVGA Documents Router`, `action`) | `get_roles`, `get_user_roles{user_iin}`, `get_users_by_role{role_code}`, `get_all_user_roles`, `check_user_role{user_iin,role_code,controlling_body_code}` | `{success, data}` | внутренние проверки |
| GET `/webhook/evga/references/employees` | — | см. §3.1 п.19 | выбор сотрудников в рабочую группу |

### 4.7 Что уже есть в prof (`apps/accounts`) и как ложится

* `User(AbstractUser)`: `id uuid`, `auth_provider ∈ {keycloak, local}`, `full_name`, `position`, `phone`, `email`
  (уникален без учёта регистра), `department FK catalogs.Department`, `is_subject_representative`, `subject FK`.
* `FederatedIdentity(user, issuer, subject_claim, first_seen_at, last_login_at)` — unique `(issuer, subject_claim)`.
* `AuthSession` (cookie-сессия с токенами Keycloak; `SessionCookieAuthentication` продлевает access через
  `keycloak.ensure_fresh_access_token`), `OidcAuthRequest` (PKCE `state/code_verifier/nonce`).
* `services/keycloak.py`: discovery, `build_authorization_url` (scope `openid profile email`), `exchange_code_for_tokens`,
  `decode_id_token` (PyJWKClient, проверка `nonce`), `provision_user_from_claims(claims)` — ищет `FederatedIdentity`
  по `(iss, sub)`, иначе создаёт `User(username=f"kc_{sub}", auth_provider=KEYCLOAK, email, full_name=name)`.
* `Role(code, name, order, scope ∈ {national, territorial})`, `RolePermission(role, domain ∈ {semiannual, cases,
  execution}, level ∈ {none, view, edit, approve, sign, decide})`, `RoleAssignment(user, role, department, valid_from,
  valid_to)` + `RoleAssignmentQuerySet.active()`; DRF-permission `HasDomainLevel` (`view.required_domain`,
  `view.required_levels`); `IsSubjectRepresentative`.
* `seed_roles`: 14 ролей prof через `Role.objects.update_or_create(code=…)`.
* Settings: `KEYCLOAK_ISSUER`, `KEYCLOAK_CLIENT_ID (saq-backend)`, `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_REDIRECT_URI`,
  `KEYCLOAK_POST_LOGOUT_REDIRECT_URI`; URL `api/accounts/keycloak/{login,callback,logout}`, `api/accounts/me`.

Маппинг старое → prof:

| Старое (n8n/surfk/Keycloak) | prof (`accounts`) | Действие |
|---|---|---|
| `surfk.users.keycloak_user_id` (`sub`), `origin_user_id` | `FederatedIdentity.subject_claim`; `origin_user_id` → новое поле `FederatedIdentity.origin_subject` (nullable) | добавить поле |
| `surfk.users.iin` = `preferred_username` | нет → добавить `User.iin CharField(12, unique, null)`; заполнять из `preferred_username`, если `^\d{12}$` | добавить; `username` оставить `kc_{sub}` |
| `fullname/given_name/family_name/email/email_verified` | `User.full_name`, `first_name`, `last_name`, `email` | в `provision_user_from_claims` дописать `first_name/last_name` |
| `surfk.users.is_active` (блокировка админом) | `User.is_active` (уже проверяется в `SessionCookieAuthentication`) | как есть; при `is_active=False` — 403 `user_blocked` на `/me` |
| `evga_user_roles(role, controlling_body_code)` | `RoleAssignment(role, department)`; орган контроля ↔ `Department` (`is_central` = КВГА ЦА, иначе территориальное) | синхронизировать при логине (см. ниже) |
| `evga_roles.role_level`, `can_*_documents` | `Role.order` + `RolePermission(domain, level)` | seed |
| `realm_access.roles` → роли ЭВГА | в `provision_user_from_claims(claims)`: взять `roles = set(claims['realm_access']['roles']) ∩ KEYCLOAK_ROLE_MAP`, создать/закрыть `RoleAssignment` (закрывать `valid_to=now()` для отсутствующих, а не удалять — история сохраняется) | реализовать `sync_role_assignments_from_claims` |
| `evga_user` (вход в подсистему) | `User.is_active` + наличие хотя бы одного `RoleAssignment.active()` **или** отдельный флаг `has_evga_access`; проще: роль `reader` по умолчанию при `evga_user` | решение команды |
| `admin_evga`, `portal_admin` | `sysadmin` (prof: `is_staff/is_superuser` вручную) + `evga-admin` роль с домен-правами | seed |
| `audit_object_signer` / BPMN `audit_object` | `User.is_subject_representative=True` + `subject FK` + `IsSubjectRepresentative` | как в prof |
| `check_user_role(iin, role_code, cb)` | `RoleAssignment.objects.active().filter(user=…, role__code=…, department=…)` | сервис-функция |
| `evga_users_with_roles` / `qc/heads`, `appeals/heads` | `GET /api/accounts/users/?role=qc-head&department=` (фильтр по активным назначениям) | ViewSet |
| Keycloak Admin API (назначение ролей из UI) | **не переносить**: роли назначаются в Keycloak администратором; Django только читает claims. Если нужна админка в приложении — отдельный сервис с `client_credentials` и правами `manage-users` (риск) | отложить |

Замечание по scope: prof `Role.scope` (`national`/`territorial`) + `RoleAssignment.department` покрывают
`controlling_body_code`: КВГА ЦА (`30101`) — `national`, территориальные департаменты — `territorial`.

### 4.8 Предлагаемый список ролей ЭВГА для `seed_roles` (accounts)

Соглашение: `Role.code` в kebab-case, как в prof (`ca-specialist`) и во фронте (`appeal-head`); коды Keycloak —
snake_case как есть; маппинг хранить в `settings.KEYCLOAK_ROLE_MAP`.

| Django `Role.code` | Keycloak realm-роль | Фронт `Role` (`types.ts`) / аккаунт | BPMN `allowed_roles` | Название | scope |
|---|---|---|---|---|---|
| `auditor` | `auditor` | `auditor` (`auditor`, `coauthor`, участники РГ) | `auditor` | Аудитор (член рабочей группы) | territorial |
| `reviewer` | `approver` | `reviewer` («Согласующий 1/2») | `approver` («Согласовать») | Согласующее лицо | territorial |
| `approver` | `confirmer` | `approver` («Утверждающий», `quality-head`, `commission-chair`) | `confirmer` («Утвердить») | Утверждающее лицо | territorial |
| `qc-expert` | `qc_expert` | `quality` | `qc_expert` | Эксперт контроля качества | national |
| `qc-head` | `qc_head` | аккаунт `quality-head` (сейчас `role: "approver"`) | `qc_head` | Руководитель контроля качества | national |
| `kvga-confirmer` | `kvga_confirmer` | `kvga` | — (`requires_kvga_confirmation`) | Подтверждение КВГА | national |
| `kvga-kk-head` | `kvga_kk_head_approver` | (нет; часть `kvga`) | — | Руководитель КК КВГА | national |
| `kvga-kk-expert` | `kvga_kk_expert` | (нет) | — | Эксперт КК КВГА | national |
| `reestr-confirmer` | ? (`report_manager` / `report_manager_kvga` — не подтверждено) | `reestr-confirmer` | — | Подтверждение реестра | national |
| `invited-specialist` | `invited_specialist` | `invited-specialist` | — (`member_role_code`) | Приглашённый специалист | territorial |
| `object` | `audit_object_signer` | `object` | `audit_object` | Представитель объекта аудита (внешний) | — (`is_subject_representative`) |
| `appeal-head` | `appeal_head` | `appeal-head` | `appeal_head` | Руководитель управления апелляции | national |
| `appeal-expert` | `appeal_expert` | `appeal-expert` | `appeal_expert` | Сотрудник управления апелляции | national |
| `appeal-commission-chair` | (нет в старой) | `commission-chair` (`approver`, `area: appeal`) | — | Председатель апелляционной комиссии | national |
| `appeal-commission-member` | (нет) | `commission-1/2` (`reviewer`, `area: appeal`) | — | Член апелляционной комиссии | national |
| `lawyer-head`, `lawyer` | `lawyer_head`, `lawyer` | (нет) | — | Юридическая служба | national |
| `report-manager`, `report-manager-kvga` | `report_manager`, `report_manager_kvga` | (нет) | — | Отчётность | national |
| `superuser-ga` | `superuser_ga_rk` | (нет) | — | Суперпользователь ГА РК | national |
| `observer` | `reader_ga` | (нет) | — | Наблюдатель (только чтение) — есть в prof | national |
| `evga-admin` | `admin_evga` (+`portal_admin`) | (нет) | — | Администратор ЭВГА | national |
| *permission-флаг, не роль* | `dsp_access` | — | — | доступ к ДСП-делам (`cases.is_dsp`) → `RolePermission`-домен `dsp` или булево поле `User.has_dsp_access` | — |

Домены прав (`PermissionDomain`) для ЭВГА предлагается расширить: `cases` (дела/документы), `quality`
(контроль качества), `appeals`, `registry` (реестр/КВГА), `admin`, `dsp`; уровни оставить prof-овские
(`view/edit/approve/sign/decide`). Так `HasDomainLevel` переиспользуется без изменений.

---

## 5. Уведомления

### 5.1 Таблицы

| Таблица | Поля (по SQL) | Кем используется |
|---|---|---|
| `portal.notifications` (актуальная) | `id uuid, user_id int → portal.users.id, title varchar, message text, event_type varchar, notification_type varchar, meta_data jsonb, status varchar ('UNREAD'|'READ'), channel varchar ('WEB'), created_by_id int, created_at, read_at, deleted_at` | `create notification by recipients` (INSERT … `'UNREAD','WEB',NOW()`), `get unread notification`, `Mark notification as read`, `notifications/mark-all-read` |
| `notifications.web_notifications` (legacy, jsonb) | `id, account_id, created_time, updated_time, object_data jsonb {username, status, eventType, userId, payload{title, message, metaData}}` | `update_notification_status` (PATCH), `get_notification_data`, `get_notification` (неакт.) |
| `surfk.evga_audit_object_notifications`, `surfk.oa_notifications`, `surfk.get_notification_by_document(caseId, documentId)`, `surfk.evga_doc_notification_vap_rk` | связь `case_document_id`; `oa/acknowledge` (ознакомление ОА с документом с подписью), `oa/notification/:caseId/:documentId`; `notification_vap_rk(recipient_bin, recipient_name_ru/kz, outgoing_doc_number, outgoing_doc_date, material_description)` | это **«уведомление объекту аудита»/«уведомление в ВАП РК» как документы**, домен documents, не in-app уведомления |

### 5.2 Типы и получатели

* `eventType` (default `'FREE_TEXT_NOTIFICATION_EVENT'`), `notificationType` (`'INFO'` default, `'SUCCESS'` в тестах;
  других значений в коде нет), `metaData` — произвольный JSON.
* Получатели: **e-mail адреса** (`recipients` — массив или CSV; если не передано — отправитель сам себе);
  адрес → `portal.users.email_bi` через blind-index (`lookup-hash`, normalize `ci`) в крипто-сервисе
  (`{CRYPTO_SERVICE_URL}/api/v1/crypto/lookup-hash`, header-cred `APP_CRYPTO_INTERNAL_TOKEN`) — потому что
  «плейнтекст email удалён миграцией V20260824150000». Пользователь не найден → `throw 'No users found for provided emails'`.
* Отправитель = `sub` из токена (`senderId`, `senderEmail`, `senderName = preferred_username`).
* Канал: `channel='WEB'` + realtime push узлом `CUSTOM.notificationService` (`apiUrl: {APP_BASE_URL}/api/notifications/notifications`,
  `bearerToken`, `title`, `message`, `recipients`, `notificationType`) — внешний Node/WS-сервис портала. Email/SMS/push
  на телефон — **нет нигде**.
* В `Worktime` заявка «Уведомление руководителю не создаётся: это действующий контракт ручки» (и в `Precheck`
  явно воспроизводится ошибка `null value in column "user_id" of relation "notifications"`), т.е. серверные
  уведомления из бизнес-процессов в старой системе практически не генерировались; в EVGA-воркфлоу
  `send-notification-with-recipients` не вызывается ни разу (grep по `all_workflows_raw.json`).

### 5.3 API (старое)

| Метод/путь | Вход | Выход |
|---|---|---|
| POST `/webhook/send-notification-with-recipients` | Bearer; body `{title*, message*, recipients?: string[]|"a@b,c@d", notificationType?, eventType?, metaData?}` | `{success:true, totalSent, sender, notifications:[{id,userId,title,message,status,createdAt}]}` |
| GET `/webhook/notifications/unread?page=1&limit=20(≤100)` | Bearer (пользователь должен быть в `portal.users`, иначе 404 `{error:'Unauthorized', message:'User not found'}`) | `{data:[{id, accountId, createdBy, createdTime, updatedTime, objectData:{eventType, status, userId, payload:{title,message,metaData}}}], pagination{page,limit,total,totalPages,hasNext,hasPrev}, unreadCount}` (формат «как у WebSocket») |
| PUT `/webhook/:id/mark-read` | Bearer | `{success:true, notification:{id,status,readAt}}`; чужое → 403 `You can only mark your own notifications as read`; несуществующее → пустой 200 |
| PUT `/webhook/notifications/mark-all-read` | Bearer | `{success:true, message:'Marked N notification(s) as read', markedCount}` |
| PATCH `/webhook/update_status?id=` | JWT decode | legacy `UPDATE notifications.web_notifications SET object_data = jsonb_set(object_data,'{status}','"READ"') WHERE … status='UNREAD'` |
| GET `/webhook/notifications_by_id?start_date&end_date` (`DD.MM.YYYY HH24:MI:SS`) | JWT decode | legacy выборка по `username` |

### 5.4 Фронт `saq-evga-test`

`AuditCase.notifications?: {id, at, documentId, text, recipients: string[] (account ids), readBy: string[]}[]`
(`types.ts:233`); создаются в бизнес-функциях (`appeals.ts::change` — всем `area==='appeal'`, авторам дела,
`approver`, `object`; `assignAppeal` — исполнителю), отображаются в `components/Notifications.tsx` (таблица
Дата/Дело/Уведомление/Состояние «Прочитано|Новое», кнопка «Открыть» → `/cases/{id}/documents/{docId}` или
`/cases/{id}/general`, при этом `readBy += account.id`). Т.е. фронт ожидает: адресность по пользователю, привязку к
делу и документу, статус прочтения на получателя, deep-link.

### 5.5 Предложение: `apps/notifications` (Django)

```python
class NotificationEventType(models.TextChoices):
    FREE_TEXT = "free_text", "Произвольное"
    DOCUMENT_ASSIGNED = "document_assigned", "Назначен документ/задача"
    DOCUMENT_STATUS = "document_status", "Изменение статуса документа"
    CASE_STATUS = "case_status", "Изменение статуса дела"
    APPEAL = "appeal", "Апелляция"
    DEADLINE = "deadline", "Срок"

class NotificationLevel(models.TextChoices):   # старое notification_type
    INFO = "info"; SUCCESS = "success"; WARNING = "warning"; ERROR = "error"

class Notification(TimeStampedModel):           # core.TimeStampedModel: id uuid, created_at, updated_at, created_by
    recipient = FK(User, related_name="notifications")
    title = CharField(255); message = TextField(blank=True)
    event_type = CharField(choices=NotificationEventType); level = CharField(choices=NotificationLevel, default=INFO)
    case = FK("cases.AuditCase", null=True)      # для фильтра «уведомления по делу»
    content_type/object_id/content_object        # GenericFK на документ/апелляцию (deep-link), как у core.Attachment
    meta = JSONField(default=dict)
    channel = CharField(choices=[("web","В приложении"),("email","E-mail")], default="web")
    read_at = DateTimeField(null=True)            # status = read_at is not None
    deleted_at = DateTimeField(null=True)
```

Сервис `notifications.services.notify(recipients: Iterable[User], *, title, message, event_type, case=None,
target=None, meta=None)` — вызывается из сервис-слоя переходов (`documents`, `appeals`, `cases`), а не из API.
API (DRF, `SessionCookieAuthentication`): `GET /api/notifications/?unread=true&page=` (только свои),
`GET /api/notifications/unread-count/`, `POST /api/notifications/{id}/read/`, `POST /api/notifications/read-all/`.
Ответ — DRF-пагинация, поля `id, title, message, event_type, level, case{id,number}, target{type,id,url}, created_at, read_at`.
Realtime: не переносить `CUSTOM.notificationService`; на первом этапе — polling `unread-count`; позже Django Channels.
E-mail: `channel='email'` + Celery-таска (в prof Celery уже есть? — уточнить; если нет, `send_mail` синхронно из
management-команды/сигнала). Получателей выбирать по `RoleAssignment`/участникам дела, **не по e-mail-строкам**.

---

## 6. Журнал активности / аудита

### 6.1 `surfk.evga_audit_log` — `Log Activity` (`POST /webhook/activity-log`, active)

Вход (body): `action_type*`, `action_description_ru*`, `entity_type` (`'case'` | `'case_document'` | другое),
`entity_id`, `metadata` (JSON), `performed_by_iin`, `performed_by_name`. Валидация → 400
`{success:false, message, error:'MISSING_ACTION_TYPE'|'MISSING_DESCRIPTION'}`.

```sql
INSERT INTO surfk.evga_audit_log (entity_type, entity_id, case_id, action_code, action_name_ru, metadata,
                                  performed_by_iin, performed_by_name, source, created_at)
VALUES (…, CASE WHEN entity_type='case' THEN entity_id
                WHEN entity_type='case_document' THEN (SELECT case_id FROM surfk.evga_case_documents WHERE id = entity_id)
                ELSE NULL END, …, 'user', CURRENT_TIMESTAMP) RETURNING id
```

Ответ 201 `{success:true, message:'Activity logged successfully', id}`. Пример вызова из
`Appeals - Assign Expert`: `{action_type:'approve', action_description_ru:'Утверждено назначение эксперта апелляции: <ФИО>',
entity_type:'case', entity_id, performed_by_iin, performed_by_name, metadata:{appeal_expert_iin, appeal_expert_fullname}}`.
В ту же таблицу пишет `EVGA: Document History Record` (документный домен, 4 обращения; `source` там, вероятно, `'system'`).
Читалки `evga_audit_log` в экспорте **нет**.

### 6.2 `surfk.activity_log` — `get logs` (`GET /webhook/activity-log`, неактивен)

Другая таблица с полями `id, feature, action_type, action_description_ru, action_description_kz, entity_id,
entity_type, metadata, performed_by_keycloak_id, performed_by_name, ip_address, performed_at`; фильтры
`feature, entity_id, entity_type, action_type, performed_by (keycloak id), date_from, date_to, limit(50), offset`;
ответ `{success:true, data:[…], count}`. Это более ранняя схема (есть `feature`, `ip_address`, `_kz`) — полезна как
список желаемых полей.

### 6.3 `surfk.case_status_history` — `EVGA Case Workflow Log (Zeebe → PostgreSQL)` (`POST /webhook/evga/case-workflow-log`)

Вход от Zeebe: `caseId*, actionCode*, performedByIin ('system'), performedByFullname ('Zeebe System'), comment,
documentId, processInstanceId`. Пользователь ищется `SELECT id FROM public.users WHERE iin = …` (**другая схема**,
fallback `changedByUserId = 1`!). Запись: `(case_id, old_status_id = c.status_id, new_status_id = c.status_id,
changed_by, comment, changed_at)` — т.е. **статус фактически не меняется**, а `actionCode/documentId/processInstanceId`
в таблицу не попадают (теряются). Ответ `{success:true, data:{caseId, actionCode, documentId, changedByUserId, historyId, message}}`.

### 6.4 `surfk.evga_document_workflow_history`

Пишется внутри SQL действий над документами (`EVGA - Appeal Result`, `EVGA_ Invited Specialist`, `Docs: CRUD/KVGA`):
`(case_document_id, action_code, action_name_ru, from_status_id, to_status_id, performed_by_iin, performed_by_fullname,
created_at[, comment])`. Коды действий из области апелляций: `sign/'Подписать'`, `send_to_confirmation/'Отправить на
утверждение'`, `confirm/'Утвердить'`, `return_for_revision/'Вернуть на доработку'`, `change_confirmer/'Сменить
утверждающего'`, `activate/'Активировать'`, `send_to_invited_specialists`, `sign_invited_specialist`.

### 6.5 ИБ-лог в RabbitMQ (`Rabbit MQ logger`, id `kcQrkRUekjdmnkOg`, инлайнится в портальные воркфлоу)

Входы: `serviceName, action, userId, authHeader, username, ip, entityType, entityId, description, operationStartTime,
operationEndTime, success, logFormat ('json'|text), eventType, objectId, objectName, resource, eventTime`.
Текстовый формат: `dd.LL.yyyy / HH:mm:ss | service | username (efc_user_id=<sub>, idp_user_id=<origin_user_id>) | ip |
start=… | end=… | OK/FAILED | ACTION [entityType#id]: description`; JSON (`schemaVersion: 1`):
`{eventTime, eventType, outcome: SUCCESS|FAILURE, service, action, subject{username, efcUserId, idpUserId},
object{type,id,name,resource}, source{ip}, operation{startTime,endTime}, description}`. TZ `Asia/Almaty`.
`eventType` значения: `DATA_ACCESS`, `DATA_CHANGE`, `AUTH_FAILURE`, `ACCESS_DENIED`, `VALIDATION_ERROR`,
`PERMISSION_GRANT`, `PERMISSION_REVOKE`. Очередь `$vars.RABBITMQ_LOG_QUEUE`, cred `RabbitMQ account`, `durable: true`.
`ip` = первый из `x-forwarded-for` или `x-real-ip`. Примеры `action`: `LIST_KEYCLOAK_USERS`, `ASSIGN_IB_ADMIN`,
`GRANT_SUBSYSTEM_ACCESS`, `SEND_NOTIFICATION`, `MARK_ALL_NOTIFICATIONS_READ`, `CREATE_TIME_REQUEST`, `GET_PROFILE`.

### 6.6 Фронт

`HistoryEntry {id, at, actor (ФИО), action, comment}` (`history.ts::log`); хранится в `AuditCase.history[]` и
`DocumentVersion.history[]`.

### 6.7 Соответствие prof `core.AuditEvent` и что расширить

prof: `AuditEvent(content_type/object_id GFK, action ∈ {create, approve, sign, send, acknowledge, decide, exchange},
status_from, status_to, actor FK, actor_role, occurred_at, reason, attachment FK, exchange_id)`, append-only
(`save()` запрещает обновление, `AuditEventQuerySet.update/delete` бросают), индекс `(content_type, object_id, occurred_at)`.

| Потребность ЭВГА (из старых логов) | Есть в `AuditEvent` | Предложение |
|---|---|---|
| Код действия из набора ~25 (`assign_qc_expert_appeal`, `return_for_revision`, `send_to_invited_specialists`, `activate`, …) | `action` — 7 choices | расширить `AuditAction` (добавить `assign, return, confirm, activate, reject, submit, objection, appeal_assign, appeal_admission, delete, restore`) **и** добавить `action_code CharField(64)` (точный код перехода из state-machine) + `action_name_ru` для отображения без справочника |
| Привязка к делу для журнала дела (старое `case_id` денормализовано) | нет (только GFK на объект) | `case = FK("cases.AuditCase", null=True, db_index=True)` — заполнять для событий по документам/апелляциям |
| `metadata jsonb` | `reason` (text), `exchange_id` | `metadata = JSONField(default=dict)` |
| `performed_by_iin/name` для системных/внешних субъектов (Zeebe, объект аудита) | `actor` FK + `actor_role` (`'system'`) | добавить `actor_name CharField` (снимок ФИО) и `actor_iin CharField(12, blank)`; `actor` nullable уже есть |
| `source` (`user`/`system`/`zeebe`) | `actor_role='system'` | добавить `source CharField(choices)`; вместо zeebe — `'workflow'` |
| `ip_address`, `user_agent` (ИБ) | нет | добавить `ip_address GenericIPAddressField(null)`; писать из middleware/сервиса |
| Переходы статуса документа (`from/to`) | `status_from/status_to` | как есть |
| Чтение журнала | — | `GET /api/audit-events/?case=&object_type=&object_id=&action=&actor=&date_from=&date_to=` (`HasDomainLevel` view) |
| ИБ-события (AUTH_FAILURE, ACCESS_DENIED, DATA_ACCESS) | нет | отдельная модель `core.SecurityEvent(event_type, outcome, subject_sub, subject_iin, username, ip, resource, description, occurred_at)` + запись из `SessionCookieAuthentication`/permission-denied handler; RabbitMQ **не** переносить (при необходимости — экспорт в SIEM отдельной командой) |

`case_status_history` как отдельная сущность не нужна — это `AuditEvent` с `content_object = AuditCase`.

---

## 7. Апелляции / возражения

### 7.1 Старый процесс (n8n + BPMN)

1. После вручения аудиторского отчёта объекту аудита создаётся документ возражений `M20-VOZ` (BPMN
   `evga_doc_51 "EVGA Doc 51: Возражения"`: ожидание «Подписан» ОА, действия `save`/`signed` с `allowed_roles:
   ["audit_object"]`; таймер `=now() + duration("P10D")` → «Срок возражений истёк»). Подача возражений
   (`Submit Objection Query`) переводит родительский документ в `signed_with_objection` и стартует
   Zeebe-процесс; BPMN дальше шлёт `action_code: "ready_send_to_appeal"`.
2. **Список дел на апелляции** — `GET /webhook/appeals/cases`: дела, у которых есть недоудалённый `M20-VOZ` в
   статусе `active|signed|completed`; фильтры `search` (`registration_number`, `ao.name_ru`, `ao.bin`),
   `status_id`, `controlling_body_code`, `appeal_expert_iin` (через актуальное назначение — последняя запись
   `assigned` без более поздней `unassigned`), `appeal_head_iin` (принимается, но **не применяется**); ответ
   `{success, data:[c.* + status_name, controlling_body_name/code, audit_object_name/bin], pagination{page,limit,total,totalPages,hasNext,hasPrev}, filters}`.
3. **Назначение эксперта** — `POST /webhook/assign-appeal-expert/cases/:caseId/assign-appeal-expert`
   body `{user_iin, user_name, user_keycloak_id, comment, appeal_expert_iin, appeal_expert_fullname}`:
   * если уже назначен тот же эксперт → 400 `{success:false, error:'Данный эксперт апелляции уже назначен на это дело', data{…}}`;
   * иначе одним SQL: `UPDATE surfk.case_appeal_expert_assignments SET action='unassigned', updated_at=NOW() WHERE case_id=… AND action='assigned'`
     + `INSERT (case_id, appeal_expert_iin, appeal_expert_fullname, assigned_by_iin, assigned_by_fullname, action='assigned', comment)`;
   * `POST {N8N_WEBHOOK_BASE_URL}/webhook/evga/zeebe {action:'publish_case_message', params:{case_id, action_code:'assign_qc_expert_appeal', performedByIin}}`
     (имя сообщения переиспользовано от КК);
   * `POST …/webhook/activity-log` (`action_type:'approve'`, см. §6.1);
   * ответ `{success:true, data:{case_id, appeal_expert_iin, appeal_expert_fullname, message:'Эксперт апелляции назначен'}}`.
   Проверки роли вызывающего (руководитель апелляции) **нет**.
4. **Списки людей**: `GET /webhook/appeals/heads` (`role_id = 7`), `GET /webhook/appeals/experts` (`role_id = 8`).
5. **Результат рассмотрения возражений `M23-RVO`** — `POST /webhook/evga/appeal-result` `{action, params}`:

   | `action` | SQL / эффект | Ответ |
   |---|---|---|
   | `get` | `evga_case_documents` ⨝ `evga_document_statuses` ⨝ `evga_doc_objection_appeal_result ar (review_date, review_result, decision_text)` + `violations[]` из `evga_doc_oar_violations (id, ao_violation_id, sequence_number, risk_object_type, risk_object_name, violation_type, violation_amount, violation_status, cancelled_amount, final_amount, note)` + `attachments[]` из `evga_document_attachments (file_id, file_name, description)`; `document_type_name = {ru:'Результаты возражения', kz:'Қарсылық нәтижелері'}` | `{success, data}` |
   | `update` | upsert `evga_doc_objection_appeal_result(case_document_id)`; `SET review_date, review_result, decision_text` из `params.fields` | `{success:true, message:'Document updated successfully'}` |
   | `sign` | `INSERT evga_document_signatures (…, signature_type='sign')` если `params.signature` непустая; статус → `signed`; history `sign` | `{document_id, new_status:'signed'}` |
   | `send_to_confirmation` | статус → `pending_confirmation`, `confirmer_iin = params.confirmer_iin`; history | `new_status:'pending_confirmation'` |
   | `confirm` | подпись `signature_type='confirm'`; статус → `confirmed`; history | `new_status:'confirmed'` |
   | `return_for_revision` | статус → `revision`; history с `comment` | `new_status:'revision'` |
   | `change_confirmer` | `confirmer_iin` без смены статуса; history | `new_status: <текущий>` |
   | `activate` | статус → `active`; history | `new_status:'active'` |
   | `get_actions` | `evga_status_transitions` для текущего статуса и типа документа, `is_automatic=false` | `{data:{actions:[{action_code, action_name_ru/kz, requires_signature, requires_comment, required_role_code, is_automatic}]}}` |
   | иное | | `{success:false, error:'Unknown action: …'}` |

   BPMN `evga_doc_objection_results` («Результаты возражения к аудиторскому отчету (2.7)») и
   `evga_doc_rezultat_vozrazhenii`: `draft` — `save`/`send_to_confirmation` (`appeal_expert`); `pending_confirmation` —
   `confirm` (подпись), `return` (комментарий) — `appeal_head`; `change_confirmer` — `appeal_expert`; `revision` —
   `save`/`resubmit` (`appeal_expert`). Роли-исполнители: `appeal_expert` готовит, `appeal_head` утверждает.
   Комиссии/председателя, «принято/отказано в рассмотрении», обоснований аудитора в старой системе **нет**.
6. Также `violations` считает `objection_amount = obj.cancelled_amount` из последнего `M23-RVO` по
   `oo.violation_reference = v.id::text` — т.е. результат возражений уменьшает сумму нарушения в реестре.

### 7.2 Фронт `appeals.ts` (модель, которую надо обслужить)

`Appeal {objectionId, version, receivedAt, expertId?, admission?{decision:'Принято к рассмотрению'|'Отказ в
рассмотрении', at, by, reason, files[], notifiedAt?}, arguments?{rows:[{violationId, textRu, textKz, files[]}], at, by,
submittedAt?, signedAt?, signedBy?, comment?}}`; функции:

| Функция | Кто | Правило |
|---|---|---|
| `getAppeal(audit)` | — | апелляция существует, если есть документ `kind==='objections'` в статусе «Активный»; `receivedAt` = последняя подпись |
| `assignAppeal(audit, actor, expertId)` | `appeal-head` | эксперт — аккаунт с ролью `appeal-expert`; нельзя при `admission.decision==='Отказ в рассмотрении'`; нельзя, пока `objection-result` не в «Проект»/«Возвращен на доработку»; при возвращённом документе — переназначение владельца версии (`reassignReturnedDocument`) + уведомление исполнителю |
| `recordAdmission(audit, actor, decision, reason, files)` | `commission-chair` | однократно; требует основание и файл; только пока результат не направлен |
| `notifyAdmission(audit, actor, files)` | `appeal-head` или назначенный эксперт | фиксирует `notifiedAt` и файлы направления решения объекту |
| `saveAppealArguments(audit, actor, rows, submit)` | аудитор дела (`canAuthorCase`) | при `submit` — по каждому оспоренному пункту (`violations` из версии возражений) ровно одна строка, оба языка, ≥1 файл |
| `decideArguments(audit, actor, approve, comment)` | `approver` | подпись руководителя аудитора или возврат с замечанием |
| `appealSubmissionBlock(audit)` | — | документ результата нельзя направить, пока: нет исполнителя → нет решения «Принято» → обоснования не подписаны |
| `appealFilingDue(audit)` | — | срок подачи возражений = `addWorkingDays(delivery.sentAt, 10, calendar)` (старый BPMN: календарных `P10D`) |

Уведомления при каждом действии — получателям `area==='appeal'`, авторам дела, `approver`, `object`.

### 7.3 Соответствие

| Старое | Фронт | Django (предложение) |
|---|---|---|
| `case_appeal_expert_assignments` (история assigned/unassigned) | `Appeal.expertId` | `AppealExpertAssignment(appeal FK, expert FK User, assigned_by FK, comment, assigned_at, unassigned_at null)` — история сохраняется; актуальный = `unassigned_at IS NULL` |
| фильтр дел с активным `M20-VOZ` | `getAppeal()` по документу `objections` | `Appeal(case FK, objection_document FK documents.Document, objection_version int, received_at, filing_due_date)` создаётся сервисом при подписании объектом возражений |
| — | `admission` | `AppealAdmission(appeal 1:1, decision ∈ {accepted, refused}, decided_by, decided_at, reason, notified_at)` + `core.Attachment(kind='decision_attachment')` |
| — | `arguments` | `AppealArgument(appeal FK, violation FK, text_ru, text_kk)` + `Attachment(kind='audit_evidence')`; агрегат `AppealArgumentSet(appeal 1:1, submitted_at, signed_at, signed_by, return_comment)` |
| `M23-RVO` + `evga_doc_objection_appeal_result` + `evga_doc_oar_violations` | документ `objection-result` | документ типа `objection_result` в `documents` с формой `{review_date, review_result, decision_text, rows:[{violation, status, cancelled_amount, final_amount, note}]}`; переходы — общая state-machine документов |
| `appeals/heads`, `appeals/experts` | `accounts.filter(role==='appeal-expert')` | `GET /api/accounts/users/?role=appeal-expert` |
| `assign_qc_expert_appeal` (Zeebe message) | — | вызов сервиса `appeals.services.assign_expert()` → `AuditEvent(action='assign', action_code='appeal_assign_expert')` + `notify()` |
| `activity-log 'approve'` | `history.push(log(...))` | `AuditEvent` |
| таймер `P10D` | `appealFilingDue` (10 раб. дней) | поле `filing_due_date` + Celery-beat/management-команда «истёк срок возражений» (в prof аналог — `execution` дедлайны) |

API: `GET /api/appeals/?expert=&status=&search=`, `GET /api/cases/{id}/appeal/`, `POST …/appeal/assign-expert/`,
`POST …/appeal/admission/`, `POST …/appeal/admission/notify/`, `PUT …/appeal/arguments/`, `POST …/appeal/arguments/submit/`,
`POST …/appeal/arguments/decide/`. Права: `HasDomainLevel(domain='appeals', levels=[edit|decide|sign])`.

---

## 8. Прочее

### 8.1 Worktime (`Worktime - *`, 10 воркфлоу, active)

Портальный модуль заявок на отсутствие: `portal.time_requests (employee_id, department_id, absence_date, time_from,
time_to, reason, comment, status 'MANAGER_APPROVAL'→…, manager_id, director_id, rejection_comment)`,
`portal.time_request_status_history (request_id, status, changed_by)`; endpoints `POST worktime/requests`,
`PATCH worktime/requests/:id/{cancel, manager/approve, manager/reject, director/approve, director/reject}`,
`GET worktime/requests/{my, manager, director}`, `GET worktime/journal`. ФИО хранятся зашифрованными
(`full_name_ru_enc`) и расшифровываются через крипто-сервис. **Вердикт: не относится к ЭВГА — drop.**

### 8.2 `EVGA Info Request API (deprecated)` (`POST /webhook/evga/info-request`)

Возвращает `{success:false, error:'This endpoint is deprecated. InfoRequest now uses the universal Zeebe workflow.'}`
с комментарием: «deprecated as of migration 122. InfoRequest (type_id=10) now uses the universal DynamicForm
pattern with Zeebe BPMN. All status transitions are handled by evga/workflow-update. Item-level operations
(questions) go through the standard document update API». **Вердикт: drop**; запросы информации — это документ
типа `InfoRequest` в домене documents (фронт: `informationRequests.ts`).

### 8.3 ГБД ЮЛ (`Service GDBJL surfk` / `Service GDBJL` / `gbdul_test`)

* Вход: `POST /webhook/findJurByBin` (или `jur/findJurByBin`) `{bin}`; SOAP-запрос `ulws:getJurInfoByBin`
  (`BIN`, `SystemInfo{MessageId, ChainId, MessageDate, MessageType:'request', Operator:'ecc', ConId:'test'}`) на
  `{GBD_JL_SOAP_BASE_URL}/XISOAPAdapter/MessageServlet?…interface=SI_GBD_JL_PIWS_OS&interfaceNamespace=http://minfin.kz/GBD_JL_SHEP`
  (прод `http://prodpi1.emf.minfin.kz:50000`, тест `tstpi…:57000`), basic-auth cred `JUR`, `Content-Type: text/xml`.
* Новый вариант (`jur/findJurByBinNew`): `POST https://pi-bus-test.minfin.gov.kz/camel-gateway/api/out-integrations/gbdul`
  `{bin}` с заголовком `X-API-TOKEN` (токен зашит в воркфлоу!), ответ JSON `Organization{BIN, RegStatus{Code,NameRu},
  RegistrationDate, FullNameRu/Kz, ShortNameRu/Kz, OrgForm{Code,NameRu}, FormOfLaw{NameRu}, AddInfo{PropertyType,
  CommerceOrg, EnterpriseSubj}, OrganizationLeader{Country, IIN, FullName}, JurAddress/Address{…}}`; есть и
  `…/out-integrations/gbdfl` (ФЛ по ИИН).
* Нормализованный ответ (`Map to JSON`):
  ```json
  { "bin", "regStatus", "regStatusCode", "regDate", "fullName": {"ru","kz"}, "shortName": {"ru","kz"},
    "orgForm", "orgFormCode", "FormOfLaw", "ownership", "commerceOrg", "enterpriseSubj",
    "head": {"country","iin","fullName"},
    "address": {"country","countryKz","region","regionKz","district","districtKz","city","street","house"},
    "activityKinds", "founders": ["..."] }
  ```
* **Вердикт: adapt** — сервис `integrations/gbdul.py` (`get_legal_entity_by_bin(bin) -> LegalEntityInfo`) с
  кэшем результата в БД (как prof `subjects` хранит карточку субъекта), секреты в settings/env, таймауты, запись
  `AuditEvent(action='exchange', exchange_id=MessageId)`. Endpoint `GET /api/subjects/lookup/?bin=` для формы
  создания дела; выбор транспорта (SOAP/REST-шлюз) — конфигурацией.

### 8.4 ЭЦП / подписи

Подписи в старой системе — поле `signature` (text) в `surfk.evga_document_signatures (case_document_id, signature,
signer_iin, signer_name, signature_type ∈ {sign, confirm, invited_specialist_pending, invited_specialist_signed,
work_group_pending, work_group_signed}, signed_at, created_at)`; при ознакомлении ОА — `signature_data` в
`oa/acknowledge`. Ни в одном воркфлоу нет проверки CMS/сертификата, подпись просто сохраняется (`WHERE
'{{signature}}' != ''`). Публичная проверка документа — `EVGA Document Verify (Public)` (домен documents).
**Вердикт**: хранить подпись в `documents.DocumentSignature` (аналог), проверку CMS (NCALayer) вынести в
отдельный сервис позже; в state-machine — флаг `requires_signature` как в `evga_status_transitions`.

### 8.5 Крипто-сервис портала

`{CRYPTO_SERVICE_URL}/api/v1/crypto/{encrypt|decrypt|lookup-hash}` (`field`, `values[]`, `normalize:'ci'`, батчи по
500, envelope `enc:v1:`), header-cred `APP_CRYPTO_INTERNAL_TOKEN`; в `portal.users` ПДн лежат как `*_enc` + blind
index `*_bi`. К ЭВГА (`surfk.users` — открытые ФИО/ИИН/e-mail) не применялось. **Вердикт: не переносить**;
если ИБ потребует — шифрование на уровне поля Django (`django-fernet-fields`/pgcrypto) отдельной задачей.

### 8.6 Мелочи

* `My workflow 31` — `POST /webhook/evga-case-status/update {case_id, status_id}` прямой UPDATE статуса дела без
  истории → drop (переходы дела только через сервис + `AuditEvent`).
* `EVGA Check Audit Type (Planned/Unplanned)` — `POST /webhook/evga/check-audit-type {caseId}` →
  `{success, isPlanned, auditTypeCode, auditTypeName, caseId}`; в Django — `AuditCase.is_planned` через
  `InspectionType.is_planned`.
* `Get Password Policy` — парсинг `passwordPolicy` realm’а (`length(8) and upperCase(1)…`) → для ЭВГА не нужно
  (пароли только у `auth_provider=local`, политика — prof-валидаторы Django).

---

## 9. Общие технические паттерны старой системы и что НЕ переносить

| Паттерн | Где | Вердикт |
|---|---|---|
| Ответ `{success: true, data, total, limit, offset, lang}` / `{success:false, error, code}`; списки — `data[] + pagination{page,limit,total,totalPages,hasNext,hasPrev}` | все EVGA-воркфлоу | **не переносить**: prof использует DRF-пагинацию `{count,next,previous,results}` и стандартные HTTP-коды/`{detail}` ошибок; фронту нужен адаптер |
| Портальные ответы `{data, pagination}` без `success`, ошибки `{error, message, statusCode}` | Keycloak/notifications | не переносить |
| `lang` в query → выбор `name_ru/name_kz` в SQL (`CASE WHEN '{{lang}}'='kk'`) | справочники, списки | заменить на `Accept-Language` + сериализатор, отдавая оба поля `name_ru/name_kk` всегда |
| Интерполяция `{{ $json.x }}` в SQL, `escapeSql` только для `'` | почти везде | SQL-инъекции — ORM/параметры |
| Идентичность пользователя из body (`user_iin`, `performed_by_iin`, `user_keycloak_id`) | Appeals, Log Activity, Appeal Result, Invited Specialist | только `request.user` |
| JWT decode без проверки подписи; guard срабатывает только при наличии заголовка | §4.2 | `SessionCookieAuthentication` prof (cookie-сессия + refresh) — единственный механизм |
| Кэш `Cache-Control: public, max-age=3600` на справочниках | Reference-Get | `private`/ETag |
| Дубли активных/неактивных воркфлоу с одинаковым path (`Employees`, `Audit Type`, `Check Initiator`, `Response Measure`, `Audit Result`, `Audit Questions`) | references | брать за истину активную копию (они идентичны по SQL) |
| PostgREST | упомянут только в названии архивного воркфлоу; в EVGA-воркфлоу — прямой SQL узлом `n8n-nodes-base.postgres` (cred `portal_db`) | не переносить |
| `CUSTOM.keycloak` (Admin API через сервисный аккаунт), `CUSTOM.notificationService` (WS-push) | Keycloak/notifications | не переносить; Django читает роли из claims |
| RabbitMQ ИБ-лог, инлайн саб-воркфлоу | портал | не переносить; `SecurityEvent` в БД |
| Zeebe/Camunda оркестрация переходов (`{N8N_WEBHOOK_BASE_URL}/webhook/evga/zeebe`, `evga/workflow-update`, `TASK_COMPLETE_EVENT`, `zeebe_process_instance_id` в документах) | документы/дела/апелляции | не переносить как есть — state-machine в Django (см. отчёты по документам/воркфлоу) |
| Магические константы (`'16'`, `'30101'`, `role_id IN (4,28)`, `PLANNED_CODES`) | разное | заменить на атрибуты справочников/ролей |
| `public.users`, `portal.users`, `surfk.users` — три таблицы пользователей | логи/уведомления/логин | одна `accounts.User` |
| jsonb-«model-objects» (`object_data`, `state`, `app_name`, `account_id`) | `evga_audit_object`, `acc_100.*`, `web_notifications` | реляционные модели |
| Полезное, что стоит взять: рекурсивное дерево типов нарушений с натуральной сортировкой; идемпотентный upsert пользователя по ИИН; история назначений `assigned/unassigned`; таблица переходов `evga_status_transitions` (`requires_signature/comment`, `required_role_code`, `is_automatic`); JSON-схема ИБ-события | | adapt |

---

## 10. Открытые вопросы

1. Содержимое таблиц-справочников (значения кодов `audit_types` кроме `'16'`, `inspection_types` — какие коды
   плановых, `check_initiators`, `control_reasons_types`, `response_measures`, `sampling_methods`,
   `organizational_legal_forms`, `evga_roles` с `id 4/5/7/8/28/30`) в экспорте **нет** — нужен дамп `surfk.*` или
   выгрузка из БД для `seed_evga_catalogs`.
2. Тела SQL-функций `surfk.check_user_role`, `surfk.get_user_roles`, `surfk.get_notification_by_document` и
   определение вью `surfk.evga_users_with_roles` — нужны из БД (в n8n их нет).
3. Какой Keycloak-роли соответствует фронтовый `reestr-confirmer` (`report_manager`? `report_manager_kvga`?
   `kvga_confirmer`?), и чем `kvga_kk_head_approver/kvga_kk_expert` отличаются от `qc_head/qc_expert` (по
   `role_id IN (4,28)/(5,30)` — это одна выборка).
4. Является ли `evga_user` (`surfk_user`) обязательным для входа во фронт ЭВГА, или достаточно функциональной роли;
   нужен ли в Django отдельный флаг «доступ к подсистеме».
5. Орган контроля роли всегда `'30101'` в `User Login Sync` — как планировались территориальные органы
   (`d_controlling_orgs`, `org_lvl_id`)? Для prof-маппинга на `Department`/`RoleScope.TERRITORIAL` нужно решение.
6. Нужен ли realtime (WebSocket) для уведомлений в первом релизе, и требуется ли e-mail-канал (в старой системе
   его не было).
7. Требования ИБ к журналу: обязательны ли `ip_address`, экспорт в SIEM (RabbitMQ) — определяет, делать ли
   `SecurityEvent` и middleware в первом релизе.
8. Комиссия по апелляциям (`commission-chair`, члены) есть только во фронте; подтвердить с ТЗ, что это целевой
   процесс, а не демо-упрощение, и какими ролями Keycloak она будет представлена.
9. Срок подачи возражений: старый BPMN — 10 календарных дней (`P10D`), фронт — 10 рабочих дней с учётом
   производственного календаря (`audit.calendar`). Какой вариант в ТЗ ЭВГА?
10. Транспорт ГБД ЮЛ для целевого контура (SOAP PI vs REST camel-gateway) и выдача учётки/токена (в экспорте
    токен захардкожен).
11. ЭЦП: требуется ли серверная проверка CMS/NCALayer при `sign/confirm` в новой системе (в старой не было).

---

## 11. Приложение А. Переменные окружения и credentials старой системы (для понимания контура)

| Переменная / cred | Назначение |
|---|---|
| `N8N_WEBHOOK_BASE_URL` | внутренние вызовы воркфлоу друг друга (`/webhook/evga/zeebe`, `/webhook/activity-log`) |
| `APP_BASE_URL` | портальный backend: `/api/notifications/notifications` (WS-push), `/api/model-objects/objects/NSI_DEMO?schemaId=` |
| `KEYCLOAK_ADMIN_BASE_URL`, `KEYCLOAK_REALM` (`efc`), `KEYCLOAK_JWT_*`, `KEYCLOAK_JWKS_URL`, `KEYCLOAK_TOKEN_URL`, `KEYCLOAK_IDP_BASE_URL`, `KEYCLOAK_REALM_IDP` | Keycloak |
| `ZEEBE_API_BASE_URL`, `ZEEBE_CLIENT_ID/SECRET`, `ZEEBE_SEND_EVENT_WORKFLOW_ID`, `EVGA_DOCUMENT_HISTORY_WORKFLOW_ID` | Camunda 8 REST + саб-воркфлоу |
| `CRYPTO_SERVICE_URL` + cred `APP_CRYPTO_INTERNAL_TOKEN` | шифрование ПДн портала |
| `RABBITMQ_LOG_QUEUE` + cred `RabbitMQ account` | ИБ-лог |
| `GBD_JL_SOAP_BASE_URL`, `ERSOP_SOAP_BASE_URL` + cred `JUR` (basic), `WS_USER_NSI` (basic) | ГБД ЮЛ, eStat/BNS НСИ |
| cred `portal_db` (postgres) | единая БД (`surfk`, `portal`, `notifications`, `acc_100`, `igo` — схемы в одной БД; также `Postgres account 4/6/12/14`) |
| cred `Keycloak admin` (`CUSTOM.keycloak`), `JWT Auth account 2` (узел `jwt`), `Bearer Auth account 2` | сервисные |

## 12. Приложение Б. Полный список старых endpoint’ов области (для трассировки на новые API)

```
GET  /webhook/evga/references/{evga-audit-type|evga-check-type|evga-check-initiator|evga-controlling-org|evga-risk-category|
     control-reasons-type|control-spheres|offense-type|offense-type/tree|response-measure|risk-object-type|sampling-methods|
     organizational-legal-forms|organ-reg-check|subj-sched-insp|audit-result|evga-audit-questions|dictionaries|d-controlling-orgs|employees}
GET  /webhook/evga/audit-objects            GET /webhook/evga/audit-object/search?bin=      POST /webhook/evga/check-audit-type
POST /webhook/findJurByBin | /webhook/jur/findJurByBin | /webhook/jur/findJurByBinNew
POST /webhook/user-login-surfk
GET  /webhook/keycloak-users                GET/POST/DELETE /webhook/keycloak-ib-admins
GET  /webhook/keycloak-subsystem-access/{groups|roles|user|attributes}   PUT/DELETE …/user-groups   POST/DELETE …/user-roles   POST/DELETE …/user-attributes
GET/POST/DELETE /webhook/keycloak-subsystem-users-v2?role=evga_user
GET  /webhook/qc/heads  GET /webhook/qc/experts  GET /webhook/appeals/heads  GET /webhook/appeals/experts
POST /webhook/send-notification-with-recipients   GET /webhook/notifications/unread   PUT /webhook/:id/mark-read
PUT  /webhook/notifications/mark-all-read         PATCH /webhook/update_status?id=     GET /webhook/notifications_by_id
POST /webhook/activity-log   GET /webhook/activity-log (неакт.)   POST /webhook/evga/case-workflow-log
POST /webhook/assign-appeal-expert/cases/:caseId/assign-appeal-expert   GET /webhook/appeals/cases   POST /webhook/evga/appeal-result
POST /webhook/evga/info-request (deprecated)   POST /webhook/evga-case-status/update   POST /webhook/worktime/requests (+9 Worktime)
POST /webhook/oa/acknowledge   GET /webhook/oa/notification/:caseId/:documentId   POST /webhook/evga/invited-specialist (домен documents)
```
