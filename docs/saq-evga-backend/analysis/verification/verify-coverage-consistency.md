# Верификация `design-final.md`: покрытие фронта и внутренняя согласованность

Проверяемый документ: `reports/design-final.md` (1868 строк, прочитан целиком). Первоисточники: `reports/evga-workflows.md` (§2–§7), `reports/evga-ui-actions.md` (§3.2–§3.3), `src/evga/saq-evga-test/src/types.ts`, `src/modules/evga/{documentStateMachine,workflow,mainWorkflow,preparationWorkflow,informationRequests,appeals,amendments,qualityAssignment,thirdParties,executionDecision,executionItems,documentFactory,deadlines,approvalTasks,caseAccess,caseRules,reviewParticipants,printContext,workingPapers}.ts`, `src/data/{documentMatrix,demoData}.ts`, `src/modules/evga/forms/formLinks.ts`, `src/shared/workflow/approvalRoute.ts`, `src/shared/execution/execution.ts`, `src/pages/{ApprovalTasks,CaseWorkspace,DocumentWorkspace,CaseForm}.tsx`, `src/modules/evga/components/{CounterChecks,DocumentActions,ReferencePrintForm,QualityPrintForm,Notifications,QualityAssignmentPanel}.tsx`, `tests/*.test.ts`. Пути фронта ниже — относительно `src/evga/saq-evga-test/src/`.

Итог: **39 замечаний — 1 blocker, 7 major, 31 minor.** Общий вывод: проект покрывает практически все мутации и read-модели фронта (см. раздел «Проверено и подтверждено»), но содержит один сквозной дефект RBAC (K-01), который делает невозможными потоки КК и апелляции через HTTP-слой, и ряд расхождений с правилами фронта, которые провалят портированные 1:1 pytest-сценарии (C-09, C-10, K-02, K-05).

Обозначения: C-xx — линза 1 «покрытие фронта», K-xx — линза 2 «внутренняя согласованность». Severity: blocker — проект в этом месте нельзя реализовать без переработки; major — реализация по тексту даст неверное поведение/провал тестов; minor — неточность, требующая уточнения текста или сида.

---

## Линза 1. Покрытие фронта

### C-01 · major · §6.2 (read-модель `DocumentVersion`), §10.1 (`evgaAdapter`)

**Проект утверждает.** Сериализатор версии отдаёт «форму `DocumentVersion` фронта», перечень полей §6.2 — `version, status, …, approval_routes, registration, delivery, …, history`; `evgaAdapter` «почти identity».

**Первоисточник.** `types.ts:162-164` — `reviewers: string[]`, `reviewerIndex: number`, `approver: string` объявлены **обязательными**; используются в UI и печати: `modules/evga/components/DocumentActions.tsx:105,123` (лента участников маршрута по `v.reviewers`/`v.approver`/`v.reviewerIndex`), `modules/evga/components/ReferencePrintForm.tsx:145` (`version.approver` → ФИО утверждающего в печатной форме, а формы и печать «не трогаются»), `pages/DocumentWorkspace.tsx:300` (условие отзыва `reviewerIndex === 0`). Раздел §10.2 удаляет только `migrateLegacyApprovalRoutes`, но не потребителей этих полей.

**Исправление.** Добавить в DTO §6.2 производные поля: `reviewers` = id согласующих текущего маршрута в порядке этапов, `reviewer_index` = число `approved`, `approver` = id signer'а (`""` для assignment/report); зафиксировать в `evgaAdapter.toAuditDocument` их заполнение и указать, что `ReferencePrintForm` печатает `approver`.

### C-02 · minor · §4.1, §6.11 (`AttachmentRef {id, name, type, size, url}`)

**Проект.** Файл в JSON — только `AttachmentRef` без иных полей.
**Первоисточник.** `types.ts:47-54` — `Upload.description?`; печатные формы выводят его: `QualityPrintForm.tsx:377`, `ReferencePrintForm.tsx:228`.
**Исправление.** Добавить `description` в `core.Attachment` (аддитивно, `blank=True`) и в `AttachmentRef`; upload-сериализатор принимает `description`.

### C-03 · minor · §4.7 (`DocumentSourceVersion.content_snapshot_hash`), §6.2, §10.2 (этапы 3–5)

**Проект.** `contentSnapshot` заменён на SHA-256; клиентские `*Block` до этапа 5 остаются «подсказками `disabled`».
**Первоисточник.** `modules/evga/amendments.ts:63-65` — `amendmentBlock` сравнивает `sourceVersions[].contentSnapshot` со строкой `amendmentSnapshot(target)` = `JSON.stringify({values, group})`; `documentFactory.ts:81` пишет строку. С хешем клиентская подсказка на этапах 3–4 всегда вернёт «Содержание документа … изменилось» и кнопка «Применить» будет заблокирована до переноса `AmendmentsPanel` на API (этап 5).
**Исправление.** Либо отдавать `contentSnapshotHash` и на этапе 3 заменить в `amendments.ts` сравнение на сравнение хешей, либо перенести `AmendmentsPanel` на `available_actions` уже на этапе 3.

### C-04 · minor · §4.11 (`ErsopRegistrationStatus`), §6.2 (`registration{status(label)}`)

**Проект.** 7 статусов с label «Не направлена», «Отправлена (на рассмотрении)», «Возвращена (отказ)», «Ошибка обмена» и т.д.; адаптер кладёт label в `registration.status`.
**Первоисточник.** `types.ts:172-177` — union из трёх строк `"Отправлена" | "Зарегистрирована" | "Возвращена"`; `workflow.ts:607-621`, `amendments.ts:34`, `workflow.ts:84` сравнивают с ними буквально.
**Исправление.** В §6.2 задать таблицу: `DRAFT → registration = null`, `SENT|PENDING|ERROR → "Отправлена"` (+ отдельные поля `code`, `error`), `REGISTERED → "Зарегистрирована"`, `RETURNED|REJECTED → "Возвращена"`.

### C-05 · minor · §4.7 (`ConfirmationStatus`), §6.2 (`preparation.kvga.status`, `main.confirmation.status`)

**Проект.** `ConfirmationStatus = PENDING|CONFIRMED|RETURNED` (UPPER); в §6.2 форма `kvga{confirmerId, status, …}` без указания регистра.
**Первоисточник.** `types.ts:137,150` — `"pending" | "confirmed" | "returned"`; `preparationWorkflow.ts:116,126,191`, `mainWorkflow.ts:141` сравнивают с нижним регистром.
**Исправление.** Явно: сериализатор отдаёт `status.lower()` (или коды enum сделать строчными, как `ApprovalRouteStatus`).

### C-06 · minor · §5.2 (`registry.form_links`), §6.1 (`GET /cases/{id}/form-links/?key=`)

**Проект.** Ответ `{violationId[], riskId[], questionId[], resultId[], transfer[], claim[]}`.
**Первоисточник.** `modules/evga/forms/formLinks.ts:17-49` — ключи `violationId, riskId, questionId, resultId, field`; ключей `transfer`/`claim` нет. Кроме того `formLinks(audit, values)` зависит от **несохранённых** `values` редактируемой формы (`values.violations ?? latestValues(...)`, строки 7–14), т.е. GET без тела не воспроизводит функцию.
**Исправление.** Ключи ответа = `violationId, riskId, questionId, resultId, field`; эндпоинт принимает `?document=&version=` (берёт сохранённые `values`) или `POST …/form-links/ {values}`; убрать `transfer/claim`.

### C-07 · minor · §4.7 (`AuditDocument.stage`: «рабочие формы: number>8 → MAIN»)

**Первоисточник.** `data/documentMatrix.ts:163-168` — `stage = p.id.startsWith("financial") && p.number > 5 ? 1 : 0`.
**Исправление.** В сиде `seed_evga_document_types`: `financial-rd-06…` и далее → `Stage.MAIN`, `compliance-*` — всегда `PREPARATION`.

### C-08 · minor · §4.7 (`Workflow` — комментарии-перечни видов)

**Проект.** `ROUTE` перечисляет «claim-*», `DIRECT` — «claim-decisions»; виды `request`, `counter-request` не отнесены ни к одному семейству.
**Первоисточник.** `documentStateMachine.ts:137-149` — `directActivation` включает `claim-decisions`, `reply-law`, `obstruction`, `counter-obstruction`, `objections`, `weekly`, `account`, `counter-account`, `notification`, `counter-notification` + рабочие формы; `request`/`counter-request` — общий маршрут (не direct, не requiresQuality), затем T7.
**Исправление.** В `ROUTE`: `claim-invalid/-dishonest/-recover/-liquidation`, `request`, `counter-request`; `claim-decisions` — только `DIRECT`. Зафиксировать это в `document_types.json`.

### C-09 · major · §4.5, §4.6 (`AuditCase.subject` NOT NULL), §5.2 (`create_counter_case(person_type, subject_bin=None, person_iin, …)`), §6.1

**Проект.** `subject = FK("subjects.Subject", on_delete=PROTECT)` без `null=True`; для ФЛ «поля на `AuditCase`», `SubjectPerson` не используется.
**Первоисточник.** `modules/evga/components/CounterChecks.tsx:65-79` — для «Физическое лицо» дело получает `object = {bin: iin, ru: name, opf: "Физическое лицо", …}`; `Subject` prof — юрлицо с `bin_validator`. Следовательно у встречного дела-ФЛ нет `Subject`, и `create_counter_case` по тексту проекта нарушит NOT NULL.
**Исправление.** Либо `subject = FK(..., null=True)` + `CheckConstraint(Q(subject__isnull=False) | Q(person_type=NATURAL, person_iin__regex=r"^\d{12}$"))`, а `subject_snapshot` строится из person-полей; либо явно решить «для ФЛ создаётся `Subject` с `subject_type=natural`, `bin=iin`» и снять `bin_validator`-ограничение для этого типа. Также в `as_snapshot()`/`CaseListItem.subject` описать ФЛ-вариант.

### C-10 · major · §5.4.3 (`group-approve`: guard «все не-лидеры подписали», эффект «подпись лидера»)

**Первоисточник.** `preparationWorkflow.ts:330-336` — `approveAssignmentGroup` требует подписи **всех** участников `v.group` (включая лидера): `v.group.some(person => !groupSignatures.some(s => s.personId === person.id))`; лидер подписывает заранее через `signAssignmentGroup` (строки 280–312, роль `auditor`/`invited-specialist`, любой участник группы). Утверждение подписи не добавляет (строки 337–343). Тест `bpmn-preparation`: «задание требует подписи каждого участника и решения руководителя группы». По тексту проекта при «подписи лидера» на approve сработает `UniqueConstraint(version, signer, kind=GROUP)` → «Ваша подпись уже сохранена».
**Исправление.** Guard: `DocumentSignature(kind=GROUP)` есть у каждого `VersionParticipant` (включая лидера); `approve_assignment_group` не создаёт `GROUP`-подпись (допустимо `ACTIVATION`), только `activated_at/by` + `commit_version`.

### C-11 · minor · §5.4.4 (`group-request`: guard `main_preparation_block`)

**Первоисточник.** `mainWorkflow.ts:212-231` — `requestReportGroupSignatures` проверяет только `assertAuthor` (= `mainCurrentBlock`), статус/kind/`groupRequestedAt`, состав группы; `mainPreparationBlock` проверяется на `signReportGroup` (строка 240) и в `mainSubmissionBlock`.
**Исправление.** Убрать `main_preparation_block` из guard `group-request` (или пометить как сознательное ужесточение и добавить тест).

### C-12 · minor · §5.4.2 (`activate`: guard «`creation_block` пуст»)

**Первоисточник.** `documentStateMachine.ts:150-163` — `activateDocument` проверяет `directActivation`, `canSubmit`, совпадение `ownerId`; `creationBlock` не вызывается (он проверен при создании). Повторная проверка при активации заблокирует, например, `account` после того, как `quality[0]` стал `false` из-за новой редакции prep-документа.
**Исправление.** Убрать `creation_block` из guard активации (оставить `validate_document`).

### C-13 · minor · §5.2 (`assign_quality_expert`), §5.4.5

**Проект.** Guard «эксперт не в `case.participants`»; эффекты: `unassigned_at`, уведомление, событие.
**Первоисточник.** `qualityAssignment.ts:23-37` — проверки: только `quality-head`, дело открыто, `stage ∈ {0,1,2}`, эксперт роли `quality`, «Этот эксперт уже назначен», причина при замене. Проверки на участие в РГ нет (она в `validateDocument` для `version.group`). Пропущен эффект строк 118–122: если версия `quality{N}` не `Активный` и не подписана — `ownerId := expertId`, `ownerRole := "quality"`, событие в историю версии.
**Исправление.** Убрать лишний guard, добавить эффект перевода `owner` неактивной версии на нового эксперта.

### C-14 · minor · §5.4.1 (`send_to_quality`)

**Первоисточник.** `documentStateMachine.ts:203-208` — дополнительный guard `!(status === "Возвращен на доработку" && currentApprovalRoute(v))` («Направление на контроль качества доступно аудитору для проекта документа.»).
**Исправление.** Добавить в строку таблицы: из `RETURNED` — только если у версии нет маршрута (иначе сначала `revise`).

### C-15 · minor · §5.3 (`ActionSpec("ir-*")`), §5.4.8, §6.3/§6.9 (тела запросов)

**Первоисточник.** `informationRequests.ts:146-148` — текст обязателен для `refuse`, `reject`, `resend`, `mark-refused` («Укажите обоснование решения»); `provide` — текст или файл; `resend` требует `deadline` (строки 155–159).
**Проект.** `requires_comment=True` только у `ir-reject`, `ir-mark-refused`; `ir-refuse` (кабинет) и `ir-resend` — без флага; payload-сериализатор `ir-resend` с обязательным `deadline` не указан.
**Исправление.** `ir-refuse`, `ir-resend` → `requires_comment=True`; `ir-resend` → `payload_serializer=ResendSerializer(deadline required, > now)`.

### C-16 · minor · §5.3 (`apply_action`), §5.8, §6.13 (текст 409)

**Проект.** Единый текст `expected_version` → «Открыта устаревшая версия документа. Обновите дело».
**Первоисточник.** `documentStateMachine.ts:336,444,500` — для approve/return/reject: «Открыта устаревшая версия документа. Решение недоступно.»; «…Обновите дело» — текст `preparationCurrentBlock`/`mainCurrentBlock`/`assertCurrent` (`preparationWorkflow.ts:48,167`, `mainWorkflow.ts:32`). `evga-ui-actions.md` §3.3 предписывает 409 с текстом «Решение недоступно.».
**Исправление.** `ActionSpec.stale_message` (по умолчанию «…Решение недоступно.», для сервисов prep/main/T7 — «…Обновите дело»).

### C-17 · minor · §11.1 (таблица сценариев)

**Первоисточник.** Подсчёт `test(` по `tests/*.test.ts`: `bpmn-main-workflow` 17 (в проекте 16), `shared-approval-workflow` 26 (27), `npa-compliance` 17 (16); не отображены `audit-format.test.ts` (6) и `pdf-export.test.ts` (3); суммарно ≈199 сценариев, а не 218.
**Исправление.** Поправить числа, добавить строки для `audit-format` (→ `evga_cases/tests/test_audit_format.py`) и `pdf-export` (клиентский — остаётся во фронте).

### C-18 · minor · §4.7 (`KvgaConfirmation`, `DocumentDelivery` — OneToOne), §5.4.3, §5.4.8

**Первоисточник.** `preparationWorkflow.ts:185-202` — после возврата КВГА по `counter-instruction` статус остаётся `Согласован`, и `sendInstructionToKvga` **той же версии** перезаписывает `preparation.kvga` новым `confirmerId`/`pending`; `informationRequests.ts:164` — `resend` перезаписывает `delivery = {sentAt}` той же версии.
**Проект.** Эффекты описаны как «`KvgaConfirmation(PENDING)`», «`DocumentDelivery(sent_at)`» — при OneToOne повторное создание невозможно.
**Исправление.** Явно: `update_or_create` (сброс `status/decided_at/comment`, замена `confirmer`; для `ir-resend` — обновление `sent_at`, история — в `AuditEvent`).

### C-19 · minor · §8.5 (`recipients_for_version`), §5.2 (`notify`)

**Первоисточник.** `appeals.ts:37-56` — все действия по апелляции уведомляют `area === "appeal"` + автор/соавторы + аккаунт `approver` + все `object`; `appeals.ts:77-87` — назначенному эксперту при переназначении; `qualityAssignment.ts:123-133` — новому и прежнему эксперту; `caseAccess.ts:18-28` — соавтору. Третьи лица уведомлений не пишут.
**Проект.** Правило только «по версии» + фраза «плюс события дела».
**Исправление.** Добавить `recipients_for_case_event(case, event_type)` с этими четырьмя правилами.

### C-20 · minor · §7.3 (`accountFromUser`: `area: "appeal"` только для комиссии)

**Первоисточник.** `data/demoData.ts:272-292` — `area: "appeal"` также у `appeal-head`, `appeal-expert(-2)`; используется в `workflow.ts:519` и `appeals.ts:47` (получатели уведомлений).
**Исправление.** `area = "appeal"` для всех ролей `evga-appeal-*` и комиссии.

---

## Линза 2. Внутренняя согласованность проекта

### K-01 · **blocker** · §5.3 (`ActionSpec.domain/levels`), §6 (уровни `D:E`, `D: APPROVE/SIGN`), §6.3 (`PATCH versions/{n}/`, `DELETE`, `POST /cases/{id}/documents/`), §7.3 (права ролей)

**Проект утверждает.** `HasDomainLevel` «без изменений»; у `ActionSpec` домен по умолчанию `evga_cases`, уровень `{EDIT}`; `approve/return/reject` — `evga_cases: {APPROVE, SIGN}`; `submit`, `revise`, `deliver`, `validate`, PATCH/DELETE/создание документа — `evga_cases: EDIT`. При этом §7.3 даёт `evga-quality` только `evga_cases: VIEW` (+ `evga_quality: EDIT, SIGN`), `evga-qc-head` — `evga_cases: VIEW`, `evga-appeal-expert` — `evga_cases: VIEW`, `evga-appeal-commission-member/-chair` — `evga_cases: VIEW`.

**Следствие (по тексту проекта).** Эксперт КК не может создать `quality1/2/3` (`POST /cases/{id}/documents/` D:E), сохранить черновик (`PATCH` D:E), направить `quality1/3` на согласование (`submit` D:E), создать редакцию (`revise` D:E), удалить проект; руководитель КК не может утвердить/вернуть заключение (`approve/return/reject` D:APPROVE/SIGN); сотрудник апелляции не может создать/направить/отозвать/направить объекту `objection-result` (`deliver` D:E); члены и председатель комиссии — согласовать/утвердить его. Это ломает §5.4.5, §5.4.10, сценарии `bpmn-quality-assignment` (7), `bpmn-main-workflow` (КК2), `appeals-amendments` (8), `evga-integration` (reassign). Проверка §7.5 «объектные права в сервисах» не помогает — 403 возникает раньше, в `HasDomainLevel`.

**Исправление (одно из двух, зафиксировать в §5.3 и §7.3).** (а) Проще: выдать `evga-quality`, `evga-qc-head`, `evga-appeal-expert` уровень `evga_cases: EDIT`, `evga-qc-head` и `evga-appeal-commission-chair` — `evga_cases: SIGN`, `evga-appeal-commission-member` — `evga_cases: APPROVE`; адресность по-прежнему в сервисах. (б) Точнее: `ActionSpec.domain` → функция `domain_for(document)` (`quality*` → `evga_quality`, `objection-result`/`objections` → `evga_appeals`, иначе `evga_cases`), `DocumentActionView.required_domain` вычисляется после `get_object_or_404`; то же для `AuditDocumentViewSet.partial_update/destroy` и `CreateDocumentView`. Добавить в `test_actions_api.py` матрицу «роль × действие × вид».

### K-02 · major · §5.3 (`apply_action`), §5.9

**Проект.** `version = document.active_version` берётся **до** вызова `spec.service(...)`; далее `version.refresh_from_db(); row_version += 1; commit_version(version); record_event(version, …); ActionResult(version=version)`.
**Противоречие.** Для `revise` (все 9 функций §5.2), `submit` из `RETURNED` (создаёт `create_returned_revision`, §5.4.1), `assign_quality_expert` с подписанным `quality2` сервис создаёт **новую** версию; по псевдокоду `row_version`, `commit_version` (эффекты, уведомления, `compute_quality`), событие и ответ относятся к старой, замороженной версии (`frozen_at`), а новая версия остаётся без события «Создана версия vN…» в журнале действия.
**Исправление.** После сервиса: `version = document.active_version` (перечитать), либо сервис возвращает версию-результат; `record_event` писать на неё; для revise — `status_from` старой версии в `metadata`.

### K-03 · major · §7.3 (`accountFromUser`: «`role` = первая активная роль по приоритету»), §5.3 (`if actor_role(actor) not in spec.roles: raise PermissionDenied`), §5.2 (`permissions.actor_role`)

**Противоречие.** Пользователь с несколькими `RoleAssignment` (например, `evga-auditor` + `evga-reviewer`, или `evga-approver` + `evga-auditor`; legacy `evga_users_with_roles` допускает несколько ролей, §4.13) получает одну «роль фронта» и теряет остальные: аудитор-согласующий не сможет `approve`, руководитель-аудитор — `submit`. Во фронте у демо-аккаунта одна роль (`data/demoData.ts`), но проект переносит проверку на реальных пользователей.
**Исправление.** `actor_roles(user) -> frozenset[str]`; условие `spec.roles & actor_roles(actor)`; `available_actions` — объединение по всем ролям; `accountFromUser` отдаёт `roles[]` и `role` (приоритетную) только для UI.

### K-04 · major · §4.2 (`AuditEvent.case = FK("evga_cases.AuditCase")`), §2.1 правила 1–3 (аддитивность общих приложений, «`core` … считаются чужими»)

**Противоречие.** Общее приложение `core` получает FK на таблицу доменного приложения ЭВГА: миграция `core/000N_evga_audit_event` зависит от `evga_cases.0001`, при слиянии в монорепо prof-`core` будет ссылаться на `evga_cases`; это прямо противоречит принципу «prof-каркас не знает о доменах» и правилу 2 §2.1 (миграции общих приложений не зависят от доменных).
**Исправление.** `AuditEvent.case_id = UUIDField(null=True, blank=True, db_index=True)` без FK (целостность — сервисом `record_event`), либо хранить связь в `metadata` + индекс, либо отдельная таблица `evga_cases.CaseEventLink(event OneToOne core.AuditEvent, case FK)`; `GET /cases/{id}/history/` строится по ней.

### K-05 · major · §4.1 («вложения — `GenericRelation`»), §5.4.1 (`revise` «копирует values/attachments/group»), §5.2 (`attachments.delete_version_attachment` только `DRAFT`), §6.11

**Противоречие.** Во фронте новая версия получает копию `attachments: Upload[]` и `values` со ссылками на файлы строк (`documentStateMachine.ts:550-575`, `amendments.ts:121-137`). В проекте `Attachment` принадлежит одной версии (`content_object`), а `AttachmentRef.id` в `values` новой версии будут указывать на вложения **старой** версии: download-view проверяет права «по версии», `DELETE …/versions/{n}/attachments/{aid}/` в новом `DRAFT` удалит файл замороженной версии, `assert_attachment_retention` сравнивает id и не заметит подмену. Процедура клонирования не описана.
**Исправление.** В `revisions.create_revision`: клонировать строки `Attachment` (новый id, тот же `object_key/checksum/size`, `content_object` = новая версия), переписать `AttachmentRef.id` в `values` и `slot`; `delete_version_attachment` удаляет объект MinIO только если `object_key` больше никем не используется. Зафиксировать в §5.2 (`attachments.clone_for_version`).

### K-06 · minor · §5.3 (`ActionSpec("ersop-send", statuses={ACTIVE, RETURNED})`) vs §5.4.6 (guard «`status == ACTIVE` («Сначала утвердите документ»)»)

**Первоисточник.** `workflow.ts:605` — для всех действий регистрации `v.status !== "Активный"` → ошибка; `RETURNED` в §5.4.6 относится к статусу **регистрации**, а не документа.
**Исправление.** `statuses={ACTIVE}`; условие «регистрация отсутствует или `RETURNED/REJECTED/ERROR`» — в сервисе.

### K-07 · minor · §5.3 (`ersop-register`: `domain=EVGA_ADMIN, levels={DECIDE}, roles={"auditor","evga-admin"}`) vs §6.3 («на демо — также `auditor`») vs §7.3 (у `evga-auditor` нет `evga_admin`)

**Исправление.** На стенде выдавать `evga-auditor` `evga_admin: DECIDE` через `seed_evga_roles --demo`, либо `domain=EVGA_CASES` с фильтром по `roles` и флагом `EVGA_ALLOW_STUB_REGISTRATION`.

### K-08 · minor · §1 (решение 3 «восемь приложений `apps/evga_*`»), §13 («8 `evga_*` + `notifications`»), §9 («17 ролей §7.3»), §13 («17 ролей `evga-*` + `observer`»)

**Факт.** §3.1 перечисляет **семь** `evga_*` (`evga_cases, evga_documents, evga_workflow, evga_ersop, evga_execution, evga_appeals, evga_cabinet`) + `notifications`; §7.3 содержит 15 ролей `evga-*` + `observer` (prof) = 16 строк-ролей + представитель ОА без роли + permission `dsp`.
**Исправление.** Привести числа: «7 `evga_*` + `notifications`», «15 ролей `evga-*` + `observer`».

### K-09 · minor · §2.1 п.4 (`INSTALLED_APPS`: …, `evga_workflow, evga_execution, evga_appeals, evga_ersop, evga_cabinet`) vs §3.1/§11 («порядок в `INSTALLED_APPS` и порядок реализации совпадают»: … `evga_workflow → evga_ersop → evga_cabinet → evga_execution → evga_appeals`)

**Исправление.** Один порядок в обоих местах (по зависимостям моделей: `evga_ersop`, `evga_execution`, `evga_appeals` зависят только от `evga_documents/evga_cases`; `evga_cabinet` — последним).

### K-10 · minor · §4.7, §4.11, §4.6, §4.10 (неопределённые имена)

`AcknowledgementChannel` (§4.7 `Acknowledgement.channel`), `ErsopExchangeDirection` (§4.11), `three_false` (§4.6), сокращение `FK(User)` (§4.10–4.11), `RowProjection` (§4.7 «формат — тот же RowProjection») нигде не объявлены. **Исправление.** Объявить копии `documents.AcknowledgementChannel`/`ersop.ErsopExchangeDirection` в `evga_documents/models.py` и `evga_ersop/models.py`, `def three_false(): return [False, False, False]`, развернуть `FK(User)`, определить абстракт `RowProjection(version, row_id, sequence)`.

### K-11 · minor · §3.1/§5.2 (`evga_documents/services/actions.py` импортирует `ersop.submit_registration`, `amendments.apply_amendment`, `delivery`, `information_requests`) при FK `evga_ersop.ErsopRegistration → evga_documents.DocumentVersion` и `evga_cases.CaseAmendment → evga_documents.DocumentVersion`

**Риск.** Циклические импорты Python на уровне сервисов (`evga_documents.services.actions` ↔ `evga_ersop.services.registration` → `evga_documents.services.commit`), плюс `evga_cases.services.amendments` → `evga_documents.services.revisions` → `evga_cases.services.case_status`.
**Исправление.** Реестр `ACTIONS` наполняется из приложений-владельцев (`evga_ersop/actions.py`, `evga_cases/actions.py` вызывают `register(ActionSpec(...))` в `AppConfig.ready()`), либо ленивые импорты внутри `ActionSpec.service` (строка «module:function»).

### K-12 · minor · §11 (I6 «доставка объекту», I7 «решения ОА», I8 «`deadlines.py`»)

**Противоречие.** `DocumentDelivery.objection_due_on` (§4.7, «sent_at + 10 раб. дней»), `expires_at`, `appeal_filing_due`, `Appeal.filing_due_on` требуют `add_working_days`/календарь из `deadlines.py`, запланированного в I8 после I6–I7; `seed_evga_calendar` уже в I1.
**Исправление.** Перенести `working_date/add_working_days/localDate` в I1 (`catalogs/services/calendar.py`), в I8 оставить `audit_deadlines`, `qualityDays`, `process_deadlines`.

### K-13 · minor · §11 (оценки I3 = 10, I11 = 8, итого ≈94)

**Факт.** I3 включает порт `forms/documentForms.ts` (1094 стр.) + `referenceForms.ts` (244) + `formValues.ts` (229, `initialValues`) + `validation.ts` (269) + `violationRegistry.ts` (380) + `workingPapers.ts` (валидация РД) + сиды 105 видов/схем/62 РД — 10 дней мало. I11 объединяет серверный PDF для 105 видов (`ReferencePrintForm.tsx` 1976 стр., `QualityPrintForm.tsx` 414, `pdfExport.ts` 411) с SOAP ЕРСОП, шлюзом ГБД, синхронизацией Keycloak, `seed_evga_demo_cases` (порт `demoScenario.ts` 1340 стр.) и документацией — 8 дней нереалистично (один PDF — 10+ дней).
**Исправление.** I3 → ~14; выделить I11a «серверный PDF» (≥10) и I11b «адаптеры/синхронизация/демо-сиды/док» (≈6); итог ≈105–110 чел.-дн.; в §1 решение 18 и §13 обновить.

### K-14 · minor · §5.1 (`ApprovalWorkflowError(DocumentTransitionError, code)` → 400) vs §5.8 («дополнительно `ApprovalWorkflowError(STALE_VERSION)` из `decide_route`» как 409)

**Исправление.** `ApprovalWorkflowError(code="STALE_VERSION")` наследовать от `StaleVersionError` (409); остальные коды — 400 с `code` в нижнем регистре (`invalid_route`, `forbidden` → 403, `already_decided`, `comment_required`), как обещано в §6.13.

### K-15 · minor · §5.3 (`apply_action`: `requires_comment` → `DocumentTransitionError("Укажите замечание.")`) vs §6.13 (код `comment_required`) vs фронт

**Первоисточник.** `documentStateMachine.ts:464` — return: «Укажите замечание.»; `:518` — reject: «Укажите причину отклонения.»; `preparationWorkflow.ts:223`/`mainWorkflow.ts:336` — КВГА/реестр: «Укажите причину возврата».
**Исправление.** `ActionSpec.comment_message` (по действию) и `DocumentTransitionError(code="comment_required")`.

### K-16 · minor · §4.15 (`evga-case`: scope `<controlling_body.code>`, pattern `{org}-{yy}-{seq:05d}`)

**Противоречие.** Год входит в номер, но не в scope: счётчик не обнуляется по годам; legacy `get_next_case_sequence(year)` (§4.15, `n8n-cases-documents.md` §2.6) — годовой; фронт (`caseRules.ts:34-40`) — сквозной от 52970. Решение не зафиксировано.
**Исправление.** Явно выбрать: scope `f"{org}:{yy}"` (годовой, как legacy) либо сквозной (как фронт) — и записать в §12 п.2.

### K-17 · minor · §5.3 (`Transition.to_status: str | None`, `find_transition(workflow, status, action, kind)`), §5.4.3/§5.4.4/§5.4.6

**Противоречие.** Одно действие даёт разные целевые статусы в зависимости от payload: `kvga-decide` → `AGREED` (confirm) / `RETURNED` (return, instruction) / `AGREED` (return, counter-instruction); `registry-decide` → `AGREED`/`RETURNED`; `ersop-check-status` → 5 исходов. Структура `Transition` с одним `to_status` и `find_transition` без решения этого не выражает; инвариант «каждому `Transition` — `ActionSpec`» становится неоднозначным.
**Исправление.** Добавить `Transition.decision: str = ""` (значение `payload["decision"]`/результата) и искать `(workflow, status, action, kind, decision)`; для системных исходов (`ersop`) — `to_status` на связанной таблице.

### K-18 · minor · §5.4.5 (`quality-submit-to-head`: «`create_route(stages=[], signer=evga-qc-head)`») vs §4.8/§5.2 (`create_route` — порт `createApprovalRoute`) vs `evga-workflows.md` §4 («≥1 этап, у каждого ≥1 согласующий»)

**Первоисточник.** `mainWorkflow.ts:475-503` — фронт **не** вызывает `createApprovalRoute`, а собирает объект маршрута литералом (`reviewers: []`, `signer pending`, `status: "signing"`), обходя валидацию.
**Исправление.** Добавить `routes.create_signer_only_route(version, *, initiator, signer)` (или параметр `allow_empty_stages=True`) и сослаться на него в §5.4.5.

### K-19 · minor · §4.2 («`HistoryEntry` фронта = проекция»), §6.1 (`GET /cases/{id}/history/`)

**Первоисточник.** `workflow.ts:464-474` — история дела содержит копии событий версии с префиксом `"<docName> · vN: <action>"` и запись «… сохранены изменения» при изменении без событий. Проект отдаёт `AuditEvent(case=X)` с `target{type,id,label}`, но правило построения текста `action` для фронта не описано.
**Исправление.** В `HistoryEntrySerializer.action`: для событий с `target=version` — `f"{docName} · v{n}: {reason}"`, для `save_draft` — событие `UPDATE` с текстом «сохранены изменения» (сейчас §5.9 говорит, что `save_draft` пишет только «Сохранены изменения» в версию).

### K-20 · minor · §5.3 (`apply_action` → `assert_case_open(case)` для всех действий) vs §5.5 («`CLOSED` | любая мутация → «Дело закрыто»»)

**Первоисточник.** `workflow.ts:584-625` (`performRegistration`) и `:643-750` (`deliverDocument`) закрытие дела не проверяют; закрытие происходит по `counter-notification → REGISTERED` (§5.5), после чего `ersop-check-status`/`poll_registration` планировщика по тому же делу должны продолжать работать (журнал, `ErsopExchange(IN)`).
**Исправление.** `ActionSpec.allowed_when_closed=True` для `ersop-check-status`, `ersop-register`, `validate`; для таймера — вызывать `apply_registration_result` в обход `assert_case_open`.

---

## Проверено и подтверждено (расхождений нет)

**Мутации `evga-workflows.md` §7.1/§7.2 и таблица `evga-ui-actions.md` §3.2 → §6/§5 проекта.** Дело: создание/изменение (`create_case/update_case`, §6.1), `assignCoauthor` (`coauthors/`), календарь (`calendar/`), `CounterChecks.create` (`counter-cases/`), `assignQualityExpert` (`quality-assignments/ {stage, expert_id, reason}`), `applyAmendment` (`documents/{id}/apply-amendment/` → `CaseWorkspace`), `assignAppeal/recordAdmission/notifyAdmission/saveAppealArguments/decideArguments` (§6.6, тела совпадают: `expert_id`; `decision, reason, files[]`; `files[]`; `rows[], submit`; `approve, comment`), `recordNoThirdParties/addThirdParty/recordThirdPartyEvent` (§6.6/§6.9, `event: receipt|response|forward`), чтение уведомлений (§6.8 `read/`, `read-all/`), read-модели `auditDeadlines/executionStages+nextExecutionStep/executionItemsForCases/getApprovalTasks` (§6.1 `deadlines/`, `progress/`; §6.7; §6.4). Документ: `createDocument` (`{kind}`), `saveDocument` (`PATCH versions/{n}/ {values, group?, expected_row_version}`), `deleteDocument`, `sendDocumentToQuality`, `submitDocument` (`stages[]|reviewer_ids[], mode, signer_id, comment, expected_version`), `approve/return/reject` (`{comment, expected_version}`), `activateDocument` (`activate/`), 8 функций редакций + `renewQuality` (`revisions/ {reason}` — 8 значений), `recallDocument`, `sendInstructionToKvga/decideInstructionKvga` (`kvga-confirmation/request|decide/ {confirmer_id}` / `{decision, comment, expected_version}`), `requestPreparationQuality/requestMainQuality` (`request-quality/`), `sendPreparationForApproval/requestMainApproval` (`request-approval/`), `requestReportGroupSignatures/signReportGroup/signAssignmentGroup/approveAssignmentGroup` (`group-signatures/request|sign|approve/ {expected_version}`), `sendRegistryToConfirmer/decideRegistryConfirmation` (`registry-confirmation/*`), `signMainQuality/submitMainQualityToHead` (`quality/sign|submit-to-head/`), `performRegistration send|accept|return` (`ersop/send|check-status|register/`), `deliverDocument send|acknowledge|respond|sign|object|refuse` (`deliver/`, `deliver/refuse/`, кабинет `acknowledge|respond|decision`), `transitionInformationRequest` (9 действий: 6 у аудитора + 3 в кабинете), `validateDocument` (`validate/`), реестр нарушений (`finalizeRegistry/repairRegistry/…` — клиентские преобразования `values`, серверная `registryValidation`), `addQualityConclusion` — не переносится. Все 49 вызовов мутаций из UI (`pages/*`, `components/*`) найдены в §6.15.

**Поля `types.ts` → §4.** `AuditCase`: `qualityAssignments[stage]{expertId, assignedAt, assignedBy}` → `QualityAssignment`; `appeal` → `Appeal` (все под-поля `admission{decision, at, by, reason, files, notifiedAt}`, `arguments{rows, at, by, submittedAt, signedAt, signedBy, comment}` есть); `thirdParties` → `ThirdPartyNotice/ThirdPartyEvent` (receipt/response/forward с файлами); `thirdPartiesReviewed{at, by, none, reason}` → 4 колонки; `amendments[]` → `CaseAmendment(order_version, applied_by, targets)`; `notifications[]` → `Notification` (строка на получателя, `readBy` = `read_at`); `calendar` → `ProductionCalendarDay + CaseCalendarDay + calendar_confirmed_years`; `parentCaseId` → `parent`; `executionState` (3 значения, label дословно); `schedule{start,end,periodFrom,periodTo}` → 4 колонки; `coauthors` → `CaseCoauthor`; `documentSequence` → `document_sequence`; `jointObject` → `joint_subject`; `dsp`, `electronic` → колонки; `personType` (2 label), `counterQuestion`, `personBirthDate`, `entrepreneurName` → колонки; `sampleScenario` — удаляется (§10.2 этап 6); `object` → `subject` + `subject_snapshot`; `quality[3]` → `quality_stage_passed`; `bases[]` → `CaseBasis` (+ `source_version` для `additional-<docId>-vN`); `group` → `CaseParticipant`; `history` → `AuditEvent(case)`; `attachments` → `GenericRelation`. `DocumentVersion`: `preparation{agreedAt, qualityRequestedAt, kvga{confirmerId, status, at, by, comment}, groupSignatures}`, `main{agreedAt, groupRequestedAt, groupSignatures, confirmation{confirmerId, status, comment, decidedAt, sourceVersions}, qualityRequestedAt, approvalRequestedAt}`, `mainQuality{expertSignedAt, expertId, submittedAt}`, `registration{status, number, date, comment}`, `delivery{sentAt, acknowledgedAt, response, attachments, decision, decidedAt, decidedBy, grounds, decisionAttachments}`, `informationRequest{state, rounds[{id, sentAt, deadline, acknowledgedAt, response{at,by,text,attachments,refused,legacy}, review{at,by,decision,comment}, reviewStartedAt}]}`, `sourceVersions`, `approvalRoutes` (форма `shared/workflow`: `ApprovalRoute/Stage/Participant/Event` покрывают `stages`, `signer`, `signerAction`, `history`, `returned/rejected`, `supersededByVersionId`), `signatures{person, at, role}`, `qualityDecision` (2 label), `qualityConclusion`, `ownerRole` (4 значения), `ownerId`, `group` → `VersionParticipant`, `attachments`, `values`, `version`, `status`, `createdAt`, `history` — всё отображено (кроме C-01…C-05). `AuditDocument{id, kind, stage, number, createdAt, author, versions}`; `Basis`, `Person`, `AuditObject` (`Subject.as_snapshot`), `HistoryEntry`, `IrpiRow.files` (`form_row_file` + `slot`), `Account` (`accountFromUser`) — отображены.

**Статусы, роли, виды.** 11 значений `DocStatus` = 11 `DocumentStatus` с дословными label. 10 ролей `Role` → §7.3 (`object` = `is_subject_representative`); особые аккаунты `approver` (assignCoauthor, decideArguments → `evga-approver: DECIDE`), `quality-head` (→ `evga-qc-head`, `{role:"approver", id:"quality-head"}`), `commission-chair`/`commission-1/2` (→ роли комиссии с `area:"appeal"`), `coauthor` (auditor + `CaseCoauthor`), `reestr-confirmer`, `kvga` — покрыты. 105 видов = 36 `docKinds` + 7 `counterDocKinds` + 62 `workingPapers.json` — совпадает с сидом §9 п.7. Флаги: `requiresQuality` (9 видов) → `requires_quality`; `directActivation` (10 + рабочие формы) → `Workflow.DIRECT` + `is_working_paper`; `repeatableKinds` (19) → `is_repeatable`; `deliverable` (14) → `is_deliverable`; регистрируемые (6) → `is_registrable`; `dependencies` (24 записи `workflow.ts:86-112`) → M2M + правило «prep не проверяет dependencies», «оба requiresQuality → достаточно существования»; `amendmentTargets` (11) → `amendment_target`; `printContext.sources` (6) → `print_context_source`; `paperApplies` → `audit_type_filter` + запрет для `parent`; `has_signer=False` для assignment/report.

**Автоматы (§5.4 ↔ `evga-workflows.md` §2.3–2.11 и исходники).** Общий маршрут (submit → approve → AGREED/IN_APPROVAL/ACTIVE, return/reject с comment, revise по `RETURNED/REJECTED`, `createNextVersion` при `qualityConclusion` и статусах `ACTIVE/QUALITY_REVIEW/AGREED`, `recall` до первого решения), подготовительный этап (цепочка `preceding`, КВГА confirm/return с особым случаем `counter-instruction → AGREED`, `request-quality` открывает `quality1`, `request-approval` → `IN_APPROVAL`/`GROUP_SIGNING`, `revise(preparation)` из 4 статусов), основной этап (подписи РГ → `DRAFT` → submit без signer, `registry-send/decide` с `sourceVersions` и `qualityRequestedAt := None`, `request-quality/approval`, `mainApprovalBlock` для report — всегда блок, `deliver report AGREED → ACTIVE`), КК2 (подпись эксперта → signer-only маршрут → решение руководителя → `apply_quality_conclusion` только в текущие не-`ACTIVE` main-версии), КК1/КК3 (signer = qc-head, `renew_quality`), ЕРСОП (send только из `ACTIVE`, return → `RETURNED`), доставка (все 6 действий, guard'ы `acknowledged_at` для report, `grounds`/файлы для refuse), требования (7 состояний, 9 действий, авто-`overdue`/`refused` для counter-request, старт таймера от `acknowledge`), `response` (`assertExecutionResponseSave`, `effective_response_version`, продление), апелляция и третьи лица — таблицы проекта соответствуют функциям фронта (за исключением C-10…C-15). Автомат дела §5.5 (`OPEN/CLOSED`, `execution_state`, эффекты `additional` по `order.type`, закрытие по `completion`/`counter-notification`, `quality_stage_passed` и `qualityPassed` для stage 1 через `mainQualityConclusionBlock`) — соответствует `workflow.ts:237-544`. `commit_version` покрывает п.1–13 §2.12.

**Оптимистичная блокировка.** `expected_version` у всех решений, `expected_row_version` у черновика, `select_for_update(case)` вместо JSON-сравнений `*CurrentBlock`, кросс-документные guard'ы внутри транзакции, `IntegrityError → DocumentTransitionError` с текстами фронта — описано последовательно в §5.3/§5.8/§5.9 (кроме K-02, K-14, C-16).

**Версии и повторяемые виды vs `UniqueConstraint`.** `UniqueConstraint(document, version)` + `UniqueConstraint(case, sequence)` + проверка «Документ уже создан.» для `is_repeatable=False` под `select_for_update(case)` — корректно (частичный уникальный индекс по флагу типа невозможен); soft delete не мешает нумерации (`document_sequence` не переиспользуется — совпадает с `documentFactory.ts:36-41`).

**Нумерация.** `30101-YY-NNNNN` (старт 52970), `{case}/NN` (`padStart(2)`), `{parent}/ВП-{n}`, `УЧ-…` — совпадают с `caseRules.ts:34-40`, `documentFactory.ts:56`, `CounterChecks.tsx:64`, `workflow.ts:617`.

**Read-модели.** `workspace` (§6.2) покрывает `CaseWorkspace`; `tasks` — `getApprovalTasks` + «задания по процессу» (`pages/ApprovalTasks.tsx:25-49`: КВГА, реестр, РГ, решение ОА) + правило `caseApprovalRoutes` (signer `waiting` в `AGREED/PENDING_KVGA/PENDING_REGISTRY`, маршруты неактуальных main/quality2-версий — `superseded`); уведомления (§6.8); `ExecutionItem` (§6.7: id-формат, `claimedStatus/confirmedStatus/originalDueDate/dueDate/extensions/evidence/responses/history` = `shared/execution/execution.ts:70-86`); `Deadline{label, source, due, completed, estimated, rule}` и 15 правил + `qualityDays` (2/5/7/10/3/20) = `deadlines.ts`; `progress` (`executionStages/nextExecutionStep/documentNextAction`); `available-documents` (`creationBlock` + `creationAccessBlock`); `print-context` (`printContext.ts` — снимок дела + 6 источников); кабинет ОА (§6.9) — покрывают соответствующие экраны. Фильтры реестра дел §6.14 покрывают все 14 ключей `caseSearch.ts:10-25` (включая «`rnn` не реализуется», `coauthor`).

**План работ.** Порядок итераций I0→I11 согласован с порядком приложений §3.1 (с оговорками K-09, K-12); арифметика оценок (36 до Демо-1, 94/36 итого) сходится.
