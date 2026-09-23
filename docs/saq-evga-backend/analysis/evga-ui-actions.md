# ЭВГА (saq-evga-test): пользовательские действия в UI и что из них должно вызывать сервер

Область анализа: `src/` фронта ЭВГА `saq-evga-test`.
Образец стиля бэкенда: `saq-prof-control-demo/backend` (Django 5.2 + DRF 3.16 + django-filter + drf-spectacular + django-storages[s3]/MinIO + Keycloak).
Старая реализация для переиспользования: `n8n_old_project_archive/n8n_export/workflows/*.json`.

Все имена файлов, функций, полей и статусов ниже взяты из исходников (идентификаторы — как в коде).

---

## 0. Краткие выводы

1. Фронт ЭВГА — «толстый клиент»: вся бизнес-логика (state machine документов, маршруты согласования, КК, регистрация ЕРСОП, ознакомление объекта, уведомления, сроки) реализована чистыми функциями TypeScript вида `(audit, doc, actor, ...) => AuditDocument | AuditCase` в `src/modules/evga/*.ts` (≈ 6 000 строк). UI-компоненты только вызывают эти функции и передают результат в единственную мутацию `updateCase(next: AuditCase)` из `useAuditCases.ts`.
2. Хранилище — IndexedDB (`indexedDbCaseRepository.ts`: БД `saq-evga-test`, v1, store `state`, ключ `cases`). При любом изменении сохраняется **весь массив `AuditCase[]`** (второй `useEffect` в `useAuditCases`). Контракт `AuditCaseRepository { load(): Promise<AuditCase[]|undefined>; save(cases): Promise<void> }` — единственная точка ввода/вывода, кроме `localStorage` для выбранной роли (`saq.evga.account.v1`), политики сроков (`saq.evga.execution-policy.v1`), состояния сайдбара (`saq.sidebar.expanded.v1`) и `sessionStorage` для «выхода» (`saq.evga.demo.signed-out`).
3. Файлы хранятся как base64 data-URL внутри JSON (`Upload.data`, `utils/files.ts: readUploads → FileReader.readAsDataURL`). Они лежат в 12+ местах структуры дела (вложения дела, оснований, версий документов, строк форм `files`, ответов объекта, апелляции, третьих лиц). Это первое, что надо вынести в `Attachment` + MinIO.
4. Пользователь/роль — демонстрационные: массив `accounts` (24 учётки, 10 ролей `Role`) в `data/demoData.ts`; смена роли — выпадающий список в `AppShell`. Бизнес-код местами проверяет **конкретные `account.id`** (`"approver"`, `"quality-head"`, `"commission-chair"`, `area === "appeal"`), это нужно заменить на роли/permission-домены в стиле prof (`HasDomainLevel`, `RoleAssignment`).
5. Для перевода на сервер минимально: (а) заменить `indexedDbCaseRepository` на HTTP-адаптер и убрать «сохранение всего массива»; (б) заменить вызовы доменных функций в обработчиках кнопок на вызовы API (список ниже — 70+ действий, сгруппированы в ~45 endpoint'ов); (в) заменить `Upload.data` на ссылку на `Attachment`; (г) вынести справочники (`catalogue`, `objectRegistry`, `people`, `accounts`, `basisOptions`, `initiatorOptions`) в API. Рендеринг форм (`DocumentForm`, `FormFields`, `documentForms.ts`, печатные формы) можно не трогать.
6. Серверная бизнес-логика может быть **портирована 1:1** из `documentStateMachine.ts`, `workflow.ts`, `mainWorkflow.ts`, `preparationWorkflow.ts`, `informationRequests.ts`, `appeals.ts`, `amendments.ts`, `thirdParties.ts`, `qualityAssignment.ts`, `executionItems.ts`, `deadlines.ts` — там уже есть проверки прав, версий и «устаревшего состояния» (`expectedVersion`, `mainCurrentBlock`, `preparationCurrentBlock`, `assertExecutionResponseSave`), которые на сервере становятся проверками optimistic concurrency.

---

## 1. Архитектура фронта сегодня (факты)

### 1.1 Точка входа и состояние

| Файл | Роль |
|---|---|
| `src/App.tsx` | `useEvgaNavigation()` (hash-роутинг `location.hash`), `useDemoSession()` (вход/выход), `lazy(EvgaModule)` |
| `src/modules/evga/EvgaModule.tsx` | Контейнер модуля: `useAuditCases(indexedDbCaseRepository)`, `account` (текущая роль), `toast`, `caseForm` (модалка создания/изменения дела), рендер страниц по `path` |
| `src/modules/evga/useAuditCases.ts` | `cases`, `loaded`, `loadError`, `saveError`, `updateCase(next)`. При загрузке подмешивает демо-дела: `workflowSampleCases()`, `preparedCases()`, `addPlannedSampleCases`, `addRegistrySampleCases`, `enrichSampleQualityForms`, `migrateLegacyApprovalRoutes`, пересчёт `quality: [qualityPassed(0..2)]` |
| `src/services/auditCaseRepository.ts` | Контракт `AuditCaseRepository` |
| `src/services/indexedDbCaseRepository.ts` | Адаптер IndexedDB (сериализованная очередь `pendingSave`) |
| `src/types.ts` | Все типы: `AuditCase`, `AuditDocument`, `DocumentVersion`, `Upload`, `Person`, `AuditObject`, `Basis`, `HistoryEntry`, `Appeal`, `ThirdPartyNotice`, `Account`, `Role`, `DocStatus`, `Stage` |
| `src/shared/workflow/approvalRoute.ts` | Чистая модель маршрута согласования `ApprovalRoute` (этапы, sequential/parallel, `decideApprovalRoute`, `supersedeApprovalRoute`, `getApprovalTasks`); помечена `execution: "local-demo"` |
| `src/shared/execution/execution.ts` | Чистая модель реестра исполнения `ExecutionItem`, `DeadlinePolicy`, селекторы |

Единственная мутация: `updateCase(next)` заменяет `AuditCase` по `id` или добавляет в начало массива. Все действия строятся как `onChange(f(audit))` или `onSave(f(doc))` → `saveDocument(audit, doc, account)` → `updateCase`.

### 1.2 Маршруты (hash)

| Путь | Экран |
|---|---|
| `#/login` | `pages/LoginPage.tsx` |
| `#/cases` | `pages/CasesList.tsx` (реестр дел) |
| `#/cases/:caseId/general` \| `group` \| `regulatory` | `pages/CaseWorkspace.tsx` вкладка «Общая информация» (+ раскрытия «Рабочая группа», «Сроки и регистрация») |
| `#/cases/:caseId/documents` \| `working` \| `counter` \| `appeal` \| `third-parties` \| `amendments` | вкладка «Документы» и её разделы |
| `#/cases/:caseId/attachments` \| `history` \| `progress` | вкладки «Вложения», «История», «Ход исполнения» |
| `#/cases/:caseId/documents/:docId[/edit][/versions/:n]?view=form\|print\|sources&section=&item=` | `pages/DocumentWorkspace.tsx` |
| `#/quality`, `#/quality/:caseId` | `components/QualityRegistry.tsx` |
| `#/quality/:caseId/documents/:docId[/edit]` | `components/QualityDocumentWorkspace.tsx` (обёртка над `DocumentWorkspace`) |
| `#/objects` | `pages/ObjectsRegistry.tsx` |
| `#/tasks?case=` | `pages/ApprovalTasks.tsx` + `shared/workflow/ApprovalInbox.tsx` |
| `#/execution[/:caseId]` | `pages/ExecutionRegistryPage.tsx` + `shared/execution/ExecutionRegistry.tsx` |
| `#/notifications` | `components/Notifications.tsx` |

### 1.3 Роли и учётные записи (демо)

`Role = auditor | reviewer | approver | quality | kvga | reestr-confirmer | invited-specialist | object | appeal-head | appeal-expert`.
`accounts` (`data/demoData.ts`): `auditor` (ФИО из `config.ts: DEMO_USER`), `reviewer-1`, `reviewer-2`, `approver`, `quality`, `quality-2`, `kvga`, шесть участников из `people` (`ivanov`, `smirnov`, `suvorov`, `petrov`, `daulet`, `invited-specialist`), `coauthor`, `object`, `quality-head` (role approver), `appeal-head`, `appeal-expert`, `appeal-expert-2`, `commission-1/2` (role reviewer, `area: "appeal"`), `commission-chair` (role approver, area appeal), `reestr-confirmer`.

Места, где логика завязана на конкретный `id`, а не на роль:
- `caseAccess.assignCoauthor`: `actor.id !== "approver"` → ошибка;
- `appeals.decideArguments`: `actor.id !== "approver"`; `appeals.recordAdmission`: `actor.id !== "commission-chair"`;
- `qualityAssignment.canAssignQualityExpert`: `actor.id === "quality-head"`;
- `reviewParticipants.routeApprover`: `"commission-chair"` для `objection-result`, `"quality-head"` для `quality1..3`, иначе не `quality-head` и не `area appeal`; `routeReviewer`: `area === "appeal"` только для `objection-result`;
- `mainWorkflow.submitMainQualityToHead`: `accounts.find(a => a.id === "quality-head")`;
- `AppShell`: «Переключиться на объект» ищет `role === "object"`.
На сервере это должны быть роли/должности из справочника сотрудников + `PermissionDomain`/`PermissionLevel` (prof: `apps/accounts/models.py`).

### 1.4 Ключевые доменные структуры

- `AuditCase`: `id`, `number` (`30101-YY-NNNNN`), `object: AuditObject`, `auditType`, `checkType`, `checkKind`, `electronic`, `dsp`, `jointObject?`, `purposeRu/Kz`, `group: Person[]`, `bases: Basis[]`, `author` (ФИО!), `coauthors?: string[]` (id учёток), `status: "Открыто"|"Закрыто"`, `executionState?`, `attachments: Upload[]`, `documents: AuditDocument[]`, `documentSequence?`, `quality: [bool,bool,bool]`, `history: HistoryEntry[]`, `notifications?`, `calendar?`, `schedule?`, `parentCaseId?` (встречная проверка), `personType?/personBirthDate?/entrepreneurName?/counterQuestion?`, `qualityAssignments?`, `appeal?`, `thirdParties?`, `thirdPartiesReviewed?`, `amendments?`, `sampleScenario?` (демо-метка).
- `AuditDocument`: `id`, `kind` (код из `data/documentMatrix.ts`: 36 видов основного дела `docKinds`, 7 встречной проверки `counterDocKinds`, 62 рабочих формы `workingDocKinds` из `workingPapers.json`), `stage: 0|1|2`, `number` (`${audit.number}/NN`), `author` (ФИО), `createdAt`, `versions: DocumentVersion[]`.
- `DocumentVersion`: `version`, `status: DocStatus` (11 значений: `Проект`, `Направлен на согласование КК`, `На согласовании`, `На утверждении`, `Согласован`, `На подтверждении КВГА`, `На подтверждении реестра`, `На подписании рабочей группой`, `Возвращен на доработку`, `Отклонен`, `Активный`), `values: Record<string,unknown>` (данные формы по схеме `forms/documentForms.ts`), `attachments: Upload[]`, `group: Person[]`, `reviewers/reviewerIndex/approver` (legacy), `signatures[]`, `approvalRoutes?: ApprovalRoute[]`, `qualityConclusion?/qualityDecision?`, `ownerRole?/ownerId?`, `sourceVersions?` (ссылки на версии исходных документов, у `additional` с `contentSnapshot`), `registration?` (ЕРСОП), `delivery?` (ознакомление/решение объекта), `informationRequest?` (циклы требования), `preparation?` (KVGA, подписи РГ), `main?` (подписи РГ отчёта, подтверждение реестра, КК2), `mainQuality?`, `createdAt`, `history[]`.

---

## 2. Карта экранов и действий

Обозначения в колонке «Endpoint»: префикс `/api/evga/...`; стиль prof — `ViewSet` + `@action(detail=True, methods=["post"])` (в prof сейчас отдельные `APIView` на действие, например `documents/<uuid:pk>/approve/`; оба варианта совместимы с их роутером `DefaultRouter`). Ответ действия — всегда обновлённый агрегат (`DocumentSerializer` / `CaseSerializer`), ошибки бизнес-правил — `serializers.ValidationError({"detail": str(exc)})` из `DocumentTransitionError`, как в `apps/documents/api/views.py` prof; конфликт версий — HTTP 409 в envelope `apps/core/exceptions.py`.

### 2.1 Логин / оболочка

| Действие | Компонент → функция | Что меняется | Сервер |
|---|---|---|---|
| «Войти в ЭВГА» | `LoginPage.onLogin` → `useDemoSession.login()` + `navigate("/cases")` | `sessionStorage` | Keycloak OIDC как в prof: `GET /api/auth/keycloak/login`, `GET /api/auth/keycloak/callback`, `GET /api/auth/me` (`apps/accounts/api/keycloak_views.py`). Старый стек тоже Keycloak (`Keycloak Subsystem Users V2`, `User Login Sync`, `Get Keycloak Users`). |
| «Выйти» | `AppShell.onLogout` (подтверждение при `editing`) | `sessionStorage` | `POST /api/auth/keycloak/logout` |
| Смена роли (список `accounts`) | `AppShell.onAccountChange` → `setAccount`, `localStorage["saq.evga.account.v1"]` | текущая учётка | **Убрать.** Роль приходит из `/api/auth/me` (`roles: RoleAssignment[]`). Для демо-стендов допустимо `POST /api/auth/local/login` под разными seed-пользователями. |
| «Переключиться на объект» / «Вернуться в контролирующий орган» | `AppShell` (`portalAccount`) | учётка | Отдельный кабинет объекта (prof: `apps/cabinet`, `IsSubjectRepresentative`, `User.is_subject_representative`, `subject`). |
| Счётчик уведомлений в меню | `EvgaModule.notificationCount` — считает по всем делам `notifications[].recipients/readBy` | — | `GET /api/evga/notifications/?unread=true` (count) |
| «Главное меню» | ссылка `MAIN_MENU_URL` (`config.ts`) | — | — |

### 2.2 Реестр дел (`pages/CasesList.tsx`)

Данные: `cases.filter(c => !c.parentCaseId && !c.id.startsWith("demo-show-"))`, затем `matchesFilters(a, filters)` из `caseSearch.ts`, клиентская пагинация `Pagination` (10/20/50).

Фильтры `SearchFilters` (`caseSearch.ts: emptyFilters`): `number`, `date` (по `createdAt.slice(0,10)`), `rnn` (всегда пусто — комментарий «No RNN values»), `bin`, `name` (`object.ru` contains), `type` (`auditType`, с эквивалентностью «Фин. отчетность» через `isFinancialAudit`), `checkType`, `opf` (`object.opf`), `electronic` (`traditional|electronic`, `matchesAuditFormat`), `org` (только «КВГА МФ РК»), `author` (contains по ФИО), `coauthor` (всегда пусто — «remain Q04»), `status` (`Открыто|Закрыто`), `document` (есть документ с `kind`). Быстрые фильтры в панели: type, checkType, electronic, number, bin, org, author (select из уникальных `a.author`), status. `AdvancedSearch.tsx` — модалка с полями `number, date, rnn, bin` + добавляемые «чипы» из `extraFields`.

| Действие | Функция | Сервер |
|---|---|---|
| Изменение фильтра / «Сбросить фильтры» / страница / размер | локальный `useState` | `GET /api/evga/cases/?page=&page_size=&search=&number=&bin=&name=&created_on=&audit_type=&check_type=&format=traditional\|electronic&opf=&author=&coauthor=&status=open\|closed&has_document=<kind>&parent=null` — `django_filters.FilterSet` как `CaseRegistryFilter` в prof (`filter_search` по номеру/наименованию/БИН). Ответ `Paginated<CaseListItem>` (`count,next,previous,results`), поля строки: `id, number, object{bin,ru}, audit_type, check_type, electronic, author{id,full_name}, group[{name}], created_at, status, sample_scenario, can_edit` |
| «Расширенный поиск» → «Применить» | `AdvancedSearch.onApply` | те же query-параметры; опции `opf` в модалке берутся из `cases` → нужен `GET /api/evga/references/opf/` (старый n8n: `EVGA: Organizational Legal Forms - Get`, `evga/references/organizational-legal-forms`) |
| «Создать дело» (только `role === "auditor"`) | `EvgaModule.createCase()` → `CaseForm` | см. 2.3 |
| Клик по номеру/объекту | `onOpen` → `#/cases/:id/general` | `GET /api/evga/cases/{id}/workspace/` |
| Кнопка «Изменить дело» (disabled если `!canAuthorCase(a, account) \|\| status === "Закрыто"`) | `onEdit(a)` → `CaseForm` с `initial` | флаг `can_edit` в списке; `PATCH /api/evga/cases/{id}/` |

### 2.3 Создание/изменение дела (`pages/CaseForm.tsx`, модалка)

Состояние формы: `auditType` («Соответствие»/«Фин. отчетность»), `checkType` («Плановый»/«Внеплановый»), `electronic` (`auditFormatLabels`), `dsp`, `object` (через `ObjectLookup`), `bases` (через `BasisForm`), `checkKind` («Совместная»/«Параллельная») + `jointObject` (ещё один `ObjectLookup`), `purposeKz/purposeRu`, `group` (`WorkingGroup` → `PeoplePicker`).

| Действие | Функция | Что меняется | Сервер |
|---|---|---|---|
| Ввод 12 цифр БИН / Enter / кнопка «поиск» | `ObjectLookup.search` → `objectRegistry.find(bin)`; ошибка «Сведения по указанному БИН не найдены.»; предупреждение, если `planned && !catalogue.some(...)` | `form.object`, при смене БИН — `bases = initialBases(o)` (`plannedBasisFor(bin)` → основание «По перечню объектов…», `initiatorOptions[0]`, дата `2026-01-15`) | `GET /api/evga/audit-objects/search/?bin=&year=&lang=` — порт n8n `EVGA: Audit Object - Search by BIN` (`GET evga/audit-object/search`): возвращает объект + `in_registry` + `plan_data` (основание из `annual_plans`: `plan_title, plan_order_number, plan_order_date, audit_type, inspection_type, coverage_*, score_*, risk_level_*`). Если объекта нет в `surfk.audit_objects` — запрос в ГБД ЮЛ: n8n `Service GDBJL surfk` (`POST findJurByBin`, SOAP `getJurInfoByBin` → `fullName.ru/kz, shortName, orgForm, head.iin/fullName, address`). |
| «Добавить»/редактировать/удалить основание | `BasisForm` (`kind` из `basisOptions`, `initiator` из `initiatorOptions`, `number`, `date`, `attachments` через `FileAttachments drop`) | `form.bases` | Справочники: `GET /api/evga/references/basis-kinds/`, `GET /api/evga/references/initiators/` (n8n: `EVGA: Control Reasons Type - Get`, `EVGA: Evga Check Initiator - Get`). Вложения основания — `Attachment` с `kind=basis` (см. §4). |
| Вид проверки «Совместная» → второй БИН | `ObjectLookup` для `jointObject` | `form.jointObject` | тот же поиск объекта |
| «Выберите из справочника» (рабочая группа) | `WorkingGroup` → `PeoplePicker` (фильтр `name`, `position`; чекбоксы; «Назначить» руководителя — один `leader`) | `form.group: Person[]` | `GET /api/evga/references/employees/?search=&department_id=&position=&limit=&offset=` — порт n8n `EVGA: Employees - Get` (`surfk.employees` + `departments` + `positions`, поля `id,user_id,iin,fullname,email,department{...},position{...}`) |
| «Очистить все» | `setForm(fresh(false))` | локально | — |
| «Создать дело» / «Сохранить» | `validateCase(form, catalogue)` (12 цифр БИН; плановый объект должен быть в `catalogue`; цели на двух языках; ≥1 основание; ≥1 участник; ≤1 руководитель; при «Совместная» нужен `jointObject`) → `onSave(item)` → `EvgaModule.saveCase` (проверка `canAuthorCase`, `status !== "Закрыто"`) → `updateCase`, `history: log("Создано дело" \| "Изменены сведения дела")` | новый `AuditCase` (`id: uid()`, `number: nextCaseNumber(cases)`, `author: account.name`, `status: "Открыто"`, `quality:[false×3]`) | `POST /api/evga/cases/` body `{audit_type, check_type, check_kind, electronic, dsp, object_bin, joint_object_bin?, purpose_ru, purpose_kz, group:[{employee_id, leader}], bases:[{kind, initiator, number, date, attachment_ids[]}]}` → 201 `CaseSerializer`; номер выдаёт `issue_number(key="evga-case", context={yy})` (prof `apps/core/services/numbering.py`; текущий шаблон фронта `30101-{yy}-{seq}`; в n8n — `surfk.get_next_case_sequence(year)` в `EVGA: Create Case v4 Parallel Docs`). Изменение: `PATCH /api/evga/cases/{id}/` (те же поля; серверная проверка «автор/соавтор и дело открыто»). Валидация — та же `validateCase`, перенесённая в `services/cases.py`. |

### 2.4 Перечень объектов аудита (`pages/ObjectsRegistry.tsx`)

Данные: `catalogue` (11 объектов в `demoData.ts`), фильтры `bin`, `name`, `region`, `risk` («Высокая/Средняя/Низкая»), `value` (`score`), столбцы охвата по годам 2023–2026 — хардкод `1 000 000 / 1 000 000 / 1 500 000 / 0`.

| Действие | Функция | Сервер |
|---|---|---|
| Фильтры | локально | `GET /api/evga/audit-objects/?bin=&name=&region=&risk_level=&risk_value=&year=&page=` — порт n8n `EVGA: Audit Objects - Get` (`evga/audit-objects`, план `surfk.plan_objects` + `annual_plans`, поля `coverage_2023..2025`, `score_*`, `risk_level_gu/abp`) |
| Радиокнопка / клик по БИН (только `role === "auditor"`) | `onSelect(o)` → `EvgaModule.createCase(object)` → `CaseForm` с `preselected` | без отдельного вызова; `CaseForm` получит объект с `plan_data` |

### 2.5 Карточка дела (`pages/CaseWorkspace.tsx`)

Общее: `editable = canAuthorCase(audit, account) && audit.status !== "Закрыто"`; шапка — `AuditFormatBadge`, ссылки «Поручения» (`#/tasks?case=`) и «Исполнение пунктов» (`#/execution/:id`). Экран должен получать: `GET /api/evga/cases/{id}/workspace/` → `{case, documents: [summary + active_version{status,version,registration,delivery}], quality: [3 bool], quality_assignments, related_cases (parentCaseId = id), parent_case, deadlines (auditDeadlines), registrations, history, attachments, coauthors, notifications_unread}` — аналог `CaseWorkspaceView` prof.

#### Вкладка «Общая информация» (`general`, `group`, `regulatory`)

| Действие | Функция | Что меняется | Сервер |
|---|---|---|---|
| «Редактировать» (если `editable`) | `onEdit()` → `CaseForm initial=audit` | см. 2.3 | `PATCH /api/evga/cases/{id}/` |
| «Назначить соавтора» (только `account.id === "approver"`, дело открыто) | `caseAccess.assignCoauthor(audit, account, id)` — только `role auditor`, не автор, не дубликат; `history` + `notifications` получателю | `coauthors[]` | `POST /api/evga/cases/{id}/coauthors/` `{employee_id}`; `DELETE .../coauthors/{employee_id}/` (в UI удаления нет — добавить или нет, вопрос). n8n-аналог: `EVGA: Add Case Participants` (`POST /add-participants/:caseId`, `surfk.case_participants(case_id, employee_id, is_lead)`), `EVGA: Set Case Party Lead`, `EVGA: Delete Case Participant`. |
| Просмотр основания (ссылка «N документа»/«Просмотр») | модалка `Modal` + `FileAttachments readOnly` | — | скачивание вложений (см. §4) |
| Раскрытие «Рабочая группа» → изменение состава | `WorkingGroup.onChange` → `onChange({...audit, group, history: log("Изменена рабочая группа")})` | `group` | `PUT /api/evga/cases/{id}/group/` `{members:[{employee_id, leader}]}` (или часть `PATCH`) |
| Раскрытие «Сроки и регистрация» (`RegulatoryPanel`) — таблица `auditDeadlines(audit)` (`deadlines.ts`, 15 правил со ссылками на НПА № 392/413), сведения ЕРСОП по документам с `registration` | чтение | — | `GET /api/evga/cases/{id}/deadlines/` (сервер считает `auditDeadlines` по тем же правилам; `addWorkingDays` с `calendar`) |
| «Сохранить календарь» (holidays/workingDates/confirmedYears, валидация формата дат, только автор) | `onChange({...audit, calendar, history: log("Обновлён рабочий календарь дела")})` | `calendar` | `PUT /api/evga/cases/{id}/calendar/` `{holidays[], working_dates[], confirmed_years[]}`. Лучше — общий производственный календарь на сервере (справочник), а `calendar` дела — только переопределения. |

#### Вкладка «Документы» → раздел «Документы по этапам» (`documents`)

Таблица по `stageNames` (3 этапа; для встречного дела — один «Встречная проверка») из `kinds` (`docKinds`/`counterDocKinds` без `quality*`), статус `activeVersion(doc).status` или «Не активный», кнопки создания заблокированы по `creationBlock(audit, kind)` (`workflow.ts`, зависимости `dependencies`, регистрация в ЕРСОП, КК предыдущего этапа, приостановление) и `creationAccessBlock(audit, kind, actor)` (`documentFactory.ts`: закрыто дело, автор/соавтор, роль `quality` для `quality*`, `object` для `objections/response`, назначенный `appeal-expert` для `objection-result`). `repeatableKinds` (18 видов) можно создавать многократно.

| Действие | Функция | Что меняется | Сервер |
|---|---|---|---|
| «Создать ⌄» → вид документа (и клик по «не созданному» в таблице) | `openDocument(kind)` → `createDocument(audit, kind, account)` (номер `${audit.number}/${documentSequence+1:02}`, `values: initialValues(audit, kind)` — предзаполнение из ИРПИ/программы/поручения/реестра, `ownerRole/ownerId`, `sourceVersions` для `quality*`, `additional` (со `contentSnapshot`), `objection-result`, `response`; `group` = копия `audit.group` или эксперт КК) → `fillPreparedDocument` (демо) → `saveDocument(audit, d, account)` + `history: log("Создан документ: …")` → навигация в `/edit` если `ownerRole === account.role` | `documents[]`, `documentSequence`, `history`, `notifications` | `POST /api/evga/cases/{id}/documents/` `{kind}` → 201 `DocumentSerializer` (сервер выполняет `creationAccessBlock`, `creationBlock`, `initialValues`, нумерацию через `issue_number(key="evga-document", scope=case_id)`). Ответ должен содержать `can_edit` чтобы фронт решил, открывать ли `/edit`. Доступность видов для меню: `GET /api/evga/cases/{id}/available-documents/` → `[{kind, name, code, stage, blocked_reason}]` (n8n: `Get Available Document Types` `GET evga/available-document-types/:case_id`). |
| Иконка «Удалить проект» (одна версия, `Проект`, владелец, дело открыто) → подтверждение | `deleteDocument(audit, id, account)` (запрет, если на документ ссылаются `sourceVersions`/`values` или создан зависимый по `dependencies`) | `documents[]`, `history` | `DELETE /api/evga/documents/{id}/` (soft-delete как в n8n `EVGA Docs: CRUD` → `Soft Delete`, `is_deleted`) |
| Клик по документу / иконка «Открыть» | `onDocument(id)` | — | `GET /api/evga/documents/{id}/` |
| Раздел «Рабочие документы» (`working`): «Создать доступные рабочие формы» | цикл по `workingDocKinds` с `paperApplies` + `createDocument` + `saveDocument`; toast «Создано рабочих форм: N» | `documents[]` | `POST /api/evga/cases/{id}/documents/bulk-working-papers/` → `{created: n}` |
| «Создать»/«Открыть» рабочей формы | как выше | | как `POST .../documents/` |

#### Раздел «Встречные проверки» (`counter`, `components/CounterChecks.tsx`)

| Действие | Функция | Что меняется | Сервер |
|---|---|---|---|
| «Создать дело встречной проверки» (auditor, дело открыто, `registered(audit)` — учётная карточка зарегистрирована) → модалка (тип ЮЛ/ФЛ; `ObjectLookup` или `iin/name/birth/entrepreneur`; `question`; `WorkingGroup`) → «Создать дело» | локальная валидация → новый `AuditCase` с `parentCaseId`, `number: ${audit.number}/ВП-${n}`, `checkType: "Встречная проверка"`, `checkKind: "Встречная"`, `schedule` из ИРПИ (`latestValues(audit,"irpi")`), `history` → `onSave(next)`; переход `onOpen(next)` | новое дело | `POST /api/evga/cases/{id}/counter-cases/` `{person_type, object_bin? \| iin,name,birth_date,entrepreneur_name, question, group[]}` → 201. n8n: `EVGA Sub Cases` (`POST evga/sub-cases`, action create/list, `surfk.cases.parent_id`, `sub_case_type`, `sub_case_data`). |
| Список дочерних дел / ссылка на основное | `cases.filter(a => a.parentCaseId === audit.id)` | — | входит в `workspace.related_cases` или `GET /api/evga/cases/?parent={id}` |

#### Раздел «Возражения» (`appeal`, `components/AppealPanel.tsx`, логика `appeals.ts`)

Источник: `getAppeal(audit)` — активный документ `objections` (создаёт объект аудита) + `audit.appeal`. Все изменения идут через `change()` → `history` + `notifications` (получатели: `area appeal`, автор/соавтор, `approver`, `object`).

| Действие | Функция | Сервер |
|---|---|---|
| «Создать возражения» (role object) / «Открыть возражения» | `onCreate("objections")` → создание документа | `POST /cases/{id}/documents/ {kind:"objections"}` (кабинет объекта) |
| «Назначить» исполнителя (role `appeal-head`, список `accounts.filter(role==="appeal-expert")`) | `assignAppeal(audit, account, expertId)` (запрет, если отказ в рассмотрении; если `objection-result` возвращён — `reassignReturnedDocument` создаёт новую версию для нового владельца) | `POST /api/evga/cases/{id}/appeal/assign/` `{expert_id}`. n8n: `Appeals - Assign Expert` (`POST assign-appeal-expert/cases/:caseId/assign-appeal-expert`), `Appeals - Heads list`, `Appeals - Cases list`, `get-assigned-expert`. |
| «Зафиксировать решение о рассмотрении» (`commission-chair`; `decision` «Принято к рассмотрению»/«Отказ в рассмотрении», `reason`, файлы обязательны) | `recordAdmission(...)` | `POST /api/evga/cases/{id}/appeal/admission/` multipart `{decision, reason, files[]}` |
| «Подтвердить направление решения» (`appeal-head` или исполнитель; файлы обязательны) | `notifyAdmission(audit, account, files)` → `admission.notifiedAt`, файлы добавляются | `POST /api/evga/cases/{id}/appeal/admission/notify/` multipart |
| «Создать результаты рассмотрения» (назначенный эксперт) / «Открыть результаты» | `onCreate("objection-result")` | `POST .../documents/ {kind:"objection-result"}` |
| «Перейти к повторному КК» | навигация | — |
| «Сохранить обоснования» / «Направить руководителю на подпись» (автор/соавтор; строки `rows[{violationId,textRu,textKz,files}]` по пунктам возражений) | `saveAppealArguments(audit, account, rows, submit)` — при submit: по каждому пункту оба языка + файлы | `PUT /api/evga/cases/{id}/appeal/arguments/` `{rows:[{violation_id,text_ru,text_kz,attachment_ids[]}], submit:bool}` |
| «Подписать обоснования» / «Вернуть обоснования на доработку» (`account.id === "approver"`) | `decideArguments(audit, account, approve, comment)` | `POST /api/evga/cases/{id}/appeal/arguments/decide/` `{approve, comment}` |
| Информация: «Подача возражений до» | `appealFilingDue(audit)` = `addWorkingDays(report.delivery.sentAt, 10)` | входит в `deadlines` |

#### Раздел «Третьи лица» (`third-parties`, `ThirdPartiesPanel.tsx`, логика `thirdParties.ts`)

Только `role === "object"` и после `report.delivery.acknowledgedAt`. Пункты нарушений — `rowValues(latestValues(audit,"violations").violations)`.

| Действие | Функция | Сервер |
|---|---|---|
| «Зарегистрировать уведомление» (`name`, `identification` 12 цифр, `violationIds[]`, `noticeAt` (не в будущем, не раньше получения отчёта), файлы) | `addThirdParty(audit, account, notice)` | `POST /api/evga/cases/{id}/third-parties/` multipart |
| «Подтвердить отсутствие третьих лиц» (`reason`) | `recordNoThirdParties` → `thirdPartiesReviewed{none:true}` | `POST /api/evga/cases/{id}/third-parties/none/` `{reason}` |
| По каждому лицу: «Зарегистрировать получение уведомления» / «Зарегистрировать позицию третьего лица» / «Подтвердить передачу позиции в орган аудита» (`date`, `text`, файлы) | `recordThirdPartyEvent(audit, account, id, "receipt"\|"response"\|"forward", date, text, files)` с `assertPastDate` | `POST /api/evga/third-parties/{id}/events/` multipart `{event, date, text, files[]}` |

#### Раздел «Изменения поручений» (`amendments`, `AmendmentsPanel.tsx`, логика `amendments.ts`)

| Действие | Функция | Сервер |
|---|---|---|
| «Применить изменения поручения» (по документу `additional`/`counter-additional`; `amendmentBlock` — активен, зарегистрирован, тип «О внесении дополнений в приказ»/«Продление проверки», не применён, нет документов заключительного этапа/возражений, `sourceVersions.contentSnapshot` совпадает с текущими) | `applyAmendment(audit, doc, account)` — создаёт новые версии `Проект` всех `amendmentTargets` (11 видов), переносит поля (`general`, `questions`, `objects`, `risks`, `duration`, `period`, `coverage`), обновляет `purposeRu/Kz`, `group`, `schedule`, сбрасывает `quality = [false×3]`, пишет `amendments[]` | `POST /api/evga/documents/{id}/apply-amendment/` → возвращает `workspace` дела (меняются много документов) |

#### Вкладка «Вложения» (`attachments`)

| Действие | Функция | Сервер |
|---|---|---|
| Загрузка/удаление файлов дела (`FileAttachments`, если `editable`) | `onChange({...audit, attachments, history: log("Изменены вложения")})` | `POST /api/evga/cases/{id}/attachments/` multipart `{file, kind}`; `DELETE /api/evga/cases/{id}/attachments/{attachment_id}/`; `GET .../attachments/{attachment_id}/` (download) |

#### Вкладка «История» (`history`) — чтение `audit.history` (действие, дата, инициатор, комментарий). Сервер: `GET /api/evga/cases/{id}/history/?page=` (в prof — `AuditEvent` append-only, `apps/core/models.py`; n8n — `EVGA: Document History Record`, `Log Activity`, `EVGA Case Workflow Log`).

#### Вкладка «Ход исполнения» (`progress`, `ExecutionProgress.tsx`, логика `executionProgress.ts`)

Чтение: `executionStages(audit)` (3 этапа × шаги «Подготовка документов этапа», «Контроль качества», «Согласование и утверждение», + `registration`, `registry-delivery`, `delivery`, `appeal`, `notification`, `response`, `completion`), `nextExecutionStep`. Кнопка «Перейти к действию →» / «Открыть» вызывает `openDocument(kind)` (создание!) или навигацию в раздел. Сервер: `GET /api/evga/cases/{id}/progress/` (вычисление тех же правил на сервере — они опираются на `creationBlock`, `mainDeliveryBlock`, `completionBlock`, `qualityPassed`).

### 2.6 Рабочая область документа (`pages/DocumentWorkspace.tsx`)

Загрузка: документ с версиями; выбранная версия `versionNumber` (из URL `/versions/:n` либо `activeVersion`), `draft = structuredClone(source)`. Права: `allowedOwner` (владелец версии `ownerId`, назначенный эксперт КК для `quality*`, автор/соавтор для auditor), `readOnly = !allowedOwner || !editing || Закрыто || !canEdit(source, role) || не последняя версия`. `view` = `documentPresentation()` (`form|print|sources`; по умолчанию `print` для согласующих/подписантов/объекта).

Экран должен получать: `GET /api/evga/documents/{id}/` → `{id, case_id, kind, stage, number, author, created_at, versions:[{version,status,created_at}], current_version: {…full DocumentVersion…}, permissions:{can_edit, can_submit, can_decide, decision_label, can_send_quality, can_delete, available_actions[]}}`; `GET /api/evga/documents/{id}/versions/{n}/` → полная версия (values, attachments, group, approval_routes, history, registration, delivery, information_request, preparation, main, main_quality, source_versions). Вычисление `permissions/available_actions` на сервере снимает с фронта дублирование условий вида `canDecideDocument`, `canSubmit`, `requiresQuality`, `directActivation`, `mainSubmissionBlock`.

#### Панель инструментов и решения

| Действие (условие показа) | Функция | Что меняется | Сервер |
|---|---|---|---|
| Вкладки «Электронная форма»/«Печатная форма»/«Документы на контроле» (`sources` только для `quality*`) | `selectView` → `?view=` | — | — |
| Выбор версии (select / боковая панель «Версии документа») | `onSelectVersion` → `/versions/:n` | — | `GET .../versions/{n}/` |
| «Согласовать/Утвердить/Подписать» (`eligible = canDecideDocument(doc, account, audit)`, `readOnly`, последняя версия) | `validateDocument`/«Завершите открытые встречные проверки» для `completion` → `approveDocument(workflowDoc, account, versionNumber, audit)` → `decideApprovalRoute(..., action approve\|sign)`; статусы `На согласовании → Согласован (preparation/main: agreedAt) / На утверждении → Активный`; `signatures`, `history` | версия | `POST /api/evga/documents/{id}/approve/` `{expected_version}` |
| «Вернуть на доработку» → модалка «Замечание» (обязательно) | `returnDocument(workflowDoc, account, comment, versionNumber, audit)` → `Возвращен на доработку`, `qualityDecision = undefined` | версия | `POST .../return/` `{comment, expected_version}` |
| «Отклонить» → модалка «Причина отклонения» | `rejectDocument(...)` → `Отклонен` | версия | `POST .../reject/` `{comment, expected_version}` |
| «Отозвать с согласования» (`objection-result`, владелец `appeal-expert`, `На согласовании`, `reviewerIndex 0`, нет подписей) | `recallDocument(doc, account)` → маршрут `superseded`, статус `Проект` | версия | `POST .../recall/` |
| «Скачать PDF» (`readOnly && view === "print"`) | `PdfDownloadButton` → `downloadPrintPdf` (pdfmake, клиент) | — | см. §7 |
| «Печать» | `selectView("print")` + `window.print()` | — | — |
| «Очистить все» (редактирование) | `setDraft({...draft, values:{}, attachments:[]})` | локально | — |
| «Сохранить» (две кнопки: в тулбаре и внизу формы) | `persist()`: проверка `allowedOwner`, `canEdit`, `assertAttachmentRetention(v, draft)` (запрет удаления вложений вне `Проект`), обновление `values.printContext = printContext(audit)` (снимок дела для печати; для `violations` сохраняет `sources.program/instruction`), `history: log("Сохранены изменения")` → `onSave(next)` → `saveDocument` | версия `values`, `attachments`, `group`, `history`; в `saveDocument` — история дела, уведомления | `PATCH /api/evga/documents/{id}/versions/{n}/` `{values, group, attachment_ids, expected_updated_at}` (prof: `ControlDocumentViewSet.partial_update` разрешён только в `DRAFT`). `printContext` формировать на сервере при сохранении/подписании. |
| «Редактировать» (`allowedOwner && canEdit && открыто`, кроме `quality2`/main в «Возвращен на доработку») | `beginEdit` → `onEdit(true)` (`/edit?view=form`) | — | — |
| «Создать редакцию для доработки» (статус `Возвращен на доработку` и есть `currentApprovalRoute`) | `beginEdit` → `reviseMainDocument` (main) или `createReturnedRevision` → `createDecisionRevision` (новая версия `Проект`, старый маршрут `superseded`) | `versions[]` | `POST .../revisions/` `{reason:"returned"}` → новая версия |
| «Направить на контроль качества» (`requiresQuality(kind)` — 9 видов, не preparation/main) | `validForReview()` → `sendDocumentToQuality(doc, account)` → `Направлен на согласование КК` | версия | `POST .../send-to-quality/` |
| «Подписать» (`directActivation(kind)`: `claim-decisions, reply-law, obstruction, counter-obstruction, objections, weekly, account, counter-account, notification, counter-notification` + рабочие формы) | `activateDocument(doc, account)` → `Активный` + `signatures` | версия | `POST .../sign/` (в prof — ЭЦП не подключена, здесь тоже «имитация»; точка расширения для НУЦ/ЭЦП) |
| «Отправить на согласование» (`canSubmit`) → `ReviewRouteDialog` (`ApprovalRouteEditor`: этапы, режим sequential/parallel, согласующие из `routeReviewer`, утверждающий из `routeApprover`, комментарий) → «Отправить» | `submitDocument(doc, account, reviewerIds, signerId, comment, mode, stages, audit)` → `createApprovalRoute(...)`, `status "На согласовании"`, `sourceVersions` для preparation/main | версия (`approvalRoutes[]`, `reviewers`, `approver`) | `POST .../submit/` `{stages:[{id, mode, reviewer_ids[]}], signer_id?, comment, expected_version}`. Список кандидатов: `GET /api/evga/documents/{id}/route-candidates/` → `{reviewers:[], signers:[]}` (сервер применяет `routeReviewer/routeApprover`). |
| `quality2`: «Подписать заключение» (эксперт, `Проект`, заполнены `conclusion.decision/textRu`) | `signMainQuality` → `mainQuality.expertSignedAt` | версия | `POST .../quality/sign/` |
| `quality2`: «Направить руководителю КК» | `submitMainQualityToHead` → маршрут только с `signer = quality-head`, `На утверждении` | версия | `POST .../quality/submit-to-head/` |
| `quality2`: «Новая редакция заключения» | `reviseMainQuality` (новые `sourceVersions` = main + активный `objection-result`) | `versions[]` | `POST .../revisions/ {reason:"quality"}` |
| «Создать новую редакцию» (`Отклонен`, владелец) | `createRejectedRevision` | `versions[]` | `POST .../revisions/ {reason:"rejected"}` |
| «Уточнить ответ новой редакцией» (`response`, `Активный`) | `reviseExecutionResponse` (`createResponseRevision` + пересчёт `measures/recommendations` из `initialValues`) | `versions[]` | `POST .../revisions/ {reason:"response"}` |
| «Создать v{n+1}» (есть `qualityConclusion`, статус `Активный`/`Направлен на согласование КК`, auditor) | `createNextVersion` | `versions[]` | `POST .../revisions/ {reason:"quality-remarks"}` |

Рекомендация: один endpoint `POST /api/evga/documents/{id}/revisions/` с `reason ∈ {returned, rejected, quality-remarks, quality, main, preparation, response}` — на сервере диспетчер, повторяющий `createReturnedRevision/createRejectedRevision/createNextVersion/reviseMainDocument/revisePreparationDocument/reviseMainQuality/createResponseRevision`.

#### Панель «Маршрут документа» для основного этапа (`MainActions.tsx`, `mainWorkflow.ts`; `report`, `violations`, `evidence`)

| Действие | Функция | Сервер |
|---|---|---|
| «Направить отчёт на подписание рабочей группе» (`report`, `Проект`, автор) | `onValidate()` → `requestReportGroupSignatures` → `main.groupRequestedAt`, `На подписании рабочей группой`, `sourceVersions = mainReferences` | `POST .../group-signatures/request/` |
| «Подписать отчёт участником РГ» (участник `group`, роли auditor/invited-specialist) | `signReportGroup(audit, doc, account, viewVersion)`; когда все подписали → статус `Проект` (далее обычный `submit`) | `POST .../group-signatures/sign/` `{expected_version}` |
| «Направить реестр на подтверждение» / «Повторно направить…» (`violations`, `Согласован`, select `reestr-confirmer`) | `sendRegistryToConfirmer(audit, doc, account, confirmerId)` → `main.confirmation{pending, sourceVersions}`, `На подтверждении реестра` | `POST .../registry-confirmation/request/` `{confirmer_id}`. n8n: `EVGA Docs: KVGA/Reestr` (actions send_to_kvga/kvga_confirm/kvga_return/kvga_reject; статусы `pending_kvga`, `kvga_confirmed`, `revision`, `rejected`). |
| «Подтвердить реестр» / «Вернуть на доработку» (назначенный `reestr-confirmer`, комментарий для возврата) | `decideRegistryConfirmation(..., "confirm"\|"return", comment, viewVersion)` → `Согласован` / `Возвращен на доработку` | `POST .../registry-confirmation/decide/` `{decision, comment, expected_version}` |
| «Направить комплект на КК2» (после `confirmed`) | `requestMainQuality` → `main.qualityRequestedAt` | `POST .../request-quality/` |
| «Направить на окончательное утверждение» (`violations`/`evidence`, `Согласован`, `mainApprovalBlock` пуст: КК2 «Без замечаний» по актуальным версиям) | `requestMainApproval` → `На утверждении` | `POST .../request-approval/` |
| «Создать новую редакцию для согласования» | `reviseMainDocument` | `POST .../revisions/ {reason:"main"}` |

#### Панель «Маршрут документа» для подготовительного этапа (`PreparationActions.tsx`, `preparationWorkflow.ts`; `irpi, program, plan, assignment, instruction, counter-instruction`)

| Действие | Функция | Сервер |
|---|---|---|
| «Направить на подтверждение КВГА» (`instruction`/`counter-instruction`, `Согласован`, select `kvga`) | `sendInstructionToKvga(..., confirmerId)` → `preparation.kvga{pending}`, `На подтверждении КВГА` | `POST .../kvga-confirmation/request/` `{confirmer_id}` |
| «Подтвердить поручение» / «Вернуть на доработку» (назначенный `kvga`) | `decideInstructionKvga(..., "confirm"\|"return", comment, viewVersion)` (для `counter-instruction` возврат тоже даёт `Согласован` — «M43 returns to the auditor's sending step») | `POST .../kvga-confirmation/decide/` |
| «Направить дело на КК» (`instruction`, KVGA confirmed) | `requestPreparationQuality` → `preparation.qualityRequestedAt` | `POST .../request-quality/` |
| «Направить на подписание рабочей группе» (`assignment`) / «Направить на окончательное утверждение» (остальные, `Согласован`, `preparationApprovalBlock` пуст — КК1 «Без замечаний», предыдущие активны) | `sendPreparationForApproval` → `На подписании рабочей группой` (+`preparation.groupSignatures=[]`) / `На утверждении` | `POST .../request-approval/` |
| «Подписать задание участником РГ» / «Утвердить задание руководителем РГ» (`assignment`) | `signAssignmentGroup` / `approveAssignmentGroup` → `Активный` | `POST .../group-signatures/sign/`, `POST .../group-signatures/approve/` |
| «Создать новую редакцию для согласования» | `revisePreparationDocument` (`supersedeApprovalRoute`) | `POST .../revisions/ {reason:"preparation"}` |

#### Панель «Учёт регистрации в ЕРСОП» и «Ознакомление и ответ объекта аудита» (`DocumentActions.tsx`, `workflow.ts`)

Регистрируемые виды (`isRegistration`): `account, counter-account, notification, counter-notification, additional, counter-additional`. `deliverable(kind)` — 14 видов.

| Действие | Функция | Что меняется | Сервер |
|---|---|---|---|
| «Провести повторный контроль качества» (`quality*`, `Активный`, назначенный эксперт) | `renewQuality(audit, doc, account)` → новая версия `Проект` с актуальными `sourceVersions` | `versions[]` | `POST .../revisions/ {reason:"quality-renew"}` |
| «Подготовить к регистрации» (auditor, `Активный`) | `performRegistration(doc, account, "send")` → `registration{status:"Отправлена"}` | версия | `POST .../ersop/send/` — сервер вызывает интеграцию (стаб `apps/ersop/services/stub_exchange.py` в prof; n8n `EVGA ERSOP Workflow` action `send_to_ersop` → `webhook/ersop/send-document`, статус `sent_to_ersop`) |
| «Учесть регистрацию» → модалка «Номер регистрации в ЕРСОП» (обязателен) | `performRegistration(doc, account, "accept", "", number)` → `Зарегистрирована`, `number` (дефолт `УЧ-${doc.number.replaceAll("/","-")}`), `date` | версия; в `saveDocument` побочные эффекты: для `additional` — `executionState` (Приостановлено/Проводится/Отменено→`Закрыто`), новое основание в `bases`, продление `schedule.end`; для `counter-notification` — дело `Закрыто` | **Убрать ручной ввод**: `POST .../ersop/check-status/` (n8n `check_status` → `webhook/getErsop`; `registered_ersop`/`returned`). Для демо — стаб, возвращающий номер `issue_number(key="ersop-registration")`. |
| «Учесть возврат» → модалка «Причина возврата» | `performRegistration(..., "return", reason)` → `Возвращена`, статус версии `Возвращен на доработку` | версия | тот же `check-status` (ответ ЕРСОП «возврат») или админ-действие `POST .../ersop/return/` для стенда |
| «Направить объекту аудита» (автор; для `objection-result` — владелец-эксперт; `mainDeliveryBlock` для report/violations; `instruction` только после `registered(audit)`; `additional` только после регистрации) | `deliverDocument(doc, account, "send", "", [], audit)` → `delivery{sentAt}`; `report` из `Согласован` → `Активный` | версия | `POST .../deliver/` — создаёт задачу в кабинете объекта (prof `apps/cabinet`) |
| Роль object: «Ознакомлен» | `deliverDocument(..., "acknowledge")` → `delivery.acknowledgedAt` | версия | `POST /api/evga/cabinet/documents/{id}/acknowledge/` (prof: `CabinetAcknowledgeView`, `record_acknowledgement`, каналы `portal`/`manual`) |
| Роль object: «Предоставить ответ» (`request, counter-request, prescription, conclusion`) → модалка (текст, файлы) | `deliverDocument(..., "respond", text, files)` (для `request` — делегирует в `transitionInformationRequest("provide")`) | версия | `POST /api/evga/cabinet/documents/{id}/respond/` multipart |
| Роль object: «Подписать без возражений» / «Подписать с возражениями» (`report, violations, counter-act`; для `report` требуется `acknowledgedAt`; обоснование обязательно) | `deliverDocument(..., "sign"\|"object", grounds, files)` → `delivery.decision` («Подписан»/«Подписан с возражениями»), `decidedAt/decidedBy/grounds/decisionAttachments` | версия | `POST /api/evga/cabinet/documents/{id}/decision/` `{decision, grounds, files[]}` |
| Автор: «Зафиксировать отказ от подписания» (обоснование + файлы обязательны) | `deliverDocument(..., "refuse", ...)` → «Отказ от подписания» | версия | `POST .../deliver/refuse/` multipart |

#### Панель «Предоставление и проверка сведений» (`InformationRequestPanel.tsx`, `informationRequests.ts`; `request`, `counter-request`)

Состояние `informationRequestCycle(doc, now)` (`sent → awaiting → received/review → accepted/refused`, `overdue` по `deadline` из `values.general.deadline`; для `counter-request` просрочка = `refused`). Доступные действия — `informationRequestActions(audit, doc, actor)`.

| Действие (роль) | Функция | Сервер |
|---|---|---|
| «Направить требование объекту» (автор) | `transitionInformationRequest(..., "send")` — нужен `deadline` в будущем; `rounds.push`, `delivery{sentAt}` | `POST .../information-request/send/` |
| «Ознакомиться с требованием» (object) | `"acknowledge"` | `POST /cabinet/documents/{id}/information-request/acknowledge/` |
| «Предоставить сведения» / «Отказать в предоставлении сведений» (object; текст/файлы) | `"provide"` / `"refuse"` | `POST /cabinet/.../information-request/respond/` `{refused, text, files[]}` |
| «Взять сведения на проверку» / «Принять сведения» / «Отклонить сведения и завершить требование» / «Вернуть и повторно запросить сведения» (новый `deadline`) / «Зафиксировать отказ после истечения срока» (автор) | `"review"`/`"accept"`/`"reject"`/`"resend"`/`"mark-refused"` | `POST .../information-request/{action}/` `{comment, deadline?}`. n8n: `EVGA Info Request API (deprecated)` (`POST evga/info-request`) — старое API, логику брать из фронта. |
| Таймер просрочки | вычисляется при рендере по `now` | серверный периодический пересчёт (Celery beat / management command) или вычисление в сериализаторе |

#### Форма документа (`DocumentForm.tsx` / `ViolationRegistryForm.tsx` / `IrpiForm.tsx` / `WorkingPaperForm.tsx` / `AuditCalculations.tsx`)

Все изменения локальны в `draft` до нажатия «Сохранить» — сервер получает итоговый `values` целиком. Особенности:
- `Collection` (секции `collection: true`): модалка «Добавить/Редактировать запись», удаление с подтверждением, `section.attachments` → файлы строки `row.files: Upload[]`.
- `FormFields` тип `object`: ввод БИН с автоподстановкой из `catalogue` (`nameRu/nameKz/recipientNameRu/…/opf/addressRu`) → нужен `audit-objects/search`. Тип `person`: select из `[...audit.group, ...people]` → справочник сотрудников. Тип `document`: select связанных документов дела.
- `formLinks.ts`/`selectFormLink`: связи `violationId/riskId/questionId/resultId/field` — берутся из значений других документов дела (`latestValues(audit, kind)`), значит серверный `DocumentSerializer` должен отдавать (или фронт запрашивать) `latest values` документов `violations`, `instruction`, `program` того же дела: `GET /api/evga/cases/{id}/form-links/`.
- `IrpiForm`: строки `materials/risks/controls/materiality/questions` (`IrpiRowForm` с файлами), «Загрузить предыдущие аудиты» из `previousAuditRows(audit, previousCases)` (по `object.bin` среди всех дел) → `GET /api/evga/audit-objects/{bin}/previous-audits/` (n8n: `get_previous_audit_list_by_bin`, `GET listPreAudits?caseId=`); `ObjectLookup` для `jointObject`; `counterBins`.
- `ViolationRegistryForm`: вкладки «Объекты риска и вопросы» / «Результаты проверки»; функции `saveRiskSelection`, `removeRegistryRisk`, `assignRegistryResult`, `finalizeRegistry`, `repairRegistry` — все чистые над `values`, остаются на клиенте; серверная валидация — `registryValidation`.
- `AuditCalculations`: «Рассчитать» — чистые функции `auditCalculations.ts`; `validateDocument` требует наличие `calculationResult_*` при заполненных `calculationInputs_*` — повторить на сервере.
- `validateDocument(audit, doc, v)` (`forms/validation.ts`) вызывается перед `submit/approve/send-to-quality/sign` — обязательно повторить на сервере (`services/validation.py`), схемы `documentForms.ts` можно перенести в JSON-справочник `DocumentType.form_schema` (в n8n аналог — `surfk.evga_document_mappings.form_schema`).

### 2.7 Контроль качества (`QualityRegistry.tsx`, `QualityAssignmentPanel.tsx`, `QualityDocumentWorkspace.tsx`)

| Действие | Функция | Сервер |
|---|---|---|
| Список объектов КК (поиск по `number/object.ru/bin`, без встречных и `demo-show-`) со статусами 3 этапов `stageState` («Не начат»/статус версии/«Повторный КК» если `sourceVersions` устарели) и экспертами `qualityExpert(audit, stage)` | чтение | `GET /api/evga/quality/?search=&page=` → строки `{case, stages:[{stage, status_label, expert, outdated}]}` |
| «Открыть объект →» | навигация | `GET /api/evga/quality/{case_id}/` → `{case, stages:[{kind, doc?, label, detail, sources[], block}]}` (использует `creationBlock`, `creationAccessBlock`, `documentNextAction`) |
| «Назначить эксперта» / «Заменить эксперта» (`quality-head`; select из `role === "quality"`; при замене — причина) | `assignQualityExpert(audit, stage, account, expertId, reason)` — пишет `qualityAssignments[stage]`, историю, уведомления; для подписанного `quality2` создаёт новую версию, отменяя маршрут | `POST /api/evga/cases/{id}/quality-assignments/` `{stage, expert_id, reason}`. n8n: `assign-expert-to-case`, `get-assigned-expert`. |
| «Создать заключение» | `createDocument(item, "quality{n}", account)` + `saveDocument` → `/quality/:id/documents/:doc/edit` | `POST /cases/{id}/documents/ {kind:"quality1|2|3"}` |
| «Открыть заключение»; вкладки «Форма заключения»/«Документы на контроле» (таблица `sourceVersions` с «есть новая версия») | `QualityDocumentWorkspace` подменяет `values` на `qualityFormValues(audit, version)` (`qualityConclusion.ts`) | входит в `GET /documents/{id}/` (`source_versions` с текущими статусами источников) |
| Побочный эффект активации заключения | в `saveDocument`: при `Активный` записывает `qualityDecision/qualityConclusion` в версии-источники, пересчитывает `audit.quality` | серверная транзакция в `services/quality.py` |

### 2.8 Поручения (`pages/ApprovalTasks.tsx` + `shared/workflow/ApprovalInbox.tsx`)

Данные: (1) `processTasks` — вычисляются по всем открытым делам: `На подтверждении КВГА` для назначенного `kvga`, `На подтверждении реестра` для `reestr-confirmer`, `На подписании рабочей группой` для участников группы без подписи, объектные решения (`report/violations/counter-act` активны, есть `delivery` без `decision`) для роли object; (2) `caseApprovalRoutes(cases)` → `ApprovalRoute[]` с обогащением из `accounts` и пометкой `superseded` для не-последних версий; `ApprovalInbox` показывает «Входящие» (`getApprovalTasks(routes)` где `assignee.id === userId && status === "pending"`) и «Отправленные» (`route.initiator.id === userId`), поиск и фильтр состояния — клиентские.

| Действие | Сервер |
|---|---|
| Открыть страницу / переключить вкладку / поиск / фильтр | `GET /api/evga/tasks/?tab=incoming\|sent&case=&search=&status=&page=` → `{process_tasks:[{case, document, action}], tasks: Paginated<ApprovalTask>, routes: Paginated<ApprovalRoute>}`. Хранить `ApprovalRoute` как таблицы `ApprovalRoute/ApprovalStage/ApprovalParticipant/ApprovalEvent` (модель уже описана в `approvalRoute.ts`; поле `execution: "local-demo"` → `"server"`). |
| «Открыть документ» | навигация `/cases/:id/documents/:doc/versions/:n` | — |

### 2.9 Исполнение (`pages/ExecutionRegistryPage.tsx` + `shared/execution/ExecutionRegistry.tsx`)

Данные: `executionItemsForCases(cases)` (`executionItems.ts`) — пункты `prescription.financial/procedural` и `conclusion.recommendations` из последних активных версий, сопоставленные со строками `response.measures/recommendations`; `confirmedStatus` (`open/partial/completed/not_remediable/in_review`), `evidence` (файлы строк ответа, `href = file.data`), `extensions` (продление из `general.extension/deadline/extensionReason` утверждённого ответа), `history`.

| Действие | Функция | Сервер |
|---|---|---|
| Открыть реестр (все дела / одно) | чтение | `GET /api/evga/execution/items/?case=&module=&status=&responsible=&document_kind=&deadline=&search=&page=` → `Paginated<ExecutionItem>` (prof: `PrescriptionItemViewSet`, `PrescriptionItemFilter`) |
| «Подготовить ответ о мерах» (`creationAccessBlock/creationBlock("response")`) | `createDocument(audit,"response")` + `saveDocument` → `/edit` | `POST /cases/{id}/documents/ {kind:"response"}` |
| «Ответ о принятых мерах» / «Документы дела» / «Открыть пункт» | навигация по `itemHref` | — |
| «Предупреждать за, дней» (`onDeadlinePolicyChange`) | `localStorage["saq.evga.execution-policy.v1"]` | оставить в localStorage (персональная настройка) или `PATCH /api/auth/me/preferences/` |
| Сообщение `completionBlock(audit)` | вычисление | входит в ответ `GET /cases/{id}/progress/` |

### 2.10 Уведомления (`components/Notifications.tsx`)

Данные: `cases.flatMap(a.notifications)` где `recipients.includes(account.id)`, сортировка по `at`. Создаются в `saveDocument` (по статусу — согласующим `pending`, подтверждающим, группе, утверждающему, экспертам КК, объекту при `delivery`, владельцу), `assignCoauthor`, `assignQualityExpert`, `appeals.change`.

| Действие | Функция | Сервер |
|---|---|---|
| «Открыть» | `readBy` += `account.id` → `onChange(audit)`; навигация к документу/делу | `POST /api/evga/notifications/{id}/read/`; список `GET /api/evga/notifications/?page=&unread=`; n8n: `create notification by recipients` (`portal.notifications(user_id,title,message,event_type,notification_type,meta_data,status,channel)`), `update_notification_status`, `notifications_mark-all-read`, WebSocket `notification service`. Рекомендуется таблица `Notification(recipient, case, document, text, read_at)` + `POST .../mark-all-read/`. |

---

## 3. Предлагаемый API в стиле prof

### 3.1 Структура backend-приложений (по образцу `backend/apps/*` prof)

```
backend/apps/evga_cases/       models: AuditCase, CaseParticipant(group, leader), CaseCoauthor, CaseBasis,
                                       CaseCalendar, CounterCaseDetails; services: cases.py (validateCase,
                                       nextCaseNumber→issue_number), case_status.py (qualityPassed, completionBlock)
backend/apps/evga_documents/   models: DocumentType(kind, name, stage, code, repeatable, requires_quality,
                                       direct_activation, deliverable, registrable, form_schema JSON),
                                       AuditDocument, DocumentVersion(values JSONB, status, owner, ...),
                                       DocumentSourceVersion, DocumentHistory (AuditEvent); services:
                                       factory.py (createDocument/initialValues), state_machine.py,
                                       preparation.py, main.py, quality.py, revisions.py, validation.py
backend/apps/evga_approval/    models: ApprovalRoute, ApprovalStage, ApprovalParticipant, ApprovalEvent;
                                       services: route.py (порт approvalRoute.ts)
backend/apps/evga_exchange/    ErsopRegistration (send/check/return) + stub; DeliveryRecord (sentAt,
                                       acknowledgedAt, response, decision...), InformationRequestRound
backend/apps/evga_appeals/     Appeal, AppealAdmission, AppealArgumentRow; ThirdPartyNotice, ThirdPartyEvent
backend/apps/evga_execution/   projection ExecutionItem (или view) + deadlines (auditDeadlines)
backend/apps/evga_references/  AuditObject (surfk.audit_objects + plan), Employee, OPF, BasisKind, Initiator,
                                       Region, RiskLevel; GBD ЮЛ клиент (SOAP getJurInfoByBin) + stub
backend/apps/notifications/    Notification
```

Общие компоненты prof переиспользуются как есть: `apps/core` (`TimeStampedModel`, `Attachment`, `AuditEvent`, `NumberSequence/IssuedNumber`, `PageNumberPaginationWithPageSize`, `exception_handler`), `apps/accounts` (`User`, `RoleAssignment`, `HasDomainLevel`, `ScopedQuerySetMixin`, Keycloak), `apps/catalogs` (`Department`, `Region`, `GovernmentBody`).

Новые `PermissionDomain`: `evga_cases`, `evga_quality`, `evga_kvga`, `evga_registry_confirm`, `evga_appeal`, `evga_cabinet`; уровни `VIEW/EDIT/APPROVE/SIGN/DECIDE` как в prof.

### 3.2 Сводная таблица endpoint'ов

| Метод и путь | Тело → ответ | Порт из фронта |
|---|---|---|
| `GET /api/evga/cases/` | фильтры §2.2 → `Paginated<CaseListItem>` | `caseSearch.matchesFilters` |
| `POST /api/evga/cases/` | §2.3 → 201 `Case` | `CaseForm.save`, `validateCase`, `nextCaseNumber` |
| `GET /api/evga/cases/{id}/workspace/` | → агрегат §2.5 | `CaseWorkspace` |
| `PATCH /api/evga/cases/{id}/` | поля дела → `Case` | `saveCase` |
| `PUT /api/evga/cases/{id}/group/` | `{members[]}` | `WorkingGroup.onChange` |
| `POST /api/evga/cases/{id}/coauthors/` | `{employee_id}` | `assignCoauthor` |
| `PUT /api/evga/cases/{id}/calendar/` | `{holidays[],working_dates[],confirmed_years[]}` | `RegulatoryPanel` |
| `GET /api/evga/cases/{id}/deadlines/` | → `Deadline[]` | `auditDeadlines` |
| `GET /api/evga/cases/{id}/progress/` | → `ExecutionStage[]` + `next` | `executionStages`, `nextExecutionStep` |
| `GET /api/evga/cases/{id}/history/` | → `Paginated<HistoryEntry>` | `audit.history` |
| `POST/GET/DELETE /api/evga/cases/{id}/attachments/[{aid}/]` | multipart | `FileAttachments` дела |
| `GET /api/evga/cases/{id}/available-documents/` | → `[{kind, blocked_reason}]` | `creationBlock`, `creationAccessBlock` |
| `POST /api/evga/cases/{id}/documents/` | `{kind}` → 201 `Document` | `createDocument` + `saveDocument` |
| `POST /api/evga/cases/{id}/documents/bulk-working-papers/` | → `{created}` | «Создать доступные рабочие формы» |
| `POST /api/evga/cases/{id}/counter-cases/` | §2.5 → 201 `Case` | `CounterChecks.create` |
| `POST /api/evga/cases/{id}/quality-assignments/` | `{stage, expert_id, reason}` | `assignQualityExpert` |
| `POST /api/evga/cases/{id}/appeal/assign/` · `admission/` · `admission/notify/` · `arguments/` (PUT) · `arguments/decide/` | §2.5 | `appeals.ts` |
| `POST /api/evga/cases/{id}/third-parties/` · `third-parties/none/` · `POST /api/evga/third-parties/{id}/events/` | §2.5 | `thirdParties.ts` |
| `GET /api/evga/documents/{id}/` · `GET .../versions/{n}/` | → `Document`, `DocumentVersion` + `permissions` | `DocumentWorkspace` |
| `PATCH /api/evga/documents/{id}/versions/{n}/` | `{values, group, attachment_ids}` (только `Проект`/`Возвращен на доработку` без активного маршрута) | `persist`, `assertAttachmentRetention` |
| `DELETE /api/evga/documents/{id}/` | soft delete | `deleteDocument` |
| `POST /api/evga/documents/{id}/send-to-quality/` | | `sendDocumentToQuality` |
| `POST .../sign/` | | `activateDocument` |
| `GET .../route-candidates/` · `POST .../submit/` | `{stages[], signer_id, comment, expected_version}` | `ReviewRouteDialog`, `submitDocument` |
| `POST .../approve/` · `return/` · `reject/` · `recall/` | `{comment?, expected_version}` | `approveDocument`, `returnDocument`, `rejectDocument`, `recallDocument` |
| `POST .../revisions/` | `{reason}` → новая версия | 7 функций создания редакций + `renewQuality` |
| `POST .../group-signatures/request/` · `sign/` · `approve/` | | `requestReportGroupSignatures`, `signReportGroup`, `signAssignmentGroup`, `approveAssignmentGroup` |
| `POST .../registry-confirmation/request/` · `decide/` | `{confirmer_id}` / `{decision, comment}` | `sendRegistryToConfirmer`, `decideRegistryConfirmation` |
| `POST .../kvga-confirmation/request/` · `decide/` | | `sendInstructionToKvga`, `decideInstructionKvga` |
| `POST .../request-quality/` · `request-approval/` | | `requestMainQuality`/`requestPreparationQuality`, `requestMainApproval`/`sendPreparationForApproval` |
| `POST .../quality/sign/` · `quality/submit-to-head/` | | `signMainQuality`, `submitMainQualityToHead` |
| `POST .../ersop/send/` · `ersop/check-status/` · `ersop/return/` (стенд) | | `performRegistration` |
| `POST .../deliver/` · `deliver/refuse/` | | `deliverDocument("send"/"refuse")` |
| `POST .../information-request/{send\|review\|accept\|reject\|resend\|mark-refused}/` | `{comment, deadline?}` | `transitionInformationRequest` |
| `POST .../apply-amendment/` | → `workspace` | `applyAmendment` |
| `POST/GET/DELETE .../versions/{n}/attachments/[{aid}/]` | multipart `{file, slot?}` | вложения версии и строк |
| `GET /api/evga/cabinet/documents/` · `POST .../{id}/acknowledge/` · `respond/` · `decision/` · `information-request/acknowledge/` · `respond/` · `POST /api/evga/cabinet/cases/{id}/documents/ {kind: objections\|response}` | | роль `object` (`deliverDocument`, `transitionInformationRequest`, `creationAccessBlock`) |
| `GET /api/evga/quality/` · `GET /api/evga/quality/{case_id}/` | | `QualityRegistry` |
| `GET /api/evga/tasks/` | | `ApprovalTasks` + `caseApprovalRoutes` |
| `GET /api/evga/execution/items/` | | `executionItemsForCases` |
| `GET /api/evga/notifications/` · `POST .../{id}/read/` · `mark-all-read/` | | `Notifications` |
| `GET /api/evga/audit-objects/` · `search/?bin=` · `{bin}/previous-audits/` | | `ObjectsRegistry`, `ObjectLookup`, `previousAuditRows` |
| `GET /api/evga/references/employees/` · `opf/` · `basis-kinds/` · `initiators/` · `regions/` · `risk-levels/` · `document-types/` | | `PeoplePicker`, `AdvancedSearch`, `BasisForm`, `documentMatrix` |
| `GET /api/auth/me` (prof) | `{id, full_name, position, roles[]}` | `account` |

Порядок реализации по критичности: (1) auth/me + cases list/create/workspace; (2) documents get/patch/create + attachments; (3) submit/approve/return/reject + tasks; (4) preparation/main/KVGA/registry/quality actions; (5) ERSOP/delivery/cabinet/information-request; (6) appeals/third-parties/amendments/counter-cases; (7) execution/progress/deadlines/notifications; (8) references и стабы.

### 3.3 Соглашения ответа и конкурентность

- Каждое действие возвращает обновлённый `Document` (или `workspace` дела, когда меняются несколько документов: `apply-amendment`, активация `quality*`, регистрация `additional`). Фронт заменяет объект в состоянии — это совместимо с текущим `updateCase(next)`.
- `expected_version` (номер версии) обязателен для решений — фронт уже передаёт `versionNumber` в `approveDocument/returnDocument/rejectDocument/signReportGroup/decideRegistryConfirmation/decideInstructionKvga`. При несовпадении — 409 с `detail` «Открыта устаревшая версия документа. Решение недоступно.» (текст из `documentStateMachine.ts`). Проверки `mainCurrentBlock`, `preparationCurrentBlock`, `assertExecutionResponseSave`, «stale» в `saveDocument` заменяются на `updated_at`/`select_for_update` в транзакции.
- Ошибки — `DocumentTransitionError` → `ValidationError({"detail"})` (prof), envelope `apps/core/exceptions.py`. Тексты сообщений уже есть на русском во всех функциях `*Block`/`throw Error(...)` — переносить дословно, фронт показывает их в `toast`/`error`.

---

## 4. Файлы: сейчас и как перевести на `Attachment` + MinIO

### 4.1 Как сейчас

- `types.ts: Upload = { id, name, type, size, data: string (data:URL base64), description? }`.
- `utils/files.ts: readUploads(files)` — `FileReader.readAsDataURL`, `id: crypto.randomUUID()`.
- `components/FileAttachments.tsx` — `<input type=file multiple>`, drag&drop (`drop`), список `<a href={f.data} download={f.name}>`, кнопка удаления (`onChange(value.filter(...))`), `readOnly`.
- Где лежат `Upload[]` (все в одном JSON дела в IndexedDB):
  1. `AuditCase.attachments` (вкладка «Вложения»);
  2. `Basis.attachments` (`BasisForm`), и копия в `values.printContext.bases` каждой версии (через `printContext(audit)` — base64 дублируется в каждом документе);
  3. `DocumentVersion.attachments` (панель «Вложения» формы, ИРПИ, рабочие формы);
  4. `values.<section>[].files` строк коллекций с `section.attachments` (`DocumentForm.Collection`), `IrpiRow.files` (`IrpiRowForm`), `permissionFiles` в ИРПИ, `row.files` в `ViolationRegistryForm`;
  5. `delivery.attachments`, `delivery.decisionAttachments`;
  6. `informationRequest.rounds[].response.attachments`;
  7. `appeal.admission.files`, `appeal.arguments.rows[].files`;
  8. `thirdParties[].noticeFiles/receiptFiles/response.files/response.forwardingFiles`;
  9. `saveDocument` копирует `v.attachments` в новое основание `bases[]` при регистрации `additional`;
  10. `executionItems.ts` строит `evidence[].href = file.data`.
- `forms/validation.ts: assertAttachmentRetention` ищет любые объекты с полями `id+data+name` во всём `values` и запрещает удалять их вне статуса `Проект`.
- Ограничений размера/типа нет; `alert("Не удалось прочитать файл")` при ошибке.

### 4.2 Целевое состояние (по prof)

- Модель `apps/core/models.py: Attachment` (UUID, `GenericForeignKey(content_type, object_id)`, `kind: AttachmentKind`, `file = FileField(upload_to=attachment_upload_to)` → `attachments/{ct}/{object_id}/{uuid}_{name}`, `original_name`, `size`, `mime`, `checksum` SHA-256 (`core/services/files.py: sha256_of`), `uploaded_by`, `uploaded_at`). Хранилище: `STORAGES["default"] = storages.backends.s3.S3Storage` с `MINIO_*` (prof `config/settings/production.py`, `default_acl: private`, `querystring_auth: True`, `file_overwrite: False`); локально `FileSystemStorage`. `docker-compose.yml` prof уже содержит `minio` + `minio-init` (bucket `saq-attachments`).
- Загрузка: `attach_file(target, kind, uploaded_file, uploaded_by)` (prof `apps/documents/services/attachments.py`). Endpoint'ы: `POST /api/evga/documents/{id}/versions/{n}/attachments/` (multipart `file`, `kind`, `slot`), `POST /api/evga/cases/{id}/attachments/`, а для строк форм и панелей (§4.1 п. 4–8) — общий `POST /api/evga/attachments/` `{file, kind, target_type, target_id, slot}` где `slot` = `"values:<section>:<rowId>"`, `"delivery"`, `"delivery.decision"`, `"information-request:<roundId>"`, `"appeal.admission"`, `"appeal.arguments:<violationId>"`, `"third-party:<id>:<event>"`. Ответ — `AttachmentSerializer` (`id, kind, original_name, size, mime, file(url), uploaded_by, uploaded_at`).
- Скачивание: `GET .../attachments/{attachment_id}/` → `FileResponse(attachment.file.open("rb"), filename=original_name, as_attachment=True)` с проверкой домена/скоупа (prof `DownloadAttachmentView`); для кабинета объекта — отдельный маршрут (`cabinet-document-download-attachment`). Не отдавать прямые presigned-URL MinIO наружу без необходимости.
- Удаление: `DELETE .../attachments/{id}/` разрешено только пока владелец-объект в статусе `Проект` (это и есть `assertAttachmentRetention`); иначе 400 с текстом «Удалять вложения можно только в статусе «Проект»…».
- Ссылки в JSON `values`: вместо `Upload` хранить `{ id, name, type, size, url }` (`AttachmentRef`) — те же имена полей `id/name/type/size`, поэтому `FileAttachments`, `DocumentForm`, `IrpiRowForm`, печатные формы (`printFiles` в `referencePrintData.ts`) продолжают работать после замены `href={f.data}` на `href={f.url}`. `printContext` больше не должен копировать файлы оснований — только `attachment_ids`.
- Ограничения (в prof явно не заданы — предложение): `DATA_UPLOAD_MAX_MEMORY_SIZE`/`FILE_UPLOAD_MAX_MEMORY_SIZE` 25 МБ, максимум 50 МБ на файл, allow-list MIME (pdf, doc/docx, xls/xlsx, jpg/png, zip, sig/cms для ЭЦП), проверка расширения+`python-magic`, антивирус — открытый вопрос.
- В старом стеке файлы шли через портал (`Upsert Document` → `portal.documents(purpose_id, url)`, `Delete Document File` → HTTP DELETE по `url`, `Document Uploaded` webhook) — т.е. внешний файловый сервис с URL; в новой схеме заменяется MinIO через django-storages.

### 4.3 Изменения на фронте для файлов

- `FileAttachments`: `onChange` → вместо `readUploads` вызывать `api.uploadAttachment(target, files)` и добавлять полученные `AttachmentRef`; кнопка удаления → `api.deleteAttachment(id)` (только в `Проект`, иначе скрыть). Нужен проп `target` (тип+id+slot) — единственное изменение сигнатуры, затрагивает ~20 мест использования.
- `utils/files.ts` — удалить или оставить для превью.
- `assertAttachmentRetention` — оставить как клиентскую подсказку (по `id`).

---

## 5. Справочные API (ObjectLookup, PeoplePicker, рабочая группа, участники маршрутов)

| Компонент / потребность | Сейчас | Нужный API | Источник в n8n |
|---|---|---|---|
| `ObjectLookup` (БИН → объект; `planned` — предупреждение «не включён в перечень») | `objectRegistry` (12 записей), `catalogue` (11) | `GET /api/evga/audit-objects/search/?bin=000000000000&year=2026&lang=ru` → `{found, object:{bin,name_ru,name_kz,director,opf,abp,address,region,risk_level,risk_value}, in_registry, plan_data:{basis_kind, order_number, order_date, audit_type, inspection_type, coverage_*, score_*}}`; при отсутствии — обращение к ГБД ЮЛ и сохранение в `AuditObject` | `EVGA: Audit Object - Search by BIN`, `Service GDBJL surfk` (SOAP `getJurInfoByBin` на `prodpi1.emf.minfin.kz`), `audit-objects-apl_CRUD` |
| `ObjectsRegistry` (перечень ОА с рисками по годам) | `catalogue` | `GET /api/evga/audit-objects/?year=&region=&risk_level=&search=&page=` | `EVGA: Audit Objects - Get`, `EVGA: Evga Risk Category - Get`, `EVGA: Subj Sched Insp - Get` |
| Предыдущие аудиты объекта (ИРПИ) | `previousAuditRows(audit, previousCases)` — сканирует все дела в памяти | `GET /api/evga/audit-objects/{bin}/previous-audits/?before=<created_at>` → `[{case_number, authority, report_number, date, questions[], period}]` | `get_previous_audit_list_by_bin` (`listPreAudits`) |
| `PeoplePicker` / `WorkingGroup` (ФИО, должность, организация, руководитель) | `people` (6 записей) | `GET /api/evga/references/employees/?search=&department_id=&position=&limit=&offset=` → `{id, iin, fullname, department{name, short_name}, position{name}, email}`; `Person` фронта = `{id, name, position, organization, leader}` — маппинг `organization = department.short_name` | `EVGA: Employees - Get` (`surfk.employees/departments/positions`, `is_active`, `employment_status='active'`) |
| Соавторы (`CaseWorkspace`, select из `accounts` с `role auditor`) | `accounts` | тот же справочник сотрудников с фильтром по роли `auditor` | `EVGA: Add Case Participants` |
| Кандидаты маршрута (`ReviewRouteDialog`: `routeReviewer`, `routeApprover`) | `accounts` | `GET /api/evga/documents/{id}/route-candidates/` (сервер фильтрует по ролям: reviewer/approver, «апелляция» для `objection-result`, `quality-head` для `quality*`) | `Get Keycloak Users`, `Keycloak Subsystem Users V2` |
| Подтверждающие КВГА / реестра, эксперты КК, исполнители апелляции (select'ы в `PreparationActions`, `MainActions`, `QualityAssignmentPanel`, `AppealPanel`) | `accounts.filter(role === …)` | `GET /api/evga/references/employees/?role=kvga\|reestr-confirmer\|quality\|appeal-expert` | `Appeals - Heads list`, `assign-expert-to-case` |
| `FormFields` `type: "person"` (`[...audit.group, ...people]`) и `type: "object"` (`catalogue`) | демо-массивы | те же два справочника | — |
| `BasisForm` (`basisOptions`, `initiatorOptions`), `AdvancedSearch` (`opf`, `org`), `documentMatrix` (виды документов), `stageNames` | константы | `GET /api/evga/references/{basis-kinds,initiators,opf,controlling-orgs,document-types,audit-types,check-types}` | `EVGA: Control Reasons Type`, `Evga Check Initiator`, `Organizational Legal Forms`, `Evga Controlling Org`, `Evga Audit Type`, `Evga Check Type`, `Dictionaries - Get` |
| Вопросы программы аудита (`questionFields`, `irpiForm.ts`) | ввод вручную | `GET /api/evga/references/audit-questions/` | `EVGA: Evga Audit Questions - Get` |
| Виды нарушений / меры реагирования / объекты риска / методы выборки | ввод вручную/`options` в схемах | справочники | `Offense Type - Get` (+`/tree`), `Response Measure - Get`, `Risk Object Type - Get`, `Sampling Methods - Get`, `Audit Result - Get`, `Control Spheres - Get` |

---

## 6. Демо-механики, которые должен заменить сервер

| Механика | Где | Что делать |
|---|---|---|
| Переключение ролей (`AppShell` меню «Сменить роль», `accounts`, `localStorage saq.evga.account.v1`, `pendingAccount` с подтверждением) | `AppShell.tsx`, `EvgaModule.tsx` | Удалить. Роль — из `/api/auth/me`. Для стенда: seed-пользователи (`manage.py seed_evga_users`) с теми же ролями/ФИО, что в `accounts` (auditor, reviewer-1/2, approver, quality, quality-2, kvga, coauthor, object, quality-head, appeal-*, commission-*, reestr-confirmer), локальный вход `POST /api/auth/local/login`. |
| «Тестовый ответ ЕРСОП» — кнопки «Учесть регистрацию» (ввод номера, дефолт `УЧ-…`) и «Учесть возврат» в `DocumentActions`; демо `advanceDemoCase` вызывает `performRegistration(...,"send")` и `"accept"` | `workflow.ts: performRegistration` | Сервис `evga_exchange/services/ersop.py` с интерфейсом `send(document) → exchange_id`, `check_status(document) → {status, number, date, comment}`; реализация-стаб как `apps/ersop/services/stub_exchange.py: fake_register_package` (номер через `issue_number(key="ersop-registration", context={yyyy})`), запись обменов в `ErsopExchange(request_payload/response_payload)`. Реальная интеграция — порт `EVGA ERSOP Workflow` (`send_to_ersop`/`check_status`). Кнопки «Учесть регистрацию/возврат» остаются только у роли администратора стенда. |
| Тестовая регистрация номеров дел/документов (`nextCaseNumber` от 52970, `documentSequence`, `ВП-n`) | `caseRules.ts`, `documentFactory.ts`, `CounterChecks.tsx` | `NumberSequence` + `issue_number` (prof): ключи `evga-case` (`30101-{yy}-{seq}`), `evga-document` (scope = case, `{case_number}/{seq:02d}`), `evga-counter-case` (`{parent}/ВП-{seq}`); n8n использовал `surfk.get_next_case_sequence(year)`, `surfk.get_next_doc_sequence('with_org', year)` — при миграции взять текущие значения счётчиков. |
| Имитация ознакомления объекта и решений объекта (роль `object` в том же браузере: «Ознакомлен», «Предоставить ответ», «Подписать…»; `deliverDocument`, `transitionInformationRequest`) | `DocumentActions.tsx`, `InformationRequestPanel.tsx`, `ThirdPartiesPanel.tsx`, `AppealPanel` («Создать возражения») | Кабинет объекта аудита как `apps/cabinet` prof: пользователь `is_subject_representative` + `subject`; endpoint'ы `/api/evga/cabinet/...` (§3.2); нарочное ознакомление — автор фиксирует канал `manual` со сканом (prof `record_acknowledgement`). |
| Уведомления в памяти (`AuditCase.notifications[]`, `readBy`) | `workflow.saveDocument`, `caseAccess`, `qualityAssignment`, `appeals` | Таблица `Notification`; создание в тех же сервисных функциях (список получателей по статусу — логика `saveDocument` строк 476–541); отправка WS/e-mail — опционально (n8n `notification service` использовал WebSocket `CUSTOM.notificationService`). |
| `demoScenario.ts` (1340 строк): `workflowSampleCases` («С нуля», «Полностью заполнено», «Основные документы», «Половина процесса»), `preparedCases` (`case-2026-0910/0911`), `addPlannedSampleCases`, `addRegistrySampleCases` («Реестр: выбор вопросов/результаты и нарушения»), `createDemoCase` (`demo-show-*`), `advanceDemoCase`/`demoNextLabel` («Быстрый показ»), `fillDemoDocument`/`fillPreparedDocument`, `financialDemoValues.ts`; метка `sampleScenario` в `CasesList`/`QualityRegistry` | `useAuditCases.ts` (подмешивает при каждой загрузке) | Перенести в management-команду `seed_evga_demo_cases` (как `seed_checklists`/`seed_risk_rules` prof), которая через те же серверные сервисы прогоняет сценарии (полезно как интеграционный тест). `fillPreparedDocument` в `CaseWorkspace.openDocument` и `sampleScenario` из UI убрать; `isDemoCase`-фильтры (`!id.startsWith("demo-show-")`) убрать. |
| `seedCases` («sample-case» `30101-25-52970`) и `catalogue/objectRegistry/people/accounts` | `demoData.ts` | `seed_evga_references` (объекты, сотрудники, справочники) + `seed_evga_users`. |
| Клиентский расчёт `quality: [bool×3]` при загрузке, `migrateLegacyApprovalRoutes` | `useAuditCases.ts` | `quality` считает сервер (`qualityPassed`); миграция legacy-маршрутов не нужна (данных в IndexedDB на проде нет). |
| «Рабочий календарь дела» вручную (`RegulatoryPanel`) | `calendar` | Справочник производственного календаря РК на сервере; переопределения по делу — опционально. |
| Политика сроков в `localStorage` | `ExecutionRegistryPage` | Оставить (персональная настройка UI). |

---

## 7. PDF / печать

### 7.1 Сейчас

- Печатные формы — React-компоненты: `ReferencePrintForm.tsx` (1976 строк; 11 видов `hasReferencePrint`: `irpi, program, plan, assignment, instruction, request, report, violations, evidence, conclusion, prescription`; приложения к Правилам № 413/392 — `annexes`), `QualityPrintForm.tsx` (заключение КК, 16 пунктов, kz/ru), `DocumentPrintForm.tsx` (общая печать по схеме `formFor` для остальных видов). Переключатель языка «Русский/Қазақша» — локальный `useState` в форме. Данные — `printAudit(audit, version)` берёт снимок `values.printContext` (дело на момент версии) через `referencePrintData.ts`.
- «Печать» — `window.print()` с CSS `document-print.css`.
- «Скачать PDF» — `PdfDownloadButton` → `pdfExport.ts`: клонирует DOM печатной формы (`PRINT_ARTICLE_SELECTOR`), `buildPrintDefinition` конвертирует DOM в определение pdfmake (A4, поля 20 мм, `LiberationSerif` 12pt, нумерация страниц), шрифты `src/assets/fonts/LiberationSerif-*.ttf` грузятся fetch'ем в VFS; pdfmake подключается лениво (`import("pdfmake/build/pdfmake.js")`). Комментарий в коде: «No document data is sent to a server».
- Тест `tests/pdf-export.test.ts`.

### 7.2 Рекомендация

- **Оставить клиентскую печать/PDF как есть** на первом этапе: она зависит только от `audit`, `doc`, `version` — после перехода на API получает те же объекты из `GET /documents/{id}/versions/{n}/` (при условии, что `printContext` сохраняется сервером в `values` при создании/сохранении версии, как сейчас в `persist()` и `createDocument`). Вложения в печатной форме (`printFiles`) выводят только имена — base64 не нужен.
- **Серверный PDF нужен** только для: (а) подписания ЭЦП (нужен детерминированный файл), (б) отправки в ЕРСОП/объекту/на печать без браузера, (в) архивации версии. Тогда: endpoint `GET /api/evga/documents/{id}/versions/{n}/print/?lang=ru|kz&format=pdf|html`, генерация HTML из тех же данных (Jinja2-шаблоны по видам документов; шаблоны строятся по разметке `ReferencePrintForm` — она уже разбита на функции `Study/Program/Plan/Assignment/Instruction/Request/Report/Violations/Evidence/Conclusion/Prescription`) → WeasyPrint/wkhtmltopdf; шрифты — те же `LiberationSerif` (лицензия `LICENSE_LIBERATION`); реквизиты — `GovernmentBody` (prof `catalogs`: `letterhead_kk/ru`, адрес), номер/дата документа, подписи из `signatures[]`, регистрационный номер ЕРСОП. Готовый PDF складывать как `Attachment(kind="print_form")` к версии, чтобы не пересчитывать.
- Требуется серверу для печати: `printContext` (объект, цель, основания, тип/формат аудита, `schedule`, группа, автор, `sources` — последние версии `instruction/irpi/program/report/violations/conclusion` — см. `printContext.ts`), справочник должностей подписантов, двуязычные наименования (`object.kz`, `purposeKz`), нумерация приложений (`annexes` в `ReferencePrintForm`).
- Старый стек: `EVGA Document Verify (Public)` (`GET evga/documents/verify`) — публичная проверка документа по QR/номеру; если нужна — серверный PDF обязателен.

---

## 8. Оценка: что менять при переходе на API, что не трогать

### 8.1 Не трогать (или минимальные правки)

| Файл(ы) | Причина |
|---|---|
| `components/ui.tsx`, `Modal.tsx`, `ErrorBoundary.tsx`, `Sidebar.tsx`, CSS | чистый UI |
| `forms/schema.ts`, `forms/documentForms.ts`, `forms/formValues.ts` (кроме `initialValues` — уйдёт на сервер), `forms/formLinks.ts`, `forms/referenceForms.ts`, `data/irpiForm.ts`, `data/workingPapers.json`, `data/documentMatrix.ts` | схемы форм и справочник видов документов; можно продублировать на сервер как JSON, но фронту нужны для рендера |
| `DocumentForm.tsx`, `FormFields.tsx` (кроме источника `catalogue/people`), `IrpiForm.tsx`, `IrpiRowForm.tsx`, `WorkingPaperForm.tsx`, `ViolationRegistryForm.tsx`, `AuditCalculations.tsx`, `BasisForm.tsx` | работают над локальным `draft` |
| `ReferencePrintForm.tsx`, `QualityPrintForm.tsx`, `DocumentPrintForm.tsx`, `referencePrintData.ts`, `pdfExport.ts`, `PdfDownloadButton.tsx` | печать по данным версии |
| `shared/workflow/ApprovalInbox.tsx`, `ApprovalRouteEditor.tsx`, `shared/execution/ExecutionRegistry.tsx`, `execution.ts` | презентационные, получают массивы через пропсы |
| `documentPresentation.ts`, `auditFormat.ts`, `auditType.ts`, `dateFormat.ts`, `navigation.ts`, `useEvgaNavigation.ts` | утилиты |
| `types.ts` | оставить, добавить `AttachmentRef`, `permissions`, серверные `id` |

### 8.2 Менять минимально (замена источника данных/вызова)

| Файл | Изменение |
|---|---|
| `services/auditCaseRepository.ts` + новый `services/apiCaseRepository.ts` | Контракт «load всё / save всё» заменить на `EvgaApi` (`client.ts` в стиле prof `frontend/src/api/client.ts`: `fetch` с `credentials: "include"`, `ApiError`, `API_ERROR_EVENT`) |
| `useAuditCases.ts` | Убрать подмешивание демо, `migrateLegacyApprovalRoutes`, пересчёт `quality`, автосохранение всего массива; `updateCase` оставить как локальный кэш |
| `EvgaModule.tsx` | `account` из `/api/auth/me`; загрузка дела по маршруту (`workspace`), документа по `docId`; `saveCase` → `POST/PATCH`; `onSave` документа → API; `onCreate` КК → API |
| `CasesList.tsx`, `AdvancedSearch.tsx` | фильтры/пагинация → query-параметры, `Paginated` |
| `CaseForm.tsx`, `ObjectLookup.tsx`, `PeoplePicker.tsx`, `FormFields.tsx` (`object`, `person`) | справочники → API; `validateCase` оставить как клиентскую проверку |
| `ObjectsRegistry.tsx` | список → API |
| `CaseWorkspace.tsx` | каждое `onChange(f(audit))` → вызов API (создание документа, удаление, группа, календарь, соавтор, вложения); блокировки кнопок — из `available-documents`/`permissions` |
| `DocumentWorkspace.tsx` | `act(fn)` → `act(apiCall)`; `persist` → `PATCH`; `readOnly/eligible/canSubmit` → `permissions` с сервера (можно оставить клиентские функции как дублирующие подсказки, но источник истины — сервер) |
| `MainActions.tsx`, `PreparationActions.tsx`, `DocumentActions.tsx`, `InformationRequestPanel.tsx`, `ReviewRouteDialog.tsx` | `onAction(() => domainFn(...))` → `onAction(() => api.post(...))`; select'ы участников → справочники |
| `AppealPanel.tsx`, `ThirdPartiesPanel.tsx`, `AmendmentsPanel.tsx`, `CounterChecks.tsx`, `QualityRegistry.tsx`, `QualityAssignmentPanel.tsx`, `Notifications.tsx`, `ExecutionRegistryPage.tsx`, `ApprovalTasks.tsx`, `ExecutionProgress.tsx`, `RegulatoryPanel.tsx` | замена доменного вызова на API; данные (`executionItemsForCases`, `caseApprovalRoutes`, `executionStages`, `auditDeadlines`) — с сервера |
| `FileAttachments.tsx` | `readUploads` → upload API; `href={f.url}`; проп `target` |
| `AppShell.tsx`, `LoginPage.tsx`, `useDemoSession.ts` | убрать смену ролей, подключить Keycloak-вход |

### 8.3 Перенести на сервер (Python), на фронте оставить только для подсказок/тестов

`documentStateMachine.ts`, `workflow.ts`, `mainWorkflow.ts`, `preparationWorkflow.ts`, `documentFactory.ts`, `informationRequests.ts`, `appeals.ts`, `amendments.ts`, `thirdParties.ts`, `qualityAssignment.ts`, `qualityControlRules.ts`, `qualityConclusion.ts` (данные формы КК), `executionItems.ts`, `executionDecision.ts`, `executionProgress.ts`, `deadlines.ts`, `caseAccess.ts`, `caseRules.ts`, `reviewParticipants.ts`, `approvalTasks.ts`, `violationRegistry.ts` (валидация), `forms/validation.ts`, `irpiValidation.ts`, `workingPapers.ts` (`validateWorkingPaper`), `shared/workflow/approvalRoute.ts`, `history.ts`, `printContext.ts`. Тесты `tests/*.test.ts` (22 файла, ~5 000 строк, `node --test`) — готовые спецификации для pytest: каждый сценарий (`bpmn-main-workflow`, `bpmn-preparation`, `bpmn-information-requests`, `appeals-amendments`, `full-process`, `npa-compliance` и т.д.) переводится в интеграционный тест API.

### 8.4 Удалить

`demoScenario.ts`, `financialDemoValues.ts`, большая часть `data/demoData.ts` (оставить только текстовые константы до появления справочников), `indexedDbCaseRepository.ts` (после миграции), `scripts/test-ui.mjs` — оставить (проверка `.test.tsx` через esbuild+linkedom), `scripts/import-working-papers.py` — оставить (импорт таблиц рабочих форм из `zakon.uchet.kz` в `workingPapers.json`; на сервере тот же JSON — источник `DocumentType.form_schema` для 62 рабочих форм).

### 8.5 Объём

- Действий пользователя, требующих серверного вызова: ~75 (подсчёт по §2), сводятся к ~45 endpoint'ам (§3.2).
- Компоненты, которые придётся править: 25 файлов (§8.2), из них существенно — `EvgaModule`, `CaseWorkspace`, `DocumentWorkspace`, `FileAttachments`, `useAuditCases`.
- Компоненты без изменений: ~30 файлов (§8.1).

---

## 9. Открытые вопросы

1. Соавторов назначает `account.id === "approver"` («руководитель органа аудита») — какая роль/должность в Keycloak соответствует этому и `commission-chair`, `quality-head`, `appeal-head`?
2. ЭЦП: «Подписать»/«Утвердить»/«Подписать заключение» сейчас — запись в `signatures[]` без подписи. Нужен ли НУЦ/CMS-подпись PDF на сервере (тогда серверная генерация PDF обязательна, §7)?
3. ЕРСОП: реальный контракт `send-document`/`getErsop` из n8n (`EVGA ERSOP Workflow`) — форматы payload не видны в узлах (вызовы через `$vars.N8N_WEBHOOK_BASE_URL`); нужен доступ к этим воркфлоу/документации КПСиСУ.
4. Кабинет объекта аудита: строить отдельный SPA/раздел (как prof `/subject/:caseId`) или общий фронт с ролью `object`? Влияет на `AppShell` («Переключиться на объект»).
5. Нумерация: сохранять текущие форматы (`30101-YY-NNNNN`, `NNNNN/NN`, `…/ВП-n`) или взять из `surfk.get_next_case_sequence`/`get_next_doc_sequence('with_org')` старого стека (там другой формат)?
6. Производственный календарь РК: справочник на сервере или ручной ввод по делу (как сейчас `RegulatoryPanel`)?
7. Ограничения на файлы (размер, типы, антивирус) — в prof не заданы; нужны требования.
8. Фильтр `coauthor` и поле `rnn` в поиске дел сейчас отключены («Q04», «No RNN values») — нужны ли в API?
9. Уведомления: только внутри системы или также e-mail/WebSocket (в n8n был `notification service` c WS и RabbitMQ-логированием)?
10. Рабочие формы (62 вида, `workingPapers.json`): оставить схему в JSON на клиенте или хранить в `DocumentType.form_schema` на сервере (как `surfk.evga_document_mappings.form_schema`)?
11. Многоэтапные маршруты (`ApprovalRouteEditor` поддерживает несколько этапов sequential/parallel) — подтверждено ли это ТЗ ЭВГА (в `docs/architecture.md` указано «последовательное согласование»)?
12. `objection-result` с отзывом (`recallDocument`) и переназначением (`reassignReturnedDocument`) — есть ли аналог в BPMN (`EVGA - Appeal Result (M23-RVO) actions`)?
