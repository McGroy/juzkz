# ЭВГА (saq-evga-test): бизнес-процессы, конечные автоматы и правила фронта — спецификация для сервисного слоя бэкенда

Источник: `saq-evga-test/src` (React 19 + TS, ветка `diar`). Все правила ниже прочитаны из исходников `src/modules/evga/*.ts`, `src/shared/workflow/approvalRoute.ts`, `src/shared/execution/execution.ts`, `src/types.ts`, `src/data/*.ts` и тестов `tests/*.test.ts`. Идентификаторы кода, строки статусов и тексты ошибок приведены как в исходниках (они же — ожидаемые тексты в тестах через `assert.throws(/…/)`).

Главный вывод: во фронте нет ни одного «UI-only» правила процесса — вся доменная логика сосредоточена в чистых функциях вида `(audit, doc, actor, …) => AuditDocument | AuditCase`, которые бросают `Error("текст")` при нарушении. Сервисный слой Django можно построить как прямой перенос этих функций (один сервис на файл), сохранив тексты ошибок и структуру `AuditCase/AuditDocument/DocumentVersion` (JSONB для `values`).

---

## 0. Как устроено состояние во фронте (что переносится на сервер)

| Элемент | Где | Суть |
|---|---|---|
| Хранилище | `src/services/auditCaseRepository.ts`, `indexedDbCaseRepository.ts` | Контракт `AuditCaseRepository { load(): Promise<AuditCase[]>; save(cases): Promise<void> }`. Всё состояние — массив дел, хранимый целиком (IndexedDB `saq-evga-test`, store `state`, key `cases`). |
| Точка входа мутаций | `src/modules/evga/EvgaModule.tsx`, `useAuditCases.ts` | `updateCase(next)` заменяет дело в массиве. Практически все изменения документов проходят через `saveDocument(audit, doc, actor)` (`workflow.ts`) — это «commit» с проверками конкурентности и побочными эффектами. |
| Загрузка | `useAuditCases.ts` | При загрузке: добавляются демо-дела (`workflowSampleCases`, `preparedCases`, `addPlannedSampleCases`, `addRegistrySampleCases`), `enrichSampleQualityForms`, `migrateLegacyApprovalRoutes`, пересчёт `quality[]` через `qualityPassed`. |
| Актор | `Account { id, name, role: Role, label, area?: "appeal" }` (`types.ts`), список `accounts` в `data/demoData.ts` | Роль выбирается переключателем в UI (localStorage `saq.evga.account.v1`); серверной авторизации нет. |
| История | `history.ts: log(actor, action, comment)` → `HistoryEntry {id, at, actor, action, comment}` | Пишется и в версию документа (`version.history`), и в дело (`audit.history`). |
| Время | `new Date().toISOString()` внутри функций (кроме `informationRequests.ts` и `approvalRoute.ts`, где `now` — параметр) | На сервере — единый `now` в транзакции. |

### 0.1 Ключевые типы (`src/types.ts`)

```
Role = "auditor" | "reviewer" | "approver" | "quality" | "kvga" | "reestr-confirmer"
     | "invited-specialist" | "object" | "appeal-head" | "appeal-expert"
Stage = 0 | 1 | 2                       // подготовительный, основной, заключительный
DocStatus = "Проект" | "Направлен на согласование КК" | "На согласовании" | "На утверждении"
          | "Согласован" | "На подтверждении КВГА" | "На подтверждении реестра"
          | "На подписании рабочей группой" | "Возвращен на доработку" | "Отклонен" | "Активный"

AuditCase: id, number, object: AuditObject, auditType, checkType, checkKind, electronic, dsp,
  jointObject?, purposeRu/Kz, group: Person[], bases: Basis[], author (ФИО!), createdAt,
  status: "Открыто"|"Закрыто", attachments, documents: AuditDocument[], quality: [bool,bool,bool],
  history, qualityAssignments?: {0|1|2: {expertId, assignedAt, assignedBy}}, appeal?: Appeal,
  thirdParties?, thirdPartiesReviewed?, amendments?, documentSequence?, coauthors?: string[] (id),
  notifications?: {id, at, documentId, text, recipients[], readBy[]}[],
  calendar?: {holidays[], workingDates[], confirmedYears[]}, parentCaseId?,
  executionState?: "Проводится"|"Приостановлено"|"Отменено", personType?, counterQuestion?,
  personBirthDate?, entrepreneurName?, schedule?: {start,end,periodFrom,periodTo}, sampleScenario?

AuditDocument: id, kind, stage, number ("<case.number>/NN"), createdAt, author (ФИО), versions[]
DocumentVersion: version, status: DocStatus, values: Record<string,unknown> (форма), attachments,
  group: Person[], reviewers: string[] (legacy), reviewerIndex, approver, signatures[{person,at,role}],
  approvalRoutes?: ApprovalRoute[], qualityConclusion?, qualityDecision?: "Без замечаний"|"С замечаниями",
  ownerRole?: Role, ownerId?, sourceVersions?: [{documentId, version, contentSnapshot?}],
  registration?: {status: "Отправлена"|"Зарегистрирована"|"Возвращена", number?, date?, comment?},
  delivery?: {sentAt, acknowledgedAt?, response?, attachments?, decision?: "Подписан"|"Подписан с возражениями"|"Отказ от подписания", decidedAt?, decidedBy?, grounds?, decisionAttachments?},
  informationRequest?: InformationRequestCycle, mainQuality?: {expertSignedAt, expertId, submittedAt?},
  main?: {agreedAt?, groupRequestedAt?, groupSignatures?, confirmation?: {confirmerId, status: pending|confirmed|returned, comment?, decidedAt?, sourceVersions?}, qualityRequestedAt?, approvalRequestedAt?},
  preparation?: {agreedAt?, qualityRequestedAt?, kvga?: {confirmerId, status: pending|confirmed|returned, at?, by?, comment?}, groupSignatures?},
  createdAt, history
```

Важно для бэкенда: `audit.author` и `doc.author` — это **ФИО**, а `coauthors`, `ownerId`, `reviewers`, `approver`, `confirmerId`, `expertId` — **id аккаунтов**. `canAuthorCase` сравнивает `audit.author === actor.name`. На сервере нужно перейти на `author_id` (Keycloak sub).

---

## 1. Виды документов и этапы (`src/data/documentMatrix.ts`)

36 видов основного дела (`docKinds`), 7 встречной проверки (`counterDocKinds`, префикс `counter-`), 62 рабочие формы (`workingDocKinds`: `financial-rd-01..59`, `compliance-rd-02..04`; `isWorkingPaper(kind) = /^(financial|compliance)-rd-\d{2}$/`).

| Этап | kind → название |
|---|---|
| 0 подготовительный | `irpi` ИРПИ, `program` программа, `plan` план, `assignment` аудиторское задание, `instruction` поручение, `quality1` КК 1 этап, `account` учётная карточка ЕРСОП, `vap` уведомление в ВАП, `additional` дополнительное поручение, `request` требование сведений, `obstruction` акт о воспрепятствовании |
| 1 основной | `report` аудиторский отчёт, `violations` реестр нарушений, `evidence` аудиторские доказательства, `quality2` КК 2 этап, `weekly` еженедельный отчёт, `measurement` акт контрольного обмера, `objections` возражения, `objection-result` результаты возражений |
| 2 заключительный | `conclusion` заключение, `prescription` предписание, `quality3` КК 3 этап, `notification` талон-уведомление, `forward-up/-law/-abp` передачи, `reply-up/-law/-abp` ответы, `claim-invalid/-dishonest/-recover/-liquidation` иски, `claim-decisions` решения по искам, `response` ответ о принятых мерах, `completion` справка о завершении |
| встречная (stage 0) | `counter-instruction`, `counter-account`, `counter-additional`, `counter-request`, `counter-obstruction`, `counter-act`, `counter-notification` |

Группы видов, определяющие маршрут (точные множества из кода):

| Множество | Состав | Где |
|---|---|---|
| `requiresQuality(kind)` | program, plan, assignment, instruction, violations, evidence, report, conclusion, prescription | `documentStateMachine.ts` |
| `isPreparationDocument(kind)` | irpi, program, plan, assignment, instruction, counter-instruction | `preparationWorkflow.ts` (`sequence` = irpi→program→plan→assignment→instruction) |
| `isMainDocument(kind)` | report, violations, evidence | `mainWorkflow.ts` |
| `isQuality(kind)` | quality1, quality2, quality3 | `workflow.ts` |
| `directActivation(kind)` | claim-decisions, reply-law, obstruction, counter-obstruction, objections, weekly, account, counter-account, notification, counter-notification, + все рабочие формы | `documentStateMachine.ts` |
| `repeatableKinds` (можно несколько экземпляров) | additional, request, obstruction, weekly, measurement, forward-*, reply-*, claim-*, counter-additional, counter-request, counter-obstruction | `workflow.ts` |
| `deliverable(kind)` (направляются объекту) | instruction, additional, request, report, violations, conclusion, obstruction, prescription, counter-instruction, counter-additional, counter-request, counter-act, counter-obstruction, objection-result | `workflow.ts` |
| Регистрируемые в ЕРСОП | account, counter-account, notification, counter-notification, additional, counter-additional | `performRegistration` |
| `qualitySources(audit, stage)` (комплект КК) | stage 0: irpi, program, plan, assignment, instruction; stage 1: report, violations, evidence; stage 2: conclusion, prescription (без рабочих форм и quality*) | `workflow.ts` |
| Цели дополнительного поручения `amendmentTargets` | program, plan, assignment, instruction, account, violations, evidence, report, counter-instruction, counter-account, counter-act | `amendments.ts` |
| Остальные («общий маршрут») | vap, measurement, forward-*, reply-up/-abp, claim-invalid/-dishonest/-recover/-liquidation, objection-result, response, completion, counter-account…, и т.д. | submit → reviewers → approver |

Нумерация: `createDocument` даёт `number = `${audit.number}/${String(documentSequence(audit)+1).padStart(2,"0")}``, где `documentSequence = max(audit.documentSequence, max(последний сегмент number всех документов))`. Номера после удаления не переиспользуются (`deleteDocument` фиксирует `documentSequence`). Дело: `nextCaseNumber` → `30101-YY-NNNNN`, стартовое значение 52970 (`caseRules.ts`). Встречное дело: `${parent.number}/ВП-${n}` (`CounterChecks.tsx`).

---

## 2. Конечный автомат документа

### 2.1 Статусы версии (`DocStatus`) и их смысл

| Статус | Кто держит | Что означает |
|---|---|---|
| `Проект` | владелец (`ownerRole`, `ownerId`) | Редактируемый черновик. Для `report` после подписей всех участников РГ статус возвращается в `Проект`, но `main.groupRequestedAt` уже стоит (редактирование запрещено). |
| `Направлен на согласование КК` | эксперт КК | Только для документов «общего маршрута» с `requiresQuality` (не prep/main — они на КК не «направляются» по одному, а комплектом). Редактирование блокируется, ждёт `qualityDecision`. |
| `На согласовании` | текущие согласующие маршрута | `approvalRoutes.at(-1).status === "review"`. |
| `На утверждении` | утверждающий/подписывающий (`route.signer`) | `route.status === "signing"`; для prep/main — после явного `sendPreparationForApproval` / `requestMainApproval`. |
| `Согласован` | автор | Промежуточный статус prep/main документов: все согласующие одобрили, но финальное утверждение ещё не запрошено (нужны КВГА / подтверждение реестра / КК). |
| `На подтверждении КВГА` | назначенный `kvga` | `preparation.kvga.status === "pending"` (только instruction/counter-instruction). |
| `На подтверждении реестра` | назначенный `reestr-confirmer` | `main.confirmation.status === "pending"` (только violations). |
| `На подписании рабочей группой` | участники `version.group` | report (`main.groupSignatures`) и assignment (`preparation.groupSignatures`). |
| `Возвращен на доработку` | владелец | После `return` любого участника, возврата КВГА/реестра/ЕРСОП. Дальше — новая версия (`createReturnedRevision`) или для legacy без маршрута — повторный submit той же версии. |
| `Отклонен` | владелец | Терминальный для версии; только `createRejectedRevision`. |
| `Активный` | — | Утверждён/подписан. Версия неизменяема (кроме `registration`, `delivery`, `informationRequest`, `qualityDecision/qualityConclusion` и истории). |

Подсостояния, которые не являются `DocStatus`, но участвуют в guard-ах: `qualityDecision`, `preparation.kvga.status`, `preparation.qualityRequestedAt`, `main.groupRequestedAt`, `main.agreedAt`, `main.confirmation.status`, `main.qualityRequestedAt`, `mainQuality.expertSignedAt/submittedAt`, `registration.status`, `delivery.*`, `informationRequest.state`, `approvalRoutes.at(-1).status`.

### 2.2 Права на редактирование и отправку (`documentStateMachine.ts`)

```
canEdit(version, role) =
  !version.main?.groupRequestedAt && !version.mainQuality?.expertSignedAt &&
  !hasActiveApprovalRoute(version) && currentApprovalRoute(version)?.status !== "rejected" &&
  role === (version.ownerRole ?? "auditor") && status ∈ {"Проект","Возвращен на доработку"}

canSubmit(doc, role, audit?) =
  kind !== "quality2" &&
  (!isMain || (audit && !mainCurrentBlock && !mainSubmissionBlock)) &&
  (!isPrep || (audit && !preparationCurrentBlock && !preparationSubmissionBlock)) &&
  !hasActiveApprovalRoute && route?.status !== "rejected" && role === ownerRole &&
  (canEdit || (kind==="report" && status==="Проект" && main.groupRequestedAt) || status==="Направлен на согласование КК") &&
  (isPrep || isMain || !requiresQuality(kind) || qualityDecision === "Без замечаний")
```

`canDecideDocument(doc, actor, audit)` — кто может approve/return/reject: при наличии маршрута — участник со `status === "pending"` (reviewer c `routeReviewer`, signer c `routeApprover`); для main/prep/quality2 дополнительно `mainCurrentBlock/mainReferencesBlock`, `preparationCurrentBlock/preparationReferencesBlock`, `mainQualityVersionBlock`, `mainQuality.submittedAt`; для approver в статусе `На утверждении` — `mainApprovalBlock` / `preparationApprovalBlock`. Legacy без маршрута: `reviewers[reviewerIndex] === actor.id` или `approver === actor.id`.

Владелец версии: `ownerRole` = `quality` для quality*, `object` для objections и response (если создал object), `appeal-expert` для objection-result, иначе `auditor`. `ownerId` ставится только для objection-result и quality* (`documentFactory.ts`).

### 2.3 Общий маршрут (документы вне prep/main/quality2)

| Из | Действие (функция) | В | Роль | Guard | Эффекты |
|---|---|---|---|---|---|
| — | `createDocument(audit, kind, actor)` | `Проект` v1 | по `creationAccessBlock`: auditor-автор/соавтор; `quality` — назначенный эксперт этапа; `object` — objections/response; `appeal-expert` — назначенный по апелляции для objection-result | `creationBlock(audit, kind)` (см. §3.3); `!repeatableKinds.has(kind) && exists` → «Документ уже создан.» | `values = initialValues(audit, kind)` (копирование вопросов/нарушений из источников), `group` (для quality — сам эксперт), `sourceVersions` (quality: `qualitySources`; additional: `amendmentTargets` + `contentSnapshot`; objection-result: objections; response: активные prescription/conclusion), history «Создана версия v1» |
| `Проект`/`Возвращен на доработку` | `sendDocumentToQuality(doc, actor)` | `Направлен на согласование КК` | владелец (`canEdit`) | `requiresQuality(kind)`; не prep (ошибка «Сначала согласуйте подготовительные документы…»), не main («Сначала согласуйте основной комплект и подтвердите реестр…»); не (`Возвращен` && есть маршрут) | `qualityConclusion/qualityDecision := undefined`; history «Проект направлен на контроль качества» |
| `Проект`/`Возвращен`/`Направлен на согласование КК` | `submitDocument(doc, actor, reviewers[], approver, comment, mode, stages?, audit?)` | `На согласовании` | владелец (`ownerId` если задан); prep/main — `canAuthorCase`; quality* — `qualityAssignmentBlock` | `canSubmit`; `reviewers` непустой, без дублей; `approver` обязателен кроме `assignment`/`report`; все reviewers проходят `routeReviewer(kind, a)`, approver — `routeApprover`; для quality* approver === `"quality-head"`, для остальных — не quality-head; `quality2` → ошибка «Подпишите заключение и направьте непосредственно руководителю КК» | если `Возвращен` и есть маршрут — автоматически `createReturnedRevision` (новая версия); `createApprovalRoute` (см. §4); prep: `preparation = {}`, `sourceVersions = preparationReferences`; main: `sourceVersions = mainReferences`; `signatures = []` (кроме report); `reviewers`, `reviewerIndex = 0`, `approver` (пусто для assignment/report); history «Направлено на последовательное/параллельное согласование» или «…: этапов — N» |
| `На согласовании` | `approveDocument(doc, actor, expectedVersion, audit?)` — согласующий | `На согласовании` (ещё есть pending) / `На утверждении` (route → signing) / `Согласован` (prep/main: все reviewers approved, финального участника нет или ещё не активирован) / `Активный` (route completed без signer и не prep/main) | reviewer из маршрута со статусом `pending` | `expectedVersion === activeVersion.version` («Открыта устаревшая версия документа…»); main/quality2: `mainCurrentBlock`, `mainReferencesBlock`/`mainQualityVersionBlock`; prep: `preparationCurrentBlock`, `preparationReferencesBlock`; `canDecideDocument` | `decideApprovalRoute(action:"approve")`; `reviewerIndex = число approved`; prep → `preparation.agreedAt`, main → `main.agreedAt`; `signatures.push({person, at, role})`; history «Согласовано» |
| `На утверждении` | `approveDocument` — финальный участник | `Активный` | `route.signer` (approver), для prep дополнительно `preparationApprovalBlock`, для main `mainApprovalBlock` | как выше | history «Утверждено» (signerAction approve) / «Подписано» |
| `На согласовании`/`На утверждении` | `returnDocument(doc, actor, comment, expectedVersion, audit?)` | `Возвращен на доработку` | текущий pending reviewer/signer | `comment.trim()` обязателен («Укажите замечание.»); те же block-и | `decideApprovalRoute(action:"return")` → маршрут `returned`, остальные участники `cancelled`, инициатору задача `revise`; `qualityDecision := undefined`; history «Возвращен на доработку» + comment |
| `На согласовании`/`На утверждении` | `rejectDocument(doc, actor, comment, expectedVersion, audit?)` | `Отклонен` | текущий pending reviewer/signer | причина обязательна («Укажите причину отклонения.») | маршрут `rejected`; `qualityDecision := undefined`; history «Отклонено» |
| `Возвращен на доработку` | `createReturnedRevision(doc, actor, audit?)` | `Проект` v+1 | владелец = инициатор маршрута; для quality* — также вновь назначенный эксперт (`assignedReplacement`) | `previous.status === "Возвращен на доработку"` | старый маршрут → `supersedeApprovalRoute` (или ручной supersede с комментарием «Новая редакция назначенным руководителем КК экспертом»); новая версия: `reviewers=[]`, `approver=""`, `signatures=[]`, `approvalRoutes=[]`, `preparation/main/mainQuality/qualityDecision/qualityConclusion/registration/delivery/informationRequest = undefined`; history = вся предыдущая + «Создана версия vN для доработки» (comment = причина возврата). main → `reviseMainDocument`, quality2 → `reviseMainQuality` |
| `Отклонен` | `createRejectedRevision` | `Проект` v+1 | владелец | `status === "Отклонен"` | аналогично, history «Создана новая версия vN после отклонения» |
| `Активный`/`Направлен на согласование КК`/`Согласован` с `qualityConclusion` | `createNextVersion(doc, actor, audit?)` | `Проект` v+1 | `auditor` | `qualityConclusion` заполнен («Новая версия доступна после заключения контроля качества.»); main → `reviseMainDocument` | новая версия копирует values/attachments/group, сбрасывает маршрут/подписи/preparation/main/mainQuality/quality*/registration/delivery/informationRequest; history «Создана версия vN» / «Ознакомление с заключением к версии vN-1» |
| `Проект` (directActivation) | `activateDocument(doc, actor)` | `Активный` | владелец, `canSubmit` | `directActivation(kind)`, `ownerId` совпадает | `signatures.push`, history «Подписано и активировано» |
| legacy без маршрута: `На согласовании` | `approveDocument` | `На утверждении` (когда `reviewerIndex === reviewers.length`) | `reviewers[reviewerIndex]` | prep-документы → ошибка «Повторно направьте подготовительный документ по актуальному маршруту согласования» | `reviewerIndex++` |
| `Активный` (quality*) | `addQualityConclusion(doc, actor, text)` (`qualityControlRules.ts`, устаревший путь) | — | `quality` | текст непустой, `qualityConclusion` ещё нет | `qualityConclusion`, history «Получено заключение контроля качества» |

### 2.4 Подготовительный этап (`preparationWorkflow.ts`; BPMN `evga_doc_1_irpi`…`evga_doc_5_poruchenie`, `evga_doc_m43_vk_por`)

Порядок согласования: `preceding(audit, kind)` = предшествующие по `sequence`, при этом `plan` и `assignment` учитываются только если созданы (опциональны), `irpi`/`program` — всегда. `isPreparationAgreed(doc)`: `status === "Активный"` или (`preparation.agreedAt` и последний маршрут `signing|completed` на текущий `documentVersionId` и все reviewers `approved` и статус не в {Проект, Возвращен, Отклонен}).

Блоки (возвращают текст или undefined):
- `preparationCurrentBlock` — версия/состояние в переданном `doc` совпадает с сохранённым в `audit` (сравнение JSON набора полей status/preparation/approvalRoutes/reviewers/…/history/ownerId/qualityDecision). Иначе «Открыта устаревшая версия документа. Обновите дело» / «Состояние документа изменилось. Обновите дело перед решением».
- `preparationSubmissionBlock` — дело `Открыто`, не `Приостановлено`; все `preceding` согласованы («Сначала согласуйте: ИПИ, Программа аудита…»).
- `preparationReferencesBlock` — если `preparation` есть, `sourceVersions` должны совпадать с текущими версиями preceding («Изменился состав или версия предыдущих документов. Создайте новую редакцию и повторите согласование»).
- `preparationQualityBlock(audit)` — существуют irpi, program, instruction («Подготовьте документ: …»); все `preparationSources` согласованы и ссылки актуальны; `instruction.preparation.kvga.status === "confirmed"` («Получите подтверждение поручения назначенным сотрудником КВГА»).
- `preparationApprovalBlock(audit, doc)` — референсы; документ согласован («Сначала завершите согласование документа»); для `counter-instruction` только КВГА confirmed; иначе `preparationQualityBlock`, затем `quality1` `Активный` с `conclusion.decision === "Без замечаний"` («Получите утверждённое заключение КК подготовительного этапа без замечаний»), его `sourceVersions` покрывают текущие версии всех `preparationSources` и не ссылаются на несуществующие («Заключение КК относится к предыдущим версиям. Проведите повторный контроль качества»); все `preceding` уже `Активный` («Сначала утвердите: …»).

| Из | Действие | В | Роль | Guard | Эффекты |
|---|---|---|---|---|---|
| `Согласован` (instruction/counter-instruction) | `sendInstructionToKvga(audit, doc, actor, confirmerId)` | `На подтверждении КВГА` | автор/соавтор (`assertAuthor`) | `isPreparationAgreed`; kvga ещё не `confirmed`; `preparationReferencesBlock`; `confirmerId` — аккаунт роли `kvga` | `preparation.kvga = {confirmerId, status:"pending"}`; history «Поручение направлено на подтверждение КВГА» |
| `На подтверждении КВГА` | `decideInstructionKvga(audit, doc, actor, "confirm", comment, expectedVersion)` | `Согласован` | назначенный `kvga` (`confirmerId === actor.id`) | `assertCurrent`; референсы | `kvga.status="confirmed", at, by, comment`; history «Поручение подтверждено КВГА» |
| `На подтверждении КВГА` | `decideInstructionKvga(…, "return", comment)` | `Возвращен на доработку` (instruction) / `Согласован` (counter-instruction — «M43 возвращает к шагу отправки аудитора») | назначенный `kvga` | comment обязателен («Укажите причину возврата») | `kvga.status="returned"`; history «Поручение возвращено КВГА» |
| `Согласован` (instruction) | `requestPreparationQuality(audit, doc, actor)` | без смены статуса | автор | `preparationQualityBlock` пуст; ещё не направлен («Комплект уже направлен на КК») | `preparation.qualityRequestedAt`; history «Согласованный комплект подготовительного этапа направлен на КК». Именно этот флаг открывает `creationBlock(audit, "quality1")` |
| `Согласован` (prep, кроме assignment) | `sendPreparationForApproval(audit, doc, actor)` | `На утверждении` | автор | `preparationApprovalBlock` пуст (т.е. КК1 утверждён без замечаний по актуальным версиям и все предыдущие уже `Активный`) | `preparation.*` сохраняется; history «Направлено на окончательное утверждение». Дальше `approveDocument` утверждающим маршрута → `Активный` |
| `Согласован` (assignment) | `sendPreparationForApproval` | `На подписании рабочей группой` | автор | группа непуста, ровно один `leader`, id уникальны («Укажите рабочую группу и одного руководителя группы») | `preparation.groupSignatures = []`; history «Направлено на подписание рабочей группой» |
| `На подписании рабочей группой` (assignment) | `signAssignmentGroup(audit, doc, actor, expectedVersion)` | без смены | участник `version.group` с ролью `auditor`/`invited-specialist` | `preparationApprovalBlock`; не подписывал («Ваша подпись уже сохранена») | `preparation.groupSignatures.push`, `signatures.push`; history «Аудиторское задание подписано участником рабочей группы» |
| `На подписании рабочей группой` (assignment) | `approveAssignmentGroup(audit, doc, actor, expectedVersion)` | `Активный` | руководитель группы (`auditor` && `group.leader`) | все участники подписали («Дождитесь подписей всех участников рабочей группы») | history «Аудиторское задание утверждено руководителем рабочей группы» |
| `Согласован`/`На утверждении`/`На подписании РГ`/`Активный` (prep) | `revisePreparationDocument(audit, doc, actor)` | `Проект` v+1 | автор | статус из перечня | старый маршрут `supersedeApprovalRoute`; новая версия без preparation/sourceVersions/маршрута/подписей/КК/registration/delivery; history «Создана новая редакция vN; требуется повторное согласование и КК» |

Тестами закреплено: черновики всех prep-документов можно создать заранее; согласование строго по цепочке; `quality1` создаётся только после `requestPreparationQuality`; окончательное утверждение — только после КК1 «Без замечаний» по актуальным версиям; добавление плана после КК1 блокирует утверждение до повторного согласования/КК; новая версия любого предшественника инвалидирует ссылки зависимых; `counter-instruction` проходит согласование → КВГА → утверждение без КК основного дела и не выставляет `quality[0]`.

### 2.5 Основной этап (`mainWorkflow.ts`; BPMN `evga_doc_m18_m19_auto_create`, реестр, `evga_doc_ad`, `evga_doc_37_kk2`, `prc_JwETUJ5Idw7y4AnvNvhyFxuRrB2`)

Порядок: **отчёт (подписи всей РГ → согласование без утверждающего) → реестр (согласование) → доказательства, если созданы (согласование) → подтверждение реестра назначенным `reestr-confirmer` → автор направляет комплект на КК2 → эксперт подписывает и направляет руководителю КК → утверждение КК2 → окончательное утверждение реестра, затем доказательств → параллельно отправка отчёта и реестра объекту → ознакомление → подпись/возражения/отказ.**

`mainReferences(audit, doc)`: violations → [report]; evidence → [report, violations]; report → [program, instruction] (текущие версии). `isMainAgreed(doc)`: `main.agreedAt` && маршрут `signing|completed` на текущий versionId && все reviewers approved && статус ∉ {Проект, Возвращен, Отклонен, На согласовании}.

Блоки:
- `mainCurrentBlock` — дело открыто, не приостановлено; версия совпадает с сохранённой; состояние (всё кроме values/attachments/group) совпадает; если есть `main` или `mainQuality` — и содержимое (values/attachments/group) совпадает («Подписанное содержимое изменилось. Создайте новую редакцию»).
- `mainPreparationBlock(audit)` — quality1 `Активный` «Без замечаний», есть irpi/program/instruction, все prep `Активный` и их версии есть в `sourceVersions` КК1 («Завершите актуальную подготовку и КК подготовительного этапа»).
- `mainSubmissionBlock` — открыто/не приостановлено; `mainPreparationBlock`; report: если `groupRequestedAt` — ссылки на program/instruction актуальны («Изменились подготовительные документы. Создайте новую редакцию отчёта»), группа непуста, `groupRequestedAt` есть, все подписали («Получите подписи всех участников рабочей группы под отчётом»); violations/evidence: отчёт `isMainAgreed` («Сначала подпишите рабочей группой и согласуйте отчёт»); evidence: реестр `isMainAgreed` («Сначала согласуйте реестр нарушений»).
- `mainReferencesBlock` — submission + (если есть agreedAt или маршрут) sourceVersions актуальны («Изменились исходные документы. Создайте новую редакцию и повторите согласование»).
- `mainConfirmationBlock(audit)` — есть report и violations («Подготовьте отчёт и реестр нарушений»); все main `isMainAgreed` («Сначала согласуйте отчёт/реестр нарушений/аудиторские доказательства») и ссылки актуальны.
- `mainQualityBlock(audit)` — confirmation + `violations.main.confirmation.status === "confirmed"` («Получите подтверждение реестра назначенным сотрудником») + `confirmation.sourceVersions` совпадают с текущими версиями всех main docs («Комплект изменился после подтверждения реестра. Повторите подтверждение»).
- `mainQualityConclusionBlock(audit)` — qualityBlock + quality2 `Активный` «Без замечаний» («Получите утверждённое заключение КК основного этапа без замечаний») + его `sourceVersions` совпадают с текущими версиями main docs («Заключение КК относится к предыдущим версиям. Проведите повторный контроль качества»).
- `mainApprovalBlock(audit, doc)` — report: всегда блок («Отчёт согласуется после подписей рабочей группы; отдельное утверждение не предусмотрено»); иначе referencesBlock + qualityConclusionBlock; evidence: violations должен быть `Активный` («Сначала утвердите реестр нарушений»).
- `mainDeliveryBlock(audit, doc)` — currentBlock; только report/violations; qualityConclusionBlock; все main кроме report `Активный` («Сначала утвердите реестр и все существующие аудиторские доказательства»).
- `mainQualityVersionBlock(audit, doc)` (для quality2) — qualityBlock; kind quality2; `sourceVersions` КК2 совпадают с текущими main («Комплект изменился. Создайте актуальную редакцию заключения КК»); `violations.main.qualityRequestedAt` («Автор дела должен направить комплект на КК»).

| Из | Действие | В | Роль | Guard | Эффекты |
|---|---|---|---|---|---|
| `Проект` (report) | `requestReportGroupSignatures(audit, doc, actor)` | `На подписании рабочей группой` | автор/соавтор | нет `groupRequestedAt`; группа непуста, id и имена непустые и уникальны («Проверьте участников рабочей группы…») | `sourceVersions = mainReferences`; `main = {groupRequestedAt, groupSignatures: []}`; history «Отчёт направлен на подпись всем участникам рабочей группы» |
| `На подписании рабочей группой` (report) | `signReportGroup(audit, doc, actor, expectedVersion)` | `Проект` когда подписали все, иначе без смены | участник `group` c ролью `auditor`/`invited-specialist` | `mainPreparationBlock`; ссылки актуальны; не подписывал | `main.groupSignatures.push`, `signatures.push`; history «Отчёт подписан участником рабочей группы» |
| `Проект` (report, все подписи) | `submitDocument(…, approver="")` | `На согласовании` | автор | `canSubmit` (groupRequestedAt) | маршрут без signer |
| `На согласовании` (main) → все approved | `approveDocument` | `Согласован` | reviewer | referencesBlock | `main.agreedAt` |
| `Согласован` (violations) | `sendRegistryToConfirmer(audit, doc, actor, confirmerId)` | `На подтверждении реестра` | автор | `mainConfirmationBlock`; confirmer роли `reestr-confirmer` | `main.confirmation = {confirmerId, status:"pending", sourceVersions: все main docs текущих версий}`; `main.qualityRequestedAt := undefined`; history «Реестр направлен назначенному подтверждающему» |
| `На подтверждении реестра` | `decideRegistryConfirmation(audit, doc, actor, "confirm"|"return", comment, expectedVersion)` | `Согласован` / `Возвращен на доработку` | назначенный `reestr-confirmer` | `mainConfirmationBlock`; `confirmation.sourceVersions` актуальны («Комплект изменился. Повторно направьте реестр на подтверждение»); return требует comment | `confirmation.status`, `comment`, `decidedAt`; history «Реестр подтверждён»/«Реестр возвращён на доработку» |
| `Согласован` (violations, confirmed) | `requestMainQuality(audit, doc, actor)` | без смены | автор | `mainQualityBlock`; не направлен | `main.qualityRequestedAt`; history «Согласованный и подтверждённый комплект основного этапа направлен на КК». Открывает `creationBlock(audit,"quality2")` |
| `Согласован` (violations, evidence) | `requestMainApproval(audit, doc, actor)` | `На утверждении` | автор | `mainApprovalBlock` | `main.approvalRequestedAt`; history «Документ направлен на окончательное утверждение после КК» |
| `На утверждении` (violations/evidence) | `approveDocument` утверждающим маршрута | `Активный` | signer | `mainApprovalBlock` повторно на commit (`saveDocument`) | |
| `Согласован` (report) | `deliverDocument(report, auditor, "send", …, audit)` | `Активный` + `delivery.sentAt` | автор/соавтор | `mainDeliveryBlock` | отчёт не имеет отдельного утверждения |
| любая (main) | `reviseMainDocument(audit, doc, actor)` | `Проект` v+1 | автор | не (`Проект` без `main`) («Редактируйте существующий проект») | сброс `main`, `sourceVersions`, маршрута, подписей, КК, delivery, registration; history «Создана редакция vN; требуется повторное подписание и согласование» |

КК2 (`quality2`) — особый маршрут без согласующих:

| Из | Действие | В | Роль | Guard | Эффекты |
|---|---|---|---|---|---|
| `Проект` | `signMainQuality(audit, doc, actor)` | `Проект` + `mainQuality.expertSignedAt` | назначенный эксперт (`ownerId`) | `mainCurrentBlock`, `mainQualityVersionBlock`, `qualityAssignmentBlock(audit,1,actor)`; `values.conclusion.decision` и `textRu` заполнены | `signatures.push`; после подписи содержимое заморожено (`mainCurrentBlock`) |
| `Проект` (подписан) | `submitMainQualityToHead(audit, doc, actor)` | `На утверждении` | эксперт-подписант | ещё не `submittedAt` | `approvalRoutes.push` маршрут `{reviewers:[], signer: quality-head (pending), signerAction:"approve", status:"signing"}`; `approver="quality-head"`; `mainQuality.submittedAt`; history «Подписанное заключение направлено непосредственно руководителю КК» |
| `На утверждении` | `approveDocument(doc, quality-head, v, audit)` | `Активный` | `quality-head` | `mainQualityVersionBlock` (в т.ч. повторно при `saveDocument`) | `saveDocument` записывает `qualityDecision/qualityConclusion` в версии источников |
| `На утверждении` | `returnDocument` / `rejectDocument` | `Возвращен`/`Отклонен` | `quality-head` | comment | |
| `Возвращен`/`Отклонен`/подписан/устарел | `reviseMainQuality(audit, doc, actor)` | `Проект` v+1 | назначенный эксперт | `mainQualityBlock`; условие «подписанного, возвращённого или устаревшего» | `sourceVersions` = main docs + активные `objection-result`; сброс mainQuality/подписей/маршрута; history «Создана актуальная редакция заключения КК vN; требуется подпись эксперта и решение руководителя» |

### 2.6 Заключения КК1/КК3 (`quality1`, `quality3`) — общий маршрут с ограничениями

- Создать/редактировать/отправить может только эксперт, назначенный руководителем КК на этап (`qualityAssignmentBlock`: «Руководитель КК должен назначить эксперта на N этап» / «Заключение оформляет назначенный эксперт КК: <имя>»).
- `submitDocument` для quality*: `approver` обязан быть `"quality-head"` («Заключение КК утверждает руководитель контроля качества»); reviewers — обычные `reviewer` (без `area: "appeal"`).
- Маршрут: `На согласовании` → `На утверждении` → `Активный` (`quality-head`).
- `renewQuality(audit, doc, actor)` — повторный КК: только назначенный эксперт роли `quality`, версия `Активный`, `creationBlock(audit, kind)` пуст → новая версия `Проект`, `values = {quality: old.values.quality}`, `sourceVersions` = текущие `qualitySources` (+ активный `objection-result` для stage 1), history «Начат повторный контроль качества».
- `validateDocument` для quality*: `sourceVersions` обязательны; `values.quality.level ∈ {"Первый уровень","Второй уровень"}`; участники `version.group` не должны входить в `audit.group` («Контроль качества проводит сотрудник, не участвовавший в этом аудите»); для stage 1 обязательна оценка охвата вопросов программы (`coverage[].assessmentRu`).
- Печатная форма — 16 пунктов `qualityHeadings` (`qualityConclusion.ts`), контекст фиксируется в `values.context` при создании (`qualityContextValues`), чтобы последующие правки дела не меняли печатный текст.

### 2.7 Регистрация в ЕРСОП (`performRegistration(doc, actor, action, comment, registrationNumber)`)

| Из | action | В | Роль | Guard | Эффекты |
|---|---|---|---|---|---|
| `Активный`, `registration` нет или `Возвращена` | `"send"` | `registration = {status:"Отправлена"}` | `auditor` | kind ∈ регистрируемые; `status === "Активный"` («Сначала утвердите документ»); не отправлен («Документ уже направлен на регистрацию») | history «Учёт регистрации: Отправлена» |
| `Отправлена` | `"accept"` | `{status:"Зарегистрирована", number: registrationNumber || "УЧ-<number с / → ->", date: now}` | `auditor` | `registration.status === "Отправлена"` («Документ не ожидает ответа ЕРСОП») | при `saveDocument` для additional/counter-additional — изменение состояния проверки (§3.5); `registered(audit)` становится true для account/counter-account |
| `Отправлена` | `"return"` | `{status:"Возвращена", comment}` + `status = "Возвращен на доработку"` | `auditor` | comment обязателен («Укажите причину возврата») | документ снова редактируем (`canEdit`) |

Во фронте ЕРСОП имитируется («Тестовый ответ»); на сервере `accept/return` — это обработка ответа интеграции, `send` — инициирование.

### 2.8 Направление объекту аудита (`deliverDocument(doc, actor, action, response, attachments, audit?)`)

| Из | action | Роль | Guard | Эффекты |
|---|---|---|---|---|
| `Активный` (или `Согласован` для report — переводится в `Активный`), `deliverable(kind)`, нет `delivery` | `"send"` | `auditor`; для `objection-result` — `appeal-expert`-владелец; report/violations — автор/соавтор и `mainDeliveryBlock` | instruction/counter-instruction: `registered(audit)` («Поручение направляется объекту после регистрации учетной карточки»); additional: `registration.status === "Зарегистрирована"` | `delivery = {sentAt}`; history «Направлено объекту аудита»; уведомление всем `object` |
| после send | `"acknowledge"` | `object` | ещё не ознакомлен | `delivery.acknowledgedAt`; history «Объект аудита ознакомлен» |
| после send | `"respond"` | `object` | не для report/violations («По документу требуется явное решение объекта: подпись или отказ»); текст или файл | `delivery.response/attachments`; history «Получен ответ объекта» |
| после send, report/violations/counter-act, нет `decision` | `"sign"` | `object` | report: `acknowledgedAt` обязателен («Сначала подтвердите ознакомление объекта с отчётом») | `decision="Подписан"`, `decidedAt/decidedBy` |
| то же | `"object"` | `object` | обоснование обязательно («Укажите обоснование»); report — после ознакомления | `decision="Подписан с возражениями"`, `grounds`, `decisionAttachments` |
| то же | `"refuse"` | `object` или `auditor` (автор/соавтор) | обоснование + вложения обязательны («Приложите подтверждение отказа и передачи отчёта через канцелярию») | `decision="Отказ от подписания"` |

Требования (`request`, `counter-request`) обрабатываются не через `delivery`, а через `transitionInformationRequest` (§2.9); `deliverDocument` для них — адаптер (`send/acknowledge/respond→provide`).

### 2.9 Требование о предоставлении сведений (`informationRequests.ts`; BPMN `evga_doc_info_request`, `evga_doc_m45_vk_treb`)

Отдельный автомат внутри активной версии: `version.informationRequest = {state, rounds[]}`. Состояния `InformationRequestState`: `sent` («Направлено объекту: ожидается ознакомление»), `awaiting` («Ожидание сведений»), `received` («Ответ получен: ожидает рассмотрения»), `review` («Сведения на проверке у аудитора»), `overdue` («Срок предоставления сведений истёк»), `accepted`, `refused`.

Раунд: `{id, sentAt, deadline?, acknowledgedAt?, response?: {at, by, text, attachments, refused?, legacy?}, review?: {at, by, decision: accepted|rejected|resend|refused, comment}, reviewStartedAt?}`.

Действия (`InformationRequestAction`) и доступность (`informationRequestActions`):

| Состояние | object | автор/соавтор (`canAuthorCase`) |
|---|---|---|
| нет цикла | — | `send` |
| `sent` | `acknowledge` | — |
| `awaiting` | `provide`, `refuse` | — |
| `received` | — | `review` (только counter-request попадает сюда) |
| `review` | — | `accept`, `reject`, `resend` |
| `overdue` | — | `resend`, `mark-refused` |
| `accepted`/`refused` | — | — (терминальные) |

Переходы (`transitionInformationRequest(audit, doc, actor, action, {text, attachments, deadline}, now)`):
- `send`: срок берётся из `values.general.deadline` (ISO datetime), обязателен и позже `now` («Укажите срок предоставления сведений», «Срок предоставления сведений должен быть позже времени отправки»); `request` → `sent`, `counter-request` → `awaiting` (ознакомление не требуется); `delivery = {sentAt}`.
- `acknowledge` → `awaiting`, `acknowledgedAt` (таймер срока стартует только отсюда для обычного требования).
- `provide` (текст или файл) → `request`: `review`; `counter-request`: `received`; `refuse` (обоснование) → `refused`.
- `review` → `review` (`reviewStartedAt`).
- `accept` → `accepted`; `reject` → `refused`; `mark-refused` → `refused`; `resend` (обоснование + новый `deadline`) → новый раунд, предыдущий раунд получает `review.decision="resend"`.
- Вычисляемое истечение (`informationRequestCycle(doc, now)`): в `awaiting` при `now >= deadline` → `overdue` (request) или сразу `refused` (counter-request, автоматический отказ по BPMN). В `review` просрочка не наступает.
- Guard общий (`assertCurrent`): дело открыто, документ в `audit` совпадает с переданным (JSON активной версии), kind — требование, версия `Активный`.
- Legacy: старый `delivery.response` мигрирует в цикл как `received` с `response.legacy=true`, `at=""` — не считается принятым.

### 2.10 Результаты возражений (`objection-result`) и отзыв

- Создаёт назначенный `appeal-expert` (`creationAccessBlock`: «Результаты оформляет назначенный сотрудник управления апелляции»; при `admission.decision === "Отказ в рассмотрении"` — блок).
- Маршрут: reviewers — только аккаунты с `area: "appeal"` и ролью `reviewer` (члены комиссии), approver — только `"commission-chair"` (`routeReviewer/routeApprover`).
- `recallDocument(doc, actor)`: `На согласовании` → `Проект`, только владелец-эксперт, `reviewerIndex === 0` и нет подписей («Отзыв доступен исполнителю до первого согласования»); маршрут помечается `superseded`, участники `cancelled`.
- `reassignReturnedDocument(doc, actor, expertId)` (вызывается из `assignAppeal`): `Возвращен на доработку` → `Проект` v+1 с `ownerId = новый эксперт`; только `appeal-head`; маршрут должен быть `returned`.
- Отправка объекту: `deliverDocument(result, appeal-expert-owner, "send")`.
- `validateDocument` для objection-result: `appealSubmissionBlock` (назначен исполнитель, `admission = "Принято к рассмотрению"`, обоснования аудитора подписаны); каждое оспоренное нарушение ровно один раз; суммы (`Подтверждено` → cancelled 0; `Отменено` → cancelled = amount; `Отменено частично` → 0 < cancelled < amount).

### 2.11 Ответ о принятых мерах (`response`) — `executionDecision.ts`, `executionItems.ts`

- Создаёт `auditor` или `object` (`ownerRole = "object"`, если создал объект); `sourceVersions` = активные версии prescription/conclusion; `values.measures` копируют пункты предписания (`violationId`, `amount`, `accepted="0"`), `values.recommendations` — рекомендации заключения.
- Действующая редакция для исполнения: `effectiveExecutionResponseVersion(doc)` — последняя версия с `hasCompletedDocumentApproval` (`Активный` + маршрут `completed` на этот `documentVersionId`, либо legacy подпись роли `approver`).
- `assertExecutionResponseSave(previous, next)` при каждом `saveDocument`: замороженные версии (не `Проект` и не `Возвращен` без маршрута) не меняются по содержимому («Изменение направленного ответа требует новой редакции и нового согласования.»); `Активный` полностью неизменяем («Утверждённый ответ сохранён в истории…»); `Отклонен` нельзя перевести обратно; нельзя откатить статус в `Проект`, потерять историю/подписи/маршрут; статус `Активный` допустим только при завершённом маршруте («Результат исполнения применяется после завершения согласования и утверждения ответа.»).
- `createResponseRevision(doc, actor)` (после утверждения, владелец) и `reviseExecutionResponse(audit, doc, actor)` — новая версия с перепривязкой строк к текущим активным prescription/conclusion (`sourceVersions` обновляются, `amount` берётся из предписания, `done` рекомендации сбрасывается при изменении текста).
- `responseConfirmsSourceVersion(response, source, version)`: ответ подтверждает версию источника, если `sourceVersions` содержит её, либо (legacy без ссылок) версия источника = 1.
- Продление срока: `values.general.extension === true` + `deadline` (YYYY-MM-DD) + `extensionReason`; действует только в утверждённой редакции и только если новая дата позже исходной (`executionItemsForCases`).

### 2.12 Побочные эффекты `saveDocument(audit, doc, actor)` (`workflow.ts`) — «commit» документа

Порядок проверок и эффектов (важно воспроизвести на сервере в одной транзакции):
1. `assertExecutionResponseSave` (для `response`).
2. Конкурентность для quality*: входящая версия не старее сохранённой; у всех сохранённых версий не изменился `ownerId` и не потеряны события истории → «Заключение КК или назначение эксперта изменилось. Обновите документ перед сохранением решения».
3. Конкурентность для prep/main/quality2: не потеряны версии, события истории, подписи, `main.groupSignatures`, `preparation.groupSignatures`, события маршрутов; при наличии `main/mainQuality` не изменены values/attachments/group → «Документ изменился. Обновите дело перед сохранением решения».
4. Для main/quality2 той же версии: любое изменение при наличии `main/mainQuality/маршрута` должно сопровождаться новым событием истории («Изменение маршрута требует нового решения с записью истории»); при новом событии повторно проверяются кросс-документные предусловия по актуальному делу: `mainQualityVersionBlock` (quality2), `mainPreparationBlock`, актуальность `sourceVersions` («Исходные документы изменились перед сохранением решения»), `mainReferencesBlock`, актуальность `confirmation.sourceVersions` («Комплект изменился перед сохранением подтверждения реестра»), `mainApprovalBlock` при переходе в `Активный`, `mainDeliveryBlock` при изменении `delivery`. Предыдущие версии неизменяемы («Предыдущие версии документов доступны только для чтения»).
5. Для quality* при акторе `quality` — `qualityAssignmentBlock`.
6. Замена/добавление документа; `documentSequence` пересчитывается.
7. `objections` стал `Активный` → `audit.appeal = getAppeal(next)`.
8. quality* стал `Активный` (новая активная версия) → для каждой `sourceVersions` записать в версию источника `qualityDecision` («Без замечаний»/«С замечаниями» по `values.conclusion.decision`), `qualityConclusion` (= `conclusion.textRu` или decision), history «Получено заключение контроля качества <номер>, vN». Для main-документов — только если версия текущая и не `Активный`.
9. `additional`/`counter-additional` стал `Зарегистрирована` → по `values.order.type`: «Приостановление проверки» → `executionState="Приостановлено"`; «Возобновление проверки» → `"Проводится"`; «Отмена проверки» → `"Отменено"` и `status="Закрыто"`; всегда — history «Зарегистрировано дополнительное поручение: <type>», новое основание в `audit.bases` (`id: additional-<docId>-vN`, kind = `order.basisRu || order.reason || type`); «Продление проверки» с `order.extendDate` → `schedule.end`.
10. `quality = [qualityPassed(0), qualityPassed(1), qualityPassed(2)]`.
11. `completion` стал `Активный` → `status="Закрыто"`; `counter-notification` `Зарегистрирована` → `status="Закрыто"`.
12. История дела: новые события версии копируются с префиксом `"<docName> · vN: <action>"`; если событий нет, но документ изменился — «<docName> · vN: сохранены изменения».
13. Уведомление (`notifications.push`) при любом изменении; получатели по статусу:
   - quality* или objections стали `Активный` → автор/соавторы + все `quality` (+ `appeal-head` для objections);
   - `На согласовании` → pending reviewers маршрута (или `reviewers[reviewerIndex]`);
   - `На подтверждении реестра` → `confirmerId`; `На подтверждении КВГА` → `kvga.confirmerId`;
   - `На подписании рабочей группой` → участники группы без подписи;
   - `На утверждении` → `approver`; `Направлен на согласование КК` → все `quality`;
   - появился `delivery` → все `object`;
   - `objection-result` `Активный` → автор/соавторы + quality + object + area appeal;
   - иначе → `ownerId` либо все аккаунты `ownerRole` (для auditor — только автор/соавторы).

### 2.13 Удаление (`deleteDocument(audit, id, actor)`)

Только: дело открыто; актор — владелец (`ownerRole`, `ownerId`; auditor — автор/соавтор); ровно одна версия в статусе `Проект` («Удалить можно только проект без подписанных версий»); на документ не ссылается ни один другой (`sourceVersions` или упоминание id в `values`) («Документ используется в другом документе или заключении КК»); нет документов, зависящих по `dependencies` («На основании проекта уже создан следующий документ»). Эффект: `documentSequence` фиксируется, history «Удалён проект <docName> · <number>».

### 2.14 Валидация формы перед отправкой (`forms/validation.ts: validateDocument(audit, doc, version)`)

Вызывается UI перед `submit`/`activate`/`sendToQuality` и в тестах; на сервере должна выполняться в тех же точках. Помимо схем полей (`formFor(kind, auditType)` в `forms/documentForms.ts`, 1094 строки): расчётные блоки (`calculationInputs_*` требуют `calculationResult_*`), `irpi` — `validateIrpiForReview`, рабочие формы — `validateWorkingPaper` (применимость, период, `completed`, ответы Да/Нет/Нет ответа), `creationBlock`, обязательные поля/коллекции (`section.min`), проверка дат и сумм (`datesError`), группа (один руководитель; `assignment` ≥ 2 участников), `violations` — `registryValidation`, quality* — см. §2.6, `evidence`/`report` — версия реестра из `sourceVersions` доступна, у каждого нарушения есть доказательство с файлом и реквизитами (если документ доказательств существует), доказательства ссылаются на существующие нарушения; `report` — состав и порядок вопросов совпадают с программой из `sourceVersions`; `objections` — ссылки на `effectiveViolations` без повторов и с исходными суммами, дата подачи не в будущем, «По почте» требует вложение; `objection-result` — §2.10; `prescription` — ровно все `effectiveViolations`, суммы совпадают; `response` — вложения у мер со статусом ≠ «Не устранено»; `completion` — `completionBlock`. `assertAttachmentRetention(before, after)` — вне статуса `Проект` нельзя удалять вложения.

---

## 3. Конечный автомат дела и этапов

### 3.1 Состояния дела

- `status`: `"Открыто"` → `"Закрыто"`. Закрытие: `completion` стал `Активный`; `counter-notification` зарегистрирован (встречное дело); зарегистрировано доп. поручение «Отмена проверки». Обратного перехода нет. При `Закрыто` все мутации блокируются («Дело закрыто»).
- `executionState`: `undefined`/`"Проводится"` ↔ `"Приостановлено"` → `"Отменено"`. При `Приостановлено` `creationBlock` разрешает создавать только `additional`/`counter-additional` («Проверка приостановлена. Оформите дополнительное поручение о возобновлении»); prep/main-переходы блокируются («Проверка приостановлена»).
- `quality: [КК1, КК2, КК3]` — вычисляемое (`qualityPassed`), пересчитывается при каждом `saveDocument`, `applyAmendment` сбрасывает в `[false,false,false]`, `assignQualityExpert` для подписанного quality2 сбрасывает `quality[1]`.
- Создание/изменение дела (`CaseForm.tsx` + `validateCase`): БИН 12 цифр; «Плановый» — объект из перечня; цели на двух языках; ≥1 основание; ≥1 участник; ≤1 руководитель; «Совместная» требует `jointObject`. Изменять открытое дело может только автор/соавтор роли `auditor`. history «Создано дело» / «Изменены сведения дела».
- Встречное дело (`CounterChecks.tsx`): предусловие `registered(parent)` («Учетная карточка основного дела должна быть зарегистрирована в КПСиСУ»); поля `parentCaseId`, `personType` («Юридическое лицо»/«Физическое лицо»), `personBirthDate`, `entrepreneurName`, `counterQuestion`, `schedule` из ИРПИ родителя, `checkType="Встречная проверка"`, `checkKind="Встречная"`, `group` (копия), history «Создано дело встречной проверки к <number>».
- Соавтор (`assignCoauthor(audit, actor, id)`): актор `id === "approver" && role === "approver"` («Соавтора назначает руководитель органа аудита»); выбранный — `auditor`, не автор, не дубль; уведомление соавтору.
- Календарь дела (`RegulatoryPanel.tsx`): `calendar = {holidays[], workingDates[], confirmedYears[]}`; даты YYYY-MM-DD, годы `20\d{2}`, дата не может быть одновременно рабочей и нерабочей; history «Обновлён рабочий календарь дела».

### 3.2 Этапы и `qualityPassed(audit, stage)` (`workflow.ts`)

`stageAvailable(audit, stage) = stage === 0 || audit.quality.slice(0, stage).every(Boolean)` (`qualityControlRules.ts`). `creationBlock` для основного дела: документ этапа `> 0` требует `quality[0..stage-1]` («Завершите контроль качества предыдущего этапа»); `account` требует `quality[0]` («Завершите КК и утвердите документы подготовительного этапа»).

`qualityPassed(audit, stage)`:
- stage 1, если есть main-документы с `main` (новый маршрут): `!mainQualityConclusionBlock(audit)` и все `qualitySources(1)` готовы (report — `isMainAgreed`, остальные `Активный`).
- иначе: документ `quality{stage+1}` существует, версия `Активный`, `values.conclusion.decision === "Без замечаний"`, `sourceVersions` непусты и покрывают все `qualitySources(stage)`, и каждая ссылка указывает на **текущую** версию источника в статусе `Активный` (рабочие формы исключены из проверки актуальности).

Следствие (закреплено тестами): положительное заключение КК не заменяет утверждение документов; любая новая версия источника или новый условный документ этапа обнуляет `quality[stage]`.

### 3.3 Зависимости создания документов (`creationBlock(audit, kind)`; `dependencies`)

| kind | Требует | Правило |
|---|---|---|
| program | irpi | prep-документы: зависимости через `dependencies` **не** проверяются (`isPreparationDocument → []`), порядок обеспечивается на согласовании |
| plan, assignment, instruction | program | то же |
| account | instruction, quality1 | + `quality[0]` |
| vap, additional, request, obstruction | instruction | `isActive(instruction)` |
| objections | report | `isActive(report)` (для report — `Активный`) |
| objection-result | objections | |
| prescription | conclusion | пропускается, если нет `effectiveViolations` (и тогда «Подтвержденных нарушений нет: предписание не требуется») |
| notification | quality3 | |
| response | prescription | пропускается без нарушений |
| completion | quality3, notification, response | `response` активен = есть `effectiveExecutionResponseVersion` |
| reply-up/-law/-abp | forward-up/-law/-abp | |
| counter-account, counter-additional, counter-request, counter-obstruction | counter-instruction | |
| counter-act | counter-account | |
| counter-notification | counter-act | |

Правило проверки зависимости: если и `kind`, и зависимость `requiresQuality` — достаточно существования документа; иначе зависимость должна быть активна (`isActive`). Текст: «Сначала подготовьте/утвердите: <названия>».

Дополнительные условия `creationBlock`: рабочая форма соответствует типу аудита (`paperApplies`: `financial-*` — `isFinancialAudit`, `compliance-*` — /соответств/i, и не для встречных дел); `counter-*` только в делах с `parentCaseId` и наоборот («Документ относится к другому виду дела»); `violations`, `report`, `request`, `counter-act`, `counter-request` требуют `registered(audit)` («Сначала учтите регистрацию учетной карточки в ЕРСОП»); `conclusion`/`prescription` требуют решения объекта по отчёту (`delivery.decision`) («Получите подпись объекта под отчётом либо зафиксируйте отказ…»), а при «Подписан с возражениями» или наличии `objections` — активный `objection-result` («Сначала рассмотрите возражения объекта аудита») и активный `quality2`, ссылающийся на текущую версию `objection-result` («После рассмотрения возражений проведите повторный КК основного этапа»); исключение — отказ в рассмотрении с `notifiedAt`. Для `quality1`: `preparationQualityBlock` + `instruction.preparation.qualityRequestedAt` («Автор дела должен направить согласованный комплект на контроль качества»); `quality2`: `mainQualityBlock` + `violations.main.qualityRequestedAt`; `quality3`: обязательные `conclusion` (+`prescription` при нарушениях) существуют и все `qualitySources(2)` в статусе `Активный` или `Направлен на согласование КК` («Сначала подготовьте и направьте на КК документы этапа: …»).

`isActive(audit, kind)`: есть документ вида с активной версией `Активный` (для `response` — `effectiveExecutionResponseVersion`). `registered(audit)`: `account`/`counter-account` с `registration.status === "Зарегистрирована"`.

### 3.4 Сквозной процесс по этапам (как закреплено `full-process.test.ts` и `demoScenario.ts: stage/finish/prepareDemoMainStage`)

1. **Подготовительный**: создать irpi, program, (plan), (assignment), instruction (+ рабочие формы `compliance-rd-02..04` для соответствия / `financial-rd-01..05` для АФО — по желанию, не блокируют КК) → согласовать по цепочке (каждый: submit → reviewers → `Согласован`) → `sendInstructionToKvga` → `decideInstructionKvga confirm` → `requestPreparationQuality` → `assignQualityExpert(stage 0)` → эксперт создаёт `quality1`, submit (reviewers + `quality-head`) → `Активный` «Без замечаний» → автор `sendPreparationForApproval` каждого документа по порядку (assignment: подписи РГ + руководитель) → `Активный` → `quality[0] = true`.
2. **Регистрация**: `account` (directActivation) → `performRegistration send/accept` → `registered`. Теперь можно `instruction → deliver send`, создавать `violations`, `report`, `request`, встречные дела.
3. **Основной**: черновики report/violations/evidence → `requestReportGroupSignatures` → подписи всей РГ → submit report (без approver) → согласовано → submit violations → согласовано → submit evidence → согласовано → `sendRegistryToConfirmer` → `decideRegistryConfirmation confirm` → `requestMainQuality` → `assignQualityExpert(stage 1)` → эксперт `quality2`: `signMainQuality` → `submitMainQualityToHead` → `quality-head approve` → `requestMainApproval(violations)` → approve → `requestMainApproval(evidence)` → approve → `quality[1] = true` → `deliver report send` (Согласован → Активный), `deliver violations send` → object `acknowledge` → `sign`/`object`/`refuse`.
4. **Возражения** (если «Подписан с возражениями»): объект создаёт/активирует `objections` → `assignAppeal` → `recordAdmission` → аудитор `saveAppealArguments(submit)` → `decideArguments` руководителем → эксперт `objection-result` → комиссия → председатель → `deliver send` → `renewQuality`/`reviseMainQuality` quality2 со ссылкой на `objection-result` → `Активный`.
5. **Заключительный**: `conclusion` (sendDocumentToQuality → …), `prescription` (если `effectiveViolations`) → `assignQualityExpert(stage 2)` → `quality3` → `Активный` «Без замечаний» → submit/approve conclusion, prescription → `quality[2] = true` → `notification` (activate + регистрация талона) → `response` (submit → approve) → `completion` (validate = `completionBlock`) → `Активный` → дело `Закрыто`.

### 3.5 Дополнительные поручения: приостановление/возобновление/отмена/продление/дополнения (`additional`, `counter-additional`)

`values.order.type ∈ {"Приостановление проверки", "Возобновление проверки", "Отмена проверки", "О внесении дополнений в приказ", "Продление проверки"}` (`forms/documentForms.ts`). Документ проходит общий маршрут (submit → approve → `Активный`), затем `performRegistration`; эффекты — при регистрации в `saveDocument` (§2.12 п.9). `deliverDocument send` для additional требует регистрации.

`applyAmendment(audit, doc, actor)` (`amendments.ts`) — перенос изменений в связанные документы:
- Guard `amendmentBlock`: автор/соавтор; дело открыто; kind additional/counter-additional, `Активный`, `Зарегистрирована`; тип — только «О внесении дополнений в приказ» или «Продление проверки» («Это поручение изменяет состояние проверки и не требует переноса полей»); ещё не применялось для этой версии; нет `objections/objection-result/conclusion/prescription/completion` («Изменения после начала рассмотрения возражений или заключительного этапа требуют отдельного решения о пересмотре материалов»); есть `amendmentTargets`; `sourceVersions` поручения содержат все цели с текущими версиями и `contentSnapshot` (JSON `{values, group}`) совпадает; все цели `Активный`.
- Эффект: для каждой цели новая версия `Проект` v+1 с перенесёнными полями (`general`, `questions` merge по id, `objects`, `coverage.amount`, `risks`, `duration/period`; для продления — только `end/extendDate`), `sourceVersions=[{documentId: doc.id, version}]`, history «Создана версия vN по дополнительному поручению …»; дело: `purposeRu/Kz`, `group`, `schedule`; `audit.amendments.push`; `quality=[false,false,false]`; history «Применено дополнительное поручение …».

### 3.6 Встречная проверка

Отдельное дело с `parentCaseId`; документы только `counter-*`; последовательность: `counter-instruction` (согласование → КВГА → утверждение, без КК) → `counter-account` (activate → регистрация) → `counter-additional`/`counter-request`/`counter-obstruction` → `counter-act` (требует регистрации; объект подписывает `sign/object/refuse`) → `counter-notification` (activate → регистрация → дело `Закрыто`). `executionStages` для встречного дела показывает один этап «Встречная проверка».

### 3.7 Возражения и апелляция (`appeals.ts`)

`Appeal = {objectionId, version, receivedAt, expertId?, admission?: {decision: "Принято к рассмотрению"|"Отказ в рассмотрении", at, by, reason, files, notifiedAt?}, arguments?: {rows[{violationId, textRu, textKz, files}], at, by, submittedAt?, signedAt?, signedBy?, comment?}}`. `getAppeal(audit)` — по активному `objections` (пересоздаётся при новой версии возражений).

| Действие | Роль | Guard | Эффект |
|---|---|---|---|
| `assignAppeal(audit, actor, expertId)` | `appeal-head` | эксперт роли `appeal-expert`; нет отказа в рассмотрении; `objection-result` в `Проект`/`Возвращен` («Дождитесь возврата результатов с согласования перед сменой исполнителя») | `appeal.expertId`; если результат `Возвращен` другому — `reassignReturnedDocument` + уведомление; `ownerRole/ownerId` результата |
| `recordAdmission(audit, actor, decision, reason, files)` | `commission-chair` (по id) | reason и files обязательны; решения ещё нет; результат не направлен | `appeal.admission` |
| `notifyAdmission(audit, actor, files)` | `appeal-head` или назначенный эксперт | files; решение есть, `notifiedAt` нет | `admission.notifiedAt`, files |
| `saveAppealArguments(audit, actor, rows, submit)` | автор/соавтор | не submitted/signed; при submit — по каждому оспоренному пункту ровно одна строка с textRu/textKz/files | `appeal.arguments` (+`submittedAt`) |
| `decideArguments(audit, actor, approve, comment)` | `"approver"` (по id, «руководитель подразделения аудитора») | `submittedAt` есть, не подписано; отказ требует comment | `signedAt/signedBy` или сброс `submittedAt` + comment |
| `appealSubmissionBlock(audit)` | — | назначен исполнитель; `admission = Принято`; обоснования подписаны | используется `validateDocument(objection-result)` |

Все изменения пишут history и уведомление (area appeal + автор/соавторы + `approver` + все `object`). `effectiveViolations(audit)` = нарушения последней версии реестра с учётом решений активного `objection-result` («Отменено» — исключить, «Отменено частично» — `amount − cancelled`); используется предписанием, ответом, заключительным этапом.

### 3.8 Третьи лица (`thirdParties.ts`)

Все действия — роль `object`, дело открыто, отчёт ознакомлен (`report.delivery.acknowledgedAt`). `recordNoThirdParties(reason)` → `thirdPartiesReviewed {none:true}`; `addThirdParty({name, identification (12 цифр или пусто), violationIds ⊂ реестр, noticeAt (прошлая дата ≥ ознакомления), noticeFiles})`; `recordThirdPartyEvent(id, "receipt"|"response"|"forward", date, text, files)` — строго по порядку, даты не раньше предыдущего события и не в будущем (`assertPastDate`), файлы обязательны.

### 3.9 Исполнение и закрытие (`completionBlock`, `executionItems.ts`, `shared/execution`)

`completionBlock(audit)` (используется `validateDocument(completion)` и «Учёт исполнения предписания» в ходе исполнения):
1. Если есть утверждённый ответ — он должен ссылаться на текущие активные версии prescription/conclusion, если в них есть пункты («Ответ о принятых мерах не подтверждает текущую версию документа «…»»).
2. По каждому пункту предписания (financial + procedural последней активной версии) ровно одна мера с тем же `violationId` («По каждому пункту предписания требуется одна подтвержденная мера…»), `amount` совпадает, при статусе «Устранено» и `remediation !== "Не подлежит устранению"` `accepted ≥ recover + restoreWork + restoreAccounting`.
3. Нет мер вне предписания; все меры в статусе «Устранено» или «Не подлежит устранению»; все рекомендации заключения отмечены `done`; `accepted ≤ amount`.

Read-модель реестра исполнения `executionItemsForCases(cases)` → `ExecutionItem` (общий контракт `shared/execution/execution.ts`): `id = createExecutionItemId(source)` (`execution:evga:<caseId>:<docId>:<docVersionId>:<itemId>`), `claimedStatus` (по текущей редакции ответа), `confirmedStatus` (по утверждённой: `open|in_review|partial|completed|not_remediable`), `originalDueDate`/`dueDate` (продление только из утверждённого ответа), `extensions` (`approved`/`proposed`/`rejected`), `evidence`, `responses`, `history`. `getDeadlineStatus(dueDate, today, policy)` — календарный по умолчанию, `warningDays` не задаётся по умолчанию, `timeZone` явно, `calendar: "business"` исключает выходные/праздники политики.

`executionProgress.ts` (`executionStages`, `nextExecutionStep`, `documentNextAction`) — read-модель «ход исполнения»: для каждого этапа шаги «Подготовка документов этапа», «Контроль качества · N-й этап», «Согласование и утверждение документов» (+ регистрация, подписание реестра/отчёта объектом, возражения, талон, исполнение предписания, завершение). Содержит формулировки следующего действия и актора — полезно как спецификация серверного эндпоинта `progress`.

---

## 4. Маршрут согласования (`src/shared/workflow/approvalRoute.ts`) — как должен жить на сервере

Чистый модуль без React-зависимостей; документация в `src/shared/workflow/README.md` (контракт «зафиксирован для интеграции»). Один документ-версия может иметь несколько маршрутов (`version.approvalRoutes[]`), актуальный — последний (`currentApprovalRoute`).

```
ApprovalRoute {
  id, documentId, documentVersionId ("<docId>:v<N>"), moduleId?: "evga", caseId?, documentTitle?, caseTitle?, documentVersionLabel?,
  initiator: ApprovalPerson {id, name, role?, position?, department?},
  mode: "parallel"|"sequential",            // режим первого этапа (совместимость)
  stages?: [{id, mode, reviewerIds[]}],     // порядок этапов; отсутствие = один этап из reviewers
  reviewers: ApprovalParticipant[] {…person, status, stageId?, stageIndex?, activatedAt?, decidedAt?, comment?},
  signer?: ApprovalParticipant, signerAction?: "sign"|"approve" (отсутствие = sign в старых данных; ЭВГА везде передаёт "approve"),
  status: "review"|"signing"|"completed"|"returned"|"rejected"|"superseded",
  createdAt, updatedAt, history: [{id, action: submitted|approve|sign|return|reject|supersede, actorId, actorName, documentVersionId, at, comment?, newDocumentVersionId?}],
  returned?/rejected?: {actorId, actorName, comment, at}, supersededByVersionId?, execution: "local-demo"
}
ApprovalParticipantStatus: waiting | pending | approved | signed | returned | rejected | cancelled
```

Функции и инварианты (все чистые, не мутируют вход, ошибки `ApprovalWorkflowError{code}`: `INVALID_ROUTE`, `FORBIDDEN`, `STALE_VERSION`, `INVALID_STATUS`, `ALREADY_DECIDED`, `COMMENT_REQUIRED`):
- `createApprovalRoute(input)`: id/documentId/documentVersionId непустые; ≥1 этап, у каждого ≥1 согласующий и корректный mode; id этапов уникальны; согласующие без повторов; signer не среди согласующих; инициатор не среди согласующих (но может быть signer — «инициатор может подписать после независимого согласования»); статус `review`; `advanceReviews` активирует первый незавершённый этап (parallel — всех `waiting` → `pending`; sequential — первого); событие `submitted`.
- `decideApprovalRoute(route, {actorId, documentVersionId, action, comment, now})`: `documentVersionId` совпадает (`STALE_VERSION`); участник назначен (`FORBIDDEN`); не решал (`ALREADY_DECIDED`); маршрут `review|signing` (`INVALID_STATUS`); участник `pending` и фаза соответствует; reviewer → только `approve`; signer → только `signerAction ?? "sign"`; `return`/`reject` требуют comment (trim). `approve` reviewer → `approved`, `advanceReviews` (следующий этап / `signing` с signer `pending` / `completed` без signer); signer approve/sign → `completed`; `return`/`reject` → маршрут `returned|rejected`, `route.returned|rejected = {…}`, все `waiting/pending` → `cancelled`. `now` не может быть раньше `updatedAt`.
- `supersedeApprovalRoute(route, {actorId = initiator, documentVersionId, newDocumentVersionId})`: только инициатор; новый id версии отличается; не `superseded`; незавершённые → `cancelled`; статус `superseded`, `supersededByVersionId`, событие `supersede`. Сохраняет `returned/rejected` и всю историю.
- `getApprovalTasks(routes, userId?)` → `ApprovalTask {id: "<routeId>:<action>:<participantId>", routeId, initiator, assignee, action: approve|sign|revise, participantRole: reviewer|signer|approver, status: waiting|pending|completed|returned|rejected|cancelled, createdAt, updatedAt, comment?, …контекст}`; для `returned` маршрута инициатору создаётся задача `revise` (`pending`, пока маршрут `returned`). `getPendingApprovalTasks` — только `pending`. Сортировка по `updatedAt` desc, затем id.

ЭВГА-адаптер (`approvalTasks.ts`):
- `caseApprovalRoutes(cases)` — проекция всех маршрутов всех версий для inbox: дописывает `caseId`, `caseTitle` (`"<number> · <object.ru>"`), `documentTitle` (`"<docName> · <number>"`), `documentVersionLabel` («Версия №N»), данные участников из справочника; для main/quality2 маршруты неактуальных версий помечает `superseded`, участников `cancelled`; signer в статусах документа `Согласован`/`На подтверждении КВГА`/`На подтверждении реестра` показывается как `waiting` (финальное решение ещё не запрошено автором).
- `migrateLegacyApprovalRoutes(audit)` — для версий `На согласовании`/`На утверждении` без маршрута строит маршрут из `reviewers/reviewerIndex/approver` (id `legacy-<docId>-v<N>`); везде проставляет `signerAction ?? "approve"`.
- Inbox (`pages/ApprovalTasks.tsx`) кроме маршрутных задач показывает «задания по процессу», не являющиеся маршрутами: «Подтверждение КВГА», «Подтверждение реестра», «Подписание рабочей группой», «Подписание объектом аудита» — вычисляются из статусов документов и адресатов.

Рекомендация по серверу: таблицы `approval_route` (1 строка на маршрут, FK на `document_version`), `approval_participant` (reviewer/signer с `stage_index`, статусом, датами), `approval_event` (история); задачи inbox — либо материализованная таблица `approval_task`, либо view по участникам + отдельные «process tasks» по статусам версий. Тесты `shared-approval-workflow.test.ts` (27 сценариев) — прямой контракт для pytest.

---

## 5. Роли и права

### 5.1 Роли (`Role`) и демо-аккаунты (`data/demoData.ts: accounts`)

| Роль (`role`) | Демо-аккаунты (id) | Что может (по коду) |
|---|---|---|
| `auditor` | `auditor` (DEMO_USER «Жукенов К. А.»), `coauthor` («Даулет Оразбаев»), + все `people[]` кроме приглашённого специалиста | Создание/редактирование дела и документов **только как автор (`audit.author === name`) или соавтор (`coauthors ∋ id`)** (`canAuthorCase`); submit, sendToQuality, activate, createNextVersion, ревизии; КВГА/реестр/КК запросы; регистрация ЕРСОП; отправка объекту, фиксация отказа объекта; требования (send/review/accept/reject/resend/mark-refused); подписи РГ; обоснования по апелляции; применение доп. поручений; удаление проекта. Участник РГ (`version.group`) — подпись отчёта/задания; `leader` — утверждение задания. |
| `invited-specialist` | `invited-specialist` | Только подписи рабочей группы (report, assignment). |
| `reviewer` | `reviewer-1`, `reviewer-2`; с `area:"appeal"`: `commission-1`, `commission-2` | Согласование/возврат/отклонение в маршруте. `routeReviewer(kind, a)`: обычные reviewers — все документы кроме `objection-result`; члены комиссии — только `objection-result`. |
| `approver` | `approver` («Петров Александр»), `quality-head` («Руководитель контроля качества»), `commission-chair` (`area:"appeal"`) | Утверждение (финальный участник). `routeApprover`: `objection-result` → только `commission-chair`; quality* → только `quality-head`; остальное → любой approver кроме quality-head и appeal. Спецполномочия по **id**: `approver` — `assignCoauthor`, `decideArguments`; `quality-head` — `assignQualityExpert` (`canAssignQualityExpert`); `commission-chair` — `recordAdmission`. |
| `quality` | `quality`, `quality-2` | Создание/редактирование/подпись/отправка/повторный КК заключений **только при назначении на этап** (`qualityAssignments[stage].expertId`). Получает уведомления о направлении на КК. |
| `kvga` | `kvga` | `decideInstructionKvga` только как назначенный `confirmerId`. |
| `reestr-confirmer` | `reestr-confirmer` | `decideRegistryConfirmation` только как назначенный `confirmerId`. |
| `object` | `object` | `acknowledge/respond/sign/object/refuse`; требования (`acknowledge/provide/refuse`); создание/активация `objections`, создание `response`; третьи лица. |
| `appeal-head` | `appeal-head` | `assignAppeal`, `notifyAdmission`, переназначение возвращённого результата. |
| `appeal-expert` | `appeal-expert`, `appeal-expert-2` | `objection-result` (создание, submit, recall, отправка объекту) при назначении `appeal.expertId`. |

Общие правила доступа: любое действие блокируется при `status === "Закрыто"`; действия владельца проверяют `ownerRole`/`ownerId`; решения по маршруту — только назначенный участник в `pending`; `expectedVersion` обязателен для решений (защита от устаревшей вкладки); все «adressные» роли (КВГА, реестр, эксперт КК, апелляция) — по id назначения, не по роли.

### 5.2 Предлагаемое отображение на Keycloak

| Демо | Keycloak role / атрибут | Комментарий |
|---|---|---|
| `auditor` | `evga_auditor` | автор/соавтор — не роль, а связь `case.author_id`/`case_coauthor`; руководитель РГ — `case_group.leader` |
| `invited-specialist` | `evga_invited_specialist` (внешняя организация) | только подписи РГ |
| `reviewer` | `evga_reviewer` | выбор из штатного расписания (`people[]` → справочник сотрудников) |
| `approver` (id `approver`) | `evga_approver` + `evga_department_head` | назначение соавтора и подпись обоснований — руководитель подразделения |
| `quality-head` | `evga_quality_head` | назначение экспертов, утверждение КК |
| `quality` | `evga_quality_expert` | назначение на этап хранится в `quality_assignment` |
| `kvga` | `evga_kvga_confirmer` | адресное подтверждение поручения |
| `reestr-confirmer` | `evga_registry_confirmer` | отдельная от КВГА роль (по BPMN) |
| `object` | `evga_object_representative` + атрибут БИН | доступ только к своему делу (по `object.bin`) |
| `appeal-head` / `appeal-expert` | `evga_appeal_head` / `evga_appeal_expert` | |
| `commission-1/2`, `commission-chair` | `evga_appeal_commission_member` / `evga_appeal_commission_chair` | |

Вне демо в постановке перечислены также юрист, аналитик, администратор отчётного периода, пользователь секретных дел, пользователь просмотра (`docs/specification-baseline.md`) — во фронте не реализованы.

---

## 6. Сроки и напоминания (`deadlines.ts`, `appeals.ts: appealFilingDue`, `informationRequests.ts`, `shared/execution`)

Календарь: **рабочие дни** (`workingDate`: не сб/вс, не в `calendar.holidays`, либо в `calendar.workingDates` — перенос), `addWorkingDays(date, n, calendar)` (n может быть отрицательным), дата события переводится в локальную дату `Asia/Almaty` (`localDate`). Срок помечается `estimated: true`, если хотя бы один год интервала отсутствует в `calendar.confirmedYears`. Сроки требований сведений — **календарные datetime** (ISO), без рабочих дней. Реестр исполнения — календарные дни по умолчанию (`DeadlinePolicy`), рабочие — только при явном `calendar:"business"`.

`qualityDays(audit, doc)`: «Второй уровень» → 20; stage 0 → 2; stage 2 → 3; stage 1 → 10 для финансовой отчётности (`isFinancialAudit`), 7 при `quality.departmentReview`, иначе 5.

`auditDeadlines(audit)` → `Deadline {label, source, due, completed, estimated, rule}`:

| label | Отсчёт от | Дней (раб.) | Источник | completed |
|---|---|---|---|---|
| «КК N этапа · <уровень>» | `values.quality.receivedAt` каждого quality* | `qualityDays` | № 392, пп. 129–131 | версия `Активный` |
| «Представить отчёт объекту» | `schedule.end` (или `instruction.duration.end`) | −1 (если ≤15 раб. дней проведения) / −2 | № 413, п. 16; № 392, п. 99 | есть `report.delivery` |
| «Подача возражений» | `report.delivery.sentAt` | +10 | № 392, пп. 101–102 | есть `objections` |
| «Уведомить затронутых третьих лиц» | `report.delivery.acknowledgedAt` | +2 | № 392, п. 101-1 | `thirdPartiesReviewed` |
| «Обоснования аудитора в комиссию» | `appeal.receivedAt` | +3 | № 392, п. 133 | `arguments.signedAt` |
| «Рассмотреть возражения к отчёту» | `appeal.receivedAt` | +30 | Закон о госаудите, ст. 58-4 | `objection-result` активен или отказ |
| «Известить объект об отказе в рассмотрении» | `appeal.receivedAt` | +5 | ст. 58-3 | `admission.notifiedAt` |
| «Оформить результаты решения комиссии» | `objection-result.values.general.date` | +2 | ст. 58-5 | результат активен |
| «Позиция третьего лица: <имя>» | `party.receivedAt` | +5 | № 392, п. 101-1 | `party.response` |
| «Передать позицию в орган аудита: <имя>» | `report.delivery.sentAt` | +10 | № 392, п. 101-1 | `response.forwardedAt` |
| «Подготовить аудиторское заключение» | electronic: утверждение quality2 / иначе `report.delivery.decidedAt` | +3 / +10 | № 413, п. 20 / № 392, п. 107 | conclusion активен |
| «Направить заключение объекту» | утверждение conclusion | +1 | № 413, п. 22; № 392, п. 108 | `conclusion.delivery` |
| «Направить предписание объекту» | утверждение conclusion | +1 | то же | `prescription.delivery` |
| «Направить талон о результатах в ЕРСОП» | утверждение conclusion | +3 | № 413, п. 14; № 392, п. 113 | `notification.registration` |
| «Меры при неисполнении предписания» | `prescription.values.general.deadline` | +5 | № 413, п. 29 | дело закрыто |

Дополнительно: `appealFilingDue(audit)` = `report.delivery.sentAt + 10 раб. дней`; требование — `deadline` раунда, просрочка → `overdue`/`refused` (§2.9); исполнение — `dueDate` пункта предписания (`general.deadline` / `row.deadline`) с продлением из утверждённого ответа. Напоминаний/планировщика во фронте нет — сроки вычисляются на чтение; на сервере целесообразен периодический job для `overdue` требований и статусов исполнения.

---

## 7. Перечень мутаций и предлагаемые эндпоинты (в стиле prof: DRF ViewSet + `path("<uuid:pk>/<action>/", …View.as_view())`)

Соглашения: базовый префикс `/api/evga/`; тело действий — JSON; каждое действие над версией принимает `expected_version` (аналог `expectedVersion`) и возвращает обновлённое дело/документ; ошибки — `400 {"detail": "<текст из фронта>"}`, `403` для ролевых блоков, `409` для «устаревшая версия/состояние изменилось».

### 7.1 Дело

| Функция фронта | Сигнатура | Endpoint |
|---|---|---|
| создание дела (`CaseForm.save` + `validateCase`, `nextCaseNumber`) | `(form) → AuditCase` | `POST /api/evga/cases/` |
| изменение дела | автор/соавтор, открыто | `PATCH /api/evga/cases/{id}/` |
| `assignCoauthor(audit, actor, id)` | `→ AuditCase` | `POST /api/evga/cases/{id}/coauthors/ {user_id}` |
| календарь (`RegulatoryPanel`) | `calendar` | `PUT /api/evga/cases/{id}/calendar/ {holidays, working_dates, confirmed_years}` |
| встречное дело (`CounterChecks.create`) | `→ AuditCase(parentCaseId)` | `POST /api/evga/cases/{id}/counter-cases/ {person_type, bin|iin, name, birth_date, entrepreneur_name, question, group}` |
| `assignQualityExpert(audit, stage, actor, expertId, reason)` | `→ AuditCase` | `POST /api/evga/cases/{id}/quality-assignments/ {stage, expert_id, reason}` |
| `applyAmendment(audit, doc, actor)` | `→ AuditCase` | `POST /api/evga/cases/{id}/documents/{docId}/apply-amendment/` |
| `assignAppeal(audit, actor, expertId)` | `→ AuditCase` | `POST /api/evga/cases/{id}/appeal/assign/ {expert_id}` |
| `recordAdmission(audit, actor, decision, reason, files)` | | `POST /api/evga/cases/{id}/appeal/admission/ {decision, reason, files[]}` |
| `notifyAdmission(audit, actor, files)` | | `POST /api/evga/cases/{id}/appeal/admission/notify/ {files[]}` |
| `saveAppealArguments(audit, actor, rows, submit)` | | `PUT /api/evga/cases/{id}/appeal/arguments/ {rows[], submit}` |
| `decideArguments(audit, actor, approve, comment)` | | `POST /api/evga/cases/{id}/appeal/arguments/decide/ {approve, comment}` |
| `recordNoThirdParties(audit, actor, reason)` | | `POST /api/evga/cases/{id}/third-parties/none/ {reason}` |
| `addThirdParty(audit, actor, notice)` | | `POST /api/evga/cases/{id}/third-parties/` |
| `recordThirdPartyEvent(audit, actor, id, event, date, text, files)` | | `POST /api/evga/cases/{id}/third-parties/{tpId}/events/ {event: receipt|response|forward, date, text, files[]}` |
| прочтение уведомления (`Notifications.tsx`: `readBy`) | | `POST /api/evga/notifications/{nid}/read/`; `GET /api/evga/notifications/` |
| read-модели: `auditDeadlines`, `executionStages/nextExecutionStep`, `executionItemsForCases`, `caseApprovalRoutes`+`getApprovalTasks` | | `GET /api/evga/cases/{id}/deadlines/`, `GET /api/evga/cases/{id}/progress/`, `GET /api/evga/execution/`, `GET /api/evga/tasks/` |

### 7.2 Документ (все — `/api/evga/cases/{id}/documents/{docId}/…`, кроме создания)

| Функция фронта | Сигнатура (фронт) | Endpoint |
|---|---|---|
| `createDocument(audit, kind, actor)` | `→ AuditDocument` | `POST /api/evga/cases/{id}/documents/ {kind}` |
| сохранение черновика (`saveDocument` с изменёнными `values/attachments/group`) | `saveDocument(audit, doc, actor)` | `PUT …/{docId}/ {version, values, attachments, group}` (только `canEdit`) |
| `deleteDocument(audit, id, actor)` | `→ AuditCase` | `DELETE …/{docId}/` |
| `sendDocumentToQuality(doc, actor)` | | `POST …/send-to-quality/` |
| `submitDocument(doc, actor, reviewers, approver, comment, mode, stages?, audit)` | | `POST …/submit/ {stages:[{id, mode, reviewer_ids[]}] \| reviewer_ids[], mode, approver_id, comment}` |
| `approveDocument(doc, actor, expectedVersion, audit)` | | `POST …/approve/ {expected_version}` |
| `returnDocument(doc, actor, comment, expectedVersion, audit)` | | `POST …/return/ {comment, expected_version}` |
| `rejectDocument(doc, actor, comment, expectedVersion, audit)` | | `POST …/reject/ {comment, expected_version}` |
| `activateDocument(doc, actor)` | | `POST …/activate/` |
| `createNextVersion` / `createReturnedRevision` / `createRejectedRevision` / `reviseMainDocument` / `revisePreparationDocument` / `reviseMainQuality` / `createResponseRevision`+`reviseExecutionResponse` / `renewQuality` | все `→ AuditDocument` с новой версией | `POST …/revisions/ {reason: "quality"|"returned"|"rejected"|"main"|"preparation"|"quality2"|"response"|"renew-quality"}` (сервер выбирает функцию по kind/статусу; либо отдельные `…/revise/`, `…/renew-quality/`) |
| `recallDocument(doc, actor)` | objection-result | `POST …/recall/` |
| `sendInstructionToKvga(audit, doc, actor, confirmerId)` | | `POST …/kvga/send/ {confirmer_id}` |
| `decideInstructionKvga(audit, doc, actor, decision, comment, expectedVersion)` | | `POST …/kvga/decide/ {decision: confirm|return, comment, expected_version}` |
| `requestPreparationQuality(audit, doc, actor)` | instruction | `POST …/request-quality/` |
| `requestMainQuality(audit, doc, actor)` | violations | `POST …/request-quality/` (тот же endpoint, ветвление по kind) |
| `sendPreparationForApproval(audit, doc, actor)` | | `POST …/send-for-approval/` |
| `requestMainApproval(audit, doc, actor)` | violations/evidence | `POST …/request-approval/` |
| `requestReportGroupSignatures(audit, doc, actor)` | report | `POST …/group-signatures/request/` |
| `signReportGroup` / `signAssignmentGroup(audit, doc, actor, expectedVersion)` | | `POST …/group-signatures/sign/ {expected_version}` |
| `approveAssignmentGroup(audit, doc, actor, expectedVersion)` | assignment | `POST …/group-signatures/approve/ {expected_version}` |
| `sendRegistryToConfirmer(audit, doc, actor, confirmerId)` | violations | `POST …/registry-confirmation/send/ {confirmer_id}` |
| `decideRegistryConfirmation(audit, doc, actor, decision, comment, expectedVersion)` | | `POST …/registry-confirmation/decide/ {decision, comment, expected_version}` |
| `signMainQuality(audit, doc, actor)` | quality2 | `POST …/quality/sign/` |
| `submitMainQualityToHead(audit, doc, actor)` | quality2 | `POST …/quality/submit-to-head/` |
| `performRegistration(doc, actor, action, comment, registrationNumber)` | | `POST …/registration/ {action: send|accept|return, comment, number}` (accept/return — от интеграции ЕРСОП) |
| `deliverDocument(doc, actor, action, response, attachments, audit)` | | `POST …/delivery/ {action: send|acknowledge|respond|sign|object|refuse, response, attachments[]}` |
| `transitionInformationRequest(audit, doc, actor, action, {text, attachments, deadline}, now)` | request/counter-request | `POST …/information-request/ {action, text, attachments[], deadline}` |
| `addQualityConclusion(doc, actor, conclusion)` (legacy) | | не переносить (заменён документом quality*) |
| реестр нарушений: `saveRiskSelection`, `removeRegistryRisk`, `assignRegistryResult`, `repairRegistry`, `linkedViolation`, `finalizeRegistry` | чистые функции над `values` | клиентские преобразования `values`; сервер валидирует `registryValidation` при сохранении/отправке (`PUT …/{docId}/`) |
| `validateDocument(audit, doc, version)` | | `POST …/validate/` (опционально) и обязательно внутри submit/activate/send-to-quality |

Демо-функции (`createDemoCase`, `advanceDemoCase`, `prepareDemoMainStage`, `workflowSampleCases`, `preparedCases`, `addPlannedSampleCases`, `addRegistrySampleCases`, `enrichSampleQualityForms`, `fillDemoDocument`) — не API, а генераторы фикстур; ценны как pytest-фикстуры «дело на шаге N», т.к. используют настоящие переходы.

---

## 8. Что зафиксировано тестами — перечень сценариев для бэкенд-тестов

Все тесты — `node --test` над чистыми функциями (без React), т.е. переносятся 1:1 в pytest над сервисным слоем. Ниже — файлы и сценарии (названия тестов дословно).

**tests/bpmn-preparation.test.ts** (13): черновики независимы, согласование → КВГА/КК → окончательное утверждение после КК; опциональные план/задание пропускаются только при отсутствии; адресность КВГА, проверка версии, причина возврата, новая редакция без `preparation`; задание требует подписи каждого участника и решения руководителя группы; новая версия источника инвалидирует согласование/КК и не наследует подписи; prep нельзя активировать напрямую и без контекста дела; встречное поручение: согласование → КВГА → утверждение без КК; устаревшая v1 не может решать/затирать v2 и архив; параллельные решения по одной версии сохраняют все ранние; план после КК блокирует утверждение до повторного согласования; возврат КВГА оставляет дело открытым, следующая редакция требует нового подтверждения; правки черновика сохраняются и отправляются без ослабления проверок; у задания нет фиктивного утверждающего.

**tests/bpmn-main-workflow.test.ts** (16): отчёт открывает реестр, отдельное подтверждение, КК2, последовательное утверждение, параллельная отправка ОА; отсутствие доказательств не блокирует; все подписи РГ обязательны, чужой участник/повтор/stale запрещены; подписанный отчёт нельзя изменить старым снимком; новая редакция отчёта сохраняет историю и заново требует всю РГ; возвращённый отчёт проходит новое подписание; подтверждение реестра адресное, возврат с причиной; КК2 без reviewers, подписывает эксперт, решает руководитель; подпись эксперта защищает содержимое; новые доказательства аннулируют подтверждение и КК; редакция программы после подписей РГ блокирует отчёт; ОА не подписывает устаревший пакет; устаревшее подписанное КК2 восстанавливается новой редакцией; отказ объекта фиксирует только автор/соавтор; уникальность участников группы; commit повторно проверяет комплект (аудитор и руководитель КК).

**tests/bpmn-quality-assignment.test.ts** (7) и **bpmn-main-assignment.test.ts** (4): только `quality-head` назначает эксперта на каждый этап; неназначенный эксперт не создаёт заключение, `ownerId` проставляется; замена переносит незавершённое заключение и отзывает доступ; явное назначение не переписывает утверждённые заключения; решение из старой формы не затирает назначение; A→B→A не стирает промежуточные назначения; заменяющий эксперт дорабатывает возврат; для КК2: замена подписавшего эксперта создаёт новую версию без чужой подписи, замена после отправки супер-седит маршрут, утверждённое заключение неизменно, неподписанный проект передаётся без редакции.

**tests/bpmn-information-requests.test.ts** (10): обычное требование acknowledge→provide→accept, ответ ≠ принятие; встречное ждёт отдельного review; resend сохраняет файлы и историю раунда; refuse/reject терминальны и требуют обоснование; срок стартует после ознакомления, permits resend/mark-refused; встречное — автоматический отказ по сроку; ответ на проверке не просрочивается; legacy delivery → received; отказ чужим аудиторам/закрытому делу/stale/старым версиям; срок обязателен и в будущем.

**tests/bpmn-main-validation.test.ts** (4): отчёт без документа доказательств; доказательства требуют файлы и реквизиты; версия реестра из `sourceVersions`; вопросы отчёта по зафиксированной программе.

**tests/full-process.test.ts** (10): сквозной маршрут до закрытия; КК с замечаниями блокирует этап, v2 и повторный КК сохраняют v1; регистрация до основной проверки, возврат ЕРСОП; prep согласуются до КК, утверждение ждёт заключения; копирование вопросов/нарушений без изменения источников; ознакомление после отправки; отдельный цикл встречной проверки; валидация формы до согласования (все 105 видов имеют формы/секции); несколько экземпляров требований с уникальными номерами; полный маршрут с заполнением всех обязательных форм.

**tests/workflow.test.ts** (7): Q08 создание документа не порождает другие; Q06 порядок согласующих; Q05 возврат с точным статусом и замечанием; пустой/дублирующий маршрут; Q07 v2 после заключения, v1 неизменна; Q02 этап требует КК предыдущих; Q01/Q03 валидация дела.

**tests/evga-integration.test.ts** (18): параллельные задания; возврат сохраняет старую редакцию; реестр исполнения (claimed/confirmed, evidence, href); продление проекта не меняет срок; новый ответ копирует действующее предписание; ответ на прежнюю версию не подтверждает новую; завершение ждёт утверждённого ответа к текущим версиям; совместимость legacy-ответов; переназначение возвращённого результата возражений; этапы маршрута; отклонение завершает редакцию; legacy reject; presentation; уточнение результата/продление ждут финального решения; активный ответ неизменяем; устаревшее сохранение не стирает маршрут; legacy-ответ без ссылок; нормализация legacy signerAction.

**tests/appeals-amendments.test.ts** (8): снимок содержимого для поручения; расчёты ИРПИ/рабочих форм; апелляция полный цикл (назначение → обоснования → подпись → комиссия → отправка); отказ в рассмотрении и извещение; атомарные новые версии по поручению; поручение не затирает изменённую/согласуемую версию; третьи лица; расчёты существенности.

**tests/npa-compliance.test.ts** (16): подпись с возражениями; отказ с обоснованием и канцелярией; заключение ждёт решения по возражениям и КК; частичная/полная отмена нарушений; завершение не обойти мерами; рекомендации обязательны; поручение не направить до регистрации; удаление проекта; история и уведомления; сроки КК 2/5/10/7/3/20; календарь (выходные, праздники, переносы, граница года); состав рабочих форм (59+3) и неприменимость; сохранность вложений при доработке; соавтор; продление изменяет срок и основание; доказательства перед КК; риск по вопросам.

**tests/violation-registry.test.ts** (11): пары риск-вопрос, стабильные id; валидация перед согласованием (результаты, трудозатраты, двуязычный комментарий); наследование контекста нарушениями; нельзя снять вопрос/объект с данными; дубли/битые ссылки; идемпотентный repair; остаток суммы; снимок вопросов программы; демо-реестры валидны.

**tests/shared-approval-workflow.test.ts** (27) — контракт маршрута (§4); **tests/shared-execution.test.ts** (16) — контракт сроков исполнения; **tests/execution-progress.test.ts** (3) — ход исполнения; **tests/quality-conclusion.test.ts** (4) — печатная форма КК; **planned-demo/demo-readiness/reference-data/audit-format/navigation/pdf-export** — демо-данные, справочники, поиск, навигация, PDF (для бэкенда не критичны, кроме `reference-data`: печатные реквизиты версии фиксируются в `values.printContext`).

---

## 9. Открытые вопросы и рекомендации для бэкенда

1. **Идентификация автора по ФИО** (`audit.author === actor.name`, `doc.author`, `signatures[].person`, `history.actor`) — заменить на `user_id`, оставив ФИО как денормализованный снимок.
2. **Жёстко зашитые id** (`"approver"`, `"quality-head"`, `"commission-chair"`) — перевести в роли Keycloak (§5.2); уточнить у команды, кто «руководитель органа аудита» для `assignCoauthor` и «руководитель подразделения» для `decideArguments`.
3. **Состояние «Согласован» и сигнал `signer: waiting`** — маршрут после согласующих замирает до явного `send-for-approval`/`request-approval`; в БД удобнее хранить `route.status = "review"` + флаг `signer_activated=false`, а не патчить проекцию как `caseApprovalRoutes`.
4. **Оптимистичная блокировка**: фронт сравнивает JSON-снимки (`mainCurrentBlock`, `preparationCurrentBlock`, `assertCurrent`, `saveDocument`). На сервере достаточно `expected_version` + `SELECT … FOR UPDATE` дела и повторной проверки предусловий в транзакции — все тексты ошибок («Открыта устаревшая версия документа. Обновите дело», «Состояние документа изменилось…», «Документ изменился. Обновите дело перед сохранением решения») стоит сохранить.
5. **ЕРСОП**: `performRegistration accept/return` во фронте инициирует аудитор («Тестовый ответ»); на сервере это callback интеграции (см. старый n8n: статусы регистрации). Номер по умолчанию `УЧ-…` — заглушка.
6. **Таймеры**: истечение требований (`overdue`/`refused` для counter-request), просрочка исполнения — вычисляются на чтение; нужен job или вычисление в сериализаторе с `now`.
7. **Уведомления** во фронте — массив в деле; на сервере — отдельная таблица `notification(recipient, case, document, text, read_at)` с правилом получателей из §2.12 п.13.
8. **QC-маршрут выбора КК2/КК КВГА (`qc_route`)** в BPMN вычислялся внешним сервисом — во фронте не смоделирован (`docs/bpmn-main-stage-2026-09-21.md`).
9. **Не реализовано во фронте** (значит, требования нужно брать из старой системы/ТЗ): административное производство, месячная выборка 2-го уровня КК, автоматическое закрытие дела при отрицательном КВГА, автоподпись отчёта по таймеру, реальные ЭЦП, доставка внешним адресатам.
10. **Демо-генераторы** (`demoScenario.ts`, 1340 строк) используют настоящие переходы — идеальные фикстуры для интеграционных тестов бэкенда («дело на этапе КК2», «половина процесса» и т.п.).
11. `addQualityConclusion` (`qualityControlRules.ts`) — устаревший путь (текстовое заключение на активной версии), оставлен для совместимости; в API не переносить.
12. `Person.id` участников РГ должны совпадать с id аккаунтов — иначе подписи РГ невозможны («Нет демонстрационной учётной записи участника РГ» в демо); на сервере — FK на сотрудника.
