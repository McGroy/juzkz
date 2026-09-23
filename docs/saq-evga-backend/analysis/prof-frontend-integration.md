# Интеграция фронта prof-control с бэкендом и отличия от фронта ЭВГА

Область отчёта: как эталонный фронт `saq-prof-control-demo/frontend` работает с Django/DRF-бэкендом, как устроен текущий фронт ЭВГА `saq-evga-test` (без бэкенда, IndexedDB), и как перевести ЭВГА на серверный API «в стиле prof».

Все пути ниже относительны к `(рабочая папка анализа)/src/`:

- `prof/saq-prof-control-demo` — эталон (git HEAD `7e9834b feat(launcher): localize and reorder modules`);
- `evga/saq-evga-test` — фронт ЭВГА (git HEAD `25b32f8 Merge BPMN main-stage workflow ... (#7)`, ветки `main`, `diar`, `codex/*`);
- `n8n_old` — старая реализация (n8n + Camunda), в этом отчёте затрагивается только как источник ролей/таблиц.

Замечание по ЭВГА: `docs/architecture.md` фронта ЭВГА прямо говорит, что он писался «по примеру» prof-фронта на коммите `5bbd21d` — **более раннем снимке, в котором ещё не было API, авторизации и БД** («У команды в данном `main` нет API, серверной авторизации и базы данных; демонстрационное состояние находится в React»). Текущий prof (`7e9834b`) уже полностью серверный. Поэтому структура модулей у ЭВГА и prof похожа, а слой данных — принципиально разный.

---

## 0. Краткие выводы

1. В prof весь обмен с сервером сосредоточен в одном файле `src/api/client.ts` (555 строк): единая функция `request<T>()` поверх `fetch` с `credentials: "include"`, объект `api` с пространствами имён (`auth`, `subjects`, `reporting`, `risk`, `semiannual`, `cases`, `documents`, `checklists`, `execution`, `cabinet`, `ersop`, `dashboard`). CSRF-токен не используется: бэкенд аутентифицирует по собственной httpOnly-cookie `saq_session` через `SessionCookieAuthentication` (DRF `BaseAuthentication`, без `enforce_csrf`).
2. Ошибки бэкенда приходят в едином конверте `{type,title,status,detail,code,<field>:[...]}` (`apps/core/exceptions.py`), клиент превращает их в `ApiError` и одновременно рассылает `window`-событие `saq:api-error`, которое `App.tsx` показывает как тост.
3. Типы разделены на два слоя: `src/api/types.ts` (snake_case, зеркало DRF-сериализаторов, `Paginated<T>`) и `src/types.ts` (camelCase, русские подписи, доменные типы UI). Между ними — адаптеры `src/api/profControlAdapter.ts`, `src/api/legacyAdapter.ts`, `src/modules/prof/profControlModuleHelpers.ts`.
4. Авторизация: `App.tsx` при старте вызывает `api.auth.maybeMe()` (`GET /api/auth/me`, 401 → `null`), показывает `LoginPage` (email+пароль → `POST /api/auth/local/login`), затем оборачивает модуль в `AuthProvider value={{user, logout}}`. Роли — `user.roles[].code`, по ним в `ProfControlModule` вычисляются флаги `canApproveDocumentAction`, `canSignDocumentAction`, `canDecideExecution`, `canRecordDocumentAcknowledgement`; `user.is_subject_representative` принудительно ведёт в кабинет субъекта.
5. Мутации: контейнер `ProfControlModule.tsx` (1054 строки) держит состояние по ключу дела, вызывает action-эндпоинты (`/documents/{id}/approve/`, `/sign/`, `/send/`, `/acknowledge/`, `/ersop/packages/.../submit/` …) и после каждой мутации делает **полную перезагрузку дела** (`reloadCase` → `api.cases.detail` + `api.cases.workspace`). Оптимистичных обновлений нет; локальный «прогресс документа» (`documentStatusRoutes.ts`) — только визуальный слой поверх серверных статусов.
6. Пагинация — DRF `{count,next,previous,results}` с `page`/`page_size` (max 200); prof обходит все страницы циклами (`loadEntries`, `loadCaseRegistry`, `collectPages`) и фильтрует на клиенте — это известная слабость, для ЭВГА её повторять не нужно.
7. Файлы — `FormData` в те же action-эндпоинты (`attachments/`, `acknowledge/`, `submissions/`, `decide/`), скачивание по `api.*.attachmentUrl(path)`; в проде хранилище MinIO.
8. i18n — Paraglide JS (`project.inlang`, `messages/ru.json` 267 ключей + `kk.json`), `m.key()`; плюс хак `LegacyLocalization.tsx` (MutationObserver переводит захардкоженные русские строки на казахский по шаблонам из `ru.json`).
9. Маршрутизация — `react-router-dom` v7 `BrowserRouter`, чистые хелперы `modules/prof/routing.ts`, хук `useProfRouting`; nginx `try_files … /index.html`.
10. ЭВГА: один массив `AuditCase[]` в памяти (`useAuditCases`), любое изменение → `repository.save(cases)` **целиком** в IndexedDB (`saq-evga-test`/`state`/`cases`); все бизнес-правила — чистые функции (`workflow.ts` 840 строк, `documentStateMachine.ts` 831, `mainWorkflow.ts` 560, `preparationWorkflow.ts` 406 …), которые возвращают новый объект дела или бросают `Error(текст)`. Роли — переключатель из `data/demoData.ts` (`accounts[]`, ~25 учёток, 10 значений `Role`), сессия — флаг в `sessionStorage`. ЕРСОП, доставка объекту, уведомления и подписи имитируются полями внутри `DocumentVersion` (`registration`, `delivery`, `signatures`, `approvalRoutes`) и `AuditCase.notifications`.
11. План: перенести на ЭВГА «скелет» prof (`api/client.ts`, `api/types.ts`, `auth/AuthContext.tsx`, `App.tsx` с проверкой сессии, `vite.config.ts` с proxy, `.env.example`, деплой nginx+docker), а контракт `AuditCaseRepository` заменить на гранулярный шлюз (`EvgaGateway`) с двумя реализациями — `apiGateway` и `localGateway` (обёртка над сегодняшними чистыми функциями + IndexedDB). Мигрировать по «страйглеру»: сессия/роли → справочники и реестры → дела → документы/действия → задания/уведомления → исполнение/КК/апелляции → удалить demo-seed и IndexedDB.
12. Обязательно унифицировать: слой API + auth, react-router (вместо hash), деплой same-origin (cookie `SameSite=Lax` не переживёт Vercel + чужой домен API), разделение `api/types.ts` vs `types.ts`, серверные статусы/номера/UUID. Можно оставить: plain CSS вместо Tailwind (evga уже скопировал `saq-theme.css` из prof), PNG-иконки, prettier, node-тесты, `ErrorBoundary`, `shared/workflow` и `shared/execution` как контракты. Paraglide (ru/kk) — рекомендуется добавить, но можно поэтапно.

---

## 1. Стек и структура двух фронтов

| Параметр | prof `frontend/` | evga `saq-evga-test/` |
|---|---|---|
| React / TS / Vite | `react ^19.1.1`, `typescript ^5.9.3`, `vite ^7.1.7` | `react 19.1.1`, `typescript 5.9.3`, `vite 7.1.7` (версии зафиксированы без `^`) |
| Роутер | `react-router-dom ^7.18.2` (`BrowserRouter`) | нет; hash-навигация (`location.hash`), `utils/navigation.ts` |
| Стили | `tailwindcss ^4.3.3` + `@tailwindcss/vite`; `src/tailwind.css` 5604 строки (Tailwind как слой поверх «наследуемых» семантических классов `.page`, `.panel`, `.data-table`) | plain CSS: `styles.css` (1758), `saq-theme.css` (1088, «shared visual rules from the prof-control reference»), `audit-layout.css`, `execution-progress.css`, `document-print.css`, CSS-файлы у компонентов |
| Иконки | `lucide-react ^1.33.0` (лаунчер, AppShell) + inline SVG в `AppShell.RailIcon` | PNG в `src/assets/*.png` через `import.meta.glob` (`components/ui.tsx: Icon`) + inline SVG в `Sidebar.NavigationIcon` |
| Шрифт | `@fontsource/inter ^5.2.8` | `@fontsource/inter 5.2.8` (+ `cyrillic-ext`) |
| i18n | `@inlang/paraglide-js ^2.24.1`, `project.inlang/settings.json` (`baseLocale: ru`, `locales: [ru, kk]`), `messages/{ru,kk,en}.json` | нет, все строки по-русски в JSX |
| Прочее | `jszip` (экспорт Excel полугодового списка), `vite-plugin-singlefile` (`build:offline`) | `pdfmake 0.2.20` (PDF на клиенте), `prettier`, `linkedom` + `esbuild` (UI-тесты) |
| Скрипты | `dev`, `i18n:compile`, `build` (= `i18n:compile && tsc -b && vite build`), `build:offline`, `typecheck` | `dev`, `build` (`tsc -b && vite build`), `typecheck`, `test` (`node --experimental-strip-types --test tests/*.test.ts`), `format`, `check`, `test:ui` |
| Env | `.env.example`: `VITE_API_BASE_URL=/api`, `VITE_DEV_API_TARGET=http://127.0.0.1:8000` | нет `.env`; `src/config.ts`: `MAIN_MENU_URL = "https://smartaudit.kz/"`, `DEMO_USER` |
| tsconfig | `strict`, `allowJs: true`, exclude `src/data/appDatabase.ts` | `strict`, `noUnusedLocals`, `noUnusedParameters`, `allowImportingTsExtensions` (импорты с `.ts`) |
| Тесты | нет | 26 файлов `tests/*.test.ts(x)` на `node:test` (чистые функции правил, навигация, shared-модули) |
| Деплой | nginx на хосте + `docker-compose.yml` (postgres, minio, backend/gunicorn); см. `deploy/README.md` | Vercel (`vercel.json`: `rewrites` всё → `/index.html`, `X-Robots-Tag: noindex`) |

Размер: prof `src/` ≈ 20 850 строк (из них 9 226 — сгенерированный `data/reportingFields.generated.ts`); evga `src/` ≈ 30 868 строк (крупнейшие: `ReferencePrintForm.tsx` 1976, `demoScenario.ts` 1340, `forms/documentForms.ts` 1094, `ViolationRegistryForm.tsx` 1065).

---

## 2. Паттерн интеграции prof-frontend с бэкендом

### 2.1. Конфигурация и proxy

`frontend/vite.config.ts`:

```ts
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [react(), tailwindcss(), paraglideVitePlugin({ project: "./project.inlang", outdir: "./src/paraglide", emitTsDeclarations: true, strategy: ["localStorage", "preferredLanguage", "baseLocale"] })],
    server: { proxy: { "/api": { target: env.VITE_DEV_API_TARGET || "http://127.0.0.1:8000", changeOrigin: true } } },
    build: { outDir: "dist", emptyOutDir: true },
  };
});
```

- В dev фронт и API живут на одном origin (`127.0.0.1:5173`), `/api` проксируется на Django → cookie-сессия работает без CORS-настроек в браузере.
- В проде nginx отдаёт `dist/` из `/var/www/saq` и проксирует `/api/` и `/admin/` на `127.0.0.1:8000` (`deploy/README.md`, раздел 4). Опять same-origin.
- `API_BASE_URL` в клиенте: `import.meta.env.VITE_API_BASE_URL?.trim() || "/api"` с обрезкой хвостового `/`.
- Отдельная сборка `vite.singlefile.config.ts` (`build:offline`, `dist-offline`, всё инлайном) — для демонстрации без сервера; в ЭВГА аналог был удалён (`docs/architecture.md`: «Убраны команда и зависимость автономной HTML-сборки»).

### 2.2. `src/api/client.ts` — единый HTTP-клиент

Ключевые элементы (цитаты по файлу):

| Элемент | Что делает |
|---|---|
| `class ApiError extends Error { status; details }` | единый тип ошибки; `status = 0` при сетевой ошибке |
| `API_ERROR_EVENT = "saq:api-error"`, `notifyError(message)` | `window.dispatchEvent(new CustomEvent(...))` — глобальная шина ошибок, слушает `App.tsx` (тост 6 с). `notifyError` также используется UI напрямую (например, `FilePicker`: «Пустой файл нельзя прикрепить.») |
| `errorMessage(payload, fallback)` | из конверта берёт `detail` (строка), иначе первое значение объекта (строка или первый элемент массива) — то есть покрывает и `{"detail": "..."}`, и DRF field-errors `{"email": ["..."]}` |
| `request<T>(path, init)` | `fetch(\`${API_BASE_URL}${path}\`, {...init, headers, credentials: "include"})`; если `body` не `FormData` и нет `Content-Type` → `application/json`; всегда `Accept: application/json`; `204` → `undefined`; парсинг по `content-type` (json/text); не-ok → `ApiError` + `notifyError` |
| `apiRequest<T>` | публичная обёртка над `request` (для нестандартных вызовов) |
| `optionalRequest<T>` | то же, но `401 → null` (используется только `auth.maybeMe`) |
| `query(params)` | `URLSearchParams`; массив → повторяющиеся параметры (`risk_category=HIGH&risk_category=MEDIUM`), пустые/`null`/`undefined` пропускаются |
| `countEndpoint(path)` | `GET ...?page_size=1` и вернуть `count` (для дашборда) |
| `export const api = {...}` | пространства имён с типизированными методами (см. Приложение A) |

Соглашения, которые стоит перенять:

- путь = как в Django (`/documents/${id}/approve/` с завершающим слэшем у ViewSet-ов и `path(... /)`; у `/auth/*` — без слэша, как объявлено в `apps/accounts/api/urls.py`);
- все методы возвращают уже распарсенный DRF-объект, типизированный интерфейсами из `api/types.ts`;
- многочастные запросы собираются прямо в методе (`acknowledge`, `registerSubmission`, `decide`, `attach*`): если есть `File` → `FormData`, иначе JSON;
- `attachmentUrl: (path) => \`${API_BASE_URL}${path.replace(/^\/api/, "")}\`` — сервер отдаёт относительные ссылки на скачивание (`/api/documents/<id>/attachments/<aid>/`), клиент нормализует префикс.

CSRF: в клиенте нет ни `X-CSRFToken`, ни чтения cookie `csrftoken`. Это согласовано с бэкендом: `REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES = ["apps.accounts.authentication.SessionCookieAuthentication"]`, класс наследует `BaseAuthentication` и не вызывает `enforce_csrf` (в отличие от стандартного `SessionAuthentication`); DRF `APIView` обёрнут в `csrf_exempt`. Django `CsrfViewMiddleware` в `MIDDLEWARE` остаётся, но касается только `/admin/` (у админки отдельная cookie `SESSION_COOKIE_NAME = "saq_admin_session"`).

### 2.3. Серверный контракт, от которого зависит клиент

| Аспект | Реализация в `backend/` | Следствие для фронта |
|---|---|---|
| Сессия | `apps/accounts/services/sessions.py`: cookie `API_SESSION_COOKIE_NAME = "saq_session"`, `httponly=True`, `samesite="Lax"`, `secure=API_SESSION_COOKIE_SECURE` (в проде `true`, для HTTP-стенда `false`), `max_age = API_SESSION_MAX_AGE = 12h`; значение — pk записи `AuthSession` | фронт не хранит токенов; `credentials: "include"` обязателен; API и SPA должны быть same-site |
| Аутентификация | `SessionCookieAuthentication.authenticate`: cookie → `AuthSession` → проверка `is_active`, срока для `LOCAL`, обновление Keycloak-токена (`keycloak.ensure_fresh_access_token`) | 401 без cookie/просроченная сессия → `optionalRequest` вернёт `null`, остальные вызовы → тост |
| Логин | `POST /api/auth/local/login {email,password}` → `MeSerializer` + Set-Cookie; `POST /api/auth/local/register {email,password,full_name,bin}` — для представителей субъекта; `POST /api/auth/local/logout` → 204 + удаление cookie; `GET /api/auth/me` | `LoginPage` различает `401` («Неверная почта или пароль», `m.login_error()`) и прочие ошибки (текст из `ApiError`) |
| Keycloak | `GET /api/auth/keycloak/login?redirect_to=`, `/callback`, `/logout` (PKCE, `OidcAuthRequest`); ошибки → редирект `APP_BASE_URL?auth_error=...` | фронт prof **не использует** (нет ни кнопки, ни обработки `auth_error`); задел для SSO есть |
| Пользователь | `MeSerializer`: `id, username, full_name, email, auth_provider, position, department, is_subject_representative, subject{id,bin,name}, roles[{code,name,scope,department}]` | тип `User` в `api/types.ts` 1:1 |
| Роли | `seed_roles`: `list-officer, list-officer-inspector, list-supervisor, list-supervisor-controller, ca-specialist, ca-approver, ca-signer, ca-group-head, territorial-specialist, territorial-group-head, territorial-approver, territorial-signer, observer, sysadmin`; на сервере права — `HasDomainLevel(required_domain, required_levels)` и `IsSubjectRepresentative` | фронт **дублирует** проверку только для показа/скрытия кнопок; сервер — источник истины |
| Конверт ошибок | `apps/core/exceptions.py:exception_handler` → `{"type":"about:blank","title":..., "status":..., "detail":..., "code":..., <field>: [...]}`; `JsonNotFoundMiddleware` → JSON-404 для `/api/*` | `errorMessage()` ожидает `detail` или field-errors |
| Пагинация | `PageNumberPaginationWithPageSize`: `page_size_query_param = "page_size"`, `max_page_size = 200`, `PAGE_SIZE = 25` | `Paginated<T>`; клиент передаёт `page`, `page_size`, циклы по 200 |
| Фильтры | `DjangoFilterBackend`, `SearchFilter`, `OrderingFilter` | query-параметры `search`, `ordering`, доменные фильтры (`status`, `subject_type`, `region`, `list_entry`, `document`, `run`, `risk_category` …) |
| CORS | `CORS_ALLOWED_ORIGINS` из env, `CORS_ALLOW_CREDENTIALS = True` | нужно только при разных origin (dev через proxy этого избегает) |
| Файлы | dev `FileSystemStorage`; prod `STORAGES` → S3/MinIO (`MINIO_*` в `docker-compose.yml`) | скачивание через отдельные `Download*View` эндпоинты, а не прямые ссылки на бакет |
| Swagger | `/api/docs/`, `/api/schema/` (drf-spectacular) | документация контракта для фронта |

### 2.4. Типы: `src/api/types.ts` vs `src/types.ts`

- `src/api/types.ts` (466 строк) — «зеркало» сериализаторов: `UUID = string`, `Paginated<T>`, `User`, `RoleAssignment`, `SubjectListItem/SubjectDetail`, `DfoExtract`, `RiskRun/RiskCandidate/RiskRule`, `SemiannualList/Version/Entry`, `DepartmentAssignment`, `ControlCase`, `CaseRegistryItem`, `Attachment`, `Acknowledgement`, `ControlDocument` (с `details: Record<string, unknown> | null`, `acknowledgements[]`, `attachments[]`), `ErsopPackage`, `BackendChecklist*`, `PrescriptionItem`, `ExecutionSubmission/Decision`, `CaseWorkspaceResponse`, `DashboardStats`. Все поля snake_case; необязательные «человеческие» поля помечены `?` (`region_name?`, `responsible_name?`, `status_label?`) — так фронт терпит бэкенд, который их ещё не отдаёт (`API_INTEGRATION.md`).
- `src/types.ts` (144 строки) — доменные типы UI: `View`, `SubjectType` (`"АО" | "ПАО" | …`), `Candidate`, `ControlCase` (camelCase, `statusLabel`, `startDate` уже отформатирован), `DocumentAcknowledgementRecord` (`mode: "Нарочное ознакомление" | "Электронное ознакомление"`), `ExecutionSubmission` и т.п.
- Нарочно допускается дублирование имён (`ControlCase` есть в обоих файлах) — импорт различается путём.

### 2.5. Адаптеры DRF → доменные типы

| Файл | Функции | Назначение |
|---|---|---|
| `src/api/profControlAdapter.ts` (285) | `unwrapPage`, `formatDate` (Intl ru-RU), `periodTitle`, `versionStatusLabel`, `toControlCase(item, list?, version?)`, `documentsToProgress(documents)`, `documentsToAcknowledgements`, `documentsToFieldValues` | `toControlCase` собирает строку реестра из `CaseRegistryItem` (+ `list`/`version` для заголовков), подставляя «Не указан/Не назначено/Не назначен» и форматируя даты; `documentsToProgress` переводит серверный `status` в индекс шага UI по таблице `documentProgressByStatus` (`notice: {DRAFT:1, APPROVED:2, SENT:3, ACKNOWLEDGED:4}`, `appointment-act: {... SIGNED:4, READY:4, IN_ERSOP:5, REGISTERED:6, SENT:7, ACKNOWLEDGED:8}` …); `documentsToFieldValues` раскладывает `document.details` в значения полей формы по типу документа (`notice`, `appointment-act`, `card-1-p`, `result-act`, `prescription`) |
| `src/api/legacyAdapter.ts` (153) | `loadLatestRiskPackage(runId?)`, `collectPages(load)`, `toCandidate(risk, subject, index)` | «пакет СУР»: параллельно грузит extracts+runs, затем все страницы `subjects` и `risk/candidates` (по 200), склеивает по БИН, строит `Candidate` с объяснением риска; бросает осмысленные `Error` («На backend нет завершённого расчёта риска…») |
| `src/modules/prof/profControlModuleHelpers.ts` (128) | `loadEntries(versionId)`, `loadCaseRegistry()`, `errorText(error, fallback)`, `todayIso`, `toIsoDate`, `requireIsoDate`, `inspectedPeriod`, `prescriptionItemExecutionKey`, `assertExecutionActionsAvailable`, `isUuid`, `executionSubmissionsFromBackend(items, responsible)` | пагинация циклом; нормализация дат `dd.mm.yyyy` ↔ ISO; группировка ответов по исполнению из `PrescriptionItem[].submissions` |
| `src/utils/statusLabel.ts` | `statusLabel(code, fallback)`, `ersopPositionLabel`, `ersopDirectionLabel` | словарь кодов → русские подписи (`AWAITING_NOTICE`, `NOTICE_SENT`, `APPOINTMENT`, `IN_PROGRESS`, `AWAITING_EXECUTION`, `EXECUTED`, `DRAFT`, `APPROVED`, `SIGNED`, `SENT`, `ACKNOWLEDGED`, `READY`, `IN_ERSOP`, `REGISTERED`, `ACCEPTED`, `SUBMITTED`, `GENERATED`, `IN_PACKAGE_1/2`, `AWAITING_RESPONSE`, `UNDER_CONTROL`, `RECEIVED`, `RELEASE`, `EXTEND`, `DONE`, `NOT_FORMED`, `FORMED`); при наличии `status_label` от сервера используется он |
| `src/data/documentStatusRoutes.ts` | `documentStatusRoutes` (по документу: `statuses[]`, `actions{}`, `acknowledgementReadyAt`), `getDocumentStatus/Action`, `getNextDocumentProgress`, `isDocumentReadyForAcknowledgement`, `getDocumentAcknowledgedProgress`, `isDocumentAvailableToSubject` | статичное описание UI-маршрута документа («Не создан → Проект → Согласовано → Направлен → Субъект ознакомлен»); подписи кнопок («Создать», «Согласовать», «Подписать», «Направить») |
| `src/data/workflowDefinitions.ts` | `listSteps[]`, `caseSteps[]` | названия шагов мастера списка и вкладок дела |

Вывод: серверные коды статусов — источник истины, а `documentStatusRoutes` + `documentProgressByStatus` — презентационная проекция. В ЭВГА аналогом будут `DocStatus` (русские строки) и `documentPresentation.ts`.

### 2.6. Auth-контекст и вход

`src/auth/AuthContext.tsx` (17 строк):

```ts
type AuthContextValue = { user: User; logout: () => Promise<void> };
export const AuthProvider = AuthContext.Provider;
export function useAuth(): AuthContextValue { /* throw, если вне провайдера */ }
```

`src/App.tsx` (123 строки):

1. Модульный singleton `sessionCheckPromise` — `checkSession()` вызывает `api.auth.maybeMe()` один раз (устойчиво к `StrictMode` двойному эффекту); `setAuthenticatedSession(user)` переопределяет его после логина/логаута.
2. `useEffect` → `setUser`, `setCheckingSession(false)`; пока идёт проверка — экран `m.session_check()` («Проверка авторизации…»).
3. `useEffect` подписывается на `API_ERROR_EVENT` и держит массив тостов `{id, message}` (авто-удаление через 6 с, `aria-live="assertive"`).
4. `logout`: `api.auth.logout()` в `try/finally` → `setUser(null)`.
5. Без пользователя — `<LoginPage onAuthenticated={...} />`; с пользователем — `<BrowserRouter>` → `AuthenticatedApp` → `<AuthProvider value={{ user, logout }}>` → `<Routes>`: `index` → `SAQModulesPage` (лаунчер модулей), `*` → `ProfControlModule` (lazy), если путь «узнаваем» (`/lists`, `/cases`, `/subject` и их подпути), иначе `NotFoundPage`.

`src/pages/LoginPage.tsx` (98 строк): контролируемая форма email/password, `api.auth.login(email.trim(), password)` → `onAuthenticated(user)`; ошибка: `requestError instanceof ApiError && status !== 401 ? message : m.login_error()`; `LanguageSwitcher` в углу; стили — Tailwind-классы.

Использование ролей в `ProfControlModule.tsx`:

```ts
const canRecordDocumentAcknowledgement = user.roles.some(r => ["list-officer-inspector","list-supervisor-controller","ca-specialist","ca-group-head","territorial-specialist","territorial-group-head"].includes(r.code));
const canDecideExecution = user.roles.some(r => ["ca-group-head","territorial-group-head"].includes(r.code));
const canApproveDocumentAction = user.roles.some(r => ["ca-approver","territorial-approver"].includes(r.code));
const canSignDocumentAction = user.roles.some(r => ["ca-signer","territorial-signer"].includes(r.code));
```

и `useEffect`: `if (user.is_subject_representative && view !== "subject") { setViewState("subject"); navigate("/subject"); }` — представитель субъекта видит только кабинет и работает через `api.cabinet.*`.

`SAQModulesPage`/`AppShell` берут `user.full_name || user.email || user.username` и `user.position || user.roles[0]?.name` для шапки.

### 2.7. Действия (approve/sign/send/…) и обновление состояния

Контейнерный паттерн: `ProfControlModule` держит ~50 `useState`, страницы (`CasesList`, `SemiannualListRegistry`, `SemiannualListWorkspace`, `CaseWorkspace`, `SubjectPortalPage`) — почти «тупые», получают данные и колбэки пропсами. Исключение — `CaseWorkspace.tsx` (1233 строки), который **сам** вызывает `api.checklists.*` для мелкозернистой работы с проверочным листом (12 вызовов: `saveItem`, `createViolation`, `updateViolation`, `deleteViolation`, `attach*File`, `saveGeneralReference`, `complete`).

Загрузка:

- `loadRegistry()`: `api.semiannual.lists` + `api.risk.runs` параллельно, затем **на каждый список** `api.semiannual.versions(list.id)` и `loadEntries(version.id)` (N+1 — антипаттерн, не копировать).
- `loadCases(rows)`: `loadCaseRegistry()` (все страницы `/cases/`) → `toControlCase`.
- `loadDocumentsForCase(item)`: если есть `backendId` → `api.cases.workspace(id)` (агрегат `{case, list_entry, documents, ersop_packages, checklist}`), иначе `api.documents.list({listEntry})`; далее из `documents` строятся `caseDocumentProgress`, `caseDocumentFieldValues`, `documentAcknowledgements`, `caseChecklists`; если есть документ `prescription` — `api.execution.items({document})` → `casePrescriptionItems`, `executionSubmissions`. Всё кладётся в словари по `caseKey(item) = item.id || item.registryId`.
- Deep-link: `useEffect` по `routeListId`/`routeCaseId`/`routeSubjectId` находит сущность в уже загруженных `registryRows`/`controlCases` и вызывает `openList`/`loadDocumentsForCase` — то есть маршрут гидрирует состояние после первичной загрузки реестров.

Мутации (все через `try { … await api…; await reloadCase(...) } catch { setXxxError(errorText(e, fallback)) }`):

| Операция | Последовательность вызовов | Обновление состояния |
|---|---|---|
| Сформировать список (`approveList`) | `formVersion1` → `versions` → `loadEntries` → `updateEntryRegion` (×N) → `transitionVersionToFormed`: `updateDepartmentAssignmentResponsible` (×N) → `submitVersion` → `approveVersion` → `formVersion` | `refreshBackendData()` (полная перезагрузка реестров) |
| Версия №2 (`startAmendment`/`approveAmendment`) | `createVersion2` → `loadEntries` → `hydrateList`; при утверждении `excludeEntry` (×N) → `transitionVersionToFormed` | `refreshBackendData()` |
| Документ (`runDocumentAction(documentType, values, files, progress)`) | клиентский «диспетчер» по `document.status`: `notice`: нет → `createNotice`; `DRAFT` → `patchDetails` + `approve`; `APPROVED` → `send`; `appointment-act`: create/patch → `attach` (explanatory_note, investor_basis) → `approve`/`sign`; `result-act`: … → `approve`/`sign`/`send`; `prescription`: `execution.updateItem` (×N) → `approve`/`sign`/`send` | `reloadCase(registryId)` → `api.cases.detail` + `loadDocumentsForCase`; страница `CaseWorkspace` дополнительно двигает локальный `documentProgress` (`getNextDocumentProgress`) и вызывает `onCaseStatusChange` |
| ЕРСОП пакет №1 (`mutateErsopPackage`) | `submit`: `buildPackage1(caseId)` → `submitPackage1(pkg.id)`; `register`: `registerPackage1(current.id)` | `setCaseErsopPackages` + `reloadCase` |
| ЕРСОП пакет №2 (`mutateErsopClosurePackage`) | `buildPackage2` → цикл `approvePackage2Step` пока `package_2_approved_steps < 5` → `submitPackage1` (тот же `/submit/`) | `reloadCase` |
| Ответ по исполнению (`registerExecutionSubmission`) | `assertExecutionActionsAvailable(status)` → `execution.items` → по каждому пункту `execution.registerSubmission` (FormData при файле) → `execution.items` повторно | `setCasePrescriptionItems`, `setExecutionSubmissions`, `reloadCase` |
| Решение по пункту (`decideExecutionItem`) | `execution.decide(itemId, {kind: RELEASE|EXTEND, ...})` → `execution.items` | как выше |
| Ознакомление (`saveDocumentAcknowledgement`) | `documents.acknowledge(id, {channel, acknowledged_on, proof_ref, attachment})` | точечное обновление: заменить документ в `caseDocuments[key]`, пересчитать `documentsToAcknowledgements`/`documentsToProgress` (единственный случай без полной перезагрузки) |
| Кабинет субъекта | `cabinet.acknowledgeDocument`, `cabinet.registerSubmission` | `loadCabinetData()` |

Важные свойства паттерна:

- **Сервер — источник статусов**, клиент лишь выбирает следующий endpoint по текущему `status`; если статус неожиданный — `throw new Error("Действие для уведомления в статусе «…» не предусмотрено.")`.
- **Нет оптимистичных апдейтов и кэша** — после мутации всегда рефетч. Просто и надёжно, но дорого (несколько запросов на действие).
- Ошибки двух уровней: (а) глобальный тост из `client.ts` для любого не-2xx, (б) локальная панель ошибки в разделе (`caseDataError`, `registryError`, `casesError`, `cabinetError`, `ersopPackageError`, `listFormError`, `dfoError`).
- Флаг «идёт операция» (`listForming`, `ersopPackageLoading`, `casesLoading`, `registryLoading`, `cabinetLoading`) блокирует повторные клики.
- `refreshKey` + `<AppShell key={refreshKey}>` — «перезапустить» модуль сбросом состояния.

### 2.8. Пагинация и фильтрация

- Контракт: `Paginated<T> = {count, next, previous, results}`; параметры `page`, `page_size` (клиент везде явно задаёт `page_size` 25/50/100/200).
- Практика prof: реестры грузятся **целиком** циклами по 200 (`loadEntries`, `loadCaseRegistry`, `collectPages`) и фильтруются в памяти (`CasesList`: поиск по строке, категория, регион, статус; `SemiannualListRegistry`: год/полугодие/статус). Серверные фильтры `api.cases.list({search,status,subject_type,region,business_category})` объявлены, но контейнер их не использует.
- Для ЭВГА рекомендуется серверная пагинация с самого начала (у `CasesList` ЭВГА уже есть компонент `Pagination({count,page,size,setPage,setSize})` — его достаточно переключить на `count` от сервера и `page/page_size` в запрос).

### 2.9. Загрузка и скачивание файлов

- Загрузка: `FormData` (`body.append("file", file)`, `"kind"`, `"attachment"` …) в те же action-эндпоинты; `request()` не ставит `Content-Type` для `FormData` (браузер сам добавляет boundary).
- Эндпоинты: `POST /documents/{id}/attachments/` (`kind: explanatory_note|investor_basis`), `POST /documents/{id}/acknowledge/` (с `attachment`), `POST /checklists/items/{id}/attachments/`, `POST /checklists/violations/{id}/attachments/`, `DELETE …/attachments/{aid}/`, `POST /execution/items/{id}/submissions/`, `POST /execution/items/{id}/decide/`, `POST /reporting/extracts/import/`, кабинет — `POST /cabinet/execution-items/{id}/submissions/`.
- Ответ содержит `Attachment {id, kind, original_name, size, mime, file, uploaded_by, uploaded_at}`, где `file` — относительный путь скачивания; UI делает `<a href={api.cabinet.attachmentUrl(attachment.file)} target="_blank">`.
- `FilePicker.tsx`: отбрасывает пустые файлы, пересобирает `FileList` через `DataTransfer`, сбрасывает `input.value`.
- Ограничения: nginx `client_max_body_size 25m`.

### 2.10. Локализация (Paraglide)

- `project.inlang/settings.json`: `baseLocale: "ru"`, `locales: ["ru","kk"]`, `pathPattern: ./messages/{locale}.json`.
- `paraglideVitePlugin` генерирует `src/paraglide/{messages.js,runtime.js}`; `npm run i18n:compile` — то же для `tsc`. Стратегия выбора локали: `localStorage` → `preferredLanguage` → `baseLocale`.
- Использование: `import { m } from "../paraglide/messages.js"; m.login_button()`; `getLocale()/setLocale()` в `LanguageSwitcher.tsx` (кнопка `RU`/`ҚАЗ`), `main.tsx` ставит `document.documentElement.lang` и `document.title = m.app_title()`.
- Покрытие неполное: `m.*` встречается лишь в `SubjectPortalPage` (22), `AppShell` (20), `SaqSidebar` (9), `LoginPage` (6), `App`, `LanguageSwitcher`, `main`; остальные страницы — русский текст в JSX. Поэтому есть `src/i18n/LegacyLocalization.tsx`: при `kk` строит регэкспы из `messages/ru.json` и через `MutationObserver` переписывает текстовые узлы, `aria-label`, `title`, `placeholder` в DOM. Это компенсирующий хак; в ЭВГА его копировать не стоит — лучше сразу писать `m.*`.
- Ключи `messages/ru.json` уже содержат описания всех модулей SAQ, включая `saq_module_evga_title` («Электронный внутренний государственный аудит»).

### 2.11. Маршрутизация (react-router)

- `App.tsx`: `BrowserRouter`, `Routes` с `index` (лаунчер) и `*` (модуль).
- `modules/prof/routing.ts` (чистые функции, без React): `viewFromPath(pathname): View`, `pathForView(view)`, `routeIdentifier(pathname, prefix)`, `caseStageSlug/caseStageFromPath` (`overview|preparation|control|execution|history`), `caseStageForDocument(documentId)`, `caseDocumentFromPath`, `caseStagePath(caseId, stage)` → `/cases/:id/stages/:slug`, `caseDocumentPath(caseId, documentId)` → `/cases/:id/documents/:docId`.
- `modules/prof/useProfRouting.ts`: `useLocation`/`useNavigate`; `view` синхронизируется с `location.pathname`; возвращает `routeListId`, `routeCaseId`, `routeSubjectId`.
- `CaseWorkspace` сам читает `location.pathname` для активного шага/документа и вызывает `navigate(caseStagePath(...))` при переключении вкладок — URL является источником состояния вкладки.
- Маршруты: `/` (лаунчер), `/lists`, `/lists/:id`, `/lists/new`, `/cases`, `/cases/:id`, `/cases/:id/stages/:slug`, `/cases/:id/documents/:docId`, `/subject`, `/subject/:caseId`.
- Лаунчер `config/saqModules.ts` ссылается на ЭВГА как на внешний модуль: `url: "https://saq-evga-test.vercel.app/#/cases"` (hash-маршрут!) — при переезде ЭВГА на `BrowserRouter`/новый хост эту ссылку надо изменить.

### 2.12. Оболочка и UI-примитивы

- `components/AppShell.tsx`: сайдбар (`SaqSidebar`, состояние свёрнутости в `localStorage` `saq.sidebar.expanded.v1`), топбар с заголовком по `view` (`getTitles()` из `m.*`), `LanguageSwitcher`, блок пользователя, кнопки «Главное меню» (`navigate("/")`, иконка `LayoutGrid` из lucide) и `m.logout()`.
- `components/ui.tsx`: `Badge({tone})`, `PageHeading({eyebrow,title,subtitle,action})`, `StatCard`, `EmptyStage`; классы `.page`, `.panel`, `.stats-grid`, `.filter-bar`, `.data-table`, `.clickable-row`, `.row-action`.
- `components/ModuleCard.tsx` (`Link` для `internal`, `<a target=_blank>` для `external`).
- CSS-переменные в `tailwind.css` `:root`: `--bg #eef4f8`, `--surface #fff`, `--text #2a2c31`, `--muted #697386`, `--line #d2d7e3`, `--blue #006196`, `--blue-dark #003b5c`, `--green #52c41a`, `--amber #faad14`, `--red #ff4d4f` — те же значения объявлены в `styles.css` ЭВГА (`--blue`, `--dark-blue`, `--line`, `--muted` …), т.е. визуальная база уже общая.

### 2.13. Деплой prof

- `docker-compose.yml`: `postgres:16-alpine`, `minio` + `minio-init` (создание бакета `saq-attachments`), `backend` (Dockerfile `python:3.13-slim`, gunicorn `config.wsgi`, `entrypoint.sh` = `migrate` + `collectstatic` + `seed_*`), порт `8000`. Фронт **в compose не входит**.
- nginx на Ubuntu (`deploy/README.md`): `root /var/www/saq` (результат `npm run build --prefix frontend`), `location /api/ { proxy_pass http://127.0.0.1:8000; … X-Forwarded-Proto }`, `location /admin/`, `location /static/` (alias на `deploy/staticfiles`), `location / { try_files $uri $uri/ /index.html; }`.
- `deploy/.env.example`: `SAQ_PUBLIC_URL`, `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `API_SESSION_COOKIE_SECURE=false` (для HTTP-стенда), `DJANGO_SECURE_SSL_REDIRECT=false`, `POSTGRES_*`, `DATABASE_URL`, `MINIO_*`, `KEYCLOAK_*` (пусто → только локальный вход).
- Обновление: `git pull` → `docker compose up --build -d` → `npm ci && npm run build` → `rsync dist/ /var/www/saq/`.

---

## 3. Текущая модель данных и состояния фронта ЭВГА

### 3.1. Корневая композиция

`src/main.tsx` → `<ErrorBoundary><App/></ErrorBoundary>`; `App.tsx` (35 строк):

```ts
const { path, navigate } = useEvgaNavigation();      // hash
const { signedOut, login, logout } = useDemoSession(); // sessionStorage-флаг
if (signedOut || path === "/login") return <LoginPage onLogin={() => { navigate("/cases"); login(); }} />;
return <Suspense><EvgaModule path={path} navigate={navigate} onLogout={...} /></Suspense>;
```

`pages/LoginPage.tsx` (20 строк) — экран «Вы вышли из модуля» с кнопкой «Войти в ЭВГА» и ссылкой `MAIN_MENU_URL`; полей ввода нет. `auth/useDemoSession.ts` хранит только `sessionStorage["saq.evga.demo.signed-out"]`.

### 3.2. Хранилище: один массив в памяти → IndexedDB целиком

`services/auditCaseRepository.ts`:

```ts
export interface AuditCaseRepository { load(): Promise<AuditCase[] | undefined>; save(cases: AuditCase[]): Promise<void>; }
```

`services/indexedDbCaseRepository.ts`: БД `saq-evga-test` v1, store `state`, ключ `cases`; `save` делает `structuredClone` и сериализует записи через цепочку `pendingSave` (защита от гонки записей).

`modules/evga/useAuditCases.ts` (80 строк):

1. `repository.load()` → если пусто, `structuredClone(seedCases)`.
2. **При каждой загрузке** подмешиваются демо-дела: `workflowSampleCases()`, `preparedCases()` (если их id ещё нет), затем `addPlannedSampleCases`, `addRegistrySampleCases`, `enrichSampleQualityForms`, `migrateLegacyApprovalRoutes`, и пересчитывается `quality: [qualityPassed(item,0), …]`. То есть seed и миграции живут в рантайме фронта (`demoScenario.ts` 1340 строк).
3. `useEffect([cases, loaded])` → `repository.save(cases)` — **весь массив при любом изменении**; ошибка → `saveError` («Изменения не сохранены…»).
4. `updateCase(next)`: заменить по `id` или добавить в начало.

Следствия: нет частичных обновлений, нет серверной проверки прав, нет конкурентного доступа (кроме клиентских «stale»-проверок в `saveDocument`), вложения (`Upload.data` — base64 data URL, `utils/files.ts: readUploads`) раздувают IndexedDB, роль — свойство браузера.

### 3.3. Где происходит мутация

`modules/evga/EvgaModule.tsx` (331 строка) — контейнер, аналог `ProfControlModule`:

- состояние: `cases` (из `useAuditCases(indexedDbCaseRepository)`), `account` (из `accounts[]`, id в `localStorage["saq.evga.account.v1"]`), `toast`, `caseForm`, `preselected`, `leave` (подтверждение ухода при редактировании), `pendingAccount`;
- разбор пути: `parts = pathname.split("/")`; `audit = cases.find(id === parts[1])` для `cases|quality`; `doc = audit.documents.find(id === parts[3])`; `editing = parts[4] === "edit"`; версии `parts[4] === "versions" && parts[5]`; query `?section=&item=&view=`;
- `saveCase(next)`: проверка `account.role === "auditor"` и `canAuthorCase` → `updateCase(next)`; иначе тост;
- всем страницам передаётся `onChange={updateCase}` / `onSave={(next) => updateCase(saveDocument(audit, next, account))}`; для документов `key` = `doc.id-account.id-version-item` (принудительный remount при смене роли/версии).

Страницы и компоненты вызывают **чистые функции**, возвращающие новый объект:

| Модуль (строк) | Экспорт | Что делает |
|---|---|---|
| `workflow.ts` (840) | `repeatableKinds`, `isQuality`, `qualitySources`, `isActive`, `registered(audit)`, `creationBlock`, `qualityPassed`, `saveDocument(audit, doc, actor)`, `deleteDocument`, `performRegistration(doc, actor, "send"|"accept"|"return", comment, number)`, `deliverable(kind)`, `deliverDocument(doc, actor, "send"|"acknowledge"|"respond"|"sign"|"object"|"refuse", …)`, `completionBlock`, `renewQuality` | правила создания/удаления, зависимости документов (`dependencies`: `program: ["irpi"]`, `account: ["instruction","quality1"]`, `prescription: ["conclusion"]` …), stale-проверки при сохранении, имитация ЕРСОП и доставки объекту |
| `documentStateMachine.ts` (831) | `activeVersion`, `canEdit`, `canSubmit`, `canDecideDocument`, `requiresQuality`, `directActivation`, `activateDocument`, `sendDocumentToQuality`, `submitDocument`, `approveDocument`, `returnDocument`, `rejectDocument`, `createNextVersion`, `createReturnedRevision`, `createRejectedRevision`, `reassignReturnedDocument`, `createResponseRevision`, `recallDocument`, `currentApprovalRoute`, `documentVersionId` | переходы `DocStatus` («Проект» → «Направлен на согласование КК» → «На согласовании» → «На утверждении» → «Согласован»/«Активный», «Возвращен на доработку», «Отклонен», «На подтверждении КВГА», «На подтверждении реестра», «На подписании рабочей группой»), версии, маршруты согласования |
| `mainWorkflow.ts` (560) | `isMainDocument`, `mainCurrentBlock`, `requestReportGroupSignatures`, `signReportGroup`, `sendRegistryToConfirmer`, `decideRegistryConfirmation`, `requestMainQuality`, `requestMainApproval`, `reviseMainDocument`, `signMainQuality`, `submitMainQualityToHead`, `reviseMainQuality` … | основной этап (отчёт, реестр нарушений, доказательства, КК2) |
| `preparationWorkflow.ts` (406) | `isPreparationDocument`, `sendInstructionToKvga`, `decideInstructionKvga`, `sendPreparationForApproval`, `signAssignmentGroup`, `approveAssignmentGroup`, `requestPreparationQuality`, `revisePreparationDocument` … | подготовительный этап (ИРПИ, программа, план, задание, поручение, КВГА, КК1) |
| `documentFactory.ts` (115) | `creationAccessBlock`, `documentSequence`, `createDocument(audit, kind, actor)` | номер `${audit.number}/${NN}`, `ownerRole`, `sourceVersions`, версия v1 «Проект» |
| `caseAccess.ts`, `caseRules.ts` | `canAuthorCase`, `assignCoauthor`; `validateCase`, `nextCaseNumber` (`30101-YY-NNNNN`, старт 52970) | доступ автора/соавтора; нумерация дел на клиенте |
| `qualityAssignment.ts`, `qualityConclusion.ts`, `qualityControlRules.ts` | назначение эксперта КК, заключения | |
| `informationRequests.ts`, `thirdParties.ts`, `appeals.ts`, `amendments.ts`, `executionItems.ts`, `executionDecision.ts`, `executionProgress.ts`, `approvalTasks.ts` | требования сведений, третьи лица, возражения, доп. поручения, исполнение, задания | |
| `shared/workflow/approvalRoute.ts` (539) | `createApprovalRoute`, `decideApprovalRoute`, `supersedeApprovalRoute`, `getApprovalTasks`, `getPendingApprovalTasks`, `ApprovalWorkflowError{code}` | общий (для evga/sva/prof) маршрут согласования, `execution: "local-demo"` |
| `shared/execution/execution.ts` (492) | `ExecutionItem`, `createExecutionItemId`, `getDeadlineStatus`, `filterExecutionItems`, `summarizeExecutionItems` | общая read-проекция пунктов исполнения |

Пример типичной мутации (`pages/CaseWorkspace.tsx: openDocument`):

```ts
const d = fillPreparedDocument(audit, createDocument(audit, kind, account));
onChange({ ...saveDocument(audit, d, account), history: [...audit.history, log(account.name, `Создан документ: …`)] });
```

и `DocumentActions.tsx`: `onAction(() => performRegistration(doc, account, "accept", "", registrationNumber))`. Ошибки правил — `throw Error("…")` → `notify(message)` (тост в `EvgaModule`).

Плюс этого подхода: правила изолированы, покрыты тестами (`tests/*.test.ts`, 173 теста по `docs/bpmn-implementation-2026-09-21.md`) и легко переносимы на сервер как спецификация.

### 3.4. Модель данных (`src/types.ts`, 315 строк)

- `AuditCase`: `id`, `number`, `object: AuditObject{bin,ru,kz,director,opf,abp,address,region,risk,score}`, `auditType`, `checkType`, `checkKind`, `electronic`, `dsp`, `jointObject?`, `purposeRu/Kz`, `group: Person[]`, `bases: Basis[]` (с `attachments: Upload[]`), `author`, `createdAt`, `status: "Открыто"|"Закрыто"`, `attachments`, `documents: AuditDocument[]`, `quality: [bool,bool,bool]`, `history: HistoryEntry[]`, опционально `coauthors`, `notifications[]`, `qualityAssignments`, `appeal`, `thirdParties`, `amendments`, `parentCaseId` (встречные проверки), `executionState`, `schedule`, `calendar`, `sampleScenario`, `documentSequence`.
- `AuditDocument`: `id`, `kind` (43 вида из `data/documentMatrix.ts: docKinds` — `irpi, program, plan, assignment, instruction, quality1, account, vap, additional, request, obstruction, report, violations, evidence, quality2, weekly, measurement, objections, objection-result, conclusion, prescription, quality3, notification, forward-*/reply-*, claim-*, response, completion, counter-*`), `stage: 0|1|2`, `number`, `createdAt`, `author`, `versions: DocumentVersion[]`.
- `DocumentVersion`: `version`, `status: DocStatus`, `values: Record<string, unknown>` (поля формы по схемам `forms/documentForms.ts`), `attachments: Upload[]`, `group`, `reviewers`, `reviewerIndex`, `approver`, `signatures[]`, `approvalRoutes?: ApprovalRoute[]`, `qualityConclusion?`, `qualityDecision?`, `ownerRole?`, `ownerId?`, `sourceVersions?`, `registration?: {status: "Отправлена"|"Зарегистрирована"|"Возвращена", number?, date?, comment?}`, `delivery?: {sentAt, acknowledgedAt?, response?, attachments?, decision?: "Подписан"|"Подписан с возражениями"|"Отказ от подписания", …}`, `informationRequest?`, `main?`, `mainQuality?`, `preparation?`, `createdAt`, `history[]`.
- `Account = {id, name, role: Role, label, area?: "appeal"}`, `Role` = `auditor | reviewer | approver | quality | kvga | reestr-confirmer | invited-specialist | object | appeal-head | appeal-expert`.
- `Upload = {id, name, type, size, data(base64), description?}`.

### 3.5. Переключение демо-ролей

- `data/demoData.ts: accounts[]` — `auditor` (= `DEMO_USER`), `reviewer-1/2`, `approver`, `quality`, `quality-2`, `kvga`, все `people[]` как аудиторы/`invited-specialist`, `coauthor`, `object`, `quality-head`, `appeal-head`, `appeal-expert(-2)`, `commission-1/2`, `commission-chair`, `reestr-confirmer` (~25 записей).
- `components/AppShell.tsx`: кнопка пользователя открывает `account-menu`: «Уведомления (Непрочитанных: N)», «Переключиться на объект» / «Вернуться в контролирующий орган» (`portalAccount`, запоминает `lastAuthorityId`), список «Сменить роль». `EvgaModule.onAccountChange` при `editing` показывает `Confirm` («Сменить роль без сохранения изменений в документе?»).
- Ролевые ограничения — в чистых функциях (`actor.role !== "auditor"` → `throw`), в страницах (`disabled={account.role !== "auditor"}` в `CasesList`, `ObjectsRegistry`), в `reviewParticipants.ts` (`routeReviewer`, `routeApprover` по `id`/`area`), в `ApprovalTasks.tsx` (`kvga`, `reestr-confirmer`, `object`).

### 3.6. Имитации внешних систем и сервисов

| Что имитируется | Где | Как |
|---|---|---|
| Регистрация в ЕРСОП (учётная карточка `account`/`counter-account`, `notification`, `additional`) | `workflow.ts: performRegistration`, UI `components/DocumentActions.tsx` панель «Учёт регистрации в ЕРСОП» (кнопки «Подготовить к регистрации», «Учесть регистрацию» (модал с номером), «Учесть возврат») | аудитор сам проставляет `version.registration = {status: "Отправлена"}` → `{status: "Зарегистрирована", number: N || \`УЧ-${doc.number}\`, date}` или `{status: "Возвращена", comment}` (+ `v.status = "Возвращен на доработку"`); `registered(audit)` гейтит отправку поручения объекту и создание встречных проверок |
| Доставка документов объекту и его ответ | `workflow.ts: deliverDocument`, `DocumentActions.tsx` панель «Ознакомление и ответ объекта аудита» | `version.delivery = {sentAt}` → объект (та же учётка-браузер, роль `object`) делает `acknowledge`/`respond`/`sign`/`object`/`refuse` |
| Требования сведений | `informationRequests.ts: transitionInformationRequest` | раунды `InformationRequestRound` внутри версии |
| Подписи рабочей группы, КВГА, подтверждение реестра | `preparationWorkflow.ts`, `mainWorkflow.ts` | массивы `groupSignatures`, `preparation.kvga`, `main.confirmation` внутри версии |
| ЭЦП | нет | `signatures[]` с `{person, at, role}` без криптографии |
| Уведомления | `AuditCase.notifications[] {id, at, documentId, text, recipients[], readBy[]}`; создаются только в `caseAccess.ts: assignCoauthor`; страница `components/Notifications.tsx` показывает и помечает `readBy` через `onChange` | счётчик непрочитанных в `EvgaModule` → `AppShell notificationCount` |
| Задания (входящие) | `pages/ApprovalTasks.tsx`: вычисляются из статусов версий (`На подтверждении КВГА`, `На подтверждении реестра`, `На подписании рабочей группой`, решение объекта) + `ApprovalInbox` из `shared/workflow` по `caseApprovalRoutes(cases)` | производные данные, не хранятся |
| Исполнение | `pages/ExecutionRegistryPage.tsx` + `shared/execution/ExecutionRegistry`; `executionItemsForCases(cases)` проецирует пункты из значений форм `prescription`/`conclusion`/`response`; политика сроков в `localStorage["saq.evga.execution-policy.v1"]` | |
| Справочники (объекты, сотрудники, органы) | `data/demoData.ts: catalogue`, `objectRegistry`, `plannedDemoObjects`, `people`, `basisOptions`, `initiatorOptions`; `pages/ObjectsRegistry.tsx` фильтрует `catalogue` | статичные массивы |
| PDF | `modules/evga/pdfExport.ts` + `pdfmake`, шрифты Liberation в `assets/fonts` | на клиенте |
| Нумерация | `caseRules.ts: nextCaseNumber` (`30101-26-NNNNN`), `documentFactory.ts: documentSequence` | на клиенте |
| Идентификаторы | `utils/id.ts: uid = () => crypto.randomUUID()` | на клиенте |

### 3.7. Навигация ЭВГА (hash)

`utils/navigation.ts`: `go(path) => location.hash = path`, `route() => location.hash.slice(1) || "/cases"`, `documentViewPath(path, view)`, `documentVersionPath(path, version)` (регэксп `^/(cases|quality)/([^/]+)/documents/([^/]+)(?:/edit|/versions/\d+)?$`). `useEvgaNavigation` слушает `hashchange` и делает `scrollTo(0,0)`. Ссылки в JSX — `href="#/tasks?case=…"`.

| Маршрут | Экран |
|---|---|
| `#/cases` | `CasesList` (без `parentCaseId` и без `demo-show-*`) |
| `#/cases/:id/:tab` (`general|group|regulatory|documents|working|counter|appeal|third-parties|amendments|attachments|history`) | `CaseWorkspace` |
| `#/cases/:id/documents/:docId[/edit | /versions/:n]?view=form|print|sources&section=&item=` | `DocumentWorkspace` / `QualityDocumentWorkspace` |
| `#/quality`, `#/quality/:id`, `#/quality/:id/documents/:docId…` | `QualityRegistry`, КК-документы |
| `#/tasks?case=` | `ApprovalTasks` |
| `#/execution[/:caseId]` | `ExecutionRegistryPage` |
| `#/notifications` | `Notifications` |
| `#/objects` | `ObjectsRegistry` |
| `#/login` | `LoginPage` |

`vercel.json` уже переписывает все пути на `index.html`, так что переход на `BrowserRouter` технически совместим и с Vercel.

### 3.8. Что уже «в стиле prof» у ЭВГА

Совпадает по замыслу (см. таблицу в `docs/architecture.md` ЭВГА): `lazy/Suspense` модуля, контейнер `EvgaModule` ≈ `ProfControlModule`, `pages/` + `components/` + `data/` + `types.ts`, `AppShell`/`Sidebar` (тот же ключ `saq.sidebar.expanded.v1`, те же классы `.app-shell .rail .topbar .content`), `ErrorBoundary`, `Confirm`-модалы. Отсутствует: слой API, auth, роутер, i18n, серверные справочники.

---

## 4. План перевода фронта ЭВГА на серверный API «по образцу prof»

### 4.1. Целевая архитектура

```
main.tsx ─ ErrorBoundary ─ App.tsx
   ├─ checkSession(): api.auth.maybeMe()  → LoginPage (email/password | кнопка Keycloak)
   └─ BrowserRouter ─ AuthProvider{user, logout}
        ├─ "/"            → SAQModulesPage (лаунчер, как в prof) или redirect /evga/cases
        └─ "/evga/*"      → EvgaModule (lazy)
              ├─ useEvgaRouting()  (react-router; хелперы из utils/navigation.ts сохранить как чистые)
              ├─ gateway = useEvgaGateway()   // apiGateway | localGateway (VITE_EVGA_DATA_MODE)
              ├─ hooks: useCaseList(query), useCase(id), useCaseWorkspace(id), useTasks(), useNotifications()
              └─ pages/* и modules/evga/components/* — получают AuditCase/AuditDocument той же формы (через evgaAdapter)
src/api/client.ts   ← копия prof (request/ApiError/notifyError/query) + пространство `api.evga.*`, `api.auth.*`, `api.catalogs.*`
src/api/types.ts    ← snake_case-типы DRF ЭВГА (EvgaCase, EvgaDocument, EvgaDocumentVersion, Attachment, ApprovalRouteDto, NotificationDto, ExecutionItemDto, Paginated<T>, User)
src/api/evgaAdapter.ts ← toAuditCase(dto), toAuditDocument(dto), toUpload(attachment), toAccount(user), payload-билдеры
```

### 4.2. Файлы: добавить / заменить / оставить

| Действие | Файл | Основание |
|---|---|---|
| Добавить (скопировать из prof) | `src/api/client.ts` | оставить `ApiError`, `notifyError`, `API_ERROR_EVENT`, `request`, `optionalRequest`, `query`; заменить содержимое `api` на `auth`, `evga.cases`, `evga.documents`, `evga.versions`, `evga.attachments`, `evga.tasks`, `evga.notifications`, `evga.execution`, `evga.quality`, `evga.appeals`, `catalogs` |
| Добавить | `src/api/types.ts` | по образцу prof: `Paginated<T>`, `User`, `RoleAssignment`, DTO ЭВГА |
| Добавить | `src/api/evgaAdapter.ts` | аналог `profControlAdapter.ts`: DTO → `AuditCase`/`AuditDocument`/`DocumentVersion` (форма из `src/types.ts` сохраняется, чтобы не трогать 30 тыс. строк форм); `Upload` ← `Attachment` (`data` → `href`) |
| Добавить | `src/auth/AuthContext.tsx` | копия prof без изменений |
| Добавить | `src/auth/roles.ts` | `accountFromUser(user: User): Account` — маппинг `user.roles[].code` → `Role` ЭВГА (см. 4.7) |
| Заменить | `src/pages/LoginPage.tsx` | форма email/password как в prof (`api.auth.login`), при наличии `KEYCLOAK_ISSUER` — кнопка «Войти через Keycloak» (`window.location = \`${API_BASE_URL}/auth/keycloak/login?redirect_to=/evga/cases\``) и обработка `?auth_error=` |
| Заменить | `src/App.tsx` | как в prof: `checkSession`, тосты `API_ERROR_EVENT`, `BrowserRouter`, `AuthProvider` |
| Заменить | `src/modules/evga/useEvgaNavigation.ts` | `useEvgaRouting` на `useLocation/useNavigate`; `utils/navigation.ts` оставить как чистые хелперы (тесты `tests/navigation.test.ts` продолжат работать), только `go/route` заменить |
| Заменить | `src/modules/evga/useAuditCases.ts` | серверные хуки; удалить подмешивание `demoScenario` |
| Заменить контракт | `src/services/auditCaseRepository.ts` → `src/services/evgaGateway.ts` | гранулярный интерфейс (4.3) |
| Оставить как offline-реализацию (временно) | `src/services/indexedDbCaseRepository.ts` + чистые функции правил | `localGateway` = сегодняшнее поведение; включается `VITE_EVGA_DATA_MODE=local` |
| Удалить (после этапа 6) | `src/auth/useDemoSession.ts`, `src/config.ts: DEMO_USER`, переключатель ролей в `AppShell`, `data/demoData.ts: accounts/people/catalogue`, `modules/evga/demoScenario.ts` из рантайма | сервер — источник пользователей/справочников; демо-сценарии → `manage.py seed_evga_demo` |
| Изменить | `vite.config.ts` | добавить `loadEnv` + `server.proxy["/api"]`, при желании `paraglideVitePlugin` |
| Добавить | `.env.example` | `VITE_API_BASE_URL=/api`, `VITE_DEV_API_TARGET=http://127.0.0.1:8000`, `VITE_EVGA_DATA_MODE=api` |
| Изменить | `package.json` | `react-router-dom`, (опц.) `@inlang/paraglide-js`, `lucide-react`; скрипты `build`/`typecheck` с `i18n:compile`, если Paraglide |
| Изменить | `README.md`, `docs/architecture.md` | зафиксировать новый контракт |
| Заменить | `vercel.json` → `deploy/` | nginx-конфиг по образцу prof (см. 4.5) |

### 4.3. `AuditCaseRepository`: заменить, а не адаптировать

Вариант «`ApiCaseRepository` с тем же `load()/save(cases)`» отвергается: `save` целиком означает, что клиент — источник истины (роли, статусы, номера, история проверяются в браузере), сервер не может ни авторизовать действие, ни разрешить конфликт двух пользователей, ни принять файл потоком. Это ровно то, чего prof избегает: у него **каждое действие — отдельный endpoint**, а состояние перечитывается.

Предлагаемый контракт (гранулярный, зеркалит будущие DRF-эндпоинты; имена под `api.evga.*`):

```ts
export interface EvgaGateway {
  // дела
  listCases(params: { page?: number; pageSize?: number; search?: string; auditType?: string; checkType?: string; electronic?: boolean; status?: string; author?: string }): Promise<Paginated<AuditCaseSummary>>;
  getCase(id: string): Promise<AuditCase>;                 // агрегат: дело + документы + версии + маршруты (аналог /cases/{id}/workspace/)
  createCase(payload: CaseInput): Promise<AuditCase>;      // номер выдаёт сервер
  updateCase(id: string, payload: Partial<CaseInput>): Promise<AuditCase>;
  closeCase(id: string): Promise<AuditCase>;
  assignCoauthor(id: string, userId: string): Promise<AuditCase>;
  // документы и версии
  createDocument(caseId: string, kind: string): Promise<AuditDocument>;
  saveDraft(documentId: string, version: number, values: Record<string, unknown>, expectedUpdatedAt?: string): Promise<AuditDocument>;
  action(documentId: string, version: number, action: DocumentAction, payload?: Record<string, unknown>): Promise<AuditDocument>;
  //   DocumentAction = "submit" | "send-to-quality" | "approve" | "return" | "reject" | "recall" | "activate" | "new-version"
  //                  | "register-send" | "register-accept" | "register-return" | "deliver" | "acknowledge" | "respond" | "sign" | "object" | "refuse"
  //                  | "kvga-decide" | "group-sign" | "registry-confirm" | "assign-quality-expert" | "quality-conclusion" | ...
  uploadAttachment(documentId: string, version: number, file: File, meta?: { description?: string; fieldKey?: string }): Promise<Attachment>;
  deleteAttachment(documentId: string, attachmentId: string): Promise<void>;
  // задания, уведомления, исполнение, справочники
  listTasks(): Promise<ApprovalTask[]>;
  listNotifications(): Promise<NotificationItem[]>; markNotificationRead(id: string): Promise<void>;
  listExecutionItems(params: { caseId?: string }): Promise<ExecutionItem[]>;
  catalogs(): Promise<{ auditObjects: AuditObject[]; people: Person[]; controllingBodies: string[]; auditTypes: string[]; inspectionTypes: string[]; basisOptions: string[]; initiatorOptions: string[] }>;
}
```

`localGateway` реализует это поверх текущих чистых функций и IndexedDB (например, `action("register-accept")` → `performRegistration(doc, actor, "accept", …)` + `saveDocument` + `save(cases)`), `apiGateway` — через `api.evga.*`. Так страницы переводятся на новый контракт один раз, а источник данных переключается флагом. После завершения бэкенда `localGateway`, `indexedDbCaseRepository` и `demoScenario` удаляются.

Серверу при этом достаётся роль владельца правил: чистые функции ЭВГА (`documentStateMachine.ts`, `workflow.ts`, `mainWorkflow.ts`, `preparationWorkflow.ts`) — готовая спецификация для Django-сервисов (аналог `apps/documents/services` в prof), а их тесты `tests/*.test.ts` — готовые сценарии для `pytest`.

### 4.4. Поэтапная миграция (страйглер, без поломки страниц)

| Этап | Что делаем | Что остаётся локальным | Критерий готовности |
|---|---|---|---|
| 0. Каркас | `api/client.ts`, `api/types.ts` (`User`, `Paginated`), `auth/AuthContext.tsx`, новый `App.tsx` + `LoginPage`, `vite.config.ts` proxy, `.env.example`, `react-router` вместо hash (маршруты те же, без `#`), `accountFromUser` | все данные (IndexedDB через `localGateway`) | вход через `/api/auth/local/login`, `useAuth().user` в `AppShell` вместо `account`-дропдауна; deep-link `/evga/cases/:id/documents/:doc` открывается |
| 1. Справочники и реестры (read-only) | `api.catalogs.*` (объекты аудита ← `surfk.audit_objects`, сотрудники ← `surfk.employees`/`evga_users_with_roles`, органы ← `controlling_bodies`, типы ← `audit_types`/`inspection_types`, основания ← `check_initiators`/`control_reasons_types`), `listCases` с серверной пагинацией (`CasesList.Pagination` → `count` от сервера, фильтры → query) | документы, действия | `ObjectsRegistry`, `CaseForm` (`ObjectLookup`, `PeoplePicker`) берут данные с сервера |
| 2. Дела | `createCase/updateCase/closeCase/assignCoauthor`, основания с вложениями (`FormData`), номер дела от сервера (`get_next_doc_sequence` из старой схемы) | документы | `CaseForm.onSave` → `gateway.createCase`; `nextCaseNumber` не используется |
| 3. Документы и действия | `getCase` возвращает агрегат; `createDocument`, `saveDraft`, `action(...)`, `uploadAttachment`; `evgaAdapter.toAuditDocument` сохраняет форму `AuditDocument/DocumentVersion` (включая `registration`, `delivery`, `approvalRoutes`, `history`) — `DocumentWorkspace`, `DocumentActions`, `PreparationActions`, `MainActions`, формы не меняются; `canEdit/canDecideDocument/creationBlock` остаются как UI-подсказки, но сервер повторяет проверки и отвечает 403/409 с `detail` | КК, апелляции, третьи лица, исполнение | все `onAction(() => pureFn(...))` заменены на `gateway.action(...)`; stale-проверка через `expected_version`/`updated_at` (409) вместо `saveDocument`-сравнений |
| 4. Задания и уведомления | `listTasks` (сервер строит из `evga_document_approvals`/маршрутов), `listNotifications`/`markRead`; `ApprovalInbox` получает `routes` от сервера | | `ApprovalTasks`, `Notifications` без вычислений по всем делам в браузере |
| 5. Исполнение, КК, апелляции, третьи лица, требования сведений | соответствующие `action`-ы и списки; `ExecutionRegistry` получает `ExecutionItem[]` от сервера (контракт `shared/execution` уже задуман как read-проекция) | — | |
| 6. Зачистка | удалить `localGateway`, IndexedDB, `useDemoSession`, переключатель ролей (или спрятать за `VITE_DEMO_ROLES=true` только для dev), `demoScenario` → `manage.py seed_evga_demo`; PDF — оставить на клиенте или перенести на сервер | — | `npm run check` зелёный, `tests/` актуализированы |

Правила на каждом этапе: (а) страницы получают тот же `AuditCase` — переход невидим для форм; (б) после любой мутации — рефетч агрегата дела (`getCase`) как в `reloadCase` prof; (в) ошибки — `errorText(e, fallback)` + глобальный тост; (г) в `apiGateway` нельзя импортировать чистые функции правил (иначе логика «размажется» по двум местам).

### 4.5. Конфигурация, окружение, деплой

`vite.config.ts` (целевой):

```ts
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [react() /*, paraglideVitePlugin({...}) */],
    server: { host: "0.0.0.0", allowedHosts: ["terminal.local"], proxy: { "/api": { target: env.VITE_DEV_API_TARGET || "http://127.0.0.1:8000", changeOrigin: true } } },
    build: { outDir: "dist" },
  };
});
```

`.env.example`: `VITE_API_BASE_URL=/api`, `VITE_DEV_API_TARGET=http://127.0.0.1:8000`, `VITE_EVGA_DATA_MODE=api`.

Деплой — как prof (nginx на хосте + `docker compose`), а не Vercel:

- cookie `saq_session` имеет `SameSite=Lax`; при SPA на `*.vercel.app` и API на другом домене браузер не отправит cookie на `fetch` → потребовалось бы `SameSite=None; Secure` + CORS с credentials — это изменение бэкенда и ослабление безопасности. Same-origin через nginx решает вопрос без правок сервера.
- Два варианта размещения: (1) отдельный `root /var/www/saq-evga` и `location /api/ → backend ЭВГА` (или общий Django с `apps/evga`); (2) один SPA-хост SAQ, где `/lists`, `/cases` — prof, `/evga/*` — ЭВГА (единый лаунчер `SAQModulesPage`, `saqModules.ts: {id:"evga", type:"internal", url:"/evga/cases"}`). Второй вариант ближе к «нашему стилю» и снимает проблему ссылки `https://saq-evga-test.vercel.app/#/cases`.
- Если Vercel всё же остаётся на переходный период — `vercel.json` `rewrites: [{ "source": "/api/(.*)", "destination": "https://<api-host>/api/$1" }]` (прокси Vercel сохраняет cookie как same-origin), но `API_SESSION_COOKIE_SECURE=true` обязателен.

### 4.6. Маппинг данных ЭВГА на серверные ресурсы (ориентир)

Старая схема `surfk.*` (по частоте упоминаний в `n8n_old/n8n_export`): `evga_case_documents` (638), `evga_document_statuses` (392), `evga_document_types` (177), `cases` (165), `evga_document_workflow_history` (103), `evga_document_approvals` (83), `controlling_bodies` (75), `audit_objects` (72), `evga_document_mappings` (58), `case_participants` (58), `evga_document_signatures` (57), `audit_types` (48), `case_statuses` (43), `employees` (40), `inspection_types` (36), `evga_document_stages` (35), `get_next_doc_sequence` (30), `case_appeal_expert_assignments`, `case_qc_expert_assignments`, `users`, `evga_users_with_roles`, `evga_roles`, `evga_user_roles`, `case_bases`, `case_base_attachments`, `regions`, `positions`, `departments`, `annual_plans`, `risk_levels`. Keycloak-воркфлоу: `Keycloak_Subsystem_Access`, `Get_Keycloak_Users`, `Keycloak_IB_Admins`.

| Поле фронта (`src/types.ts`) | Серверный ресурс (предложение) |
|---|---|
| `AuditCase{number, object, auditType, checkType, checkKind, electronic, dsp, purposeRu/Kz, status, author, createdAt}` | `cases` (+ `audit_objects`, `audit_types`, `inspection_types`, `case_statuses`) → `GET/POST /api/evga/cases/`, `GET /api/evga/cases/{id}/workspace/` |
| `group: Person[]`, `coauthors` | `case_participants` (+ `employees`) → `POST /api/evga/cases/{id}/participants/` |
| `bases: Basis[]` с `attachments` | `case_bases`, `case_base_attachments` → `POST /api/evga/cases/{id}/bases/` (multipart) |
| `documents[]`, `versions[]`, `values`, `status`, `history` | `evga_case_documents`, `evga_document_types`, `evga_document_stages`, `evga_document_statuses`, `evga_document_workflow_history` → `/api/evga/documents/{id}/versions/{n}/` |
| `approvalRoutes`, `reviewers`, `approver`, `signatures` | `evga_document_approvals`, `evga_document_signatures` → `/action/`-эндпоинты + `GET /api/evga/tasks/` |
| `qualityAssignments`, `appeal.expertId` | `case_qc_expert_assignments`, `case_appeal_expert_assignments` |
| `registration`, `delivery` | новые таблицы/поля документа + интеграционные адаптеры ЕРСОП (в старой системе — n8n-воркфлоу) |
| `Upload.data` | `Attachment{id, original_name, size, mime, file}` в MinIO (как prof) |
| `Account/Role` | `users` + `evga_user_roles`/`evga_roles` (Keycloak realm roles) → `GET /api/auth/me` |

Детализация схем — зона других агентов; здесь важно, что фронт должен получать **уже собранный агрегат дела** и **готовые статусные подписи** (`status_label`), как `CaseWorkspaceResponse` в prof.

### 4.7. Роли и авторизация

- Сервер отдаёт `User.roles[{code,name,scope,department}]`; для ЭВГА нужны коды вида `evga-auditor`, `evga-reviewer`, `evga-approver`, `evga-quality`, `evga-quality-head`, `evga-kvga`, `evga-registry-confirmer`, `evga-invited-specialist`, `evga-object`, `evga-appeal-head`, `evga-appeal-expert`, `evga-commission-member`, `evga-commission-chair` (сопоставить с `surfk.evga_roles` старой системы).
- Адаптер `accountFromUser(user): Account` даёт `{id: user.id, name: user.full_name, role, label: user.position || roles[0].name, area}` — весь существующий код с `account.role` продолжает работать; позже роль-строку можно заменить на набор флагов, как в `ProfControlModule` (`canApproveDocumentAction`…).
- Представитель объекта: у prof это `is_subject_representative` + отдельный API `/api/cabinet/*` и `IsSubjectRepresentative`; для ЭВГА нужен аналогичный кабинет (`objections`, `response`, ознакомление, ответы на требования) вместо переключения роли `object` в том же браузере.
- Серверные проверки — по образцу `HasDomainLevel(required_domain, required_levels)`; клиентские `creationAccessBlock`, `canEdit`, `canDecideDocument` остаются только для отрисовки.

### 4.8. Файлы

- `components/FileAttachments.tsx` сейчас читает файлы в base64 (`readUploads`) и хранит их в `values`/`attachments`. Переход: проп `onUpload?: (files: File[]) => Promise<Upload[]>`; `apiGateway.uploadAttachment` возвращает `Attachment`, адаптер приводит к `Upload{id, name, type, size, data: href}` (для `<a href download>` и печатных форм этого достаточно). Для форм с `files` внутри строк (`IrpiRow.files`, реестр нарушений) — тот же приём: в `values` хранится массив `{id, name, href}`, а не base64.
- Скачивание — через эндпоинты `…/attachments/{id}/` (как prof `Download*View`), не через прямые ссылки на MinIO.
- `pdfExport.ts` можно оставить клиентским (pdfmake) на первое время.

### 4.9. Ошибки, тосты, i18n

- Глобальный тост `API_ERROR_EVENT` из `App.tsx` prof + локальный `toast` `EvgaModule` (уже есть, 6 с) — совместить: `notifyError` для HTTP-ошибок, `notify` для доменных сообщений.
- Конверт ошибок бэкенда ЭВГА должен совпадать с prof (`apps/core/exceptions.py`), тогда `errorMessage()` работает без изменений; для 409 (устаревшая версия документа) — `detail: "Документ изменился. Обновите дело перед сохранением решения"` (текст уже есть в `saveDocument`).
- Paraglide: скопировать `project.inlang`, `messages/ru.json` (ключи модулей SAQ уже там), добавить `messages/kk.json`; новые строки писать через `m.*`; для старых — постепенно. Требование двуязычия (ru/kk) для госсистемы фактически обязательное, а у ЭВГА уже есть `kz`-поля в данных (`purposeKz`, `object.kz`).

### 4.10. Пагинация и фильтры в реестре дел

`pages/CasesList.tsx` сегодня фильтрует `cases` через `matchesFilters(a, filters)` (`caseSearch.ts`: `number, bin, org, author, status, type, checkType, electronic`) и режет `slice((page-1)*size, page*size)`. Перевести на `gateway.listCases({page, pageSize: size, search, auditType, checkType, electronic, status, author})` — компонент `Pagination` и панель фильтров сохраняются; `AdvancedSearch` передаёт те же параметры.

---

## 5. Различия стека/стиля и рекомендации

| Измерение | prof | evga | Рекомендация |
|---|---|---|---|
| Слой данных | `api/client.ts` + адаптеры, сервер — источник истины | `AuditCaseRepository` (IndexedDB), правила на клиенте | **Обязательно унифицировать** (разделы 4.2–4.4) |
| Аутентификация | cookie-сессия, `AuthContext/useAuth`, `LoginPage` с паролем | `useDemoSession` (флаг), переключатель `accounts[]` | **Обязательно**: `AuthContext` prof; переключатель ролей — только dev-режим |
| Роутер | `react-router-dom` v7, `BrowserRouter`, URL = состояние вкладок | hash, ручной разбор `parts[]` | **Обязательно**: react-router (deep-links, nginx `try_files`, единый лаунчер); чистые хелперы `utils/navigation.ts` оставить |
| Деплой | nginx + docker compose, same-origin | Vercel | **Обязательно**: same-origin (cookie `SameSite=Lax`) |
| Типы | `api/types.ts` (snake_case) ↔ `types.ts` (UI) через адаптеры | один `types.ts` | **Обязательно**: ввести `api/types.ts` + `evgaAdapter.ts`; `types.ts` не ломать |
| Статусы/подписи | коды с сервера + `statusLabel`, `status_label` | русские строки `DocStatus` как коды | **Обязательно**: сервер отдаёт код + `status_label`; на клиенте словарь как `statusLabel.ts`; на переходный период допустимо оставить русские строки как коды |
| Идентификаторы/номера | UUID и номера от сервера | `crypto.randomUUID()`, `nextCaseNumber`, `documentSequence` | **Обязательно**: сервер |
| Файлы | `FormData` → MinIO, скачивание через API | base64 в JSON | **Обязательно** |
| Обновление после мутаций | рефетч агрегата (`reloadCase`) | `updateCase(next)` в памяти | **Обязательно**: рефетч; кэш — позже при необходимости |
| Пагинация | серверная (частично используется) | клиентская `Pagination` | **Обязательно** серверная для реестров |
| Ошибки | `ApiError` + `API_ERROR_EVENT` тост + локальные панели | `throw Error` + `notify` тост | Совместить (4.9) |
| i18n | Paraglide ru/kk (+ хак `LegacyLocalization`) | нет | **Рекомендуется**: Paraglide; `LegacyLocalization` не копировать |
| Стили | Tailwind 4 + семантические классы | plain CSS (`saq-theme.css` — копия prof-оболочки) | Можно оставить CSS; Tailwind внедрять только в новых компонентах, если команда хочет; токены цветов уже совпадают |
| Иконки | lucide-react + SVG | PNG (`assets/*.png`) + SVG | Можно оставить; для новых экранов — lucide |
| UI-примитивы | `Badge, PageHeading, StatCard, EmptyStage` | `Button, Field, Info, Panel, Toggle, Segments, Status, Pagination, Icon`, `Modal/Confirm` | Оставить evga-набор (богаче); при объединении SPA — вынести в общий пакет |
| Оболочка | `AppShell` + `SaqSidebar` + `LanguageSwitcher` | `AppShell` + `Sidebar` (тот же ключ localStorage, те же классы) | Оставить; добавить `LanguageSwitcher`, «Главное меню» → `navigate("/")` |
| Контейнер модуля | `ProfControlModule` (состояние + колбэки) | `EvgaModule` (то же) | Оставить; вынести загрузку в хуки, чтобы не повторять 50 `useState` |
| Бизнес-правила | на сервере (`apps/*/services`), клиент — проекция (`documentStatusRoutes`) | чистые функции на клиенте с тестами | Перенести на сервер как спецификацию; клиентские копии — только для подсказок UI |
| Тесты | нет | `node:test` (26 файлов), `test:ui` | Оставить и расширить контрактными тестами адаптера |
| Форматирование | нет | prettier (`printWidth 100`) | Оставить |
| tsconfig | `allowJs`, без `noUnused*` | `noUnusedLocals/Parameters`, `allowImportingTsExtensions` | Оставить более строгий evga-вариант |
| ErrorBoundary | нет | есть | Оставить |
| Даты | `utils/dateFormat.ts` (регэксп, без TZ) + `Intl` в адаптере | `dateText` (`Intl`, `timeZone: "Asia/Almaty"`) | Оставить evga (явный TZ) |
| Демо-данные | `manage.py seed_*` на сервере | `data/demoData.ts`, `demoScenario.ts` в рантайме | **Обязательно** перенести в seed-команды |
| Общие модули | — | `shared/workflow`, `shared/execution` (контракты «для evga/sva/prof») | Оставить контракты; данные — с сервера; `execution: "local-demo"` → `"server"` |
| Лаунчер | `SAQModulesPage` + `saqModules.ts` (ЭВГА = внешняя Vercel-ссылка с `#/cases`) | `MAIN_MENU_URL = https://smartaudit.kz/` | При объединении — `type: "internal", url: "/evga/cases"`; иначе обновить URL |

---

## 6. Риски и открытые вопросы

1. **Один SPA или два?** Prof-лаунчер считает ЭВГА внешним модулем. Объединение в один фронт (общие `client.ts`, `AuthContext`, оболочка, Paraglide) — самый «стильный» вариант, но требует монорепо/общего пакета и согласования CSS (Tailwind vs plain).
2. **Один Django или два?** Cookie `saq_session` и `/api/auth/*` живут в prof-бэкенде. Если ЭВГА получит свой Django, потребуется общий SSO (Keycloak) или общий сервис аккаунтов; если общий — `apps/evga` внутри prof-бэкенда с теми же `SessionCookieAuthentication`, `exception_handler`, `PageNumberPaginationWithPageSize`.
3. **Keycloak vs локальный вход.** Старая ЭВГА работала с Keycloak (`Keycloak_Subsystem_Access`, `evga_users_with_roles`); prof-фронт пока пользуется только локальным логином, хотя бэкенд поддерживает OIDC. Нужно решить, показывать ли кнопку SSO.
4. **Хранение версий документов.** `DocumentVersion.values: Record<string, unknown>` — JSON-блоб по 62+ схемам форм (`forms/documentForms.ts`). Нормализовать на сервере или хранить JSONB как есть (быстрее для миграции фронта)? От этого зависит объём `evgaAdapter`.
5. **Двойная логика.** Пока клиентские правила остаются как подсказки, они могут разойтись с сервером. Нужен регламент: сервер — единственный судья, клиент только прячет кнопки; тесты `tests/*.test.ts` переезжают в `pytest`.
6. **Кабинет объекта аудита.** Сейчас «объект» — роль в том же браузере. По образцу prof нужен отдельный тип пользователя (`is_subject_representative`) и API кабинета; это влияет на `deliverDocument`, `objections`, `response`, требования сведений.
7. **Казахский язык.** Обязателен ли kk-интерфейс на первом релизе? Определяет, тянуть ли Paraglide в этап 0.
8. **Существующие данные в IndexedDB** пользователей стенда (дела, base64-вложения) — импортировать на сервер или считать тестовыми и отбросить?
9. **Нумерация** `30101-YY-NNNNN` (клиент) vs `surfk.get_next_doc_sequence` (старый бэкенд) — какой формат официальный?
10. **Внешние ссылки на hash-маршруты** (`saqModules.ts`, документация, закладки пользователей) сломаются при переходе на `BrowserRouter`; нужен редирект `#/…` → `/evga/…` в `App.tsx` на переходный период.
11. **Производительность prof-паттерна** (N+1 в `loadRegistry`, полный обход страниц) — для ЭВГА с 43 видами документов и версиями агрегатный endpoint `workspace` обязателен с первого дня.
12. **PDF** — оставить pdfmake на клиенте или генерировать на сервере (печатные формы ЭВГА — `ReferencePrintForm.tsx` 1976 строк)?

---

## Приложение A. Эндпоинты, которые использует `api` в prof `client.ts`

| Пространство | Метод клиента | HTTP | Путь |
|---|---|---|---|
| auth | `me`, `maybeMe` | GET | `/auth/me` |
| auth | `login`, `register`, `logout` | POST | `/auth/local/login`, `/auth/local/register`, `/auth/local/logout` |
| subjects | `list`, `detail` | GET | `/subjects/?page&page_size&search&subject_type&ordering=name`, `/subjects/{id}/` |
| reporting | `extracts`, `importExtract` | GET, POST(FormData) | `/reporting/extracts/?status`, `/reporting/extracts/import/` |
| risk | `runs`, `trigger`, `candidates`, `rules` | GET, POST | `/risk/runs/`, `/risk/runs/trigger/ {extract}`, `/risk/candidates/?run&risk_category[]`, `/risk/rules/` |
| semiannual | `lists`, `versions`, `entries`, `departmentAssignments` | GET | `/semiannual/lists/`, `/semiannual/versions/?semiannual_list`, `/semiannual/entries/?version`, `/semiannual/department-assignments/?version` |
| semiannual | `formVersion1`, `createVersion2`, `submitVersion`, `approveVersion`, `formVersion`, `excludeEntry` | POST | `/semiannual/lists/form-v1/`, `/semiannual/lists/{id}/create-v2/`, `/semiannual/versions/{id}/submit/`, `…/approve/`, `…/form/`, `/semiannual/entries/{id}/exclude/ {reason}` |
| semiannual | `updateEntryResponsible`, `updateEntryRegion`, `updateDepartmentAssignmentResponsible` | PATCH | `/semiannual/entries/{id}/`, `/semiannual/department-assignments/{id}/` |
| cases | `list`, `detail`, `workspace` | GET | `/cases/?page&page_size&search&status&subject_type&region&business_category`, `/cases/{id}/`, `/cases/{id}/workspace/` |
| documents | `list`, `detail` | GET | `/documents/?status&list_entry`, `/documents/{id}/` |
| documents | `createNotice`, `createAppointmentAct`, `createResultAct` | POST | `/documents/notice/`, `/documents/appointment-act/`, `/documents/result-act/` |
| documents | `patchDetails` | PATCH | `/documents/{id}/` |
| documents | `approve`, `send`, `sign`, `acknowledge`, `attach` | POST (JSON или FormData) | `/documents/{id}/approve/`, `/send/`, `/sign/`, `/acknowledge/`, `/attachments/` |
| checklists | `byDocument`, `saveItem`, `attachItemFile`, `createViolation`, `updateViolation`, `deleteViolation`, `attachViolationFile`, `deleteViolationAttachment`, `saveGeneralReference`, `attachGeneralReferenceFile`, `complete` | GET/PATCH/POST/DELETE | `/checklists/?document`, `/checklists/items/{id}/`, `…/attachments/`, `…/violations/`, `/checklists/violations/{id}/`, `/checklists/{docId}/general-reference/`, `…/attachments/`, `/checklists/{docId}/complete/` |
| execution | `items`, `detail`, `updateItem`, `registerSubmission`, `decide` | GET/PATCH/POST | `/execution/items/?document`, `/execution/items/{id}/`, `…/submissions/`, `…/decide/` |
| cabinet | `documents`, `executionItems`, `acknowledgeDocument`, `registerSubmission` | GET/POST | `/cabinet/documents/`, `/cabinet/execution-items/?prescription__document`, `/cabinet/documents/{id}/acknowledge/`, `/cabinet/execution-items/{id}/submissions/` |
| ersop | `packages`, `buildPackage1`, `buildPackage2`, `submitPackage1`, `registerPackage1`, `approvePackage2Step` | GET/POST | `/ersop/packages/?case&kind`, `/ersop/packages/build-package-1/ {case}`, `…/build-package-2/`, `/ersop/packages/{id}/submit/`, `…/register/`, `…/approve-step/` |
| dashboard | `dashboard()` | GET ×7 | `countEndpoint` по 6 реестрам + `subjects.list({pageSize:5})`, `Promise.allSettled` |

## Приложение B. Каталог клиентских мутаций ЭВГА → кандидаты в серверные action-эндпоинты

| Чистая функция (файл) | Предлагаемый `action`/endpoint |
|---|---|
| `createDocument` (`documentFactory.ts`) | `POST /api/evga/cases/{id}/documents/ {kind}` |
| `saveDocument` (`workflow.ts`) — сохранение черновика/версии | `PATCH /api/evga/documents/{id}/versions/{n}/ {values, attachments…}` c `If-Unmodified-Since`/`expected_updated_at` |
| `deleteDocument` | `DELETE /api/evga/documents/{id}/` |
| `submitDocument`, `sendDocumentToQuality`, `approveDocument`, `returnDocument`, `rejectDocument`, `recallDocument`, `activateDocument`, `createNextVersion`, `createReturnedRevision`, `createRejectedRevision`, `reassignReturnedDocument`, `createResponseRevision` (`documentStateMachine.ts`) | `POST /api/evga/documents/{id}/actions/ {action: "submit"|"send-to-quality"|"approve"|"return"|"reject"|"recall"|"activate"|"new-version"|"reassign", comment?, route?}` |
| `performRegistration(send|accept|return)` (`workflow.ts`) | `POST …/actions/ {action: "register-send"|"register-accept"|"register-return", number?, comment?}` (в будущем — реальный вызов ЕРСОП на сервере) |
| `deliverDocument(send|acknowledge|respond|sign|object|refuse)` | `POST …/actions/ {action: "deliver"|"acknowledge"|"respond"|"sign"|"object"|"refuse", text?, files?}`; часть — из кабинета объекта |
| `sendInstructionToKvga`, `decideInstructionKvga`, `sendPreparationForApproval`, `signAssignmentGroup`, `approveAssignmentGroup`, `requestPreparationQuality`, `revisePreparationDocument` (`preparationWorkflow.ts`) | `{action: "kvga-send"|"kvga-decide"|"prep-approve-send"|"group-sign"|"group-approve"|"prep-quality-request"|"prep-revise"}` |
| `requestReportGroupSignatures`, `signReportGroup`, `sendRegistryToConfirmer`, `decideRegistryConfirmation`, `requestMainQuality`, `requestMainApproval`, `reviseMainDocument`, `signMainQuality`, `submitMainQualityToHead`, `reviseMainQuality` (`mainWorkflow.ts`) | `{action: "report-group-request"|"report-group-sign"|"registry-send"|"registry-confirm"|"main-quality-request"|"main-approval-request"|"main-revise"|"qc2-sign"|"qc2-submit"|"qc2-revise"}` |
| `addQualityConclusion`, `renewQuality` (`qualityControlRules.ts`, `workflow.ts`), назначение эксперта (`qualityAssignment.ts`) | `POST /api/evga/cases/{id}/quality/{stage}/assign/`, `…/conclusion/`, `…/renew/` |
| `assignCoauthor` (`caseAccess.ts`) | `POST /api/evga/cases/{id}/coauthors/` |
| `transitionInformationRequest` (`informationRequests.ts`) | `{action: "ir-send"|"ir-acknowledge"|"ir-provide"|"ir-refuse"|"ir-accept"|"ir-resend"}` |
| `thirdParties.ts`, `appeals.ts`, `amendments.ts`, `executionDecision.ts` | отдельные под-ресурсы дела |
| `nextCaseNumber`, `documentSequence` | серверная нумерация |
| `caseApprovalRoutes`, `getApprovalTasks` (`approvalTasks.ts`, `shared/workflow`) | `GET /api/evga/tasks/` |
| `executionItemsForCases` (`executionItems.ts`) | `GET /api/evga/execution/items/?case` |

## Приложение C. Инвентарь ключевых файлов

prof `frontend/src`: `App.tsx` (123), `main.tsx` (31), `api/client.ts` (555), `api/types.ts` (466), `api/profControlAdapter.ts` (285), `api/legacyAdapter.ts` (153), `auth/AuthContext.tsx` (17), `modules/prof/ProfControlModule.tsx` (1054), `profControlModuleHelpers.ts` (128), `routing.ts` (58), `useProfRouting.ts` (31), `pages/LoginPage.tsx` (98), `pages/SAQModulesPage.tsx` (47), `components/AppShell.tsx` (155), `SaqSidebar.tsx` (117), `LanguageSwitcher.tsx` (19), `ui.tsx` (60), `ModuleCard.tsx` (52), `i18n/LegacyLocalization.tsx` (111), `config/saqModules.ts` (76), `data/documentStatusRoutes.ts` (103), `workflowDefinitions.ts` (14), `documentMatrix.ts` (330), `types.ts` (144), `utils/statusLabel.ts` (57), `modules/prof/pages/CaseWorkspace.tsx` (1233), `CasesList.tsx` (120), `SemiannualListRegistry.tsx` (97), `SemiannualListWorkspace.tsx` (235), `case-workspace/*` (DocumentModal 402, ExecutionWorkspace 495, FilePicker 58 …), `subject-portal/*`.

evga `src`: `App.tsx` (35), `main.tsx` (31), `config.ts` (6), `auth/useDemoSession.ts` (34), `pages/LoginPage.tsx` (20), `modules/evga/EvgaModule.tsx` (331), `useAuditCases.ts` (80), `useEvgaNavigation.ts` (15), `services/auditCaseRepository.ts` (7), `indexedDbCaseRepository.ts` (63), `utils/navigation.ts` (22), `files.ts` (22), `id.ts` (1), `types.ts` (315), `components/AppShell.tsx` (189), `Sidebar.tsx` (158), `ui.tsx` (216), `Modal.tsx` (87), `FileAttachments.tsx` (85), `ErrorBoundary.tsx` (19), `data/demoData.ts` (352), `documentMatrix.ts` (177), `modules/evga/workflow.ts` (840), `documentStateMachine.ts` (831), `mainWorkflow.ts` (560), `preparationWorkflow.ts` (406), `demoScenario.ts` (1340), `documentFactory.ts` (115), `approvalTasks.ts` (113), `caseAccess.ts` (30), `caseRules.ts` (40), `pages/CasesList.tsx` (232), `CaseForm.tsx` (315), `CaseWorkspace.tsx` (653), `DocumentWorkspace.tsx` (765), `ApprovalTasks.tsx` (119), `ExecutionRegistryPage.tsx` (119), `ObjectsRegistry.tsx` (129), `modules/evga/components/DocumentActions.tsx` (404), `Notifications.tsx` (76), `shared/workflow/approvalRoute.ts` (539), `shared/execution/execution.ts` (492), `docs/architecture.md`, `vercel.json`, `vite.config.ts`.
