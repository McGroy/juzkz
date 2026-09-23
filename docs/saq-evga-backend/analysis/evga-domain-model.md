# Доменная модель фронта ЭВГА (saq-evga-test): что должно стать моделями БД и API

Отчёт аналитика по области «доменная модель фронта ЭВГА». Источник — каталог
`saq-evga-test/src`
(React 19.1.1 + TypeScript 5.9 + Vite 7, `pdfmake` 0.2.20, тесты `node --experimental-strip-types --test tests/*.test.ts`,
`engines.node >= 22.18`). Эталон стиля бэкенда — `src/prof/saq-prof-control-demo/backend/apps/*` (Django 5 + DRF,
`TimeStampedModel` c UUID-ключами, `TextChoices`, приложения `core / catalogs / documents / cases / execution / ersop / subjects / accounts`).
Все имена полей, функций и констант ниже приводятся так, как они записаны в исходниках.

Содержание:

1. Резюме: как устроено состояние фронта и что из этого следует для бэкенда
2. Инвентарь сущностей (таблицы «поле | тип | обязательность | откуда берётся | комментарий»)
3. Каталог видов документов (36 основного дела + 7 встречной проверки + 62 рабочих документа + ИРПИ), зависимости, схемы полей, `formLinks`, `initialValues`
4. Справочники, зашитые в `data/` и `forms/`
5. Правила валидации, которые нужно перенести на сервер
6. Расчёты и печать/PDF
7. Предложение маппинга на Django-модели в стиле prof
8. Открытые вопросы
9. Кандидаты на переиспользование (в т.ч. сопоставление с n8n-схемой `surfk.*`)

---

## 1. Резюме

### 1.1. Как хранится состояние сейчас

* Единственный контракт хранилища — `src/services/auditCaseRepository.ts`:
  `interface AuditCaseRepository { load(): Promise<AuditCase[] | undefined>; save(cases: AuditCase[]): Promise<void>; }`.
* Реализация — `src/services/indexedDbCaseRepository.ts`: база IndexedDB `saq-evga-test`, objectStore `state`, ключ `cases`;
  **весь массив дел сохраняется целиком одним JSON-документом** при каждом изменении (`useAuditCases.ts`, `updateCase`).
* Вся бизнес-логика — чистые функции над неизменяемым `AuditCase` (`structuredClone` → изменения → возврат нового объекта).
  Ошибки — `throw Error("текст на русском")`, блокировки — функции `*Block(...)`, возвращающие строку-причину или `undefined`.
  Это удобно переносить в слой `services/` Django (как `apps/documents/services/*.py` в prof) практически 1:1.
* Файлы (`Upload`) хранятся **внутри JSON как data-URL** (`data: string`, `readUploads()` в `utils/files.ts`), в том числе вложения
  в строках коллекций (`files` в строках `violations`, `evidence`, `measures`, `objections.violations` и т.д.). На сервере это MinIO +
  `core.Attachment`.
* Аккаунты/роли — демо-список `accounts` в `data/demoData.ts` (`Account = {id,name,role,label,area?}`), «текущий пользователь» — `auth/useDemoSession.ts`.
  На сервере — Keycloak + `accounts.User` (как в prof).

### 1.2. Ключевые архитектурные свойства, которые нужно сохранить на бэкенде

| Свойство | Где во фронте | Следствие для БД/API |
|---|---|---|
| Документ = `kind` + массив **версий**; активна последняя (`activeVersion(doc) = doc.versions.at(-1)`) | `documentStateMachine.ts` | Таблица `DocumentVersion` с `version: int`, уникальность `(document, version)`; прошлые версии read-only |
| Содержимое версии — `values: Record<string, unknown>` по декларативной схеме `formFor(kind, auditType)` | `forms/documentForms.ts`, `forms/schema.ts` | `JSONField values` + серверная валидация по той же схеме (схему можно хранить в справочнике или зеркалить в Python) |
| Каждая версия фиксирует ссылки на версии исходных документов `sourceVersions[{documentId, version, contentSnapshot?}]` | `documentFactory.ts`, `mainWorkflow.ts`, `preparationWorkflow.ts` | Таблица `DocumentSourceVersion`; проверки «исходники изменились» — на сервере |
| Снимок дела для печати `values.printContext` (объект, цель, основания, группа, `sources{kind→{id,number,createdAt,version,values}}`) | `printContext.ts`, `referencePrintData.ts` | Хранить снимок дела в версии (JSON); значения исходных документов брать по FK на их версии |
| Маршрут согласования — отдельная неизменяемая сущность `ApprovalRoute` с историей, стадиями, участниками; замена версии → `superseded` | `shared/workflow/approvalRoute.ts` | Отдельные таблицы `ApprovalRoute / ApprovalStage / ApprovalParticipant / ApprovalEvent`; задачи (inbox) — вычисляемая проекция `getApprovalTasks` |
| Оптимистическая блокировка: «Открыта устаревшая версия», «Документ изменился. Обновите дело» (сравнение JSON истории/подписей) | `workflow.saveDocument`, `mainCurrentBlock`, `preparationCurrentBlock`, `executionDecision.assertExecutionResponseSave` | Поле `updated_at`/`row_version` + `If-Match`/`expected_version` в API действий |
| Реестр нарушений (`violations`) — 4 связанные коллекции внутри `values` со стабильными `id` строк, на которые ссылаются другие документы | `violationRegistry.ts`, `formLinks.ts` | Нормализованная проекция `Violation` (uuid строки = PK) обязательна: на неё ссылаются доказательства, возражения, предписание, ответ, третьи лица, КК, исполнение |
| Единая нумерация: дело `30101-YY-NNNNN`, документ `{дело}/NN`, встречная проверка `{дело}/ВП-N` | `caseRules.nextCaseNumber`, `documentFactory.documentSequence`, `CounterChecks.tsx` | `core.NumberSequence` + `IssuedNumber` (как в prof) |
| Уведомления, история дела, дедлайны (рабочие дни по производственному календарю) | `workflow.saveDocument`, `history.log`, `deadlines.ts` | `core.AuditEvent` (append-only), таблица уведомлений, справочник производственного календаря |

### 1.3. Итоговые цифры инвентаря

* Дело `AuditCase`: 40 полей верхнего уровня (11 обязательных + 29 опциональных), 4 вложенных массива-«реестра» (`documents`, `bases`, `group`, `history`) и 9 опциональных вложенных объектов/массивов (`appeal`, `thirdParties`, `amendments`, `notifications`, `calendar`, `schedule`, `qualityAssignments`, `coauthors`, `thirdPartiesReviewed`).
* Версия документа `DocumentVersion`: 15 обязательных полей + 13 опциональных блоков состояния.
* Видов документов: 36 (`docKinds`) + 7 (`counterDocKinds`) + 62 рабочих документа (`workingPapers.json`: 59 `financial-rd-NN` по акту `V1700015209`, 3 `compliance-rd-NN` по акту `V2200026715`) = 105 `kind`.
* Схем форм в `documentForms`: 42 базовых (все `docKinds`/`counterDocKinds` кроме `irpi`) + 2 финансовых варианта (`program`, `report`), расширения через `referenceFormFor`. Суммарно ≈ 900 объявлений полей (с учётом bilingual-полей, разворачиваемых в `*Ru`/`*Kz`).
* Статусов версии документа (`DocStatus`): 11. Ролей (`Role`): 10. Маршрутных статусов: 6 (маршрут) + 7 (участник) + 6 (задача).
* Правил валидации/блокировок, требующих переноса на сервер: ~120 (см. раздел 5).

---

## 2. Инвентарь сущностей

Обозначения: **обяз.** — поле обязательно по TS-типу (без `?`); «откуда» — кто/что заполняет.

### 2.1. `AuditCase` — дело аудита (`src/types.ts`)

| Поле | Тип | Обяз. | Откуда берётся | Комментарий |
|---|---|---|---|---|
| `id` | string (uuid) | да | `uid()` при создании (`CaseForm.tsx`) | PK |
| `number` | string | да | `nextCaseNumber(cases)` → `30101-{YY}-{seq}` (база 52970); для встречной — `${parent.number}/ВП-${n}` | Уникально |
| `object` | `AuditObject` | да | `ObjectLookup` по БИН из `objectRegistry` | Снимок объекта на момент создания |
| `auditType` | string | да | select `auditTypeOptions` = `Соответствие` / `Фин. отчетность` | `isFinancialAudit()` = `/финансов\|фин\./i` — исторически были и полные названия |
| `checkType` | string | да | `checkTypeOptions` = `Плановый` / `Внеплановый` | Плановый требует наличия в `catalogue` (перечень) |
| `checkKind` | string | да | `CaseForm` select (`Совместная` и др.) | При `Совместная` обязателен `jointObject` |
| `electronic` | boolean | да | `auditFormatLabels` (`traditional`/`electronic`) | Влияет на сроки заключения (3 vs 10 раб. дн.) |
| `dsp` | boolean | да | Toggle «Признак ДСП» | |
| `jointObject` | `AuditObject` | нет | `ObjectLookup` | Госорган-соисполнитель |
| `purposeRu`, `purposeKz` | string | да | форма дела | Цель аудита, двуязычно |
| `group` | `Person[]` | да | `WorkingGroup` компонент; `leader?: boolean` | Рабочая группа; ровно один `leader` |
| `bases` | `Basis[]` | да | `BasisForm`; для плановых — `plannedBasisFor(bin)`; пополняется при регистрации `additional` | Основания |
| `author` | string (ФИО) | да | `account.name` | В prof это FK на User; здесь строка |
| `createdAt` | ISO datetime | да | | |
| `status` | `"Открыто" \| "Закрыто"` | да | закрывается при активации `completion`, регистрации `counter-notification`, приказе «Отмена проверки» | |
| `attachments` | `Upload[]` | да | | Вложения дела |
| `documents` | `AuditDocument[]` | да | `createDocument` | Порядок = порядок создания |
| `quality` | `[boolean, boolean, boolean]` | да | пересчитывается `qualityPassed(audit, stage)` при каждом сохранении | Денормализованный флаг «КК этапа пройден» |
| `history` | `HistoryEntry[]` | да | `log(actor, action, comment)` | Журнал дела |
| `qualityAssignments` | `Partial<Record<Stage,{expertId, assignedAt, assignedBy}>>` | нет | `assignQualityExpert` (только `quality-head`) | Назначение эксперта КК на этап |
| `sampleScenario` | enum 6 значений | нет | демо-сценарии | **Не переносить** (демо) |
| `appeal` | `Appeal` | нет | `getAppeal`/`assignAppeal`/`recordAdmission`… | Рассмотрение возражений |
| `thirdParties` | `ThirdPartyNotice[]` | нет | `addThirdParty` (роль `object`) | Реестр третьих лиц |
| `thirdPartiesReviewed` | `{at, by, none: boolean, reason}` | нет | `recordNoThirdParties` / `addThirdParty` | Факт проверки наличия третьих лиц |
| `amendments` | `{documentId, version, at, by, targets[{documentId, version}]}[]` | нет | `applyAmendment` | Журнал применения доп. поручений |
| `documentSequence` | number | нет | `documentSequence(audit)` | Счётчик номеров документов (max из `number.split("/").pop()`) |
| `coauthors` | string[] (account id) | нет | `assignCoauthor` (только account `approver`) | Соавторы дела |
| `notifications` | `{id, at, documentId, text, recipients[], readBy[]}[]` | нет | `saveDocument`, `appeals.change`, `assignCoauthor`, `assignQualityExpert` | Внутрисистемные уведомления |
| `calendar` | `{holidays: string[], workingDates: string[], confirmedYears: number[]}` | нет | | Производственный календарь **на дело** (на сервере — глобальный справочник) |
| `parentCaseId` | string | нет | `CounterChecks.create` | Признак дела встречной проверки |
| `executionState` | `"Проводится" \| "Приостановлено" \| "Отменено"` | нет | регистрация `additional` с `order.type` | Состояние проверки |
| `personType` | `"Юридическое лицо" \| "Физическое лицо"` | нет | `CounterChecks` | Только для встречных проверок |
| `counterQuestion` | string | нет | `CounterChecks` | Вопрос встречной проверки → `questions[0].question` в `counter-instruction`/`counter-act` |
| `personBirthDate` | string (date) | нет | `CounterChecks` | Для физлица |
| `entrepreneurName` | string | нет | `CounterChecks` | Для ИП |
| `schedule` | `{start, end, periodFrom, periodTo}` | нет | заполняется из ИРПИ/поручения, меняется `applyAmendment` | Действующие сроки и период охвата |

### 2.2. `AuditObject` — объект аудита

| Поле | Тип | Обяз. | Откуда | Комментарий |
|---|---|---|---|---|
| `bin` | string(12) | да | реестр `objectRegistry` (`data/demoData.ts`) | Валидация `^\d{12}$` |
| `ru`, `kz` | string | да | | Наименование |
| `director` | string | да | | Руководитель |
| `opf` | string | да | | Организационно-правовая форма (например «Государственное учреждение») |
| `abp` | string | да | | Администратор бюджетных программ |
| `address` | string | да | | |
| `region` | string | да | | «Астана», «Карагандинская обл.», «г. Алматы» |
| `risk` | string | да | | `Высокая`/`Средняя`/`Низкая` (уровень риска СУР) |
| `score` | number | да | | Балл риска (99.7, 70.5, 22.5…) |

Два списка: `catalogue` (перечень объектов, дающий право на плановый аудит и `plannedBasisFor`) и `objectRegistry` = `catalogue` + объекты вне перечня.
На сервере: `AuditObject` (аналог `subjects.Subject` в prof, но с полями ЭВГА) + признак/таблица «включён в перечень на год» (в n8n — `surfk.annual_plans`, `surfk.plan_objects`).

### 2.3. `Basis` — основание

| Поле | Тип | Обяз. | Откуда | Комментарий |
|---|---|---|---|---|
| `id` | string | да | `basis-227`, `planned-basis-{bin}`, `additional-{docId}-v{n}` | |
| `number` | string | да | | Номер документа-основания |
| `kind` | string | да | `basisOptions` (6 значений) либо текст приказа | Вид основания |
| `initiator` | string | да | `initiatorOptions` (14 значений) | Инициатор |
| `date` | string (date) | да | | |
| `attachments` | `Upload[]` | да | | |

### 2.4. `Person` / `Account` / `Role`

`Person = {id, name, position, organization, leader?}` — участник рабочей группы (в `audit.group` и в `version.group`; при создании документа `group = structuredClone(audit.group)`, для КК — один эксперт с `organization: "КВГА МФ РК", position: "Эксперт контроля качества"`).

`Account = {id, name, role: Role, label, area?: "appeal"}`. `Role`: `auditor`, `reviewer`, `approver`, `quality`, `kvga`, `reestr-confirmer`, `invited-specialist`, `object`, `appeal-head`, `appeal-expert`.
Особые аккаунты, на которые логика ссылается **по `id`** (нужно превратить в роли/полномочия): `approver` (руководитель органа аудита: назначает соавторов `assignCoauthor`, подписывает обоснования `decideArguments`), `quality-head` (руководитель КК: `canAssignQualityExpert`, утверждает `quality1..3`), `commission-chair` (председатель апелляционной комиссии: `recordAdmission`, утверждает `objection-result`), `commission-1/2` (`reviewer` с `area: "appeal"`), `coauthor`, `object`, `kvga`, `reestr-confirmer`.

### 2.5. `Upload` — файл

| Поле | Тип | Комментарий |
|---|---|---|
| `id` | uuid | Стабильный id: `assertAttachmentRetention` запрещает исчезновение id из непроектной версии |
| `name`, `type`, `size` | string, string(MIME), number | |
| `data` | string (data-URL base64) | На сервере → MinIO, в JSON остаётся `{id, name, type, size}` |
| `description` | string? | |

### 2.6. `HistoryEntry` — `{id, at, actor (ФИО), action, comment}`. Ведётся и на дело, и на каждую версию документа; при сохранении новые события версии копируются в историю дела с префиксом `«{docName} · v{n}: »`. Аналог — `core.AuditEvent` prof (append-only).

### 2.7. `AuditDocument`

| Поле | Тип | Обяз. | Откуда | Комментарий |
|---|---|---|---|---|
| `id` | uuid | да | `uid()` | |
| `kind` | string | да | `definition(kind)` из `allDocKinds` | FK на справочник видов |
| `stage` | `0 \| 1 \| 2` | да | `definition(kind).stage` | Подготовительный / Основной / Заключительный |
| `number` | string | да | `${audit.number}/${seq.padStart(2,"0")}` | |
| `createdAt` | ISO | да | | |
| `author` | string (ФИО) | да | `actor.name` | |
| `versions` | `DocumentVersion[]` | да | | Минимум одна |

### 2.8. `DocumentVersion` — версия документа

| Поле | Тип | Обяз. | Откуда | Комментарий |
|---|---|---|---|---|
| `version` | number ≥ 1 | да | `+1` при `createNextVersion`, `createReturnedRevision`, `createRejectedRevision`, `reviseMainDocument`, `reviseMainQuality`, `revisePreparationDocument`, `applyAmendment`, `renewQuality`, `assignQualityExpert`, `reassignReturnedDocument`, `createResponseRevision` | |
| `status` | `DocStatus` (11) | да | конечный автомат | см. 2.19 |
| `values` | `Record<string, unknown>` | да | `initialValues(audit, kind)` → редактирование по `formFor` | Ключи = `section.key`; объектные секции → объект, коллекции → массив строк `{id, ...}`; `bilingual` поле `x` → `xRu`,`xKz`; плюс служебные `printContext`, `paper`, `calculationInputs_*`, `calculationResult_*`, `registrySchemaVersion` |
| `attachments` | `Upload[]` | да | | Вложения версии |
| `group` | `Person[]` | да | снимок `audit.group` | Рабочая группа версии (для `form.group === true` обязательна) |
| `reviewers` | string[] (account id) | да | `submitDocument` | Legacy-маршрут; при наличии `approvalRoutes` дублирует |
| `reviewerIndex` | number | да | | Позиция текущего согласующего (legacy) |
| `approver` | string (account id) | да | | Утверждающий (legacy) |
| `signatures` | `{person, at, role}[]` | да | все решения | ЭЦП-заглушка |
| `createdAt` | ISO | да | | |
| `history` | `HistoryEntry[]` | да | | |
| `approvalRoutes` | `ApprovalRoute[]` | нет | `submitDocument`, `submitMainQualityToHead` | Последний = текущий; старые `superseded` |
| `qualityConclusion` | string | нет | `saveDocument` при активации `qualityN` | Текст заключения КК по этой версии |
| `qualityDecision` | `"Без замечаний" \| "С замечаниями"` | нет | там же | Разрешает `canSubmit` для `requiresQuality` |
| `ownerRole` | `Role` | нет | `createDocument` | Кто редактирует: `auditor`/`quality`/`object`/`appeal-expert` |
| `ownerId` | string | нет | для КК и `objection-result` | Конкретный исполнитель |
| `sourceVersions` | `{documentId, version, contentSnapshot?}[]` | нет | см. 1.2 | `contentSnapshot` = `JSON.stringify({values, group})` только для `additional` |
| `registration` | `{status: Отправлена\|Зарегистрирована\|Возвращена, number?, date?, comment?}` | нет | `performRegistration` (ЕРСОП) | Для `account`, `counter-account`, `notification`, `counter-notification`, `additional`, `counter-additional` |
| `delivery` | `{sentAt, acknowledgedAt?, response?, attachments?, decision?: Подписан\|Подписан с возражениями\|Отказ от подписания, decidedAt?, decidedBy?, grounds?, decisionAttachments?}` | нет | `deliverDocument` | Направление объекту аудита (`deliverable(kind)`) |
| `informationRequest` | `InformationRequestCycle` | нет | `transitionInformationRequest` | Только `request`/`counter-request` |
| `preparation` | `{agreedAt?, qualityRequestedAt?, kvga?: {confirmerId, status: pending\|confirmed\|returned, at?, by?, comment?}, groupSignatures?: {personId, name, at}[]}` | нет | `preparationWorkflow.ts` | Состояние подготовительного маршрута |
| `main` | `{agreedAt?, groupRequestedAt?, groupSignatures?, confirmation?: {confirmerId, status, comment?, decidedAt?, sourceVersions?}, qualityRequestedAt?, approvalRequestedAt?}` | нет | `mainWorkflow.ts` | Состояние основного маршрута (`report`/`violations`/`evidence`) |
| `mainQuality` | `{expertSignedAt, expertId, submittedAt?}` | нет | `signMainQuality`, `submitMainQualityToHead` | Подпись эксперта КК2 |

### 2.9. Маршрут согласования (`shared/workflow/approvalRoute.ts`)

`ApprovalRoute`:

| Поле | Тип | Обяз. | Комментарий |
|---|---|---|---|
| `id` | uuid | да | |
| `documentId`, `documentVersionId` | string | да | `documentVersionId = "{doc.id}:v{n}"` |
| `moduleId?`, `caseId?`, `documentTitle?`, `caseTitle?`, `documentVersionLabel?` | string | нет | Контекст для inbox |
| `initiator` | `ApprovalPerson {id, name, role?, position?, department?}` | да | Инициатор не может быть согласующим |
| `mode` | `parallel \| sequential` | да | режим первой стадии |
| `stages` | `{id, mode, reviewerIds[]}[]` | нет | Многостадийный маршрут; отсутствие = одна стадия |
| `reviewers` | `ApprovalParticipant[]` (+`status`, `stageId`, `stageIndex`, `activatedAt`, `decidedAt`, `comment`) | да | без повторов |
| `signer` | `ApprovalParticipant` | нет | Финальный участник, отдельный от согласующих |
| `signerAction` | `sign \| approve` | нет | default `sign` (в ЭВГА всегда `approve`) |
| `status` | `review \| signing \| completed \| returned \| rejected \| superseded` | да | |
| `createdAt`, `updatedAt` | ISO | да | |
| `history` | `{id, action: submitted\|approve\|sign\|return\|reject\|supersede, actorId, actorName, documentVersionId, at, comment?, newDocumentVersionId?}[]` | да | `id = "{route.id}:event:{n}"` |
| `returned` / `rejected` | `{actorId, actorName, comment, at}` | нет | |
| `supersededByVersionId` | string | нет | |
| `execution` | `"local-demo"` | да | маркер демо; на сервере не нужен |

`ApprovalTask` (проекция `getApprovalTasks`): `id = "{route.id}:{action}:{personId}"`, `routeId`, `initiator`, `assignee`, `action: approve|sign|revise`, `participantRole: reviewer|signer|approver`, `status: waiting|pending|completed|returned|rejected|cancelled`, `createdAt`, `updatedAt`, `comment?`. Ошибки `ApprovalWorkflowError` с кодами `INVALID_ROUTE | FORBIDDEN | STALE_VERSION | INVALID_STATUS | ALREADY_DECIDED | COMMENT_REQUIRED` — хорошая основа для кодов ошибок DRF.

### 2.10. Требование о предоставлении сведений — `InformationRequestCycle`

`{state: sent|awaiting|received|review|overdue|accepted|refused, rounds: InformationRequestRound[]}`;
`InformationRequestRound = {id, sentAt, deadline?, acknowledgedAt?, response?: {at, by, text, attachments, refused?, legacy?}, review?: {at, by, decision: accepted|rejected|resend|refused, comment}, reviewStartedAt?}`.
Действия (`InformationRequestAction`): `send, acknowledge, provide, refuse, review, accept, reject, resend, mark-refused`. Срок `deadline` берётся из `values.general.deadline` (`datetime-local`); просрочка вычисляется на чтении (`informationRequestCycle(doc, now)`): для `request` → `overdue`, для `counter-request` → `refused`.

### 2.11. `Appeal` — рассмотрение возражений

| Поле | Тип | Откуда |
|---|---|---|
| `objectionId`, `version` | ссылка на активную версию документа `objections` | `getAppeal` |
| `receivedAt` | ISO | последняя подпись версии возражений |
| `expertId` | account id (`appeal-expert`) | `assignAppeal` (`appeal-head`) |
| `admission` | `{decision: Принято к рассмотрению\|Отказ в рассмотрении, at, by, reason, files, notifiedAt?}` | `recordAdmission` (`commission-chair`), `notifyAdmission` |
| `arguments` | `{rows: {violationId, textRu, textKz, files}[], at, by, submittedAt?, signedAt?, signedBy?, comment?}` | `saveAppealArguments` (автор дела), `decideArguments` (account `approver`) |

### 2.12. `ThirdPartyNotice` — третьи лица (ведёт роль `object`)

`{id, name, identification (ИИН/БИН, 12 цифр или пусто), violationIds[] (id строк реестра), noticeAt (date), noticeFiles[], recordedBy, receivedAt?, receiptFiles?, response?: {at, text, files, recordedBy, forwardedAt?, forwardingFiles?}}`.

### 2.13. Прочие вложенные структуры дела

* `amendments[]` — журнал применённых доп. поручений (см. 2.1).
* `notifications[]` — `{id, at, documentId, text, recipients: accountId[], readBy: accountId[]}`; адресаты вычисляются в `saveDocument` по статусу версии (согласующие с `pending`, `confirmerId`, участники группы без подписи, `approver`, все `quality`, все `object` и т.д.).
* `qualityAssignments` — по этапам `0|1|2`.
* `calendar` — праздники/рабочие даты/подтверждённые годы.
* `schedule` — действующие сроки.

### 2.14. Встречная проверка (дочернее дело)

Создаётся в `CounterChecks.tsx`: новое `AuditCase` с `parentCaseId`, `number = "{parent}/ВП-{n}"`, `personType`, `personBirthDate`, `entrepreneurName`, `counterQuestion`; документы — только `counter-*` (`creationBlock`: `Boolean(audit.parentCaseId) !== kind.startsWith("counter-")` → «Документ относится к другому виду дела»). Рабочие документы к встречным делам не применяются (`paperApplies`: `!audit.parentCaseId`). Объекты встречной проверки предварительно перечисляются в ИРПИ (`counterNeeded`, `counterBins[]`) и в плане (`plan.counterObjects[]`).

### 2.15. ИРПИ (`irpi`) — единственный документ без схемы в `documentForms`

Форма `components/IrpiForm.tsx` + `data/irpiForm.ts`. Ключи `values`:

| Ключ | Тип | Комментарий |
|---|---|---|
| `{key}Ru`, `{key}Kz` для `key ∈ legal, constituent, structure, seizure, previous, internal, budget, procurement, information, appeals` | string | 10 обязательных двуязычных полей `irpiSections` (6 разделов) |
| `accountingRu/Kz`, `commitmentsRu/Kz`, `paidActivitiesRu/Kz`, `budgetAdjustmentsRu/Kz`, `receivablesRu/Kz` | string | `financialIrpiSections` — опциональные, для фин. аудита |
| `expediencyRu/Kz` | string | Целесообразность |
| `start`, `end`, `periodStart`, `periodEnd` | date | Сроки и период (обязательны); переносятся в `audit.schedule` и `initialValues` всех последующих документов |
| `normsRu/Kz` | string | НПА → `program.general.norms` |
| `materials`, `risks`, `controls`, `materiality`, `questions` | `IrpiRow[]` | Строки по `IrpiRowKind`; `IrpiRow = {id, ru?, kz?, level?, indicator?, rating?, question?, budget?, from?, to?, amount?, files?}` |
| `previousAudits` | `ReferenceIrpiRow[]` | Результаты предыдущих аудитов (`previousAuditRows()` ищет активные отчёты по тому же БИН) — поля `number, authority, date, documentName, outcomeRu/Kz, sourceCaseId` |
| `jointObject` | `AuditObject` | Совместный орган |
| `counterNeeded`, `counterBins[]` | boolean, string[] | Потребность во встречных проверках |
| `specialists`, `specialistsReasonRu/Kz` | boolean, string | Привлечение специалистов |
| `permission`, `permissionDescriptionRu/Kz`, `permissionFiles[]` | boolean, string, Upload[] | Разрешительные документы |
| `calculationInputs_{compliance\|financial}`, `calculationResult_{…}` | объекты | Расчёт существенности (см. 6.1) |

Дополнительные поля строк `ReferenceIrpiRow` (`irpiRowLabels`): `method` («Метод исследования»), `balanceCurrency`, `registration`, `topic`, `subtopic`, `normsRu/Kz`.

### 2.16. Рабочие документы (`workingPapers.json`, `workingPapers.ts`)

Шаблон: `Paper = {id, number, act, title, blocks: ({type:"text", text} | {type:"table", rows: PaperCell[][], dataStart})[]}`,
`PaperCell = {text, colSpan, rowSpan, editable}`. 62 шаблона, 222 блока (158 текстовых, 64 таблиц), 2906 ячеек.
Состояние заполнения хранится в `values.paper`:

| Ключ | Тип | Комментарий |
|---|---|---|
| `applicability` | `Применяется \| Не применяется` | при «Не применяется» обязательны `reasonRu`, `reasonKz` |
| `start`, `end`, `periodFrom`, `periodTo` | date | |
| `completed` | boolean | «Подтвердите завершение рабочей формы» |
| `cells` | `Record<"t{table}-r{row}-c{cell}", string>` | `paperKey(table,row,cell)`; ответы на тестовые вопросы — только `Да\|Нет\|Нет ответа` |
| `extra` | `Record<tableIndex, number>` | Сколько строк добавлено сверх шаблона |

Стадия: `financial-rd-NN` при `number > 5` → `stage 1`, иначе `0`; `compliance-rd-*` → `0`. Код отображения `РД-{number}`.

### 2.17. Реестр нарушений (`violations`) — четыре коллекции в `values` (`violationRegistry.ts`, `registrySchemaVersion: 2`)

| Коллекция | Ключевые поля строки | Связи |
|---|---|---|
| `risks[]` | `id, riskType, riskObject, riskNumber, year, amount, budgetAmount, transfers, assets, questionReferences` | копия из `instruction.risks` |
| `riskQuestions[]` | `id, riskId, questionId, question` | пара (`riskId`,`questionId`) уникальна; `questionId` — id строки `program.questions` (через `printContext.sources.program` или `sourceVersions`) |
| `results[]` | `id, riskId, questionId, question, topic, hours, result (Не проверено\|В работе\|Нарушений не выявлено\|Нарушение выявлено), commentRu, commentKz` | ровно один на пару |
| `violations[]` | `id, resultId, riskId, questionId, question, riskType, riskObject, riskNumber, kind, violationType, consequence, principles, amount, recovered, restored, accounted, conformed, remaining, inefficientAmount, paragraph, npaRu, npaKz, remediation, descriptionRu, descriptionKz, files[]` + фин.: `balanceLine, balanceAmount, materiality, distorted, notDistorted, reportingType, materialityExcess` | `remaining = amount − (recovered+restored+accounted+conformed)`; `result.noViolations` вычисляется `finalizeRegistry` |

«Эффективный» реестр после рассмотрения возражений — `effectiveViolations(audit)`: строки со `status === "Отменено"` в `objection-result.decisions` исключаются, для «Отменено частично» `amount −= cancelled`. Именно на него опираются `prescription`, `response`, `objections`, `creationBlock`.

### 2.18. Исполнение (`shared/execution/execution.ts`, `executionItems.ts`) — проекция, не хранимая сущность

`ExecutionItem = {id, source: ExecutionSource, text, responsible?: {id?, name}, originalDueDate?, dueDate?, claimedStatus: not_submitted|partial|completed, confirmedStatus: open|in_review|partial|completed|cancelled|not_remediable, evidence[], responses[], history[], extensions?: {id, previousDueDate?, dueDate?, reason, status: proposed|approved|rejected, decidedAt?, decidedBy?, untilCourtDecision?, documentHref?}[], isDisputed?}`,
`ExecutionSource = {module: evga|sva|prof, caseId, caseTitle?, documentId, documentVersionId?, documentTitle, documentKind?, itemId, itemNumber?, caseHref?, documentHref?, itemHref?}`,
`id = createExecutionItemId(source) = "execution:{module}:{caseId}:{documentId}:{documentVersionId}:{itemId}"`.
Источники пунктов: активная версия `prescription` (`financial[]`, `procedural[]`) и `conclusion.recommendations[]`; ответы — версии `response` (`measures[]` по `violationId`, `recommendations[]` по `id`). `DeadlinePolicy = {warningDays?, calendar?: calendar|business, timeZone?, holidays?, weekendDays?}`.

`Deadline` (`modules/evga/deadlines.ts`) — `{label, source (ссылка на НПА), due?, completed?, estimated, rule}`, тоже вычисляемая проекция.

### 2.19. Сводка перечислений (кандидаты в `TextChoices`)

| Перечисление | Значения | Где |
|---|---|---|
| `DocStatus` | `Проект`, `Направлен на согласование КК`, `На согласовании`, `На утверждении`, `Согласован`, `На подтверждении КВГА`, `На подтверждении реестра`, `На подписании рабочей группой`, `Возвращен на доработку`, `Отклонен`, `Активный` | `types.ts` |
| `AuditCase.status` | `Открыто`, `Закрыто` | |
| `executionState` | `Проводится`, `Приостановлено`, `Отменено` | |
| `Stage` | `0`, `1`, `2` (`stageNames`: Подготовительный / Основной / Заключительный этап) | `documentMatrix.ts` |
| `Role` | 10 значений (2.4) | |
| `registration.status` | `Отправлена`, `Зарегистрирована`, `Возвращена` | |
| `delivery.decision` | `Подписан`, `Подписан с возражениями`, `Отказ от подписания` | |
| `qualityDecision` | `Без замечаний`, `С замечаниями` | |
| `kvga.status`, `confirmation.status` | `pending`, `confirmed`, `returned` | |
| `InformationRequestState` | `sent, awaiting, received, review, overdue, accepted, refused` | |
| `round.review.decision` | `accepted, rejected, resend, refused` | |
| `ApprovalRouteStatus` | `review, signing, completed, returned, rejected, superseded` | |
| `ApprovalParticipantStatus` | `waiting, pending, approved, signed, returned, rejected, cancelled` | |
| `ApprovalTaskStatus` | `waiting, pending, completed, returned, rejected, cancelled` | |
| `ApprovalMode` / `ApprovalSignerAction` | `parallel, sequential` / `sign, approve` | |
| `admission.decision` | `Принято к рассмотрению`, `Отказ в рассмотрении` | |
| `ExecutionClaimedStatus` / `ExecutionConfirmedStatus` | см. 2.18 | |
| `DeadlineKind` | `unspecified, upcoming, due_soon, due_today, overdue` (+ `closed, cancelled, not_remediable`) | |
| `personType` | `Юридическое лицо`, `Физическое лицо` | |
| `paper.applicability` | `Применяется`, `Не применяется` | |
| `resultStatuses` (реестр) | `Не проверено`, `В работе`, `Нарушений не выявлено`, `Нарушение выявлено` | `violationRegistry.ts` |
| `AuditFormat` | `traditional` («Традиционный аудит»), `electronic` («Электронный аудит») | `auditFormat.ts` |
| `DocumentView` | `form`, `print`, `sources` | `documentPresentation.ts` |


---

## 3. Каталог видов документов

### 3.1. Этапы и общие классификаторы видов (из `workflow.ts`, `documentStateMachine.ts`, `mainWorkflow.ts`, `preparationWorkflow.ts`)

| Классификатор | Виды | Смысл |
|---|---|---|
| `stageNames` | `0` Подготовительный этап, `1` Основной этап, `2` Заключительный этап | `AuditDocument.stage` |
| `requiresQuality(kind)` | `program, plan, assignment, instruction, violations, evidence, report, conclusion, prescription` | Отправка на маршрут только после заключения КК «Без замечаний» (кроме подготовительных/основных, где КК идёт по комплекту) |
| `isPreparationDocument` | `irpi, program, plan, assignment, instruction, counter-instruction` | Подготовительный маршрут: согласование по цепочке, КВГА-подтверждение поручения, КК1 по комплекту, утверждение |
| `isMainDocument` | `report, violations, evidence` | Основной маршрут: подписи группы под отчётом → согласование → подтверждение реестра → КК2 → утверждение → отправка объекту |
| `isQuality` | `quality1, quality2, quality3` | Заключения КК; владелец — назначенный эксперт; утверждает `quality-head` |
| `directActivation` | `claim-decisions, reply-law, obstruction, counter-obstruction, objections, weekly, account, counter-account, notification, counter-notification` + все рабочие документы | «Подписать и активировать» без маршрута (`activateDocument`) |
| `repeatableKinds` | `additional, request, obstruction, weekly, measurement, forward-up, forward-law, forward-abp, reply-up, reply-law, reply-abp, claim-invalid, claim-dishonest, claim-recover, claim-liquidation, claim-decisions, counter-additional, counter-request, counter-obstruction` | Можно создавать несколько экземпляров; остальные — «Документ уже создан.» |
| `deliverable` | `instruction, additional, request, report, violations, conclusion, obstruction, prescription, counter-instruction, counter-additional, counter-request, counter-act, counter-obstruction, objection-result` | Направляются объекту аудита (`deliverDocument`) |
| Регистрируемые в ЕРСОП (`performRegistration`) | `account, counter-account, notification, counter-notification, additional, counter-additional` | `registration.status`; отправка только из статуса `Активный` |
| `qualitySources(stage)` | 0: `irpi, program, plan, assignment, instruction`; 1: `report, violations, evidence`; 2: `conclusion, prescription` | Что попадает в `sourceVersions` заключения КК |
| Обязательный состав для создания `qualityN` | 0: `irpi, program, instruction`; 1: `report, violations, evidence`; 2: `conclusion` (+ `prescription`, если есть подтверждённые нарушения) | `creationBlock` |
| `amendmentTargets` | `program, plan, assignment, instruction, account, violations, evidence, report, counter-instruction, counter-account, counter-act` | Документы, которым доп. поручение создаёт новую версию |
| `printContext.sources` | `instruction, irpi, program, report, violations, conclusion` | Снимки исходных документов в печатном контексте |
| Без утверждающего в маршруте | `assignment`, `report` | `submitDocument`: `signer: undefined`; задание утверждает руководитель группы, отчёт — только согласуется |

Зависимости создания `dependencies` (`workflow.ts`; для подготовительных документов при создании **не** проверяются — там работает `preparationSubmissionBlock` при отправке):

```
program: [irpi]            plan: [program]            assignment: [program]      instruction: [program]
account: [instruction, quality1]   vap: [instruction]   additional: [instruction]   request: [instruction]   obstruction: [instruction]
objections: [report]       objection-result: [objections]     prescription: [conclusion]    notification: [quality3]
response: [prescription]   completion: [quality3, notification, response]
reply-up: [forward-up]     reply-law: [forward-law]   reply-abp: [forward-abp]
counter-account/-additional/-request/-obstruction: [counter-instruction]   counter-act: [counter-account]   counter-notification: [counter-act]
```
Правило: зависимость считается выполненной, если документ **активен** (`isActive`); если и текущий, и зависимый вид требуют КК — достаточно факта существования. Для `prescription`/`response` зависимость снимается, если `effectiveViolations` пуст.

Дополнительные условия `creationBlock` (кроме зависимостей): дело закрыто; `executionState === "Приостановлено"` (кроме `additional`); рабочий документ не того типа аудита; `parentCaseId` ↔ `counter-*`; для `stage > 0` — `audit.quality[0..stage-1]` все `true`; `account` требует `quality[0]`; `conclusion`/`prescription` требуют решения объекта по отчёту (`delivery.decision`), при возражениях — активный `objection-result` и повторный КК2, ссылающийся на него; `violations, report, request, counter-act, counter-request` требуют `registered(audit)` (зарегистрированная учётная карточка); `quality1` — `preparationQualityBlock` + `instruction.preparation.qualityRequestedAt`; `quality2` — `mainQualityBlock` + `violations.main.qualityRequestedAt`; `qualityN` — все `qualitySources` в статусе `Активный` или `Направлен на согласование КК`.

### 3.2. 36 документов основного дела (`docKinds`)

Колонки: **Код** — отображаемый код из `documentMatrix.ts` (не уникален, комментарий в исходнике: «Display codes are not unique IDs»); **Маршрут** — способ активации; **Схема** — секции/коллекции/полей/обязательных из дампа `formFor(kind, "Соответствие")` (в скобках — вариант для фин. аудита); **Предзаполнение** — `initialValues`.

| # | `kind` | Наименование | Этап | Код | КК | Маршрут | Повтор. | Объекту | ЕРСОП | Владелец | Схема | Ключевые секции/поля | Предзаполнение |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `irpi` | Информация о результатах предварительного изучения | 0 | 12 | источник КК1 | подготовительный | нет | нет | нет | auditor | своя форма (2.15) | 10 двуязычных разделов, сроки, строки `materials/risks/controls/materiality/questions/previousAudits`, `counterBins`, расчёт существенности | `printContext` |
| 2 | `program` | Программа аудита соответствия / Программа аудита финансовой отчетности | 0 | 55 | да | подготовительный | нет | нет | нет | auditor | 2/1/16/7 (2/1/13/9) | `general{purpose, norms}`, `questions[]` (14 полей: `question, registration, topic, subtopic, norms, indicator[4], budget, from, to, amount, budgetAmount, transfers, assets, method`; фин.: без бюджетных сумм, + `method[2]`, `balanceCurrency`), `total: amount` | `general.norms` ← `irpi.norms`, `questions` ← `program.questions ?? irpi.questions` |
| 3 | `plan` | План аудита | 0 | 33 | да | подготовительный | нет | нет | нет | auditor | 4/2/19/18 | `general{start,end,resources}`, `objects[]`(≥1: `bin, name, start, end, location, route, auditor`), `counterObjects[]`, `coverage{amount, materiality}` | `objects` ← объект дела, `counterObjects` ← `irpi.counterBins` через `catalogue`, `coverage.amount` = Σ`questions.amount` |
| 4 | `assignment` | Аудиторское задание | 0 | 88 | да | подготовительный; без утверждающего; далее «На подписании рабочей группой» → утверждает `leader` | нет | нет | нет | auditor | 2/1/16/10 (17) | `general{start,end,days}`, `questions[]`(≥1: `question, from, to, auditor, reviewFrom, reviewTo, days, submissionDate`+справочные) | `questions` ← программа |
| 5 | `instruction` | Поручение на проведение аудиторского мероприятия | 0 | 17 | да | подготовительный → КВГА (`sendInstructionToKvga`) → КК1 (`requestPreparationQuality`) → утверждение | нет | да (после регистрации карточки) | нет | auditor | 6/1/16/12 | `general{purpose}`, `duration`, `period`, `responsible{person}`, `risks[]`(`riskType[7], riskObject, riskNumber, year, amount…`, `total: amount`), `head{person}` | `general` ← цель дела, `duration/period` ← `schedule`, `risks: []` |
| 6 | `quality1` | Контроль качества (1 этап) | 0 | 55 | — | эксперт → маршрут → `quality-head` | нет | нет | нет | quality (`ownerId` = эксперт этапа 0) | 5/1/31/20 | `quality{basis, date, receivedAt, level[2], departmentReview, approverPosition, basisKz}`, `context{9 пунктов}`, `requirements{complianceRu/Kz, formComplianceRu/Kz, counterRu/Kz}`, `remarks[]`, `conclusion{decision[2], textRu/Kz}` | `context` ← `qualityContextValues`, `quality{basis, date, receivedAt, level "Первый уровень"}`; `sourceVersions` ← `qualitySources(0)` |
| 7 | `account` | Учетная карточка (ЕР СОП) | 0 | 12 | нет | прямая активация | нет | нет | **да** | auditor | 8/2/47/37 | `general{number, registeredAt, start, end, periodFrom, periodTo, scope, exceptional, objectType}`, `registration{goDate, department, basis, authority, investor→prosecutor, registrar, moratorium}`, `questions[]`(≥1), `subject{recipientBin, opf, ownership, address, businessType, size, oked…}`, `objects[]`(≥1), `unplanned{}`, `author{}`, `signer{}` | `general.number` ← номер дела, `subject` ← объект, `questions` ← программа (`questionRu`), `objects` |
| 8 | `vap` | Уведомление в ВАП | 0 | 12 | нет | маршрут | нет | нет | нет | auditor | 1/0/5/4 | `recipient{vapBin, commissionBin, number, date, description}` | — |
| 9 | `additional` | Дополнительное поручение | 0 | 33 | нет | маршрут → регистрация → (для «О внесении дополнений»/«Продление») `applyAmendment` | **да** | да (после регистрации) | **да** | auditor | 6/3/44/33, вкладки 4 | `order{type[5], suspendDate/resumeDate/extendDate (when), reason, responsible, effective, information, law, basis, notes}`, `program{purpose}`, `questions[]`, `objects[]`, `duration{4 даты}`, `risks[]` | `program` ← цель, `questions`, `objects` ← план, `duration`, `risks` ← поручение; `sourceVersions` ← `amendmentTargets` + `contentSnapshot` |
| 10 | `request` | Требование по предоставлению сведений | 0 | 33 | нет | маршрут; далее цикл `informationRequest` | **да** | да | нет | auditor | 2/1/5/3 | `general{deadline: datetime-local, date}`, `requested[]`(≥1: `name, period, description`) | — |
| 11 | `obstruction` | Акт о воспрепятствовании | 0 | 33 | нет | прямая активация | **да** | да | нет | auditor | 4/2/9/9 | `general{date, place, auditor}`, `obstructions[]`(≥1: `form, description`), `representatives[]`(≥1: `iin, name, position`), `measures{description}` | — |
| 12 | `report` | Аудиторский отчет / Аудиторский отчет финансовой отчетности | 1 | 55 | да (КК2 по комплекту) | основной: подписи группы → согласование (без утверждающего) → после КК2 отправка объекту (`send` переводит в `Активный`) → ознакомление → `sign/object/refuse` | нет | **да** | нет | auditor | 7/3/27/17 (9/3/34/22) | `general{start, end, periodFrom, periodTo, date, place, copies, attachmentPages}`, `officials[]`, `previous{text}`, `results{text}`, `questions[]`(≥1: `question, from, to, answer, documentDetails, noViolations`), `obstructions[]`, `measures{}`; фин.: + `circumstances{text}`, `auditResult{result[4], management, auditor, obstructionPresent}`, `opinion{basis, text}` | `general` ← сроки, `questions` ← программа; `sourceVersions` ← `program, instruction` |
| 13 | `violations` | Реестр нарушений | 1 | 55 | да (КК2) | основной: согласование → подтверждение реестра (`reestr-confirmer`) → КК2 → утверждение → объекту | нет | **да** | нет | auditor | 5/4/42/17 (49) | вкладки «Объекты риска» (`risks[]`≥1, `riskQuestions[]`) и «Результаты аудита» (`result{noViolations}`, `results[]`, `violations[]` 22/29 полей + файлы) | `risks` ← поручение, `registrySchemaVersion: 2`, пустые коллекции; `sourceVersions` ← `report` |
| 14 | `evidence` | Аудиторские доказательства | 1 | 55 | да (КК2) | основной: после согласования реестра; утверждение после активного реестра | нет | нет | нет | auditor | 2/1/8/8 | `general{date}`, `evidence[]`(`violationId, violationType, consequence, amount, evidence, documentDetails, source` + файлы) | `evidence` ← `effectiveViolations` (по одной строке на нарушение); `sourceVersions` ← `report, violations` |
| 15 | `quality2` | Контроль качества (2 этап) | 1 | 55 | — | `signMainQuality` (эксперт) → `submitMainQualityToHead` → утверждение `quality-head`; `canSubmit` = false | нет | нет | нет | quality | 8/3/64/28 | + `requirements{timelinessRu/Kz, measuresRu/Kz, recognition, document1..3}`, `coverage[]`(≥1: `indicator, question, reimbursement, restoration, procedural, paragraph, assessmentRu/Kz, violationId, npa`), `coverageSummary{textRu/Kz}`, `corrections[]`(`violationId, field, current, next, assessmentRu/Kz, question, riskType, riskObject, paragraph, npa, objectionAmount, acceptedMeasures`) | как `quality1`; `sourceVersions` ← `report, violations, evidence` (+ активный `objection-result` при повторном КК) |
| 16 | `weekly` | Еженедельный отчёт | 1 | 88 | нет | прямая активация | **да** | нет | нет | auditor | 2/1/10/9 | `general{from, to}`, `questions[]`(≥1: `question, from, to, auditor, result, plannedDays, actualDays, deviation`) | `questions` ← программа |
| 17 | `measurement` | Акт контрольного обмера | 1 | 34 | нет | маршрут | **да** | нет | нет | auditor | 3/2/10/10 | `representatives[]`(≥1), `general{place, date}`, `items[]`(≥1: `name, unit, reported, actual, price`) | — |
| 18 | `objections` | Возражения к аудиторскому отчету | 1 | 76 | нет | прямая активация (роль `object`); активация создаёт `audit.appeal` | нет | нет | нет | **object** | 2/1/11/11 | `general{submittedAt, method[3], place, applicant, identification, grounds, documents}`, `violations[]`(≥1: `violationId, violationType, amount, objection` + файлы) | `general{applicant ← object.ru, identification ← bin, submittedAt ← сегодня, method "Электронно"}`, `violations` ← `effectiveViolations` |
| 19 | `objection-result` | Результаты возражения к Аудиторскому отчету | 1 | 76 | нет | маршрут: согласующие — члены комиссии (`area: "appeal"`), утверждающий — `commission-chair`; `recallDocument` до первого согласования; `reassignReturnedDocument` руководителем | нет | **да** (отправляет `appeal-expert`) | нет | **appeal-expert** (`ownerId` = `appeal.expertId`) | 3/1/8/8 | `general{date, result[3]}`, `decisions[]`(≥1: `violationId, amount, status[3], cancelled, note`), `decision{description}` | `decisions` ← `objections.violations` c `cancelled: "0"`; `sourceVersions` ← версия возражений |
| 20 | `conclusion` | Аудиторское заключение | 2 | 55 | да (КК3) | маршрут | нет | **да** | нет | auditor | 4/1/8/7 | `general{periodFrom, periodTo, results}`, `conclusions{text}`, `recommendations[]`(`text, deadline`), `measures{description, deadline}` | `general.results` ← `report.results.text` (фин.: `report.opinion.text`) |
| 21 | `prescription` | Предписание на устранение нарушений | 2 | 55 | да (КК3) | маршрут | нет | **да** | нет | auditor | 3/2/23/12, вкладки 3 | `general{deadline, legalBasis, measures, procurementMeasures, liability, budgetCode, head}`, `financial[]`(`violationId, riskType, riskObject, paragraph, deadline, amount, recover, restoreWork, restoreAccounting`), `procedural[]`(… `affected`) | строки ← `effectiveViolations` по `kind` («Финансовые нарушения» → `financial`, иначе `procedural`) |
| 22 | `quality3` | Контроль качества (3 этап) | 2 | 55 | — | эксперт → маршрут → `quality-head` | нет | нет | нет | quality | 6/2/51/26 | + `requirements{measuresRu (обяз.), recognitionRu (обяз.), document1}`, `corrections[]` | как `quality1`; `sourceVersions` ← `conclusion, prescription` |
| 23 | `notification` | Талон-уведомление | 2 | 55 | нет | прямая активация | нет | нет | **да** | auditor | 3/1/22/16 | `general{location, place, recipient, end, result, protected, court, sent}`, `liability{npa, responsibility, activity, termination, summary, phone, notes}`, `npa[]`(`kind, article, part, paragraph, subparagraph, number, date`) | — |
| 24 | `forward-up` | Передача в вышестоящие органы | 2 | 55 | нет | маршрут | **да** | нет | нет | auditor | 1/0/4/4 | `general{letterNumber, recipient, letterDate, description}` | — |
| 25 | `reply-up` | Ответ от вышестоящих органов | 2 | 76 | нет | маршрут | **да** | нет | нет | auditor | 2/1/4/3 | `general{transfer: document<forward-up>}`, `answers[]`(≥1: `description, date, officials` + файлы) | — |
| 26 | `forward-law` | Передача в правоохранительный орган | 2 | 76 | нет | маршрут | **да** | нет | нет | auditor | 1/0/5/5 | `general{… + amount}` | — |
| 27 | `reply-law` | Ответ от правоохранительных органов | 2 | 76 | нет | прямая активация | **да** | нет | нет | auditor | 2/1/4/3 | `general{transfer: document<forward-law>}`, `answers[]` | — |
| 28 | `forward-abp` | Передача администраторам бюджетных программ | 2 | 76 | нет | маршрут | **да** | нет | нет | auditor | 1/0/5/5 | `general{… + amount}` | — |
| 29 | `reply-abp` | Ответ от администраторов бюджетных программ | 2 | 76 | нет | маршрут | **да** | нет | нет | auditor | 2/1/6/5 | `general{transfer: document<forward-abp>, letterNumber, sender}`, `answers[]` | — |
| 30 | `claim-invalid` | Иски о признании договора государственных закупок недействительными | 2 | 76 | нет | маршрут | **да** | нет | нет | auditor | 3/1/21/10 | `general{contract, number, date, protocolDate, protocolNumber, amount, claimDate, court, executor}`, `defendants[]`(≥1: `recipientBin, recipientName`), `enforcement{10 полей АИС ОИП}` | — |
| 31 | `claim-dishonest` | Иски о признании поставщика недобросовестным участником ГЗ | 2 | 76 | нет | маршрут | **да** | нет | нет | auditor | 1/0/5/4 | `general{recipientBin, recipientName, claimDate, court, executor}` | — |
| 32 | `claim-recover` | Иски о возмещении в бюджет выявленных сумм нарушений | 2 | 76 | нет | маршрут | **да** | нет | нет | auditor | 2/0/18/7 | `general{plaintiff, defendant, amount, claimDate, court, executor, demands, grounds}`, `enforcement{}` | — |
| 33 | `claim-liquidation` | Иски о принудительной ликвидации палаты оценщиков | 2 | 76 | нет | маршрут | **да** | нет | нет | auditor | 1/0/7/6 | `general{recipientBin, recipientName, claimDate, court, executor, demands, grounds}` | — |
| 34 | `claim-decisions` | Решения по искам | 2 | 76 | нет | прямая активация | **да** | нет | нет | auditor | 2/0/5/5 | `general{kind[4], claim: document<claim-*>}`, `decision{date, court, text}` | — |
| 35 | `response` | Ответ о принятых мерах | 2 | 55 | нет | маршрут; `assertExecutionResponseSave`; новая редакция после утверждения `createResponseRevision`/`reviseExecutionResponse` | нет | нет | нет | auditor **или object** (если создаёт объект) | 5/4/20/17 | `general{extension, extensionReason (when), deadline (when)}`, `discipline[]`, `measures[]`(`violationId, violationType, amount, accepted, status[4], date, letterNumber, letterDate, note` + файлы), `risks[]`(`riskObject, measure, done`), `recommendations[]`(`text, done` + файлы) | `measures` ← активное предписание (`accepted: "0"`), `recommendations` ← активное заключение; `sourceVersions` ← активные версии `prescription`/`conclusion` |
| 36 | `completion` | Справка о завершении | 2 | 55 | нет | маршрут; активация закрывает дело | нет | нет | нет | auditor | 2/0/5/5 | `general{shortcomings}`, `measures{measures, administrative, claims, other}` | — |

### 3.3. 7 документов встречной проверки (`counterDocKinds`; все `stage 0`, только для дел с `parentCaseId`)

| `kind` | Наименование | Код | Маршрут | Повтор. | Объекту | ЕРСОП | Схема | Отличия |
|---|---|---|---|---|---|---|---|---|
| `counter-instruction` | Поручение на проведение встречной проверки | 17 | подготовительный (без цепочки предшественников) → КВГА (при возврате статус остаётся `Согласован`) → утверждение (только КВГА-подтверждение, без КК) | нет | да (после регистрации карточки) | нет | 4/1/10/8: `period`, `duration`, `general{law, responsible, effective, direction}`, `questions[]`(≥1: `question, executor`) | `questions[0]` ← `counterQuestion ?? purposeRu`, `executor` ← `group[0]` |
| `counter-account` | Учетная карточка по встречной проверке | 12 | прямая активация | нет | нет | да | = `account` (8/2/47/37) | |
| `counter-additional` | Дополнительное поручение по встречной проверке | 33 | = `additional` | да | да | да | = `additional` | |
| `counter-request` | Требование по предоставлению сведений по встречной проверке | 33 | маршрут; цикл сведений: `send` сразу → `awaiting`, `provide` → `received`, просрочка → `refused` | да | да | нет | = `request` | |
| `counter-obstruction` | Акт об отказе в доступе по встречной проверке | 33 | прямая активация | да | да | нет | = `obstruction` | |
| `counter-act` | Акт встречной проверки | 55 | маршрут; объект может `sign/object/refuse` | нет | да | нет | 8/3/18/18: `object{description}`, `general{place, date}`, `questions[]`(≥1: `question, answer`), `period{4 даты}`, `participants[]`(`participation, name, position, from, to`), `results{text}`, `obstructions[]`, `measures{text}` | требует `registered` |
| `counter-notification` | Талон-уведомление по встречной проверке | 55 | прямая активация; регистрация закрывает дело | нет | нет | да | = `notification` | |

### 3.4. 62 рабочих документа (`workingDocKinds`, шаблоны в `data/workingPapers.json`)

| Группа | `kind` | Акт | Этап | Назначение |
|---|---|---|---|---|
| Фин. аудит, оценка рисков и существенности | `financial-rd-01` … `financial-rd-08` | `V1700015209` | 0 | РД-РСИ (риск существенных искажений, 2 таблицы), РД-ОРСК (44 тестовых вопроса), РД-ОНР (53), РД-ОРН, РД-РУС (расчёт уровня существенности), РД-ИВИ, «Определение уровня надежности», РД-АВ (выборка) |
| Денежные средства | `financial-rd-09` … `-14` | `V1700015209` | 1 | программа процедур, входящее/исходящее сальдо, тест СВК, свод ошибок, выводы |
| Финансовые инвестиции и обязательства | `financial-rd-15` … `-24` | | 1 | + бюджетные займы, займы полученные, вознаграждения, инвентаризация ЦБ |
| Запасы | `financial-rd-25` … `-32` | | 1 | + списание, инвентаризация |
| Дебиторская/кредиторская задолженность | `financial-rd-33` … `-38` | | 1 | |
| Долгосрочные активы | `financial-rd-39` … `-46` | | 1 | + ремонт/обслуживание, инвентаризация |
| Прочие активы и обязательства | `financial-rd-47` … `-52` | | 1 | |
| Чистые активы/капитал | `financial-rd-53` … `-58` | | 1 | |
| Оценка результатов | `financial-rd-59` | | 1 | РД-ОР (2 таблицы) |
| Аудит соответствия | `compliance-rd-02`, `-03`, `-04` | `V2200026715` | 0 | Оценка риска средств контроля (44 вопроса), неотъемлемого риска (50), аудиторская выборка |

Шаблоны применимы: `financial-*` — только при `isFinancialAudit(auditType)`, `compliance-*` — при `/соответств/i`; для встречных дел — никогда. Заполняются по `values.paper` (2.16), активируются напрямую, участвуют в КК как источники (`qualityPassed` не требует для них совпадения версии).

### 3.5. Связи между формами — `formLinks(audit, values)` и `selectFormLink`

| Ключ поля-ссылки | Источник вариантов | Подпись варианта | Поля, копируемые в строку при выборе |
|---|---|---|---|
| `violationId` | `values.violations ?? latestValues("violations").violations` | `Пункт {paragraph} · {violationType \| descriptionRu \| kind}` | `amount, violationType, consequence, kind, paragraph, npaRu, npaKz, question, riskType, riskObject, riskNumber`; если в строке есть `field` — также `current` |
| `riskId` | `values.risks ?? violations.risks ?? instruction.risks` | `{riskType} · {riskObject \| riskNumber}` | `riskType, riskObject, riskNumber` |
| `questionId` | `program.questions ?? values.questions` | `{registration \| №}. {question \| questionRu}` | `question, registration, topic, subtopic, normsRu, normsKz` |
| `resultId` | `values.results ?? violations.results` | `{№}. {question} · {result}` | `questionId, question, riskId, topic` |
| `field` (корректировки КК) | фиксированный список 11 полей реестра: `amount, recovered, restored, accounted, conformed, remaining, consequence, kind, paragraph, npaRu, remediation` | подпись поля | `current` ← значение выбранного нарушения |
| `transfer` (`type: "document"`, `sourceKind: forward-up/-law/-abp`) | документы дела указанного вида | | — |
| `claim` (`sourceKind: "claim-*"`) | документы дела видов `claim-*` | | — |

На сервере это означает: (а) API «варианты для поля» по делу, (б) при сохранении — проверка, что `violationId/riskId/questionId/resultId/transfer/claim` ссылаются на существующие строки/документы (сейчас частично делает `validateDocument`).

### 3.6. Что делает `applyAmendment` (приказ «О внесении дополнений» / «Продление проверки»)

Для каждого документа из `amendmentTargets` создаётся новая версия `Проект` с `sourceVersions = [{documentId: поручение, version}]`: `program/instruction/counter-instruction.general ← data.program`; `questions` для `program, assignment, report, account, counter-account, counter-act` ← `data.questions` (слияние по `id`); `objects` для `plan, account, counter-account`; `plan.coverage.amount` пересчитывается; `risks` для `instruction, counter-instruction, violations`; `general{start,end}` для `plan, assignment, report, account, counter-account, counter-act`; `duration/period` для поручений. При «Продление проверки» меняется только `end`. Обновляются `audit.purposeRu/Kz`, `audit.group`, `audit.schedule`, `audit.quality = [false,false,false]`, пишется `audit.amendments[]`.
Блокировки `amendmentBlock`: только автор/соавтор; поручение активно и зарегистрировано; тип приказа подходящий; версия ещё не применялась; нет документов `objections, objection-result, conclusion, prescription, completion`; все цели активны и их `contentSnapshot` совпадает с текущим содержимым.


---

## 4. Справочники, зашитые в `data/` и `forms/`

Колонка «→ catalogs» показывает, что должно стать таблицей справочника на бэкенде (в стиле `apps/catalogs` prof: `CodeNamedModel`/`OrderedCodeNamedModel` с `code`, `name`, `order`), а что остаётся `TextChoices`/константой кода. Указано сопоставление с таблицами старой n8n-схемы `surfk.*`, где оно очевидно из имени.

| № | Справочник | Где во фронте | Значения (примеры / полный список) | → catalogs |
|---|---|---|---|---|
| 1 | Этапы аудита | `stageNames` (`documentMatrix.ts`) | `Подготовительный этап`, `Основной этап`, `Заключительный этап` | `TextChoices`/`IntegerChoices` (`surfk.evga_document_stages`) |
| 2 | Виды документов | `docKinds` (36), `counterDocKinds` (7), `workingDocKinds` (62) | `{id, name, stage, code}` + производные флаги из 3.1 | **таблица** `EvgaDocumentType` (аналог `documents.DocumentType` prof; `surfk.evga_document_types`) с полями `code(kind), name_ru, name_kk?, stage, display_code, requires_quality, direct_activation, repeatable, deliverable, registrable, is_counter, is_working_paper, owner_role, order` |
| 3 | Виды оснований | `basisOptions` (6) | `По перечню объектов государственного аудита`; `По поручениям Президента Республики Казахстан`; `По вопросам, связанным с корректировкой технико-экономического обоснования`; `По результатам мониторинга данных ИС … с применением системы управления рисками` (`basisText`); `По обращениям физических и юридических лиц`; `По поручению акима` | **таблица** `BasisKind` (`surfk.control_reasons_types`) |
| 4 | Инициаторы | `initiatorOptions` (14) | `Комитет внутреннего гос.аудита`, `Поручение Администрации Президента РК`, `Поручение Правительства РК`, `Поручение Министерства финансов РК`, `Поручение ЦА КВГА (для территориальных подразделений)`, `Органы национальной безопасности`, `Органы внутренних дел РК`, `Генеральная прокуратура РК`, `Транспортная прокуратура РК`, `Военная прокуратура РК`, `Комитет государственных доходов (СЭР)`, `Юридические или физические лица`, `Депутатский запрос`, `Агентство РК по делам госслужбы и противодействию коррупции` | **таблица** `Initiator` (`surfk.check_initiators`) |
| 5 | Тип аудита | `auditTypeOptions` (`caseSearch.ts`) | `Соответствие`, `Фин. отчетность` (исторически полные названия; `isFinancialAudit` — regex) | **таблица** `AuditType` с флагом `is_financial` (`surfk.audit_types`) |
| 6 | Тип проверки | `checkTypeOptions` | `Плановый`, `Внеплановый` | `TextChoices` (`surfk.inspection_types`) |
| 7 | Вид проверки | `CaseForm.tsx` select | `Совместная` («Совместная проверка»), `Параллельная`, пусто | `TextChoices` |
| 8 | Формат аудита | `auditFormatLabels` | `traditional` → «Традиционный аудит», `electronic` → «Электронный аудит» | булево `electronic` (как сейчас) или `TextChoices` |
| 9 | ОПФ объекта | значения `AuditObject.opf` | `Государственное учреждение`, `Главное управление`, `Акционерное общество`; в `account.subject.opf` — текст | **таблица** `LegalForm` (`surfk.organizational_legal_forms`) |
| 10 | Регионы | `AuditObject.region` | `Астана`, `Карагандинская обл.`, `г. Алматы` | **таблица** `catalogs.Region` (есть в prof; `surfk.regions`) |
| 11 | Уровень риска объекта (СУР) | `AuditObject.risk` / `riskLevel()` | `Высокая`/`Средняя`/`Низкая` (объект) и `Высокий`/`Средний`/`Низкий` (рабочие документы: `<30`, `<70`, иначе) | **таблица** `RiskLevel` (`surfk.risk_levels`) — унифицировать род |
| 12 | Тип объекта риска | `riskFields.riskType` (7) | `Объявление по ГЗ`, `Договор по ГЗ`, `Финансово-хозяйственная деятельность`, `Расход бюджета`, `Финансовая отчетность`, `Объект контроля`, `Пункт плана по ГЗ` | **таблица** `RiskObjectType` (`surfk.risk_object_types`) |
| 13 | Вид нарушения | `violationFields.kind` (2) | `Финансовые нарушения`, `Процедурные нарушения` | `TextChoices` (определяет вкладку предписания) |
| 14 | Тип нарушения (классификатор) | `violationFields.violationType.suggestions` | `1.1.1.2. — Неполное зачисление в бюджет неналоговых поступлений … повлекшее недополучение доходов бюджета` | **таблица** `ViolationType` с иерархическим кодом (`surfk.offense_type`) |
| 15 | Тип последствия нарушения | `consequence` (7) | `Повлияло на итоги государственных закупок`, `Не повлияло на итоги государственных закупок`, `Подлежит возмещению в республиканский бюджет`, `Подлежит возмещению в местный бюджет`, `Подлежит восстановлению путем выполнения работ, оказания услуг, поставки товаров`, `Подлежит восстановлению путем отражения по учету`, `Не подлежит устранению` | **таблица** `ConsequenceType` |
| 16 | Принципы | `principles.suggestions` | `Принцип результативности` | **таблица** `AuditPrinciple` (мало данных) |
| 17 | Статус нарушения (устранение) | `remediation` (5, фин. +2) | `Подлежит устранению`, `Не подлежит устранению`, `Устранено`, `Частично устранено`, `Не устранено`, `Устранено частично` | `TextChoices` — **устранить дубль** «Частично устранено»/«Устранено частично» (см. 8) |
| 18 | Показатель аудита | `questionFields.indicator` (4) | `Эффективность`, `Экономичность`, `Результативность`, `Продуктивность` | **таблица** `AuditIndicator` |
| 19 | Метод исследования | `method` (2) | `Сплошная`, `Выборочная` | `TextChoices` (`surfk.sampling_methods`) |
| 20 | Тип приказа (доп. поручение) | `additional.order.type` (5) | `Приостановление проверки`, `Возобновление проверки`, `Отмена проверки`, `О внесении дополнений в приказ`, `Продление проверки` | `TextChoices` — влияет на `executionState`/закрытие/`applyAmendment` |
| 21 | Способ подачи возражения | `objections.general.method` (3) | `Электронно`, `Лично`, `По почте` (по почте — обязателен файл-подтверждение) | `TextChoices` |
| 22 | Результат рассмотрения возражения | `objection-result.general.result` (3) / `decisions.status` (3) | `Принято`, `Принято частично`, `Отклонено` / `Подтверждено`, `Отменено`, `Отменено частично` | `TextChoices` |
| 23 | Статус меры в ответе | `response.measures.status` (4) | `Не устранено`, `Устранено частично`, `Устранено`, `Не подлежит устранению` | `TextChoices` |
| 24 | Тип искового заявления | `claim-decisions.kind` (4) | `О признании договора недействительным`, `О признании поставщика недобросовестным`, `О возмещении в бюджет`, `О ликвидации палаты оценщиков` | `TextChoices` (1:1 с видами `claim-*`) |
| 25 | Уровень КК / решение КК | `quality.level` (2), `conclusion.decision` (2) | `Первый уровень`, `Второй уровень` / `Без замечаний`, `С замечаниями` | `TextChoices` |
| 26 | Результат фин. аудита (мнение) | `financialReport.auditResult.result` (4) | `Отчет без оговорки`, `Отчет с оговоркой`, `Отрицательное мнение`, `Отказ от выражения мнения` | `TextChoices` |
| 27 | Тип отчётности | `reportingType` (2) | `Финансовая отчетность`, `Бюджетная отчетность` | `TextChoices` |
| 28 | Статус результата вопроса (реестр) | `resultStatuses` (4) | `Не проверено`, `В работе`, `Нарушений не выявлено`, `Нарушение выявлено` | `TextChoices` |
| 29 | Пункты заключения КК | `qualityHeadings` (16) | 1 «Наименование объекта…» … 16 «Выводы и рекомендации» | константа/`QualityHeading` таблица для печати; заполнение по этапам (`deferred` в `qualityPrintData`) |
| 30 | Разделы ИРПИ | `irpiSections` (6 разделов/10 полей), `financialIrpiSections` (5), `rowTitles`, `irpiRowLabels` | ключи `legal, constituent, structure, seizure, previous, internal, budget, procurement, information, appeals, accounting, commitments, paidActivities, budgetAdjustments, receivables` | **таблица** `IrpiSectionTemplate` (или JSON-схема ИРПИ в справочнике форм) |
| 31 | Шаблоны рабочих документов | `workingPapers.json` (62), акты `V1700015209`, `V2200026715` | блоки `text`/`table`, ячейки `editable` | **таблица** `WorkingPaperTemplate {code, number, act (FK catalogs.NormativeAct), title, stage, audit_type, blocks JSON}` |
| 32 | Сотрудники / аккаунты / роли | `people` (6), `accounts` (~25), `Role` (10) | должности `Аудитор`, `Начальник отдела`, `Приглашённый специалист`; организации `КВГА МФ РК`, `Комитет`, `Экспертная организация` | `accounts.User` + Keycloak-роли; `catalogs.Department`/`GovernmentBody` (prof); должности — таблица `Position` (`surfk.positions`, `surfk.employees`, `surfk.evga_roles`) |
| 33 | Реестр объектов аудита и перечень | `catalogue` (8), `objectRegistry` (9), `plannedDemoObjects` (4), `plannedBasisFor(bin)` | БИН, наименования ru/kz, руководитель, ОПФ, АБП, адрес, регион, риск, балл | **таблицы** `AuditObject` + `AnnualPlanEntry` (`surfk.audit_objects`, `surfk.annual_plans`, `surfk.plan_objects`) |
| 34 | Подписи состояний требования/исполнения | `informationRequestLabels` (7), `STATUS_LABELS`, `CLAIMED_LABELS`, `EXECUTION_MODULE_LABELS` | см. 2.10, 2.18 | `TextChoices` labels |
| 35 | Нормативные сроки | `auditDeadlines()` (`deadlines.ts`) | КК: `№ 392, пп. 129–131` (2/3/5/7/10/20 раб. дн.); отчёт объекту `№ 413, п. 16; № 392, п. 99` (1–2 дня до окончания); возражения `№ 392, пп. 101–102` (10 дн.); третьи лица `№ 392, п. 101-1` (2 и 5 дн.); обоснования `№ 392, п. 133` (3 дн.); рассмотрение возражений `Закон о гос. аудите ст. 58-4` (30 дн.), отказ `ст. 58-3` (5 дн.), оформление `ст. 58-5` (2 дн.); заключение `№ 413, п. 20` (3) / `№ 392, п. 107` (10); направление `№ 413, п. 22; № 392, п. 108` (1); талон `№ 413, п. 14; № 392, п. 113` (3); меры при неисполнении `№ 413, п. 29` (5) | **таблица** `DeadlineRule {code, label, source_act (FK NormativeAct), days, calendar, anchor_event}` + `catalogs.NormativeAct` (есть в prof) |
| 36 | Сроки КК по уровню/этапу | `qualityDays()` | 2-й уровень → 20; этап 0 → 2; этап 2 → 3; этап 1: фин. 10, с согласованием ведомством 7, иначе 5 | часть `DeadlineRule` |
| 37 | Производственный календарь | `AuditCase.calendar` | `holidays[]`, `workingDates[]`, `confirmedYears[]` | **таблица** `ProductionCalendarDay {date, is_working, year_confirmed}` (глобальная, не на дело) |
| 38 | Пороги существенности РД | `workingPapers.materiality()` | `{Низкий: 90, Средний: 75, Высокий: 50}` % от уровня существенности; `riskLevel`: `<30` Низкий, `<70` Средний | константы расчёта (версионировать вместе с актом) |
| 39 | Фильтры поиска дел | `emptyFilters`, `extraFields` (`caseSearch.ts`) | `number, date, rnn, bin, name, type, checkType, opf, electronic, org, author, coauthor, status, document` | параметры `filters.py` DRF (`rnn` и `coauthor` сейчас не реализованы) |
| 40 | Демо-данные | `sampleScenario`, `seedCases`, `demoScenario.ts`, `financialDemoValues.ts`, `DEMO_USER`, `MAIN_MENU_URL` | | **не переносить** в модель; `MAIN_MENU_URL` → настройка |

---

## 5. Правила валидации и блокировки, которые нужно перенести на сервер

Все правила ниже сейчас выполняются только в браузере; фронт может продолжать показывать их для UX, но сервер обязан повторять их в `services/` (комментарий в `approvalRoute.ts`: «A production service must repeat all authorization and version checks»). Формулировки сообщений — из исходников.

### 5.1. Универсальные проверки полей формы (`forms/validation.ts`: `fieldError`, `datesError`, `validateDocument`)

| Правило | Условие | Сообщение |
|---|---|---|
| Обязательность | `required && type !== "boolean"`; для `bilingual` — оба `{key}Ru` и `{key}Kz`; поле проверяется только если `visibleField` (условие `when`) | `Заполните поле` |
| Число | `type === "number"` → конечное неотрицательное (запятая допускается) | `Укажите неотрицательное число` |
| БИН/ИИН | `type === "object"` или ключ `iin`/`identification` → `^\d{12}$` | `Номер должен содержать 12 цифр` |
| Даты | пары `start/end`, `from/to`, `periodFrom/periodTo`, `reviewFrom/reviewTo` | `Дата окончания не может быть раньше даты начала` |
| Частичные суммы | `budgetAmount, assets, recover, restoreWork, restoreAccounting, cancelled, accepted` ≤ `amount` | `Частичная сумма не может превышать общую сумму` |
| Трансферты | `transfers ≤ budgetAmount` | `Трансферты не могут превышать бюджетные средства` |
| Возмещение | `recover + restoreWork + restoreAccounting ≤ amount` | `Общая сумма возмещения и восстановления превышает сумму нарушения` |
| Минимум строк | `section.collection && records.length < section.min` | `{title}: добавьте не менее {min} записей` |
| Расчёты | есть `calculationInputs_*` с данными, но нет `calculationResult_*` | `Выполните расчёт после изменения его исходных данных` |
| Рабочая группа | `form.group && !v.group.length` | `Добавьте участника рабочей группы` |
| Один руководитель | `group.filter(leader).length > 1` | `В рабочей группе может быть только один руководитель` |
| Задание | `assignment` и `group.length < 2` | `Аудиторское задание составляется для группы из двух и более аудиторов` |
| Вложения | `assertAttachmentRetention`: из непроектной версии нельзя удалить ни один `Upload.id` (обход `attachments` и всех `values`) | `Удалять вложения можно только в статусе «Проект»…` |

### 5.2. Правила по видам документов (`validateDocument`, `validateIrpiForReview`, `validateWorkingPaper`, `registryValidation`)

| Вид | Правило |
|---|---|
| `irpi` | все 10 полей `irpiSections` в Ru и Kz, даты `start, end, periodStart, periodEnd`, непустая группа → иначе `Заполните обязательные поля перед согласованием`; `start ≤ end`, `periodStart ≤ periodEnd` |
| рабочие документы | `applicability` обязательна; при «Не применяется» — `reasonRu` и `reasonKz`; даты периода/сроков и их порядок; `completed`; хотя бы одна заполненная ячейка, если в шаблоне есть `editable`; каждый тестовый вопрос (`riskAnswerKeys`) отвечен `Да/Нет/Нет ответа`; группа непуста |
| `qualityN` | `sourceVersions` непусты (`Укажите документы, переданные на контроль качества`); `quality.level ∈ {Первый уровень, Второй уровень}`; эксперт не входит в `audit.group` (`Контроль качества проводит сотрудник, не участвовавший в этом аудите`) |
| `violations` | `registryValidation`: программа содержит вопросы; уникальные `id` во всех 4 коллекциях; уникальные пары (`riskId`,`questionId`) в `riskQuestions` и `results`; каждая связь ссылается на существующий риск/вопрос и имеет ровно один результат; каждый результат имеет связь; «Нарушений не выявлено» несовместимо с нарушениями; при отправке: все результаты завершены, `hours ≥ 0`, `commentRu/Kz`, «Нарушение выявлено» ⇒ ≥1 нарушение; каждое нарушение связано с результатом/риском/вопросом; `remainingAmount ≥ 0`; у каждого риска выбраны вопросы |
| `evidence` / `report` | версия реестра из `sourceVersions` существует; при наличии документа доказательств — у каждого нарушения есть строка с `files` и `documentDetails` (`Нарушение {paragraph}: приложите доказательство с реквизитами документа`); доказательство не ссылается на отсутствующее нарушение |
| `report` | перечень и порядок `questions` совпадают с программой (`Перечень и последовательность вопросов отчёта должны совпадать с программой аудита`) |
| `objections` | `violationId` уникальны и существуют в `effectiveViolations` с той же суммой; `submittedAt` — корректная дата не в будущем (`assertPastDate`); при `method === "По почте"` — вложение обязательно |
| `objection-result` | для `ownerRole === "appeal-expert"` — `appealSubmissionBlock` (назначен исполнитель, есть решение «Принято к рассмотрению», обоснования подписаны); каждый оспоренный пункт рассмотрен ровно один раз; ссылки на оспоренные нарушения; `amount` = исходной, `cancelled ≤ amount`; `Подтверждено` ⇒ `cancelled = 0`; `Отменено` ⇒ `cancelled = amount`; `Отменено частично` ⇒ `0 < cancelled < amount` |
| `prescription` | содержит **все** `effectiveViolations` ровно по одному разу и ничего лишнего; суммы совпадают |
| `response` | у мер со статусом ≠ «Не устранено» есть файлы (`Приложите документы, подтверждающие принятые меры`) |
| `completion` | `completionBlock`: ответ подтверждает текущие версии предписания/заключения; по каждому пункту ровно одна мера с той же суммой; при «Устранено» `accepted ≥ recover + restoreWork + restoreAccounting`; нет мер вне предписания; все меры `Устранено`/`Не подлежит устранению`; все рекомендации отмечены `done`; `accepted ≤ amount` |

### 5.3. Правила дела (`caseRules.validateCase`)

БИН 12 цифр; плановый объект должен быть в `catalogue`; цель Ru и Kz; ≥1 основание; ≥1 участник группы; ≤1 руководитель; при `Совместная` — `jointObject`.

### 5.4. Правила жизненного цикла и полномочий

| Область | Функция | Ключевые правила |
|---|---|---|
| Создание документа | `creationAccessBlock`, `createDocument`, `creationBlock` | дело закрыто; `objection-result` создаёт только назначенный `appeal-expert`; аудитор — только автор/соавтор (`canAuthorCase`); КК — назначенный эксперт (`qualityAssignmentBlock`); `objections` — только `object`; `response` — `auditor` или `object`; остальные роли — запрет; неповторяемый вид — один экземпляр; зависимости 3.1 |
| Удаление | `deleteDocument` | только владелец, одна версия, статус `Проект`, на документ нет ссылок (`sourceVersions` или упоминание id в `values`), нет созданных по зависимости документов |
| Редактирование | `canEdit` | роль = `ownerRole`; статус `Проект`/`Возвращен на доработку`; нет активного маршрута; маршрут не `rejected`; нет `main.groupRequestedAt`/`mainQuality.expertSignedAt` |
| Отправка на КК | `sendDocumentToQuality` | только `requiresQuality` и не подготовительный/основной; из `canEdit` |
| Отправка на маршрут | `submitDocument`, `canSubmit` | для `requiresQuality` (кроме подготовительных/основных) — `qualityDecision === "Без замечаний"`; согласующие без повторов; утверждающий обязателен кроме `assignment`/`report`; проверка ролей `routeReviewer`/`routeApprover` (возражения — комиссия/председатель; КК — `quality-head`, для остальных `quality-head` запрещён); `quality2` через `submitMainQualityToHead` |
| Решения по маршруту | `approveDocument`, `returnDocument`, `rejectDocument`, `decideApprovalRoute` | `expectedVersion` = текущая; только назначенный участник в статусе `pending`; `return`/`reject` требуют комментарий; инициатор не согласует свой документ; повторное решение запрещено; после всех согласующих у подготовительных/основных — `Согласован` (+`agreedAt`) |
| Активация напрямую | `activateDocument` | только `directActivation`, `canSubmit`, `ownerId` |
| Новые редакции | `createNextVersion`, `createReturnedRevision`, `createRejectedRevision`, `revise*` | только владелец; старый маршрут → `superseded`; сбрасываются `signatures, approvalRoutes, registration, delivery, informationRequest, quality*` |
| Подготовительный маршрут | `preparationSubmissionBlock`, `preparationReferencesBlock`, `preparationApprovalBlock`, `sendInstructionToKvga`, `decideInstructionKvga`, `sendPreparationForApproval`, `signAssignmentGroup`, `approveAssignmentGroup`, `requestPreparationQuality` | предшественники согласованы (`irpi → program → plan/assignment/instruction`); ссылки на их версии актуальны; КВГА подтверждает поручение (`kvga` роль, `pending`); утверждение только после КК1 «Без замечаний» по актуальным версиям и утверждения предшественников; задание подписывают все участники, утверждает `leader` |
| Основной маршрут | `mainSubmissionBlock`, `mainReferencesBlock`, `mainConfirmationBlock`, `mainQualityBlock`, `mainQualityConclusionBlock`, `mainApprovalBlock`, `mainDeliveryBlock`, `requestReportGroupSignatures`, `signReportGroup`, `sendRegistryToConfirmer`, `decideRegistryConfirmation`, `requestMainQuality`, `requestMainApproval` | КК1 пройден по актуальным версиям; отчёт подписан всей группой (`auditor`/`invited-specialist`); реестр после согласованного отчёта; доказательства после согласованного реестра; подтверждение реестра (`reestr-confirmer`) фиксирует версии комплекта; КК2 по подтверждённому комплекту; утверждение доказательств после активного реестра; отправка объекту после КК2 и активных реестра/доказательств |
| КК2 | `signMainQuality`, `submitMainQualityToHead`, `reviseMainQuality`, `mainQualityVersionBlock` | подпись назначенного эксперта при заполненных `decision`/`textRu`; прямая отправка `quality-head`; смена эксперта создаёт новую версию, старая подпись сохраняется (`assignQualityExpert`) |
| Назначение эксперта КК | `assignQualityExpert`, `canAssignQualityExpert` | только `quality-head`; при замене — причина; уведомления |
| Регистрация ЕРСОП | `performRegistration` | только `auditor`; только регистрируемые виды; статус `Активный`; `send` один раз; `accept`/`return` только из `Отправлена`; возврат требует комментарий и переводит в `Возвращен на доработку`; регистрация доп. поручения меняет `executionState`, добавляет `basis`, продлевает `schedule.end`; регистрация `counter-notification` закрывает дело |
| Направление объекту | `deliverDocument`, `deliverable` | отправляет автор/соавтор (для `objection-result` — владелец-эксперт); поручения — после регистрации карточки; доп. поручение — после регистрации; объект: `acknowledge` один раз, `respond` — текст или файл, `sign/object/refuse` только для `report/violations/counter-act` и один раз; для отчёта решение только после ознакомления; `object/refuse` — обоснование, `refuse` — файл; аудитор может зафиксировать `refuse` за объект |
| Требование о сведениях | `informationRequestActions`, `transitionInformationRequest` | автомат 2.10; объект: `acknowledge` (из `sent`), `provide/refuse` (из `awaiting`); автор: `send`, `review`, `accept/reject/resend`, `resend/mark-refused` после просрочки; обоснование обязательно для `refuse/reject/resend/mark-refused`; срок > времени отправки |
| Возражения / апелляция | `assignAppeal`, `recordAdmission`, `notifyAdmission`, `saveAppealArguments`, `decideArguments`, `recallDocument`, `reassignReturnedDocument` | роли `appeal-head`, `commission-chair`, `approver`; обоснования по каждому пункту на двух языках с файлами; сроки 10 раб. дн. на подачу (`appealFilingDue`) |
| Третьи лица | `recordNoThirdParties`, `addThirdParty`, `recordThirdPartyEvent`, `assertPastDate` | только `object` после `report.delivery.acknowledgedAt`; ИИН/БИН 12 цифр; `violationIds` существуют без повторов; хронология дат (`noticeAt ≥ acknowledgedAt`, `receivedAt ≥ noticeAt`, `response.at ≥ receivedAt`, `forwardedAt ≥ response.at`, все не в будущем); файлы обязательны |
| Доп. поручения | `amendmentBlock`, `applyAmendment` | см. 3.6 |
| Соавторы | `assignCoauthor` | только account `approver`; не автор; без дублей |
| Ответ о мерах | `assertExecutionResponseSave`, `createResponseRevision` | замороженные версии неизменяемы; отклонённую нельзя переотправить; активная только при завершённом маршруте |
| Конкурентность | `saveDocument` (stale-проверки), `mainCurrentBlock`, `preparationCurrentBlock`, `assertVersion (STALE_VERSION)`, `expectedVersion` | версия не ниже сохранённой; история/подписи/маршруты сохранённой версии не потеряны; подписанное содержимое (`values, attachments, group`) при наличии `main`/`mainQuality` неизменно; прошлые версии read-only (`Предыдущие версии документов доступны только для чтения`) |
| Печать/представление | `documentPresentation` | не правило данных — можно оставить на клиенте |

Рекомендация: перенести всё из 5.1–5.4 в Python-сервисы (`apps/evga_documents/services/{forms,registry,preparation,main,quality,delivery,registration,requests,appeals,third_parties,amendments,execution}.py`), возвращая ошибки с кодами как в `ApprovalWorkflowError`; на фронте сохранить `validation.ts` только как предварительную подсказку.

---

## 6. Расчёты и печать/PDF

### 6.1. Расчёты (что и где считается)

| Расчёт | Функция | Формула / правило | Где хранится результат | Сервер? |
|---|---|---|---|---|
| Существенность (аудит соответствия) | `complianceMateriality(coverage)` | `coverage × 0.02`, `coverage > 0` | `irpi.values.calculationResult_compliance` `{at, mode, input, output}` | да — расчёт детерминированный, но результат подписывается в документе; сервер должен пересчитывать и сверять |
| Существенность (фин. аудит) | `financialMateriality(balance, investments)` | `base = balance − investments`, `materiality = base × 0.02`; `0 ≤ investments ≤ balance` | `calculationResult_financial` | да |
| Аудиторский риск | `auditRisk(inherent, control, detection)` | `misstatement = IR×CR/100`, `audit = IR×CR×DR/10000`, все 0..100 | `calculationResult_risk` (`financial-rd-01`, `-04`) | да |
| Остаточная совокупность | `residualPopulation(general, lowRisk, restricted)` | `general − lowRisk − restricted`, исключения не превышают совокупность | `calculationResult_residual` (прочие РД) | да |
| Режим расчёта по виду | `AuditCalculations.tsx` | `irpi` → `financial`/`compliance`; `financial-rd-01/-04` → `risk`; `financial-rd-05` → `financial`; иначе `residual` | | правило конфигурации |
| Балл риска РД | `riskScore(answers)` | доля «Нет» среди «Да/Нет» × 100, 2 знака | не хранится (вычисляется из `paper.cells`) | да (для отчётности) |
| Уровень риска / порог существенности | `riskLevel(percent)`, `materiality(base, percent, risk)` | `<30` Низкий, `<70` Средний; `value = base×percent/100`, `threshold = value × {90,75,50}%` | | да |
| Остаток нарушения | `remainingAmount(row)` | `amount − (recovered+restored+accounted+conformed)`, ≥ 0 | `violations[].remaining` (денормализовано `linkedViolation`) | да |
| Эффективный реестр | `effectiveViolations(audit)` | исключение «Отменено», уменьшение суммы на `cancelled` при частичной отмене | не хранится | да — основа предписания/ответа |
| Итоги секций | `section.total` (`amount`) в `program.questions`, `instruction.risks`, `violations.risks/violations`, `prescription.financial/procedural`; `plan.coverage.amount = Σ questions.amount` | суммирование `numberValue` | `coverage.amount` хранится; остальное на лету | сервер при печати/API |
| Флаг «нарушения не выявлены» | `finalizeRegistry` | все результаты «Нарушений не выявлено» и нет нарушений | `result.noViolations` | да |
| Статус исполнения пункта | `executionItems.confirmedStatus` | ровно одна мера; сумма совпадает; `Не подлежит устранению` → `not_remediable`; `Устранено` и `accepted ≥ recover+restoreWork+restoreAccounting` → `completed`; иначе `partial`/`open`; при маршруте ответа → `in_review` | проекция | да — в стиле `PrescriptionItem.status` prof |
| Продление срока | `executionItems` | утверждённое: `response.general.extension && deadline > originalDueDate`; предложенное — из проекта ответа | проекция | да |
| Нормативные дедлайны | `auditDeadlines`, `addWorkingDays`, `workingDate`, `qualityDays`, `appealFilingDue` | рабочие дни по календарю (`Asia/Almaty`), правила 4.35–4.36 | проекция (`estimated`, если год не подтверждён) | да |
| Статусы сроков исполнения | `getDeadlineStatus`, `getExecutionDeadlineStatus` | календарные/рабочие дни, `warningDays` не задан по умолчанию | проекция | клиент (чистая функция) + сервер для отчётов |
| Номера | `nextCaseNumber`, `documentSequence`, `ВП-n`, `УЧ-…` | см. 1.2 | | **только сервер** (последовательности) |

### 6.2. Печать и PDF

| Компонент | Что делает | Вывод |
|---|---|---|
| `printContext.ts` | При создании версии в `values.printContext` кладётся снимок дела (`object, purposeRu/Kz, bases, auditType, checkType, checkKind, electronic, schedule, number, group, author, createdAt`) и последних версий `instruction, irpi, program, report, violations, conclusion` (`{id, number, createdAt, version, values}` без вложенного `printContext`) | Снимок дела нужен и на сервере (данные дела мутируют). Снимки документов заменить FK на их версии (`DocumentSourceVersion`), т.к. версии неизменяемы — экономия объёма JSON |
| `components/referencePrintData.ts` | Помощники печати: `printAudit` (дело из снимка), `printSource` (значения источника по снимку/`sourceVersions`), `printPerson`, `printGroup`, `printFiles` (обход `values` за `Upload`), `printBasis`, `printPeriods` (каскад `general → duration/period → v → instruction → irpi → schedule`), `printBilingual`, `questionName`, `linkedViolation`, `printAmount`, `printSum` | Логику каскадов перенести в серверный сборщик печатного контекста |
| `components/ReferencePrintForm.tsx` (1976 строк) | Эталонные печатные формы для `irpi, program, plan, assignment, instruction, conclusion, report (+фин.), violations, prescription, …` (двуязычные, `language: ru\|kz`, приложения `annexes`, блок утверждения для `irpi, program, plan, assignment, conclusion`) | Это и есть спецификация печатных форм; на сервере — шаблоны (DOCX/HTML→PDF) |
| `components/QualityPrintForm.tsx` + `qualityConclusion.qualityPrintData` | Печать заключения КК по 16 пунктам `qualityHeadings`, отложенные пункты по этапам, `approverPosition` по умолчанию «Руководитель управления контроля качества» | шаблон на сервере |
| `components/DocumentPrintForm.tsx` | Универсальная печать по схеме формы для остальных видов | серверный генератор «по схеме» |
| `pdfExport.ts` | Клиентская конвертация DOM печатной формы (`.evga-reference-print, .quality-print, .evga-document-print`) в PDF через `pdfmake` (A4, поля 20 мм, шрифт LiberationSerif из `assets/fonts`, таблицы с `colSpan/rowSpan`, нумерация страниц, `data-print-orientation`, `data-print-page-break`); «No document data is sent to a server» | **Для юридически значимых документов PDF надо генерировать на сервере** (единый шаблон, хранение в MinIO рядом с версией, ЭЦП). Клиентский экспорт можно оставить как «черновик/предпросмотр» |

Рекомендация по разделению:

* **Сервер**: сборка печатного контекста версии (снимок дела + значения версий-источников + справочники), генерация PDF/DOCX по шаблонам (WeasyPrint/`docxtpl` — в prof документы тоже «printable», `DocumentType.is_printable`), хранение сформированного файла как `core.Attachment` с `kind = "print_form"`, все расчёты 6.1, дедлайны, номера.
* **Клиент**: рендер форм по схеме, предпросмотр печатной формы, `getDeadlineStatus`/фильтры реестра исполнения (чистые функции из `shared/execution`), локальный `pdfExport` как fallback.


---

## 7. Предложение маппинга на Django-модели в стиле prof

### 7.1. Принципы, взятые из `saq-prof-control-demo/backend`

* Все модели наследуют `core.TimeStampedModel` (`id = UUIDField(primary_key)`, `created_at`, `updated_at`, `created_by FK User`).
* Статусы — `models.TextChoices` с кодом в UPPER_SNAKE и русской подписью (`DocumentStatus.DRAFT = "DRAFT", "Проект"`), переопределения подписей по типу документа — словарь `_STATUS_LABEL_OVERRIDES` + `document_status_label()`.
* Справочники — отдельное приложение `catalogs` с абстрактными `CodeNamedModel` / `OrderedCodeNamedModel`; типы документов — таблица `DocumentType` с флагами (`creation_mode`, `is_printable`, `integration`, `requires_acknowledgement`, `is_implemented`) и `normative_act FK`.
* Вложения — `core.Attachment` (GenericFK, `kind: AttachmentKind`, `file`, `original_name`, `size`, `mime`, `checksum`); журнал — `core.AuditEvent` (append-only, GenericFK, `action`, `status_from/to`, `actor`, `actor_role`, `reason`); нумерация — `core.NumberSequence` (`key`, `scope`, `pattern`, `current_value`) + `core.IssuedNumber`.
* Дело ссылается на свои документы, у документа — «шапка» (`ControlDocument`: статус, даты, подписи, `attachments = GenericRelation`) и детали в `OneToOne`-таблицах по типу (`NoticeDetails`, `AppointmentActDetails`…); статус дела **вычисляется** сервисом (`compute_status`).
* Исполнение — `execution.PrescriptionItem` со свойством `status`, `ExecutionSubmission(+Item)`, `ExecutionDecision` (`RELEASE`/`EXTEND`, `new_due_date`).
* Интеграция ЕРСОП — `ersop.ErsopPackage/Item/Exchange` с `JSONField request_payload/response_payload`.
* `JSONField` в prof используется точечно (`reporting.values`, `risk.source_values`, `ersop.*_payload`) — для содержимого форм и внешних payload'ов.
* Слои: `models.py` → `services/*.py` (доменные операции и исключения) → `api/{serializers,views,filters,urls}.py` (DRF, пагинация `{count,next,previous,results}`, действия как `@action`: `sign`, `acknowledge`, `attachments`).

### 7.2. Состав приложений для ЭВГА

| Приложение | Содержимое |
|---|---|
| `apps/catalogs` (расширить) | `AuditType`, `BasisKind`, `Initiator`, `RiskObjectType`, `ViolationType`, `ConsequenceType`, `AuditIndicator`, `AuditPrinciple`, `LegalForm`, `RiskLevel`, `DeadlineRule`, `ProductionCalendarDay`; переиспользовать `Region`, `Department`, `GovernmentBody`, `NormativeAct` |
| `apps/evga_objects` | `AuditObject`, `AnnualPlanEntry` (перечень на год) |
| `apps/evga_cases` | `AuditCase`, `CaseBasis`, `CaseParticipant`, `CaseCoauthor`, `QualityAssignment`, `CaseAmendment`, `CaseNotification`, `NotificationRead` |
| `apps/evga_documents` | `EvgaDocumentType`, `WorkingPaperTemplate`, `IrpiSectionTemplate`, `FormSchema`, `AuditDocument`, `DocumentVersion`, `VersionParticipant`, `DocumentSignature`, `DocumentSourceVersion`, `DocumentRegistration`, `DocumentDelivery`, `KvgaConfirmation`, `RegistryConfirmation`, проекции `AuditQuestion`, `RiskObject`, `QuestionResult`, `Violation`, `EvidenceItem`, `PrescriptionItem`, `Recommendation`, `ResponseMeasure` |
| `apps/evga_workflow` | `ApprovalRoute`, `ApprovalStage`, `ApprovalParticipant`, `ApprovalEvent` (+ сервис `approval_tasks` = порт `getApprovalTasks`) |
| `apps/evga_requests` | `InformationRequestRound` |
| `apps/evga_appeals` | `Appeal`, `AppealArgument`, `ThirdPartyNotice` |
| `apps/evga_execution` | сервисы проекции `ExecutionItem` (порт `executionItems.ts`), `ExecutionExtension` (при необходимости материализации) |
| `apps/evga_ersop` | `RegistrationExchange` (по образцу `ersop.ErsopExchange`) |

### 7.3. Модели (эскиз в стиле prof)

Ниже — существенные поля; `TimeStampedModel` подразумевается. Имена полей — snake_case от полей фронта.

```python
# apps/evga_cases/models.py
class CaseStatus(models.TextChoices):
    OPEN = "OPEN", "Открыто"
    CLOSED = "CLOSED", "Закрыто"

class ExecutionState(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", "Проводится"
    SUSPENDED = "SUSPENDED", "Приостановлено"
    CANCELLED = "CANCELLED", "Отменено"

class CheckType(models.TextChoices):
    PLANNED = "PLANNED", "Плановый"
    UNPLANNED = "UNPLANNED", "Внеплановый"

class CheckKind(models.TextChoices):
    NONE = "", "—"
    JOINT = "JOINT", "Совместная"
    PARALLEL = "PARALLEL", "Параллельная"

class PersonType(models.TextChoices):
    LEGAL = "LEGAL", "Юридическое лицо"
    NATURAL = "NATURAL", "Физическое лицо"

class AuditCase(TimeStampedModel):
    number = CharField(max_length=32, unique=True)              # 30101-YY-NNNNN / {parent}/ВП-N
    parent = ForeignKey("self", null=True, on_delete=PROTECT, related_name="counter_cases")
    object = ForeignKey("evga_objects.AuditObject", on_delete=PROTECT)
    object_snapshot = JSONField(default=dict)                    # AuditObject на момент создания (для печати)
    joint_object = ForeignKey("evga_objects.AuditObject", null=True, on_delete=PROTECT, related_name="+")
    audit_type = ForeignKey("catalogs.AuditType", on_delete=PROTECT)   # is_financial
    check_type = CharField(choices=CheckType.choices)
    check_kind = CharField(choices=CheckKind.choices, blank=True)
    electronic = BooleanField(default=False)                     # auditFormat
    dsp = BooleanField(default=False)
    purpose_ru = TextField(); purpose_kk = TextField()
    author = ForeignKey(User, on_delete=PROTECT, related_name="+")
    status = CharField(choices=CaseStatus.choices, default=CaseStatus.OPEN)
    execution_state = CharField(choices=ExecutionState.choices, default=ExecutionState.IN_PROGRESS)
    schedule_start = DateField(null=True); schedule_end = DateField(null=True)
    period_from = DateField(null=True); period_to = DateField(null=True)
    quality_stage_passed = ArrayField(BooleanField(), size=3, default=[False,False,False])  # либо вычислять (qualityPassed)
    document_sequence = PositiveIntegerField(default=0)         # или core.NumberSequence(scope=case)
    # встречная проверка
    person_type = CharField(choices=PersonType.choices, blank=True)
    person_birth_date = DateField(null=True)
    entrepreneur_name = CharField(max_length=255, blank=True)
    counter_question = TextField(blank=True)
    third_parties_reviewed_at = DateTimeField(null=True); third_parties_reviewed_by = FK(User, null=True)
    third_parties_none = BooleanField(null=True); third_parties_reason = TextField(blank=True)
    attachments = GenericRelation("core.Attachment")
    closed_at = DateTimeField(null=True)

class CaseBasis(TimeStampedModel):        # Basis[]
    case = FK(AuditCase, related_name="bases"); number = CharField(64)
    kind = FK("catalogs.BasisKind", null=True); kind_text = CharField(500, blank=True)   # приказы из additional
    initiator = FK("catalogs.Initiator", null=True); initiator_text = CharField(500, blank=True)
    date = DateField(); source_document_version = FK("evga_documents.DocumentVersion", null=True)
    attachments = GenericRelation("core.Attachment")

class CaseParticipant(TimeStampedModel):  # group: Person[]
    case = FK(AuditCase, related_name="participants"); user = FK(User, null=True)
    full_name = CharField(255); position = CharField(255); organization = CharField(255)
    is_leader = BooleanField(default=False); order = PositiveSmallIntegerField(default=0)
    # constraint: не более одного is_leader на дело (validateCase / validateDocument)

class CaseCoauthor(TimeStampedModel):     # coauthors[]
    case = FK(AuditCase, related_name="coauthors"); user = FK(User); assigned_by = FK(User)

class QualityAssignment(TimeStampedModel):  # qualityAssignments[stage]
    case = FK(AuditCase, related_name="quality_assignments"); stage = PositiveSmallIntegerField(choices=Stage.choices)
    expert = FK(User); assigned_by = FK(User); reason = TextField(blank=True)
    # unique(case, stage) — история замен в core.AuditEvent

class CaseAmendment(TimeStampedModel):    # amendments[]
    case = FK(AuditCase, related_name="amendments"); order_version = FK("evga_documents.DocumentVersion")
    applied_by = FK(User); targets = JSONField()   # [{document_id, version}]

class CaseNotification(TimeStampedModel): # notifications[]
    case = FK(AuditCase, related_name="notifications"); document = FK("evga_documents.AuditDocument", null=True)
    text = CharField(500); recipients = ManyToManyField(User, related_name="+")
class NotificationRead(models.Model):     # readBy[]
    notification = FK(CaseNotification, related_name="reads"); user = FK(User); read_at = DateTimeField(auto_now_add=True)
```

```python
# apps/evga_documents/models.py
class Stage(models.IntegerChoices):
    PREPARATION = 0, "Подготовительный этап"
    MAIN = 1, "Основной этап"
    FINAL = 2, "Заключительный этап"

class OwnerRole(models.TextChoices):
    AUDITOR = "auditor", "Аудитор"; QUALITY = "quality", "Эксперт КК"
    OBJECT = "object", "Объект аудита"; APPEAL_EXPERT = "appeal-expert", "Сотрудник апелляции"

class EvgaDocumentType(TimeStampedModel):   # docKinds + counterDocKinds + workingDocKinds (справочник)
    code = CharField(max_length=32, unique=True)          # kind: "irpi", "counter-act", "financial-rd-05"
    name_ru = CharField(255); name_ru_financial = CharField(255, blank=True); name_kk = CharField(255, blank=True)
    display_code = CharField(16)                          # "12", "55", "РД-5" (не уникален)
    stage = PositiveSmallIntegerField(choices=Stage.choices); order = PositiveSmallIntegerField()
    requires_quality = BooleanField(); direct_activation = BooleanField(); repeatable = BooleanField()
    deliverable = BooleanField(); registrable = BooleanField(); is_counter = BooleanField(); is_working_paper = BooleanField()
    workflow = CharField(choices=[("preparation","Подготовительный"),("main","Основной"),("quality","КК"),("route","Маршрут"),("direct","Прямая активация")])
    default_owner_role = CharField(choices=OwnerRole.choices)
    has_working_group = BooleanField()                    # form.group
    dependencies = ManyToManyField("self", symmetrical=False, blank=True)   # dependencies map
    normative_act = FK("catalogs.NormativeAct", null=True)
    legacy_code = CharField(16, blank=True)               # n8n: M5-IPI, M6-PA, M7-POR, M8-PLAN, M9-AZ, M17-AO, M18-RNS/M18-RNAFO, M19-AD, M20-VOZ, M23-RVO, M24-AZK, M25-PRED, M26-TU, M28-OPM, M43-VK

class FormSchema(TimeStampedModel):          # documentForms + referenceForms как данные (версионируемо по НПА)
    document_type = FK(EvgaDocumentType); audit_type = FK("catalogs.AuditType", null=True)  # null = любой
    version = PositiveSmallIntegerField(); effective_from = DateField()
    schema = JSONField()      # {sources, group, tabs, sections:[{key,title,collection,min,attachments,total,tab,fields:[{key,label,type,required,options,suggestions,sourceKind,when}]}]}

class WorkingPaperTemplate(TimeStampedModel):  # workingPapers.json
    document_type = OneToOneField(EvgaDocumentType); number = PositiveSmallIntegerField()
    act = FK("catalogs.NormativeAct"); title = CharField(500); blocks = JSONField()

class DocumentStatus(models.TextChoices):
    DRAFT = "DRAFT", "Проект"
    SENT_TO_QUALITY = "SENT_TO_QUALITY", "Направлен на согласование КК"
    IN_REVIEW = "IN_REVIEW", "На согласовании"
    IN_APPROVAL = "IN_APPROVAL", "На утверждении"
    AGREED = "AGREED", "Согласован"
    KVGA_CONFIRMATION = "KVGA_CONFIRMATION", "На подтверждении КВГА"
    REGISTRY_CONFIRMATION = "REGISTRY_CONFIRMATION", "На подтверждении реестра"
    GROUP_SIGNING = "GROUP_SIGNING", "На подписании рабочей группой"
    RETURNED = "RETURNED", "Возвращен на доработку"
    REJECTED = "REJECTED", "Отклонен"
    ACTIVE = "ACTIVE", "Активный"

class AuditDocument(TimeStampedModel):
    case = FK(AuditCase, related_name="documents"); document_type = FK(EvgaDocumentType, on_delete=PROTECT)
    stage = PositiveSmallIntegerField(choices=Stage.choices); number = CharField(64)     # {case}/NN
    author = FK(User); sequence = PositiveSmallIntegerField()
    # constraint: unique(case, document_type) если not repeatable — проверка в сервисе (createDocument)

class DocumentVersion(TimeStampedModel):
    document = FK(AuditDocument, related_name="versions"); version = PositiveSmallIntegerField()
    status = CharField(choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    owner_role = CharField(choices=OwnerRole.choices); owner = FK(User, null=True)
    values = JSONField(default=dict)                 # содержимое по FormSchema (+ paper, calculationInputs_*, calculationResult_*, registrySchemaVersion)
    print_context = JSONField(default=dict)          # снимок дела; снимки документов — через DocumentSourceVersion
    quality_decision = CharField(choices=QualityDecision.choices, blank=True); quality_conclusion = TextField(blank=True)
    # preparation / main / mainQuality — типизированные столбцы
    agreed_at = DateTimeField(null=True); group_requested_at = DateTimeField(null=True)
    quality_requested_at = DateTimeField(null=True); approval_requested_at = DateTimeField(null=True)
    expert_signed_at = DateTimeField(null=True); expert = FK(User, null=True, related_name="+"); expert_submitted_at = DateTimeField(null=True)
    row_version = PositiveIntegerField(default=0)    # оптимистическая блокировка (expectedVersion / "Документ изменился")
    attachments = GenericRelation("core.Attachment")
    class Meta: constraints = [UniqueConstraint(fields=["document","version"], name="evga_documentversion_natural_key")]

class VersionParticipant(TimeStampedModel):   # version.group (снимок рабочей группы версии)
    version = FK(DocumentVersion, related_name="participants"); user = FK(User, null=True)
    full_name = CharField(255); position = CharField(255); organization = CharField(255); is_leader = BooleanField(); order = SmallInt

class SignatureKind(models.TextChoices):
    ROUTE = "ROUTE", "Решение по маршруту"; GROUP = "GROUP", "Подпись участника рабочей группы"
    ACTIVATION = "ACTIVATION", "Подписано и активировано"; EXPERT = "EXPERT", "Подпись эксперта КК"
class DocumentSignature(TimeStampedModel):    # signatures[], preparation.groupSignatures, main.groupSignatures
    version = FK(DocumentVersion, related_name="signatures"); user = FK(User); role = CharField(32)
    kind = CharField(choices=SignatureKind.choices); signed_at = DateTimeField(); signature_payload = TextField(blank=True)  # ЭЦП

class DocumentSourceVersion(TimeStampedModel):  # sourceVersions[]
    version = FK(DocumentVersion, related_name="sources"); source_version = FK(DocumentVersion, related_name="+")
    content_snapshot_hash = CharField(64, blank=True)   # amendmentSnapshot → SHA-256 вместо полного JSON
    class Meta: unique_together = [("version", "source_version")]

class RegistrationStatus(models.TextChoices):
    SENT = "SENT", "Отправлена"; REGISTERED = "REGISTERED", "Зарегистрирована"; RETURNED = "RETURNED", "Возвращена"
class DocumentRegistration(TimeStampedModel):   # registration (ЕРСОП)
    version = OneToOneField(DocumentVersion, related_name="registration")
    status = CharField(choices=RegistrationStatus.choices); number = CharField(64, blank=True); date = DateTimeField(null=True); comment = TextField(blank=True)

class DeliveryDecision(models.TextChoices):
    SIGNED = "SIGNED", "Подписан"; SIGNED_WITH_OBJECTIONS = "SIGNED_WITH_OBJECTIONS", "Подписан с возражениями"; REFUSED = "REFUSED", "Отказ от подписания"
class DocumentDelivery(TimeStampedModel):       # delivery (объекту аудита)
    version = OneToOneField(DocumentVersion, related_name="delivery")
    sent_at = DateTimeField(); sent_by = FK(User); acknowledged_at = DateTimeField(null=True)
    response = TextField(blank=True); decision = CharField(choices=DeliveryDecision.choices, blank=True)
    decided_at = DateTimeField(null=True); decided_by = FK(User, null=True); grounds = TextField(blank=True)
    attachments = GenericRelation("core.Attachment")   # kind: RESPONSE / DECISION_ATTACHMENT

class ConfirmationStatus(models.TextChoices):
    PENDING = "PENDING", "Ожидает"; CONFIRMED = "CONFIRMED", "Подтверждено"; RETURNED = "RETURNED", "Возвращено"
class KvgaConfirmation(TimeStampedModel):       # preparation.kvga
    version = OneToOneField(DocumentVersion, related_name="kvga_confirmation"); confirmer = FK(User)
    status = CharField(choices=ConfirmationStatus.choices); decided_at = DateTimeField(null=True); comment = TextField(blank=True)
class RegistryConfirmation(TimeStampedModel):   # main.confirmation
    version = OneToOneField(DocumentVersion, related_name="registry_confirmation"); confirmer = FK(User)
    status = CharField(choices=ConfirmationStatus.choices); decided_at = DateTimeField(null=True); comment = TextField(blank=True)
    source_versions = ManyToManyField(DocumentVersion, related_name="+")   # confirmation.sourceVersions

# --- проекции строк JSON (пересобираются сервисом при сохранении версии; row_id = id строки в values) ---
class Violation(TimeStampedModel):              # values.violations[]
    version = FK(DocumentVersion, related_name="violations"); row_id = UUIDField()
    result_row_id = UUIDField(null=True); risk_row_id = UUIDField(null=True); question_row_id = UUIDField(null=True)
    kind = CharField(choices=ViolationKind.choices); violation_type = FK("catalogs.ViolationType", null=True); violation_type_text = CharField(500)
    consequence = FK("catalogs.ConsequenceType", null=True); remediation = CharField(choices=RemediationStatus.choices)
    amount = DecimalField(18, 2); recovered = Decimal; restored = Decimal; accounted = Decimal; conformed = Decimal; remaining = Decimal
    paragraph = CharField(32); npa_ru = TextField(); npa_kk = TextField(); description_ru = TextField(); description_kk = TextField()
    risk_type = CharField(255); risk_object = CharField(500); risk_number = CharField(64); question = TextField()
    class Meta: unique_together = [("version", "row_id")]
class RiskObject(...)        # values.risks[]        (row_id, risk_type FK, risk_object, risk_number, year, amount…)
class AuditQuestion(...)     # program.values.questions[] (row_id, question, registration, topic, subtopic, indicator, from, to, amount…)
class QuestionResult(...)    # values.results[]      (row_id, risk_row_id, question_row_id, result, hours, comment_ru/kk)
class EvidenceItem(...)      # evidence.values.evidence[] (row_id, violation_row_id, document_details, source)
class PrescriptionItem(...)  # prescription.values.financial[]/procedural[] (row_id, violation_row_id, section, deadline, amount, recover, restore_work, restore_accounting, affected)
class Recommendation(...)    # conclusion.values.recommendations[] (row_id, text_ru/kk, deadline)
class ResponseMeasure(...)   # response.values.measures[]/recommendations[] (row_id, violation_row_id | recommendation_row_id, status, accepted, date, letter_number, letter_date, done)
```

```python
# apps/evga_workflow/models.py  (порт shared/workflow/approvalRoute.ts)
class ApprovalMode(TextChoices): PARALLEL = "parallel", "Параллельно"; SEQUENTIAL = "sequential", "Последовательно"
class SignerAction(TextChoices): SIGN = "sign", "Подписать"; APPROVE = "approve", "Утвердить"
class ApprovalRouteStatus(TextChoices): REVIEW="review","На согласовании"; SIGNING="signing","На подписании"; COMPLETED="completed","Завершён"; RETURNED="returned","Возвращён"; REJECTED="rejected","Отклонён"; SUPERSEDED="superseded","Заменён"
class ApprovalParticipantStatus(TextChoices): WAITING="waiting","Ожидает"; PENDING="pending","Активно"; APPROVED="approved","Согласовано"; SIGNED="signed","Подписано"; RETURNED="returned","Возвращено"; REJECTED="rejected","Отклонено"; CANCELLED="cancelled","Отменено"

class ApprovalRoute(TimeStampedModel):
    document_version = FK(DocumentVersion, related_name="approval_routes"); initiator = FK(User)
    mode = CharField(choices=ApprovalMode.choices); signer_action = CharField(choices=SignerAction.choices, default=SignerAction.APPROVE)
    status = CharField(choices=ApprovalRouteStatus.choices); superseded_by = FK(DocumentVersion, null=True, related_name="+")
    returned_comment = TextField(blank=True); rejected_comment = TextField(blank=True)
class ApprovalStage(TimeStampedModel): route = FK(ApprovalRoute, related_name="stages"); order = SmallInt; mode = CharField(choices=ApprovalMode.choices)
class ApprovalParticipant(TimeStampedModel):
    route = FK(ApprovalRoute, related_name="participants"); stage = FK(ApprovalStage, null=True); user = FK(User)
    is_signer = BooleanField(default=False); order = SmallInt; status = CharField(choices=ApprovalParticipantStatus.choices)
    activated_at = DateTimeField(null=True); decided_at = DateTimeField(null=True); comment = TextField(blank=True)
    class Meta: unique_together = [("route", "user")]     # «Согласующие не должны повторяться»
class ApprovalEvent(models.Model):   # route.history[] — append-only, как core.AuditEvent
    route = FK(ApprovalRoute, related_name="events"); action = CharField(choices=[submitted, approve, sign, return, reject, supersede])
    actor = FK(User); at = DateTimeField(); comment = TextField(blank=True); new_document_version = FK(DocumentVersion, null=True)
# ApprovalTask — не таблица: сервис approval_tasks.for_user(user) (порт getApprovalTasks/getPendingApprovalTasks)
```

```python
# apps/evga_requests/models.py
class InformationRequestState(TextChoices): SENT="sent","Направлено объекту: ожидается ознакомление"; AWAITING="awaiting","Ожидание сведений"; RECEIVED="received","Ответ получен: ожидает рассмотрения"; REVIEW="review","Сведения на проверке у аудитора"; OVERDUE="overdue","Срок предоставления сведений истёк"; ACCEPTED="accepted","Сведения приняты аудитором"; REFUSED="refused","Предоставление сведений завершено отказом"
class ReviewDecision(TextChoices): ACCEPTED="accepted","Принято"; REJECTED="rejected","Отклонено"; RESEND="resend","Повторно направлено"; REFUSED="refused","Отказ"
class InformationRequestRound(TimeStampedModel):
    version = FK(DocumentVersion, related_name="request_rounds"); order = SmallInt
    sent_at = DateTimeField(); deadline = DateTimeField(null=True); acknowledged_at = DateTimeField(null=True)
    response_at = DateTimeField(null=True); response_by = FK(User, null=True); response_text = TextField(blank=True); response_refused = BooleanField(default=False)
    review_started_at = DateTimeField(null=True); review_at = DateTimeField(null=True); review_by = FK(User, null=True)
    review_decision = CharField(choices=ReviewDecision.choices, blank=True); review_comment = TextField(blank=True)
    attachments = GenericRelation("core.Attachment")
# state вычисляется сервисом (informationRequestCycle) с учётом now — хранить не нужно, но можно кешировать в DocumentVersion
```

```python
# apps/evga_appeals/models.py
class AdmissionDecision(TextChoices): ACCEPTED="ACCEPTED","Принято к рассмотрению"; REFUSED="REFUSED","Отказ в рассмотрении"
class Appeal(TimeStampedModel):
    case = OneToOneField(AuditCase, related_name="appeal"); objection_version = FK(DocumentVersion); received_at = DateTimeField()
    expert = FK(User, null=True); admission_decision = CharField(choices=AdmissionDecision.choices, blank=True)
    admission_at = DateTimeField(null=True); admission_by = FK(User, null=True); admission_reason = TextField(blank=True); admission_notified_at = DateTimeField(null=True)
    arguments_at = DateTimeField(null=True); arguments_by = FK(User, null=True); arguments_submitted_at = DateTimeField(null=True)
    arguments_signed_at = DateTimeField(null=True); arguments_signed_by = FK(User, null=True); arguments_comment = TextField(blank=True)
    attachments = GenericRelation("core.Attachment")    # admission.files
class AppealArgument(TimeStampedModel):    # arguments.rows[]
    appeal = FK(Appeal, related_name="arguments"); violation_row_id = UUIDField(); text_ru = TextField(); text_kk = TextField(); attachments = GenericRelation("core.Attachment")
class ThirdPartyNotice(TimeStampedModel):  # thirdParties[]
    case = FK(AuditCase, related_name="third_parties"); name = CharField(500); identification = CharField(12, blank=True)
    violation_row_ids = ArrayField(UUIDField())   # или M2M на Violation
    notice_at = DateField(); recorded_by = FK(User); received_at = DateField(null=True)
    response_at = DateField(null=True); response_text = TextField(blank=True); response_recorded_by = FK(User, null=True); forwarded_at = DateField(null=True)
    attachments = GenericRelation("core.Attachment")   # kinds: NOTICE / RECEIPT / RESPONSE / FORWARDING
```

Справочники (`apps/catalogs`, все на `OrderedCodeNamedModel` с `name_ru`/`name_kk`): `AuditType(is_financial)`, `BasisKind`, `Initiator`, `RiskObjectType`, `ViolationType(code иерархический, parent)`, `ConsequenceType`, `AuditIndicator`, `AuditPrinciple`, `LegalForm`, `RiskLevel`, `DeadlineRule(source_act FK NormativeAct, days, calendar, anchor)`, `ProductionCalendarDay(date unique, is_working, source)`, `IrpiSectionTemplate(key, title, order, audit_type null)`.

Нумерация (`core.NumberSequence`): `key="evga_case", scope="30101", pattern="30101-{yy}-{seq}"`; `key="evga_document", scope=<case uuid>, pattern="{case}/{seq:02d}"`; `key="evga_counter_case", scope=<parent uuid>, pattern="{case}/ВП-{seq}"`; `key="evga_registration", pattern="УЧ-{doc}"` (заглушка до интеграции ЕРСОП).

### 7.4. JSONField vs колонки — что куда и почему

| Данные | Решение | Обоснование |
|---|---|---|
| Содержимое форм (`values` по `formFor`) | **`DocumentVersion.values JSONField`** | 105 видов, ≈900 полей, схема уже декларативна и меняется вместе с НПА; фронт рендерит по схеме; prof хранит содержимое отчётных форм так же (`reporting.values`). Серверная валидация — по `FormSchema` (порт `fieldError/datesError`) |
| Идентификация, статус, владелец, даты этапов маршрута | колонки `DocumentVersion` | фильтры списков/инбокса, индексы, FK на пользователей |
| Строки, на которые ссылаются другие документы (`violations`, `risks`, `results`, `questions`, `evidence`, `financial/procedural`, `recommendations`, `measures`) | JSON — канонично; **проекции-таблицы** пересобираются при сохранении | нужны SQL-запросы (реестр исполнения, отчётность, третьи лица, КК-корректировки, `effectiveViolations`), FK-целостность `violation_row_id`; при этом версия остаётся неизменяемым снимком |
| Рабочая группа версии, подписи, `sourceVersions`, регистрация, доставка, подтверждения, раунды требования | **таблицы** | FK на `User`/`DocumentVersion`, уникальность, участие в уведомлениях и инбоксе; в prof аналогичные факты — таблицы (`Acknowledgement`, `ErsopPackage`) |
| `approvalRoutes` | **таблицы** (`evga_workflow`) | общий модуль для ЭВГА/СВА/ПК; inbox по пользователю; аудит решений |
| `printContext` (снимок дела) | `JSONField print_context` | данные дела мутируют, снимок нужен для юридической стабильности печати; снимки документов заменить на FK (версии неизменяемы) |
| `paper` (ячейки РД), `calculationInputs_*`/`calculationResult_*`, `registrySchemaVersion` | внутри `values` | разреженные, не фильтруются; расчёты сервер проверяет пересчётом |
| `Upload` (файлы) | `core.Attachment` + в JSON только ссылка `{id, name, size, type}` | MinIO, checksum, права; правило `assertAttachmentRetention` → запрет удаления `Attachment`, на который ссылается непроектная версия |
| `history` (дела и версий) | `core.AuditEvent` | append-only, единый журнал; строка `action` фронта → `action` + `reason` |
| `notifications` | таблица + `NotificationRead` | адресаты — FK; прочтение по пользователю |
| `calendar` | глобальная `ProductionCalendarDay` | во фронте на дело только потому, что нет сервера |
| `quality: [bool×3]` | колонка-кеш + пересчёт сервисом `quality_passed(case, stage)` при каждом сохранении (как сейчас) либо чисто вычисляемое свойство (как `ControlCase.status` в prof) | |
| `ExecutionItem`, `Deadline`, `ApprovalTask`, `InformationRequestState` | вычисляемые сервисами (не таблицы) | во фронте это проекции; в prof `PrescriptionItem.status` — тоже `@property` |

### 7.5. Контур API (DRF, префикс `/api/evga/`, в стиле `apps/*/api/urls.py`)

* `cases/` (list/create, фильтры из `caseSearch.ts`: `number, date, bin, name, type, checkType, opf, electronic, org, author, coauthor, status, document`), `cases/{id}/`, `cases/{id}/counter-cases/`, `cases/{id}/coauthors/`, `cases/{id}/quality-assignments/`, `cases/{id}/deadlines/`, `cases/{id}/notifications/`, `cases/{id}/history/`.
* `cases/{id}/documents/` (create: `{kind}` → `createDocument` с `initialValues` на сервере), `documents/{id}/`, `documents/{id}/versions/{n}/`, `PATCH versions/{n}/values` (только `Проект`/`Возвращен`, с `row_version`), `versions/{n}/attachments/`.
* Действия версии (`@action`, тело `{expected_version, comment?, ...}`): `send-to-quality`, `submit` (`{stages[], signer_id}`), `approve`, `return`, `reject`, `activate`, `revise` (новая редакция), `request-group-signatures`, `sign-group`, `send-to-kvga`, `decide-kvga`, `send-to-confirmer`, `decide-confirmation`, `request-quality`, `request-approval`, `sign-quality`, `submit-quality-to-head`, `renew-quality`, `register` (`send|accept|return`), `deliver` (`send|acknowledge|respond|sign|object|refuse`), `information-request` (`send|acknowledge|provide|refuse|review|accept|reject|resend|mark-refused`), `recall`, `apply-amendment`, `calculate` (`{mode, inputs}`), `print/` (PDF).
* `cases/{id}/appeal/` (`assign`, `admission`, `notify`, `arguments`, `decide-arguments`), `cases/{id}/third-parties/` (+`receipt|response|forward`).
* `approval-tasks/` (inbox пользователя), `execution/items/` (реестр исполнения по всем делам, фильтры `ExecutionFilters`), `catalogs/*`, `form-schemas/{kind}?audit_type=`, `form-links/{case}/{key}` (варианты для `violationId/riskId/questionId/resultId/transfer/claim`).
* Переходный вариант для фронта: реализовать `ApiCaseRepository implements AuditCaseRepository` (`load()` = GET всех дел пользователя в текущем JSON-виде через сериализаторы, `save()` — запрещён) и постепенно заменять вызовы чистых функций фронта на действия API; это позволяет не переписывать UI сразу.


---

## 8. Открытые вопросы

1. **Дубль статусов устранения**: `remediation` содержит и `Частично устранено`, и `Устранено частично` (второе добавляется `referenceFormFor` для фин. аудита), а `response.measures.status` — `Устранено частично`. Нужен единый справочник.
2. **Коды видов документов**: `documentMatrix.code` («12», «55», «76»…) не уникальны и взяты с макета `stage1-260.jpg`. Настоящий классификатор — коды старой системы (`M5-IPI`, `M6-PA`, `M7-POR`, `M8-PLAN`, `M9-AZ`, `M17-AO`, `M18-RNS`/`M18-RNAFO`, `M19-AD`, `M20-VOZ`, `M21-AKO`?, `M23-RVO`, `M24-AZK`, `M25-PRED`, `M26-TU`, `M28-OPM`, `M39-ADM`?, `M43-VK`) из `n8n_old/bpmn` и `surfk.evga_document_types` — требуется подтверждение соответствия каждому `kind` (особенно `M21`, `M39`).
3. **ИРПИ без схемы**: единственный документ с ручной формой (`IrpiForm.tsx`) и ручной валидацией. Для серверной валидации нужно описать его схему в том же формате `FormSchema` (поля 2.15).
4. **Особые аккаунты по `id`** (`approver`, `quality-head`, `commission-chair`, `commission-1/2`, `reestr-confirmer`, `kvga`, `coauthor`) — какие роли/группы Keycloak им соответствуют и как задаётся состав апелляционной комиссии (на дело или глобально)?
5. **`printContext.sources`** дублирует значения документов внутри каждой версии (рост JSON). Предлагается заменить на FK (версии неизменяемы) — нужно согласие, т.к. `referencePrintData.printSource` трактует *отсутствие* документа в снимке как значимое («документ создан позже»).
6. **Производственный календарь** хранится на дело (`calendar.confirmedYears`) — источник данных для глобального справочника (ИС «Календарь»/ручной ввод)?
7. **Стадия рабочих документов**: правило `financial-rd-NN` с `number > 5` → основной этап — из кода `documentMatrix.ts`; подтвердить нормативно.
8. **`evidence` как отдельный документ**: комментарий в `validation.ts` — «The linked BPMN permits no separate evidence document» — при этом вид `evidence` существует. Нужен ли отдельный документ на сервере или доказательства — часть реестра?
9. **`response` создаёт и аудитор, и объект** (`ownerRole` зависит от актора): один документ с двумя владельцами или два разных документа (ответ объекта / регистрация аудитором, как `ExecutionSubmissionSource` в prof)?
10. **ЭЦП**: подписи сейчас — `{person, at, role}` без криптографии (`execution: "local-demo"`). Требуется ли NCALayer/КНБ-подпись на сервере для `Активный`, `sign`, `sign-group`, `sign-quality`?
11. **Фильтры `rnn` и `coauthor`** в поиске помечены как нереализованные (`caseSearch.ts`: «No RNN values…», «Coauthor permissions and data remain Q04»).
12. **Двуязычность заключений КК**: поля `*Kz` в `qualityN` необязательны («optional KZ companions do not invalidate legacy reviews») — на сервере требовать оба языка?
13. **Источник объектов встречной проверки**: `irpi.counterBins` → `plan.counterObjects` → ручное создание дела в `CounterChecks.tsx` — три несвязанных места; нужно определить, откуда создаётся дочернее дело.
14. **`quality: [bool×3]`** — хранить кеш или вычислять (`qualityPassed`) при каждом чтении; во фронте пересчёт при загрузке (`useAuditCases`).
15. **Интеграция ЕРСОП**: `performRegistration` — заглушка (`УЧ-{номер}`); в n8n есть `surfk.organ_reg_checks`, `subj_sched_insp` — уточнить контракт обмена.
16. **Уведомления в ВАП (`vap`)** и «Иски» — есть ли внешние интеграции (АИС ОИП: секция `enforcement`)?
17. **Хранение `Upload.data` (data-URL)** в существующих демо-данных — миграция не нужна (демо), но `seedCases`/`demoScenario` содержат эталонные сценарии для приёмочных тестов — стоит перенести их в fixtures/тесты бэкенда.

## 9. Кандидаты на переиспользование

| Элемент | Вердикт | Комментарий |
|---|---|---|
| `forms/schema.ts` + `forms/documentForms.ts` + `forms/referenceForms.ts` (декларативные схемы 42 форм) | **адаптировать** | Экспортировать в JSON (скрипт `node --experimental-strip-types`, как сделано для этого отчёта: `tmp_evga_domain/dump_forms.mts`) → fixture `FormSchema`; фронт продолжает использовать те же файлы |
| `data/workingPapers.json` (62 шаблона РД) | **переиспользовать как есть** | fixture `WorkingPaperTemplate` |
| `data/irpiForm.ts` (`irpiSections`, `financialIrpiSections`, `irpiRowLabels`) | **переиспользовать как есть** | fixture `IrpiSectionTemplate` + схема ИРПИ |
| `data/documentMatrix.ts` (`docKinds`, `counterDocKinds`, `stageNames`, `docName`) + классификаторы из `workflow.ts`/`documentStateMachine.ts` | **адаптировать** | fixture `EvgaDocumentType` с флагами (3.1) |
| `data/demoData.ts`: `basisOptions`, `initiatorOptions`, `catalogue`/`objectRegistry` | **адаптировать** | fixtures справочников `BasisKind`, `Initiator`, `AuditObject`; `accounts`/`people`/`seedCases` — только для тестов |
| `forms/validation.ts`, `irpiValidation.ts`, `workingPapers.validateWorkingPaper`, `violationRegistry.registryValidation`, `caseRules.validateCase` | **переписать на Python** | 1:1 порт в `services/`; тексты ошибок сохранить |
| `workflow.ts`, `documentStateMachine.ts`, `preparationWorkflow.ts`, `mainWorkflow.ts`, `qualityAssignment.ts`, `appeals.ts`, `thirdParties.ts`, `amendments.ts`, `informationRequests.ts`, `executionDecision.ts` | **переписать на Python** | доменные сервисы; логика уже чистая и покрыта тестами `tests/bpmn-*.test.ts`, `workflow.test.ts` — использовать как спецификацию для pytest |
| `shared/workflow/approvalRoute.ts` (+ README с контрактом) | **адаптировать** | Модели 7.3 + порт `createApprovalRoute/decideApprovalRoute/supersedeApprovalRoute/getApprovalTasks`; коды ошибок `ApprovalWorkflowError` → коды API; React-компоненты `ApprovalRouteEditor`/`ApprovalInbox` остаются |
| `shared/execution/execution.ts` (чистые функции сроков/фильтров) | **переиспользовать как есть** на клиенте; статусы и `createExecutionItemId` — порт на сервер | `executionItems.ts` → серверная проекция (аналог `PrescriptionItem.status` prof) |
| `modules/evga/deadlines.ts` (`auditDeadlines`, `qualityDays`, `addWorkingDays`) | **адаптировать** | правила → fixture `DeadlineRule`; расчёт на сервере по `ProductionCalendarDay` |
| `auditCalculations.ts`, `workingPapers.riskScore/riskLevel/materiality`, `violationRegistry.remainingAmount`, `formValues.effectiveViolations` | **переписать на Python** | тривиальные формулы; клиентские копии оставить для мгновенного отклика |
| `formValues.initialValues`, `formLinks.ts` | **переписать на Python** | предзаполнение и варианты ссылок должны выдаваться API (иначе клиент снова тянет всё дело) |
| `printContext.ts`, `components/referencePrintData.ts`, `qualityConclusion.qualityContextValues/qualityPrintData` | **адаптировать** | серверный сборщик печатного контекста |
| `components/ReferencePrintForm.tsx`, `QualityPrintForm.tsx`, `DocumentPrintForm.tsx` | **адаптировать** | спецификация печатных форм → серверные шаблоны PDF/DOCX; клиентский рендер оставить для предпросмотра |
| `pdfExport.ts` (pdfmake, LiberationSerif) | **переиспользовать как есть** для предпросмотра; официальный PDF — сервер | |
| `services/indexedDbCaseRepository.ts` | **удалить/заменить** | на `ApiCaseRepository` (переходно) и далее на модульные API-клиенты |
| `demoScenario.ts`, `financialDemoValues.ts`, `sampleScenario`, `useDemoSession.ts`, `DEMO_USER` | **удалить** | демо-контур; сценарии перенести в тестовые fixtures |
| n8n: `surfk.evga_document_types/statuses/stages/mappings`, `evga_document_versions/approvals/signatures/workflow_history`, `case_bases`, `case_participants`, `case_qc_expert_assignments`, `case_appeal_expert_assignments`, `evga_audit_object_notifications` | **адаптировать** | подтверждают ту же структуру (версии, маршруты, назначения экспертов); коды и подписи статусов взять оттуда |
| n8n: справочники `dictionaries`, `risk_levels`, `risk_object_types`, `offense_type`, `sampling_methods`, `control_reasons_types`, `check_initiators`, `organizational_legal_forms`, `audit_types`, `inspection_types`, `regions`, `positions`, `departments` | **переиспользовать содержимое** | наполнение таблиц `catalogs` вместо зашитых массивов фронта |
| n8n: функции `get_next_doc_sequence`, `check_document_creation_condition`, `send_document_to_audit_object`; таблицы `evga_doc_preliminary_study`, `evga_doc_audit_program`, `evga_doc_ap_questions`, `evga_doc_audit_order`, `evga_doc_apl_audit_objects`, `evga_doc_info_request`, `evga_doc_ir_questions`, `evga_doc_oar_violations`, `evga_doc_objection_appeal_result`, `response_measures`, `audit_results` | **адаптировать** | те же сущности, что проекции 7.3 (`AuditQuestion`, `RiskObject`, `Violation`, `ResponseMeasure`); n8n-версия хранила их только колонками — брать оттуда состав колонок и коды, но каноничным оставить `values` JSON + проекции |
| Camunda BPMN (`evga_doc_1_irpi`, `evga_doc_2_pa`, `evga_doc_3_plan`, `evga_doc_4_az`, `evga_doc_5_poruchenie`, `evga_doc_m43_vk_por`, `evga_doc_m18_m19_auto_create`) | **адаптировать** | фронт уже ссылается на них в комментариях (`preparationWorkflow.ts`, `mainWorkflow.ts`) — использовать как спецификацию переходов для Python-сервисов, без Zeebe |

Служебные файлы этого анализа: `(рабочая папка анализа)/tmp_evga_domain/dump_forms.mts` (экспорт схем), `forms_dump.json` (полный JSON всех схем для обоих типов аудита), `forms_summary.txt` (сводка).
