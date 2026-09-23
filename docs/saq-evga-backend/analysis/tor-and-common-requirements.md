# ТЗ модуля prof-control и сквозные требования SAQ, применимые к бэкенду ЭВГА

Область отчёта: постановка задачи модуля «Профилактический контроль» (`prof_docx4/Postanovka_obshhaya.txt`, 1768 строк / ~101 КБ текста, извлечённого из docx; таблицы docx разделены символами ` | `), сопутствующие документы эталонного проекта (`saq-prof-control-demo/docs/specs/document-matrix.md`, `docs/architecture/project-decisions.md`, `docs/release-notes/2026-07-30.md`, `README.md`), базовая трассировка ЭВГА (`saq-evga-test/docs/specification-baseline.md`) и реализация сквозных требований в бэкенде prof (`saq-prof-control-demo/backend/apps/*`). Для интеграций дополнительно разобраны воркфлоу старой реализации ЭВГА (`n8n_old/n8n_export/…`, `n8n_old/bpmn/…`).

Все пути ниже даны относительно `(рабочая папка анализа)/`:

| Сокращение | Путь |
|---|---|
| `TZ` | `prof_docx4/Postanovka_obshhaya.txt` |
| `prof/` | `src/prof/saq-prof-control-demo/` |
| `prof-be/` | `src/prof/saq-prof-control-demo/backend/apps/` |
| `prof-fe/` | `src/prof/saq-prof-control-demo/frontend/src/` |
| `evga/` | `src/evga/saq-evga-test/` |
| `n8n/` | `src/n8n_old/n8n_export/` |
| `bpmn/` | `src/n8n_old/bpmn/` |

Отчёт самодостаточен: все утверждения подтверждены чтением указанных файлов; там, где факт взят из формулировки задания и в репозиториях не найден, это явно отмечено.

---

## 0. Резюме

1. ТЗ prof описывает **один целевой маршрут** «СУР → полугодовой перечень → дело → уведомление → акт о назначении → пакет №1 в ЕРСОП → электронный проверочный лист → акт о результатах → предписание → пакет №2 → исполнение по пунктам». Оно построено из 52 нумерованных таблиц пяти типов (общие сведения, роли, сценарий варианта использования, функциональные требования с шифрами `RQ.SAQ.PC.NN.MM`, статусы документа, описание полей, правила процесса, интеграции, контрольные точки, статусы дела). Этот формат — образец для постановки бэкенда ЭВГА.
2. Раздел 2.13 (табл. 48–49) и раздел 3 (табл. 50) ТЗ содержат **сквозные требования платформы SAQ**: журнал действий с фиксированным составом записи, формат дат `ДД.ММ.ГГГГ` / `ДД.ММ.ГГГГ, ЧЧ:ММ`, унифицированная кнопка «Направить»/статус «Направлен», единый визуальный стиль «ЭВГА», интеграции как заглушки, раздельное хранение электронного и нарочного ознакомления, личный кабинет субъекта с печатными формами, вложения как файлы. В самом ТЗ (табл. 48, `RQ.SAQ.PC.09.01`) визуальный стиль prof предписано брать **из системы ЭВГА** — то есть prof и ЭВГА заказчик считает одной платформой.
3. В бэкенде prof эти требования реализованы в `core` (`AuditEvent`, `Attachment`, `NumberSequence`/`IssuedNumber`, `exceptions.py`, `pagination.py`), `accounts` (роли/уровни/скоуп, Keycloak PKCE, локальный вход), `documents` (`DocumentType`, `DocumentStatus`, `Acknowledgement`, сервисы переходов), `ersop` (`ErsopPackage`/`ErsopExchange` + `stub_exchange.py`), `cabinet` (кабинет субъекта), `catalogs` (справочники + `seed_catalogs`). Главная нестыковка эталона: **`AuditEvent` объявлен, но ни один сервис его не пишет** (`grep AuditEvent` даёт только `core/models.py`, `core/admin.py`, `core/tests/test_audit_event.py`), а «печатные формы» существуют только во фронте (`prof-fe/components/OfficialPrintForm.tsx`), бэкенд PDF не формирует.
4. Из 12 документов матрицы prof (`docs/specs/document-matrix.md`) прямые концептуальные аналоги в ЭВГА (36 `docKinds` + 7 `counterDocKinds` в `evga/src/data/documentMatrix.ts`) есть у 11; сопоставление приведено в разделе 3. Модели `ControlDocument`/`*Details`/`Acknowledgement`/`PrescriptionItem`/`ExecutionSubmission`/`ExecutionDecision` и сервисы переходов можно наследовать, но ЭВГА требует версии документа, повторяемые виды и многошаговый маршрут — этого в prof нет.
5. Интеграции: prof заглушает только ЕРСОП (`ersop/services/stub_exchange.py::fake_register_package`, регистрационный номер берётся из `NumberSequence` `ersop-package-1/2`), ГБД и ЭЦП не заглушены вовсе (ГБД — поле `Subject.gbd_synced_at` без сервиса, ЭЦП — просто статус `SIGNED`/`is_signed`). Старая n8n-реализация ЭВГА содержит реальный контракт ЕРСОП (SOAP `SI_SUR2ERSOP_RequestSubjectAsync`, `messageType M_TYPE_STARTED`, состав полей `started{…}`, файл PDF в base64), таблицу журнала `surfk.evga_audit_log` и синхронизацию пользователей Keycloak по ИИН — их надо перенести в стек prof как «адаптер + заглушка».
6. Для документации бэкенда ЭВГА рекомендуется завести `docs/specs/document-matrix.md` (по колонкам prof + `kind`, M-код, этап, владелец, тип маршрута, повторяемость, доставка объекту, регистрация в ЕРСОП, КК, печатная форма), `docs/specs/status-matrix.md`, `docs/specs/api-actions.md`, `docs/architecture/project-decisions.md`, `docs/architecture/integrations.md`, `docs/release-notes/YYYY-MM-DD.md`, `docs/tor/` и README по образцу prof (раздел 5).

---

## 1. Краткое содержание ТЗ prof-control

### 1.1 Общие сведения (раздел 1, табл. 1)

| Параметр | Значение из ТЗ |
|---|---|
| Система / модуль | ИС SAQ, модуль «Профилактический контроль»; документ на 35 листах, г. Астана, 2026 |
| Задача | Автоматизация основного (целевого) маршрута профилактического контроля с посещением субъекта |
| Заказчик / разработчик | КВГА МФ РК / АО «Центр электронных финансов» |
| Основание | Протокол рабочей встречи по постановке; действующие НПА РК по профилактическому контролю и регистрации актов |
| Цель | Сквозное электронное сопровождение от результатов СУР и полугодового перечня до снятия пунктов предписания с контроля |
| **Формат дат** | «Во всех экранных и печатных формах — ДД.ММ.ГГГГ; дата и время событий — ДД.ММ.ГГГГ, ЧЧ:ММ» |

Терминология: везде «субъект контроля» (в ЭВГА — «объект аудита»); единая логика ЭПЛ/Акта/Предписания/исполнения для всех категорий объектов (АО, ПАО, ПОБ, ОПСБ, ОПИ, ПО).

**В границах этапа**: получение результатов СУР и формирование перечня; создание дела после направления уведомления; документы начала контроля и пакет №1 в ЕРСОП; направление субъекту акта о назначении, проверочного листа и статьи 155 с фиксацией ознакомления; электронный проверочный лист (общая справка, результаты по требованиям, дробление нарушения на пункты, вложения, черновик, печатные формы); автоматический Акт о результатах из данных листа; пакет №2 на закрытие; исполнение отдельно по пунктам предписания (продление с согласованием / снятие с контроля); печатные формы и действия в личном кабинете субъекта.

**Вне границ**: возражения субъекта и результаты их рассмотрения; административное производство и обжалование; **окончательная ролевая модель и промышленная интеграция с внешними системами — «в прототипе представлены согласованными заглушками»**. Это прямо задаёт стиль MVP: заглушка интеграции считается допустимым результатом этапа.

### 1.2 Бизнес-процесс, роли, контрольные точки, статусы дела (раздел 2, табл. 2, 51, 52)

Роли (табл. 2): Аудитор (исполнитель); Согласующее/подписывающее лицо («конкретный состав определяется ролевой моделью»); Руководитель/ответственный; Субъект контроля (кабинет); SAQ (автоматические документы/статусы, валидация комплектности, история, обмен); СУР/DFO; ЕРСОП.

Контрольные точки маршрута (табл. 51):

| № | Точка | Условие продолжения |
|---|---|---|
| 1 | Формирование перечня | Проект согласован; нажата команда «Сформировать» |
| 2 | Создание дела | Уведомление направлено |
| 3 | Пакет №1 | Готовы 5 из 5 обязательных позиций |
| 4 | Начало контроля | Акт зарегистрирован в ЕРСОП; зафиксировано ознакомление с Актом, Проверочным листом и Статьёй 155 |
| 5 | Завершение проверочного листа | Сформирован хотя бы один пункт нарушения с описанием |
| 6 | Согласование Акта о результатах | После статуса «Согласован» ЭПЛ переводится в режим только для просмотра |
| 7 | Пакет №2 | Акт о результатах и Предписание подписаны, направлены, ознакомлены; 5 согласований завершены |
| 8 | Исполнение | Все пункты Предписания сняты с контроля; дело «Исполнена» |

Статусы дела (табл. 52 и `RQ.SAQ.PC.02.04`): «Ожидает уведомление» → «Уведомление направлено» → «Назначение контроля» → «В работе» (дата регистрации акта в ЕРСОП = дата начала контроля) → «Проверка завершена, ожидает исполнения» → «Исполнена». Статус дела **вычисляется** из этапа процесса (табл. 10, п. 11: «Рассчитывается из этапа процесса»).

### 1.3 Функциональные подразделы 2.1–2.12 (сводка)

| Подраздел | Суть | Шифры требований | Таблицы статусов / полей |
|---|---|---|---|
| 2.1 Полугодовой перечень | Получение кандидатов из СУР без изменения расчёта; поиск/фильтры/сортировка; «Детально» (учредитель, детализация риска); недоступные кандидаты серым с причиной; прямое основание и балльный отбор; версия №1 не утверждается — после согласования «Сформировать»; версия №2 однократна и допускает только исключение | `RQ.SAQ.PC.01.01–01.05` | табл. 5 (16 полей кандидата), табл. 7 (правила: состав, источник СУР, дата, автор и история версии сохраняются) |
| 2.2 Реестр и дело | Дело создаётся только после направления уведомления; ближайшая дата исполнения с цветом (≤5 дней красный, 6–10 жёлтый, >10 зелёный); поиск по номеру дела/субъекту/БИН/региону; фильтры тип/регион/КО/статус | `RQ.SAQ.PC.02.01–02.04` | табл. 10 (12 полей строки реестра) |
| 2.3 Уведомление | Создать → Согласовать → Направить; печатная форма в кабинет; возврат в «Проект»; ознакомление электронно или сканом | — | табл. 12 (5 статусов), табл. 13 (14 полей; исходящий номер из «регистрационного журнала SAQ») |
| 2.4 Акт о назначении | Создать/Согласовать/Подписать/Направить; два обязательных файла (пояснительная записка, основание решения по инвестору) блокируют согласование; после валидации авто-формируются карточка 1-П и проверочный лист; рег. номер и дата начала только после регистрации пакета №1; файлы в PDF акта не выводятся | `RQ.SAQ.PC.03.01–03.05` | табл. 16 (9 статусов), табл. 17 (22 поля) |
| 2.5 Автодокументы начала контроля | Учётная карточка 1-П (перенос полей акта, статусы «Не создан → Готова к отправке → Принята ЕРСОП», без отдельной печатной формы); проверочный лист по шаблону категории субъекта (отдельный PDF); статья 155 после регистрации | — | табл. 19 (9 полей 1-П), табл. 21 (5 статусов ПЛ), табл. 22 (3 статуса ст. 155) |
| 2.6 Пакет №1 | 5 позиций (табл. 24): подтверждение ознакомления с уведомлением; акт (согласован и подписан); карточка 1-П; требования ПЛ; пояснительная записка. Одна кнопка отправки при полной комплектности; фиксируется состав и идентификатор обмена; после регистрации сообщение «Зафиксируйте ознакомление с Актом о назначении, Проверочным листом и Статьёй 155»; ознакомление по каждому документу отдельно | — | табл. 25 (правила), табл. 27 (8 полей факта ознакомления: документ, способ, статус ответа кабинета, дата, скан, электронное подтверждение, кем, дата/время фиксации) |
| 2.7 ЭПЛ | Единая форма для всех категорий; «Общая информация для справки» + вложения; результат по каждому требованию; при «Нарушения выявлены» один или несколько пунктов (справка, обязательное описание, вложения); суммы только для ОПИ-01 с автосчётом; «Сохранить черновик» + дата/время; переход к Акту только при ≥1 пункте; блокировка листа после согласования Акта; печатный ПЛ отдельно от акта | `RQ.SAQ.PC.04.01–04.13` | табл. 30 (21 поле: код/наименование требования, результат, номер пункта, суммы, автор изменения, дата сохранения) |
| 2.8 Акт о результатах | Проект формируется автоматически из дела и ЭПЛ; аудитор заполняет только реквизиты; печатная форма по приложению 17 к Правилам регистрации актов; п. 5 — полный список требований; п. 6 — справка и пункты по требованиям; таблица нарушений без сумм; приложения из ЭПЛ; статусы согласование/подписание/направление/ознакомление | `RQ.SAQ.PC.05.01–05.10` | табл. 33 (7 статусов), табл. 34 (20 полей) |
| 2.9 Предписание | Позиция на каждый пункт нарушения (не на требование); приложение 18 к Правилам; по пункту — степень риска, рекомендации, дата исполнения; после ознакомления — отдельный объект исполнения на пункт | `RQ.SAQ.PC.06.01–06.06` | табл. 37 (9 статусов, включая «На исполнении», «Исполнено»), табл. 38 (17 полей) |
| 2.10 Пакет №2 | Два документа (Акт о результатах, Предписание — подписаны, направлены, ознакомлены); маршрут из 5 последовательных согласований (табл. 41: Исполнитель → Руководитель РГ → Руководитель СП → Курирующий руководитель → Уполномоченный руководитель); в пакет не входят акт о назначении, ПЛ и ст. 155; карточки закрытия нет | — | табл. 40, 41, 42 |
| 2.11 Исполнение | Единица — пункт предписания; поступления из кабинета и записи аудитора хранятся раздельно, неограниченно; «Снять с контроля» с датой; «Продлить срок» с новым сроком, основанием и согласованием; история решений по пункту; дело «Исполнена» после снятия всех пунктов; сводка «исполнено / на контроле / ожидается ответ»; цвет даты исполнения | `RQ.SAQ.PC.07.01–07.09` | табл. 45 (20 полей пункта исполнения: источник поступления, канал, автор, сведения о мерах, дата исполнения по ответу, вложения, решение, дата снятия, новый срок, основание, вложение к решению, автор/дата решения, история) |
| 2.12 Личный кабинет | Печатные формы, идентичные формам аудитора; обязательная последовательность ознакомления; ответ и вложения по пункту предписания; повторные ответы после продления с сохранением предыдущих | `RQ.SAQ.PC.08.01–08.05` | табл. 46 |

### 1.4 Раздел 2.13 — общие требования к интерфейсу, журналированию и данным (табл. 48–49)

| Шифр | Требование (дословно по смыслу) |
|---|---|
| `RQ.SAQ.PC.09.01` | Использовать визуальный стиль **системы ЭВГА**, адаптированный к структуре меню SAQ |
| `RQ.SAQ.PC.09.02` | Свёрнутое меню-иконки и развёрнутое меню; активный пункт выделять цветом |
| `RQ.SAQ.PC.09.03` | На 1920×1080 компактные таблицы и действия; длинные разделы сворачиваемые |
| `RQ.SAQ.PC.09.04` | Кнопку отправки унифицировать как «Направить»; статус направления — «Направлен» |
| `RQ.SAQ.PC.09.05` | Не выводить служебные подсказки-маршруты статусов в рабочей форме документа |
| `RQ.SAQ.PC.09.06` | Фиксировать автора, дату/время и результат каждого значимого действия в истории дела/документа |
| `RQ.SAQ.PC.09.07` | Для всех дат применять формат ДД.ММ.ГГГГ |

Минимальный состав записи журнала аудита (табл. 49):

| Поле | Тип | Содержание |
|---|---|---|
| Идентификатор дела/документа | Строка | Объект действия |
| Действие | Справочник | Создание, согласование, подписание, направление, ознакомление, решение и т.д. |
| Предыдущий/новый статус | Справочник | Переход состояния |
| Автор | Пользователь/роль | Кто выполнил действие |
| Дата и время | Дата/время | ДД.ММ.ГГГГ, ЧЧ:ММ |
| Основание/комментарий | Текст | При наличии |
| Файл/идентификатор обмена | Ссылка | При наличии вложения или внешнего обмена |

Это и есть спецификация `core.AuditEvent` prof (см. 2.1): семь колонок табл. 49 отображены в `content_type+object_id`, `action`, `status_from/status_to`, `actor/actor_role`, `occurred_at`, `reason`, `attachment/exchange_id`.

### 1.5 Раздел 3 — интеграции (табл. 50)

Преамбула раздела: «В демонстрационном прототипе интеграционные операции реализованы как функциональные заглушки. Настоящее ТЗ фиксирует состав данных и контрольные точки; протоколы, адреса сервисов, форматы сообщений, ЭЦП и обработка технических ошибок подлежат детализации на этапе промышленной интеграции».

| Система/контур | Направление | Состав данных | Результат |
|---|---|---|---|
| DFO | В SAQ | Данные отчётов АО, ПАО, ПОБ, ОПСБ, ОПИ, ПО | Проект кандидатов перечня |
| ГБД ЮЛ | В SAQ | БИН; наименование; ОПФ; дата и статус регистрации; юридический адрес; учредители и руководитель | Карточка субъекта, проверка регистрационных данных |
| ГБД ФЛ | В SAQ | ИИН; ФИО; сведения о ФЛ-учредителях/руководителях/представителях | Идентификация связанных лиц |
| ЕРСОП — пакет №1 | Из SAQ | Подтверждение ознакомления с уведомлением; подписанный Акт; карточка 1-П; требования ПЛ; пояснительная записка | Рег. номер/дата Акта; статус обмена |
| Личный кабинет субъекта | Двустороннее | Печатные формы; электронные подтверждения ознакомления; ответы и файлы по пунктам | «Субъект ознакомлен» и поступления исполнения |
| ЕРСОП — пакет №2 | Из SAQ | Акт о результатах и Предписание с подтверждениями; результат пятиэтапного согласования | Принятие пакета на закрытие; идентификатор обмена |

Keycloak/ЭЦП в табл. 50 отсутствуют: авторизация и подпись в ТЗ prof упомянуты только как «пользователь авторизован» (предусловия сценариев) и «Подписать»/«Подписан» (действия и статусы). Это подтверждает решение MVP из `prof/docs/specs/document-matrix.md`: «Вместо ЭЦП используется демонстрационное действие „Утвердить“».

### 1.6 Формат постановки (что копировать для ЭВГА)

Каждая функция описана фиксированным набором таблиц с однотипными шапками:

| Тип таблицы | Колонки | Пример |
|---|---|---|
| Сценарий варианта использования | Параметр / Описание: Действующие лица; Предусловия; Постусловия; Основной сценарий (нумерованные шаги); Альтернативные сценарии | табл. 3, 6, 8, 11, 14, 18, 20, 23, 26, 28, 31, 35, 39, 43, 46 |
| Функциональные требования | Шифр требования (`RQ.SAQ.PC.<функция>.<номер>`) / Требование / Новое-изменённое | табл. 4, 9, 15, 29, 32, 36, 44, 47, 48 |
| Статусы документа | № / Статус / Условие установления | табл. 12, 16, 21, 22, 33, 37 |
| Описание полей | № / Наименование поля / Тип поля (Строка, Дата, Справочник, Файл, Логический, Составной блок, Автотекст, Журнал…) / Обязательность (Да, Нет, Условно, Автоматически) / Комментарий (источник значения) | табл. 5, 10, 13, 17, 19, 27, 30, 34, 38, 45 |
| Правила процесса | № / Правило | табл. 7, 25, 42 |
| Состав пакета / маршрут | № / Позиция / Критерий готовности; Шаг / Участник / Результат | табл. 24, 40, 41 |
| Интеграции, контрольные точки, статусы дела | см. 1.2, 1.5 | табл. 50, 51, 52 |

Стиль `evga/docs/specification-baseline.md` совместим: там те же категории (границы модуля, общая модель документа, роли, коды `UC.EKA.EGA.VP.01–08`, таблицы полей с пометками О/НО и Р/НР, интеграции, журнал расхождений). Отличие — в ЭВГА обязательность полей задаётся кодами **О/НО**, редактируемость **Р/НР**, а в prof — словами «Да/Нет/Условно/Автоматически» в отдельной колонке. Для постановки бэкенда ЭВГА рекомендуется объединить: колонки prof + признак редактируемости.

---

## 2. Сквозные требования SAQ и их реализация в prof-бэкенде

### 2.0 Сводная таблица

| № | Сквозное требование | Источник в ТЗ | Реализация в prof-бэкенде (файл / класс / функция) | Вердикт для ЭВГА |
|---|---|---|---|---|
| 1 | Журнал действий по делу/документу | табл. 49, `RQ.SAQ.PC.09.06` | `prof-be/core/models.py::AuditEvent`, `AuditAction`, append-only `AuditEventQuerySet`; **сервисы не пишут** | reuse-as-is + расширить `AuditAction` + helper `record_event()` |
| 2 | Формат дат | табл. 1, `RQ.SAQ.PC.09.07` | Бэкенд: ISO 8601 (DRF `DateField`/`DateTimeField`, `TIME_ZONE="UTC"`); фронт: `prof-fe/utils/dateFormat.ts::formatDateDisplay` | reuse; решить вопрос `TIME_ZONE` (ЭВГА/ЕРСОП — `+05:00`) |
| 3 | Нумерация (регистрационный журнал SAQ) | табл. 13 п. 9, табл. 34 п. 1, табл. 38 п. 1, табл. 10 п. 1 | `core/models.py::NumberSequence/IssuedNumber`, `core/services/numbering.py::issue_number`, `seed_number_sequences.py` | reuse-as-is, свои шаблоны |
| 4 | Статусы документов | табл. 12, 16, 21, 22, 33, 37 | `documents/models.py::DocumentStatus` (14 кодов), `_STATUS_LABEL_OVERRIDES`, `document_status_label()` | adapt: коды ЭВГА (11 `DocStatus`) + тот же механизм подписей |
| 5 | Согласование/подписание/направление вместо ЭЦП | табл. 15 `RQ.SAQ.PC.03.01`, матрица MVP «Утвердить» | `ControlDocument.approved_at/by, is_signed, signed_at/by, sent_at/by`; `documents/services/{notice,appointment_act,result_act,prescription}.py`; `documents/api/views.py::Approve/Sign/SendDocumentView` | adapt: та же схема + модель подписи с провайдером-заглушкой |
| 6 | Ознакомление (электронное/нарочное, раздельно) | табл. 26–27, табл. 25 п. 04 | `documents/models.py::Acknowledgement` (`unique(document, channel)`), `services/acknowledgement.py::record_acknowledgement` | reuse-as-is |
| 7 | Личный кабинет субъекта/объекта | 2.12, табл. 50 | `accounts.User.is_subject_representative/subject`, `accounts/permissions.py::IsSubjectRepresentative`, `cabinet/api/*` | adapt: те же view-паттерны + действия ЭВГА |
| 8 | Вложения | табл. 27, 30, 45; матрица «доказательства — файлы» | `core/models.py::Attachment/AttachmentKind`, `core/services/files.py::sha256_of`, `documents/services/attachments.py`, MinIO в `config/settings/production.py` | reuse-as-is + новые `AttachmentKind` |
| 9 | Права ролей и территориальный скоуп | табл. 2, «ролевая модель — заглушка» | `accounts/models.py::Role/RoleScope/PermissionDomain/PermissionLevel/RolePermission/RoleAssignment`, `permissions.py::HasDomainLevel`, `querysets.py::ScopedQuerySetMixin`, `seed_roles.py` (14 ролей), `documents/api/views.py::_assert_department_in_scope` | adapt: домены/роли ЭВГА, объектные права в сервисах |
| 10 | Справочники/НСИ | табл. 5, 13, 17 («Справочник», «НСИ») | `catalogs/models.py` (`Region`, `Department`, `GovernmentBody`, `SubjectTypeRef`, `BusinessCategory`, `ViolationSeverity`, `RiskDegree`, `InspectionSubjectMatter`, `NormativeAct`, `ControlEligibilityRule`), `seed_catalogs.py` | adapt: общие оставить, добавить справочники ЭВГА |
| 11 | Версии документов / перечня | табл. 6–7 (версии №1/№2 перечня) | `semiannual/models.py::SemiannualListVersion` (+`current_version`), `services/list_formation.py`; у `ControlDocument` версий нет (`UniqueConstraint(list_entry, document_type)`) | rewrite: `DocumentVersion` в ЭВГА обязателен |
| 12 | Печатные формы | табл. 15 п. 05, `RQ.SAQ.PC.05.01`, `06.01`, `08.01` | **бэкенд не формирует**; `prof-fe/components/OfficialPrintForm.tsx` рендерит HTML для 6 документов из `details` API | новое: серверный PDF нужен для ЕРСОП (см. 4.1) |
| 13 | Статус дела вычисляется | табл. 10 п. 11, табл. 52 | `cases/models.py::ControlCase.status` (property) → `cases/services/case_status.py::compute_status/entry_status` | adapt (паттерн) |
| 14 | Единый формат ошибок API | — (техническое) | `core/exceptions.py::exception_handler` (RFC 7807-подобный конверт `type/title/status/detail/code`), `core/middleware.py::JsonNotFoundMiddleware`, `core/views.py` | reuse-as-is |
| 15 | Пагинация/фильтры | `RQ.SAQ.PC.01.02`, `02.03` | `core/pagination.py::PageNumberPaginationWithPageSize` (`page_size`, max 200), `django_filters` + `SearchFilter` + `OrderingFilter` в `REST_FRAMEWORK` | reuse-as-is |
| 16 | Интеграции как заглушки | раздел 3 | `ersop/services/stub_exchange.py::fake_register_package` | reuse паттерн; см. раздел 4 |
| 17 | Кнопка «Направить»/статус «Направлен» | `RQ.SAQ.PC.09.04` | `DocumentStatus.SENT = "Направлен"`, `SendDocumentView` | adapt: в ЭВГА «Направлен» = `deliverDocument("send")`, при этом статус документа `Активный` |

### 2.1 Журналирование действий

**ТЗ**: табл. 49 (7 полей), `RQ.SAQ.PC.09.06`; кроме того, табл. 7 п. 03 («состав каждой версии, источник СУР, дата, автор и история действий сохраняются»), табл. 27 п. 7–8 («Кем зафиксировано», «Дата и время фиксации — аудит события»), табл. 30 п. 20–21 («Автор изменения», «Дата сохранения»), табл. 45 п. 19–20 («Автор и дата решения — неизменяемая запись», «История решений — журнал»).

**prof-бэкенд** (`prof-be/core/models.py`):

```python
class AuditAction(models.TextChoices):
    CREATE = "create", "Создание"; APPROVE = "approve", "Согласование"; SIGN = "sign", "Подписание"
    SEND = "send", "Направление"; ACKNOWLEDGE = "acknowledge", "Ознакомление"
    DECIDE = "decide", "Решение"; EXCHANGE = "exchange", "Обмен"

class AuditEvent(models.Model):
    content_type / object_id / content_object (GenericFK)      # табл. 49 «Идентификатор дела/документа»
    action = CharField(choices=AuditAction.choices)             # «Действие» (справочник)
    status_from / status_to                                     # «Предыдущий/новый статус»
    actor = FK(User, on_delete=PROTECT); actor_role ('system')  # «Автор» (пользователь/роль)
    occurred_at = DateTimeField(default=timezone.now)           # «Дата и время»
    reason = TextField                                          # «Основание/комментарий»
    attachment = FK(Attachment); exchange_id = CharField        # «Файл/идентификатор обмена»
```

Свойства: `save()` запрещает изменение существующей записи, `delete()` запрещён, `AuditEventQuerySet.update/delete` бросают `ValueError`; `actor` защищён `PROTECT` (тест `test_deleting_the_actor_user_is_blocked_while_they_have_audit_events`). Индекс `(content_type, object_id, occurred_at)`, `ordering=["-occurred_at"]`.

**Факт**: ни один сервис prof не создаёт `AuditEvent` — история переходов восстанавливается только по полям `approved_at/by`, `signed_at/by`, `sent_at/by` документа, `ErsopExchange`, `ExecutionDecision`, `Acknowledgement.created_by/created_at`. Поле «Кем зафиксировано» (табл. 27 п. 7) реализовано как `Acknowledgement.created_by` (в `AcknowledgementSerializer.created_by_name`).

**Аналоги в ЭВГА и n8n**:
- Фронт ЭВГА: `evga/src/types.ts::HistoryEntry = {id, at, actor, action, comment}`, `evga/src/modules/evga/history.ts::log(actor, action, comment)`; история ведётся на деле и на каждой версии документа (`DocumentVersion.history`), например `v.history.push(log(actor.name, "Учёт регистрации: Отправлена", comment))` в `workflow.ts::performRegistration`. Это ровно проекция табл. 49 без `status_from/to` и без ссылки на файл/обмен.
- n8n: таблица `surfk.evga_audit_log` (воркфлоу `EVGA: Document History Record`, `n8n/workflows/EVGA_Document_History_Record__2v33Om9wo0jmfRgl.json`): `entity_type ('case'|'case_document')`, `entity_id`, `case_document_id`, `case_id`, `action_code`, `status_code`, `field_changes jsonb` (`[{field:'status', old, new}]`), `performed_by_iin`, `performed_by_name`, `comment`, `source ∈ {user, zeebe, system, ersop, timer}`, `created_at`; дедупликация одинаковых записей в окне 10 секунд; чтение с `JOIN surfk.evga_document_action_types at ON at.code = al.action_code` и `surfk.evga_document_statuses ds ON ds.code = al.status_code` (человекочитаемые `name_ru`), пагинация `page/page_size ≤ 100`.

**Рекомендация для ЭВГА**: взять `core.AuditEvent` как есть; расширить `AuditAction` кодами n8n (см. 2.4: `submit`, `return`, `reject`, `activate`, `confirm`, `kvga_confirm`, `send_to_ersop`, `ersop_registered`, `deliver`…) или хранить `action` как код справочника `AuditActionType(code, name_ru, name_kz)`; добавить поле `source` (`user/system/ersop/timer`) по образцу n8n; в `core/services/audit.py` завести `record_event(target, *, action, actor, status_from="", status_to="", reason="", attachment=None, exchange_id="")` и вызывать его из каждой transition-функции после `save()`. GET-эндпоинт истории — `/api/evga/documents/<id>/history/` с пагинацией prof.

### 2.2 Форматы дат и времени

**ТЗ**: `ДД.ММ.ГГГГ` везде, `ДД.ММ.ГГГГ, ЧЧ:ММ` для событий (табл. 1, `RQ.SAQ.PC.09.07`, табл. 49).

**prof**: бэкенд не форматирует — `config/settings/base.py`: `LANGUAGE_CODE="ru"`, `TIME_ZONE="UTC"`, `USE_TZ=True`; DRF отдаёт `YYYY-MM-DD` / ISO 8601. Форматирование на фронте: `prof-fe/utils/dateFormat.ts::formatDateDisplay(value)` → `"${day}.${month}.${year}"` или `"${day}.${month}.${year}, ${hour}:${minute}"`; `parseDateValue` принимает оба вида. В печатных формах свой `formatDate` в `OfficialPrintForm.tsx`.

**ЭВГА-фронт**: `evga/src/utils/dateFormat.ts::dateText(value, time)` — `Intl.DateTimeFormat("ru-RU", {day:"2-digit", month:"2-digit", year:"numeric", timeZone:"Asia/Almaty"})`, т.е. тот же формат, но с явной зоной Алматы.

**n8n/ЕРСОП**: `formatDateForErsop` → `YYYY-MM-DD+05:00`, `formatDateTimeForErsop` → ISO с `+05:00` (воркфлоу `ERSOP - Build and Send from Document`).

**Рекомендация**: API — ISO 8601 (как prof); для ЭВГА установить `TIME_ZONE="Asia/Almaty"` (сроки в рабочих днях и ответы ЕРСОП завязаны на местную дату); формат отображения — на фронте; в серверных PDF использовать `ДД.ММ.ГГГГ`.

### 2.3 Нумерация

**ТЗ**: «Исходящий номер — регистрационный журнал SAQ» (табл. 13 п. 9), «Номер акта/предписания — регистрационный журнал SAQ» (табл. 34 п. 1, табл. 38 п. 1), «Номер дела присваивается после направления уведомления» (табл. 10 п. 1), регистрационный номер акта присваивает ЕРСОП (табл. 17 п. 1).

**prof** (`prof-be/core/models.py`, `core/services/numbering.py`, `core/management/commands/seed_number_sequences.py`):

| `key` | `pattern` | Кто выдаёт |
|---|---|---|
| `control-case` | `ПК-{region:02d}-{yy}-{seq:04d}` | `documents/services/notice.py::send_notice` → `ControlCase.number` |
| `notice-outgoing` | `Исх-{yyyy}-{seq:04d}` | `send_notice` → `ControlDocument.number` уведомления |
| `ersop-package-1` | `ERSOP-OUT-{yyyy}-{seq:04d}` | `ersop/services/stub_exchange.py::fake_register_package` → `registration_number` |
| `ersop-package-2` | `ERSOP-CLOSE-{yyyy}-{seq:04d}` | то же для пакета №2 |

`issue_number(key, target, scope, context)` — `select_for_update` на `NumberSequence`, идемпотентность через `IssuedNumber(sequence, content_type, object_id)` (`UniqueConstraint` на `(sequence, value)` и на `(sequence, content_type, object_id)`), `SequenceNotDefined` если сид не выполнен. Номера акта о результатах и предписания сервисы prof **не выдают** (поле `number` у них остаётся пустым — расхождение с табл. 34/38).

**ЭВГА-фронт**: `caseRules.ts::nextCaseNumber` → `30101-{YY}-{seq}` (seq — max по существующим +1); `documentFactory.ts` → номер документа `${audit.number}/${NN}` через `documentSequence(audit)` (номера удалённых документов не переиспользуются); регистрационный номер ЕРСОП-заглушки `УЧ-{doc.number с «/»→«-»}` (`workflow.ts::performRegistration`).

**n8n**: `surfk.cases.registration_number` (используется как `case_number` в ЕРСОП-пакете), `surfk.evga_doc_registration_card.uo_check_number`.

**Рекомендация**: `seed_number_sequences` ЭВГА: `("evga-case", "", "30101-{yy}-{seq:04d}")`, `("evga-document", scope=<case uuid>, "{case_number}/{seq:02d}")` (scope = id дела, чтобы нумерация была внутри дела), `("ersop-registration", "", "УЧ-{yyyy}-{seq:05d}")` для заглушки регистрации.

### 2.4 Статусы документов

**ТЗ**: 6 таблиц статусов с колонкой «Условие установления»; общее ядро «Не создан → Проект → Согласовано → Подписан → Направлен → Субъект ознакомлен» плюс ЕРСОП-ветка («Готов к отправке → На регистрации в ЕРСОП → Зарегистрирован») и ветка исполнения («Включено в пакет №2 → На исполнении → Исполнено»).

**prof** (`prof-be/documents/models.py`):

```python
class DocumentStatus(models.TextChoices):
    DRAFT="Проект"; APPROVED="Согласовано"; SIGNED="Подписан"; READY="Готов к отправке"
    IN_ERSOP="На регистрации в ЕРСОП"; REGISTERED="Зарегистрирован"; SENT="Направлен"
    ACKNOWLEDGED="Субъект ознакомлен"; ACCEPTED="Принята ЕРСОП"; GENERATED="Сформирован"
    IN_PACKAGE_1="Включён в пакет №1"; IN_PACKAGE_2="Включён в пакет №2"
    IN_EXECUTION="На исполнении"; EXECUTED="Исполнено"
_STATUS_LABEL_OVERRIDES = {("card-1-p", READY): "Готова к отправке", ("result-act", APPROVED): "Согласован",
                           ("prescription", APPROVED): "Согласован", ("prescription", IN_PACKAGE_2): "Включено в пакет №2"}
```

Приём: **один общий enum кодов + переопределение подписей по типу документа** (`document_status_label(code, status)`, отдаётся сериализатором как `status_label`). Статус «Не создан» в БД не хранится — это отсутствие записи (`case.document(code) is None`), на фронте `documentStatusRoutes.ts` держит его как индекс 0. Переходы жёстко проверяются в сервисах (`if document.status != DocumentStatus.DRAFT: raise DocumentTransitionError(...)`).

**ЭВГА-фронт**: `types.ts::DocStatus` — 11 русских строк-кодов: «Проект», «Направлен на согласование КК», «На согласовании», «На утверждении», «Согласован», «На подтверждении КВГА», «На подтверждении реестра», «На подписании рабочей группой», «Возвращен на доработку», «Отклонен», «Активный». Статус живёт на версии (`DocumentVersion.status`); «Направлен» объекту — не статус, а `delivery.sentAt`; регистрация — `registration.status ∈ {Отправлена, Зарегистрирована, Возвращена}`.

**n8n** (`surfk.evga_document_statuses.code`, встречаются в SQL воркфлоу): `draft`, `pending_approval`, `approved`, `pending_kvga`, `kvga_confirmed`, `pending_confirmation`, `confirmed`, `revision`, `rejected`, `active`, `signed`, `signed_with_objection`, `sent_to_ak`, `sent_to_ersop`, `registered`, `closed`. Коды действий (`action_code` в `surfk.evga_audit_log` / Zeebe `availableActions`): `create`, `save`, `submit`, `approve`, `confirm`, `direct_confirm`, `activate`, `accept`, `return`, `reject`, `send_to_kvga`, `kvga_confirm`, `kvga_return`, `kvga_reject`, `send_to_confirmation`, `send_to_ersop`, `ersop_registered`, `ersop_accepted`, `ersop_revision`, `ersop_rejected`, `ersop_error`, `send_to_audit_object`, `send_to_ak`, `objection`, `create_objection_doc`, `qc_close`, `close_case`, `case_created`, `delete`.

**Рекомендация**: `DocumentStatus` ЭВГА — латинские коды по образцу n8n (`DRAFT`, `QUALITY_REVIEW`, `IN_REVIEW`, `IN_APPROVAL`, `REVIEWED`, `PENDING_KVGA`, `PENDING_REGISTRY`, `GROUP_SIGNING`, `RETURNED`, `REJECTED`, `ACTIVE`) с русскими `label` = строки `DocStatus` фронта (чтобы фронт продолжал показывать свои строки), плюс `_STATUS_LABEL_OVERRIDES` для видов с особой лексикой. Отдельные enum'ы `RegistrationStatus` (`SENT/REGISTERED/RETURNED`) и `DeliveryDecision` (`SIGNED/SIGNED_WITH_OBJECTION/REFUSED`) — как поля версии, не статус.

### 2.5 Согласование, подписание, направление (утверждение вместо ЭЦП)

**ТЗ**: действия «Создать», «Согласовать», «Подписать», «Направить» (`RQ.SAQ.PC.03.01`, табл. 11, 14, 31, 35), пятишаговое согласование пакета №2 (табл. 41 — «заглушка прототипа»). `prof/docs/specs/document-matrix.md`: «Вместо ЭЦП используется демонстрационное действие „Утвердить“» — на практике в коде это пара `approve` + `sign`.

**prof**: на `ControlDocument` поля `approved_at/approved_by`, `is_signed/signed_at/signed_by`, `sent_at/sent_by`; сервисы `approve_*`, `sign_*`, `send_*` в `documents/services/*.py`; API — три `APIView` с диспетчеризацией по коду типа (`ApproveDocumentView._APPROVERS`, `SignDocumentView._SIGNERS`, `SendDocumentView` if/elif), уровни прав `APPROVE` / `SIGN` / `EDIT` соответственно (`required_levels`). Побочные эффекты переходов закодированы в сервисах: `sign_appointment_act` создаёт карточку 1-П (`READY`) и проверочный лист (`GENERATED` + `generate_checklist`); `sign_result_act` вызывает `generate_prescription`; `send_notice` выдаёт номера и создаёт `ControlCase`. Многошаговое согласование есть только у пакета №2: счётчик `ErsopPackage.package_2_approved_steps` и константа `PACKAGE_2_APPROVAL_STEPS` (5 названий ролей) в `ersop/services/package_2.py` — участники не персонифицированы.

**ЭВГА-фронт**: `DocumentVersion.signatures[{person, at, role}]` без криптографии; маршрут `ApprovalRoute` (`evga/src/shared/workflow/approvalRoute.ts`, последовательный `reviewers[]` + `approver`, статусы `review/signing/completed/superseded`), подписи рабочей группы («На подписании рабочей группой»), решение объекта `delivery.decision`.

**n8n/BPMN**: ЭЦП присутствует как флаг и параметр: в Zeebe-процессах `availableActions[].requires_signature` (например, `bpmn/bpmn_summary.txt`, процесс `evga_doc_51` «Возражения»: действие `signed` с `requires_signature: true`, `allowed_roles: ["audit_object"]`), в `EVGA ERSOP Workflow` параметр `signature` передаётся в `send_to_ersop` и в `surfk.evga_document_approvals` пишется комментарий «Подписан ЭЦП и отправлен в ЕРСОП»; проверки подписи в воркфлоу нет.

**Рекомендация**: сохранить контракт prof (`approve/sign/send` + `approved_by/signed_by/sent_by`), но вынести подпись в модель `DocumentSignature(version, signer, role, signed_at, provider ∈ {stub, ncalayer}, cms_payload, cert_subject)`; в MVP `provider=stub` заполняется действием «Утвердить/Подписать»; сервис `signing.py::sign_version(version, actor, *, signature=None)` принимает опциональный CMS из фронта (как параметр `signature` в n8n) и валидирует его только при `provider != stub`. Многошаговый маршрут — отдельные модели `ApprovalRoute/ApprovalStep` (контракт уже описан во фронте), а не счётчик, как в пакете №2.

### 2.6 Ознакомление

**ТЗ**: табл. 26–27; правило табл. 25 п. 04 «для каждого документа ознакомление учитывается отдельно»; альтернативный сценарий табл. 26: «электронный и внесённый аудитором факты хранятся раздельно и не перезаписывают друг друга».

**prof**: `documents/models.py::Acknowledgement(document, channel ∈ {portal, manual}, acknowledged_on, proof_ref, attachment)` с `UniqueConstraint(document, channel)`; `AcknowledgementChannel`, `PortalAcknowledgementStatus (received/not_received)`; `services/acknowledgement.py::record_acknowledgement` — `select_for_update` на документ, требует статус `SENT|ACKNOWLEDGED`, для `manual` обязателен скан (`AttachmentKind.ACKNOWLEDGEMENT_SCAN`), для `portal` — `proof_ref` (формируется как `cabinet:{user.id}:{iso}` или `staff:{user.id}:{iso}`); первый факт переводит документ в `ACKNOWLEDGED`. `DocumentType.requires_acknowledgement` определяет, какие типы попадают в кабинет.

**ЭВГА-фронт**: `DocumentVersion.delivery{sentAt, acknowledgedAt, response, attachments, decision, decidedAt, decidedBy}`; `workflow.ts::deliverDocument(doc, actor, action ∈ {send, acknowledge, respond, sign, object, refuse})`; `deliverable(kind)` — 14 видов.

**Рекомендация**: reuse `Acknowledgement` без изменений (привязать к `DocumentVersion`), добавить `DocumentDelivery(version, sent_at, sent_by, decision, decided_at, decided_by, response_text)` для решений объекта («Подписан / Подписан с возражениями / Отказ от подписания»), которых в prof нет.

### 2.7 Личный кабинет субъекта / объекта аудита

**ТЗ**: 2.12, `RQ.SAQ.PC.08.01–08.05`, табл. 50 «Личный кабинет субъекта — двустороннее».

**prof**: представитель — обычный `accounts.User` с `is_subject_representative=True` и FK `subject` (регистрация по БИН в `accounts/api/local_views.py::RegisterView` → `RegisterSerializer.validate` ищет `Subject` по `bin`); `accounts/permissions.py::IsSubjectRepresentative`; приложение `cabinet` (`/api/cabinet/`): `CabinetDocumentViewSet` (документы субъекта с `document_type.requires_acknowledgement=True` и `sent_at` не пустым), `CabinetAcknowledgeView` (канал `portal`), три download-view для вложений (документа, общей справки ПЛ, пункта нарушения), `CabinetPrescriptionItemViewSet` (пункты предписания в статусах `ACKNOWLEDGED/IN_EXECUTION/EXECUTED`), `CabinetRegisterSubmissionView` (`register_submission(source=SUBJECT_CABINET, channel="Личный кабинет")`); защита `_assert_subject_owns(user, subject_id)`; сериализаторы получают `context={"cabinet": True}`, чтобы ссылки на файлы указывали на кабинетные маршруты. Печатные формы субъекту отдаёт фронт (`OfficialPrintForm` по тем же `details`).

**ЭВГА-фронт**: роль `object` в той же SPA; действия объекта — ознакомление, ответ на требование сведений, подпись отчёта/реестра с возражениями, подача возражений (`objections`, владелец `object`), третьи лица (`ThirdPartyNotice`), ответ о принятых мерах (`response`, может создавать объект).

**n8n**: роль `audit_object` в `allowed_roles` действий Zeebe.

**Рекомендация**: reuse каркас `cabinet` (permission, `_assert_subject_owns`, контекст `cabinet`), расширить эндпоинтами: `POST /api/cabinet/documents/<id>/decision/` (sign/object/refuse), `POST /api/cabinet/requests/<id>/respond/`, `POST /api/cabinet/objections/`, `POST /api/cabinet/third-parties/`, `POST /api/cabinet/execution-items/<id>/submissions/` (уже есть в prof).

### 2.8 Вложения

**ТЗ**: файлы в табл. 17 (пояснительная записка, основание по инвестору — «в PDF не выводится», «передаётся в ЕРСОП»), табл. 27 (скан подтверждения), табл. 30 (приложения к общей информации/пункту, документ к доказательству), табл. 45 (вложения к ответу и к решению); матрица MVP: «Аудиторские доказательства реализуются как прикладываемые файлы».

**prof**: `core/models.py::Attachment` — GenericFK (`content_type`, `object_id` CharField 64), `kind` (`AttachmentKind`: `acknowledgement_scan`, `explanatory_note`, `investor_basis`, `audit_evidence`, `general_reference`, `execution_confirmation`, `decision_attachment`), `file` (`upload_to="attachments/{content_type_id}/{object_id}/{uuid}_{name}"`), `original_name`, `size`, `mime`, `checksum` SHA-256 (`core/services/files.py::sha256_of`), `uploaded_by/at`. Хранилище: локально `FileSystemStorage` (`MEDIA_ROOT`), в production `storages.backends.s3.S3Storage` на MinIO (`config/settings/production.py`, `docker-compose.yml`: сервисы `minio`, `minio-init` с бакетом `saq-attachments`, `default_acl=private`, `querystring_auth=True`, `file_overwrite=False`). Выдача файлов — только через view с проверкой прав (`FileResponse`, `Http404` если файла нет в хранилище). Обязательность файлов проверяется в сервисе перехода (`approve_appointment_act` → `REQUIRED_ATTACHMENT_KINDS`). Ограничений размера/MIME на бэкенде нет.

**ЭВГА-фронт**: `Upload` хранится в IndexedDB как base64 внутри `AuditCase`; n8n: `surfk.evga_document_attachments(document_id, file_id, description, file_name)` + отдельный сервис файлов (`/webhook/download-base64-test/…/download-base64/{file_id}`), из которого документ в base64 уходит в ЕРСОП.

**Рекомендация**: reuse `Attachment`; расширить `AttachmentKind` (`document_file`, `basis_document`, `evidence_file`, `request_response`, `refusal_proof`, `objection_argument`, `third_party_notice`, `quality_material`, `signed_pdf`); добавить проверку MIME/размера в сериализаторах загрузки; для ЕРСОП — сервис, получающий содержимое файла из storage и кодирующий base64.

### 2.9 Права ролей и территориальный скоуп

**ТЗ**: табл. 2; «окончательная продуктивная ролевая модель… вне границ» — в прототипе роли-заглушки; табл. 41 — пять именованных участников согласования.

**prof** (`prof-be/accounts/`):
- `Role(code, name, order, scope ∈ {national, territorial})`, `RolePermission(role, domain ∈ {semiannual, cases, execution}, level ∈ {none, view, edit, approve, sign, decide})`, `RoleAssignment(user, role, department, valid_from, valid_to)` с `RoleAssignmentQuerySet.active()`; территориальная роль требует `department` (`RoleAssignment.clean`).
- `permissions.py::HasDomainLevel` — view объявляет `required_domain` и `required_levels`; `IsSubjectRepresentative`.
- `querysets.py::ScopedQuerySetMixin` — `national` видит всё, `territorial` — только свои `department` (`scope_department_field`), `assert_department_writable`.
- `documents/api/views.py::_assert_department_in_scope(user, department)` — та же проверка для action-эндпоинтов, достающих объект по UUID (импортируется в `ersop`, `checklists`, `execution`, `cases`).
- `seed_roles.py` — 14 ролей: `list-officer`, `list-officer-inspector`, `list-supervisor`, `list-supervisor-controller`, `ca-specialist`, `ca-approver`, `ca-signer`, `ca-group-head`, `territorial-specialist`, `territorial-group-head`, `territorial-approver`, `territorial-signer`, `observer`, `sysadmin` (у последнего все домены `none`, доступ через `is_staff/is_superuser`).
- `MeSerializer.roles` отдаёт фронту `[{code, name, scope, department}]`.

Уровни `APPROVE/SIGN` соответствуют действиям ТЗ «Согласовать/Подписать»; `DECIDE` — решениям по исполнению (табл. 45 «Решение аудитора»). Объектных прав (автор, участник маршрута) в prof нет.

**ЭВГА-фронт**: 10 ролей `Role = auditor | reviewer | approver | quality | kvga | reestr-confirmer | invited-specialist | object | appeal-head | appeal-expert`; объектные права: `ownerRole/ownerId` версии, `canEdit`, `canDecideDocument`, участие в `ApprovalRoute`, назначения на дело (`qualityAssignment.ts`, `appeals.ts`).

**n8n**: роли из Keycloak-токена (`User Login Sync`: `token_roles` из `realm_access`), портал-подсистема `evga` с `adminRole 'admin_evga'` и префиксом групп `/evga` (`Keycloak Subsystem Access`), проверка `portal.roles/role_permissions/permissions` с условиями `subsystemKeys`; `allowed_roles` в Zeebe-действиях (`audit_object` и др.).

**Рекомендация**: reuse модель `Role/RolePermission/RoleAssignment/HasDomainLevel/ScopedQuerySetMixin`; `PermissionDomain` заменить на `audit`, `quality`, `registry`, `appeal`, `execution`, `cabinet`; `PermissionLevel` дополнить `confirm`; `seed_roles` под 10 ролей фронта + `sysadmin`; объектные права — в сервисах (`assert_can_edit(version, user)`, `assert_route_step(route, user)`), как `assert_checklist_editable` в prof; `_assert_department_in_scope` перенести в `accounts/querysets.py`.

### 2.10 Справочники / НСИ

**ТЗ**: типы полей «Справочник» в табл. 5, 10, 13, 17, 30, 38, 45: тип субъекта (АО, ПАО, ПОБ, ОПСБ, ОПИ, ПО), регион, КО (микро/малый/средний/крупный), категория риска, контролирующий орган («НСИ государственных органов»), предмет проверки («НСИ ЕРСОП»), категория РСП, категория/степень нарушения, степень риска, способ ознакомления, источник/канал поступления.

**prof** (`prof-be/catalogs/`): абстрактные `CodeNamedModel(code unique, name)` / `OrderedCodeNamedModel(+order)`; `Region(code, number, name_ru, name_kk)` — 20 регионов; `Department(code, name, region, is_central)` — ЦА + 20 ДВГА (`clean`: территориальное требует регион); `GovernmentBody` (КВГА МФ РК, реквизиты бланка `letterhead_kk/ru`); `SubjectTypeRef` (6 типов); `BusinessCategory` (4); `ViolationSeverity` (грубое/значительное/незначительное); `RiskDegree` (3); `InspectionSubjectMatter(code, name, subject_type)` — «плейсхолдер, не подтверждено аналитиком» (по сообщению сида); `NormativeAct(code, title, approved_at, source_url, edition_label)`; `ControlEligibilityRule` (периодичность контроля, `current()`). Сид `seed_catalogs` идемпотентен (`update_or_create`). Read-only API для справочников в prof нет (фронт хранит копии в `prof-fe/data/*`).

**ЭВГА-фронт**: справочники зашиты в `evga/src/data/*` (см. отчёт `reports/evga-domain-model.md`, разд. 4). **n8n**: десятки воркфлоу `EVGA: * - Get` (`Dictionaries`, `Control Spheres`, `Control Reasons Type`, `Audit Type`, `Check Initiator`, `Check Type`, `Controlling Org`, `Risk Category`, `Offense Type`, `Organ Reg Check`, `Organizational Legal Forms`, `Response Measure`, `Risk Object Type`, `Sampling Methods`, `Employees`, `Audit Questions`), таблицы `surfk.d_*`/`surfk.evga_*` (например `surfk.evga_legal_basis_audit(code, name_ru, name_kz)`, `surfk.d_query_check_npa(query_check_code, code)`, `surfk.audit_types.ersop_code`).

**Рекомендация**: оставить `Region/Department/GovernmentBody/NormativeAct` и базовые абстракции; добавить справочники ЭВГА по образцу `OrderedCodeNamedModel` с двуязычными полями `name_ru/name_kz` (в prof двуязычие только у `Region`), с полями `ersop_code` там, где нужен маппинг в ЕРСОП (`audit_types.ersop_code`, `query_check_code/npa_code`); завести read-only `CatalogViewSet` (`/api/catalogs/<name>/`), которого в prof нет.

### 2.11 Версии

**ТЗ**: версии №1/№2 полугодового перечня (табл. 6–7, `project-decisions.md` «Изменение утверждённого списка»); для документов версии не предусмотрены (документ один на тип, «возврат на доработку в статус „Проект“»).

**prof**: `semiannual/models.py::SemiannualListVersion(semiannual_list, version_number ∈ {1,2}, status NOT_FORMED→DRAFT→APPROVED→FORMED, submitted/approved/formed_at/by)`, указатель `SemiannualList.current_version`, сервисы `submit_version/approve_version/form_version/create_version_2`. `ControlDocument` версий не имеет: `UniqueConstraint(list_entry, document_type)`.

**ЭВГА-фронт**: `AuditDocument.versions[]`, `activeVersion(doc)` = последняя, `documentVersionId = "{doc.id}:v{n}"`, создание следующей версии из `Активный | Направлен на согласование КК | Согласован`, ревизии после возврата/отклонения, `sourceVersions` у заключений КК и доп. поручений, `amendmentTargets`. Повторяемые виды (`repeatableKinds`, 19 видов).

**Рекомендация**: rewrite — `Document(case, document_type, number, parent/sequence)` + `DocumentVersion(document, version_number, status, values JSONB, is_active, supersedes, created_by…)`; уникальность `(document, version_number)`; паттерн переходов «`status` + `*_at/*_by`» и указатель `current_version` взять из `SemiannualListVersion`.

### 2.12 Печатные формы

**ТЗ**: печатные формы уведомления, акта о назначении (без файлов-приложений в PDF — `RQ.SAQ.PC.03.05`), ПЛ (отдельно от акта — `RQ.SAQ.PC.04.13`), ст. 155, акта о результатах (приложение 17 — `RQ.SAQ.PC.05.01`), предписания (приложение 18 — `RQ.SAQ.PC.06.01`); в кабинете «печатные формы, идентичные формам на стороне аудитора» (`RQ.SAQ.PC.08.01`); у карточки 1-П печатной формы нет (табл. 18).

**prof**: бэкенд PDF не генерирует (grep `pdf|reportlab|weasy|docx` по `backend/` — пусто); `DocumentType.is_printable` — только признак. Фронт: `prof-fe/components/OfficialPrintForm.tsx` собирает HTML-бланк (казахско-русская шапка КВГА) для `officialDocumentIds = {notice, appointment-act, checklist, article-155, result-act, prescription}` из `details` сериализаторов (`NoticeDetailsSerializer`, `AppointmentActDetailsSerializer`, `ResultActDetailsSerializer`, `PrescriptionDetailsSerializer` с вычисляемыми `appointment_act_number`, `control_period_start/end`, `inspector_name`…), печать — браузером. Полугодовой список выгружается в Excel (`prof-fe/utils/semiannualListExcel.ts`).

**ЭВГА-фронт**: `pdfExport.ts` (pdfmake, A4, поля 20 мм) конвертирует DOM-узлы `.evga-reference-print, .quality-print, .evga-document-print`; официальные бланки не подтверждены (открытый вопрос Q20 в `evga/docs`).

**n8n/ЕРСОП**: в пакет ЕРСОП кладётся `files[{fileName, mimeType 'application/pdf', fileLang 'kz', fileDesc, fileBase64}]` — **файл документа обязателен на стороне сервера**.

**Рекомендация**: для документов, уходящих в ЕРСОП (карточка, доп. поручение, талон), и для кабинета объекта нужен серверный рендер: HTML-шаблон (Django templates) → PDF (WeasyPrint или аналог) → `Attachment(kind="signed_pdf")` при подписании/активации; для остальных — оставить клиентскую печать. Сериализаторы `details` prof — образец состава полей печатной формы.

### 2.13 Статус дела, ошибки API, пагинация

- `cases/models.py::ControlCase` — `status` как `@property` → `cases/services/case_status.py::compute_status(case)` (6 статусов `CaseStatus`, совпадают с табл. 52), `entry_status(list_entry)` — «Ожидает уведомление» пока дела нет; кэш `case.document(code)`. Для ЭВГА полезен тот же приём для `stage`, `quality[]`, `executionState`.
- `core/exceptions.py::exception_handler` оборачивает все ошибки DRF в `{type, title, status, detail, code, …field errors}`; бизнес-ошибки сервисов (`DocumentTransitionError`, `ListTransitionError`) в view превращаются в `serializers.ValidationError({"detail": str(exc)})` → HTTP 400 с русским текстом. `JsonNotFoundMiddleware` и `handler404/500` дают JSON на `/api/*`.
- `core/pagination.py::PageNumberPaginationWithPageSize` (`PAGE_SIZE=25`, `page_size` ≤ 200); фильтры `filterset_fields`, `search_fields`, `ordering` в viewsets (`cases/api/filters.py`, `semiannual/api/filters.py`).

---

## 3. Сопоставление документов prof (12) и ЭВГА (36 + 7)

### 3.1 Источники

- prof: `prof/docs/specs/document-matrix.md` — 12 печатных документов дела (уведомление; акт о назначении; учётная карточка; дополнительный акт; протокол об отказе в принятии акта; аудиторские доказательства; акт о результатах; возражение; результаты рассмотрения возражения; предписание; ответ о принятых мерах; талон-уведомление). В коде: `prof-be/documents/management/commands/seed_document_types.py` — 9 `DocumentType` (`notice`, `appointment-act`, `card-1-p`, `checklist`, `explanatory-note`, `article-155`, `evidence`, `result-act`, `prescription`); `prof-fe/data/documentMatrix.ts` — id `notice`, `appointment-act`, `checklist`, `registration-card`, `article-155`, `additional-act`, `evidence`, `result-act`, `prescription`, `measures-response`; `prof-fe/data/documentStatusRoutes.ts` — дополнительно `explanatory-note`, `closure-card`. Замечание: в сиде `is_implemented=False` у `result-act` и `prescription`, хотя сервисы `documents/services/result_act.py` и `prescription.py` реализованы — флаг устарел, копировать его в ЭВГА не следует.
- ЭВГА: `evga/src/data/documentMatrix.ts::docKinds` (36) и `counterDocKinds` (7); подробная таблица по каждому виду — в `reports/evga-domain-model.md` §3.2–3.3. M-коды старой реализации взяты из `n8n/all_workflows_raw.json` и `bpmn/bpmn_summary.txt` (`'M5-IPI'`, `'M6-PA-S'/'M6-PA-F'`, `'M7-POR'`, `'M8-PLAN'`, `'M9-AZ'`, `M10-QC1`, `M11` (учётная карточка, упоминается в `evga/docs`), `M13` (ВАП), `M14` (доп. поручение), `'M17-AO-S'/'M17-AO-F'`, `'M18-RNS'/'M18-RNAFO'`, `'M19-AD'`, `'M20-VOZ'`, `'M21-AKO'`, `'M23-RVO'`, `'M24-AZK'`, `'M25-PRED'`, `M26-TU`, `'M28-OPM'`, `'M39-ADM-PROT'`, `'M43-VK-POR'`).
- Коды разделов постановки ЭВГА, указанные в задании («талон 3.9», «возражение 2.6», «результаты 2.7», «ответ о принятых мерах 3.3»), в репозиториях **не найдены** (`grep` по `evga/docs/*.md` пуст) — они относятся к документу «ПЗ по модулю ВГА ЭВГА», которого в выгрузке нет; ниже приводятся как ссылка на задание.

### 3.2 Таблица соответствий

| № prof | Документ prof (матрица) | Код prof (бэкенд/фронт) | Модели/сервисы prof | Аналог в ЭВГА (`kind`, M-код, код ПЗ по заданию) | Тип соответствия | Что наследовать |
|---|---|---|---|---|---|---|
| 1 | Уведомление | `notice` | `ControlDocument`+`NoticeDetails`, `create_notice/approve_notice/send_notice` (создаёт дело и номера), `Acknowledgement` | Прямого аналога нет. Ближайшие: **`instruction` (Поручение, M7-POR)** как первый документ, направляемый объекту после регистрации карточки (`deliverable`), и `vap` (Уведомление в ВАП, M13) — иное назначение | концептуальный | Схему «Согласовать → Направить → Ознакомлен» (`send_*` + `record_acknowledgement`) для `deliverDocument("send"/"acknowledge")`; выдачу исходящего номера через `issue_number` |
| 2 | Акт о назначении профилактического контроля | `appointment-act` | `AppointmentActDetails` (место, уполномоченные лица, эксперты «Не привлекаются», предмет, инвестор, правовые основания, плановое окончание, проверяемый период, подписант), `create/approve/sign_appointment_act`, обязательные файлы `REQUIRED_ATTACHMENT_KINDS` | **`instruction` (Поручение на проведение аудиторского мероприятия, M7-POR)** + **`assignment` (Аудиторское задание, M9-AZ)**; встречная проверка — `counter-instruction` (M43-VK-POR) | прямой (поручение = распорядительный акт о назначении) | Паттерн `*Details` с полями «сроки/период/рабочая группа/подписант»; проверку обязательных вложений перед согласованием; авто-создание зависимых документов при подписании (в ЭВГА — `dependencies`: `account: [instruction, quality1]`) |
| 3 | Учётная карточка (1-П) | `card-1-p` (`registration-card` на фронте) | Авто-документ без `*Details` (`Card1PDetailsSerializer` собирает поля из акта и дела), статусы `READY → ACCEPTED`, позиция пакета №1 `ErsopPositionKind.CARD_1P` | **`account` (Учетная карточка ЕР СОП, M11)**, `counter-account`; в n8n — `surfk.evga_doc_registration_card` + `evga_doc_rc_work_group` | прямой | Регистрационную цепочку `ErsopPackage → submit → register` (в ЭВГА — регистрация отдельного документа, статусы `Отправлена/Зарегистрирована/Возвращена`); в ЭВГА карточка — **редактируемая форма** (8 секций, 47 полей), поэтому `*Details`/JSONB, а не авто-проекция |
| 4 | Дополнительный акт (продление срока) | `additional-act` (только фронт; бэкенда нет) | — | **`additional` (Дополнительное поручение, M14)**, `counter-additional`; повторяемый, регистрируется в ЕРСОП, `applyAmendment` порождает версии связанных документов | прямой | Ничего из бэкенда prof; из матрицы — правило «дополнительный срок не превышает первоначальный» как валидация |
| 5 | Протокол об отказе в принятии акта | — (только матрица) | — | **`obstruction` (Акт о воспрепятствовании)** / `counter-obstruction` (Акт об отказе в доступе); отказ объекта от подписи отчёта — `delivery.decision = "Отказ от подписания"` | концептуальный | Модель `DocumentDelivery.decision` (новая, см. 2.6) |
| 6 | Аудиторские доказательства | `evidence` (`creation_mode=attachment`, `is_implemented=False`) | `AttachmentKind.AUDIT_EVIDENCE`, `checklists/services/attachments.py`, поле `CaseChecklistItem.evidence_text` | **`evidence` (Аудиторские доказательства, M19-AD)** — документ со строками по нарушению (`violationId, violationType, consequence, amount, evidence, documentDetails, source` + файлы) | прямой по смыслу, разный по форме | `Attachment` для файлов; строки — в JSONB версии |
| 7 | Акт о результатах | `result-act` | `ResultActDetails`, `create_result_act` (после `complete_checklist`), `approve_result_act` (требует ≥1 пункт нарушения — `has_completable_violation`), `sign_result_act` (порождает предписание), `send_result_act`; содержательная часть — `CaseChecklist/CaseChecklistItem/CaseChecklistViolation` | **`report` (Аудиторский отчёт, M17-AO-S/M17-AO-F)** + **`violations` (Реестр нарушений, M18-RNS/M18-RNAFO)**; итог — `conclusion` (Аудиторское заключение, M24-AZK); встречная — `counter-act` | прямой (акт = отчёт + реестр) | Правило «акт недоступен без пункта нарушения» → «предписание/ответ зависят от `effectiveViolations`»; «блокировка листа после согласования акта» (`assert_checklist_editable`) → «источник неизменен после `sourceVersions`»; дробление нарушения на пункты (`CaseChecklistViolation.order`) → строки реестра `violations[]` |
| 8 | Возражение к акту о результатах | — (вне границ ТЗ; только матрица) | — | **`objections` (Возражения к аудиторскому отчёту, M20-VOZ; по заданию — п. 2.6 ПЗ ЭВГА)**; владелец `object`; активация создаёт `audit.appeal`; Zeebe-процесс `evga_doc_51` с таймером `P10D` | прямой | Кабинетный паттерн создания документа субъектом (`CabinetRegisterSubmissionView`) |
| 9 | Результаты рассмотрения возражения | — (только матрица) | — | **`objection-result` (M23-RVO; по заданию — п. 2.7)**; согласующие — члены комиссии, утверждает `commission-chair`, направляет `appeal-expert` | прямой | Ничего из бэкенда; нужна модель комиссии/маршрута |
| 10 | Предписание об устранении нарушений | `prescription` | `PrescriptionDetails`, `generate_prescription` (из подписанного акта), `execution.PrescriptionItem(violation, risk_degree, recommendation, due_date, order)`, `generate_prescription_items` (severity → `RiskDegree`), `approve_prescription` (все пункты с рекомендацией и сроком), `sign/send_prescription`; статусы до `IN_EXECUTION/EXECUTED` | **`prescription` (Предписание на устранение нарушений, M25-PRED)**; строки `financial[]`/`procedural[]` по `effectiveViolations` (`violationId, riskType, riskObject, paragraph, deadline, amount, recover, restoreWork, restoreAccounting`) | прямой | `PrescriptionItem` как отдельная таблица пунктов (не только JSON), `effective_due_date`, вычисляемый `status`, правило «согласование только при заполненных сроках/рекомендациях» |
| 11 | Ответ о принятых мерах | `measures-response` (фронт); бэкенд — `execution.ExecutionSubmission/ExecutionSubmissionItem` | `register_submission(source ∈ {subject-cabinet, inspector-registration}, channel, author, items[{item, measures, completion_date, attachment}])`, `decide_item(kind ∈ {RELEASE, EXTEND})`, `_mark_prescription_executed_if_complete` | **`response` (Ответ о принятых мерах, M28-OPM; по заданию — п. 3.3)**; строки `measures[]` (`violationId, accepted, status[4], date, letterNumber…`), `recommendations[]`, новая редакция после утверждения (`createResponseRevision`); исполнение — `shared/execution` (`claimedStatus/confirmedStatus`, `extensions`) | прямой | `ExecutionSubmission` + `ExecutionDecision` как хранилище фактов и решений; в ЭВГА добавить связь с версией документа-ответа |
| 12 | Талон-уведомление | `closure-card` (фронт, статусы «Готова к отправке → Отправлена → Принята ЕРСОП»); бэкенд — пакет №2 (`ErsopPackage kind=2`, `PACKAGE_2_APPROVAL_STEPS`) | `build_package_2/approve_package_2_step/submit_package_2/register_package_2` | **`notification` (Талон-уведомление, M26-TU; по заданию — п. 3.9)**, `counter-notification`; регистрируется в ЕРСОП (`messageType Finished` в n8n `SEND_REQ_TO_ERSOP::build Finished` с `TalonQuery{CheckQueryCode, CheckThemeCode}`); регистрация встречного талона закрывает дело | прямой | `ErsopExchange` и цепочку статусов; вместо счётчика согласований — `ApprovalRoute` |
| + | Электронный проверочный лист | `checklist` | `ChecklistTemplate/ChecklistItem` (6 шаблонов по типу субъекта), `CaseChecklist/CaseChecklistItem/CaseChecklistViolation`, сервисы `checklists/services/checklist.py` | Аналога нет; частично — вопросы `program.questions[]` / `assignment.questions[]` и реестр `violations` | косвенный | Приёмы: `assert_*_editable`, `draft_saved_at/completed_at`, generic-вложения на строку |
| + | Статья 155 | `article-155` | Авто-документ `SENT` при регистрации пакета №1 | Аналога нет | — | — |
| + | Пояснительная записка | `explanatory-note` (`creation_mode=attachment`) | `AttachmentKind.EXPLANATORY_NOTE` | Вложения к `instruction`/`account` | косвенный | `Attachment.kind` |

Документы ЭВГА без аналога в prof (нужно проектировать заново): `irpi` (M5-IPI), `program` (M6-PA-S/F), `plan` (M8-PLAN), `quality1/2/3` (M10-QC1…), `vap` (M13), `request` (требование сведений), `weekly`, `measurement`, `forward-*`/`reply-*`, `claim-*`, `completion`, встречные `counter-request/counter-act`, 62 рабочих документа (`workingDocKinds`).

### 3.3 Дело и сквозные сущности

| prof | ЭВГА | Вердикт |
|---|---|---|
| `cases.ControlCase(list_entry 1:1, number, responsible, notice_sent_at, started_on, closed_at)`; статус вычисляется | `AuditCase(number "30101-YY-seq", object, bases[], group[], stage, quality[], documents[], history[], appeal, parentCaseId…)` | rewrite модели, reuse паттерн `status`-property и `case.document(code)` |
| `subjects.Subject(bin, name, subject_type, business_category, legal_form, registration_*, actual_region, department, last_control_date, gbd_synced_at)`, `SubjectPerson(iin, role_kind)`, валидаторы БИН/ИИН | `AuditObject{bin, ru, kz, director, opf, abp, address, region, risk, score}`; ФЛ для встречной проверки (ИИН, ФИО, дата рождения) | adapt: + `name_kk`, `opf`, `abp`, `director`, `risk/score` |
| `semiannual.SemiannualListEntry` как «строка перечня → дело» | основание дела `Basis` (план/внеплан, документ-основание) | rewrite |
| `catalogs.Department` + `RoleAssignment.department` (территориальный скоуп) | `Person.organization`, штатное расписание для согласующих | adapt |

---

## 4. Интеграции, общие для prof и ЭВГА

### 4.1 ЕРСОП / КПСиСУ

**ТЗ prof** (табл. 50, 2.6, 2.10): два пакета; результат — регистрационный номер/дата акта и идентификатор обмена; дата регистрации = дата начала контроля; заглушка в прототипе.

**prof-бэкенд** (`prof-be/ersop/`):

| Элемент | Реализация |
|---|---|
| `ErsopPackage(case, kind ∈ {1,2}, status DRAFT→SUBMITTED→REGISTERED/ACCEPTED, submitted_at/by, registration_number, registration_date, accepted_at, package_2_approved_steps)` | `UniqueConstraint(case, kind)` |
| `ErsopPackageItem(package, position_kind, document, is_ready, blocking_reason, order)` | 7 `ErsopPositionKind`: `notice-ack`, `appointment-act`, `card-1-p`, `checklist`, `explanatory-note`, `result-act`, `prescription` |
| `ErsopExchange(package, direction IN/OUT, exchange_id, request_payload, response_payload, occurred_at)` | журнал обмена (табл. 49 «идентификатор обмена») |
| `services/package_1.py::build_package_1` | пересчитывает 5 позиций (табл. 24): ознакомление с уведомлением (`notice.acknowledgements.exists()`), акт в статусе ≥ `SIGNED`, карточка, ПЛ, файл `EXPLANATORY_NOTE`; при полной готовности акт → `READY` |
| `submit_package_1` | блокирует при `is_ready=False` (текст «Пакет не укомплектован: …»), акт → `IN_ERSOP`, ПЛ → `IN_PACKAGE_1`, пакет → `SUBMITTED` |
| `register_package_1` | вызывает `stub_exchange.fake_register_package`, пишет `ErsopExchange(IN)`, `case.started_on = registration_date`, карточка → `ACCEPTED`, акт → `REGISTERED` (`external_number`, `external_registered_at`) → `SENT`, ПЛ → `SENT`, создаёт `article-155` в `SENT` (правило табл. 25 п. 01–02) |
| `services/package_2.py` | `build_package_2` (акт о результатах + предписание при наличии, готовность = `ACKNOWLEDGED|IN_PACKAGE_2`), `approve_package_2_step` (счётчик до 5), `submit_package_2` (документы → `IN_PACKAGE_2`), `register_package_2` (пакет `ACCEPTED`, предписание → `IN_EXECUTION`) |
| `services/stub_exchange.py::fake_register_package(package)` | без сети; `exchange_id = registration_number = issue_number("ersop-package-1"/"-2")`, `status: registered/accepted`, `registration_date = today` |
| API `/api/ersop/` | `packages/build-package-1/`, `packages/build-package-2/`, `packages/<id>/approve-step/`, `packages/<id>/submit/`, `packages/<id>/register/` (регистрация — отдельный POST, имитирующий асинхронный ответ ЕРСОП) |

**Старая реализация ЭВГА (n8n)** — реальный контракт, который нужно перенести:

| Элемент | Где | Содержание |
|---|---|---|
| Входная точка | `EVGA ERSOP Workflow` (`n8n/workflows/EVGA_ERSOP_Workflow__cyKRwRgN5AUhCaZ0.json`), webhook `POST evga/ersop` | `body.action ∈ {send_to_ersop, check_status}`, `params{document_id, user_iin, user_fullname, signature}`, JWT в `Authorization` |
| Отправка | узлы `Validate send_to_ersop` → `Call ERSOP Send API` (`/webhook/ersop/send-document`) → `UPDATE surfk.evga_case_documents SET status_id = (code='sent_to_ersop')` → `INSERT surfk.evga_document_approvals(status='sent_to_ersop', comments='Подписан ЭЦП и отправлен в ЕРСОП')` → Zeebe-событие `send_to_ersop` | статус документа `sent_to_ersop`, запись в журнал |
| Сборка тела | `ERSOP - Build and Send from Document`: `Load Document` (`surfk.evga_doc_registration_card` ⋈ `evga_case_documents` ⋈ `cases` ⋈ `audit_types.ersop_code` ⋈ `d_query_check_npa` ⋈ `evga_doc_preliminary_study` M5-IPI), `Load Legal Basis` (`evga_legal_basis_audit`), `Load Work Group` (`evga_doc_rc_work_group`), `Load Attachment` + `Download File Base64`, `Build ERSOP Body` | тело: `{systemId:'10002', requestId: uuid, docId, requestDate, messageType:'M_TYPE_STARTED', message.started{number(≤21), organCode, typeCheckCode, typeAuditCode, checkDate, beginDate, endDate, periodBegin, periodEnd, oraganCodeKPSSU, shortFabula/shortFabulaKz, faces[{iin, lastName, firstName, middleName, positionRU/KK/QAZ, organizationNameRU/KK/QAZ, phone, mobile}], checkQuery{checkQueryCode:'0'+query_check_code, checkThemeCode:'0'+npa_code}, files[{fileName, mimeType, fileLang:'kz', fileDesc, fileBase64}], SubjectInfo{subjectId, bin}, ObjectInfo{objId}, userCreate, userSign}}`; текущий пользователь и телефоны — `MOCK` («TODO: replace with real data») |
| Транспорт | `SEND_REQ_TO_ERSOP` (webhook `ersop-requset`): SOAP `POST http://tstpi.emf.minfin.kz:57000/XISOAPAdapter/MessageServlet?…interface=SI_SUR2ERSOP_RequestSubjectAsync&interfaceNamespace=http://minfin.kz/ERSOP`, `Switch` по `messageType` с XML-сборщиками `Started`, `Prolonged`, `PeriodChanged`, `Resumed`, `Suspended`, `Stoped`, `ExecutorChanged`, `Finished` (талон: `TalonQuery`), элементы `Notice/SystemId/RequestId/RequestDate/MessageType/Message`, `Faces/Person/UserCreate/UserSign/FilesContent`; запрос сохраняется в `acc_100.rspns_msg_rsp(id = requestId||'R', account_id = docId, object_data jsonb, app_name 'EVGA')` |
| Ответ | асинхронный callback (`ersop-callback` воркфлоу) в ту же таблицу; `getErsopResponse` (webhook `getErsop?requestId=`) ищет `object_data->>'noticeid'/'messageid'`; `EVGA ERSOP Workflow::check_status` → `Parse ERSOP Status` (`successful`, `error`), `Is ERSOP Pending?` → «ЕРСОП ещё не вернул финальный ответ», иначе `UPDATE … status_id = code(new_status_code)` и запись `evga_document_approvals` с комментарием («Зарегистрирован в ЕРСОП» и др.); коды действий `ersop_registered`, `ersop_accepted`, `ersop_revision`, `ersop_rejected`, `ersop_error` |

**ЭВГА-фронт**: `workflow.ts::performRegistration(doc, actor, action ∈ {send, accept, return}, comment, registrationNumber)` — только для `account`, `counter-account`, `notification`, `counter-notification`, `additional`, `counter-additional`; только из статуса `Активный`; `return` требует комментарий и переводит версию в «Возвращен на доработку»; запись в историю «Учёт регистрации: …»; демо-номер `ТЕСТ-30101-26-52972-05`.

**Как применить в ЭВГА**: приложение `integrations` (или `ersop`) по образцу prof:

```python
class ExternalRegistration(TimeStampedModel):           # аналог ErsopPackage, но на версию документа
    version = OneToOne("documents.DocumentVersion")
    system = CharField(choices=[("ersop", "ЕРСОП/КПСиСУ")])
    message_type = CharField(choices=["Started","Prolonged","PeriodChanged","Suspended","Resumed","Stoped","ExecutorChanged","Finished"])
    status = CharField(choices=["DRAFT","SENT","REGISTERED","RETURNED","REJECTED","ERROR"])   # = Отправлена/Зарегистрирована/Возвращена
    request_id = CharField(unique)  # ← requestId / exchange_id
    registration_number, registration_date, return_comment
class ExternalExchange(TimeStampedModel):               # = ErsopExchange без изменений
    registration = FK; direction IN/OUT; exchange_id; request_payload JSON; response_payload JSON; occurred_at
```

Сервисы: `build_registration_payload(version)` (порт `Build ERSOP Body` — состав полей выше, файл из `Attachment` → base64), `submit_registration(version, by)` (статус `SENT`, `ExternalExchange(OUT)`, событие `AuditAction.EXCHANGE`), `apply_registration_result(registration, result)` (`REGISTERED/RETURNED`, при возврате версия → `RETURNED` как в `performRegistration`), `poll_registration(registration)` (порт `check_status`). Адаптер выбирается настройкой `ERSOP_ADAPTER = "stub" | "soap"`; `stub` — порт `fake_register_package` (номер из `NumberSequence`, ответ «сразу» или по отдельному POST `/register/` как в prof), `soap` — порт `SEND_REQ_TO_ERSOP` (httpx, XML). Готовность (аналог `ErsopPackageItem.is_ready/blocking_reason`) считать функцией `registration_block(version)` → список причин (нет активной версии, нет PDF, нет рабочей группы, нет `ersop_code` у типа аудита).

### 4.2 ГБД ЮЛ / ГБД ФЛ

**ТЗ prof** (табл. 50): состав данных ЮЛ (БИН, наименование, ОПФ, дата/статус регистрации, юридический адрес, учредители, руководитель) и ФЛ (ИИН, ФИО, роль по отношению к субъекту) «в составе, доступном по интеграционному контракту». Табл. 5: «БИН — источник: ГБД ЮЛ». **ЭВГА** (`specification-baseline.md`): ГБД ЮЛ заполняет наименование/ОПФ/форму собственности/вид деятельности объекта (О/НР), ГБД ФЛ — ФИО и дату рождения для встречной проверки ФЛ.

**prof-бэкенд**: заглушки нет. `subjects.Subject` содержит поля-приёмники (`legal_form`, `registration_date`, `registration_status`, `registration_address`, `gbd_synced_at`) и `SubjectPerson(role_kind ∈ {founder, head, representative})`; данные приходят из импорта DFO (`reporting/services/dfo_import.py`) и сида. Валидаторы БИН/ИИН с контрольной суммой — `subjects/validators.py` (`bin_validator`, `iin_validator`, `checksum_validator`).

**n8n**: `Service GDBJL surfk` (не активен), `EVGA: Audit Object - Search by BIN`, `EVGA: Audit Objects - Get` — поиск по локальной таблице объектов; **ЭВГА-фронт**: `ObjectLookup` по тестовому `catalogue` (3 БИН + 4 плановых).

**Как применить**: `subjects/services/gbd.py` с интерфейсом `lookup_legal_entity(bin) -> dict | None`, `lookup_person(iin) -> dict | None` и двумя адаптерами: `StubGbdAdapter` (справочник из `data/gbd_stub.json`, содержащий состав полей табл. 50) и `ShepGbdAdapter` (на будущее). Эндпоинт `GET /api/subjects/lookup/?bin=` возвращает состав полей, фронт подставляет их в форму дела (поля НР). Результат сохраняется в `Subject` с `gbd_synced_at`; `SubjectPerson` — для руководителя/учредителей.

### 4.3 Keycloak / OIDC

**ТЗ prof**: только «пользователь авторизован» (предусловия); табл. 50 Keycloak не упоминает. **ЭВГА**: «SSO/единая авторизация» (`specification-baseline.md`, «Интеграции»).

**prof-бэкенд** (`prof-be/accounts/`): полноценный OIDC Authorization Code + PKCE: `services/keycloak.py` (`get_discovery_document` с кэшем 6 ч, `build_authorization_url` со `scope=openid profile email`, `S256`, `exchange_code_for_tokens`, `refresh_access_token`, `decode_id_token` через `PyJWKClient` с проверкой `aud/iss/nonce`, `provision_user_from_claims` — `FederatedIdentity(issuer, subject_claim)` → `User(username=f"kc_{sub}")`, ошибка `EmailAlreadyLinkedError`); `api/keycloak_views.py` (`/api/auth/keycloak/login|callback|logout`, `OidcAuthRequest(state, code_verifier, nonce, redirect_target)` с TTL 10 мин, ошибки в `?auth_error=`); сессия — собственная cookie `saq_session` (`AuthSession` с токенами, `authentication.py::SessionCookieAuthentication` обновляет access token по refresh, локальные сессии живут 12 ч); параллельно локальный вход `/api/auth/local/*` (для представителей субъекта и dev). Настройки `KEYCLOAK_ISSUER/CLIENT_ID/CLIENT_SECRET/REDIRECT_URI/POST_LOGOUT_REDIRECT_URI` в `.env`; при пустом `KEYCLOAK_ISSUER` остаётся локальный вход (`deploy/.env.example`). Роли из Keycloak **не** берутся — только `RoleAssignment` в БД.

**n8n**: `User Login Sync` (webhook `user-login-surfk`): декодирует JWT (в коде отмечено «подпись и exp здесь не проверяются»), требует 12-значный ИИН в `preferred_username`, `INSERT … surfk.users(keycloak_user_id, origin_user_id, iin, fullname, given_name, family_name, email, email_verified, last_login_at) ON CONFLICT (iin) DO UPDATE`, роли — из токена (`token_roles`), ответ содержит `controlling_body_code/name_ru/kz`, `roles[]`. `Keycloak Subsystem Access`: подсистема `evga` (`adminRole 'admin_evga'`, группы `/evga`, префикс ролей), проверка прав через `portal.roles/role_permissions/permissions` с `conditions.subsystemKeys`, аудит в RabbitMQ.

**Как применить**: reuse `accounts` целиком. Дополнить `provision_user_from_claims`: сохранять `iin` (из `preferred_username`, валидатор `iin_validator`), `position`, `department` (по claim `department`/группе), и опционально синхронизировать `RoleAssignment` из `realm_access.roles` с префиксом `evga_` (маппинг «код роли Keycloak → `Role.code`» в настройках). Оставить локальный вход для кабинета объекта и тестов. Имя пользователя в журнале — `User.full_name` (в n8n — `performed_by_iin/name`).

### 4.4 ЭЦП

**ТЗ prof**: «ЭЦП… подлежат детализации на этапе промышленной интеграции» (раздел 3); матрица MVP — «Утвердить» вместо ЭЦП. **ЭВГА** (`specification-baseline.md`): «Согласование и утверждение выполняются с ЭЦП»; фронт хранит `signatures[{person, at, role}]` без криптографии.

**prof-бэкенд**: подписи как факта нет — `ControlDocument.is_signed/signed_at/signed_by` и статус `SIGNED`; уровень прав `PermissionLevel.SIGN`.

**n8n/BPMN**: параметр `signature` в `send_to_ersop`; `requires_signature: true/false` на действиях Zeebe; `userSign` в теле ЕРСОП (ИИН, ФИО, должность, орган, телефон) — т.е. ЕРСОП ожидает данные подписанта, а не CMS.

**Как применить**: см. 2.5 — модель `DocumentSignature` с `provider ∈ {stub, ncalayer}`; в MVP действие «Подписать» создаёт запись `provider=stub`; поле `cms_payload` и сервис проверки (`verify_cms`) добавляются при промышленной интеграции; `userSign` для ЕРСОП берётся из `DocumentSignature.signer` (`User.full_name/position/phone`, `Department`/`GovernmentBody.code` как `organCode`).

---

## 5. Рекомендации по оформлению постановки и документации бэкенда ЭВГА в стиле команды

### 5.1 Что есть в эталоне

| Файл prof | Назначение | Структура |
|---|---|---|
| `README.md` (151 строка) | Точка входа | Состав проекта (`frontend/`, `backend/`, `docker-compose.yml`, `deploy/`, `docs/`, `scripts/dev/`, `backend/data/`); требования; контейнерный запуск (`docker compose --env-file deploy/.env up --build -d`); локальная разработка (venv, `.env`, `migrate`, **перечень seed-команд**: `seed_catalogs`, `seed_roles`, `seed_number_sequences`, `seed_document_types`, `seed_report_forms`, `seed_checklists`, `seed_risk_rules`); локальный вход (`admin/admin`, роль `list-officer-inspector`); маршруты фронта; группы API (`/api/auth/`, `/api/subjects/`, …, `/api/cabinet/`); проверка (`typecheck`, `build`, `manage.py check`, `pytest`); сброс БД; остановка |
| `docs/specs/document-matrix.md` (45 строк) | Матрица документов | Абзац об основаниях (НПА, образцы); «Принятые решения MVP» (8 пунктов); сводная таблица `№ / Документ / Этап / Автор / Основные поля / Источник полей / Утверждение / Статусы / PDF / Интеграция`; нормативные источники (ссылки adilet.zan.kz); замечания по образцам |
| `docs/architecture/project-decisions.md` (86 строк) | Зафиксированные проектные решения | Тематические разделы с нумерованными правилами: «Единый процесс», «Отчётность объектов», «Начальное состояние демонстрации», «Распределение», «Проверочный лист», «Изменение утверждённого списка», «Повторное открытие», «Объяснимость результата СУР», «Временные допущения» |
| `docs/release-notes/2026-07-30.md` (4 пункта) | Изменения по датам | Маркированный список пользовательских изменений |
| `docs/tor/Postanovka_obshhaya.docx` | Исходное ТЗ | копия постановки |
| `docs/back_risks/123.xlsx` | Реестр рисков | — |
| Swagger `/api/docs/` (`drf_spectacular`, `SPECTACULAR_SETTINGS.TITLE = "SAQ — Профилактический контроль API"`) | Живая спецификация API | `extend_schema(description=…)` на каждом action-view с русским описанием перехода («Проект → Согласовано. Применимо к …») |

Документация ЭВГА-фронта (`evga/docs/`, 30+ файлов) шире: `specification-baseline.md` (трассировка требований, журнал расхождений), `architecture.md`, `full-process.md` (сквозной тестовый процесс, «Что имитируется», «Оставшиеся вопросы»), `bpmn-*.md`, `user-answers-*.json`, `stand-verification.xlsx`, `figma-reference/`. Её надо не дублировать, а **ссылаться** из документации бэкенда.

### 5.2 Предлагаемый состав `docs/` бэкенда ЭВГА

| Файл | Содержание | Образец |
|---|---|---|
| `README.md` | Разделы как в prof; группы API `/api/auth/`, `/api/subjects/`, `/api/catalogs/`, `/api/evga/cases/`, `/api/evga/documents/`, `/api/evga/routes/`, `/api/evga/quality/`, `/api/evga/execution/`, `/api/integrations/`, `/api/cabinet/`; seed-команды `seed_catalogs`, `seed_roles`, `seed_number_sequences`, `seed_document_types`, `seed_form_schemas`, `seed_working_papers`, `seed_calendar`; локальные учётки для ролей `auditor/reviewer/approver/quality/kvga/object` | `prof/README.md` |
| `docs/specs/document-matrix.md` | «Принятые решения MVP» (утверждение вместо ЭЦП, регистрация ЕРСОП как заглушка, кабинет объекта в той же SPA, версии документов, повторяемые виды, рабочие дни); таблица по 36+7 видам: `№ / kind / M-код / Наименование / Этап (0/1/2) / Владелец (ownerRole) / Маршрут (подготовительный, основной, обычный, прямая активация, КК) / Повторяемый / Направляется объекту / ЕРСОП / КК / Версии-источники / Основные поля (секции формы) / Печатная форма / Интеграция`; отдельная таблица рабочих документов (62); нормативные источники; замечания по образцам | `prof/docs/specs/document-matrix.md` + `reports/evga-domain-model.md` §3 |
| `docs/specs/status-matrix.md` | Таблица «Статус (код / метка) / Условие установления» в формате табл. 12/16/33/37 ТЗ — по группам видов (подготовительные, основные, КК, прямая активация, регистрируемые); отдельные таблицы для `RegistrationStatus`, `DeliveryDecision`, статусов маршрута (`review/signing/completed/superseded`), состояний исполнения; таблица действий `action → уровень прав → из статуса → в статус → побочные эффекты → запись журнала` | табл. 12–37, 52 ТЗ; `DocumentStatus` + `_STATUS_LABEL_OVERRIDES` |
| `docs/specs/api-actions.md` | Перечень action-эндпоинтов по образцу `documents/api/urls.py` (`<id>/submit/`, `/approve/`, `/return/`, `/reject/`, `/recall/`, `/activate/`, `/sign/`, `/send/`, `/acknowledge/`, `/register/`, `/new-version/`), тело запроса, коды ошибок (`creation_blocked`, `stale_version`, `forbidden_route_step`, `comment_required`) в конверте `core/exceptions.py` | `prof-be/documents/api/urls.py`, Swagger |
| `docs/specs/fields/<kind>.md` (или одна `document-fields.md`) | Таблицы полей в формате ТЗ: `№ / Поле / Тип / Обязательность (Да/Нет/Условно/Автоматически) / Редактируемость (Р/НР) / Комментарий-источник` — по секциям формы (`general`, `questions[]`, …) | табл. 13/17/34/38 ТЗ; `specification-baseline.md` «Поля форм встречной проверки» |
| `docs/architecture/project-decisions.md` | Разделы: «Единый процесс и этапы» (Stage 0/1/2, `quality[]`); «Версии документов» (правила `createNextVersion`, неизменяемость утверждённых, `sourceVersions`); «Маршрут согласования» (последовательный, возврат/отклонение/отзыв, замена); «Подпись вместо ЭЦП»; «Регистрация в ЕРСОП» (заглушка, ручной ответ, `return`); «ГБД» (заглушка); «Кабинет объекта»; «Права и назначения»; «Нумерация»; «Журнал действий»; «Сроки и производственный календарь»; «Хранение форм (JSONB vs таблицы)»; «Временные допущения» | `prof/docs/architecture/project-decisions.md` |
| `docs/architecture/integrations.md` | Таблица в формате табл. 50 ТЗ (`Система / Направление / Состав данных / Результат`) для ЕРСОП (по типам сообщений `Started…Finished` с составом полей из 4.1), ГБД ЮЛ/ФЛ, Keycloak, ЭЦП, ВАП, кабинет; для каждой — «адаптер `stub` / адаптер prod», контрольные точки (формат табл. 51) | табл. 50–51 ТЗ; `prof-be/ersop` |
| `docs/architecture/data-model.md` | ER-описание приложений (`core`, `accounts`, `catalogs`, `subjects`, `audits`, `documents`, `workflow`, `quality`, `requests`, `appeals`, `execution`, `integrations`, `cabinet`) с указанием, что унаследовано из prof | `reports/prof-backend-style.md` §10 |
| `docs/release-notes/YYYY-MM-DD.md` | По одному файлу на релиз, 3–10 пунктов пользовательским языком | `prof/docs/release-notes/2026-07-30.md` |
| `docs/tor/` | `Postanovka_obshhaya.docx` (prof — как источник сквозных требований), ПЗ ЭВГА и постановка «Встречная проверка» (когда будут получены) | `prof/docs/tor/` |
| `docs/questions.md` или `docs/back_risks/` | Открытые вопросы заказчику с номерами (Q-коды, как в `evga/docs/user-answers-2026-09-06.json`), риски | `prof/docs/back_risks/123.xlsx`, `specification-baseline.md` «Журнал расхождений» |

### 5.3 Стиль постановки для бэкенда ЭВГА (если готовится ПЗ)

- Шифры требований `RQ.SAQ.EVGA.<NN>.<MM>` по функциям (01 — дело и объект, 02 — документы и версии, 03 — маршрут согласования, 04 — контроль качества, 05 — регистрация ЕРСОП, 06 — доставка объекту и кабинет, 07 — исполнение, 08 — возражения, 09 — интерфейс и журналирование, 10 — интеграции), колонка «Новое/изменённое» относительно фронта `saq-evga-test`.
- На каждую функцию — четыре таблицы ТЗ prof (сценарий ВИ, ФТ, статусы, поля) + «Правила процесса»; действующие лица — из 10 ролей фронта + «SAQ» + «ЕРСОП» + «Объект аудита».
- Термины: «объект аудита» (не «субъект контроля»), «Активный» (не «Утверждён»), «Направить»/«Направлен» — для доставки объекту (`RQ.SAQ.PC.09.04`), «Отправлена/Зарегистрирована/Возвращена» — для ЕРСОП.
- Формат дат в тексте — `ДД.ММ.ГГГГ`, время `ДД.ММ.ГГГГ, ЧЧ:ММ`; сроки — в рабочих днях с указанием НПА (как в `evga/src/modules/evga/deadlines.ts`).
- Состав записи журнала — табл. 49 ТЗ без изменений плюс поле `source` (`user/system/ersop/timer`).

---

## 6. Открытые вопросы

1. **Регистрация в ЕРСОП: пакеты или документы.** prof регистрирует пакеты (табл. 24, 40), ЭВГА — отдельные документы (`account`, `additional`, `notification` + встречные) с типами сообщений `Started/Prolonged/…/Finished`. Нужно подтвердить у заказчика, что для ЭВГА принимается модель «регистрация на версию документа» и какие M-коды (M11, M14, M26, встречные M44/M47 — последние два в репозиториях не найдены) подлежат регистрации.
2. **PDF для ЕРСОП.** n8n отправляет `fileBase64` документа; prof PDF на сервере не делает. Требуется решение: серверный рендер (WeasyPrint/иное) или загрузка PDF, сформированного фронтом (`pdfmake`), как вложения `signed_pdf` перед отправкой.
3. **Коды разделов ПЗ ЭВГА** (2.6, 2.7, 3.3, 3.9 из задания) не подтверждены документами репозитория — нужен сам файл ПЗ ЭВГА для точной трассировки и для `docs/tor/`.
4. **ЭЦП в ЭВГА.** ПЗ требует ЭЦП при согласовании и утверждении; prof-подход «Утвердить» принят только для prof-MVP. Подтвердить, допустима ли заглушка `provider=stub` для первого релиза бэкенда ЭВГА и кто именно является `userSign` для ЕРСОП (утверждающий или автор карточки).
5. **Часовой пояс.** prof: `TIME_ZONE="UTC"`; ЭВГА-фронт и ЕРСОП: `Asia/Almaty`/`+05:00`; сроки в рабочих днях. Зафиксировать `TIME_ZONE="Asia/Almaty"` и хранение сроков как `DateField`.
6. **Роли из Keycloak или из БД.** prof — только `RoleAssignment`; n8n — роли из токена. Выбрать источник истины (предложение: БД, синхронизация из токена при входе как опция).
7. **Коды статусов/действий.** Фронт ЭВГА использует русские строки как коды; n8n — латинские (`draft`, `active`, `send_to_ersop`…). Согласовать таблицу соответствия до генерации `TextChoices`, чтобы `status_label` совпадал со строками фронта.
8. **Журнал: справочник действий или enum.** n8n хранит `surfk.evga_document_action_types(code, name_ru)`; prof — `AuditAction` enum из 7 значений. Для ЭВГА нужно ~30 кодов (см. 2.4) — выбрать enum (проще) или таблицу (гибче, двуязычно).
9. **ГБД-заглушка.** Состав полей табл. 50 ТЗ prof vs. поля объекта ЭВГА (`ru/kz/opf/abp/director/address/region`) — согласовать единый контракт `lookup_legal_entity`.
10. **Флаги `DocumentType.is_implemented`/`is_printable` в prof** не соответствуют коду (у `result-act`/`prescription` `is_implemented=False` при наличии сервисов). При сидировании типов ЭВГА держать флаги в актуальном состоянии или вычислять из реестра сервисов.
11. **Номера акта о результатах и предписания.** ТЗ prof требует номера из «регистрационного журнала SAQ» (табл. 34/38), сервисы prof их не выдают. В ЭВГА номера документов `{дело}/{NN}` выдаются при создании — подтвердить, нужен ли отдельный исходящий номер при направлении объекту.
12. **Ограничения файлов.** В prof нет лимитов размера/MIME; ЕРСОП принимает PDF. Определить лимиты и допустимые типы для `Attachment` ЭВГА.

---

## 7. Кандидаты на переиспользование (сводка)

| Элемент prof | Вердикт | Примечание |
|---|---|---|
| `core.TimeStampedModel`, UUID-PK | reuse-as-is | совместимо с `crypto.randomUUID()` фронта |
| `core.AuditEvent`/`AuditAction` | reuse-as-is + расширить | добавить коды действий ЭВГА и `source`; **начать реально писать** из сервисов (`record_event`) |
| `core.Attachment`/`AttachmentKind`, `files.py::sha256_of`, MinIO-настройки, download-view | reuse-as-is + новые kind | добавить лимиты MIME/размера |
| `core.NumberSequence`/`IssuedNumber`, `numbering.py::issue_number`, `seed_number_sequences` | reuse-as-is | шаблоны `30101-{yy}-{seq:04d}`, `{case_number}/{seq:02d}` (scope = дело) |
| `core.exceptions.exception_handler`, `JsonNotFoundMiddleware`, `core/views.py`, `PageNumberPaginationWithPageSize` | reuse-as-is | коды ошибок ЭВГА в `code` |
| `accounts` (User, AuthSession, OidcAuthRequest, FederatedIdentity, `services/keycloak.py`, `authentication.py`, local/keycloak views, `MeSerializer`) | reuse-as-is | добавить `iin`, синхронизацию ролей из токена (опция) |
| `accounts.Role/RolePermission/RoleAssignment/HasDomainLevel/ScopedQuerySetMixin`, `_assert_department_in_scope` | adapt | домены `audit/quality/registry/appeal/execution/cabinet`, уровень `confirm`, 10 ролей фронта + `sysadmin`; helper перенести в `accounts/querysets.py` |
| `documents.DocumentType` + `seed_document_types` | adapt | сидировать 36+7(+62) видов с `kind`, `legacy_code` (M-код), `stage`, `owner_role`, `route_kind`, `is_repeatable`, `deliverable`, `registers_in_ersop`, `requires_quality`, `depends_on` |
| `documents.DocumentStatus` + `_STATUS_LABEL_OVERRIDES` + `document_status_label` | adapt | 11 статусов ЭВГА, метки = строки `DocStatus` |
| `documents.ControlDocument` + `*Details` + `UniqueConstraint(list_entry, document_type)` | rewrite | `Document` + `DocumentVersion` (JSONB `values`), уникальность `(document, version_number)`; паттерн `*_at/*_by` сохранить |
| `documents.Acknowledgement` + `record_acknowledgement` | reuse-as-is | привязать к версии; добавить `DocumentDelivery.decision` |
| `documents/services/*` (функции переходов с `DocumentTransitionError`, `select_for_update`, `@transaction.atomic`) и `documents/api/views.py` (один `APIView` на действие + словарь диспетчеризации по типу) | reuse паттерн | тела функций — порт `workflow.ts`/`documentStateMachine.ts`/`preparationWorkflow.ts`/`mainWorkflow.ts` |
| `documents/api/serializers.py::DETAILS_SERIALIZERS`, `details` в `ControlDocumentSerializer`, контекст `{"cabinet": True}` | reuse паттерн | сериализатор печатных реквизитов на вид документа |
| `cases.ControlCase.status` (property) + `case_status.py` | adapt (паттерн) | `stage`, `quality[]`, `executionState`, «Открыто/Закрыто» |
| `subjects.Subject/SubjectPerson` + `validators.py` (БИН/ИИН) | adapt | + `name_kk`, `opf`, `abp`, `director`, `risk/score`; сервис `gbd.py` со stub-адаптером |
| `catalogs` (`Region`, `Department`, `GovernmentBody`, `NormativeAct`, абстракции, `seed_catalogs`) | adapt | + справочники ЭВГА с `name_ru/name_kz` и `ersop_code`; read-only API |
| `ersop.ErsopExchange` + `stub_exchange.py` + цепочка `build → submit → register` | adapt | `ExternalRegistration` на версию документа; адаптеры `stub`/`soap` (порт n8n `SEND_REQ_TO_ERSOP`, `Build ERSOP Body`) |
| `ersop.ErsopPackage.package_2_approved_steps` + `PACKAGE_2_APPROVAL_STEPS` | drop | заменить на `ApprovalRoute/ApprovalStep` |
| `cabinet` (`IsSubjectRepresentative`, `_assert_subject_owns`, `CabinetDocumentViewSet`, `CabinetAcknowledgeView`, `CabinetRegisterSubmissionView`, download-views) | adapt | + решения объекта, ответы на требования, возражения, третьи лица |
| `execution.PrescriptionItem/ExecutionSubmission/ExecutionSubmissionItem/ExecutionDecision` + `register_submission/decide_item/_mark_prescription_executed_if_complete` | adapt | статусы под `claimedStatus/confirmedStatus` фронта; связь с версией `response` |
| `checklists` (`assert_checklist_editable`, `draft_saved_at/completed_at`, `CaseChecklistViolation` как «пункт нарушения») | drop (приёмы — adapt) | прообраз строк реестра нарушений |
| `semiannual.SemiannualListVersion` (цепочка статусов, `current_version`, однократная корректировка) | adapt (паттерн) | образец для `DocumentVersion` |
| `reporting`, `risk`, `semiannual` (процессы ПК) | drop | — |
| `prof-fe/components/OfficialPrintForm.tsx` (HTML-бланки) | adapt как шаблон | перенести в серверные Django-шаблоны для PDF ЕРСОП/кабинета |
| `prof/docs/*` (структура матрицы, решений, release-notes, README) | reuse структуру | см. раздел 5 |
| n8n `surfk.evga_audit_log` (состав, `source`, дедупликация), `Build ERSOP Body` (состав полей), `SEND_REQ_TO_ERSOP` (SOAP/XML по типам сообщений), `User Login Sync` (ИИН из `preferred_username`) | adapt (перенос в Python) | единственный источник реального контракта ЕРСОП |
