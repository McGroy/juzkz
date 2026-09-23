# Старый бэкенд ЭВГА на n8n — домены «дела» и «документы»

Отчёт-исследование. Источник — `n8n_old_project_archive/` (далее `n8n_old/`): экспорт воркфлоу n8n (`n8n_export/workflows/*.json`, распечатки `n8n_export/analysis/*.txt`, полный дамп `n8n_export/all_workflows_raw.json` — 566 воркфлоу) и BPMN-процессы Camunda 8 (`bpmn/*.bpmn`, `bpmn/bpmn_summary.txt`, `bpmn/bpmn_map.txt`). Все идентификаторы (таблицы, колонки, коды действий/статусов, пути webhook'ов) приведены так, как они записаны в исходниках. Документ самодостаточен и предназначен для агентов, которые будут проектировать Django-бэкенд ЭВГА «в стиле prof» (см. соседний отчёт `reports/prof-backend-style.md`) и не имеют доступа к этому контексту.

Промежуточные распечатки узлов, на которые ссылается отчёт, лежат в `scratchpad/tmp_n8n_cases_docs/out/*.txt` (воркфлоу из `workflows/`) и `scratchpad/tmp_n8n_cases_docs/out2/*.txt` (воркфлоу, извлечённые из `all_workflows_raw.json`); скрипты — `parse_wf.py`, `parse_raw.py` там же.

---

## 0. Резюме

1. Старый бэкенд — это ~50 n8n-воркфлоу (webhook → JS-код → сырой SQL к схеме `surfk.*` → ответ) плюс ~70 BPMN-процессов Camunda 8/Zeebe, которые держат «состояние документа» (статус + `available_actions`) и через HTTP-коннекторы пишут его обратно в Postgres теми же n8n-webhook'ами. Бизнес-логика размазана по трём слоям: JS в узлах Code, SQL в узлах Postgres (в т.ч. хранимые функции `surfk.check_*`, `surfk.get_next_*_sequence`, `surfk.send_case_to_qc` и др., тел которых в экспорте **нет**), и BPMN-гейты.
2. Ядро домена «дела»: таблица `surfk.cases` (+ `case_participants`, `case_bases`, `case_base_attachments`, `case_status_history`, `case_qc_assignments`, `case_qc_expert_assignments`, `audit_objects`, view `cases_list_view`). Подчинённые дела (`admin_violation`, `counter_control`) — те же `cases` с `parent_id`/`sub_case_type`/`sub_case_data`.
3. Ядро домена «документы»: справочники `evga_document_types`/`evga_document_stages`/`evga_document_statuses`, общая «шапка» `evga_case_documents`, generic-движок `evga_document_mappings` (`root_table` + `fields_mapping` + `subtables_mapping` + `form_schema` в JSONB, из которых JS генерирует динамический SQL в таблицы `evga_doc_*`), журналы `evga_document_approvals` / `evga_document_signatures` / `evga_document_workflow_history` / `evga_document_versions` / `evga_audit_log`.
4. Единая точка входа для документов — `POST /webhook/evga/documents` `{action, params}` с 59 кодами действий (монолит «EVGA Additional Actions», активная копия `VMkW67X9Wz5jfxh8`; роутер «EVGA Documents Router» + 8 доменных саб-воркфлоу `EVGA Docs: *` — незавершённый рефакторинг, все выключены).
5. Создание дела (`EVGA: Create Case v4 Parallel Docs`) атомарностью не обладает: 1 INSERT дела + upsert объекта аудита + 5 INSERT документов (M5-IPI, M6-PA-S/F, M8-PLAN, M9-AZ, M7-POR) + 5+1 старт процессов Zeebe + HTTP-вызовы самого себя для рабочей группы. Нумерация дела — `<код органа>-<YY>-<00000>` через `surfk.get_next_case_sequence(year)`; документов — `YYYY/MM/DD – 00000` (стандарт) или `<prefix>-<орган>-<YY>-<000000>/<хвост номера дела>[_1]` (`with_org`).
6. Важные находки, которых нет в курируемой папке `workflows/`, но есть в `all_workflows_raw.json` и без которых картина неполна: активный монолит `EVGA Additional Actions` (`VMkW67X9Wz5jfxh8`), Zeebe-хаб `EVGA Zeebe Integration` (`evga/zeebe`), обратные webhook'и `evga/workflow-update` и `evga/case-workflow-update` (Zeebe → Postgres), `send-case-to-qc`, `EVGA: Work Group Approval`, `EVGA Case Update (Extended…)`, `EVGA: Get Case Documents`, `EVGA: Cases - Delete`, `ERSOP - Build and Send from Document`, `restErsop`/`SEND_REQ_TO_ERSOP`, `QC Conclusion Workflow`, `EVGA_ Invited Specialist`.
7. Воркфлоу `Upsert Document`, `Get All Documents`, `Document Uploaded`, `Delete Document File`, `Worktime - Create Time Request` — **не ЭВГА**: это портал (`portal.documents`, `portal.time_requests`) и аудит-лог в RabbitMQ. Для бэкенда ЭВГА их надо отбросить.
8. Вердикт в целом: схему данных и коды (статусы, действия, типы документов, форматы номеров, ЕРСОП-сообщения) переносить; SQL/JS-логику превращать в сервисы-функции и ORM; Zeebe/BPMN и n8n-специфику (роутеры через `$vars.*_WORKFLOW_ID`, `workflow_state.available_actions` как источник правды, конкатенация SQL из параметров, `COUNT(*)+1`-нумерация) — выбросить и заменить явным конечным автоматом на сервере.

---

## 1. Источники и охват

### 1.1. Что прочитано

| Группа | Воркфлоу (id, активность) | Где распечатано |
|---|---|---|
| Дела — ядро | `EVGA: Create Case v4 Parallel Docs` (54iSD0yMQIhjzUxO, on), `EVGA: Cases - List` (EjawnHl7W52lNxNK, off), `EVGA: Get Case Detail` (C5irseH3IQ8vD4ry, on), `EVGA Sub Cases` (EwhTskPBkJFgzxdu, on), `EVGA: Set Case Party Lead` (8sbPxZGwOPlVOQOK, on), `EVGA: Add Case Participants` (DdGaqbwSlWkFpYv8 on / A9MYq8oJVlnRqo8T off), `EVGA: Delete Case Participant` (9cFyAbLOPoHeZ1SS on / aqukWLVO4iFomaaj off), `assign-expert-to-case` (3LcwF4UHmTLarhnV on / eWOF1HjDHgDkhvzJ off), `get-assigned-expert`, `list-ak-cases`, `get-ak-case-documents`, `audit-objects-apl CRUD` | `analysis/cases_core_raw_dump.txt`, `tmp_n8n_cases_docs/out/` |
| Дела — из raw-дампа | `send-case-to-qc` (qFoaOFDafzsaW31d, on), `list-qc-cases` (i1rG7dTAzUzBgMhh, on), `OA get case` (y0m8RUeeMocAzfuZ, on), `EVGA: Get Case Work Group` (ua0k1bxKrjLg49Gp, on), `EVGA Get Case Bases` (mYf9usM9egsKMD0I, on), `EVGA Case Update (Extended with workflow_state)` (ZAHkA8dyJV18abS5, on), `EVGA: Cases - Delete (Soft Delete)` (YtrKBjkK5fzsruS5, on), `My workflow 31` (Ct0H9kLN7saxeZwc, on — смена статуса дела), `EVGA Case Action → Zeebe Event` (vR80mIaWfwXgsOv2, on), `EVGA Case Workflow Update (Zeebe → PostgreSQL)` (SGOGVWvb9lJfa0e9, on), `EVGA Case Workflow Log (Zeebe → PostgreSQL)` (6Ge3jrKwsxPQwAzk, on), `EVGA: Create Case v3 Simple dev` (off, предшественник v4) | `tmp_n8n_cases_docs/out2/` |
| Документы — ядро | `EVGA Documents Router` (FyOhpPDlAv69NSES, on), `EVGA Additional Actions` (C4FIU7mx71GievWg **off**, 246 узлов; активная копия **VMkW67X9Wz5jfxh8 on**, 249 узлов), `EVGA Docs: CRUD` / `Case Misc` / `KVGA/Reestr` (off), `EVGA Docs: Lifecycle` / `QC` / `Meta` / `Roles` / `Generic` (off, только в raw), `EVGA Check Documents Status`, `EVGA: Document History Record`, `EVGA Document Verify (Public)`, `Get Available Document Types`, `EVGA: Get Case Documents` (ZACkAb8ICdWslOOp on), `EVGA: Work Group Approval` (o7qXjwFWHnqMOskM on), `QC Conclusion Workflow` (VvAGylLDyNt9eX4c on), `EVGA_ Invited Specialist` (GpIzFb8dCC5LWxvP on), `audit-assignment CRUD`, `acknowledge-document`, `Copy Poruchenie Data to Registration Card`, `Get Activity Log`, `EVGA Info Request API` (Hac72Ds2Nj9NeZaP off; `…(deprecated)` 3qkoem1fA0uuqmUu — 3 узла, заглушка) | `analysis/documents_raw_dump.txt`, `out/`, `out2/` |
| Zeebe | `Zeebe: Send Event (Sub-workflow)` (yvkEuLA9CzuDRPNb), `Zeebe: Start Process (Sub-workflow)` (9aUvzbLTHnoL0gQn), `EVGA Zeebe Integration (Start Process + Send Events)` (UiWVsuAqEQyf7QqL, on), `EVGA Workflow Update (Zeebe → PostgreSQL)` (PtrEVtyCsuMt05Ce, on) | `out2/` |
| ЕРСОП/внешние | `EVGA ERSOP Workflow` (cyKRwRgN5AUhCaZ0, on), `ERSOP - Build and Send from Document` (gMhkTFjsmrZGiCHK, on), `SEND_REQ_TO_ERSOP` (EONQxH4A8o5mpf8V, off; путь `ersop-requset2`), `restErsop` (0dseI7mXnFgbwiOB, on; `sendErsop`), `ersopStarted1pForm`, `sendRequestErap`, `Service GDBJL surfk` (off) | `out/`, `out2/` |
| Справочные в моём периметре | `violations` (qcs2), `EVGA Check Audit Type`, `EVGA: Audit Result - Get` (оба), `Get offense-type-tree`, `get_previous_audit_list_by_bin` | `out/` |
| Не-ЭВГА (портал) | `Upsert Document`, `Get All Documents`, `Document Uploaded`, `Delete Document File`, `Worktime - Create Time Request` | `analysis/documents_raw_dump.txt` |

Манифесты: `included_manifest.json` (84 файла) и `domain_manifest.json` (классификация по доменам; «EVGA Additional Actions» и «My workflow 31» попали в `_unclassified`). В `excluded_manifest.json` ошибочно исключён `Zeebe: Start Process (Sub-workflow)` (reason `no evga signal`), а `Zeebe: Send Event` и хаб `EVGA Zeebe Integration` вообще не попали в курируемую папку — извлечены мной из `all_workflows_raw.json`.

### 1.2. Общая архитектура старого бэкенда

```
Фронт (React) ──HTTP──▶ n8n webhook (/webhook/<path>)
                          │  Code (JS): парсинг/валидация/сборка SQL строкой
                          │  Postgres executeQuery: сырой SQL к surfk.* (иногда хранимые функции)
                          │  Execute Workflow: саб-воркфлоу по $vars.*_WORKFLOW_ID
                          ▼
                       Zeebe REST-middleware ($vars.ZEEBE_API_BASE_URL)
                          POST /process-instances?processId=…      (старт BPMN-процесса документа/дела)
                          POST /process-instances/event?processInstanceId=…  (сообщение TASK_COMPLETE_EVENT)
                          ▲
BPMN (Camunda 8) ──http-json connector──▶ n8n: /webhook/evga/workflow-update (461 вызова в 70 BPMN),
                                               /webhook/evga/zeebe (46), /webhook/evga/case-workflow-update (28),
                                               /webhook/evga/check-docs-status (15), /webhook/evga/documents (5, action=create),
                                               /webhook/work-group-approval (3, action=init), /webhook/evga/cases/bases (2),
                                               /webhook/evga/check-audit-type (1)
```

Конверт ответа везде свой, но чаще всего `{ success: true, data: … }` / `{ success: false, error: '…' }` (иногда `message`, `count`, `pagination{page,limit,total,totalPages,hasNext,hasPrev}`, `filters`). HTTP-коды: 200 по умолчанию, 201 при создании дела/участников, 400/404/422/500 в отдельных ветках `Respond Error`.

Авторизация: почти нигде не проверяется. `Parse Request` роутера и `EVGA ERSOP Workflow` лишь извлекают `jwtToken` из `Authorization` и прокидывают дальше (в саб-воркфлоу он передаётся как `"jwtToken": "="`, т.е. пусто). Реальную JWT-проверку (RS256 по JWKS Keycloak, роли `portal_admin`/`admin`) делают только портальные воркфлоу `Upsert Document`/`Document Uploaded`/`Delete Document File`/`Worktime` (блок `PORTAL JWT GUARD v1`). Идентификация пользователя — `user_iin`/`author_iin` (ИИН, 12 цифр) в теле запроса, иногда `*_keycloak_id` (uuid). Токен для Zeebe — `client_credentials` (`$vars.KEYCLOAK_TOKEN_URL`, `ZEEBE_CLIENT_ID`, `ZEEBE_CLIENT_SECRET`); Create Case v4 вместо этого пробрасывает bearer пользователя.

Переменные окружения n8n (`$vars`): `ZEEBE_API_BASE_URL`, `N8N_WEBHOOK_BASE_URL`, `KEYCLOAK_TOKEN_URL`, `ZEEBE_CLIENT_ID/SECRET`, `ZEEBE_SEND_EVENT_WORKFLOW_ID`, `ZEEBE_START_PROCESS_WORKFLOW_ID`, `EVGA_DOCUMENT_HISTORY_WORKFLOW_ID`, `EVGA_DOCS_{CRUD,META,LIFECYCLE,KVGA_REESTR,QC,ROLES,CASE_MISC,GENERIC}_WORKFLOW_ID`, `ERSOP_SOAP_BASE_URL`, `KEYCLOAK_REALM/ADMIN_BASE_URL/JWT_ISSUER/JWKS_URL/JWT_AUDIENCE`, `RABBITMQ_LOG_QUEUE`; `$env.DOCUMENT_SERVICE_URL` (файловый сервис, вложения плана).

---

## 2. Реконструированная схема `surfk.*`

Схема восстановлена только из SQL в узлах (DDL в экспорте нет). Типы — по контексту. Полный список упоминаемых объектов схемы (из всех 566 воркфлоу) — в §2.9.

### 2.1. Дело и его окружение

**`surfk.cases`** (sequence `surfk.cases_id_seq`; soft delete)

| Колонка | Тип/семантика | Откуда видно |
|---|---|---|
| `id` | serial PK | везде |
| `registration_number` | text, формат §4.2 | Create Case v4 `Insert Case1` |
| `code` | text (не заполняется n8n) | Get Case Detail, data_migration |
| `audit_object_id` | FK `audit_objects` | |
| `plan_object_id` | FK `plan_objects` (реестр/план) | Get Case Detail, data_migration |
| `controlling_body_id` | FK `controlling_bodies` | |
| `inspection_type_id` | FK `inspection_types` (`code` `'1'` плановый / `'2'` внеплановый; `id = 6` — внеплановый по коду `Check Bases Update`, `Get Case Bases`) | |
| `inspection_kind_id` | int, 24 «Совместная проверка» / 25 «Параллельная проверка» (захардкожено в Get Case Detail) | |
| `audit_type_id` | FK `audit_types` (7 — аудит соответствия, 8 — аудит фин. отчётности; `audit_types.code`, `audit_types.ersop_code`) | Create Case v4 валидация |
| `status_id` | FK `case_statuses` | |
| `author_id` | FK `employees` (deprecated, «authorId (deprecated)») | |
| `author_iin`, `author_keycloak_id` | varchar(12), uuid | |
| `approver_id`, `supervisor_id` | FK `employees` (n8n не пишет) | Get Case Detail |
| `start_date`, `end_date` | date | |
| `audit_goal_ru`, `audit_goal_kz` | text | |
| `is_electronic_audit`, `is_dsp` | bool | |
| `director` | text (дублирует `audit_objects.director`) | |
| `workflow_state` | jsonb `{available_actions:[…], is_editable, source:'n8n'|'zeebe', process_instance_id, updated_at}` | Insert Case1, Case Workflow Update |
| `zeebe_process_instance_id` | text | |
| `qc_head_iin`, `qc_head_fullname` | руководитель КК | send-case-to-qc |
| `qc_expert_iin`, `qc_expert_fullname` | эксперт КК | assign-expert-to-case |
| `parent_id`, `sub_case_type` (`'admin_violation'`\|`'counter_control'`), `sub_case_data` jsonb | подчинённые дела | EVGA Sub Cases |
| `is_deleted`, `deleted_at`, `deleted_by` (FK `employees`) | soft delete | Cases - Delete |
| `created_at`, `updated_at` | | |

**`surfk.case_statuses`**: `id, code, name_ru, name_kz, color`. Коды, встреченные в n8n: `open` (начальный), `closed`, `qc_approved`; из BPMN (`newCaseStatus` в `evga/workflow-update`): `audit_implementation`, `pending_audit_objection`, `audit_objection_consideration`, `control`, `closed`; в `evga/case-workflow-update` (`newStatus` дела) — `open`, `sent_to_qc`, `expert_assigned`, `qc_acknowledged`, `control` и др. По id: `1` — черновик (закомментированная проверка в Cases - Delete), `11, 12` — «на КК» (фильтр по умолчанию в `list-qc-cases`).

**`surfk.case_participants`** (рабочая группа): `id, case_id, user_iin varchar(12), employee_id (старый FK employees, активная версия пишет только user_iin), is_lead bool, assigned_by uuid, assigned_at, is_active, removed_at, removed_by uuid`. Один лидер: «Reset All Leads» + «Set New Lead».

**`surfk.case_bases`** (основания внепланового аудита): `id, case_id, number, basis_ru, basis_kz, initiator_ru, initiator_kz, basis_date, sort_order`. Наименования копируются из справочников `control_reasons_types(code, name_ru, name_kz)` и `check_initiators(code, name_ru, name_kz)` по коду в момент вставки (денормализация; обратный поиск кода в `Get Case Bases` идёт по `name_ru`!). Обновление — полная замена (`DELETE … ; INSERT …`) и только если `inspection_type_id = 6`.

**`surfk.case_base_attachments`**: `id, case_base_id, document_id (строковый id файла во внешнем файловом сервисе), file_name, uploaded_at`.

**`surfk.case_status_history`** — две несовместимые формы записи: (а) `case_id, old_status_id, new_status_id, changed_by (users.id), comment, changed_at` (Zeebe-логгеры), (б) `case_id, old_status_id, new_status_id, changed_by_iin, changed_by_fullname, comment, created_at` (`close_case`). Значит в таблице есть обе пары колонок.

**`surfk.case_activity_log`**: `case_id, action ('deleted'), action_details jsonb/text, performed_by (employees.id), performed_at`.

**`surfk.case_qc_assignments`** (назначение руководителя КК): `id, case_id, qc_head_iin, qc_head_fullname, assigned_by_iin, assigned_by_fullname, action ('assigned'|'unassigned'), comment, created_at`. **`surfk.case_qc_expert_assignments`** — то же для эксперта (`qc_expert_iin/fullname`). Актуальное назначение = запись `assigned`, после которой нет `unassigned` с большим `id`. **`surfk.case_appeal_expert_assignments`** — аналог для апелляций (домен appeals).

**`surfk.cases_list_view`** (view): `id, registration_number, status_id, status_name_ru/kz, controlling_body_id, controlling_body_name_ru/kz, audit_type_name_ru/kz, audit_object_id, audit_object_name_ru, audit_object_bin, created_at, …` (`c.*`).

**`surfk.audit_objects`**: `id, bin (UNIQUE — upsert `ON CONFLICT (bin)`), name_ru, name_kz, short_name_ru, director, address_ru, org_legal_form_id (FK organizational_legal_forms: name_ru, short_name_ru), region_id (FK regions), risk_level_id (FK risk_levels.code), risk_value, controlling_body_id, is_active`.

Справочники дел: `controlling_bodies(id, code, name_ru, name_kz)`, `inspection_types(id, code, name_ru, name_kz)`, `audit_types(id, code, name_ru, name_kz, ersop_code)`, `control_reasons_types`, `check_initiators`, `organizational_legal_forms`, `regions`, `risk_levels`, `employees(id, iin, fullname, family_name?, department_id, position_id)`, `departments(name_ru)`, `positions(name_ru, name_kz)`, `users(id, iin, fullname, family_name, given_name, is_active)` (есть также `public.users(full_name_ru, iin)` и `portal.users(keycloak_user_id, department_id)` — три разных таблицы пользователей!).

Роли ЭВГА: **`surfk.evga_roles`** `(id, code, name_ru, name_kz, description_ru, role_level, can_create_documents, can_approve_documents, can_confirm_documents, can_sign_documents, is_active)`; **`surfk.evga_user_roles`** `(id, user_iin, user_fullname, user_position, role_id, controlling_body_code, controlling_body_id, valid_from, valid_to, is_active)`; view **`surfk.evga_users_with_roles`** (плоское соединение). Коды ролей, встреченные в коде: `auditor`, `oa_responsible`, `audit_object`, (в BPMN `allowed_roles`) и в фильтре действий — типы назначения `approver`, `confirmer`, `kvga_confirmer`, `author`, `qc_expert`, `qc_head`, `workgroup`, `workgroup_lead`.

### 2.2. Документы: справочники

**`surfk.evga_document_types`** (колонки из `Get Available Document Types`, `Get Create Mapping`, `Get Zeebe Process Info`):
`id, code ('M5-IPI'…), name_ru, name_kz, description_ru, stage_id (FK evga_document_stages), is_default, sequence_order, zeebe_process_id (id BPMN-процесса, напр. prc_…), requires_approval, requires_confirmation, requires_kvga_confirmation, requires_signature, sends_to_audit_object, creator_roles jsonb (['auditor']), depends_on_document, creation_condition, audit_type_codes text[], allow_multiple, is_child_only, is_manually_creatable, block_recreate_after_delete, reg_number_prefix, reg_number_format ('standard'|'with_org'), supports_version`.

**`surfk.evga_document_stages`**: `id, code, name_ru, name_kz, sequence_order` — `1` «Планирование аудита», `2` «Проведение аудита», `3` «Документы по результатам государственного аудита» (STAGE_META в `Get Available Document Types`).

**`surfk.evga_document_statuses`**: `id, code, name_ru, name_kz`. По id: `1, 2` — «черновые» (`can_edit` в Get Case Detail: нет документов со `status_id NOT IN (1,2)`), `3, 22` — исключаются при поиске «активного» документа типа (вероятно удалён/отклонён), `49` — `sent_to_ak` (фильтры АК). Полный список кодов — §4.5.

**`surfk.evga_document_mappings`** — сердце generic-движка: `document_type_id, root_table (имя evga_doc_*), fields_mapping jsonb, subtables_mapping jsonb, form_schema jsonb, is_active`.
* `fields_mapping`: `{ "<ключ поля формы>": { "column": "<колонка root_table>", "type": "integer|decimal|boolean|date|json|string", "virtual": bool } }`.
* `subtables_mapping`: массив `{ key, table, fk_column, columns:{col:{type}}, defaultValues:{}, filter:{}, fk_source: 'document_id'|'case_id'|'<key родительской подтаблицы>', root_fk_column, nested_subtables:[{source_key, field, match_on:{parent,child}, fields}], overlay_source:{table, alias, from_case_document:{root_table, document_type_ids, fk_column}, join_keys, output_fields, order_by, dictionary_join}, seed_from:{table, fk_column, source} }`.
* `form_schema` — отдаётся фронту как есть.

Прочие: `evga_available_document_types` (view над типами), `evga_dashboard_stats` (view, фильтр `controlling_body_code`), `evga_document_timeline` (view, `document_id`), `evga_document_action_types(code, name_ru)`, `evga_status_transitions(document_type_id, from_status_id, action_code, action_name_ru, action_name_kz, requires_signature, requires_comment, required_role_code, is_automatic)` — используется только в `QC Conclusion Workflow` и appeals.

### 2.3. Документ дела и его журналы

**`surfk.evga_case_documents`** (общая «шапка» документа):

| Колонка | Семантика |
|---|---|
| `id`, `case_id`, `document_type_id`, `status_id` | |
| `registration_number` | формат §4.2 |
| `author_iin`, `author_keycloak_id`, `author_id` | автор |
| `version` (default 1), `parent_document_id` | версия; дочерний документ (объекты возражений M20-VOZ, вложенные) |
| `embedded_role`, `source_document_id`, `snapshot_taken_at` | «встроенный» документ-снимок (Docs: CRUD; при удалении родителя каскадно помечаются) |
| `workflow_state` jsonb | `{available_actions:[{code,name_ru,name_kz,icon,color,requires_signature,requires_comment,allowed_roles[],action_type,assignment_type,assigned_to_iin}], is_editable, source:'zeebe'|'n8n'|'embedded', process_instance_id, updated_at}` |
| `metadata` jsonb | произвольно (M20-VOZ: `parent_document_id, objection_date, audit_object_*`) |
| `zeebe_process_instance_id` | |
| `approver_iin/fullname`, `confirmer_iin/fullname`, `kvga_confirmer_iin/fullname` | назначенные согласующий/утверждающий/КВГА |
| `submitted_at`, `approved_at`, `confirmed_at`, `confirmed_by_iin/fullname`, `kvga_confirmed_at` | отметки времени |
| `returned_by_iin/fullname`, `return_comment`, `returned_at` | возврат |
| `audit_object_acknowledged_at/by` | ознакомление ОА |
| `due_date`, `due_days` | (get-ak-case-documents) |
| `is_deleted`, `deleted_at`, `created_at`, `updated_at` | |

**`surfk.evga_document_approvals`**: `id, case_document_id, approver_iin, approver_name, status, comments, sequence_step, approved_at, created_at`. Значения `status`: `submitted, approved, revision, returned, confirmed, sent_to_confirmation, kvga_confirmed, kvga_returned, kvga_rejected, activated, sent_to_ersop, registered_ersop, rejected_ersop, sent_revision_ersop, ersop_accepted, ersop_error`.

**`surfk.evga_document_signatures`**: `id, case_document_id, signature (base64 ЭЦП), signer_iin, signer_name, signer_organization, signature_type, signed_at, document_hash, created_at, updated_at`; частичный UNIQUE `(case_document_id, signer_iin, signature_type) WHERE signature_type = 'work_group_pending'`. Типы: `work_group_pending → work_group_signed`, `invited_specialist_pending → invited_specialist_signed`, `kvga_confirm`, `kvga_reject`, `oa_acknowledge`, `sign`, `confirm`.

**`surfk.evga_document_workflow_history`**: `id, case_document_id, action_code, action_name_ru, from_status_id, to_status_id, performed_by_iin, performed_by_fullname, comment, signature_data, is_signed, created_at`. Пишется и n8n (при каждом переходе), и Zeebe-callback'ом `evga/workflow-update`.

**`surfk.evga_document_versions`**: `id, document_id, version_number, data_snapshot jsonb (surfk.create_full_document_snapshot(document_id)), returned_by_iin, returned_by_fullname, return_comment, returned_at, previous_status_id, created_at`. Создаётся только по флагу `shouldCreateVersion=true` из BPMN; после этого `evga_case_documents.version = version_number + 1`.

**`surfk.evga_audit_log`** (единая история «для людей», саб-воркфлоу `EVGA: Document History Record`): `id, entity_type ('case'|'case_document'), entity_id, case_document_id, case_id, action_code, status_code, field_changes jsonb ([{field:'status', old, new}]), performed_by_iin, performed_by_name, comment, source ('user'|'zeebe'|'system'|'ersop'|'timer'), created_at`. Дедупликация: не пишется, если та же пара (документ/дело, action_code, performed_by_iin) уже есть за последние 10 секунд.

**`surfk.evga_audit_object_notifications`** (и/или старое `surfk.oa_notifications`): `id, case_document_id, …` — создаётся функцией `send_document_to_audit_object(case_id, document_id, sender_iin, sender_fullname, requires_acknowledgment bool, expires_days int)` → возвращает `notification_id`; закрывается `acknowledge_document(notification_id, acknowledger_iin, acknowledger_fullname, comment, signature_data)`.

**`surfk.evga_qc_requests`**: `id, controlling_body_code, status ('pending'), requested_at, …` (заявки на КК; функции `send_case_to_qc`, `assign_qc_expert`, `complete_qc_review`, `get_qc_tasks`).

**`surfk.evga_document_attachments`**: `id, document_id, file_id, description, file_name` (вложения документа во внешнем файловом сервисе; скачивание base64 через `webhook/download-base64-test/test/download-base64/{file_id}`).

### 2.4. Таблицы `evga_doc_*` по типам документов

| Код типа (`evga_document_types.code`) | `root_table` | Колонки root (видны из SQL) | Подтаблицы |
|---|---|---|---|
| `M5-IPI` (id=1) Информация о результатах предварительного изучения | `evga_doc_preliminary_study` | `case_document_id, is_electronic_audit, is_dsp, joint_inspection_bin jsonb ({bin}), inspection_kind_id, audit_start_date, audit_end_date` | `evga_doc_ps_audit_questions(preliminary_study_id, question_code, period_from, period_to, coverage_amount, budget_program_code, npa_ru, npa_kk, npa_reference)`; `evga_case_audit_questions(case_id, question_code, …)` — вопросы дела для сида |
| `M6-PA-S` (id=2) / `M6-PA-F` (id=47) Программа аудита соответствия / фин. отчётности | `evga_doc_audit_program` | `case_document_id, is_electronic_audit, is_dsp` | `evga_doc_ap_questions(audit_program_id, question_number, audit_indicator_code, question_code, custom_question, budget_program_code, research_method_code, balance_currency, period_from, period_to, coverage_amount, npa_ru, npa_kk, npa_reference, fkr_fullcode, budget_amount, transfers_amount, assets_amount, control_topic, control_subtopic, registration_number, sequence_number, source_ps_question_id, created_at)` |
| `M8-PLAN` (id=3) План аудита | `evga_doc_audit_plan` | `case_document_id` | `evga_doc_apl_audit_objects(audit_plan_id, audit_object_bin, audit_object_name_ru/kz, organizational_form_code, ownership_form_code, address, period_from, period_to, route, coverage_amount, materiality_level)`; `evga_doc_apl_audit_object_members(audit_object_id, member_iin, member_fullname)` (ON DELETE CASCADE); `evga_doc_apl_attachments(file_path…)`; `evga_doc_apl_audit_events` |
| `M9-AZ` (id=4) Аудиторское задание | `evga_doc_audit_assignment` | `case_document_id` | `evga_doc_aa_question_assignments(audit_assignment_id, question_id, question_code, question_text, start_date, end_date, working_days)`; `evga_doc_aa_assignees(question_assignment_id, audit_assignment_id, full_name, position, role)` |
| `M7-POR` (id=5) Поручение | `evga_doc_audit_order` | `case_document_id, coverage_period_from/to, deadline_from/to` | `evga_doc_ao_risk_objects(audit_order_id, sequence_number, risk_object_type_code, risk_object_name_ru/kz)` |
| (id=6) «Дело КК» (BPMN `evga_doc_6_qc`) | — | создаётся со статусом `open`, а не `draft` | |
| ЗКК (id=7, BPMN `evga_doc_7_zkk`; в BPMN также `M10-QC1`), КК 2 этап (id=37), КК 3 этап (id=46) | `evga_doc_quality_control_conclusion` | `basis_for_qc, control_start_date, qc_level, has_compliance_remarks, req_preparation_stage_ru/kz, req_document_compliance_ru/kz, req_counter_inspection_ru/kz, req_notification_timeliness_ru/kz, req_response_measures_ru/kz, req_financial_violation_ru/kz, conclusions_and_recommendations` | `evga_doc_qc_conclusion_participants(case_document_id→qc.id, user_iin, fullname, position, organization)` |
| Учётная карточка (М11, BPMN `evga_doc_accounting_card`) | `evga_doc_registration_card` | `case_document_id, uo_check_number, uo_check_date, coverage_period_from/to, audit_period_from/to, legal_basis_id (→ evga_legal_basis_audit.code), query_check_ids jsonb (→ d_query_check_npa.query_check_code), assigning_authority_id, registration_authority_id, exceptional_description_ru/kz, subject_bin, ersop_subject_id, ersop_object_id` | `evga_doc_rc_work_group(registration_card_id, member_iin, member_fullname, member_position, member_organization, sequence_number)` |
| Приказ о начале / о завершении (BPMN `evga_doc_prikaz`) | `evga_doc_audit_start_order`, `evga_doc_inspection_completion_order` | `case_document_id, order_number` | |
| `M13` Уведомление ВАП | `evga_doc_notification_vap_rk` | | |
| `M14` Дополнительное поручение (BPMN `evga_doc_additional_order`) | (нет в n8n) | | |
| `M15` Требование по предоставлению сведений | `evga_doc_info_request` | | `evga_doc_ir_questions` |
| Акт контрольного обмера | `evga_doc_control_measurement_act` | | `evga_doc_cma_work_group(control_measurement_act_id, member_iin, member_last_name/first_name/middle_name, member_position_code, member_role_code ('invited_expert'|'invited_specialist'))` |
| `M17-AO-S` / `M17-AO-F` Аудиторский отчёт | (нет в n8n; только Zeebe-события) | | |
| `M18-RNS` Реестр нарушений (соответствие) | `evga_doc_vr_compliance` | | `evga_doc_vrc_violations(compliance_id, violation_type_code, violation_amount, reimbursed_amount, restored_amount, accounted_amount, brought_compliance_amount, remainder_amount, consequence_type_code, report_type_code, violation_status_code, report_paragraph_number, violation_description_ru/kz, control_theme, control_question, risk_object_seq_number, result_id, source_ap_question_id)`, `evga_doc_vrc_results(compliance_id, risk_object_type_code, risk_object_display, risk_object_seq_number, sequence_number, source_ap_question_id)`, `evga_doc_vrc_risk_objects(compliance_id, sequence_number, type_code, object_name, year, coverage_amount)` |
| `M18-RNAFO` Реестр нарушений (фин. отчётность) | `evga_doc_vr_financial_new` | | `evga_doc_vrfn_violations(financial_id, …как vrc)`, `evga_doc_vrfn_results` |
| `M19-AD` Аудиторские доказательства | (нет в n8n) | | |
| `M20-VOZ` Возражение от объекта аудита (дочерний к отчёту) | `evga_doc_audit_objection` | `case_document_id, audit_object_name, audit_object_bin, audit_object_address, controlling_body_name, executor_name, objection_date` | `evga_doc_or_objections(violation_reference)` |
| `M23-RVO` Результаты возражения | `evga_doc_objection_appeal_result` | `review_date` | `evga_doc_oar_violations(appeal_result_id, ao_violation_id, cancelled_amount)` |
| `M21-AKO` Ознакомление ОА, `M24-AZK` Аудиторское заключение, `M25-PRED` Предписание, `M26-TU` Талон-уведомление, `M28-OPM` Ответ о принятых мерах, `M16` Акт об отказе в доступе | только коды в BPMN/фильтрах | | |
| `M39-ADM-PROT` Протокол об адм. правонарушении (подчинённое дело `admin_violation`) | `evga_doc_admin_offense_protocol` | `case_document_id` | |
| `M43-VK-POR` Поручение по встречному контролю (подчинённое дело `counter_control`) | `evga_doc_counter_control_poruchenie` | `case_document_id` | |
| Адм. производство `M38-ADM-OSN`, `M40-ADM-POST-VZ`, `M41-ADM-POST-PR`, `M42-ADM-KVIT`, `M48-ADM-1AV`, `M49-ADM-VOZ`, `M50-ADM-PROT-UO`, `M52-ADM-OPLATA`, `M53-ADM-1AP`, `M57-ADM-RESH`; встречный контроль `M44-VK-UK`, `M45-VK-TREB`, `M46-VK-AKT`, `M47-VK-TU`, `M54-VK-DOP-POR`, `M55-VK-AKT-OSM`, `M56-VK-AKT-VOS` | только BPMN-процессы (`bpmn_map.txt`), таблиц в n8n нет | | |

Известные `document_type_id` (по комментариям в коде и именам BPMN `EVGA Doc N`): 1=M5-IPI, 2=M6-PA-S, 47=M6-PA-F, 3=M8-PLAN, 4=M9-AZ, 5=M7-POR, 6=Дело КК, 7=ЗКК, 37=КК-2, 46=КК-3, 51=Возражения. Порядок отображения по этапам захардкожен в `DOC_PLACEMENT` (`Get Available Document Types`): этап 1 — ids 1,2/47,3,4,5,8,50,36,10,11,9; этап 2 — 32/33,16,52/53,14,15; этап 3 — 18,19,38,35,39,54/40/41,48/49/55,42,43,44,45,20.

### 2.5. Хранимые функции (сигнатуры по вызовам; тел в экспорте нет)

| Функция | Вызов | Возвращает / назначение |
|---|---|---|
| `surfk.get_next_case_sequence(year int)` | Create Case v4 | seq для номера дела |
| `surfk.get_next_doc_sequence(kind text, year int)` | create, объекция, register | seq; `kind ∈ {'standard','with_org','PRIKAZ'}` |
| `surfk.check_sub_case_creation_condition(parent_id, sub_case_type text)` | Sub Cases | `(can_create bool, reason text)`; для `admin_violation` — гейт создания; fallback-причина `ADMIN_VIOLATION_NO_GROUNDS` |
| `surfk.get_admin_violation_grounds(parent_id)` | Sub Cases | набор `ground_code` (основания адм. дела) |
| `surfk.close_admin_violation_case(id, user_iin, user_fullname)` | Sub Cases `close` | `(success, error, id, status)` |
| `surfk.soft_delete_admin_violation_case(id, user_iin)` | Sub Cases `delete` | `(success, error, id, registration_number)` |
| `surfk.check_document_creation_condition(case_id, document_type_id)` | `can_create`, Docs: CRUD create | `(can_create, reason)` |
| `surfk.get_available_document_types_for_case(case_id, user_iin varchar(12), stage_id)` | `get_available_for_case` | строки типов (`document_type_id`, …) |
| `surfk.check_document_submit_allowed(case_document_id)` | `submit` | `(allowed, reason)` — зависимости документа |
| `surfk.check_transition_condition(case_id, document_type_id, from_status_id, to_status_id)` | `check_transition` | `(allowed, blocking_type, message_ru, message_kz, blocking_document_type_id, blocking_document_type_name, blocking_current_status, blocking_required_status)` |
| `surfk.get_case_blocking_statuses(case_id)` | `get_blocking_statuses` | строки `(document_type_id, document_type_name, blocking_type, is_confirmation_blocked, message_ru/kz, blocking_*)` |
| `surfk.send_case_to_qc(case_id, qc_stage int, requested_by_iin, requested_by_fullname, controlling_body_code, comment)` | `send_to_qc` | запись в `evga_qc_requests` |
| `surfk.assign_qc_expert(request_id, qc_head_iin, expert_iin, expert_fullname)` | `assign_qc_expert` | |
| `surfk.complete_qc_review(qc_case_document_id, conclusion_code, has_remarks bool, revision_comment)` | `complete_qc_review` | |
| `surfk.get_qc_tasks(user_iin)` | `get_qc_tasks` | |
| `surfk.get_user_roles(user_iin)`, `surfk.check_user_role(user_iin, role_code, controlling_body_code)` | roles | |
| `surfk.send_document_to_audit_object(case_id, document_id, sender_iin, sender_fullname varchar(500), requires_acknowledgment, expires_days)` | `send_to_audit_object` | `(success, notification_id, error_message)` |
| `surfk.acknowledge_document(notification_id, acknowledger_iin, acknowledger_fullname, comment text, signature_data text)` | `acknowledge_document`, `oa/acknowledge` | `(success, error_message, …)` |
| `surfk.change_document_approver(document_id, new_iin, new_fullname, user_iin)`, `surfk.change_document_confirmer(…)` | `change_approver/confirmer` | `(success, message)` |
| `surfk.create_full_document_snapshot(document_id)` | Workflow Update | jsonb снимок для `evga_document_versions` |
| `surfk.seed_doc_work_group(case_document_id)` | Docs: CRUD get (для M5-IPI, M6-PA-*) | сид рабочей группы документа из `case_participants` |
| `surfk.get_notification_by_document(...)` | (raw) | |

### 2.6. Sequences и форматы номеров

| Объект | Формат | Источник счётчика | Где |
|---|---|---|---|
| Дело | `CONCAT(controllingAuthorityCode, '-', TO_CHAR(CURRENT_DATE,'YY'), '-', LPAD(seq,5,'0'))` → напр. `СП-25-00123` | `surfk.get_next_case_sequence(EXTRACT(YEAR…))` | Create Case v4 `Insert Case1` |
| Подчинённое дело | `[ 'ВП-' если counter_control ] + split_part(parent_reg,'-',1) + '-' + YY + '-' + LPAD(N,6,'0') + '/' + split_part(parent_reg,'-',3)`; N = `COUNT(*)+1` подчинённых того же типа за год (гонка!) | COUNT | Sub Cases `Create Query` |
| Документ, `reg_number_format='standard'` | `TO_CHAR(CURRENT_DATE,'YYYY/MM/DD') || ' – ' || LPAD(seq,5,'0')` (в Create Case v4 и Sub Cases seq = `COUNT(*)+1` документов за год; в `create` — `get_next_doc_sequence('standard', year)`) | | |
| Документ, `reg_number_format='with_org'` | `'<reg_number_prefix>-<controlling_body_code>-' || YY || '-' || LPAD(get_next_doc_sequence('with_org',year),6,'0') || '/<case_id_part>' || CASE WHEN supports_version THEN '_1' END`, где `case_id_part = registration_number дела .split('-').pop()` | `get_next_doc_sequence('with_org')` | `Create Case Document` |
| Номер приказа при `register` | `doc_reg_number || '_P_' || get_next_doc_sequence('PRIKAZ', year)` → `order_number` в `evga_doc_audit_start_order` / `evga_doc_inspection_completion_order` | `PRIKAZ` | `Register Document Query` |
| Версия документа | `evga_document_versions.version_number = MAX+1`; `evga_case_documents.version = version_number+1` | | Workflow Update |
| ЕРСОП | `requestId` = UUID v4 (JS), `docId = case_document_id` | | ERSOP - Build |

Sequence-объект в явном виде один: `surfk.cases_id_seq` (`nextval` в Sub Cases). Остальные — внутри функций.

### 2.7. Прочие схемы, затронутые «документными» воркфлоу

`portal.documents(id, purpose_id UNIQUE, url, description, created_at, updated_at)` и `portal.users`, `portal.time_requests` — портал, не ЭВГА. `acc_100.rspns_msg_rsp(id, account_id, object_data jsonb, created_by, updated_by, updated_time, app_name)` — входящие ответы ЕРСОП. `public.users(iin, full_name_ru)` — ещё одна таблица пользователей.

### 2.8. Хранение файлов

Файлы в БД не хранятся: в `case_base_attachments.document_id`, `evga_document_attachments.file_id`, `evga_doc_apl_attachments.file_path` лежат идентификаторы внешнего «document-service» (tus upload id / file id). Загрузка/удаление — через `$env.DOCUMENT_SERVICE_URL/files/upload|/files/{path}`; base64-скачивание — через webhook `download-base64-test/…`.

### 2.9. Полная инвентаризация упоминаний `surfk.*` (все 566 воркфлоу)

Таблицы/представления (число воркфлоу, где встречаются, в скобках): `cases`(5 функций-вызовов + десятки select), `case_participants`, `case_bases`, `case_base_attachments`, `case_status_history`, `case_activity_log`, `case_qc_assignments`, `case_qc_expert_assignments`, `case_appeal_expert_assignments`, `case_audit_objects`, `case_audit_object_attachments`, `cases_list_view`, `cases_id_seq`, `case_statuses`, `audit_objects`, `evga_audit_object`, `annual_plans`, `annual_audit_events`, `plan_objects`, `materials_check`, `subj_sched_insp`, `organ_reg_checks`, `reason_extends`, `units_measurements`, `sampling_methods`, `response_measures`, `risk_object_types`, `risk_levels`, `regions`, `enforcement_agencies`, `d_controlling_orgs`, `d_query_check`, `d_query_check_npa`, `dictionaries(dic_name, code, name_ru, name_kz)`, `offense_type(type_code, parent_code, offence_name_ru/kz, offence_type_ru/kz, level_ru/kz)`, `offence_kind_consequence`, `audit_results`, `audit_types`, `inspection_types`, `controlling_bodies`, `control_reasons_types`, `check_initiators`, `organizational_legal_forms`, `employees`, `departments`, `positions`, `users`, `evga_roles`, `evga_user_roles`, `evga_users_with_roles`, `evga_control_spheres`, `evga_legal_basis_audit`, `evga_audit_questions(code_id, reg_number, theme_ru/kz, sub_theme_ru/kz, program_ru/kz, npa)`, `evga_case_audit_questions`, `evga_document_types`, `evga_document_stages`, `evga_document_statuses`, `evga_document_mappings`, `evga_available_document_types`, `evga_case_documents`, `case_documents`/`document_statuses` (устаревшие имена в `Check Transition Query` неактивной копии), `evga_document_approvals`, `evga_document_signatures`, `evga_document_workflow_history`, `evga_document_versions`, `evga_audit_log`, `evga_document_action_types`, `evga_document_timeline`, `evga_dashboard_stats`, `evga_status_transitions`, `evga_document_attachments`, `evga_audit_object_notifications`, `oa_notifications`, `evga_qc_requests`, и все `evga_doc_*` из §2.4.

---

## 3. Каталог API старого бэкенда

Базовый URL — `{N8N_WEBHOOK_BASE_URL}/webhook/`. Метод `None` в экспорте = GET по умолчанию. `<wf>` — сегмент, который n8n добавляет к путям, начинающимся с `/` (в экспорте не виден; из HTTP-вызовов Create Case v4 известны префиксы `add-case-participants`, `case-set-party-lead`).

### 3.1. Дела

| Метод, путь | Воркфлоу | Вход | Выход | Примечания |
|---|---|---|---|---|
| `POST evga/cases` | Create Case v4 | body: `bin`(12 цифр, обяз.), `organizationName`/`organizationNameRu`/`organizationNameKz`, `opfName`, `address`, `director`, `inspectionTypeCode` (`'1'`\|`'2'`, обяз.), `inspectionKindId`, `auditTypeId` (7\|8, обяз.), `controllingAuthorityCode` (обяз.), `controllingAuthorityName`, `participatingAuthorities[{code}]` (первый БИН → `joint_inspection_bin`), `bases[{type, initiator, documentNumber, date, fileAttachments[{file_id,file_name}]}]`, `startDate`, `endDate`, `auditGoalRu/Kz`, `authorIin` (обяз., либо deprecated `authorId`), `authorFullname`, `isElectronicAudit`, `isDSP`, `workGroupMembers[{iin,isLead}]` (обяз. ≥1 и ровно один лидер; back-compat `workGroupUserIins[]`) | 201 `{success, message:'Дело успешно создано', data:{id, registrationNumber, createdAt}}` | см. §4.1 |
| `GET evga/cases?page&limit(≤100)&search&status_id&controlling_body_id&lang` | Cases - List (off) | | `{success, data:[cases_list_view…], pagination, filters}` | search по `registration_number`, `audit_object_name_ru` |
| `GET <wf>/:id?lang=ru|kk` | Get Case Detail | | `{success, data:{…cases, audit_object{}, controlling_body{}, status{}, audit_type{}, inspection_type{}, inspection_kind{}, bases[{…, attachments[]}], work_group[], author{}, approver{}, supervisor{}, can_edit}}` \| 404 | `can_edit = status.code != 'closed' AND все документы status_id IN (1,2)` |
| `PATCH evga-case-update/update` | Case Update (Extended) | `case_id` + любое из `audit_goal_ru/kz, is_electronic_audit, is_dsp, inspection_kind_id, status_id, bases[], workflow_state | available_actions+is_editable+process_instance_id` | `{success, data:{id, registrationNumber, …, workflowState}}` | bases заменяются целиком и только для внепланового (`inspection_type_id = 6`) |
| `POST evga-case-delete/delete` | Cases - Delete | `caseId`, `deletedByIin`/`x-user-iin` | `{success, data:{id, registrationNumber, deletedAt}}` | soft delete + `case_activity_log('deleted')` |
| `POST evga-case-status/update` | My workflow 31 | `case_id, status_id` | `{success, data:{id, registration_number, status_id}}` | прямая смена статуса без истории |
| `POST evga/cases/bases` | Get Case Bases | `case_id` | `{success, data:[bases + reason_code], total, qc_route:'KK KVGA'|'KK'}` | `qc_route='KK KVGA'` если есть основание с `reason_code ∈ {'13','14'}` **и** `inspection_type_id = 6`; вызывается из BPMN дела |
| `POST evga/check-audit-type` | Check Audit Type | `caseId` | `{success, isPlanned, auditTypeCode, caseId}` | `isPlanned = inspection_types.code ∈ {'1','scheduled'}`; вызывается из BPMN |
| `GET listPreAudits?caseId` | get_previous_audit_list_by_bin | | `{success, case_id, period_from, period_to, audit_start_date, audit_end_date, audit_questions[], previous_audits[]}` | другие дела с тем же БИН; периоды из `evga_doc_ps_audit_questions` |
| `GET oa/cases?user_bin&page&limit&search&status_id&controlling_body_id&lang` | OA get case | | как Cases - List | дела, у которых есть документ, побывавший в `sent_to_audit_object`, или документ `M28-OPM` |
| `GET ak/cases?…`, `GET ak/:caseId/documents?lang` | list-ak-cases, get-ak-case-documents | | список дел/документов со `status_id = 49` (`sent_to_ak`) | Аудиторский комитет |
| `GET qc/cases?qc_head_iin&qc_expert_iin&controlling_body_code&status_id&search&page&limit&lang` | list-qc-cases | | как Cases - List (+`audit_object_*`, `controlling_body_code`) | без фильтров по ИИН — `status_id IN (11,12)` |
| `POST cases/:caseId/send-to-qc` | send-case-to-qc | `user_iin, user_name, user_keycloak_id, comment, qc_head_iin, qc_head_fullname, action_code ('send_to_qc' default \| 'change_qc_head')` | `{success, data:{case_id, qc_head_iin, qc_head_fullname, action, zeebe_event_sent, message}}` | пишет `cases.qc_head_*`, `case_qc_assignments`; шлёт событие процессу дела (кроме `change_qc_head`) |
| `POST assign-qc-expert/cases/:caseId/assign-qc-expert` | assign-expert-to-case | `user_iin, user_name, comment, qc_expert_iin, qc_expert_fullname, action_code ('assign_qc_expert')` | `{success, data:{case_id, qc_expert_iin, qc_expert_fullname, message}}` | пишет `cases.qc_expert_*`, `case_qc_expert_assignments`; затем `POST evga/zeebe` (неактивная версия вместо этого проверяла «уже назначен» → 400) |
| `GET qc/cases/:caseId/assigned-expert` | get-assigned-expert | | `{success, data: assignment|null}` | |
| `POST evga/case-action` | Case Action → Zeebe Event | `caseId, actionCode, performedByIin (обяз.), assignedToIin, documentId, documentTypeId, comment` | `{success, data:{caseId, actionCode, processInstanceId, message}}` | событие процессу дела + `evga_audit_log(entity_type='case')` |
| `POST evga/qcs2/violations` | violations | `case_id` | `{success, data:[нарушения из M18-RNS и M18-RNAFO с объектами риска, суммами, возражениями]}` | для КК 2 этапа; большой UNION-запрос (см. `out/violations__8L2Xyc6HTmgwJTZD.txt`) |

### 3.2. Подчинённые дела — `POST evga/sub-cases` `{action, params}`

| `action` | params | Логика | Ответ |
|---|---|---|---|
| `create` | `parent_id, sub_case_type ('admin_violation'|'counter_control'), sub_case_data{}, author_iin, author_keycloak_id` | для `admin_violation` — гейт `check_sub_case_creation_condition` (иначе `{success:false, error: reason|'ADMIN_VIOLATION_NO_GROUNDS'}`); INSERT в `cases` (status `open`, `audit_object_id`/`author_id` наследуются от родителя, номер §2.6); затем начальный документ: `M39-ADM-PROT` → `evga_doc_admin_offense_protocol` или `M43-VK-POR` → `evga_doc_counter_control_poruchenie` (статус `draft`, стандартный номер), старт его Zeebe-процесса, сохранение `zeebe_process_instance_id` | `{success, data:{id, registration_number, status:'open'}}` |
| `get` | `id` | подчинённое дело (`parent_id IS NOT NULL`) | `{success, data:{id, parent_id, sub_case_type, sub_case_data, registration_number, author_*, created_at, updated_at, status}}` |
| `list` | `parent_id` | все подчинённые дела родителя | `{success, data:[…]}` |
| `close` | `id, user_iin, user_fullname` | `surfk.close_admin_violation_case` | `{success, data:{id, status}}` \| `ADMIN_VIOLATION_CLOSE_FAILED` |
| `delete` | `id, user_iin` | `surfk.soft_delete_admin_violation_case` | `{success, data:{id, registration_number}}` |
| `can_create_admin_violation` | `parent_id` | `check_sub_case_creation_condition(parent_id,'admin_violation')` | `{success, data:{can_create, reason}}` |
| `admin_violation_grounds` | `parent_id` | `get_admin_violation_grounds` | `{success, data:{grounds:[code…]}}` |

### 3.3. Рабочая группа

| Метод, путь | Воркфлоу | Вход | Выход |
|---|---|---|---|
| `POST add-case-participants/add-participants/:caseId` | Add Case Participants (on) | `userIins[]` (12 цифр), `assignedByKeycloakId` | 201 `{success, message, data:{participantsAdded}}`; 400 `INVALID_CASE_ID|MISSING_USER_IINS|INVALID_USER_IINS`; 404 `CASE_NOT_FOUND`. Старая версия (off) принимала `employeeIds[]` и писала `employee_id` |
| `POST <wf>/delete-participant/:caseId` | Delete Case Participant | `participantId`, `removedByKeycloakId` | soft delete (`is_active=false, removed_at, removed_by`); 404 `PARTICIPANT_NOT_FOUND` |
| `POST case-set-party-lead/set-party-lead/:caseId` | Set Case Party Lead | `userIin` | `{success, data:{caseId, leadIin, leadFullName}}`; участник должен быть активным членом группы |
| `GET <wf>/cases/:caseId/work-group` | Get Case Work Group | | `{success, data:[{id, user_iin, user_fullname, user_position, role_id, role_code, role_name_ru/kz, role_level, controlling_body_*, can_*_documents, is_lead, is_active, assigned_at}]}` (лидер первым) |
| `POST work-group-approval` | Work Group Approval | `documentId`, `action ∈ {init, init_invited_experts, sign, approve, check}`, `userIin`, `signature`, `comment` | `init`: создаёт `work_group_pending`-подписи для всех активных участников дела (в т.ч. лидера); `init_invited_experts` — для `member_role_code='invited_expert'` акта обмера; `sign`: `pending → signed`, история `sign_work_group`, если pending=0 → событие Zeebe `work_group_complete`; `check`: список подписей, `allSigned` = все не-лидеры подписали; `approve`: только если у не-лидеров pending=0 → подпись лидера, история `approve_work_group`, событие Zeebe `approve_work_group` |

### 3.4. Документы — роутер `POST evga/documents` `{action, params}`

Активный обработчик — монолит `EVGA Additional Actions` (`VMkW67X9Wz5jfxh8`). Роутер `EVGA Documents Router` (тот же путь, включён, но его саб-воркфлоу выключены) распределяет по доменам согласно словарю `MAP` (`Route To Domain`); действия вне словаря уходят в `generic`. Ниже — объединённый список: домен по `MAP`, реализация по монолиту (и по `EVGA Docs: *`, где она отличается).

**Домен `crud`**

| `action` | params | Что делает | Ответ |
|---|---|---|---|
| `mapping` | `document_type_id` (в Docs: CRUD также `document_type_code`) | `evga_document_mappings` + тип + этап | `{success, data:{document_type_id, document_type_name{ru,kz}, stage{id,name_ru}, root_table, fields_mapping, subtables_mapping, form_schema}}` |
| `list` | `case_id` (обяз.), `document_type_id`\|`document_type_ids[]`\|`document_type_codes[]`, `status_code`, `stage_id`, `page=1`, `limit=50` | документы дела верхнего уровня (`parent_document_id IS NULL`, `is_deleted=false`), с типом/статусом/этапом, `status_timestamps` (jsonb `{status_code: last_at}` из workflow_history), `creator_roles` | `{success, data:[…], count}` |
| `list_children` | `parent_id`\|`parent_document_id`, `document_type_id`, `document_type_codes[]`, `status_code`, `embedded_only`, `embedded_role`, `page`, `limit` | дочерние документы | `{success, data, count}` |
| `get` | `document_id`\|`case_document_id` | шапка + маппинг + дело (`case_info`) + `fields` (строка `root_table`) + `subtables{key:[rows]}` (UNION ALL по `subtables_mapping`, включая `overlay_source` и `nested_subtables`), `form_schema`; в Docs: CRUD дополнительно «ленивый сид» (`seed_from`, сид вопросов программы из `evga_case_audit_questions`, `seed_doc_work_group` для M5-IPI/M6-PA-*) и переопределение `workflow_state` для `embedded_role` | `{success, data:{case_document_id, case_id, document_type_id, document_type_code, document_type_name, status{code,name_ru,name_kz}, registration_number, author_*, version, approver_*, confirmer_*, kvga_confirmer_*, submitted_at, approved_at, confirmed_at, audit_object_acknowledged_*, returned_*, return_comment, zeebe_process_instance_id, workflow_state, embedded_meta?, fields, subtables, case_info{…}}, form_schema}` |
| `create` | `case_id`, `document_type_id`\|`document_type_code`, `data{}`, `user_iin`, `parent_document_id`, `embedded_role`, `source_document_id`, `is_embedded` | проверки: маппинг активен; дубликат (если `allow_multiple=false` и есть неудалённый); в Docs: CRUD — `check_document_creation_condition`; INSERT `evga_case_documents` (статус `draft`, для `document_type_id=6` — `open`; номер §2.6) → INSERT в `root_table` по `fields_mapping` → `Get Zeebe Process Info` → старт Zeebe (саб-воркфлоу) → `zeebe_process_instance_id`; история `create` | `{success, data:{case_document_id, root_id, zeebe_process_instance_id}, zeebe_error, zeebe_skipped_reason}` |
| `update` | `document_id`, `data{}`\|`fields{}`, `subtables{key:[rows]}` | `UPDATE root_table SET …` по `fields_mapping` (+`updated_at`), затем подтаблицы: `DELETE … WHERE fk = root_id [AND filter]; INSERT …` для каждой (в Docs: CRUD — с поддержкой родитель/дочерние подтаблицы через `fk_source`, `_tempId`, CTE `WITH ev AS (INSERT … RETURNING id)`); после — «Auto Copy»: если документ M5-IPI (id=1) → копирование `evga_doc_ps_audit_questions` в пустые `evga_doc_ap_questions` программ (`document_type_id IN (2,47)`) того же дела | `{success, data:{case_document_id, updated:true, subtables_updated}}` (+`auto_copy{programs_updated, questions_copied}`) |
| `delete` | `document_id`, `user_iin`, `user_fullname` | soft delete (Docs: CRUD — каскадно `embedded_role`-дочерние); история `delete`; Docs: CRUD `Resolve Next Doc`: после удаления M19-AD → событие `doc_approved` отчёту M17-AO-*; после удаления M25-PRED при `M24-AZK` в `approved` → событие дела `ready_send_to_qc_3`; карта `{'M9-AZ':['M7-POR'], 'M8-PLAN':['M9-AZ']}` → событие `prev_approved` следующему документу, если он ещё `draft` без `submit` | `{success, data:{deleted:true, case_document_id}}` |
| `get_case_document_subtable` | `case_id`, `document_type_id`\|`document_type_code`, `subtable_key` | строки подтаблицы «активного» документа типа (`status_id NOT IN (3,22)`, последний по `created_at`) | `{success, data:[…]}` |
| `get_sibling_subtable` | `document_id`\|`case_document_id`, `subtable_key`\|`subtable_name` | строки подтаблицы данного документа | `{success, data}` |

**Домен `lifecycle`** (каждое действие: UPDATE статуса → INSERT `evga_document_approvals` и/или `evga_document_workflow_history` → саб-воркфлоу `Zeebe: Send Event` (`TASK_COMPLETE_EVENT`, `correlationKey = String(case_document_id)`, `eventData:{actionCode, performedByIin, documentId}`) → ответ `{success, data:{case_document_id, status, zeebe_event_sent, zeebe_skipped}, zeebe_error}`)

| `action` | params | Статус → | Побочные эффекты |
|---|---|---|---|
| `submit` | `document_id, user_iin, submitter_fullname, comments, signature, signer_certificate, approver_iin/fullname, confirmer_iin/fullname, kvga_confirmer_iin/fullname` | `pending_approval` (только если `check_document_submit_allowed` = true, иначе `{success:false, error: reason}`) | `submitted_at`, назначенные согласующий/утверждающий/КВГА; approvals `submitted` |
| `approve` | `document_id, user_iin, user_fullname|approver_name|user_name, comment` | `approved` | `approved_at` (в активной версии); approvals `approved` |
| `reject` | `document_id, user_iin, comment|comments` (обяз.) | `revision` | approvals `revision` |
| `return` | `document_id, user_iin, user_fullname, comment` | `revision` | `returned_by_*`, `return_comment`, `returned_at`; approvals `returned` |
| `send_to_confirmation` | `document_id, user_iin, user_fullname, confirmer_iin/fullname, kvga_confirmer_iin/fullname, comment` | `pending_confirmation` | approvals `sent_to_confirmation`; в eventData ещё `confirmerIin` |
| `confirm` | `document_id, user_iin, user_fullname, comment` | `confirmed` | `confirmed_by_*`, `confirmed_at`; approvals `confirmed` |
| `direct_confirm` | `document_id, user_iin, user_fullname` | `confirmed` | history `direct_confirm` («Утверждено руководителем КК (без эксперта)», `is_signed=true`) + approvals |
| `activate` | `document_id, user_iin, user_fullname` | `active` | history `activate`, approvals `activated` |
| `register` | `document_id, user_iin, user_fullname` | `registered`; `workflow_state.available_actions := []` | `order_number` приказа (§2.6), history `register` |
| `change_approver` / `change_confirmer` | `document_id, new_approver_iin/fullname` (`new_confirmer_*`), `user_iin` | без смены статуса | функции `change_document_approver/confirmer`; Docs: Lifecycle пишет `evga_audit_log` с комментарием «Согласующий изменён на: …» |
| `sign_work_group` | `document_id, user_iin, user_fullname, signature` | без смены статуса | (Docs: Lifecycle) `work_group_pending → work_group_signed`, history `sign_work_group`; событие Zeebe `work_group_complete` если все подписали, иначе `sign_work_group` |
| `acknowledge_document` | `notification_id, acknowledger_iin, acknowledger_fullname, comment, signature_data` | — | `acknowledge_document(...)`; событие Zeebe `accept` |
| `acknowledge_case_document` | `case_document_id, acknowledger_iin, acknowledger_fullname, signature_data` | без смены статуса | (Docs: Lifecycle, DEVEMF2-2304) `audit_object_acknowledged_at/by` + подпись `oa_acknowledge`; Zeebe не трогает |
| `approvals` | `document_id` | — | `{success, data:[approvals…], count}` |

**Домен `qc`**: `send_to_qc(case_id, qc_stage=1, requested_by_iin, requested_by_fullname, controlling_body_code, comment)` → `send_case_to_qc`; `assign_qc_expert(request_id, qc_head_iin, expert_iin, expert_fullname)`; `complete_qc_review(qc_case_document_id, conclusion_code, has_remarks, revision_comment)`; `get_qc_tasks(user_iin)`; `get_qc_requests(controlling_body_code)` → `evga_qc_requests WHERE status='pending'`; `qc_close_document(document_id, user_iin)` → статус `closed` + событие `qc_close`.

**Домен `kvga-reestr`** (`embedded_role IS NULL` — встроенные документы не переводятся)

| `action` | Статус → | Записи |
|---|---|---|
| `send_to_kvga` / `send_to_reestr_confirmer` | `pending_kvga` (audit_log: `pending_reestr_confirmation` для reestr) | `kvga_confirmer_*`; history «Отправлен на подтверждение КВГА» |
| `kvga_confirm` / `reestr_confirm` | `kvga_confirmed`, `kvga_confirmed_at` | history («Подтвержден КВГА» / «Подтвержден подтверждающим реестра»), approvals `kvga_confirmed`, подпись `kvga_confirm` (если передана `signature`) |
| `kvga_return` | `revision` | `returned_by_*`; history `kvga_return`; approvals `kvga_returned` |
| `kvga_reject` / `reestr_reject` | `rejected` | history; approvals `kvga_rejected`; подпись `kvga_reject` |
| `change_kvga_confirmer` / `change_reestr_confirmer` | без смены | `kvga_confirmer_iin/fullname := new_*` |

**Домен `case-misc`**

| `action` | params | Что делает |
|---|---|---|
| `send_to_audit_object` | `case_id, document_id, sender_iin, sender_fullname, requires_acknowledgment=true, expires_days=5` | `send_document_to_audit_object` → `notification_id`; событие `send_to_audit_object`; (Docs: Case Misc также `POST evga/invited-specialist-account` — отзыв аккаунтов приглашённых специалистов) |
| `submit_objection` | `notification_id, objector_iin` | документ → `signed_with_objection`; событие `objection` |
| `create_objection_doc` | `parent_document_id, creator_iin, creator_fullname` | создаёт `M20-VOZ` (дочерний, `draft`, стандартный номер, `metadata` + `evga_doc_audit_objection`, `workflow_state` с действиями `save`/`submit` для ролей `oa_responsible`/`audit_object`, `source:'n8n'`); старт процесса `M20-VOZ` |
| `send_to_ak` | `document_id, sender_iin, sender_fullname, signature_data` | `sent_to_ak`, `available_actions := []`; history с `signature_data` (обрезка 1000) |
| `close_case` | `document_id, user_iin, user_fullname` | дело → `closed` (активная версия; неактивная C4FI писала `qc_approved`) + `case_status_history` («Дело закрыто после утверждения ЗКК») |

**Домен `roles`**: `get_roles` (активные `evga_roles`), `get_user_roles(user_iin)`, `get_users_by_role(role_code)`, `get_all_user_roles` (только в активной копии; активные `evga_user_roles` с ролью и органом), `check_user_role(user_iin, role_code, controlling_body_code)`.

**Домен `meta`**

| `action` | params | Ответ |
|---|---|---|
| `get_document_types` | — | `evga_available_document_types` |
| `get_available_actions` | `document_id, user_iin` | `{success, data:[{action_code, action_name_ru/kz, action_icon, action_color, requires_signature, requires_comment}], count, source, debug}` — см. §4.6 |
| `can_create` | `case_id, document_type_id` | `{can_create, reason}` |
| `get_available_for_case` | `case_id, user_iin, stage_id` | типы из `get_available_document_types_for_case` |
| `check_transition` | `document_id, target_status` (в активной копии параметры перепутаны: `document_type_id`/`from_status_id`) | `{allowed, blocking_reason?{type, message_ru/kz, blocking_document{…}}}` |
| `get_blocking_statuses` | `case_id` | список блокировок по типам |
| `get_dashboard_stats` | `controlling_body_code?` | `evga_dashboard_stats` |
| `get_document_timeline` | `document_id` | `evga_document_timeline` |
| `signatures` | `document_id` | `evga_document_signatures` (без поля `signature`) |
| `versions` | `document_id` | `evga_document_versions` |

**Домен `generic`** (`Generic Action Check`): любой из `WORKFLOW_ACTIONS` без специальной ветки → INSERT в `evga_document_workflow_history` (from=to=текущий статус) → событие Zeebe с этим `action_code`. Список: `submit, approve, confirm, return, resubmit, sign, activate, reject, send_to_approval, send_to_confirmation, send_to_confirm, change_approver, change_confirmer, return_from_approval, return_from_confirmation, return_to_revision, return_for_revision, send_to_oa, send_to_audit_object, send_to_oa_confirmation, send_to_auditor, receive, acknowledge, oa_confirm, oa_acknowledge, resend_to_oa, review_decision, send_to_qc, acknowledge_qc, assign_expert, qc_confirm, qc_return, qc_approve, expert_approve, create_zkk, sign_zkk, submit_confirm, qc_close, send_to_ak, send_to_vap, send_to_ersop, send_to_court, send_to_law_enforcement, send_to_po, register_ersop, ersop_registered, ersop_rejected, vap_confirmed, vap_rejected, provide_info, accept_info, refuse_info, reject_info, review_info, mark_refused, overdue, objection, oa_objection, accept, partial_accept, sign_with_objection, sign_without_objection, send_to_kvga, kvga_confirm, kvga_return, kvga_reject, direct_confirm, sign_and_activate, send_to_signing`. Иное → `{success:false, error:"Action '…' is not a workflow action"}`.

### 3.5. Прочие документные endpoints

| Метод, путь | Воркфлоу | Вход | Выход / логика |
|---|---|---|---|
| `GET evga-case-documents/:caseId` | Get Case Documents (on) | | все типы документов (фильтр по `audit_type_codes` дела) LEFT JOIN документы дела; отсутствующие — статус `inactive` «Не активный»; `{success, data:[{id, case_id, registration_number, document_type{}, stage{}, status{}, author{}, metadata, created_at, updated_at, is_active}], pagination, meta}` |
| `GET evga/available-document-types/:case_id` | Get Available Document Types | | типы, которые можно создать вручную: `is_child_only=false AND is_manually_creatable AND creator_roles @> '["auditor"]' AND (audit_type_codes пуст OR содержит код типа аудита дела) AND (allow_multiple OR нет неудалённого документа (с учётом block_recreate_after_delete))`; группировка по этапам через `DOC_PLACEMENT` |
| `POST evga/check-docs-status` | Check Documents Status | `case_id, doc_types[codes], status` | `{success, data:{allMatched, allExistingMatched, requiredCount, foundCount, matchedCount, targetStatus, docs:[{doc_type, status, matched}]}}`; берётся последний (`id DESC`) неудалённый документ каждого типа; `allExistingMatched` — «все существующие в целевом статусе (и хотя бы один есть)» для BPMN-гейтов |
| `GET evga/document-history?document_id&page&page_size(≤100)` | Document History Record | | `{success, data:[{id, status, action_code, field_changes, from/to_status_code, to_status_name, approver_iin, approver_name, comments, created_at, source, action_name_ru}], total, page, page_size}` из `evga_audit_log`; тот же воркфлоу как саб-воркфлоу принимает `{entity_type, document_id, case_id, action_code, user_iin, user_fullname, status, from_status_code, comment, source}` |
| `GET evga/documents/verify?docId` | Document Verify (Public) | | `{success, data:{document_id, document_type_name, case_number, status_name, status_code, created_at, signatures:[{signer_iin, signer_name, signature_type, signed_at}]}}`; CORS `*`; **в SQL захардкожен `d.id = 2854`** (баг); ни QR, ни hash — только id |
| `POST evga/qc-conclusion` | QC Conclusion Workflow | `action ∈ {get, update, sign, send_to_confirmation, confirm, return_for_revision, change_confirmer, activate, get_available_actions}`, `params.document_id, user_iin, user_fullname, fields{}, signature, confirmer_iin, comment` | параллельная (не через маппинг) реализация ЗКК: прямые UPDATE `evga_doc_quality_control_conclusion`, статусы `signed → pending_confirmation → confirmed → active`/`revision`, подписи `sign`/`confirm`, история; `get_available_actions` — из `evga_status_transitions` (единственное место!) |
| `POST evga/audit-assignment-questions` | audit-assignment CRUD | `action save|delete, id, audit_assignment_id, question_id, question_code, question_text, start_date, end_date, working_days, assignees[{full_name, position, role}]` | insert/update строки + полная замена `evga_doc_aa_assignees` |
| `POST evga/audit-objects-apl` | audit-objects-apl CRUD | `action save|delete, id, audit_plan_id, audit_object_bin, …, members[{member_iin, member_fullname}]` | аналогично для плана |
| `POST evga/invited-specialist` | Invited Specialist | `action ∈ {send_to_invited_specialists, sign_invited_specialist, get_documents, check_signed}` | статус `pending_invited_specialist_sign`, подписи `invited_specialist_pending/signed`, событие Zeebe `sign_invited_specialist{allInvitedSigned:true}` когда все подписали |
| `POST evga/info-request` | Info Request API (off) | действия по требованию сведений (send to OA / to auditor / reject / return to OA / item accept / cancel accept / item return / add answer / add item) | таблицы `evga_doc_info_request`, `evga_doc_ir_questions`; коды действий в экспорте видны только по именам узлов |
| `POST oa/acknowledge` | acknowledge-document | `notification_id, acknowledger_iin, acknowledger_fullname, comment, signature_data` | `acknowledge_document` + `workflow_state := {available_actions:[], is_editable:false, source:'n8n'}` |
| `POST registration-card-created` | Copy Poruchenie → Registration Card | `case_id, document_id` | копирует из M7-POR (`registration_number → uo_check_number`, даты) в `evga_doc_registration_card` |
| `GET activity-log?case_id|entity_id&entity_type&action_type&date_from&date_to&limit(≤500)&offset` | Get Activity Log | | `evga_audit_log` с `COUNT(*) OVER()` |
| `GET evga/references/audit-result?search&limit&offset&lang`, `GET evga/references/offense-type/tree?lang` | справочники | | `audit_results`; рекурсивное дерево `offense_type` (готовый jsonb из SQL) |

### 3.6. Zeebe-ориентированные (внутренние) endpoints

| Метод, путь | Воркфлоу | Вход | Логика |
|---|---|---|---|
| `POST evga/zeebe` | EVGA Zeebe Integration | `action ∈ {start_process, publish_message, publish_case_message, trigger_doc_message}`, `params` | `start_process(document_id, case_id, document_type_id, author_iin, author_fullname)`: `zeebe_process_id` из типа + флаги → `POST /process-instances?processId=…` body `{documentId, caseId, documentTypeId, authorIin, authorFullname, requiresApproval, requiresConfirmation, requiresKvga, controllingBodyCode, auditTypeCode, isRecreated}` → `zeebe_process_instance_id`. `publish_message(document_id, action_code, user_iin, user_fullname, document_type_id, comment, extra_variables{deadlineDatetime})` → событие документу + `evga_audit_log`. `publish_case_message(case_id, action_code, user_iin, user_fullname, document_id, assigned_to_iin, comment)` → событие процессу дела. `trigger_doc_message(case_id, doc_type, action_code, user_iin, user_fullname, comment)` → событие последнему документу типа `doc_type` дела (BPMN вызывает 32 раза, напр. `signed_automatically` отчёту `M17-AO-*`) |
| `POST evga/workflow-update` | Workflow Update (Zeebe→PG) | `documentId, newStatus (обяз.), isEditable, availableActions[], performedByIin, performedByFullname, actionCode ('status_change'), comment, processInstanceId, shouldCreateVersion, newCaseStatus` | (опц.) снимок версии → `UPDATE evga_case_documents SET status_id=(code=newStatus), workflow_state=…` → `evga_document_workflow_history` → (опц.) `UPDATE cases SET status_id=(code=newCaseStatus)`. 461 вызов из BPMN — это **основной механизм смены статуса документа** |
| `POST evga/case-workflow-update` | Case Workflow Update | `caseId, newStatus?, isEditable, availableActions[], performedByIin, performedByFullname, actionCode ('case_status_change'), comment, processInstanceId` | `UPDATE cases` (статус только если код существует) + `case_status_history` |
| `POST evga/case-workflow-log` | Case Workflow Log | `caseId, performedByIin, performedByFullname, actionCode, comment, documentId, processInstanceId` | `case_status_history` (old=new=текущий) |

Саб-воркфлоу (Execute Workflow): `Zeebe: Start Process` (`processId, documentId, caseId, authorIin, auditTypeCode[, isRecreated]` → `{success, processInstanceId, error, skipped}`), `Zeebe: Send Event` (`processInstanceId, eventName='TASK_COMPLETE_EVENT', correlationKey, eventData, jwtToken` → `POST /process-instances/event?processInstanceId=…` body `{eventName, processVariableName:'taskVariable', correlationKey, eventData}` → `{success, error, skipped}`).

### 3.7. ЕРСОП и внешние системы

| Метод, путь | Воркфлоу | Логика |
|---|---|---|
| `POST evga/ersop` | EVGA ERSOP Workflow | `action='send_to_ersop'` (`document_id, user_iin, user_fullname, signature`): `POST ersop/send-document {documentId}` → если в ответе `ersopResponse.data` содержит `'oK!'` → статус `sent_to_ersop`, approvals `sent_to_ersop` («Подписан ЭЦП и отправлен в ЕРСОП»), событие Zeebe `send_to_ersop`; иначе 422. `action='check_status'` (`document_id, user_iin`): `GET getErsop?requestId=<document_id>` → `confirmstatusid`: `'1'`→`registered_ersop`/`ersop_registered`, `'2'`→`rejected_ersop`/`ersop_rejected`, `'3'`→`sent_revision_ersop`/`ersop_revision`; есть ответ без решения → `pending_for_consideration`/`ersop_accepted`; `successful=0`/`error` → `draft`/`ersop_error`; нет ответа → `{success, pending:true}`. При финале — статус, approvals, событие Zeebe с `action_code` |
| `POST ersop/send-document` | ERSOP - Build and Send from Document | `documentId` (учётная карточка): грузит `evga_doc_registration_card` + `d_query_check_npa` + `evga_legal_basis_audit` + `evga_doc_rc_work_group` + первое вложение (base64) → JSON `{systemId:'10002', requestId:uuid, docId, requestDate, messageType:'M_TYPE_STARTED', message:{started:{number(≤21), organCode, typeCheckCode(inspection_kind_id), typeAuditCode(audit_types.ersop_code), checkDate, beginDate, endDate, periodBegin, periodEnd, oraganCodeKPSSU, shortFabula/Kz, faces[{iin, lastName, firstName, middleName, positionRU/KK/QAZ, organizationNameRU/KK/QAZ, phone, mobile}], checkQuery{checkQueryCode:'0'+code, checkThemeCode:'0'+npa_code}, files[{fileName, mimeType, fileLang, fileDesc, fileBase64}], SubjectInfo{subjectId, bin}, ObjectInfo{objId}, userCreate{…}, userSign{…}}}}` → `POST ersop-requset` (SOAP). **`userCreate/userSign`, телефоны — MOCK-константы** (`Иванов Василий Петрович`, ИИН `123456789123`) |
| `POST ersop-requset2` (SEND_REQ_TO_ERSOP, off) / `ersop-requset` | сборка SOAP `<smar:sendMessageRequest><Notice>…` для `SI_SUR2ERSOP_RequestSubjectAsync` (`http://minfin.kz/ERSOP`) по `messageType`: `M_TYPE_STARTED, M_TYPE_PROLONGED (CheckId, ProlongBegin, ProlongEnd, ReasonProlongCode, Note, FilesContent, UserSign), M_TYPE_PERIOD_CHANGED (PeriodBegin/End), M_TYPE_RESUMED (ResumeDate), M_TYPE_SUSPENDED (SuspendDate, ReasonSuspendCode), M_TYPE_STOPED (ReasonRefuseCode, ReasonCancelCode, ReasonCeaseCode, Who*Code), M_TYPE_EXECUTORS_CHANGED (Faces/Experts), M_TYPE_FINISHED (FactBeginDate, FactEndDate, ResultCheckCode, AmmountLoss/Return/State/Procedural/Ineffect/Other, SendCourtCode, LawOrgCode, SendDate, TalonQuery…)` | полный список тегов — `out2/SEND_REQ_TO_ERSOP__EONQxH4A8o5mpf8V.txt` |
| `POST sendStartedFormErsop` | ersopStarted1pForm | тот же `Started` из готового JSON; успех = ответ содержит `'oK!'` |
| `POST sendErsop?bin&systemId&docId` | restErsop | входящий/исходящий `RequestSubject` (запрос субъекта по БИН); ответ записывается в `acc_100.rspns_msg_rsp` |
| `GET senReqtErap?bin|iin&limit&page` | sendRequestErap | ЕРАП `admCasesSearchRequest` (адм. дела по БИН/ИИН) |
| `POST findJurByBin` | Service GDBJL surfk (off) | ГБД ЮЛ `getJurInfoByBin` → `{bin, regStatus, fullName{ru,kz}, shortName, orgForm(Code), ownership, head{iin, fullName}, address{…}, activityKinds, founders[]}` |

### 3.8. Не-ЭВГА (портал) — исключить

`POST documents` (upsert `portal.documents` по `purposeId`, роли `portal_admin|admin`), `GET documents`, `POST document-uploaded` (только аудит-лог tus-загрузки), `DELETE document-file` (прокси удаления файла), `POST worktime/requests` (`portal.time_requests`). Все пишут структурированный лог в RabbitMQ (`$vars.RABBITMQ_LOG_QUEUE`, `eventType: DATA_CHANGE|DATA_ACCESS|AUTH_FAILURE|VALIDATION_ERROR`, `subject{username, efcUserId=sub, idpUserId=origin_user_id}`) — этот формат ИБ-лога может пригодиться как требование к аудиту, но к домену дел/документов отношения не имеет.

---

## 4. Бизнес-правила

### 4.1. Создание дела — `EVGA: Create Case v4 Parallel Docs`

Порядок узлов (см. `--- CONNECTIONS ---` в `out/EVGA_Create_Case_v4_…txt`):
1. `Parse & Validate`: обязательные `bin, inspectionTypeCode ∈ {'1','2'}, auditTypeId ∈ {7,8}, controllingAuthorityCode, authorIin` (или deprecated `authorId`); БИН/ИИН — `^\d{12}$`; для каждого `bases[i]` обязательны `type` и `initiator`; рабочая группа: ≥1 участник и ровно один `isLead=true`, иначе ошибки «Необходимо добавить хотя бы одного участника…» / «Необходимо назначить руководителя рабочей группы…».
2. Параллельно: `Insert Audit Object1` — upsert `audit_objects` по `bin` (`ON CONFLICT (bin) DO UPDATE` — имя перезаписывается всегда, `name_kz/director/address_ru/org_legal_form_id` — только непустыми; ОПФ ищется `ILIKE '%opfName%'` по `name_ru`/`short_name_ru`); `Get Controlling Body1` (`controlling_bodies.code`), `Get Inspection Type1` (`inspection_types.code`), `Get Audit Type ID1` (id как есть). `Merge1` (5 входов) → `Prepare Case1` бросает, если чего-то нет.
3. `Insert Case1`: статус `open`, номер §2.6, `workflow_state` с тремя стартовыми действиями (`add_document` dropdown, `send_to_oa` dropdown, `send_to_qc` button; `allowed_roles:['auditor']`, `is_editable:true`, `source:'n8n'`).
4. Параллельно с шагом 5: `Record Case Created` → `evga_audit_log(entity_type='case', action_code='case_created')`.
5. Если есть участники → HTTP на самого себя `add-case-participants/add-participants/{id}` `{userIins, assignedByKeycloakId: authorIin}`; если есть лидер → `case-set-party-lead/set-party-lead/{id}` `{userIin}`.
6. Последовательно 5 документов со статусом `draft` и «стандартным» номером (`COUNT(*)+1` за год): `M5-IPI` (+`evga_doc_preliminary_study{is_electronic_audit, is_dsp, joint_inspection_bin}`), `M6-PA-F` если `audit_type_id = 8` иначе `M6-PA-S` (+`evga_doc_audit_program`), `M8-PLAN`, `M9-AZ`, `M7-POR`.
7. `Start Case Zeebe1`: `POST /process-instances?processId=prc_Mz6acfNa5aUKswju2gZzvA9hiNG` (BPMN `CaseProcessV1` «изменить статус дела») body `{caseId, caseNumber, authorIin, authorFullname(=organizationName без кавычек — баг), controllingBodyCode}` с bearer пользователя → `cases.zeebe_process_instance_id`, `workflow_state.process_instance_id`.
8. `Get Docs for Zeebe1` → цикл по документам с `zeebe_process_id` типа: `POST /process-instances?processId={zeebe_process_id}` body `{documentId, caseId, authorIin, auditTypeCode}` → `evga_case_documents.zeebe_process_instance_id`; `Record Doc Created` (audit_log `create`).
9. `Check Bases1` → если есть `bases`: INSERT `case_bases` (наименования из справочников по кодам) → INSERT `case_base_attachments` для `fileAttachments`.
10. Ответ 201.

Правила, которые стоит сохранить: валидация; upsert объекта аудита по БИН; статус `open`; автосоздание 5 подготовительных документов по типу аудита; рабочая группа с обязательным лидером; основания только для внепланового (правило есть в Update, в Create не проверяется). Что не сохранять: отсутствие транзакции, самовызовы по HTTP, `COUNT(*)+1`.

### 4.2. Подчинённые дела (`EVGA Sub Cases`)

* Типы: `admin_violation` (дело об административном правонарушении) и `counter_control` (встречный контроль). Гейт `check_sub_case_creation_condition(parent_id, type)` вызывается **только для `admin_violation`**; `counter_control` создаётся без проверки. Для UI есть отдельные `can_create_admin_violation` и `admin_violation_grounds` (коды оснований).
* Наследуются `audit_object_id`, `author_id` родителя; статус `open`; номер `[ВП-]<орган>-<YY>-<000001>/<хвост родителя>`.
* Сразу создаётся начальный документ (`M39-ADM-PROT` / `M43-VK-POR`) и стартует его BPMN-процесс. Закрытие/удаление адм. дела — хранимыми функциями (тел нет).
* Во фронте ЭВГА встречная проверка — дочернее дело с `parentCaseId` и набором `counter-*` документов (отчёт `evga-domain-model.md` §3.3), что совпадает с `counter_control`.

### 4.3. Статусная модель документа

Статусы `evga_document_statuses.code`, встречающиеся в n8n и в BPMN (`newStatus` в `evga/workflow-update`, число вызовов в BPMN):

| Группа | Коды |
|---|---|
| Базовые | `draft`(77), `open` (Дело КК), `pending_approval`(37), `approved`(44), `revision`(54), `return`(15), `pending_confirmation`(38), `confirmed`(6), `active`(66), `registered`(4), `closed`(3), `rejected`, `inactive` (псевдостатус «не создан») |
| Рабочая группа / КВГА / реестр | `pending_work_group_approval`(3), `pending_kvga`(3), `kvga_confirmed`(5), `pending_reestr_confirmation`, `pending_invited_specialist_sign`, `signed`(13) |
| Объект аудита | `sent_to_audit_object`(15), `oa_acknowledged`(9), `audit_object_acknowledged`, `pending_oa_confirmation`, `oa_confirmed`, `signed_oa`, `signed_by_oa`, `signed_without_objection_oa`, `signed_with_objection`, `signed_automatically`, `sent_to_oa`, `delivered_to_oa`, `sent_by_audit_object`, `awaiting_objections`, `reviewing_objections` |
| Требования сведений | `awaiting_info`, `info_accepted`, `info_refused`, `overdue`, `sent_to_auditor`/`send_to_auditor` |
| КК / АК / внешние | `sent_to_qc`, `qc_acknowledged`, `expert_assigned`, `qc_approved`, `under_review`, `accepted`, `sent_to_ak`(id 49), `sent_to_court`, `sent_to_law_enforcement`, `control`, `audit_materials_implementation` |
| ЕРСОП | `sent_to_ersop`, `pending_for_consideration`, `registered_ersop`, `rejected_ersop`, `sent_revision_ersop` |

Переходы, которые n8n делает сам (не BPMN), сведены в §3.4 («lifecycle», «kvga-reestr», «case-misc», ERSOP). Важно: **тот же переход обычно дублируется BPMN-callback'ом** `evga/workflow-update` с тем же `newStatus` и новым `available_actions`; n8n-ветка нужна только чтобы «не ждать» Zeebe и записать approvals/подписи. Например, `submit` → n8n ставит `pending_approval`, шлёт `TASK_COMPLETE_EVENT{actionCode:'submit'}`, BPMN ловит `Message_DocAction`, идёт по гейту `actionCode = "submit"` и вызывает `workflow-update{newStatus:'pending_approval', availableActions:[approve, reject…]}`.

### 4.4. `available_actions` и `get_available_actions`

Источник правды для кнопок фронта — `evga_case_documents.workflow_state.available_actions` (пишется BPMN через `workflow-update`; n8n пишет только стартовые для дела, `M20-VOZ` и `embedded`). Фильтр в `get_available_actions` (активная копия):
1. `sign_work_group` скрывается, если у пользователя уже есть подпись `work_group_signed` по документу.
2. `hasRole` = пересечение `allowed_roles` действия с ролями пользователя (`evga_user_roles`→`evga_roles.code`).
3. `assignment_type`: `workgroup` → пользователь активный участник дела; `workgroup_lead` → `is_lead`; иначе сравнение `<assignment_type>_iin` документа/дела (`approver, confirmer, kvga_confirmer, author` из документа; `qc_expert, qc_head` из дела) с ИИН пользователя.
4. Правило: для `workgroup`/`workgroup_lead` достаточно назначения (роль не нужна); для прочих `assignment_type` — роль **и** назначение; без `assignment_type` — роль; `assigned_to_iin` (legacy) даёт доступ напрямую.
5. Возвращаются `action_code, action_name_ru/kz, action_icon, action_color, requires_signature, requires_comment`.

Это правило нужно перенести в сервис вычисления доступных действий на бэкенде (вместо хранения JSON, вычислять по статусу + типу + роли + назначению).

### 4.5. Гейты BPMN через `check-docs-status`

BPMN вызывает `POST evga/check-docs-status` с наборами (из `bpmn_summary.txt`): `["M8-PLAN","M6-PA-S","M6-PA-F"]`→`approved`; `["M18-RNAFO"|"M18-RNS","M19-AD"]`→`active` (реестр по типу аудита `auditTypeCode = "16"` → RNAFO); `["M19-AD"]`→`approved`; `["M18-RNAFO","M18-RNS","M19-AD"]`→`draft`; `["M9-AZ"]`→`draft|approved`; `["M8-PLAN"]`→`draft|approved`; `["M24-AZK","M25-PRED"]`→`active`; `["M25-PRED"]`→`approved`; `["M23-RVO"]`→`oa_acknowledged`; `["M6-PA-S","M6-PA-F"]`→`approved`. Плюс `check_document_submit_allowed` (при `submit`), `check_transition_condition`/`get_case_blocking_statuses` (UI), цепочка «предыдущий документ согласован» (`prev_approved` → `Message_PrevDocApproved`), карта в `Resolve Next Doc` (`M9-AZ`→`M7-POR`, `M8-PLAN`→`M9-AZ`).

Смысл гейтов совпадает с фронтовыми `dependencies`/`preparationSubmissionBlock` (см. `evga-domain-model.md` §3.1): программа после ИПИ, план/задание/поручение после программы, реестр+доказательства перед отчётом и КК2, заключение+предписание перед КК3 и т.д.

### 4.6. Zeebe: процессы, сообщения, переменные

* Процессы (`bpmn_map.txt`): дело — `CaseProcessV1` (`prc_Mz6acfNa5aUKswju2gZzvA9hiNG`, hardcoded в Create Case v4); документы — `evga_doc_1_irpi`, `evga_doc_2_pa`, `evga_doc_3_plan`, `evga_doc_4_az`, `evga_doc_5_poruchenie`, `evga_doc_6_qc`, `evga_doc_7_zkk`, `evga_doc_37_kk2`, `evga_doc_46_kk3`, `evga_doc_51` (возражения), `evga_doc_accounting_card` (М11), `evga_doc_vap_notification` (М13), `evga_doc_additional_order` (М14), `evga_doc_info_request` (М15), `evga_doc_access_denial_act` (М16), `evga_doc_audit_evidence` (М19), `m20_audit_objection`, `evga_doc_m21_ako`, `evga_doc_objection_results` (2.7), `evga_doc_audit_conclusion`, `evga_doc_violation_order` (3.2), `evga_doc_measures_response` (3.3), `evga_doc_transfer_authority` (3.4), `evga_doc_transfer_law_enforcement`, `evga_doc_lawsuit`, `evga_doc_lawsuit_decision`, `evga_doc_notification_slip` (3.9), `evga_doc_audit_completion_cert` (3.10), `evga_doc_qc_stage{1,2,3}`, `evga_doc_weekly_report` (2.4), `evga_doc_m18_m19_auto_create`, `prc_JwETUJ5…` (М18 реестр), `evga_doc_prikaz`, `evga_doc_talon_uvedomlenie` (M26-TU, ЕРСОП FINISHED), `evga_doc_m38…m57` (адм. производство), `evga_doc_m43…m56` (встречный контроль), `send_notification`. Соответствие `document_type.zeebe_process_id → prc_*` хранится только в БД.
* Сообщения: `TASK_COMPLETE_EVENT` (`Message_DocAction`, correlation `string(processData.documentId)` — 88 раз; `Message_CaseAction`, correlation `string(processData.caseId)` — 6), `prev_document_approved`, `DOC_STATUS_CHANGED`, `CREATE_QC_CONCLUSION_EVENT`, `DOC_CONFIRM_EVENT`. Переменная события — `taskVariable` (`taskVariable.actionCode`).
* Стартовые переменные процесса документа: `documentId, caseId, documentTypeId, authorIin, authorFullname, requiresApproval, requiresConfirmation, requiresKvga, controllingBodyCode, auditTypeCode, isRecreated`; процесса дела: `caseId, caseNumber, authorIin, authorFullname, controllingBodyCode`.
* Коды действий, которые BPMN сам шлёт в другие процессы (`evga/zeebe`): `prev_approved`(22), `ready_send_to_qc`, `ready_send_to_qc_2`, `ready_send_to_qc_3`, `ready_send_to_qc_kvga`, `ready_send_confirmation`, `ready_send_to_appeal`, `ready_kvga_confirmed`, `doc_approved`, `create_qc_conclusion_stage3`, `qc_3_completed`, `zkk_confirmed`, `signed_automatically`, `audit_object_acknowledged`, `ersop_registered`, `closed`, `status_change`, `default`. Дело: `send_to_qc`, `send_to_qc_stage2/3`, `send_to_qc_kvga`, `assign_qc_expert(_stage2/_stage3/_kvga/_appeal)`, `create_qc_conclusion(_stage2/_stage3/_kvga)`, `resubmit_to_qc_stage2`, `create_resultat_vozrazhenie`, `ready_send_to_appeal`.

### 4.7. История, согласования, версии

Четыре параллельных журнала: `evga_document_approvals` (кто/что/комментарий, для ленты согласований), `evga_document_workflow_history` (машинный переход from→to; строится и n8n, и Zeebe), `evga_audit_log` (человеческая история дела и документа, `source`, дедуп 10 с; фронт читает `evga/document-history`), `evga_document_versions` (снимок при возврате/переходе с `shouldCreateVersion`). Плюс `case_status_history` и `case_activity_log` для дела. В prof это один `core.AuditEvent` + отдельная модель версии.

### 4.8. Публичная верификация

`GET evga/documents/verify?docId=N` — публичный (CORS `*`) ответ с типом, номером дела, статусом и списком подписантов. Ни QR-токена, ни хеша (`evga_document_signatures.document_hash` есть, но не используется). В экспорте запрос захардкожен на `d.id = 2854`. При переносе — сделать через непредсказуемый публичный токен.

### 4.9. ЕРСОП

Схема обмена: документ «Учётная карточка» → `send_to_ersop` → сборка `M_TYPE_STARTED` (реальные поля из `evga_doc_registration_card` + рабочая группа; `userCreate/userSign` — заглушки) → SOAP `SI_SUR2ERSOP_RequestSubjectAsync` → успех по подстроке `oK!` → статус `sent_to_ersop`; далее polling `check_status` (`getErsop?requestId=<document_id>`) → `pending_for_consideration` → финал `registered_ersop|rejected_ersop|sent_revision_ersop`. Для доп. поручений/приостановок/завершения предусмотрены `M_TYPE_PROLONGED|PERIOD_CHANGED|RESUMED|SUSPENDED|STOPED|EXECUTORS_CHANGED|FINISHED` (BPMN `evga_doc_talon_uvedomlenie` — «ЕРСОП FINISHED»). Во фронте ЭВГА регистрируемые в ЕРСОП виды — `account, counter-account, notification, counter-notification, additional, counter-additional` (`performRegistration`), что совпадает.

### 4.10. Прочие правила

* Дело можно редактировать (`can_edit`), пока оно не `closed` и все документы «черновые» (`status_id IN (1,2)`).
* Основания дела — только для внепланового аудита (`inspection_type_id = 6`); маршрут КК: `KK KVGA`, если основание с кодом `13|14` и аудит внеплановый.
* Плановость: `inspection_types.code ∈ {'1','scheduled'}`.
* Документ типа «Дело КК» (`document_type_id = 6`) создаётся сразу в `open`.
* Дубликаты типов запрещены, если `allow_multiple = false`; `block_recreate_after_delete` запрещает пересоздание после удаления; `is_recreated` передаётся в BPMN.
* Автокопирование вопросов ИПИ → пустые программы аудита (после `update` ИПИ) и ленивый сид вопросов программы/рабочей группы при `get` (Docs: CRUD).
* Возражение ОА (`M20-VOZ`) создаётся как дочерний документ отчёта с преднастроенными действиями `save/submit` для `oa_responsible|audit_object`.
* `register` присваивает номер приказа и обнуляет `available_actions`; `send_to_ak` — тоже обнуляет.
* `close_case` из документа ЗКК: дело → `closed` (активная версия).
* Удаление участника/дела — только soft delete; удаление документа — soft delete с каскадом на встроенные.

---

## 5. Коды типов документов ↔ таблицы ↔ фронт ЭВГА

Фронт (`saq-evga-test/src/data/documentMatrix.ts`, `modules/evga/forms/documentForms.ts`) оперирует строковыми `kind` без «M-кодов»; поле `code` там — отображаемый номер формы (`12, 55, 33, 88, 17, 34, 76`), не идентификатор. Сопоставление по смыслу и BPMN-названиям:

| Старый код (`evga_document_types.code` / BPMN) | Наименование (n8n/BPMN) | `root_table` | `kind` фронта (`documentForms.ts`/`documentMatrix.ts`) |
|---|---|---|---|
| `M5-IPI` | ИПИ / Информация о результатах предварительного изучения | `evga_doc_preliminary_study` | `irpi` |
| `M6-PA-S`, `M6-PA-F` | Программа аудита (соответствия / фин. отчётности) | `evga_doc_audit_program` | `program` (вариант по `isFinancialAudit`) |
| `M8-PLAN` | План аудита | `evga_doc_audit_plan` | `plan` |
| `M9-AZ` | Аудиторское задание | `evga_doc_audit_assignment` | `assignment` |
| `M7-POR` | Поручение | `evga_doc_audit_order` | `instruction` |
| ЗКК / `M10-QC1`, КК2 (id 37), КК3 (id 46), Дело КК (id 6) | Контроль качества 1/2/3 этап | `evga_doc_quality_control_conclusion` | `quality1`, `quality2`, `quality3` (Дело КК на фронте отдельной сущности нет — это `audit.quality[stage]`) |
| М11 (`evga_doc_accounting_card`) | Учётная карточка (ЕРСОП) | `evga_doc_registration_card` | `account` / `counter-account` |
| `M13` (`evga_doc_vap_notification`) | Уведомление в ВАП | `evga_doc_notification_vap_rk` | `vap` |
| `M14` (`evga_doc_additional_order`) | Дополнительное поручение | — | `additional` / `counter-additional` |
| `M15` (`evga_doc_info_request`) | Требование по предоставлению сведений | `evga_doc_info_request` + `evga_doc_ir_questions` | `request` / `counter-request` |
| `M16` (`evga_doc_access_denial_act`, `certificate_of_refusement`) | Акт об отказе в доступе / о воспрепятствовании | — | `obstruction` / `counter-obstruction` |
| `M17-AO-S`, `M17-AO-F` | Аудиторский отчёт | — | `report` |
| `M18-RNS`, `M18-RNAFO` | Реестр нарушений (соответствие / фин. отчётность) | `evga_doc_vr_compliance`, `evga_doc_vr_financial_new` | `violations` |
| `M19-AD` | Аудиторские доказательства | — | `evidence` |
| `evga_doc_weekly_report` (2.4) | Еженедельный отчёт | — | `weekly` |
| Акт контрольного обмера (`evga_doc_control_measurement_act`) | | + `evga_doc_cma_work_group` | `measurement` |
| `M20-VOZ` (`m20_audit_objection`, `evga_doc_oa_objection` 2.6) | Возражение от объекта аудита | `evga_doc_audit_objection` | `objections` |
| `M23-RVO` (`evga_doc_objection_results` 2.7) | Результаты возражения | `evga_doc_objection_appeal_result` | `objection-result` |
| `M21-AKO` | Ознакомление ОА | — | (на фронте — часть `delivery` отчёта) |
| `M24-AZK` (`evga_doc_audit_conclusion`) | Аудиторское заключение | — | `conclusion` |
| `M25-PRED` (`evga_doc_violation_order` 3.2) | Предписание | — | `prescription` |
| `M28-OPM` (`evga_doc_measures_response` 3.3) | Ответ о принятых мерах | — | `response` |
| `M26-TU` (`evga_doc_notification_slip` 3.9) | Талон-уведомление | — | `notification` / `counter-notification` |
| `evga_doc_transfer_authority` (3.4) / `transfer_law_enforcement` / `peredacha_upoln` | Передача в вышестоящий/уполномоченный/правоохранительный орган | — | `forward-up`, `forward-law`, `forward-abp` |
| `evga_doc_law_enforcement_response`, `otvet_pravoohran` | Ответы органов | — | `reply-up`, `reply-law`, `reply-abp` |
| `evga_doc_lawsuit`, `iskovye_zayavleniya`, `lawsuit_decision` | Иски / решения по искам | — | `claim-invalid`, `claim-dishonest`, `claim-recover`, `claim-liquidation`, `claim-decisions` |
| `evga_doc_audit_completion_cert` (3.10) | Справка о завершении | — | `completion` |
| `M43-VK-POR`, `M44-VK-UK`, `M45-VK-TREB`, `M46-VK-AKT`, `M47-VK-TU`, `M54-VK-DOP-POR`, `M55-VK-AKT-OSM`, `M56-VK-AKT-VOS` | Встречный контроль | `evga_doc_counter_control_poruchenie` (только M43) | `counter-instruction`, `counter-account`, `counter-request`, `counter-act`, `counter-notification`, `counter-additional`, `counter-obstruction` (+ акт осмотра — во фронте нет) |
| `M38…M42, M48…M53, M57 -ADM-*` | Адм. производство | `evga_doc_admin_offense_protocol` (только M39) | во фронте ЭВГА **нет** (подчинённое дело `admin_violation`) |
| `evga_doc_prikaz` | Приказ о начале/завершении | `evga_doc_audit_start_order`, `evga_doc_inspection_completion_order` | во фронте нет (номер приказа = `register`) |
| Рабочие документы (`РД-N`, 62 шт.) | — | во фронте есть (`workingPapers.json`), в n8n/BPMN аналога нет |

Рекомендация: в новом бэкенде хранить `DocumentType.code` = старый M-код (для совместимости с BPMN-номенклатурой, ЕРСОП и ТЗ) и `DocumentType.kind` = строковый `kind` фронта; сидировать оба.

---

## 6. Вердикты переиспользования

Легенда: **как есть** — перенести схему/логику без изменений (в ORM/сервис); **адаптировать** — сохранить смысл, поменять реализацию под prof; **переписать** — сохранить только требования; **выбросить**.

| Элемент | Вердикт | Как в стиле prof |
|---|---|---|
| `cases` + `case_statuses` + `case_participants` + `case_bases` + `case_base_attachments` | адаптировать | `apps/cases/models.py`: `Case(TimeStampedModel)`, `CaseStatus(TextChoices)` с кодами `OPEN, CLOSED, …`, `CaseParticipant(case, user, is_lead, is_active, removed_at)` с `UniqueConstraint(case, user)` и проверкой одного лидера в сервисе, `CaseBasis`, вложения через `core.Attachment` (MinIO) вместо строковых file_id. Убрать дубли `author_id/author_iin/author_keycloak_id` → FK на `accounts.User`; `director` — из объекта |
| Подчинённые дела (`parent_id`, `sub_case_type`, `sub_case_data`) | адаптировать | `Case.parent`, `Case.kind = CaseKind(MAIN, ADMIN_VIOLATION, COUNTER_CONTROL)`; гейт и основания — сервисы `services/sub_cases.py` (тела `check_sub_case_creation_condition`/`get_admin_violation_grounds` нужно восстановить из БД или ТЗ) |
| `audit_objects` (upsert по БИН) | как есть | `subjects`/`audit_objects` с `bin` UNIQUE; upsert в сервисе `create_case` |
| `case_status_history`, `case_activity_log`, `evga_audit_log`, `evga_document_workflow_history`, `evga_document_approvals` | адаптировать → один журнал | `core.AuditEvent` (generic FK, `action`, `status_from/to`, `actor`, `reason`, `payload`); отдельная лента «согласований» — это выборка событий; дедуп 10 с не нужен |
| `evga_document_versions` + `create_full_document_snapshot` | адаптировать | `DocumentVersion(document, number, snapshot JSONField, returned_by, comment, previous_status)`; снимок = сериализация details+подтаблиц; создавать при `return`/`reject` явно, а не по флагу из BPMN |
| `evga_document_signatures` | как есть | `DocumentSignature(document, signer, signature_type, signature, signed_at, document_hash)`; типы — `TextChoices` (`WORK_GROUP_PENDING/SIGNED, INVITED_SPECIALIST_*, KVGA_CONFIRM/REJECT, OA_ACKNOWLEDGE, SIGN, CONFIRM`) |
| `evga_document_types`, `evga_document_stages` | как есть (справочник + seed) | `documents.DocumentType` с флагами `requires_approval/confirmation/kvga, requires_signature, sends_to_audit_object, allow_multiple, is_manually_creatable, is_child_only, block_recreate_after_delete, audit_type_codes, creator_roles, reg_number_format/prefix, supports_version`; `seed_document_types` |
| `evga_document_statuses` | как есть (коды) | `DocumentStatus(TextChoices)` со списком §4.3 (упорядочить и выкинуть дубли `return/revision`, `sent_to_oa/sent_to_audit_object`, `send_to_auditor/sent_to_auditor`) |
| `evga_document_mappings` + динамический SQL (`get`, `create`, `update`, подтаблицы, overlay, seed) | переписать | Как в prof: `CaseDocument` (шапка) + OneToOne `*Details` на тип (`PreliminaryStudyDetails`, `AuditProgramDetails`…) + дочерние модели строк (`AuditProgramQuestion`, `AuditPlanObject`, `AuditAssignmentQuestion`, `ViolationRegistryItem`…). Колонки берём из §2.4. Для редких типов без подтаблиц допустим `values = JSONField` (фронт ЭВГА хранит формы как `values`), но реестр нарушений, вопросы программы, объекты плана — реляционно, т.к. по ним считаются КК2, предписание, ЕРСОП |
| Нумерация (`get_next_case_sequence`, `get_next_doc_sequence('standard'|'with_org'|'PRIKAZ')`, форматы §2.6) | как есть (форматы), адаптировать (механизм) | `core.NumberSequence/IssuedNumber` prof (`select_for_update`), ключи `case:<орган>:<год>`, `doc:standard:<год>`, `doc:with_org:<год>`, `prikaz:<год>`; убрать `COUNT(*)+1` |
| Создание дела с 5 документами | адаптировать | `cases/services/case_create.py::create_case(*, actor, payload)` в `transaction.atomic`: upsert объекта → дело → участники (лидер) → 5 документов через `documents/services/create_document` → `AuditEvent`; без HTTP-самовызовов |
| Жизненный цикл документа (`submit/approve/reject/return/send_to_confirmation/confirm/direct_confirm/activate/register/send_to_kvga/kvga_*/reestr_*/send_to_audit_object/acknowledge/submit_objection/send_to_ak/qc_close/close_case`) | адаптировать | Отдельные функции-сервисы и `APIView` на действие (стиль prof); переходы — явная таблица `ALLOWED_TRANSITIONS[(type_group, from_status, action)] → to_status` + предусловия (`check_document_submit_allowed`, гейты §4.5); `DocumentTransitionError` |
| `available_actions` / `get_available_actions` | переписать | вычислять на сервере: `available_actions(document, user)` по таблице переходов + роли + назначения (`approver/confirmer/kvga_confirmer/author/qc_head/qc_expert/workgroup/workgroup_lead`) — логику фильтра §4.4 сохранить; JSON в БД не хранить |
| `check-docs-status` | как есть (как сервис) | `documents/services/gates.py::documents_in_status(case, codes, status) -> GateResult(all_matched, all_existing_matched, …)`; использовать в предусловиях вместо BPMN |
| Рабочая группа: `Work Group Approval` (`init/sign/approve/check`), `Invited Specialist` | адаптировать | сервисы `init_work_group_signatures`, `sign_by_member`, `approve_by_lead` над `DocumentSignature`; условие «лидер утверждает после всех» сохранить |
| QC: `send_case_to_qc`, `assign_qc_expert`, `complete_qc_review`, `evga_qc_requests`, `case_qc_assignments` | адаптировать | `quality` app: `QcRequest(case, stage, status, requested_by, controlling_body)`, `QcAssignment(case, head/expert, active)`; ЗКК — обычный `CaseDocument` с `QualityConclusionDetails` (колонки из `QC Conclusion Workflow`) |
| Zeebe/Camunda: старт процессов, `TASK_COMPLETE_EVENT`, `workflow-update`, `case-workflow-update`, `case-workflow-log`, `evga/zeebe`, `evga/case-action`, `Zeebe: Send Event/Start Process`, `zeebe_process_id/zeebe_process_instance_id` | выбросить | состояние и переходы — в сервисах Django; таймеры BPMN (10 дней на возражения `P10D`, сроки требований) — Celery/cron-команды в стиле `management/commands` |
| n8n-роутер (`Documents Router`, `Docs: *`, `$vars.*_WORKFLOW_ID`, `__httpStatus`) | выбросить | DRF `api/urls.py` |
| ЕРСОП (`evga/ersop`, `ERSOP - Build and Send`, `SEND_REQ_TO_ERSOP`, `restErsop`) | адаптировать | `ersop` app по образцу prof (`ErsopPackage`, `ErsopExchange`, `stub_exchange`): сохранить типы сообщений `M_TYPE_*`, состав полей `Started/Finished`, отображение статусов `confirmstatusid 1/2/3 → registered/rejected/revision`, статусы документа; реальный SOAP — адаптер за интерфейсом; убрать MOCK пользователей |
| Публичная верификация | адаптировать | `GET /api/evga/public/verify/<token>/` по непредсказуемому токену/хешу; не по id |
| Справочные endpoints (`audit-result`, `offense-type/tree`, `listPreAudits`, `qcs2/violations`, `check-audit-type`, `cases/bases`) | адаптировать | обычные ReadOnly ViewSet'ы/сервисы; SQL `violations` — в ORM/`annotate` или сырой запрос в `services/violations.py` |
| `Get Case Documents` (матрица типов × документов дела) | как есть (как запрос) | `GET /api/evga/cases/{id}/documents/` — список типов с `document|null`, как ждёт фронт (`AuditCase.documents`) |
| `Get Available Document Types` (правила создания) | как есть (правила) | `documents/services/creation.py::available_types(case, user)`; `DOC_PLACEMENT` заменить на `sequence_order`/`stage` в seed |
| `Cases - Delete`, `Delete Case Participant`, `delete` документа (soft delete) | как есть | `is_deleted/deleted_at/deleted_by` или `SoftDeleteQuerySet` |
| Портальные `documents`, `document-uploaded`, `document-file`, `worktime`, RabbitMQ-лог | выбросить | (формат ИБ-лога — как требование к `AuditEvent`, если нужно) |
| Дубли/старые версии: `Cases - List` (off), `Add/Delete Case Participants` с `employee_id` (off), `assign-expert-to-case` (off), `Additional Actions` C4FI (off), `Docs: CRUD/Case Misc/KVGA/Lifecycle/QC/Meta/Roles/Generic` (off), `Audit Result - Get` дубликат, `Create Case v3`, `Info Request API (deprecated)`, `data_migration` (Oracle `v_dm_gac_cases`) | выбросить | брать только активные версии как источник требований (различия учтены в §3.4) |
| `My workflow 31` (прямая смена статуса дела) | выбросить | статус дела меняют только сервисы |
| `Service GDBJL` (ГБД ЮЛ по БИН), `sendRequestErap` (ЕРАП) | адаптировать (отдельные интеграции) | заглушки в стиле prof, маппинг ответа §3.7 |
| Роли `evga_roles/evga_user_roles` (`role_level`, `can_*`, `controlling_body`, `valid_from/to`) | адаптировать | prof `accounts.Role/RolePermission/RoleAssignment` уже покрывают; добавить назначения по документу (`approver/confirmer/kvga_confirmer`) как поля документа |

---

## 7. Открытые вопросы

1. Тела хранимых функций (`check_sub_case_creation_condition`, `get_admin_violation_grounds`, `close_admin_violation_case`, `soft_delete_admin_violation_case`, `check_document_creation_condition`, `check_document_submit_allowed`, `check_transition_condition`, `get_case_blocking_statuses`, `send_case_to_qc`, `assign_qc_expert`, `complete_qc_review`, `get_qc_tasks`, `send_document_to_audit_object`, `acknowledge_document`, `change_document_*`, `create_full_document_snapshot`, `seed_doc_work_group`, `get_next_*_sequence`) и определения view (`cases_list_view`, `evga_users_with_roles`, `evga_available_document_types`, `evga_dashboard_stats`, `evga_document_timeline`) в экспорте отсутствуют — нужен `pg_dump --schema-only surfk`.
2. Содержимое `evga_document_types` (полный список кодов/id/`zeebe_process_id`/флагов) и `evga_document_mappings` (`fields_mapping`, `subtables_mapping`, `form_schema` по каждому типу) — только в БД; без них колонки `evga_doc_*` для ~половины типов неизвестны (в отчёте — только те, что видны в SQL).
3. Смысл id статусов `3, 22` (исключаются как «неактивные»), `49` (`sent_to_ak`), `11, 12` (статусы дела «на КК»), `1, 2` (черновые) и полный справочник `case_statuses`.
4. Какой из двух путей «действие пользователя → Zeebe» считать целевым: n8n-переходы (`evga/documents`) или прямые `evga/zeebe publish_message` (фронт `saq-evga-test` бэкенда не имеет, поэтому контракт придётся задать заново).
5. Нужно ли сохранять старые форматы номеров (`СП-25-00123`, `2025/09/21 – 00042`, `ПР-СП-25-000007/00123_1`) для преемственности с уже зарегистрированными в ЕРСОП делами.
6. Три таблицы пользователей (`surfk.users`, `public.users`, `portal.users`) и два способа идентификации (ИИН vs keycloak uuid) — какой источник считать основным для `accounts.User` в новом бэкенде.
7. `evga_status_transitions` используется только в `QC Conclusion Workflow`/appeals — была ли она задумана как общая таблица переходов (тогда её можно взять за основу `ALLOWED_TRANSITIONS`).
8. Реальные реквизиты `userCreate/userSign`, телефоны и `organCode` для ЕРСОП (сейчас MOCK), а также смысл `SubjectInfo.subjectId`/`ObjectInfo.objId` (`ersop_subject_id/ersop_object_id`).
9. Административное производство (`M38…M57`, подчинённое дело `admin_violation`) и приказы (`evga_doc_prikaz`) во фронте ЭВГА отсутствуют — входят ли они в объём нового бэкенда.
10. Публичная верификация: требуется ли QR/хеш (в старом коде — нет).

---

## 8. Приложение: сводка размеров

| Воркфлоу | Узлов | Webhook | Активен |
|---|---|---|---|
| EVGA Additional Actions (VMkW67X9Wz5jfxh8) | 249 | `evga/documents` | да |
| EVGA Additional Actions (C4FIU7mx71GievWg) | 246 | `evga/documents` | нет (отличия: нет `get_all_user_roles`, `close_case` → `qc_approved`, старые JOIN на `public.users.full_name_ru`, `case_documents`/`document_statuses` в `check_transition`) |
| EVGA Docs: Lifecycle / CRUD / Meta / Case Misc / KVGA-Reestr / QC / Roles / Generic | 94 / 74 / 34 / 34 / 32 / 28 / ? / 7 | (саб-воркфлоу) | нет |
| EVGA: Create Case v4 Parallel Docs | 36 | `evga/cases` | да |
| EVGA Zeebe Integration | 36 | `evga/zeebe` | да |
| EVGA: Work Group Approval | 39 | `work-group-approval` | да |
| EVGA Sub Cases | 33 | `evga/sub-cases` | да |
| EVGA ERSOP Workflow | 30 | `evga/ersop` | да |
| EVGA_ Invited Specialist | 22 | `evga/invited-specialist` | да |
| BPMN-процессов | 71 файл (`bpmn_inventory.txt`) | | |
