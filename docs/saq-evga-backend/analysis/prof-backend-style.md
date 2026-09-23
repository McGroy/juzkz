# Style guide бэкенда команды SAQ (эталон: `saq-prof-control-demo/backend`)

Отчёт-исследование по области «стиль и архитектура бэкенда-эталона». Источник — реальные файлы
`saq-prof-control-demo/backend`
(далее пути даются относительно `backend/`). Все идентификаторы кода — как в исходниках. Документ самодостаточен:
предназначен для агента/разработчика, который будет писать бэкенд ЭВГА «в стиле prof» и не имеет доступа к этому контексту.

---

## 0. TL;DR — что такое «стиль prof» в одном экране

| Аспект | Как сделано в эталоне |
|---|---|
| Стек | Python 3.13, Django 5.2.6, DRF 3.16.0, django-filter 25.1, drf-spectacular 0.28.0, django-environ, django-cors-headers, django-storages[s3] (MinIO), psycopg 3, PyJWT[crypto], argon2-cffi, httpx, gunicorn, whitenoise; dev: pytest 8.4 + pytest-django 4.11, ruff 0.13, django-stubs, factory-boy (объявлен, но не используется) |
| Структура | `config/` (settings split base/local/production, urls) + `apps/<domain>/{models.py, admin.py, apps.py, api/{views,serializers,urls,filters}.py, services/*.py, management/commands/seed_*.py, tests/test_*.py, migrations/}` — 13 приложений |
| Модели | UUID pk через абстрактный `core.TimeStampedModel` (`id`, `created_at`, `updated_at`, `created_by`); статусы — `models.TextChoices` c UPPER_CASE-значениями и русскими label'ами; натуральные ключи — `UniqueConstraint(name="<app>_<model>_natural_key")`; generic `Attachment`, `AuditEvent`, `NumberSequence/IssuedNumber` в `core` |
| Домен | «Документ дела» = `documents.ControlDocument` (общая шапка: тип, статус, номера, approved/signed/sent) + OneToOne `*Details` на тип документа (`NoticeDetails`, `AppointmentActDetails`, `ResultActDetails`, `PrescriptionDetails`); справочник типов `DocumentType` сидируется |
| Сервисы | Только **функции-модули** (не классы): `create_*`, `approve_*`, `sign_*`, `send_*`, `record_*`, `build_*`, `submit_*`, `register_*`; keyword-only параметры; `@transaction.atomic`; проверки инвариантов → `raise DocumentTransitionError("русское сообщение")`; статус меняется через `document.save(update_fields=[..., "updated_at"])` |
| API | `GenericViewSet` + mixins для чтения (list/retrieve, иногда partial_update) и **отдельный `APIView` на каждое действие** (approve/sign/send/acknowledge/attachments…). **`@action` не используется нигде.** `get_permissions()` всегда возвращает `[IsAuthenticated(), HasDomainLevel()]`; доступ задают классовые атрибуты `required_domain` / `required_levels` |
| Ошибки | Единый envelope в стиле RFC 7807: `{"type":"about:blank","title","status","code","detail", ...field errors}` (`core/exceptions.py`, `core/middleware.py`, `core/views.py`). Ошибки бизнес-переходов → `serializers.ValidationError({"detail": str(exc)})` (HTTP 400) |
| RBAC | Своя модель: `Role` (14 ролей, `RoleScope` national/territorial) → `RolePermission(domain, level)` → `RoleAssignment(user, role, department, valid_from/to)`. `HasDomainLevel` проверяет `(domain, level ∈ required_levels)`; `ScopedQuerySetMixin` фильтрует queryset по department территориальных ролей; `_assert_department_in_scope()` — для action-view'ов |
| Auth | Собственная сессия: opaque cookie `saq_session` (httpOnly, SameSite=Lax) → `accounts.AuthSession`; провайдеры `local` (email+пароль, регистрация представителя субъекта по БИН) и `keycloak` (OIDC Authorization Code + PKCE, `httpx` + `PyJWKClient`) |
| Интеграции | Заглушки без сети: `ersop/services/stub_exchange.py::fake_register_package()` выдаёт номера через `NumberSequence`, обмен логируется в `ErsopExchange` (JSON payload'ы) |
| Тесты | pytest-django, `pytestmark = pytest.mark.django_db`, `APIClient().force_authenticate(user)`, вспомогательные функции `_user_with_cases_role`, `_department`, без фабрик и conftest; 79 тестов в 16 файлах; проверяют сервисы, RBAC, envelope ошибок, конкурентность через `threading` |
| Инфра | `Dockerfile` (python:3.13-slim + gunicorn 3 workers), `docker/entrypoint.sh` (`migrate` → `collectstatic` → 7 seed-команд → `exec "$@"`), docker-compose: postgres:16, minio + minio-init (`mc mb`), backend; healthcheck `manage.py check --database default`; nginx на хосте раздаёт фронт и проксирует `/api/`, `/admin/` |
| Ruff | `line-length = 120`, `target-version = "py313"`, `select = ["E","F","I","UP","B","DJ"]`, `ignore = ["DJ001"]`, миграции исключены |

Ключевые цифры по эталону: 12 169 строк Python (без миграций), 13 приложений, 26 миграций, 79 тестов, 69 аннотаций `@extend_schema`, 45 использований `transaction.atomic`, 6 `select_for_update`, 33 места `ValidationError({"detail": ...})`, 0 использований `@action`, **0 записей `AuditEvent` из сервисов** (модель есть, тесты есть, но сервисы её не пишут — см. §3.6).

---

## 1. Структура приложения

### 1.1 Дерево (сокращённо)

```
backend/
├── manage.py                     # DJANGO_SETTINGS_MODULE default = config.settings.local
├── pyproject.toml                # pytest + ruff + django-stubs
├── requirements/{base,local}.txt
├── .env.example, .python-version (3.13), Dockerfile, .dockerignore
├── docker/entrypoint.sh
├── data/DFO.json                 # синтетическая выгрузка ДФО (7.9 MB) для seed/импорта
├── config/
│   ├── settings/{__init__,base,local,production}.py
│   ├── urls.py, wsgi.py, asgi.py
└── apps/
    ├── core/        models, exceptions, middleware, pagination, views, admin, services/{files,numbering}.py,
    │                management/commands/seed_number_sequences.py, tests/
    ├── catalogs/    models, admin, management/commands/seed_catalogs.py, tests/
    ├── accounts/    models, authentication, permissions, querysets, schema, admin,
    │                api/{keycloak_views,local_views,serializers,urls}.py, services/{keycloak,sessions}.py,
    │                management/commands/seed_roles.py, tests/
    ├── subjects/    models, validators, admin, api/{views,serializers,urls,filters}.py, tests/
    ├── reporting/   models, admin, api/, services/dfo_import.py, management/commands/seed_report_forms.py, tests/
    ├── risk/        models, admin, api/{views,serializers,urls,filters}.py, services/checks.py,
    │                management/commands/seed_risk_rules.py, tests/
    ├── semiannual/  models, admin, api/{views,serializers,urls,filters}.py, services/list_formation.py, tests/
    ├── cases/       models, admin, api/{views,serializers,urls,filters}.py, services/case_status.py
    ├── documents/   models, admin, api/{views,serializers,urls}.py,
    │                services/{exceptions,notice,appointment_act,result_act,prescription,acknowledgement,attachments}.py,
    │                management/commands/seed_document_types.py
    ├── checklists/  models, admin, api/, services/{checklist,attachments}.py, management/commands/seed_checklists.py
    ├── execution/   models, admin, api/{views,serializers,urls,filters}.py,
    │                services/{prescription_items,submissions,decisions,attachments}.py
    ├── ersop/       models, admin, api/, services/{stub_exchange,package_1,package_2}.py
    └── cabinet/     api/{views,serializers,urls}.py   (без моделей — только API поверх других приложений)
```

Каждое приложение — Python-пакет `apps.<name>` с `apps.py`:

```python
# apps/documents/apps.py — шаблон для всех приложений
class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.documents"
    label = "documents"
    verbose_name = "Документы дела"      # русское имя для Django admin
```

`accounts/apps.py` в `ready()` импортирует `schema.py`, чтобы зарегистрировать расширение drf-spectacular для cookie-аутентификации.

### 1.2 Порядок регистрации и маршрутизация

`config/settings/base.py`, `INSTALLED_APPS` — приложения перечислены в порядке зависимостей (важно для читаемости, миграции всё равно разрешают зависимости сами):

```
apps.core → apps.catalogs → apps.accounts → apps.subjects → apps.reporting → apps.risk →
apps.semiannual → apps.cases → apps.documents → apps.checklists → apps.execution → apps.ersop → apps.cabinet
```

`config/urls.py` — один `path("api/<app>/", include("apps.<app>.api.urls"))` на приложение; `handler404`/`handler500` переопределены на JSON-ответы для `/api/`:

```python
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/auth/", include("apps.accounts.api.urls")),
    path("api/subjects/", include("apps.subjects.api.urls")),
    ...
    path("api/cabinet/", include("apps.cabinet.api.urls")),
]
```

Внутри приложения `api/urls.py` комбинирует `DefaultRouter` для ViewSet'ов и явные `path()` для action-view'ов, **причём path'ы идут раньше `*router.urls`**, чтобы `notice/` не перехватился `<pk>/`:

```python
# apps/documents/api/urls.py
router = DefaultRouter()
router.register("", ControlDocumentViewSet, basename="control-document")

urlpatterns = [
    path("notice/", CreateNoticeView.as_view(), name="document-create-notice"),
    path("appointment-act/", CreateAppointmentActView.as_view(), name="document-create-appointment-act"),
    path("result-act/", CreateResultActView.as_view(), name="document-create-result-act"),
    path("<uuid:pk>/approve/", ApproveDocumentView.as_view(), name="document-approve"),
    path("<uuid:pk>/send/", SendDocumentView.as_view(), name="document-send"),
    path("<uuid:pk>/sign/", SignDocumentView.as_view(), name="document-sign"),
    path("<uuid:pk>/acknowledge/", AcknowledgeDocumentView.as_view(), name="document-acknowledge"),
    path("<uuid:pk>/attachments/", AttachDocumentFileView.as_view(), name="document-attach-file"),
    path("<uuid:pk>/attachments/<uuid:attachment_id>/", DownloadAttachmentView.as_view(),
         name="document-download-attachment"),
    *router.urls,
]
```

Именование URL-name: `<ресурс>-<действие>` в kebab-case (`document-approve`, `semiannual-list-version-submit`, `cabinet-register-submission`). Имена используются в сериализаторах через `reverse()` для ссылок на скачивание вложений.

### 1.3 Полная карта эндпоинтов эталона

| Приложение | Метод и путь | View | Уровень доступа |
|---|---|---|---|
| accounts | `POST /api/auth/local/register`, `POST /api/auth/local/login`, `POST /api/auth/local/logout`, `GET /api/auth/me` | `RegisterView`, `LoginView`, `LogoutView`, `MeView` | AllowAny / IsAuthenticated |
| accounts | `GET /api/auth/keycloak/login`, `GET /api/auth/keycloak/callback`, `POST /api/auth/keycloak/logout` | `KeycloakLoginView`, `KeycloakCallbackView`, `KeycloakLogoutView` | AllowAny |
| subjects | `GET/POST /api/subjects/`, `GET/PUT/PATCH /api/subjects/{id}/` (DELETE → 405) | `SubjectViewSet` | cases: read/`EDIT`,`DECIDE` |
| reporting | `GET /api/reporting/extracts/`, `GET .../{id}/`, `POST /api/reporting/extracts/import/` (multipart `file`) | `DfoExtractViewSet`, `DfoExtractImportView` | semiannual: read / EDIT |
| risk | `GET /api/risk/rules/`, `/runs/`, `/candidates/`, `POST /api/risk/runs/trigger/` | `RiskRuleViewSet`, `RiskRunViewSet`, `RiskCandidateViewSet`, `RiskRunTriggerView` | semiannual: read / EDIT |
| semiannual | `GET /api/semiannual/lists/`, `/versions/`, `/entries/` (+PATCH), `/department-assignments/` (+PATCH); `POST lists/form-v1/`, `lists/{id}/create-v2/`, `versions/{id}/submit|approve|form/`, `entries/{id}/exclude/` | `SemiannualList*ViewSet`, `FormVersion1View`, `CreateVersion2View`, `SubmitVersionView`, `ApproveVersionView`, `FormVersionView`, `ExcludeEntryView` | semiannual: read/EDIT/APPROVE |
| cases | `GET /api/cases/` (реестр = строки перечня), `GET /api/cases/{entry_id}/`, `GET /api/cases/{case_id}/workspace/` | `CaseRegistryViewSet`, `CaseWorkspaceView` | cases: read |
| documents | `GET /api/documents/`, `GET/PATCH /api/documents/{id}/`; `POST notice/`, `appointment-act/`, `result-act/`; `POST {id}/approve|sign|send|acknowledge|attachments/`; `GET {id}/attachments/{aid}/` | см. §4 | cases: read / EDIT / APPROVE / SIGN |
| checklists | `GET /api/checklists/` (lookup по `document_id`), `PATCH items/{id}/`, `POST items/{id}/attachments/`, `GET items/{id}/attachments/{aid}/`, `POST items/{id}/violations/`, `PATCH/DELETE violations/{id}/`, `POST violations/{id}/attachments/`, `GET/DELETE violations/{id}/attachments/{aid}/`, `PATCH {doc}/general-reference/`, `POST {doc}/general-reference/attachments/`, `GET .../{aid}/`, `POST {doc}/complete/` | см. `checklists/api/views.py` | cases: read / EDIT |
| execution | `GET /api/execution/items/`, `GET/PATCH items/{id}/`, `POST items/{id}/submissions/`, `POST items/{id}/decide/`, `GET items/{id}/attachments/{aid}/` | `PrescriptionItemViewSet`, `RegisterSubmissionView`, `DecideItemView`, `DownloadExecutionAttachmentView` | cases: read/EDIT; execution: DECIDE |
| ersop | `GET /api/ersop/packages/`, `POST packages/build-package-1/`, `build-package-2/`, `packages/{id}/approve-step|submit|register/` | `ErsopPackageViewSet`, `BuildPackage1View`, `BuildPackage2View`, `ApprovePackage2StepView`, `SubmitPackageView`, `RegisterPackageView` | cases: read/EDIT/APPROVE |
| cabinet | `GET /api/cabinet/documents/`, `POST documents/{id}/acknowledge/`, `GET /api/cabinet/execution-items/`, `POST execution-items/{id}/submissions/`, 4 download-view'а | `Cabinet*` | `IsSubjectRepresentative` |
| — | `GET /api/schema/`, `GET /api/docs/` (Swagger UI), `/admin/` | drf-spectacular, Django admin | — |

Фронт (`frontend/src/api/client.ts`) ходит по этим путям с `credentials: "include"`, все списки — DRF-пагинация `{count, next, previous, results}`, ошибки читаются из `payload.detail` либо первого поля envelope'а.

---

## 2. Модели

### 2.1 Базовые классы и первичные ключи

`apps/core/models.py`:

```python
class TimeStampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        abstract = True
```

Правила, которые эталон соблюдает везде:

* **Все доменные модели наследуют `TimeStampedModel`** → UUID pk, `created_at/updated_at/created_by`. Исключения — служебные модели с собственной семантикой: `Attachment`, `AuditEvent`, `IssuedNumber` (UUID pk вручную, без `updated_at`), `AuthSession` (pk — случайная строка `secrets.token_urlsafe(48)`), `User` (`AbstractUser` + `id = UUIDField`), `Role`, `RolePermission`, `RoleAssignment`, `FederatedIdentity`, `OidcAuthRequest` (UUID pk вручную).
* `created_by` **не** заполняется автоматически: сервисы/представления передают его явно (`serializer.save(created_by=self.request.user)`, `ControlDocument.objects.create(..., created_by=created_by)`).
* FK на пользователя-«актора» (`approved_by`, `signed_by`, `sent_by`, `responsible`, `excluded_by`, `updated_by`, `actor`) — всегда `null=True, blank=True, on_delete=SET_NULL, related_name="+"`. Исключение: `AuditEvent.actor` — `PROTECT` (нельзя удалить пользователя, у которого есть события журнала; есть тест).
* FK на справочники — `on_delete=PROTECT` (`subject_type`, `document_type`, `risk_degree`, `severity`, `region`, `department`), иногда `SET_NULL` там, где справочник необязателен (`business_category`, `actual_region`, `Subject.department`).
* FK «ребёнок → родитель-агрегат» — `CASCADE` (`NoticeDetails.document`, `CaseChecklistItem.checklist`, `ErsopPackageItem.package`, `ExecutionSubmissionItem.submission`).
* FK «сущность процесса → сущность процесса, которую нельзя терять» — `PROTECT` (`ControlDocument.list_entry`, `ControlCase.list_entry`, `ErsopPackage.case`, `PrescriptionItem.violation`).
* `related_name="+"` для обратных связей, которые не нужны; осмысленный `related_name` там, где по нему ходят (`list_entry.documents`, `case.ersop_packages`, `checklist.items`, `item.violations`, `prescription.items`, `item.decisions`, `item.submission_items`).

### 2.2 Статусы и перечисления

Статусы — `models.TextChoices`, значение = UPPER_SNAKE (для документов/дел/пакетов) либо kebab/snake lower (для «видов»: `AttachmentKind`, `DocumentCreationMode`, `AcknowledgementChannel`, `ExecutionSubmissionSource`), label — русский:

```python
class DocumentStatus(models.TextChoices):
    """Объединение статусных цепочек всех типов документов"""
    DRAFT = "DRAFT", "Проект"
    APPROVED = "APPROVED", "Согласовано"
    SIGNED = "SIGNED", "Подписан"
    READY = "READY", "Готов к отправке"
    IN_ERSOP = "IN_ERSOP", "На регистрации в ЕРСОП"
    REGISTERED = "REGISTERED", "Зарегистрирован"
    SENT = "SENT", "Направлен"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Субъект ознакомлен"
    ACCEPTED = "ACCEPTED", "Принята ЕРСОП"
    GENERATED = "GENERATED", "Сформирован"
    IN_PACKAGE_1 = "IN_PACKAGE_1", "Включён в пакет №1"
    IN_PACKAGE_2 = "IN_PACKAGE_2", "Включён в пакет №2"
    IN_EXECUTION = "IN_EXECUTION", "На исполнении"
    EXECUTED = "EXECUTED", "Исполнено"
```

Особенности:

* Один общий `DocumentStatus` на все типы документов; вариации label'ов по типу — словарь `_STATUS_LABEL_OVERRIDES: dict[tuple[str, str], str]` + функция `document_status_label(document_type_code, status)` (например `("prescription", IN_PACKAGE_2) → "Включено в пакет №2"`). Сериализатор отдаёт и `status`, и `status_label`.
* `IntegerChoices` для числовых перечислений: `semiannual.Half` (1/2), `ersop.ErsopPackageKind` (1/2).
* Полный список TextChoices эталона (полезно как словарь терминов): `core.AttachmentKind`, `core.AuditAction`, `accounts.AuthProvider`, `accounts.RoleScope`, `accounts.PermissionDomain`, `accounts.PermissionLevel`, `subjects.RegistrationStatus`, `subjects.SubjectPersonRole`, `reporting.Periodicity`, `reporting.DfoExtractStatus`, `reporting.SubmissionStatus`, `risk.RiskRunStatus`, `risk.RiskCategory`, `risk.RiskRuleType`, `risk.RiskRuleEvaluationStatus`, `semiannual.SemiannualListVersionStatus`, `cases.CaseStatus`, `documents.DocumentCreationMode`, `documents.DocumentIntegration`, `documents.DocumentStatus`, `documents.AcknowledgementChannel`, `documents.PortalAcknowledgementStatus`, `checklists.ChecklistItemResult`, `execution.PrescriptionItemStatus`, `execution.ExecutionDecisionKind`, `execution.ExecutionSubmissionSource`, `execution.ExecutionSubmissionStatus`, `ersop.ErsopPackageStatus`, `ersop.ErsopPositionKind`, `ersop.ErsopExchangeDirection`.

### 2.3 Generic-модели `core`

**`Attachment`** — универсальное вложение через `GenericForeignKey` (`content_type` + `object_id: CharField(64)` — строка, т.к. pk UUID):

```python
def attachment_upload_to(instance, filename):
    return f"attachments/{instance.content_type_id}/{instance.object_id}/{uuid.uuid4()}_{filename}"

class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")
    kind = models.CharField(max_length=32, choices=AttachmentKind.choices)
    file = models.FileField(upload_to=attachment_upload_to)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    mime = models.CharField(max_length=127)
    checksum = models.CharField(max_length=64, help_text="SHA-256, hex-encoded")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
```

`AttachmentKind` (7 значений): `acknowledgement_scan`, `explanatory_note`, `investor_basis`, `audit_evidence`, `general_reference`, `execution_confirmation`, `decision_attachment`. К моделям-владельцам подключается `GenericRelation("core.Attachment", content_type_field="content_type", object_id_field="object_id")` (есть на `ControlDocument.attachments`); в других местах выборка делается вручную через `Attachment.objects.filter(content_type=..., object_id=str(pk))`.

**`AuditEvent`** — append-only журнал (generic FK на объект, `action: AuditAction`, `status_from/status_to`, `actor`, `actor_role` («'system' for automatic SAQ actions»), `occurred_at`, `reason`, `attachment`, `exchange_id`). Неизменяемость обеспечена на уровне модели и QuerySet:

```python
class AuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs): raise ValueError("AuditEvent is append-only and cannot be modified in bulk.")
    def delete(self): raise ValueError("AuditEvent is append-only and cannot be deleted in bulk.")

class AuditEvent(models.Model):
    ...
    objects = AuditEventQuerySet.as_manager()
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("AuditEvent is append-only and cannot be modified.")
        super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise ValueError("AuditEvent is append-only and cannot be deleted.")
```

`AuditAction`: `create, approve, sign, send, acknowledge, decide, exchange`. В admin запрещены change/delete. **Важно:** ни один сервис эталона не создаёт `AuditEvent` (grep по `apps/` вне `core` — 0 совпадений); журнал спроектирован, покрыт тестами, но не подключён. Для ЭВГА его следует реально писать в сервисах переходов (см. §3.6).

**`NumberSequence` / `IssuedNumber`** — нумерация (см. §3.4): `NumberSequence(key, scope, pattern, current_value)` с `UniqueConstraint(key, scope)`; `IssuedNumber(sequence, value, content_type, object_id, issued_at)` с двумя уникальностями — по `(sequence, value)` и по `(sequence, content_type, object_id)` (идемпотентность выдачи одному объекту).

### 2.4 Связка «дело → документы → детали»

Центральная схема эталона (документы висят на **строке полугодового перечня**, а не на деле; дело — производная сущность):

```
semiannual.SemiannualList ──< SemiannualListVersion (v1, v2; SemiannualList.current_version → FORMED)
        │
        └──< SemiannualListEntry (subject, region, department, responsible, is_excluded)
                  │ OneToOne                       │ FK related_name="documents"
                  ▼                                ▼
          cases.ControlCase                documents.ControlDocument ──< Acknowledgement (unique: document, channel)
          (number, notice_sent_at,          (document_type FK, status, number, external_number,
           started_on, closed_at,            approved_*/signed_*/sent_*, attachments: GenericRelation)
           status = computed)                   │ OneToOne по типу:
                  │                             ├── NoticeDetails            (related_name="notice_details")
                  └──< ersop.ErsopPackage       ├── AppointmentActDetails    ("appointment_act_details")
                        ──< ErsopPackageItem    ├── ResultActDetails         ("result_act_details")
                        ──< ErsopExchange       ├── PrescriptionDetails      ("prescription_details") ──< execution.PrescriptionItem
                                                └── checklists.CaseChecklist ("checklist") ──< CaseChecklistItem ──< CaseChecklistViolation
```

`ControlDocument`:

```python
class ControlDocument(TimeStampedModel):
    list_entry = models.ForeignKey("semiannual.SemiannualListEntry", on_delete=models.PROTECT, related_name="documents")
    document_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=16, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    document_date = models.DateField(null=True, blank=True)
    number = models.CharField(max_length=64, blank=True)            # внутренний/исходящий номер SAQ
    external_number = models.CharField(max_length=64, blank=True)   # рег. номер ЕРСОП
    external_registered_at = models.DateField(null=True, blank=True)
    approved_at / approved_by, is_signed / signed_at / signed_by, sent_at / sent_by
    attachments = GenericRelation("core.Attachment", ...)

    class Meta:
        ordering = ["list_entry", "document_type"]
        constraints = [UniqueConstraint(fields=["list_entry", "document_type"], name="documents_controldocument_natural_key")]
```

Следствие: **один документ каждого типа на дело** (нет версий документа). `DocumentType` — сидируемый справочник с полями `code` (`notice`, `appointment-act`, `card-1-p`, `checklist`, `explanatory-note`, `article-155`, `evidence`, `result-act`, `prescription`), `name`, `short_name`, `stage`, `order`, `creation_mode` (`authority|subject|attachment|auto`), `is_printable`, `integration` (`none|subject-cabinet|ersop`), `normative_act`, `requires_acknowledgement`, `is_implemented`.

Доступ к документу дела по коду типа — метод-кэш на `ControlCase`:

```python
def document(self, document_type_code: str) -> ControlDocument | None:
    if not hasattr(self, "_documents_by_type"):
        self._documents_by_type = {
            doc.document_type.code: doc
            for doc in self.list_entry.documents.select_related("document_type")
        }
    return self._documents_by_type.get(document_type_code)
```

`*Details`-модели — плоские, только поля печатной формы, без бизнес-полей статуса; `OneToOneField(ControlDocument, on_delete=CASCADE, related_name=...)`.

### 2.5 Версии, вычисляемые статусы, натуральные ключи

* **Версии** реализованы только для перечня: `SemiannualListVersion(version_number ∈ {1,2}, status: NOT_FORMED→DRAFT→APPROVED→FORMED, submitted/approved/formed_*)` + указатель `SemiannualList.current_version`. Строки живут на перечне (миграция `0002_unversion_list_entries`), версия №2 отличается лишь флагами `is_excluded`.
* **Вычисляемые статусы** — не хранятся, а считаются из состояния связанных объектов: `ControlCase.status` (`@property` → `cases/services/case_status.py::compute_status`), `PrescriptionItem.status` и `effective_due_date` (`@property` по `decisions`/`submission_items`), `CaseChecklistItem.total_violation_amount`. Для фильтрации по вычисляемому статусу в `CaseRegistryFilter.filter_status` делается Python-проход (`matching_ids = [entry.id for entry in entries if entry_status(entry) == value]`) — осознанный компромисс демо.
* **Натуральные ключи** — `UniqueConstraint` с именованием `<app>_<model>_natural_key` или описательным (`semiannual_list_period`, `core_issuednumber_sequence_target`, `accounts_user_email_ci_unique` через `Lower("email")`).
* **Кастомные QuerySet'ы** через `.as_manager()`: `RoleAssignmentQuerySet.active(at)`, `ControlEligibilityRuleQuerySet.current()`, `DepartmentAssignmentQuerySet.with_subjects_counts()` (annotate подзапросами), `AuditEventQuerySet`.
* **`clean()`** используется для инвариантов, которые не выражаются constraint'ом (`Department.clean`: территориальное требует региона; `RoleAssignment.clean`: территориальная роль требует подразделения).
* **`__str__`** у всех моделей, формат «часть · часть» с разделителем `·`.
* Индексы: `Meta.indexes` только по реально используемым фильтрам (`Subject: (subject_type, actual_region)`, `Attachment: (content_type, object_id)`).
* Абстрактные справочные базы в `catalogs`: `CodeNamedModel(code unique, name)` и `OrderedCodeNamedModel(+order)`.

---

## 3. Сервисный слой

### 3.1 Форма: функции-модули, keyword-only аргументы

Сервисы — **модули с функциями**, ни одного класса-сервиса. Файл = агрегат/документ (`services/notice.py`, `services/appointment_act.py`, `services/result_act.py`, `services/prescription.py`, `services/acknowledgement.py`, `services/attachments.py`; `checklists/services/checklist.py`; `execution/services/{submissions,decisions,prescription_items}.py`; `ersop/services/{package_1,package_2}.py`; `semiannual/services/list_formation.py`; `risk/services/checks.py`; `reporting/services/dfo_import.py`; `accounts/services/{keycloak,sessions}.py`; `core/services/{numbering,files}.py`).

Сигнатура: первый позиционный аргумент — объект-агрегат, остальное — keyword-only, актор передаётся именованно (`created_by=`, `approved_by=`, `signed_by=`, `sent_by=`, `recorded_by=`, `by=`, `actor=`), возвращается изменённый объект:

```python
# apps/documents/services/notice.py
NOTICE_TYPE_CODE = "notice"

@transaction.atomic
def create_notice(list_entry: SemiannualListEntry, *, created_by=None, **fields) -> ControlDocument:
    if list_entry.semiannual_list.current_version_id is None:
        raise DocumentTransitionError("Уведомление можно создать только по строке сформированной версии перечня.")
    if list_entry.is_excluded:
        raise DocumentTransitionError("Строка исключена корректировкой, уведомление по ней не создаётся.")
    if ControlDocument.objects.filter(list_entry=list_entry, document_type__code=NOTICE_TYPE_CODE).exists():
        raise DocumentTransitionError("Уведомление по этой строке уже создано.")
    if hasattr(list_entry, "control_case"):
        raise DocumentTransitionError("По этому субъекту в этом перечне уже открыто дело.")

    document_type = DocumentType.objects.get(code=NOTICE_TYPE_CODE)
    document = ControlDocument.objects.create(
        list_entry=list_entry, document_type=document_type, status=DocumentStatus.DRAFT, created_by=created_by
    )
    NoticeDetails.objects.create(document=document, created_by=created_by, **fields)
    return document


def approve_notice(document: ControlDocument, *, approved_by=None) -> ControlDocument:
    if document.document_type.code != NOTICE_TYPE_CODE:
        raise DocumentTransitionError("Согласовать этим действием можно только уведомление.")
    if document.status != DocumentStatus.DRAFT:
        raise DocumentTransitionError(
            f"Уведомление можно согласовать только из статуса «Проект», сейчас: {document.status}"
        )
    document.status = DocumentStatus.APPROVED
    document.approved_at = timezone.now()
    document.approved_by = approved_by
    document.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
    return document
```

Устойчивые конвенции:

* Коды типов документов — модульные константы `NOTICE_TYPE_CODE = "notice"` и т.п. (дублируются по модулям, единого enum нет).
* Проверка «это тот тип документа?» и «статус допускает переход?» — первые две строки любой transition-функции; сообщения — русские, с указанием текущего статуса.
* Изменение статуса — присваивание полей + `save(update_fields=[..., "updated_at"])` (всегда явно включают `updated_at`, иначе `auto_now` не обновится).
* Побочные эффекты перехода — в той же функции под `@transaction.atomic`: `send_notice` выдаёт два номера и создаёт `ControlCase`; `sign_appointment_act` создаёт документы `card-1-p` (READY) и `checklist` (GENERATED) и вызывает `generate_checklist`; `sign_result_act` вызывает `generate_prescription`; `register_package_1` меняет статусы 4 документов, ставит `case.started_on`, создаёт `article-155`.
* Циклические зависимости между приложениями решаются **локальными импортами внутри функции** (`from apps.cases.models import ControlCase` внутри `send_notice`; `from apps.checklists.services.checklist import has_completable_violation` внутри `approve_result_act`).
* Валидация обязательных вложений на переходе: `approve_appointment_act` требует `REQUIRED_ATTACHMENT_KINDS = (EXPLANATORY_NOTE, INVESTOR_BASIS)` через `document_attachments(document).values_list("kind", flat=True)`.

### 3.2 Транзакции и блокировки

* `@transaction.atomic` на функциях с несколькими записями (45 вхождений). Простые одно-строчные переходы (`approve_*`, `send_prescription`) без декоратора.
* `select_for_update()` там, где возможны гонки: `issue_number` (строка `NumberSequence`), `record_acknowledgement` (документ), `decide_item` (пункт предписания), `approve_package_2_step` (пакет), `save_checklist_violation` (пункт листа), `trigger_risk_run` (выгрузка ДФО). Шаблон — перечитать объект под блокировкой в начале:

```python
def record_acknowledgement(document, *, channel, acknowledged_on, proof_ref="", attachment=None, recorded_by=None):
    with transaction.atomic():
        document = ControlDocument.objects.select_for_update().get(pk=document.pk)
        if document.status not in {DocumentStatus.SENT, DocumentStatus.ACKNOWLEDGED}:
            raise DocumentTransitionError(f"Ознакомление можно зафиксировать только после отправки документа, сейчас: {document.status}")
        ...
        try:
            record = Acknowledgement.objects.create(...)
        except IntegrityError as exc:
            raise DocumentTransitionError("Ознакомление этим каналом уже зафиксировано.") from exc
        if document.status == DocumentStatus.SENT:
            document.status = DocumentStatus.ACKNOWLEDGED
            document.save(update_fields=["status", "updated_at"])
        return record
```

* `IntegrityError` от уникальных ограничений всегда перехватывается и превращается в доменную ошибку (`DocumentTransitionError`, `ListTransitionError`, `serializers.ValidationError({"bin": [...]})`), а не отдаётся 500. Вложенный `with transaction.atomic()` вокруг рискованного `create` — чтобы не сломать внешнюю транзакцию (см. `issue_number`).
* Идемпотентность: `trigger_risk_run` возвращает существующий `RiskRun(status=DONE)`; `import_extract` — `already_imported=True`; `issue_number` — существующий `IssuedNumber` для того же target; `build_package_1/2` — `get_or_create` пакета и `update_or_create` позиций.
* Массовые операции — `bulk_create` (`SemiannualListEntry`, `CaseChecklistItem`, `PrescriptionItem`, `RiskCandidate`), в `dfo_import` — `bulk_create(update_conflicts=True, update_fields=..., unique_fields=...)` (upsert Django 4.1+).

### 3.3 Исключения

| Класс | Где | Наследует | Кто ловит |
|---|---|---|---|
| `DocumentTransitionError` | `documents/services/exceptions.py` | `Exception` | все view'ы documents/checklists/execution/ersop/cabinet → `serializers.ValidationError({"detail": str(exc)})` → HTTP 400. Используется и за пределами documents (checklists, execution, ersop) как общая «ошибка бизнес-перехода» |
| `ListTransitionError` | `semiannual/services/list_formation.py` | `Exception` | semiannual views → 400 |
| `DfoExtractValidationError(errors: list[str])` | `reporting/services/dfo_import.py` | `Exception` | `DfoExtractImportView` → `ValidationError({"file": exc.errors})` |
| `SequenceNotDefined` | `core/services/numbering.py` | `LookupError` | не ловится (ошибка конфигурации → 500 намеренно) |
| `KeycloakError` → `TokenExchangeError`, `KeycloakUnavailableError`, `EmailAlreadyLinkedError` | `accounts/services/keycloak.py` | `RuntimeError` | Keycloak-view'ы → redirect на SPA с `?auth_error=<reason>` |

Envelope ошибок API (`core/exceptions.py::exception_handler`, подключён через `REST_FRAMEWORK["EXCEPTION_HANDLER"]`):

```python
def _envelope(exc, status_code):
    return {"type": "about:blank", "title": _STATUS_TITLES.get(status_code, "HTTP Error"),
            "status": status_code, "detail": None,
            "code": getattr(exc, "default_code", None) or exc.__class__.__name__}

def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None: return None
    if isinstance(response.data, list):
        response.data = {**_envelope(exc, response.status_code), api_settings.NON_FIELD_ERRORS_KEY: response.data}
    elif isinstance(response.data, dict) and "type" not in response.data:
        response.data = {**_envelope(exc, response.status_code), "detail": response.data.get("detail"),
                         **{k: v for k, v in response.data.items() if k != "detail"}}
    return response
```

Пример 400 при валидации полей: `{"type":"about:blank","title":"Bad Request","status":400,"detail":null,"code":"ValidationError","email":["..."],"password":["..."]}`. Пример бизнес-ошибки: `{"...","status":400,"detail":"Уведомление можно согласовать только из статуса «Проект», сейчас: SENT","code":"invalid"}`. 404 вне DRF (нет URL) и 500 приводятся к тому же виду `JsonNotFoundMiddleware` и `core/views.py` только для путей `/api/`.

### 3.4 Нумерация (`core/services/numbering.py`)

```python
def define_sequence(*, key, scope="", pattern, created_by=None) -> NumberSequence  # update_or_create

def issue_number(*, key, target: models.Model, scope="", context: dict | None = None) -> str:
    content_type = ContentType.objects.get_for_model(target)
    with transaction.atomic():
        sequence = NumberSequence.objects.select_for_update().get(key=key, scope=scope)   # SequenceNotDefined
        existing = IssuedNumber.objects.filter(sequence=sequence, content_type=content_type, object_id=target.pk).first()
        if existing is not None:
            return existing.value                     # идемпотентно для того же объекта
        sequence.current_value += 1
        sequence.save(update_fields=["current_value", "updated_at"])
        value = sequence.pattern.format(seq=sequence.current_value, **context)
        try:
            with transaction.atomic():
                IssuedNumber.objects.create(sequence=sequence, value=value, content_type=content_type, object_id=target.pk)
        except IntegrityError:
            return IssuedNumber.objects.get(sequence=sequence, content_type=content_type, object_id=target.pk).value
        return value
```

Шаблоны сидируются `seed_number_sequences` (`SEQUENCES = [(key, scope, pattern)]`):

| key | pattern | context, кто вызывает |
|---|---|---|
| `control-case` | `ПК-{region:02d}-{yy}-{seq:04d}` | `send_notice`: `region=list_entry.region.number`, `yy=now.strftime("%y")`; target — документ уведомления |
| `notice-outgoing` | `Исх-{yyyy}-{seq:04d}` | `send_notice` |
| `ersop-package-1` | `ERSOP-OUT-{yyyy}-{seq:04d}` | `fake_register_package` |
| `ersop-package-2` | `ERSOP-CLOSE-{yyyy}-{seq:04d}` | `fake_register_package` |

Код перечня формируется без счётчика: `code or f"ПК-{year}-{half:02d}"`. Счётчик — общий на систему (scope=""), сброса по году нет — год входит в шаблон, но `seq` сквозной. Тесты `core/tests/test_numbering.py` проверяют gapless-выдачу 20 потоками и согласие 10 гонок за один объект.

### 3.5 Файлы (`core/services/files.py`, `*/services/attachments.py`)

* `sha256_of(uploaded_file)` — считает SHA-256 по `chunks()` и делает `seek(0)`.
* Создание вложения — функция на владельца: `documents.services.attachments.attach_file(document, *, kind, uploaded_file, uploaded_by)`, `checklists.services.attachments._attach(model_instance, ...)` (generic по `type(model_instance)`), `execution.services.attachments.attach_execution_file(item, *, kind, ...)`. Все делают одно и то же `Attachment.objects.create(content_type=..., object_id=str(pk), kind, file=uploaded_file, original_name=uploaded_file.name, size, mime=uploaded_file.content_type or "application/octet-stream", checksum=sha256_of(...), uploaded_by)`.
* Выборка — парная функция `document_attachments(document, *, kind=None)`, `checklist_item_attachments`, `violation_attachments`, `general_reference_attachments`, `execution_attachments`.
* Хранилище: `STORAGES["default"]` = `FileSystemStorage` (`MEDIA_ROOT = BASE_DIR / "media"`) в local; в production — `storages.backends.s3.S3Storage` с `endpoint_url=MINIO_ENDPOINT_URL`, `default_acl="private"`, `querystring_auth=True`, `file_overwrite=False`. Путь в бакете — `attachments/<content_type_id>/<object_id>/<uuid>_<имя>`.
* Отдача файла — **только через бэкенд** (`FileResponse(attachment.file.open("rb"), filename=attachment.original_name, as_attachment=True)`) с теми же проверками прав, что у объекта-владельца; `FileNotFoundError` → `Http404("Файл вложения не найден в хранилище.")`. Ссылки в API — относительные URL на эти view'ы (`AttachmentSerializer.get_file` → `reverse("document-download-attachment", ...)`), фронт достраивает `API_BASE_URL`.
* Удаление файла: `attachment.file.delete(save=False); attachment.delete()` (`DownloadChecklistViolationAttachmentView.delete`).
* Ограничений на размер/тип файла на уровне бэкенда нет (только nginx `client_max_body_size 25m`).

### 3.6 Что сервисы НЕ делают (и что стоит добавить в ЭВГА)

* Не пишут `AuditEvent` — история переходов восстанавливается только по полям `approved_at/by`, `signed_at/by`, `sent_at/by` документа, `ErsopExchange`, `ExecutionDecision`. Для ЭВГА (где фронт хранит `HistoryEntry {at, actor, action, comment}` на деле) правильно: в каждой transition-функции после `save()` вызывать общий helper вида `record_event(target, action=AuditAction.APPROVE, status_from=..., status_to=..., actor=..., reason=...)` из `core`.
* Не отправляют уведомления/письма, нет Celery/очередей, нет фоновых задач — всё синхронно в запросе.
* Не генерируют PDF/печатные формы — «печать» делает фронт из `details`.

---

## 4. API-слой

### 4.1 Два типа view'ов

**(a) Ресурс — `GenericViewSet` + mixins**, только нужные (чаще `ListModelMixin, RetrieveModelMixin`; у `SubjectViewSet` ещё `Create/Update`; DELETE нигде не разрешён — тест `test_delete_is_not_allowed_even_for_a_decide_level_user` ожидает 405):

```python
class ControlDocumentViewSet(ScopedQuerySetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    http_method_names = ["get", "patch", "head", "options"]
    queryset = ControlDocument.objects.select_related(
        "document_type", "list_entry", "list_entry__department", "list_entry__subject",
        "list_entry__semiannual_list__government_body",
        "notice_details", "appointment_act_details", "result_act_details", "prescription_details",
    ).prefetch_related("acknowledgements", "attachments")
    serializer_class = ControlDocumentSerializer
    filterset_fields = ["list_entry", "document_type__code", "status"]
    required_domain = PermissionDomain.CASES
    scope_department_field = "list_entry__department"

    @property
    def required_levels(self) -> set[str]:
        return {PermissionLevel.EDIT} if self.action == "partial_update" else _READ_LEVELS

    def get_permissions(self):
        return [IsAuthenticated(), HasDomainLevel()]

    def partial_update(self, request, *args, **kwargs):
        document = self.get_object()
        if document.status != DocumentStatus.DRAFT:
            raise serializers.ValidationError({"detail": "Редактировать можно только документ в статусе «Проект»."})
        related_name, serializer_cls = DETAILS_SERIALIZERS[document.document_type.code]   # реестр по коду типа
        serializer = serializer_cls(getattr(document, related_name), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ControlDocumentSerializer(document).data)
```

Конвенции ViewSet:
* `queryset` с полными `select_related/prefetch_related` под сериализатор (есть тест, что list не тянет лишнее: `test_list_does_not_prefetch_the_unused_persons_relation` через `CaptureQueriesContext`).
* `get_serializer_class()` разделяет `*ListSerializer` / `*DetailSerializer` (subjects).
* `http_method_names` сужается явно.
* `_READ_LEVELS = {VIEW, EDIT, APPROVE, SIGN, DECIDE}` — модульная константа в каждом `views.py` (дублируется во всех приложениях; кандидат на вынос в `accounts`).
* Уровень для записи — через `@property required_levels`, зависящий от `self.action`.
* `lookup_field` меняют, когда ресурс адресуется чужим ключом: `CaseChecklistViewSet.lookup_field = "document_id"`, `lookup_url_kwarg = "pk"`.

**(b) Действие — отдельный `APIView`** (не `@action`), один класс на переход, с `required_domain/required_levels` и явным `get_permissions`:

```python
class ApproveDocumentView(APIView):
    required_domain = PermissionDomain.CASES
    required_levels = {PermissionLevel.APPROVE}

    def get_permissions(self):
        return [IsAuthenticated(), HasDomainLevel()]

    _APPROVERS = {"notice": approve_notice, "appointment-act": approve_appointment_act,
                  "result-act": approve_result_act, "prescription": approve_prescription}

    @extend_schema(request=None, responses={200: ControlDocumentSerializer},
                   description="Проект → Согласовано. Применимо к уведомлению, акту о назначении, акту о результатах и предписанию.")
    def post(self, request, pk):
        document = get_object_or_404(ControlDocument, pk=pk)
        _assert_department_in_scope(request.user, document.list_entry.department)
        approver = self._APPROVERS.get(document.document_type.code)
        if approver is None:
            raise serializers.ValidationError({"detail": "Согласование для этого типа документа ещё не реализовано."})
        try:
            approver(document, approved_by=request.user)
        except DocumentTransitionError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response(ControlDocumentSerializer(document).data)
```

Канонический порядок внутри `post`: `get_object_or_404` → `_assert_department_in_scope` → валидация тела `Serializer(data=request.data).is_valid(raise_exception=True)` → вызов сервиса в `try/except DocumentTransitionError` → ответ полным read-сериализатором объекта (клиент сразу получает новое состояние; при создании — `status=201`). Диспетчеризация по типу документа — словарь `{code: service_fn}` в классе (`_APPROVERS`, `_SIGNERS`) или `if/elif` (`SendDocumentView`).

Для действий с файлами (`AcknowledgeDocumentView`, `RegisterSubmissionView`, `DecideItemView`) файл сначала прикладывается через `attach_*`, затем вызывается сервис — всё внутри `with transaction.atomic()` в view.

Общие базовые классы для повторяющихся действий: `checklists/api/views.py::ChecklistPermissionMixin` → `ChecklistReadView/ChecklistWriteView`, `BaseChecklistAttachFileView(model, attach_func, response_serializer_class)`, `BaseChecklistDownloadAttachmentView(model, attachments_func)`; `semiannual/api/views.py::_VersionTransitionView._transition(request, pk, action)`.

Композитный read-эндпоинт «рабочее место дела» — `CaseWorkspaceView` собирает один JSON из нескольких сериализаторов: `{"case", "list_entry", "documents", "ersop_packages", "checklist"}` (описан `CaseWorkspaceSerializer` только для схемы).

### 4.2 Сериализаторы

* **Read-сериализаторы** — `ModelSerializer` с `read_only_fields = fields` (весь набор read-only), человекочитаемые дополнения через `source="rel.field"` (`subject_name = CharField(source="list_entry.subject.name")`) и `SerializerMethodField` для `*_name` акторов (`user_display_name(user) = user.full_name or user.username` — функция дублируется в 3 модулях) и label'ов (`status_label`).
* **Request-сериализаторы** — плоские `serializers.Serializer` с докстрингом `"""Request body of the <...> endpoint."""`, имена `Create*Serializer`, `Save*Serializer`, `Register*Serializer`, `Decide*Serializer`, `Attach*FileSerializer`, `*TriggerSerializer`; поля с `required=False, allow_blank=True, default=""` / `allow_null=True, default=None`; ссылки по UUID (`list_entry = UUIDField()`), а не `PrimaryKeyRelatedField` — объект достаётся во view через `get_object_or_404` (исключение: `subject_matter = PrimaryKeyRelatedField(queryset=InspectionSubjectMatter.objects.all())`).
* **Update-сериализаторы** для PATCH — `ModelSerializer` с минимальным `fields` (`PrescriptionItemUpdateSerializer: ["risk_degree", "recommendation", "due_date"]`; `SemiannualListEntrySerializer.read_only_fields = [f for f in fields if f != "responsible"]`).
* **Полиморфные детали** — реестр `DETAILS_SERIALIZERS = {"notice": ("notice_details", NoticeDetailsSerializer), ..., "card-1-p": (None, Card1PDetailsSerializer)}`; `ControlDocumentSerializer.get_details` берёт related по имени, `None` означает «сериализовать сам документ» (`Card1PDetailsSerializer.to_representation` собирает виртуальную карточку из акта/дела/субъекта).
* Контекст `{"cabinet": True}` переключает `reverse()` ссылок на кабинетные download-view'ы и скрывает внутренние вложения (`CaseChecklistItemSerializer.get_attachments → []`).
* `to_representation` может дотягивать prefetch (`CaseChecklistSerializer` → `prefetch_related_objects([instance], "items__item", ...)`).
* Валидация в сериализаторе — `validate_<field>`, `validate(attrs)` с преобразованием входа (`actual_region_name` → `region`, `department`), `UniqueValidator` + кастомные валидаторы модели (`bin_validator`, `checksum_validator`).
* Схема ответа для нестандартных тел описывается отдельным `Serializer` только ради OpenAPI (`DfoExtractImportResultSerializer`, `RiskRunTriggerResultSerializer`, `CaseWorkspaceSerializer`).

### 4.3 Фильтры, поиск, сортировка, пагинация

* Глобально: `DEFAULT_FILTER_BACKENDS = [DjangoFilterBackend, SearchFilter, OrderingFilter]`, `DEFAULT_PAGINATION_CLASS = apps.core.pagination.PageNumberPaginationWithPageSize` (`page_size_query_param="page_size"`, `max_page_size=200`, `PAGE_SIZE=25`).
* Простые фильтры — `filterset_fields = [...]` на ViewSet; сложные — `django_filters.FilterSet` в `api/filters.py`: `Meta.fields = {...}` словарём (`SubjectFilter`), method-фильтры (`CaseRegistryFilter.filter_search` через `Q(...)|Q(...)`, `filter_status`), алиасы полей (`PrescriptionItemFilter.document = UUIDFilter(field_name="prescription__document_id")`), обратная совместимость (`_VersionAliasFilter.version` → `semiannual_list_id`), `MultipleChoiceFilter` для повторяющихся параметров (`?risk_category=HIGH&risk_category=MEDIUM`).
* `search_fields`, `ordering_fields` объявляются на ViewSet (subjects, cases).

### 4.4 drf-spectacular

* Каждое действие аннотировано `@extend_schema(request=<Serializer|None>, responses={code: Serializer | OpenApiTypes.BINARY | OpenApiResponse(...)}, description="...")`; для классов с наследуемыми методами — `@extend_schema_view(post=extend_schema(...))`.
* `SPECTACULAR_SETTINGS`: `TITLE="SAQ — Профилактический контроль API"`, `COMPONENT_SPLIT_REQUEST=True` (ключ продублирован в файле), `SERVE_INCLUDE_SCHEMA=False`.
* Cookie-аутентификация описана в схеме через `OpenApiAuthenticationExtension` (`accounts/schema.py`, `name="sessionCookie"`, `type: apiKey in cookie`).

### 4.5 Django admin

Каждое приложение регистрирует модели с `list_display`, `list_filter`, `search_fields`, `list_select_related`, inline'ами для детей (`SubjectPersonInline`, `RolePermissionInline`, `ErsopPackageItemInline`, `ChecklistItemInline`…), `readonly_fields` для системных полей, запретом `has_change/delete_permission` для append-only (`AuditEventAdmin`, `IssuedNumberAdmin`, `AuthSessionAdmin`). Admin — рабочий инструмент команды для сидов/ролей (назначение ролей делается в admin, API для этого нет).

---

## 5. Auth / RBAC

### 5.1 Пользователь и сессии

`accounts.User(AbstractUser)`: `id: UUID`, `auth_provider: AuthProvider(keycloak|local)` (обязательное), `full_name`, `position`, `phone`, `email` (nullable, регистронезависимо-уникальный через `UniqueConstraint(Lower("email"))`), `department → catalogs.Department`, `is_subject_representative`, `subject → subjects.Subject` (для представителей). `AUTH_USER_MODEL = "accounts.User"`, хэшер Argon2.

Сессия — собственная таблица `AuthSession(id=token_urlsafe(48), user, provider, access_token, refresh_token, id_token, access_token_expires_at, created_at, last_seen_at)`; cookie `API_SESSION_COOKIE_NAME = "saq_session"` (httpOnly, `secure = env API_SESSION_COOKIE_SECURE` (default `not DEBUG`), SameSite=Lax, max_age 12 ч = `API_SESSION_MAX_AGE`). Django-сессия admin живёт в отдельной cookie `saq_admin_session`.

`accounts/authentication.py::SessionCookieAuthentication(BaseAuthentication)`:

```python
def authenticate(self, request):
    if not request.COOKIES.get(settings.API_SESSION_COOKIE_NAME): return None
    session = get_session_from_request(request)
    if session is None or not session.user.is_active: return None
    if session.provider == AuthProvider.LOCAL:
        if timezone.now() - session.created_at > settings.API_SESSION_MAX_AGE:
            session.delete(); return None
    try:
        keycloak.ensure_fresh_access_token(session)     # refresh_token grant при истечении
    except keycloak.KeycloakError:
        session.delete(); return None
    touch_session(session)
    return (session.user, session)
```

Замечание по безопасности: это `BaseAuthentication`, а не `SessionAuthentication`, поэтому DRF **не проверяет CSRF** для API; защита — SameSite=Lax + CORS с `CORS_ALLOW_CREDENTIALS=True` и списком `CORS_ALLOWED_ORIGINS`. При переносе в ЭВГА либо сохранить как есть (осознанно), либо добавить `enforce_csrf`.

### 5.2 Локальный вход и Keycloak

* `POST /api/auth/local/register` — только для представителя субъекта: `RegisterSerializer(email, password, full_name, bin)` → `validate_password`, поиск `Subject` по БИН → `User(username=email, auth_provider=LOCAL, is_subject_representative=True, subject=...)` → сессия + cookie → 201 `MeSerializer`.
* `POST /api/auth/local/login` — `User.objects.filter(email__iexact, auth_provider=LOCAL)` + `check_password` → 401 `AuthenticationFailed("Incorrect email or password")` / 403 если `is_active=False`.
* `GET /api/auth/me` → `MeSerializer`: `id, username, full_name, email, auth_provider, position, department, is_subject_representative, subject{id,bin,name}, roles[{code,name,scope,department}]` (только активные `RoleAssignment`).
* Keycloak: `KeycloakLoginView` генерирует `state`, `nonce`, PKCE `code_verifier` (`secrets.token_urlsafe(64)`) → `OidcAuthRequest` (TTL 10 мин, старые чистятся) → redirect на `authorization_endpoint` (discovery кэшируется 6 ч в модуле). `KeycloakCallbackView` проверяет `iss`, `state`, TTL, обменивает код (`httpx.post token_endpoint`), валидирует `id_token` через `PyJWKClient` (RS256, `audience=KEYCLOAK_CLIENT_ID`, `issuer`, `nonce`), `provision_user_from_claims(claims)` (по `FederatedIdentity(issuer, sub)`; новый пользователь `username=f"kc_{sub}"`, `set_unusable_password()`; конфликт email → `EmailAlreadyLinkedError`), создаёт `AuthSession(provider=KEYCLOAK, tokens...)`, ставит cookie и редиректит на `redirect_target`. Ошибки — redirect `APP_BASE_URL?auth_error=1|expired|email_taken|unavailable`. `KeycloakLogoutView` возвращает `{"redirectTo": end_session_url(id_token)}`.
* Роли из Keycloak **не** берутся: после провижининга `roles == []`, роль назначает администратор в admin (`test_provisions_a_new_user_with_no_role_assigned`).

### 5.3 Ролевая модель

```python
class RoleScope(TextChoices): NATIONAL = "national"; TERRITORIAL = "territorial"
class Role(models.Model): code (unique, ≤32), name, order, scope
class PermissionDomain(TextChoices): SEMIANNUAL = "semiannual"; CASES = "cases"; EXECUTION = "execution"
class PermissionLevel(TextChoices): NONE, VIEW, EDIT, APPROVE, SIGN, DECIDE
class RolePermission: role, domain, level   # unique(role, domain)
class RoleAssignment: user, role, department (обязателен для territorial — clean()), valid_from, valid_to
    objects.active(at=None)  # valid_from <= at and (valid_to is null or >= at)
```

**Уровни не иерархичны**: `HasDomainLevel` проверяет `level__in=required_levels`, поэтому view перечисляет допустимые уровни явно (`_READ_LEVELS` = все пять, запись — `{EDIT}`, `{APPROVE}`, `{SIGN}`, `{DECIDE}`, у subjects — `{EDIT, DECIDE}`).

```python
class HasDomainLevel(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated: return False
        domain = getattr(view, "required_domain", None); levels = getattr(view, "required_levels", None)
        if not domain or not levels:
            raise AssertionError(f"{view.__class__.__name__} must set required_domain and required_levels to use HasDomainLevel")
        return RoleAssignment.objects.active().filter(
            user=user, role__permissions__domain=domain, role__permissions__level__in=levels).exists()

class IsSubjectRepresentative(BasePermission):   # кабинет субъекта
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_subject_representative and user.subject_id)
```

Скоупинг данных по подразделению — `accounts/querysets.py::ScopedQuerySetMixin` (миксин на ViewSet): `scope_department_field` (путь до FK department: `"department"`, `"list_entry__department"`, `"case__list_entry__department"`, `"document__list_entry__department"`, `"prescription__document__list_entry__department"`), `get_queryset()` → всё для national-роли, иначе `filter(<field>__in=allowed_department_ids(user))`; `assert_department_writable(department)` для create/update. Для action-view'ов (объект берётся через `get_object_or_404`, минуя `get_queryset`) — функция `documents/api/views.py::_assert_department_in_scope(user, department)` (PermissionDenied «Эта запись не входит в ваш территориальный скоуп.»); она импортируется во все остальные приложения. Для общенациональных объектов передают `None` → территориальные пользователи получают 403 (`FormVersion1View`, `_VersionTransitionView`).

Кабинет субъекта: `cabinet/api/views.py::_assert_subject_owns(user, subject_id)` + `get_queryset` фильтрует по `list_entry__subject=self.request.user.subject`.

### 5.4 Роли (seed_roles) — 14 ролей

| # | code | name | scope | semiannual | cases | execution |
|---|---|---|---|---|---|---|
| 1 | `list-officer` | Сотрудник по формированию полугодового списка | national | EDIT | VIEW | VIEW |
| 2 | `list-officer-inspector` | … с полномочиями проверяющего | national | EDIT | EDIT | VIEW |
| 3 | `list-supervisor` | Непосредственный руководитель по формированию списка | national | APPROVE | VIEW | VIEW |
| 4 | `list-supervisor-controller` | … с полномочиями по проведению контроля | national | APPROVE | EDIT | EDIT |
| 5 | `ca-specialist` | Специалист ПК центрального аппарата | national | NONE | EDIT | VIEW |
| 6 | `ca-approver` | Согласующее лицо ЦА | national | NONE | APPROVE | APPROVE |
| 7 | `ca-signer` | Подписывающее лицо ЦА | national | NONE | SIGN | SIGN |
| 8 | `ca-group-head` | Руководитель рабочей группы ЦА | national | NONE | EDIT | DECIDE |
| 9 | `territorial-specialist` | Специалист ПК территориального подразделения | territorial | NONE | EDIT | VIEW |
| 10 | `territorial-group-head` | Руководитель рабочей группы ТП | territorial | NONE | EDIT | DECIDE |
| 11 | `territorial-approver` | Согласующее лицо ТП | territorial | NONE | APPROVE | APPROVE |
| 12 | `territorial-signer` | Подписывающее лицо ТП | territorial | NONE | SIGN | SIGN |
| 13 | `observer` | Наблюдатель / аналитик | national | VIEW | VIEW | VIEW |
| 14 | `sysadmin` | Системный администратор SAQ | national | NONE | NONE | NONE (is_staff/superuser вручную) |

Сид — `Role.objects.update_or_create(code=..., defaults={...})` + `RolePermission.objects.update_or_create(role, domain, defaults={"level"})` под `@transaction.atomic`. Представитель субъекта ролей не имеет — доступ через флаг `is_subject_representative`.

---

## 6. Интеграции-заглушки (ЕРСОП)

`ersop/services/stub_exchange.py` — единственная «внешняя система», полностью имитируется:

```python
def fake_register_package(package: ErsopPackage) -> dict:
    """Заглушка вместо реального обращения к ЕРСОП, без сети"""
    now = timezone.now()
    if package.kind == ErsopPackageKind.PACKAGE_1:
        code = issue_number(key="ersop-package-1", target=package, context={"yyyy": now.year})
        return {"exchange_id": code, "status": "registered", "registration_number": code,
                "registration_date": now.date().isoformat()}
    code = issue_number(key="ersop-package-2", target=package, context={"yyyy": now.year})
    return {"exchange_id": code, "status": "accepted", "accepted_at": now.isoformat()}
```

Модель обмена: `ErsopPackage(case, kind 1|2, status DRAFT→SUBMITTED→REGISTERED|ACCEPTED, submitted_*, registration_number/date, accepted_at, package_2_approved_steps)` → `ErsopPackageItem(position_kind: ErsopPositionKind, document, is_ready, blocking_reason, order)` → `ErsopExchange(direction IN|OUT, exchange_id, request_payload JSON, response_payload JSON, occurred_at)`.

Паттерн «пакет»: `build_package_N(case)` (сборка/пересчёт готовности позиций, `update_or_create` по `(package, position_kind)`, `blocking_reason` с причиной) → `submit_package_N(package, by=)` (проверка, что все `is_ready`, для пакета №2 — что `package_2_approved_steps == len(PACKAGE_2_APPROVAL_STEPS)` (5 именованных ролей-констант), переводит документы в `IN_ERSOP`/`IN_PACKAGE_1`/`IN_PACKAGE_2`) → `register_package_N(package)` (вызов заглушки, запись `ErsopExchange(direction=IN, response_payload=result)`, проставление рег. номеров и статусов). Ответ заглушки хранится как есть в JSON — при замене на реальный клиент меняется только `fake_register_package` и парсинг `result`.

Для ЭВГА: тот же приём — модуль `services/stub_<system>.py` с функцией, возвращающей dict «как от внешней системы», + модель `*Exchange` с `request_payload/response_payload`, + `issue_number` для псевдорегистрационных номеров. Реальные клиенты (httpx, как в `accounts/services/keycloak.py`: `timeout=10.0`, `raise_for_status`, свои классы ошибок `*UnavailableError`) подключаются позже без изменения API.

---

## 7. Тесты

* Конфиг `pyproject.toml`: `DJANGO_SETTINGS_MODULE = "config.settings.local"`, `python_files = ["tests.py", "test_*.py"]`, `testpaths = ["apps"]`, `addopts = "--reuse-db"`. Запуск: `pytest backend`. Тесты живут в `apps/<app>/tests/test_*.py` (пакет с `__init__.py`); нет `conftest.py`, нет фабрик (factory-boy в requirements не задействован).
* Единица — функция `test_<что>_<ожидание>` с говорящим именем (`test_territorial_editor_cannot_create_a_subject_in_another_department`, `test_racing_calls_for_the_same_target_agree_on_one_value`); группировка классами только в `test_numbering.py` (`TestIssueNumberSequential`, `TestIssueNumberConcurrency`).
* `pytestmark = pytest.mark.django_db` на модуль; `django_db(transaction=True)` для конкурентных тестов с `threading.Thread` (закрывают `connection.close()` в воркере).
* Фикстуры данных — простые приватные функции-хелперы в модуле (`_subject_type()`, `_department(code, region_code, name)`, `_user_with_cases_role(*, scope, level, department=None)` — создаёт `User` + `Role(code=f"role-{uuid4().hex[:8]}")` + `RolePermission` + `RoleAssignment`), иногда `@pytest.fixture` (`client`, `subject`, `subject_type`, `report_form`).
* API-тесты: `APIClient()` + `client.force_authenticate(user)`; проверяют статус-код, `response.data["count"]`, побочные эффекты в БД; неавторизованный → 401; чужой department → 404 на retrieve / 403 на action.
* Юнит-тесты permission/scoping делаются без HTTP — фейковые `_Request(user)`, `_View` с `required_domain/required_levels`, `_ScopedView(ScopedQuerySetMixin)`.
* Сервисы Keycloak тестируются с `unittest.mock.patch("apps.accounts.services.keycloak.get_discovery_document", return_value=_DISCOVERY)`.
* Management-команды — `call_command("seed_report_forms", stdout=StringIO())` + проверка идемпотентности (двойной вызов).

Покрытие по файлам (79 тестов): core — audit_event (6), error_views (2), exception_handler (3), numbering (7); accounts — keycloak_login_view (1), keycloak_provisioning (3), local_auth (7), permissions (4), rbac_scoping (5); catalogs — models (4); subjects — api (12), models (7); reporting — dfo_import (11), seed_report_forms (2); risk — rules (4); semiannual — form_version1_api (1, сквозной сценарий). **Нет тестов** у documents, cases, checklists, execution, ersop, cabinet (пакеты `tests/` есть, но пустые) — основной документооборот не покрыт; для ЭВГА это первое, что стоит закрыть тестами сервисов переходов.

---

## 8. Инфраструктура

### 8.1 Settings

`config/settings/base.py` читает `.env` через `django-environ` (`environ.Env.read_env(BASE_DIR / ".env")`). `local.py`: `DEBUG=True`, `ALLOWED_HOSTS=["*"]`. `production.py`: `DEBUG=False`, `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO","https")`, `SECURE_SSL_REDIRECT` (env, default True), `SESSION_COOKIE_SECURE/CSRF_COOKIE_SECURE` (env), HSTS 30 дней, `STORAGES["default"]` → S3/MinIO. `manage.py` по умолчанию `local`, `wsgi.py/asgi.py` — `production`.

| Переменная | Назначение / default |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.local` / `production` |
| `DJANGO_SECRET_KEY` | обязательна |
| `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | `false`, `[]` |
| `DATABASE_URL` | `postgres://postgres:postgres@127.0.0.1:5432/saq_prof_control` |
| `CORS_ALLOWED_ORIGINS` | список; `CORS_ALLOW_CREDENTIALS=True` |
| `API_SESSION_COOKIE_SECURE` | `not DEBUG` |
| `APP_BASE_URL` | `http://127.0.0.1:5173/` — куда редиректить после Keycloak |
| `KEYCLOAK_ISSUER`, `KEYCLOAK_CLIENT_ID` (`saq-backend`), `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_REDIRECT_URI`, `KEYCLOAK_POST_LOGOUT_REDIRECT_URI` | пусто = Keycloak выключен, работает локальный вход |
| `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET` (`saq-attachments`), `MINIO_ENDPOINT_URL` | только production |
| `DJANGO_SECURE_SSL_REDIRECT` | production, default True (в deploy/.env — false для HTTP) |

Прочее: `LANGUAGE_CODE="ru"`, `TIME_ZONE="UTC"`, `USE_TZ=True`, `DEFAULT_AUTO_FIELD=BigAutoField` (не влияет — pk UUID), `STATIC_ROOT=BASE_DIR/"staticfiles"`, whitenoise `CompressedManifestStaticFilesStorage`. `MIDDLEWARE`: corsheaders → security → whitenoise → sessions → common → csrf → auth → messages → clickjacking → `apps.core.middleware.JsonNotFoundMiddleware`.

### 8.2 Docker / деплой

* `Dockerfile`: `python:3.13-slim`, `PYTHONDONTWRITEBYTECODE/PYTHONUNBUFFERED/PIP_NO_CACHE_DIR`, ставит только `requirements/base.txt`, `ENTRYPOINT /entrypoint.sh`, `CMD gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile - --error-logfile -`.
* `docker/entrypoint.sh`: `set -eu; migrate --noinput; collectstatic --noinput; for command in seed_catalogs seed_roles seed_number_sequences seed_document_types seed_report_forms seed_checklists seed_risk_rules; do python manage.py "$command"; done; exec "$@"` — сиды идемпотентны и выполняются при каждом старте.
* `docker-compose.yml` (корень репо): `postgres:16-alpine` (healthcheck `pg_isready`), `minio/minio` + одноразовый `minio-init` (`mc alias set; mc mb --ignore-existing`), `backend` (build `./backend`, `ports 8000:8000`, env из `deploy/.env`, volume `staticfiles`, `depends_on` postgres healthy + minio-init completed, healthcheck `python manage.py check --database default` каждые 30 с, `start_period 60s`). Фронт в контейнер не входит: `deploy/README.md` описывает nginx на Ubuntu, который раздаёт `frontend/dist` и проксирует `/api/` и `/admin/` на `127.0.0.1:8000`, `client_max_body_size 25m`, `/static/` → `deploy/staticfiles`.
* Локальная разработка (Windows-ориентирована): `.venv` в корне, `backend/.env`, `docker compose up -d postgres`, `manage.py migrate` + 7 seed-команд, `runserver 127.0.0.1:8000`; фронт Vite проксирует `/api` → `VITE_DEV_API_TARGET`. `scripts/dev/start-dev.ps1` поднимает оба.
* Superuser создаётся через shell с обязательным `auth_provider=AuthProvider.LOCAL`; для фронта ему нужно назначить роль в admin.

### 8.3 Ruff / качество

`[tool.ruff] line-length=120, target-version="py313", extend-exclude=["**/migrations/*"]`; `select=["E","F","I","UP","B","DJ"]`, `ignore=["DJ001"]` (разрешён `null=True` на CharField); per-file `E501` отключён для длинных seed-таблиц. Типизация — аннотации в сигнатурах (`-> ControlDocument`, `set[str]`, `dict | None`), `django-stubs` в dev-зависимостях, mypy не настроен. Докстринги — короткие, русские, объясняют «почему» (часто с отсылкой к ТЗ: «Табл. 38 стр. 14»).

---

## 9. Seed-команды и справочники

Единый шаблон: модульные константы-списки/словари данных → `class Command(BaseCommand)` с `help` → `@transaction.atomic def handle` → цикл `Model.objects.update_or_create(<natural key>, defaults={...})` → `self.stdout.write(self.style.SUCCESS(f"<Entity>: {n}"))`. Зависимости между сидами — по порядку в `entrypoint.sh`; `seed_risk_rules` явно проверяет предпосылки и бросает `CommandError("... Run seed_catalogs first.")`, умеет `--keep-missing` и удаляет/деактивирует (`ProtectedError` → `update(is_active=False)`) правила, которых нет в сиде.

| Команда | Что заполняет | Ключ идемпотентности |
|---|---|---|
| `seed_catalogs` | 20 `Region` (code, number, name_ru/kk), 21 `Department` (`KVGA-CENTRAL` is_central + `DVGA-<REGION>`), 1 `GovernmentBody` (`KVGA-MF-RK`), 6 `SubjectTypeRef` (АО, ПАО, ПОБ, ОПСБ, ОПИ, ПО), 4 `BusinessCategory`, 3 `ViolationSeverity` (gross/significant/minor), 3 `RiskDegree` (high/medium/low), 3 `NormativeAct`, 3×6 `InspectionSubjectMatter` | `code` |
| `seed_roles` | 14 `Role` + `RolePermission` | `code`, `(role, domain)` |
| `seed_number_sequences` | 4 `NumberSequence` | `(key, scope)` |
| `seed_document_types` | 9 `DocumentType` | `code` |
| `seed_report_forms` | 19 `ReportForm` ДФО по типам субъектов | `code` |
| `seed_checklists` | 6 `ChecklistTemplate` (по одному на тип субъекта) + 74 `ChecklistItem` (`АО-01`…`ПО-18`, severity) | `subject_type`, `(template, code)` |
| `seed_risk_rules` | 19 `RiskRule` (`AO-01`, `PAO-05`, `OPI-06`…) | `code` |

Справочники `catalogs` — обычные модели с `code unique`, без API (фронт держит свои копии/лейблы; в `API_INTEGRATION.md`: «subject-cabinet uses bundled, read-only demonstration reference data»). Для ЭВГА полезно сразу сделать read-only `CatalogViewSet`'ы, чтобы фронт не дублировал справочники.

---

## 10. Что из prof переиспользовать в бэкенде ЭВГА

Контекст ЭВГА (по `saq-evga-test/src/types.ts`): `AuditCase` с `AuditObject{bin, ru, kz, director, opf, abp, address, region, risk, score}`, `Basis`, `Person` (рабочая группа), `documents: AuditDocument[]` с **версиями** (`DocumentVersion`, `activeVersion(d).status`), `DocStatus` = «Проект | Направлен на согласование КК | На согласовании | На утверждении | Согласован | На подтверждении КВГА | На подтверждении реестра | На подписании рабочей группой | Возвращен на доработку | Отклонен | Активный», роли `auditor|reviewer|approver|quality|kvga|reestr-confirmer|invited-specialist|object|appeal-head|appeal-expert`, маршруты согласования (`ApprovalRoute`), запросы информации (`InformationRequestCycle`), исполнение (`ExecutionClaimedStatus`, `ExecutionConfirmedStatus`), обжалование, стадии `Stage 0|1|2`, `HistoryEntry`. Отсюда вердикты:

| Приложение prof | Вердикт | Что именно и как |
|---|---|---|
| **core** | **reuse-as-is** (+расширить) | `TimeStampedModel`, `Attachment`/`AttachmentKind` (добавить виды ЭВГА: `basis`, `working_paper`, `evidence`, `request_response`, `appeal`…), `AuditEvent`/`AuditAction` (расширить действиями `return`, `reject`, `confirm`, `submit`, `activate` и **реально писать из сервисов** — покрывает `HistoryEntry` фронта), `NumberSequence`/`IssuedNumber` + `numbering.py` (шаблоны номеров ЭВГА задать сидом), `exceptions.py`/`middleware.py`/`views.py`/`pagination.py`/`files.py` — без изменений. Вынести сюда общий `TransitionError` и `_READ_LEVELS`, `user_display_name` |
| **accounts** | **adapt** | `User`, `AuthProvider`, `AuthSession`, `OidcAuthRequest`, `FederatedIdentity`, `authentication.py`, `services/keycloak.py`, `services/sessions.py`, local/keycloak view'ы, `MeSerializer` — как есть. `PermissionDomain` заменить на домены ЭВГА (например `audit`, `quality`, `registry`, `execution`, `appeal`), `PermissionLevel` дополнить (`CONFIRM`, `QUALITY`?), `seed_roles` переписать под 10 ролей фронта (`auditor`, `reviewer`, `approver`, `quality`, `kvga`, `reestr-confirmer`, `invited-specialist`, `object`, `appeal-head`, `appeal-expert`), `is_subject_representative/subject` → представитель объекта аудита (`object`). `ScopedQuerySetMixin` оставить, `scope_department_field` указывать на department дела/рабочей группы; `_assert_department_in_scope` перенести в `accounts.querysets` |
| **catalogs** | **adapt** | `Region`, `Department`, `GovernmentBody`, `NormativeAct`, абстрактные `CodeNamedModel`/`OrderedCodeNamedModel`, `seed_catalogs` (регионы/подразделения) — как есть. `SubjectTypeRef`, `BusinessCategory`, `ViolationSeverity`, `RiskDegree`, `InspectionSubjectMatter`, `ControlEligibilityRule` — prof-специфичны; для ЭВГА нужны справочники ОПФ, АБП, видов аудита/оснований, классификатор нарушений и т.п. (перенести из схемы `surfk.*` старой n8n-реализации), по тому же шаблону + read-only API |
| **subjects** | **adapt** | `Subject` + `validators.py` (БИН/ИИН с контрольной суммой) + `SubjectPerson` + `SubjectViewSet/Filter/Serializers` + тесты — основа для «объекта аудита»: добавить `name_kk`, `director`, `opf`, `abp`, `risk`, `score`; `RegistrationStatus` оставить |
| **documents** | **adapt (паттерн) / rewrite (модели)** | Сохранить: `DocumentType` как сидируемый справочник (`code`, `stage`, `order`, `creation_mode`, `requires_acknowledgement`, `is_implemented`), `document_status_label`-override, `Acknowledgement` (каналы portal/manual), `services/attachments.py`, `services/exceptions.py`, реестр `DETAILS_SERIALIZERS`, схему «один `APIView` на переход + словарь диспетчеризации по коду типа», `CreateXxxView`+`CreateXxxSerializer`. Переписать: `ControlDocument` привязать к `AuditCase` (не к строке перечня); **ввести `DocumentVersion`** (номер версии, статус, `is_active`, `supersedes`), т.к. фронт ЭВГА версионирует документы и `UniqueConstraint(list_entry, document_type)` не подходит для `repeatableKinds`; `DocumentStatus` заменить на статусы ЭВГА (11 значений `DocStatus`) + добавить маршрут согласования (`ApprovalRoute`/участники/задачи) как отдельные модели; `*Details` — по типам ЭВГА (irpi, program, plan, assignment, report, violations, conclusion, prescription, response, quality1-3, working papers…) |
| **cases** | **rewrite** (паттерн сохранить) | `ControlCase` завязан на `SemiannualListEntry` и статус выводится из документов ПК — не переносится. Сохранить идеи: `status` как `@property` через `services/case_status.py::compute_status`, метод-кэш `case.document(code)`, реестр `CaseRegistryViewSet` с `search`/`status` фильтрами, композитный `CaseWorkspaceView` (`{"case","documents","ersop_packages",...}` → для ЭВГА `{"case","object","bases","group","documents","history","appeal"…}`) |
| **checklists** | **drop** (частично adapt) | Проверочный лист ПК в ЭВГА отсутствует. Переиспользовать только приёмы: generic-вложения на строку/пункт (`_attach(model_instance)`), `assert_*_editable` перед каждой правкой, `draft_saved_at/completed_at`, `select_for_update` на пункт, «дробление нарушения на пункты» (`CaseChecklistViolation`) — как прообраз реестра нарушений (`violations` документ ЭВГА) |
| **execution** | **adapt** | `PrescriptionItem` (пункт предписания с `risk_degree`, `recommendation`, `due_date`, вычисляемые `status`, `effective_due_date`), `ExecutionSubmission/Item` (поступления от объекта/аудитора, `source`), `ExecutionDecision` (RELEASE/EXTEND с согласованием), сервисы `register_submission`, `decide_item`, `_mark_prescription_executed_if_complete` — близко к `ExecutionClaimedStatus (not_submitted|partial|completed)` / `ExecutionConfirmedStatus (in_review|completed|cancelled|not_remediable)` фронта; переименовать статусы/решения под ЭВГА и добавить связь с версией документа-ответа (`responseConfirmsSourceVersion`) |
| **ersop** | **adapt** (шаблон интеграции) | Модели `ErsopPackage/Item/Exchange` и цепочка `build → submit → register` + `stub_exchange.py` — образец для любой внешней регистрации ЭВГА (ЕРСОП/КПСиСУ, реестр КВГА, «На подтверждении реестра»). `PACKAGE_2_APPROVAL_STEPS` (пошаговое согласование счётчиком) — упрощённый прообраз `ApprovalRoute`; для ЭВГА лучше сделать нормальную модель участников маршрута |
| **cabinet** | **adapt** | Кабинет представителя объекта: `IsSubjectRepresentative`, `_assert_subject_owns`, `CabinetDocumentViewSet` (документы с `requires_acknowledgement` и `sent_at`), `CabinetAcknowledgeView` (portal-канал), `CabinetRegisterSubmissionView`, download-view'ы с контекстом `{"cabinet": True}` — те же сценарии у роли `object` в ЭВГА (ознакомление, ответы на запросы информации, ответ об исполнении, возражения/обжалование) |
| **reporting** | **drop** | Импорт выгрузки ДФО и формы отчётности — только ПК. Переиспользуемый приём: `import_extract` — валидация структуры до записи (`_validate_structure → DfoExtractValidationError(errors)`), статусы `RECEIVED/PARSED/ERROR`, upsert через `bulk_create(update_conflicts=True)`, `raw_meta JSONField` — если в ЭВГА будет загрузка внешних массивов (реестр объектов, результаты СУР) |
| **risk** | **drop** | СУР ПК (правила `RiskRule`, `run_risk_check`, `RiskCandidate`) не относится к ЭВГА; у `AuditObject` есть `risk`/`score` — хранить как поля объекта/основания, без расчёта. Приём `trigger_*` с идемпотентностью и `select_for_update` на входной объект — полезен |
| **semiannual** | **drop** (паттерн версий — adapt) | Полугодовой перечень — процесс ПК. Из него берём: модель «версия» (`SemiannualListVersion` с цепочкой `NOT_FORMED→DRAFT→APPROVED→FORMED`, `submitted/approved/formed_at/by`, указатель `current_version`), правило «корректировка однократна» и `entries_editable()` — как образец для `DocumentVersion`/планов аудита ЭВГА; `_VersionTransitionView._transition()` — компактный шаблон transition-view |

Итого костяк ЭВГА-бэкенда: `core` + `accounts` + `catalogs` + `subjects` (адаптированные) + новые `audits` (дело, основания, рабочая группа, стадии), `documents` (документы с версиями и маршрутами), `execution`, `cabinet`, `integrations` (по образцу `ersop`), при необходимости `appeals`, `requests` (запросы информации), `quality`.

---

## 11. Шероховатости эталона, которые не надо копировать

1. `semiannual/api/views.py::SemiannualListEntryViewSet.perform_update` вызывает `DepartmentAssignment.objects.update_or_create(..., defaults={"region_id": ..., "subjects_count": ...})`, хотя поле `subjects_count` удалено миграцией `0003_drop_subjects_count.py` (заменено аннотацией `with_subjects_counts()`); в ветке create это даст `TypeError`. Тест `test_form_version1_api.py` также обращается к `DepartmentAssignment.objects.get(...).subjects_count` без аннотации. Коммит `ca6b289 refactor(semiannual): compute department subject counts instead of storing` оставил хвост.
2. В репозиторий закоммичен `backend/saq-cookies.txt` с реальной cookie сессии (артефакт curl) — в ЭВГА добавить в `.gitignore`.
3. Дублирование по приложениям: `_READ_LEVELS`, `user_display_name()`, константы `*_TYPE_CODE`, три почти одинаковых `*AttachmentSerializer`, четыре одинаковых download-view. Для ЭВГА вынести в `core`/`accounts` один раз.
4. `_assert_department_in_scope` живёт в `documents/api/views.py` и импортируется как приватный helper из 6 других приложений — место ему в `accounts/querysets.py`.
5. Фильтр по вычисляемому статусу (`CaseRegistryFilter.filter_status`) грузит все строки в Python; для реестра ЭВГА статус дела лучше хранить/денормализовать или считать SQL-аннотацией.
6. Смешанные языки сообщений: бизнес-ошибки по-русски, но `assert_department_writable`, `LoginView`, `RegisterSerializer`, `SubjectDetailSerializer.bin` — по-английски. Выбрать один язык (русский, как в ТЗ).
7. `AuditEvent` не пишется (см. §3.6); `SPECTACULAR_SETTINGS` содержит повтор ключа `COMPONENT_SPLIT_REQUEST`; в `core/views.py::server_error` строка `"Internal Server Error ."`.
8. Нет ограничений на размер/MIME загружаемых файлов на бэкенде; нет rate-limit; CSRF для API не проверяется (см. §5.1).
9. Основной документооборот (documents/cases/checklists/execution/ersop/cabinet) не покрыт тестами.

---

## 12. Чек-лист: как завести новое приложение ЭВГА «в стиле prof»

1. `apps/<name>/` с `__init__.py`, `apps.py` (`name="apps.<name>"`, `label`, русский `verbose_name`), `models.py`, `admin.py`, `api/{__init__,views,serializers,urls,filters}.py`, `services/__init__.py` + по модулю на агрегат, `management/commands/seed_<name>.py` (если есть справочники), `tests/__init__.py`, `migrations/`.
2. Добавить в `INSTALLED_APPS` (в порядке зависимостей) и `path("api/<name>/", include("apps.<name>.api.urls"))` в `config/urls.py`.
3. Модели: наследовать `core.TimeStampedModel`; статусы — `TextChoices` UPPER_CASE + русский label; FK на акторов `SET_NULL, related_name="+"`; на справочники `PROTECT`; `UniqueConstraint(name="<app>_<model>_natural_key")`; `__str__` через ` · `; `Meta.ordering`.
4. Сервисы: функции `create_/approve_/sign_/send_/…(obj, *, actor=None, **fields)`; первые строки — проверки типа и статуса с `raise <Domain>TransitionError("русский текст, сейчас: {status}")`; `@transaction.atomic` при нескольких записях; `select_for_update` при гонках; `save(update_fields=[..., "updated_at"])`; `IntegrityError → доменная ошибка`; после перехода — `AuditEvent` (дополнение к эталону).
5. Нумерация — `define_sequence` в seed + `issue_number(key=..., target=obj, context={...})`.
6. Вложения — `attach_<owner>_file(obj, *, kind, uploaded_file, uploaded_by)` + `<owner>_attachments(obj)`; download через `FileResponse` со своими проверками прав; ссылки через `reverse(<url-name>)`.
7. API: read — `GenericViewSet` + mixins с `select_related/prefetch_related`, `filterset_class`, `search_fields`, `ordering_fields`, `required_domain`, `required_levels` (`@property` по `self.action`), `get_permissions → [IsAuthenticated(), HasDomainLevel()]`, `ScopedQuerySetMixin` + `scope_department_field`; действия — `APIView` на каждый переход: `get_object_or_404 → _assert_department_in_scope → RequestSerializer → try сервис except TransitionError → ValidationError({"detail"}) → Response(ReadSerializer(obj).data[, 201])`; `@extend_schema(request=, responses=, description=)` на каждый метод.
8. Сериализаторы: `XxxSerializer` (read, `read_only_fields = fields`, `*_name`, `status_label`), `CreateXxxSerializer`/`SaveXxxSerializer` (request, `serializers.Serializer`, докстринг «Request body of…»), `XxxUpdateSerializer` (PATCH, минимальный `fields`).
9. Admin: `list_display/list_filter/search_fields/list_select_related`, inline'ы для детей, `readonly_fields` для системных полей.
10. Тесты: `apps/<name>/tests/test_<тема>.py`, `pytestmark = pytest.mark.django_db`, хелперы `_user_with_<domain>_role(scope, level, department)`, `APIClient().force_authenticate`, кейсы: happy path, неверный статус → 400 с `detail`, чужой department → 403/404, 401 без cookie, идемпотентность, конкурентность для номеров.
11. Seed: константы данных → `update_or_create` под `@transaction.atomic` → `self.style.SUCCESS(f"...: {n}")`; добавить команду в `docker/entrypoint.sh` и README.
12. Ruff 120 символов, `select E,F,I,UP,B,DJ`; аннотации типов в сигнатурах; докстринги по-русски и по делу.
