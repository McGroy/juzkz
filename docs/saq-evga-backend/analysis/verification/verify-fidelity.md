# Верификация проекта `design-final.md`: верность стилю prof и достоверность ссылок на старую систему

Проверяемый документ: `reports/design-final.md` (1868 строк, прочитан целиком).

Первоисточники, по которым велась сверка:

* prof — `src/prof/saq-prof-control-demo/backend/**` (прочитаны все файлы из задания плюс `apps/accounts/services/{keycloak,sessions}.py`, `apps/accounts/api/{serializers,urls,local_views}.py`, `apps/core/{pagination,middleware,views}.py`, `apps/core/services/files.py`, `apps/cabinet/api/urls.py`, `apps/cases/api/serializers.py`, `apps/execution/api/filters.py`, `apps/semiannual/models.py`, `apps/catalogs/management/commands/seed_catalogs.py`, `apps/documents/services/acknowledgement.py`, `apps/core/management/commands/seed_number_sequences.py`, `pyproject.toml`, `requirements/*`, `Dockerfile`, `../docker-compose.yml`, `../deploy/{README.md,.env.example}`, `../frontend/src/config/saqModules.ts`, `../frontend/src/api/client.ts`, тесты `apps/{core,subjects,accounts}/tests`).
* n8n — `src/n8n_old/n8n_export/all_workflows_raw.json` (566 воркфлоу, 6727 узлов; построен индекс всех строковых параметров узлов и выполнен grep по ~250 терминам), `n8n_export/workflows/*.json`, `n8n_export/analysis/*.txt`.
* BPMN — `src/n8n_old/bpmn/*.bpmn` (72 процесса), `bpmn/bpmn_summary.txt`, `bpmn_inventory.txt`, `bpmn_map.txt`.
* Отчёты фазы 1 — `n8n-cases-documents.md` (§2.3, §2.6, §5), `n8n-references-auth-notify.md` (§4.1, §4.3, §4.5, §5, §6.7), `bpmn-processes.md` (§2.1, §2.3, §3.10, §6, §7, §8, §9.3).

Формат замечания: **id | severity | раздел проекта** → что утверждает проект → что показывают первоисточники → исправление. Севериты: `blocker` — проект в этом месте нереализуем/ошибочен по существу; `major` — утверждение о prof/legacy неверно и повлияет на код, миграцию данных или тесты; `minor` — неточность, которую нужно поправить в тексте/комментариях/приложении «не подтверждено».

Итог: **0 blocker, 5 major, 30 minor** (линза 1: 3 major + 6 minor; линза 2: 2 major + 24 minor).

---

## Линза 1. Верность стилю prof (что «копируется из prof как есть» — реально ли есть)

### F-01 | major | §2.3, §3.2 (таблица файлов), §10.3 — файл `deploy/nginx.conf`

* **Проект**: строка таблицы §3.2 «`Dockerfile`, `docker/entrypoint.sh`, `docker-compose.yml`, `deploy/README.md`, `deploy/.env.example`, `deploy/nginx.conf` | **как есть + add** | … nginx-блок `/evga/`»; §10.3 «nginx (по `deploy/README.md`)».
* **Первоисточник**: в prof каталог `deploy/` содержит только `README.md` и `staticfiles/`; файла `nginx.conf` нет. Конфигурация nginx приведена текстом в `deploy/README.md:120-160` (`client_max_body_size 25m;`, `location /static/`, `location /api/ { proxy_pass http://127.0.0.1:8000; }`, `location /admin/`, `location / { try_files $uri $uri/ /index.html; }`), nginx ставится на хост (`README.md:4`).
* **Исправление**: убрать `deploy/nginx.conf` из списка «как есть»; указать, что ЭВГА добавляет новый файл (например, `deploy/nginx.evga.conf`) или расширяет блок в `deploy/README.md`; отметить, что prof-значение `client_max_body_size` — 25m, а 50m — изменение ЭВГА.

### F-02 | minor | §3.2 — `requirements/{base,local,production}.txt`

* **Проект**: «`manage.py`, `pyproject.toml` …, `requirements/{base,local,production}.txt` | как есть».
* **Первоисточник**: `backend/requirements/` содержит только `base.txt` и `local.txt`; `production.txt` нет (Dockerfile ставит `requirements/base.txt`).
* **Исправление**: `requirements/{base,local}.txt`.

### F-03 | major | §3.2 (строки `documents/services/*`, `documents/models.py::Acknowledgement`), §5.2 (`delivery.py`), §6.9 — «копии» prof-функций с несуществующими в prof именами и сигнатурами

* **Проект**: «`apps/documents/services/{exceptions,attachments}.py` | **копия** | `DocumentTransitionError`, `StaleVersionError`; `attach_version_file`/`version_attachments`/`delete_version_attachment`»; «`services/acknowledgement.py` | **копия** | `record_acknowledgement(version, *, channel, by, acknowledged_on, proof_ref, attachment)`»; §5.2 `delivery.py`: «`record_acknowledgement(version, *, channel, by, acknowledged_on=None, …)` (копия prof)»; §6.9: «проверкой `_assert_subject_owns(user, document.case)`».
* **Первоисточник**:
  * `apps/documents/services/exceptions.py:1-2` — единственный класс `DocumentTransitionError(Exception): pass`; `StaleVersionError` в prof нет.
  * `apps/documents/services/attachments.py:9-31` — только `attach_file(document, *, kind, uploaded_file, uploaded_by=None)` и `document_attachments(document, *, kind=None)`; функции удаления нет (в prof вложения не удаляются нигде).
  * `apps/documents/services/acknowledgement.py:7-15` — `record_acknowledgement(document, *, channel: str, acknowledged_on, proof_ref: str = "", attachment=None, recorded_by=None)`: актор называется `recorded_by`, `acknowledged_on` обязателен.
  * `apps/cabinet/api/views.py:28-30` — `_assert_subject_owns(user, subject_id)` сравнивает `subject_id != user.subject_id`, объект дела не принимает.
* **Исправление**: в §3.2 пометить эти строки «адаптация», а не «копия»; перечислить реальные prof-имена (`attach_file`, `document_attachments`, `recorded_by=`) и явно указать, что `StaleVersionError`, `delete_version_attachment`, `assert_attachment_retention`, `by=` — новое; в §6.9 писать `_assert_subject_owns(user, document.case.subject_id)` (либо новая функция с другой сигнатурой).

### F-04 | minor | §3.2 — `CabinetCaseViewSet`, местоположение `PrescriptionItemFilter`, «копия» `ErsopExchange`

* **Проект**: «`apps/cabinet/api/{views,serializers,urls}.py` | копия с заменой агрегата | `_assert_subject_owns`, `CabinetCaseViewSet`, `CabinetDocumentViewSet`…»; «`apps/execution/models.py` (`PrescriptionItem.status` property, `PrescriptionItemFilter`)»; §4.11 «`ErsopExchange` — копия prof ErsopExchange».
* **Первоисточник**: `apps/cabinet/api/urls.py:16-17` — в prof только `CabinetDocumentViewSet` и `CabinetPrescriptionItemViewSet`, класса `CabinetCaseViewSet` нет; `PrescriptionItemFilter` объявлен в `apps/execution/api/filters.py:6`, а не в `models.py`; prof `ErsopExchange` (`apps/ersop/models.py:79-85`): `direction max_length=8`, `exchange_id` без `blank=True`, `occurred_at = DateTimeField()` без default — в проекте `max_length=3`, `blank=True`, `default=timezone.now`, `raw_xml`.
* **Исправление**: `CabinetCaseViewSet` пометить как новый; поправить путь фильтра; для `ErsopExchange` написать «по образцу prof, поля расширены» и не менять `max_length` без причины.

### F-05 | minor | §5.2 (`cases.py`, `factory.py`), §4.15, §8.1 — вызовы `issue_number`

* **Проект**: `issue_number("evga-case", scope=controlling_body.code)`, `issue_number("evga-document", scope=case)`, `issue_number("evga-ersop-registration")`, при этом «механизм `core.NumberSequence`/`issue_number` без изменений».
* **Первоисточник**: `apps/core/services/numbering.py:19-25` — `def issue_number(*, key: str, target: models.Model, scope: str = "", context: dict | None = None)`: все аргументы keyword-only, `target` обязателен (по нему строится `IssuedNumber` и идемпотентность), `scope` — строка.
* **Исправление**: писать `issue_number(key="evga-case", target=case, scope=controlling_body.code, context={"org": …, "yy": …})`; `scope=case` заменить на `scope=str(case.pk)`.

### F-06 | minor | §6.13, §7.1, §7.5 — коды и статусы ошибок, приписанные prof

* **Проект**: 403 с `"code":"forbidden"`; «чужой скоуп/объект — 404»; §7.1 «`is_active=False` → 403 `user_blocked` (prof уже проверяет в `SessionCookieAuthentication`)»; §7.5 порядок view: `assert_department_in_scope` — копия prof.
* **Первоисточник**: `apps/core/exceptions.py:18-25` — `code` берётся из `exc.default_code`, у DRF `PermissionDenied` это `permission_denied`; prof `_assert_department_in_scope` (`apps/documents/api/views.py:55-65`) поднимает `PermissionDenied("Эта запись не входит в ваш территориальный скоуп.")` → **403**, а не 404; `SessionCookieAuthentication.authenticate` (`apps/accounts/authentication.py:15-17`) при `not session.user.is_active` возвращает `None` → **401** `not_authenticated`; 403 «Account deactivated» даёт только `LoginView` (`local_views.py:72-73`).
* **Исправление**: либо ввести собственный `PermissionDenied` с `default_code="forbidden"` и подкласс `NotFound` для скоупа, либо привести §6.13/§7.1 к фактическому поведению prof (403 `permission_denied`, 401 при блокировке).

### F-07 | major | §3.2, §4.3, §7.1 — «`provision_user_from_claims` как есть + 6 строк» и `User.iin unique=True`

* **Проект**: `iin = CharField(max_length=12, …, unique=True)`; provisioning prof дополняется шестью строками (`iin` из `preferred_username`, ФИО, `origin_subject`).
* **Первоисточник**: `apps/accounts/services/keycloak.py:163-209` — prof ищет пользователя только по `FederatedIdentity(issuer, sub)`; при `IntegrityError` на создании повторно ищет по `sub` и иначе бросает `EmailAlreadyLinkedError`. Legacy идентифицирует пользователя по ИИН (`User Login Sync :: Sync User`: `INSERT INTO surfk.users … ON CONFLICT (iin) DO UPDATE`). Следствие: второй `sub` с тем же ИИН (пересоздание учётки в Keycloak, dev/test realm, локальный пользователь, которому админ вписал ИИН) даст `IntegrityError` по `iin` и падение входа с непонятной ошибкой про e-mail.
* **Исправление**: описать правило слияния (искать существующего `User` по `iin` до создания и привязывать новую `FederatedIdentity`, как делает legacy `ON CONFLICT (iin)`), либо снять `unique=True` (индекс + проверка в сервисе). Это больше шести строк и не «как есть».

### F-08 | minor | §2.3, §10.3 — сервис `scheduler` на образе prof

* **Проект**: «`scheduler` (тот же образ): `python manage.py process_deadlines --loop 300`», без портов.
* **Первоисточник**: `backend/Dockerfile` — `ENTRYPOINT ["/entrypoint.sh"]`; `docker/entrypoint.sh:4-17` безусловно выполняет `migrate`, `collectstatic` и все `seed_*` перед `exec "$@"`. Второй контейнер на том же образе повторит миграции и сиды параллельно с `backend` (гонка `update_or_create`, двойной `collectstatic`).
* **Исправление**: для `scheduler` задать `entrypoint: ["python", "manage.py"]` и `command: ["process_deadlines", "--loop", "300"]` плюс `depends_on: backend: condition: service_healthy`.

### F-09 | minor | §3.2 (строка `apps/accounts/{authentication,permissions,schema}.py`) — незачищенный черновик

* **Проект**: «`MeSerializer` дополняется полями `iin`, `account` через наследник `EvgaMeSerializer` в `evga_cases/api/serializers.py`? — нет: `MeSerializer` расширяется аддитивно двумя полями (`iin`, `position` уже есть)».
* **Первоисточник**: `apps/accounts/api/serializers.py:53-74` — `MeSerializer` уже содержит `position`, `department`, `is_subject_representative`, `subject`, `roles`; добавить нужно только `iin`.
* **Исправление**: оставить одну формулировку: «`MeSerializer` += `iin` (аддитивно); `account` собирает фронт».

---

## Линза 2. Достоверность ссылок на старую систему

### L-01 | major | §5.3 (реестр `ACTIONS`), §5.6 — выдуманные legacy-коды `apply_amendment` и `new_version`

* **Проект**: `ActionSpec("apply-amendment", …, legacy_codes=("apply_amendment",))`, `ActionSpec("revise", …, legacy_codes=("new_version",))`; §5.6: «точные коды BPMN/n8n: … `close_case, apply_amendment`».
* **Первоисточник**: grep по всем 6727 узлам n8n и по `bpmn_summary.txt` — `apply_amendment`: 0 вхождений; `new_version`: 0 вхождений. Механизм версий в legacy — флаг `shouldCreateVersion: true` в `workflow-update` (110 вхождений в BPMN) и `surfk.create_full_document_snapshot` (`EVGA Workflow Update (Zeebe → PostgreSQL) :: Create Version Snapshot`); доп. поручение в legacy — документ `M14` (`evga_doc_additional_order`) с обычным T1/T3, отдельного действия «применить» нет.
* **Исправление**: `legacy_codes=()` у обоих `ActionSpec`, убрать `apply_amendment` из §5.6; в `LEGACY_ACTION_MAP` для `revise` сослаться на флаг `shouldCreateVersion`, а не на код. Иначе тест-инвариант §5.3 («каждый код … либо в legacy_codes») будет проходить на несуществующих кодах.

### L-02 | major | §4.16 `LEGACY_STATUS_MAP` — пропущен статус `created`

* **Проект**: словарь «legacy-код → (сущность, значение)» плюс тест полноты «каждый код из каталога `bpmn-processes.md` §2.1 либо отображён, либо в `DROPPED_LEGACY_STATUSES`».
* **Первоисточник**: n8n создаёт документы в статусе `created`: `EVGA: Create Case v4 Parallel Docs :: Create Doc 1: Preliminary Study` — `SELECT id FROM surfk.evga_document_statuses WHERE code = 'created'`; `EVGA Additional Actions :: Create Case Document` (ветка `standard`) — то же; `EVGA: Create Case v3 Simple dev :: Create Default Documents`. Кода `created` нет ни в таблице §4.16, ни в `DROPPED_LEGACY_STATUSES`, ни в каталоге §2.1 отчёта (он собран только по BPMN `newStatus`), поэтому тест полноты его не поймает; при миграции данных документы в `created` останутся без статуса.
* **Исправление**: добавить `created → DocumentStatus.DRAFT`; расширить тест полноты списком статусов, встречающихся в SQL n8n (`created`, `rejected`, `completed`, `inactive`, `sent_to_ak`, `pending_reestr_confirmation`, `pending_invited_specialist_sign`) — остальные шесть в проекте уже есть.

### L-03 | minor | §5.4.7 — legacy-код `oa_respond`

* **Проект**: строка `deliver-respond`: «Legacy: `oa_respond` (номерное поколение)».
* **Первоисточник**: `oa_respond` — 0 вхождений в n8n и BPMN. В номерном поколении ответ ОА — это `provide_info`/`refuse_info` (требования) или `accept`/`objection` (`Process_14ytj1q`).
* **Исправление**: «нет в legacy» (либо сослаться на `provide_info`).

### L-04 | minor | §4.7 (`DocumentVersion`, комментарий к актору терминальных переходов) — колонка `activated_at`

* **Проект**: «legacy `submitted_at/approved_at/confirmed_at/activated_at`».
* **Первоисточник**: `activated_at` — 0 вхождений в n8n; `EVGA Additional Actions :: Get Doc Info` выбирает `submitted_at, approved_at, confirmed_at, returned_at`, `kvga_confirmed_at`; `n8n-cases-documents.md` §2.3 перечисляет те же колонки. Есть только значение `activated` в `evga_document_approvals.status`.
* **Исправление**: убрать `activated_at`, добавить «`evga_document_approvals.status = 'activated'`».

### L-05 | minor | §4.7 `SignatureKind` (комментарии `# legacy …`) — значения `evga_document_signatures.signature_type`

* **Проект**: `ROUTE # legacy approve (виза) / confirm`, `GROUP # work_group_signed / invited_specialist_signed`, `ACTIVATION # sign (автор)`, `EXPERT # sign_zkk`, `OBJECT # oa_acknowledge / sign_with(out)_objection`, `REGISTRY # reestr_confirm`.
* **Первоисточник**: литералы `signature_type` во всех `INSERT INTO surfk.evga_document_signatures`: `approve`, `confirm`, `oa_acknowledge` (`EVGA Docs: Lifecycle`), `sign`, `confirm` (`QC Conclusion Workflow`, `EVGA - Appeal Result (M23-RVO) actions`), `kvga_confirm`, `kvga_reject` (`EVGA Additional Actions`, `EVGA Docs: KVGA/Reestr` — и для `reestr_confirm` тоже пишется `'kvga_confirm'`), `work_group_pending → work_group_signed`, `invited_specialist_pending → invited_specialist_signed` (`EVGA: Work Group Approval`, `EVGA_ Invited Specialist`). `sign_zkk`, `sign_with_objection`, `sign_without_objection`, `reestr_confirm` — это `action_code`, а не типы подписи.
* **Исправление**: `EXPERT # legacy sign (QC Conclusion Workflow)`, `OBJECT # legacy oa_acknowledge`, `REGISTRY # legacy kvga_confirm (общий с КВГА)`; добавить `kvga_reject` к `KVGA`.

### L-06 | minor | §4.13 (строка `ErsopRegistration`), §5.4.6 — M44-VK-UK и M47-VK-TU как ЕРСОП (T3)

* **Проект**: «T3: `send_to_ersop`, `check_status`, `ersop_*`; `M11`, `M14`, `M26-TU`, `M44-VK-UK`, `M47-VK-TU`, `M54-VK-DOP-POR`».
* **Первоисточник**: `bpmn-processes.md` §2.3: T3 = `accounting_card, additional_order, m48_adm_1av, m54_vk_dop_por, talon_uvedomlenie`; §2.1: «`registered` — зарегистрирован **без ЕРСОП-цепочки**: `m44`, `m47`, `notification_slip`, `prikaz`»; в `bpmn_summary.txt` процессы `evga_doc_m44_vk_uk`/`m47_vk_tu` содержат только `activate`/`register` → `registered`.
* **Исправление**: в §4.13 оставить `M11, M14, M26-TU, M54-VK-DOP-POR` (+`M48-ADM-1AV`), а регистрацию `counter-account`/`counter-notification` в ЕРСОП пометить как решение по фронту.

### L-07 | minor | §4.7 (`EvgaDocumentType.legacy_id`, комментарий) — числовые id справочника

* **Проект**: «`surfk.evga_document_types.id` (1=M5-IPI, 2=M6-PA-S, 47=M6-PA-F, 3=M8-PLAN, 4=M9-AZ, 5=M7-POR, 7=ЗКК, 37=КК2, 46=КК3, 51=M20-VOZ)».
* **Первоисточник**: подтверждены только `1` (`Create Case v4 :: Create Doc 1` — `WHERE id = 1`; `Check Auto Copy Needed` — «ИПИ (document_type_id = 1)») и `6` = «Дело КК» (`Create Case Document`: `CASE WHEN document_type_id = 6 THEN 'open'`). Значения 2, 3, 4, 5, 7, 37, 46, 51 — числа из id BPMN-процессов (`evga_doc_2_pa`, `…_3_plan`, `…_51`), не из таблицы. `47` для `M6-PA-F` не встречается ни в n8n (0 вхождений), ни в BPMN, ни в `n8n-cases-documents.md` §5.
* **Исправление**: пометить весь список «не подтверждено, кроме 1 и 6», добавить пункт в приложение; `47` убрать или указать источник.

### L-08 | minor | §4.16 — «`sent_to_qc` (на уровне дела)»

* **Проект**: `sent_to_qc` (на уровне дела) → `DocumentStatus.QUALITY_REVIEW`.
* **Первоисточник**: `bpmn_summary.txt:1549` — `"newStatus": "sent_to_qc"` — статус **документа** в `evga_doc_qc_stage3` (цепочка `sent_to_qc → qc_acknowledged → expert_assigned`, `bpmn-processes.md` §2.1); «на уровне дела» есть только **действие** `send_to_qc` (`case-workflow-update`).
* **Исправление**: «`sent_to_qc` (документ КК3, номерное поколение) → `QUALITY_REVIEW`; действие дела `send_to_qc` → `request-quality`».

### L-09 | minor | §5.5 — `compute_phase` «коды `CaseProcessV1`/`case-workflow-update`»

* **Проект**: фаза `preparation → ready_qc1 → qc1 → registration → control → awaiting_objections → reviewing_objections → qc2 → audit_materials_implementation → qc3 → closed` названа кодами `CaseProcessV1`.
* **Первоисточник**: `CaseProcessV1` шлёт единственный `newStatus: "open"` (все состояния S0–S15 в отчёте реконструированы по кнопкам); `control`, `awaiting_objections`, `reviewing_objections`, `audit_materials_implementation` — из `m18_m19_auto_create`; `qc_approved`/`closed` — n8n `Close Case Query`, `evga_doc_6_qc`. Кодов `preparation`, `ready_qc1`, `qc1`, `registration`, `qc2`, `qc3` в legacy нет.
* **Исправление**: назвать перечень новым (`CasePhase`), а в `LEGACY_STATUS_MAP` дела отобразить только реальные `open, control, awaiting_objections, reviewing_objections, audit_materials_implementation, qc_approved, closed`.

### L-10 | minor | §4.4 `InspectionType` — «`inspection_types(code '1'/'2')`, `PLANNED_CODES = ['1','scheduled']`»

* **Проект**: коды `'1'` плановый / `'2'` внеплановый.
* **Первоисточник**: `EVGA Check Audit Type (Planned / Unplanned) :: Get Audit Type` — `JOIN surfk.inspection_types it ON it.id = c.inspection_type_id`, `:: Build Result` — `PLANNED_CODES = ['1', 'scheduled']` с комментарием «Укажи реальные коды плановых проверок … » (коды не уточнены); `EVGA Get Case Bases :: Format Response` — `UNPLANNED_TYPE_ID = 6` (`inspection_type_id === 6` — внеплановый). Кода `'2'` в источниках нет.
* **Исправление**: «плановый = code `'1'` (`PLANNED_CODES`), внеплановый = `id 6` (`Get Case Bases`); код внепланового — не подтверждено».

### L-11 | minor | §4.4 `AuditType` — «legacy id 7 — соответствие, 8 — фин. отчётность»

* **Первоисточник**: `Create Case v4 :: Create Doc 2: Audit Program1` — `CASE WHEN c.audit_type_id = 8 THEN 'M6-PA-F' ELSE 'M6-PA-S'`: подтверждён только `8`; `7` — вывод по ветке `ELSE`.
* **Исправление**: «8 — АФО (подтверждено), остальное — соответствие; id 7 — не подтверждено».

### L-12 | minor | §4.7 (`InformationRequestRound`), §4.13, приложение п.7 — «колонки `evga_doc_info_request`, `evga_doc_ir_questions` не видны»

* **Первоисточник**: `EVGA Info Request API :: IR Send To OA Query / IR Send To Auditor Query / IR Item Accept Query / IR Item Cancel Accept Query` — `evga_doc_info_request.doc_status ∈ {sent_to_oa, with_auditor}`, `evga_doc_ir_questions.item_status ∈ {answered, accepted}`, `has_new_changes`, `info_request_id`, `updated_at`.
* **Исправление**: заменить «колонки не видны» на перечень выше (полезно для миграции раундов).

### L-13 | minor | §9 (строка `seed_evga_catalogs`) — «legacy `EVGA: * - Get` (20 воркфлоу)»

* **Первоисточник**: в экспорте 30 воркфлоу с именем `EVGA: … - Get` (в т.ч. `Case Statuses - Get`, `Regions - Get`, `Reason Extend - Get`, `Units Measurement - Get`, `Annual Audit Events - Get`, `Materials Check - Get`, `Enforcement Agencies - Get`, `Query Check (Вопросы проверки) - Get`, `Registry - Get Current`).
* **Исправление**: 30; отдельно отметить, что endpoint `EVGA: Case Statuses - Get` существует (не выгружены данные, а не API) — уточнить приложение п.6.

### L-14 | minor | §4.16 — «ЕРСОП-адаптером (`statusName` в ответах)»

* **Первоисточник**: в ЕРСОП-воркфлоу поля `statusName` нет; `EVGA ERSOP Workflow :: Build Check Status Response` использует словарь `statusMessages = {registered_ersop: 'Зарегистрирован в ЕРСОП', rejected_ersop: 'Отказано в ЕРСОП', sent_revision_ersop: 'Отправлен на доработку'}`; все вхождения `statusName` — в постороннем `reject_report`.
* **Исправление**: «человекочитаемый `message` по образцу `statusMessages`».

### L-15 | minor | §4.11, §8.1 — семантика `requestId` и результат `ersop_error`

* **Проект**: `request_id = UUID v4 (requestId, n8n); docId = document_id`; `get_status(request_id)`; `successful=0`/ошибка → `ERROR`.
* **Первоисточник**: `ERSOP - Build and Send from Document :: Build ERSOP Body` — `requestId: generateUUID()`, `docId: String(doc.case_document_id)` ✓; но `EVGA ERSOP Workflow :: Call ERSOP Check Status API` вызывает `/webhook/getErsop` с `requestId = case_document_id`, т.е. опрос статуса в legacy идёт по id документа, а не по UUID; `Parse ERSOP Status` при `successful === 0 || error` ставит `new_status_code: 'draft'` (документ возвращается в проект, `bpmn-processes.md` §2.3: «`ersop_error` → обратно в X»).
* **Исправление**: в §8.1 указать, что параметр опроса в legacy — `case_document_id` (для SOAP-адаптера уточнить у КПСиСУ, добавить в приложение п.5); зафиксировать, что `ERROR` без отката в `DRAFT` — сознательное отличие от legacy.

### L-16 | minor | §7.4, §7.1 — claim `departments[]` и issuer

* **Проект**: «`department` — из claim `departments[]` (`Department.code`), иначе ЦА»; issuer `https://account-{dev,test}.…/realms/efc`.
* **Первоисточник**: `departments[]` встречается только у портальных/igo-воркфлоу (`get_sp_first_reviewer_user :: get_department`: пути `/igo/departments/...`); для ЭВГА группы Keycloak не используются (`n8n-references-auth-notify.md` §4.5), `User Login Sync :: Sync User` всегда пишет `controlling_body_code = '30101'`. Issuer: dev `https://account-dev.emf.minfin.kz/realms/efc`, test `https://account-test.efinance.gov.kz/realms/efc` (разные домены, `n8n-references-auth-notify.md` §4.1).
* **Исправление**: пометить использование `departments[]` для ЭВГА «не подтверждено» (добавить в приложение); привести оба issuer полностью.

### L-17 | minor | §7.3, приложение п.3 — `role_id 4/28, 5/30`

* **Первоисточник**: `get-qc-heads :: Get QC Heads` — `uwr.role_id IN (4, 28)`; `get-qc-experts :: Get QC Experts` — `role_id IN (5, 30)`; `Appeals - Heads list` — `role_id = 7`; `Appeals - Experts list` — `role_id = 8`. Пары (4,28)/(5,30) — «руководители КК»/«эксперты КК» двух органов/веток; какой id соответствует `kvga_kk_*`, из кода не следует.
* **Исправление**: в §7.3 писать «`qc_head`+? = role_id {4,28}, `qc_expert`+? = {5,30}, `appeal_head` = 7, `appeal_expert` = 8 (`evga_users_with_roles`)» и оставить пометку «не подтверждено» для привязки к `kvga_kk_*`.

### L-18 | minor | §4.13 (строка `Acknowledgement, DocumentDelivery`) — «`M21-AKO` (не документ)»

* **Первоисточник**: в legacy `M21-AKO` — полноценный тип документа: BPMN `evga_doc_m21_ako` (T2/T5), n8n `EVGA_ Invited Specialist :: Get Invited Specialist Documents Query` — `edt.code = 'M21-AKO' AND eds.code = 'pending_invited_specialist_sign'`.
* **Исправление**: «`M21-AKO` — в новой системе не документ (поглощён `DocumentDelivery`), сидируется `is_implemented=False`».

### L-19 | minor | §12 п.10 — «автозакрытие дела при `kvga_return` (legacy)»

* **Первоисточник**: `evga_doc_5_poruchenie` публикует `publish_case_message(closed)`, но `CaseProcessV1` это сообщение не обрабатывает (`bpmn-processes.md` §7.2: «`closed` … **нет** (игнорируется)»). Фактического автозакрытия в legacy не было.
* **Исправление**: «legacy публиковала `closed`, дело не закрывалось» — риск снять.

### L-20 | minor | §6.14 — «`rnn` — не реализуется (нет данных)»

* **Первоисточник**: `EVGA: Cases - List :: Parse Query Params` принимает `page, limit, search, status_id, controlling_body_id, audit_type_id, lang, has_sent_to_oa, document_type_ids, document_type_codes`; параметра `rnn` в legacy-API нет (все `rnn` — интеграция NSI).
* **Исправление**: указать, что `rnn` — поле фронтового `caseSearch`, а не legacy-фильтр.

### L-21 | minor | §8.5 — «`send-notification-with-recipients` из бизнес-процессов не вызывался ни разу»

* **Первоисточник**: для n8n верно (0 вызовов `/webhook/send-notification…`); но в BPMN есть процесс `send_notification` (`bpmn_summary.txt:6540-6572`, `SEND NOTIFICATION → appBaseUrl + "/api/notifications/notifications"`), т.е. портальный WS-сервис уведомлений из процессов вызывался.
* **Исправление**: уточнить: «n8n-webhook не вызывался; BPMN `send_notification` бил напрямую в портальный `/api/notifications/notifications`».

### L-22 | minor | §4.7 (`AuditDocument.registration_number`), §4.15 — момент выдачи номера и суффикс `_1`

* **Проект**: `registration_number` «при активации»; `evga-doc-with-org` pattern `…/{case_tail}{v}` с `v="_1"`.
* **Первоисточник**: legacy выдаёт `registration_number` при **создании** (`EVGA Additional Actions :: Create Case Document` — `INSERT … TO_CHAR(CURRENT_DATE,'YYYY/MM/DD') || ' – ' || LPAD(...)` / `'{prefix}-{cb_code}-' || YY || '-' || LPAD(seq,6,'0') || '/{case_id_part}' || CASE WHEN supports_version THEN '_1' END`; в `Create Case v4` и `Sub Cases` — `COUNT(*)+1`). Суффикс `_1` условный (`supports_version`).
* **Исправление**: явно зафиксировать отличие (номер при активации — решение ЭВГА; для миграции старые номера уже есть у черновиков) и сделать `v` зависящим от `supports_version`/`is_repeatable`.

### L-23 | minor | §8.1, приложение п.5 — источники значений ЕРСОП в legacy

* **Первоисточник**: `ERSOP - Build and Send from Document :: Build ERSOP Body / Load Document` — `organCode = doc.assigning_authority_id`, `oraganCodeKPSSU = doc.registration_authority_id`, `SubjectInfo.subjectId = doc.ersop_subject_id`, `ObjectInfo.objId = doc.ersop_object_id`, `number = (doc.uo_check_number || doc.case_number).slice(0, 21)`, `checkDate = uo_check_date`, `beginDate/endDate = audit_period_from/to`, `periodBegin/End = coverage_period_from/to`, `typeCheckCode = COALESCE(c.inspection_kind_id, ps.inspection_kind_id)` — всё колонки `surfk.evga_doc_registration_card` (М11) / `evga_doc_preliminary_study`.
* **Исправление**: добавить эти колонки в §8.1/приложение как источник для `values` учётной карточки и для миграции.

### L-24 | minor | §4.4 `AuditQuestion` — колонка `reg_number`

* **Первоисточник**: `EVGA: Evga Audit Questions - Get :: Get Reference Data1` выбирает `id, code_id, theme_ru/kz, sub_theme_ru/kz, program_ru/kz, npa, created_at, updated_at`; `reg_number` не встречается (все совпадения — `get_next_reg_number()` других систем).
* **Исправление**: убрать `reg_number` или пометить «не подтверждено».

### L-25 | minor | §4.16 — статусы дела разнесены по разным сущностям

* **Проект**: `awaiting_objections`, `reviewing_objections` отнесены к `DocumentDelivery`; `control`, `audit_materials_implementation` — в `DROPPED_LEGACY_STATUSES`.
* **Первоисточник**: все четыре — `newStatus` **дела** из `case-workflow-update` процесса `m18_m19_auto_create` (`bpmn_summary.txt`, статусы `control(1)`, `awaiting_objections(1)`, `reviewing_objections(1)`, `audit_materials_implementation(3)`); в каталоге документных статусов §2.1 их нет.
* **Исправление**: перенести все четыре в одну строку «фаза дела → `compute_phase`» (см. L-09).

### L-26 | minor | §5.3 (формат `Transition`) — колонка `workflow_code`

* **Проект**: «структура `surfk.evga_status_transitions` (`document_type_id/workflow_code, from_status_id, action_code, to_status_id, action_name_ru/kz, required_role_code, assignment_type, requires_signature, requires_comment, is_automatic`)».
* **Первоисточник**: `EVGA - Appeal Result (M23-RVO) actions :: Get Available Actions Query` и `QC Conclusion Workflow :: Get Available Actions Query` выбирают `t.action_code, t.action_name_ru, t.action_name_kz, t.requires_signature, t.requires_comment, t.required_role_code, t.is_automatic` с условием `t.document_type_id = d.document_type_id` и `d.status_id = t.from_status_id`; колонок `workflow_code`, `assignment_type`, `to_status_id` в этих запросах нет (`to_status_id` есть только в `evga_document_workflow_history`; `assignment_type` — в JSON `workflow_state.available_actions`).
* **Исправление**: «формат по `evga_status_transitions` (подтверждённые колонки: `document_type_id, from_status_id, action_code, action_name_ru/kz, required_role_code, requires_signature, requires_comment, is_automatic`) + `assignment_type` из `workflow_state.available_actions`».

---

## Проверка приложения «не подтверждено»

Уже помечено корректно: п.1 (`zeebe_process_id → prc_*`, M-коды видов без кода), п.2 (`qc_route`), п.3 (`report_manager*`, `role_id 4/28, 5/30`), п.4 (БИН в claims), п.5 (`organCode`, `subjectId/objId`, `userCreate/userSign`, транспорт, callback, `order.type → M_TYPE_*`), п.6 (id статусов 1, 2, 3, 22, 49, 11, 12), п.8 (тела функций), п.9 (`evga_document_mappings`, данные справочников), п.10–12.

Нужно добавить в приложение: числовые `legacy_id` кроме 1 и 6 (L-07); код внепланового `InspectionType` и `audit_type_id = 7` (L-10, L-11); claim `departments[]` для ЭВГА (L-16); `AuditQuestion.reg_number` (L-24); параметр опроса ЕРСОП (`case_document_id` vs UUID) (L-15); `workflow_code`/`assignment_type` как колонки `evga_status_transitions` (L-26). Нужно **исправить**: п.7 — колонки `evga_doc_info_request`/`evga_doc_ir_questions` частично видны (L-12); п.6 — API `EVGA: Case Statuses - Get` существует, отсутствуют только данные (L-13).

---

## Проверено и подтверждено

### prof (стиль и наличие)

* Базовые классы и pk: `TimeStampedModel` (UUID pk, `created_at/updated_at/created_by SET_NULL related_name="+"`), `Attachment` (GFK, `kind` choices max_length 32, `checksum`), `AuditEvent` append-only с `AuditEventQuerySet`, `NumberSequence(key, scope, pattern, current_value)` + `IssuedNumber` (`core/models.py`); `AuditAction` — ровно 7 значений; `AuditEvent` вне `core/models.py`, admin и тестов не используется (0 вхождений) — утверждение решения 14 верно.
* `TextChoices` с UPPER-кодом и русским label (`DocumentStatus`, `CaseStatus`, `ErsopPackageStatus`); `_STATUS_LABEL_OVERRIDES` и `document_status_label` (`documents/models.py:67-79`); `UniqueConstraint(name="<app>_<model>_natural_key")` (`documents_controldocument_natural_key`, `documents_acknowledgement_natural_key`, `ersop_ersoppackage_natural_key`, `semiannual_listversion_natural_key`); `__str__` через ` · `.
* Сервисы: функции-модули, первый позиционный агрегат, keyword-only актор (`approved_by=`, `signed_by=`, `sent_by=`, `recorded_by=`, `by=` в `ersop/services/package_1.py`), `@transaction.atomic`, `select_for_update`, `save(update_fields=[..., "updated_at"])`, `DocumentTransitionError` с русскими текстами, `IntegrityError → DocumentTransitionError` (`acknowledgement.py:41-42`); `issue_number` идемпотентен по `(sequence, content_type, object_id)`, тесты конкурентности `core/tests/test_numbering.py` (`django_db(transaction=True)` + `threading`).
* API: `APIView` на действие с явными URL (`documents/api/urls.py:24-27`), `required_domain/required_levels` + `get_permissions() → [IsAuthenticated(), HasDomainLevel()]`, диспетчер `_APPROVERS/_SIGNERS` по коду типа, `_READ_LEVELS`, `_assert_department_in_scope` в `documents/api/views.py:55-65` и его импорт в `cases/api/views.py:14`; `@action` в prof не используется; `@extend_schema` на каждом методе; `ScopedQuerySetMixin` (`scope_department_field`, `is_national`, `allowed_department_ids`), `HasDomainLevel` через `role__permissions__level__in` (уровни неиерархичны), `IsSubjectRepresentative`; `RoleAssignmentQuerySet.active()`; `PermissionDomain` = 3 домена, `PermissionLevel` без `CONFIRM`; `Role.code max_length=32` (вмещает `evga-appeal-commission-member`), `RolePermission.domain max_length=16` (вмещает `evga_execution`).
* Формат ошибок `{"type","title","status","detail","code"}` (`core/exceptions.py`), 404-мидлварь `JsonNotFoundMiddleware`; сериализаторы с контекстом `{"cabinet": True}` и `reverse("cabinet-document-download-attachment")` (`documents/api/serializers.py:35-40`, `cabinet/api/urls.py:21-25`); `DETAILS_SERIALIZERS`; `CaseRegistryFilter.filter_search` через `Q`, `filter_status` Python-проходом (в проекте заменён на колонку — верно описано).
* Seed-паттерн `update_or_create` под `@transaction.atomic` + `self.style.SUCCESS` (`seed_roles.py`, `seed_number_sequences.py` с `define_sequence`, `seed_catalogs.py`); роль `observer` есть; `entrypoint.sh` — `migrate → collectstatic → seed_catalogs, seed_roles, seed_number_sequences, seed_document_types, seed_report_forms, seed_checklists, seed_risk_rules`.
* Settings/env/docker: `TIME_ZONE="UTC"`, `API_SESSION_COOKIE_NAME="saq_session"`, `samesite="Lax"` (`sessions.py:36`), `PAGE_SIZE=25`, `max_page_size=200`, `SPECTACULAR_SETTINGS.TITLE`, `KEYCLOAK_*`, `STORAGES` S3/MinIO в `production.py`, `httpx` в `requirements/base.txt`, `pyproject.toml` (`--reuse-db`, ruff 120), `docker-compose.yml` в корне репозитория с `postgres/minio/minio-init/backend` и `MINIO_BUCKET=saq-attachments`, `deploy/.env.example`; `backend/saq-cookies.txt` действительно лежит в репозитории; миграции `core` — только `0001`, `0002`.
* Прочее: `provision_user_from_claims`, `MeSerializer` (`roles[{code,name,scope,department}]`, `position`, `is_subject_representative`, `subject`), `RegisterView` по `bin` (`local/register`), `SemiannualListVersion` (`version_number`, `*_at/*_by`), `DfoExtract.values` JSONField, `PrescriptionItem.status` property, `ExecutionDecisionKind RELEASE/EXTEND`, `fake_register_package`, `ErsopPackage/ErsopPackageItem`, `Subject` с `bin_validator`/`iin_validator`, `SubjectPerson`, prof-справочники `SubjectTypeRef, BusinessCategory, ViolationSeverity, RiskDegree, InspectionSubjectMatter, ControlEligibilityRule`, `Region.name_kk`; хелперы тестов `_user_with_cases_role`, `_department`, `CaptureQueriesContext`-тест `test_list_does_not_prefetch_the_unused_persons_relation` (`subjects/tests/test_api.py`); фронт: `saqModules.ts` — `{id: "evga", type: "external", url: "https://saq-evga-test.vercel.app/#/cases"}`, `api/client.ts` — `errorMessage`, `API_ERROR_EVENT = "saq:api-error"`, `maybeMe`.

### Старая система

* **Номера**: дело — `CONCAT(controllingAuthorityCode, '-', TO_CHAR(CURRENT_DATE,'YY'), '-', LPAD(surfk.get_next_case_sequence(year),5,'0'))` (`Create Case v4 :: Insert Case1`); подчинённое дело — `['ВП-'] || split_part(parent_reg,'-',1) || '-' || YY || '-' || LPAD(COUNT(*)+1, 6,'0') || '/' || split_part(parent_reg,'-',3)` (`Sub Cases :: Create Query`); документ `standard` — `YYYY/MM/DD – NNNNN` через `get_next_doc_sequence('standard', year)`; `with_org` — `{reg_number_prefix}-{controlling_body_code}-YY-NNNNNN/{case_id_part}[_1]`; приказ — `doc_reg_number || '_P_' || get_next_doc_sequence('PRIKAZ', year)` (`Register Document Query`); `reg_number_format`/`reg_number_prefix`/`supports_version`/`allow_multiple` — колонки `evga_document_types`.
* **Статусы**: каталог `bpmn-processes.md` §2.1 (45) совпадает с `newStatus` в `bpmn_summary.txt`; n8n-специфичные `rejected`, `completed` (`Appeals - Cases list`: `ds.code IN ('active','signed','completed')`), `inactive` (синтетический в `Get Case Documents`), `sent_to_ak` (`status_id = 49` в `get-ak-case-documents`/`list-ak-cases`), `pending_reestr_confirmation` (история `Docs: KVGA/Reestr`), `pending_invited_specialist_sign`, `c.status_id IN (11, 12)` (`list-qc-cases`) — все, кроме `created`, в проекте учтены; `open/closed` у `evga_doc_6_qc`; `evga_document_approvals.status` содержит `kvga_confirmed/kvga_returned/kvga_rejected`; ЕРСОП `confirmstatusid '1'→registered_ersop/ersop_registered, '2'→rejected_ersop, '3'→sent_revision_ersop/ersop_revision`, нет ответа → `pending_for_consideration/ersop_accepted`, `successful=0` → `ersop_error` (`Parse ERSOP Status`); `'oK!'` как признак успеха отправки.
* **Коды действий**: все коды, перечисленные в `ActionSpec.legacy_codes` и §5.6, кроме `apply_amendment`, `new_version`, `oa_respond`, найдены в BPMN `actionCode`/`availableActions[].code` или n8n (`Generic Action Check`, `Documents Router :: Route To Domain`): `submit, send_to_approval, resubmit, approve, confirm, qc_confirm, return, return_from_approval, return_from_confirmation, return_for_revision, qc_return, reject, activate, sign, signed, send_to_ak, send_to_kvga, kvga_confirm, kvga_return, kvga_reject, change_kvga_confirmer, send_to_qc, send_to_qc_stage2/3, send_to_confirmation, send_to_work_group, sign_work_group, approve_work_group, send_to_reestr_confirmer, reestr_confirm, reestr_return, reestr_reject, change_reestr_confirmer, sign_zkk, submit_confirm, create_zkk, send_to_ersop, register_ersop, register, check_status, ersop_registered/rejected/revision/accepted/error, send_to_audit_object, send_to_oa, audit_object_acknowledged, oa_acknowledge, acknowledge, acknowledge_case_document, sign_without_objection, sign_with_objection, accept, objection, create_objection_doc, close_case, provide_info, refuse_info, review_info, accept_info, reject_info, resend_to_oa, mark_refused, overdue, change_approver, change_confirmer, change_head, assign_qc_expert(_stage2/_stage3/_kvga/_appeal), change_qc_expert, change_qc_head, create_qc_conclusion(_stage2/_stage3/_kvga), resubmit_to_qc_stage2, create_resultat_vozrazhenie, ready_send_to_qc(_2/_3/_kvga), ready_send_to_appeal, ready_kvga_confirmed, ready_send_confirmation, zkk_confirmed, work_group_complete, prev_approved, doc_approved, signed_automatically, default, status_change, verification, oa_confirm, with_auditor, review_decision, accepted, return_to_draft (evga_doc_2_pa)`. Правило `get_available_actions` (роль ∧ назначение; для `workgroup/workgroup_lead` достаточно назначения) — `EVGA Additional Actions :: Get Available Actions Response`.
* **Гейты и таймеры**: `check-docs-status` вызывается с `doc_types`/`status` (`evga_doc_5_poruchenie`: `["M8-PLAN","M6-PA-S","M6-PA-F"]`/`approved`; `audit_conclusion`: `["M25-PRED"]`/`approved`; `predpisanie`: `["M24-AZK","M25-PRED"]`/`active`; `["M18-RNAFO","M19-AD"]` при `auditTypeCode = "16"`); таймеры — три `timerEventDefinition`: `P10D` в `evga_doc_51` («Срок возражений истёк» → `signed_automatically`), `deadlineDatetime` в `evga_doc_info_request` и `evga_doc_m45_vk_treb` (истечение → `info_refused`, `source: "zeebe_timer"`); `m18_m19_auto_create`, `audit_conclusion → create M25-PRED`, `evga_doc_vap_notification → trigger_doc_message(ersop_registered, M7-POR)`.
* **ЕРСОП-контракт**: `systemId '10002'`, `requestId` UUID v4, `docId = case_document_id`, `requestDate`, `messageType M_TYPE_STARTED`, `message.started{number(≤21), organCode, typeCheckCode, typeAuditCode, checkDate, beginDate, endDate, periodBegin, periodEnd, oraganCodeKPSSU, shortFabula/Kz, faces[{iin, lastName, firstName, middleName, positionRU/KK/QAZ, organizationNameRU/KK/QAZ, phone, mobile}], checkQuery{checkQueryCode:'0'+…, checkThemeCode:'0'+…}, files[{fileName, mimeType, fileLang:'kz', fileDesc, fileBase64}], SubjectInfo{subjectId, bin}, ObjectInfo{objId}, userCreate, userSign}` (MOCK-константы), даты `YYYY-MM-DD+05:00`; `SEND_REQ_TO_ERSOP :: Switch` — 8 типов `M_TYPE_STARTED/PROLONGED/PERIOD_CHANGED/RESUMED/SUSPENDED/STOPED/EXECUTORS_CHANGED/FINISHED`, сборщики `build Prolonged{CheckId, ProlongBegin, ProlongEnd, ReasonProlongCode, Note, FilesContent, UserSign}`, `PeriodChanged`, `Resumed{ResumeDate}`, `Suspended{SuspendDate, ReasonSuspendCode}`, `Stoped{Reason*Code, Who*Code}`, `ExecutorChanged`, `Finished{FactBeginDate, FactEndDate, ResultCheckCode, Ammount*, SendCourtCode, LawOrgCode, SendDate, TalonQuery}`; транспорт `SI_SUR2ERSOP_RequestSubjectAsync`, ns `http://minfin.kz/ERSOP`, basic auth; ответы в `acc_100.rspns_msg_rsp`.
* **Keycloak**: realm `efc`, аудитория/azp `web-ui-service`, `preferred_username` = ИИН (`^[0-9]{12}$`, иначе `invalid_iin`), `realm_access.roles` (ключа нет — роли не трогаются; есть — полная перезапись через `DELETE`/`INSERT` с `controlling_body_code='30101'`), `origin_user_id → surfk.users.origin_user_id`; `SUBSYSTEM_SCOPE_CONFIG.evga.assignableRoles` — 19 ролей ровно как в §7.3/§7.4 (`auditor, audit_object_signer, qc_head, qc_expert, kvga_kk_head_approver, kvga_kk_expert, approver, confirmer, kvga_confirmer, appeal_head, appeal_expert, invited_specialist, lawyer_head, lawyer, report_manager, report_manager_kvga, superuser_ga_rk, reader_ga, dsp_access`), `admin_evga`, `surfk_user`/`evga_user`, `portal_admin`; инверсия `approver→reviewer`, `confirmer→approver` (`bpmn-processes.md` §9.3); BPMN `allowed_roles` включают `reestr_confirmer`, `invited_specialist`, `kvga_kk_*`, `oa_responsible`, `oa_confirmer`, `audit_object`, `audit_object_signer`; `assignment_type ∈ {author, approver, confirmer, qc_head, qc_expert, workgroup, workgroup_lead, kvga_confirmer, reestr_confirmer, appeal_head, kvga_kk_expert}`.
* **Таблицы и функции**: `surfk.cases` (`registration_number, audit_object_id, controlling_body_id, inspection_type_id, inspection_kind_id, audit_type_id, status_id, author_id, author_iin, start_date, end_date, audit_goal_ru/kz, is_electronic_audit, is_dsp, director, workflow_state, zeebe_process_instance_id, parent_id, sub_case_type, sub_case_data, plan_object_id, qc_expert_iin, is_deleted`), `case_statuses (open, qc_approved)`, `case_bases`, `case_base_attachments`, `case_participants (employee_id, user_iin, is_lead, is_active, removed_at, removed_by, assigned_by)`, `case_qc_expert_assignments`/`case_qc_assignments (action assigned/unassigned, qc_head_iin)`, `case_appeal_expert_assignments`, `audit_objects (bin, name_ru, name_kz, director, address_ru, org_legal_form_id, risk_level_id, risk_value; upsert по bin)`, `evga_audit_object.object_data`, `annual_plans`, `plan_objects (coverage_2023..2025, score_2023..2025, score_3_years, max_score, risk_level_gu/abp, risk_probability)`, `subj_sched_insp`, `evga_document_types (sends_to_audit_object, creator_roles, depends_on_document, creation_condition, audit_type_codes, allow_multiple, supports_version, requires_approval/confirmation/kvga_confirmation/signature, zeebe_process_id, stage_id, sequence_order)`, `evga_document_stages (1 Планирование аудита, 2 Проведение аудита, 3 Документы по результатам…)`, `evga_available_document_types`, `evga_document_mappings (root_table, fields_mapping, subtables_mapping, form_schema)`, `evga_case_documents` (колонки по `n8n-cases-documents.md` §2.3), `evga_document_versions (version_number, data_snapshot, returned_by_*, return_comment, previous_status_id)`, `evga_document_signatures (signature, signer_iin, signer_name, signer_organization, signature_type, signed_at, document_hash; частичный UNIQUE (case_document_id, signer_iin, signature_type) WHERE work_group_pending)`, `evga_document_approvals`, `evga_document_workflow_history`, `evga_audit_log (entity_type, entity_id, case_document_id, case_id, action_code, status_code, field_changes, metadata, performed_by_*, comment, source)`, `case_status_history`, `case_activity_log`, `evga_audit_object_notifications`/`oa_notifications`, `evga_qc_requests`, `evga_doc_preliminary_study (joint_inspection_bin, is_electronic_audit, is_dsp)`, `evga_doc_rc_work_group`, `evga_doc_cma_work_group (member_role_code invited_specialist/invited_expert)`, `evga_doc_control_measurement_act`, `evga_doc_vrc_violations`/`vrfn_violations`/`vrc_results`/`vrc_risk_objects`, `evga_doc_ap_questions`, `evga_doc_ao_risk_objects`, `evga_doc_objection_appeal_result`/`oar_violations`, `evga_doc_registration_card`, `portal.notifications (user_id, title, message, event_type, notification_type, meta_data, status UNREAD/READ, channel WEB, read_at)`, `surfk.users (keycloak_user_id, origin_user_id, iin, fullname, …)`, `evga_roles (can_create/approve/confirm_documents, role_level)`, `evga_user_roles`, `evga_users_with_roles (user_iin, user_fullname, role_code, role_id, role_level, controlling_body_code)`; справочники `audit_types (ersop_code)`, `inspection_types`, `control_reasons_types` (коды `13/14` → `qc_route = 'KK KVGA'` при `inspection_type_id = 6`), `check_initiators`, `organizational_legal_forms`, `risk_levels`, `risk_object_types` (+ маппинг `PPContractItem/PICustomer/PPContractHeader…` в `violations`), `offense_type (type_code, parent_code, offence_name_ru/kz, level_ru/kz)` и `evga/references/offense-type/tree` с натуральной сортировкой, `dictionaries (type_cons_offence, status_offense)`, `sampling_methods`, `response_measures`, `evga_audit_questions (code_id, theme_*, sub_theme_*, program_*, npa)`, `controlling_bodies`, `d_controlling_orgs (code, bin, par_id, org_type_id, org_lvl_id, su_code)`, `positions (code, name_ru, name_kz)`, `evga_legal_basis_audit (legal_basis_id)`, `d_query_check_npa (query_check_code → '0'+code, npa.code → '0'+…)`, `inspection_kind_id 24/25` захардкожены в `Get Case Detail`; хранимые функции `check_document_creation_condition, check_document_submit_allowed, check_transition_condition, get_case_blocking_statuses, send_case_to_qc, assign_qc_expert, complete_qc_review, get_qc_tasks, get_available_document_types_for_case, seed_doc_work_group, create_full_document_snapshot, send_document_to_audit_object(…, requires_acknowledgment, expires_days=5), acknowledge_document(notification_id, …), check_sub_case_creation_condition, get_next_case_sequence, get_next_doc_sequence`.
* **Воркфлоу/интеграции, на которые ссылается проект**: `EVGA: Create Case v4 Parallel Docs` (5 документов M5-IPI, M6-PA-S/F, M8-PLAN, M9-AZ, M7-POR), `EVGA Case Update (Extended with workflow_state)`, `EVGA Get Case Bases`, `EVGA: Get Case Detail`, `Get Available Document Types`, `EVGA Docs: CRUD/Lifecycle/KVGA-Reestr/Case Misc/Meta/Generic/QC/Roles`, `EVGA Documents Router`, `EVGA Sub Cases (create/get/list)`, `EVGA: Cases - List`, `EVGA: Cases - Delete (Soft Delete)`, `EVGA: Audit Objects - Get`, `EVGA: Audit Object - Search by BIN`, `EVGA: Employees - Get`, `list-qc-cases`, `get_qc_tasks`, `qc/heads`, `qc/experts`, `appeals/heads`, `appeals/experts`, `Appeals - Cases list`, `OA get case` (`oa/cases`), `acknowledge-document` (`oa/acknowledge`), `activity-log`, `EVGA Document Verify (Public)` (баг `WHERE d.id = 2854`), `User Login Sync`, `Keycloak Subsystem Access`, `Keycloak Subsystem Users V2`, `ERSOP - Build and Send from Document`, `SEND_REQ_TO_ERSOP`, `EVGA ERSOP Workflow`, `Service GDBJL :: Map to JSON` (`{bin, regStatus, regStatusCode, regDate, fullName{ru,kz}, shortName{ru,kz}, orgForm, orgFormCode, FormOfLaw, ownership, head{iin, fullName}, address{…}, activityKinds, founders[]}`), `findJurByBin`, `listPreAudits`, `camel-gateway/api/out-integrations/gbdul|gbdfl` с `X-API-TOKEN`, `SI_GBD_JL_PIWS_OS`/`getJurInfoByBin` (basic auth), `send-notification-with-recipients`, `FREE_TEXT_NOTIFICATION_EVENT`.
