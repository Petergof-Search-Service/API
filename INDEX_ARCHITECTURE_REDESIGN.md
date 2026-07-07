# Редизайн архитектуры индексации (векторные индексы AI Studio)

> **Статус: РЕАЛИЗОВАН Вариант A** (см. §3-A, §5). Решения по §7: 1 uvicorn-воркер; поллер в VM
> (in-API, `lifespan`); низкий RPS / редкие сборки; удаление индекса **запрещено пока `building`**
> (не отмена). Изменённые файлы: миграция `alembic/.../c1a2b3d4e5f6_add_index_build_status.py`,
> `app/db/models/org_index.py`, `app/db/schemas/index.py`, `rag/create_index.py` (+`rag/__init__.py`),
> `app/api/v1/endpoints/index.py`, `app/core/index_poller.py`, `app/core/config.py`, `app/main.py`;
> FE `CreateIndex.js`, `api/DeleteIndex.js` (удалён `api/CheckIndexRunning.js`). §1 ниже описывает
> состояние **до** редизайна; актуальную сводку по реализованному см. в корневом `CLAUDE.md`.

Все утверждения о поведении **до редизайна** подкреплены ссылками на код. Ось «индексации» —
отдельная от файлового пайплайна (`pending_upload → … → indexed`); здесь речь про сборку
**поискового индекса** (vector store в Yandex AI Studio) из уже проиндексированных файлов и его
использование в чате.

---

## 1. Текущая архитектура (по коду)

### 1.1. Флоу создания

```
FE CreateIndex.js (админ, /create_index)
  │  POST /api/v1/indexes {name, file_ids}         ── ответ (200) игнорируется
  ▼
index.py:create_index()
  │  if index_task:  → 409                          ── модуль-глобальный флаг (index.py:32)
  │  index_task = True
  │  asyncio.create_task(background_task())          ── fire-and-forget, ссылка теряется (index.py:135)
  │  return 200                                      ── СРАЗУ, не дожидаясь сборки
  ▼
background_task()  (та же asyncio-петля, тот же процесс API)
  │  manager.send(user_id, {index_status: running}) ── WebSocket (in-memory, per-process)
  │  chunks = _get_chunks_names_for_ids(file_ids)    ── file_ids → {stem}.chunks.jsonl
  │  filenames2ids = rag.get_files_names2ids()       ── AI Studio client.files.list()
  │  yandex_file_ids = [...]
  ▼
rag.create_index(name, yandex_file_ids)  (API/rag/create_index.py)
  │  vs = client.vector_stores.create(name, file_ids, expires_after=30d last_active_at)
  │  vector_store_id = vs.id                          ── ★ id известен СРАЗУ, синхронно
  │  while True:                                      ── ★ BUSY-POLL, без таймаута
  │     vs = client.vector_stores.retrieve(id); sleep(3)
  │     if vs.status != "in_progress": break
  │  return {name, vector_store_id, status}
  ▼
_save_index_to_db(org_id, name, vector_store_id)      ── ★ строка OrgIndex пишется ТОЛЬКО ТЕПЕРЬ
  │  manager.send(user_id, {index_status: done, index:{...}})
  │  finally: index_task = False
```

Ключевые ссылки: `API/app/api/v1/endpoints/index.py:32,69-137`, `API/rag/create_index.py:7-42`,
`API/app/core/ws.py`, WS-эндпоинт `API/app/api/v1/endpoints/files.py:276`.

### 1.2. Модель данных (что durable)

Таблица `indexes` — модель `OrgIndex` (`API/app/db/models/org_index.py:10-21`), **ровно 5 колонок**:

| колонка | тип | примечание |
|---|---|---|
| `id` | Integer PK | |
| `org_id` | Integer FK→organizations.id | NOT NULL; в миграции `b3e7f1a2c4d9` — `ondelete=CASCADE` (в модели ondelete не указан) |
| `name` | String | NOT NULL |
| `vector_store_id` | String | NOT NULL — внешний id стора в AI Studio |
| `created_at` | DateTime(tz) | server_default now() |

**Колонок `status` / `progress` / `error` / `task_id` / `updated_at` НЕТ.** Единственное
durable-состояние индекса — *факт существования готовой строки*. «Идёт ли сборка» в БД не
хранится вообще: `GET /indexes/status` (`index.py:156-165`) читает in-memory флаг `index_task`,
а не БД. Схема `IndexRecord` (`schemas/index.py:15-20`) отдаёт только `id/name/created_at`.

### 1.3. Как индекс потребляется

Чат обязан прислать `index_id` в теле запроса (`schemas/rag.py: RagQuestion.index_id`).
`POST /answer` (`endpoints/rag.py:41-43`) грузит `OrgIndex` по PK, проверяет `org_id`, и его
`vector_store_id` уходит в `client.vector_stores.search` (`rag/main.py:157`). Привязки индекса к
чату в БД **нет** — выбор индекса чисто по-запросный (FE хранит выбор в `localStorage`,
`Frontend/src/components/Chat.js`). Значит: удалили строку/стор или истёк TTL → `POST /answer`
даёт `404 Index not found` или ошибку поиска в AI Studio.

### 1.4. Какие операции над индексами есть сейчас

| метод | путь | доступ | что делает |
|---|---|---|---|
| GET | `/api/v1/indexes` | member | список индексов орг из БД (`index.py:55`) |
| POST | `/api/v1/indexes` | **admin** | запускает async-сборку (`index.py:69`) |
| GET | `/api/v1/indexes/status` | admin | in-memory флаг «still/not running» (`index.py:156`) |
| GET | `/api/v1/rag-files` | admin | файлы орг со `status='indexed'` для выбора (`index.py:140`) |

**Нет** `DELETE`, `PUT/PATCH` (переименование), reindex по индексам — нигде в API. В `API/rag/`
**нет `vector_stores.delete`** (есть только `vector_stores.files.delete` в `delete_file.py`).
Индексы и vector stores накапливаются. FE удаления индекса не имеет
(`Frontend/src/api/` — `axios.delete` только по членам орг, чатам, файлам).

### 1.5. Доставка статуса на FE

FE **не поллит**; `CreateIndex.js` открывает WebSocket `/api/v1/ws?token=…` и реагирует на
`{type:"index_status", status: running|done|error}`. На `done` — префиксом добавляет индекс в
список. `GET /indexes/status` и `Frontend/src/api/CheckIndexRunning.js` — **dead code** (нигде не
импортится). Единственный «guard» от параллельной сборки на FE — кнопка disabled по флагу
`processing`.

### 1.6. Диагноз: что именно ломается

- **Busy-wait воркера.** Сборка идёт на стороне AI Studio; наша asyncio-таска висит минуты—часы,
  лишь опрашивая `retrieve` каждые 3с (`create_index.py:26-36`). CPU почти не ест (это `await
  sleep`), но держит задачу в event loop и, главное, **держит `index_task=True`**.
- **Не переживает редеплой.** `app/main.py` пуст (нет `lifespan`/startup). Рестарт контейнера →
  корутина гибнет, `index_task` сбрасывается в `False` при реимпорте, строка `OrgIndex` не
  создаётся → **осиротевший** vector store в AI Studio (чистится только 30-дневным TTL), FE
  «done» никогда не получает. Нет reconciliation.
- **Глобальный флаг, не per-org.** Одна сборка любой орг блокирует создание у всех (409). Если
  сборка зависла в `in_progress` — флаг `True` навсегда, заклинивает до рестарта. Работает лишь
  потому, что uvicorn — **1 воркер** (нет `--workers` в `API/Dockerfile:37`,
  `Infra/docker-compose.yml:35`). При `--workers>1`/репликах сломаются и флаг, и WS-менеджер
  (оба per-process, in-memory).
- **Потерянная ссылка на таску.** `asyncio.create_task(...)` без сохранения ссылки — риск GC/
  отмены таски (`index.py:135`).
- **Опасная связность файлов и индексов.** `DELETE /files/{id}` → `rag.delete_rag_file`
  (`files.py:266`, `rag/delete_file.py:29-37`) идёт по **всем** vector store в каталоге и вырезает
  чанки файла из каждого → молча деградирует все индексы, где файл участвовал.
- **Нет lifecycle-менеджмента.** Ни удаления, ни переименования, ни ретрая, ни переиндексации,
  ни TTL-политики на нашей стороне. Vector stores копятся против квоты AI Studio (150 индексов).

### 1.7. Что подтвердилось / чего нет в AI Studio (важно для дизайна)

- **Вебхуков/пуша о готовности индекса НЕТ.** Проверено по докам Yandex AI Studio и по факту, что
  OpenAI (которого AI Studio зеркалит) не имеет vector-store-completion вебхука. **Единственный
  способ узнать готовность — поллинг** `vector_stores.retrieve`. Событийная («push при готовности»)
  архитектура невозможна.
- `retrieve` отдаёт `status` (`in_progress`/`completed`/`expired`; про `failed` — см. риск ниже) и
  `file_counts{in_progress,completed,failed,cancelled,total}` — это и есть **прогресс** для UI.
- `vector_stores.create` возвращает `id` **синхронно** — стор существует сразу, в `in_progress`
  (`create_index.py:23`). → Можно писать durable-строку немедленно.
- `vector_stores.delete` **поддерживается** (удаление стора, в т.ч. в процессе сборки), плюс
  «Cancel a vector store file batch». → Удаление/отмена реализуемы.
- TTL: `expires_after {anchor: last_active_at|created_at, days: 1–365}`; после истечения стор
  удаляется автоматически. Возвращаются `expires_at`, `last_active_at`.
- Лимиты: **150 индексов** (квота, до 1000 максимум), 10000 файлов/индекс, **10 RPS на
  векторизацию**. Отдельный RPS-лимит на `retrieve` не документирован; длительность сборки —
  без SLA.
- YC managed-примитивы для поллера, что команда уже использует: **timer (cron) триггеры** для
  Functions/Serverless Containers (как Watchdog), **Message Queue (YMQ)** триггеры с
  visibility-timeout и DLQ, Serverless **Workflows** (Preview). Workflows умеет только загрузку
  файлов в vector store, **не** ожидание готовности → всё равно нужен поллинг.

> ⚠️ **Риск по статусу `failed`.** Схема `retrieve` документирует `in_progress/completed/expired`,
> а концептуальная страница упоминает `failed`. Неясно, приходит ли ошибка сборки как
> `status="failed"` или только через `file_counts.failed>0` при незавершающемся `in_progress`.
> **Дизайн обязан** трактовать «ошибку» как: `status in {failed}` ИЛИ (`file_counts.failed>0`) ИЛИ
> `in_progress` дольше таймаута. Подтвердить эмпирически на живом сторе.

---

## 2. Цели редизайна (маппинг на 4 требования)

| # | Требование | Инвариант, который вводим |
|---|---|---|
| 1 | Без busy-waiting | Строка индекса создаётся **сразу** (id из `create`), а продвижение статуса делает **декуплированный поллер**, не держащий воркер/запрос. |
| 2 | Удаление с FE | `DELETE /indexes/{id}` + `vector_stores.delete`; определённое поведение для «в процессе». |
| 3 | Прогресс на FE | Durable `status`+`file_counts` в БД; FE узнаёт через polling `GET /indexes` (+опц. WS). |
| 4 | Устойчивость к редеплою | Состояние **только в Postgres**; восстановление = поллер сам подхватывает `building`-строки. Startup-recovery «бесплатно». |

**Общее ядро всех вариантов** (без него ни один не закрывает требования):

1. **Расширить таблицу `indexes`** (durable-статус): добавить
   `status ENUM/String` (`queued|building|ready|failed|deleting|deleted`),
   `file_counts JSONB` (или `progress_done`/`progress_total` int),
   `error_message TEXT NULL`, `source_file_ids JSONB` (снапшот выбранных file_ids — для
   retry/reindex), `updated_at`, `expires_at TIMESTAMPTZ NULL`, `created_by INT NULL`.
   `vector_store_id` сделать `NULL`able (на очень раннем этапе `queued` он ещё не получен).
2. **POST /indexes создаёт строку немедленно** со `status=building` и `vector_store_id` (из
   `vector_stores.create`), возвращает `IndexRecord` (id+status), НЕ ждёт сборку. `index_task`
   глобальный флаг **удаляется**; конкуррентность — на строках (`SELECT … FOR UPDATE SKIP
   LOCKED`), а не на процессе.
3. **Поллер** периодически берёт строки в `status=building`, зовёт `retrieve`, обновляет
   `status/file_counts/error_message`, при завершении шлёт нотификацию (WS best-effort).
   *Где живёт поллер — единственное, чем отличаются варианты ниже.*
4. **DELETE /indexes/{id}**: `vector_stores.delete(vector_store_id)` + перевод строки в
   `deleted` (или физическое удаление). Для `building`: удаление стора **отменяет** сборку.
5. **Startup/redeploy**: поскольку `building` живёт в БД, любой перезапуск поллера просто
   продолжает reconciliation. Отдельный «recovery» код не нужен — это свойство схемы.
6. **Развязать удаление файла и индексы**: `DELETE /files/{id}` не должен молча резать чанки из
   всех сторов (см. §6, отдельная правка `rag/delete_file.py`).

---

## 3. Варианты архитектуры

### Вариант A — Минимальный: durable-статус + in-API поллер (в рамках VM+API)

Никаких новых компонентов. Поллер — фоновая asyncio-петля, поднятая в **FastAPI `lifespan`**
(либо APScheduler `AsyncIOScheduler`), в том же контейнере API.

```
POST /indexes ─► create row(status=building, vs_id) ─► vector_stores.create ─► 200 {id,status}
                         │
        (тот же контейнер, отдельная петля)
        lifespan poller  ─── каждые N сек ───►  SELECT … WHERE status='building' FOR UPDATE SKIP LOCKED
                         │                       for each: client.vector_stores.retrieve(vs_id)
                         │                       update status/file_counts; if done → WS notify
                         ▼
        redeploy: петля стартует заново из lifespan, берёт те же building-строки → recovery
FE: GET /indexes каждые 3–5с пока есть building  (WS оставляем как best-effort ускорение)
DELETE /indexes/{id} ─► vector_stores.delete ─► row→deleted
```

- **Меняется/добавляется:**
  - Миграция alembic: колонки статуса на `indexes` (см. §2.1).
  - `endpoints/index.py`: переписать `POST /indexes` (немедленная строка, без глобального
    флага), добавить `DELETE /indexes/{id}`, `PATCH /indexes/{id}` (rename), обновить
    `GET /indexes` и `IndexRecord` (отдавать `status`, `progress`). Удалить `GET
    /indexes/status` (или оставить как no-op для совместимости).
  - `rag/create_index.py`: разбить на `create_vector_store()` (только `create`, возвращает id) и
    убрать busy-loop; добавить `retrieve_status()`, `delete_index()` (`vector_stores.delete`).
  - Новый модуль `app/core/index_poller.py` + запуск в `app/main.py` через `lifespan`.
  - `Frontend`: `CreateIndex.js` — polling `GET /indexes` + кнопка «Удалить» (`DeleteIndex.js`);
    per-row статус/прогресс. WS можно сохранить.
- **Trade-offs:**
  - ✅ Ноль новой инфры, дешевле всего, весь код в одном репо, легко тестировать.
  - ✅ Закрывает все 4 требования.
  - ⚠️ Поллер в процессе API. При **`--workers>1`/репликах** нужен лидер: спасает `FOR UPDATE
    SKIP LOCKED` (несколько поллеров не подерутся за строки) — но лучше запускать петлю условно
    (advisory-lock `pg_try_advisory_lock`, чтобы крутилась одна). Сегодня 1 воркер → тривиально.
  - ⚠️ Если API «прилёг» целиком — поллер тоже стоит (но и создавать индексы некому). Приемлемо.
- **Покрытие требований:** 1 ✅ (поллер не в запросе; можно даже `retrieve` в отдельном
  `asyncio.to_thread`/семафоре) · 2 ✅ · 3 ✅ (polling) · 4 ✅ (состояние в БД, lifespan-рестарт).

### Вариант B — Managed: вынесенный поллер как YC timer-функция (паттерн Watchdog)

Поллер уезжает из API в **облачную функцию `index-poller`** с **timer-триггером** (cron, напр.
раз в минуту), ровно как `Watchdog`. Функция ходит в ту же БД (или через сервисный эндпоинт),
зовёт `retrieve`, и **обновляет статус тем же контрактом сервис-ключа**, что и остальные функции.

```
POST /indexes ─► create row(status=building, vs_id) ─► vector_stores.create ─► 200
        (API больше НЕ поллит — только создаёт строку и стор)

[YC timer cron ~1/min] ─► index-poller (Function)
        │  берёт building-индексы:  либо SELECT из Managed PG,
        │                           либо GET /indexes/service (новый, под x-service-key)
        │  client.vector_stores.retrieve(vs_id) для каждого
        │  PATCH /indexes/by-id/status {system_key/index_id, status, file_counts, error}
        ▼
API применяет PATCH → пишет в БД → (опц.) WS notify залогиненному админу
FE: GET /indexes polling  ·  DELETE /indexes/{id} как в A
```

- **Меняется/добавляется:** всё ядро из §2 **плюс** новый репозиторий/функция `index-poller`
  (по образцу `Watchdog/`), timer-триггер (`yc-sls-function`), новый сервисный контракт
  `PATCH /indexes/by-id/status` (+ `require_service_key`, по аналогии с
  `PATCH /files/by-key/status`) и/или `GET /indexes/service`. `endpoints/index.py`: `POST`
  только создаёт; поллер-петли в API нет.
- **Trade-offs:**
  - ✅ Полностью развязано с жизненным циклом API: редеплой/скейл API никак не влияет на сборку.
  - ✅ Горизонтально масштабируемо (функция сама по себе; `SKIP LOCKED`/идемпотентный PATCH).
  - ✅ Единый паттерн с OCR/RAG/Watchdog (сервис-ключ, статусы, CI `yc-sls-function`).
  - ⚠️ +1 деплой-юнит, +триггер, +секрет доступа функции к БД или к сервисному эндпоинту.
  - ⚠️ Гранулярность cron: статус обновляется не чаще периода таймера (напр. до ~1 мин лага) —
    для «минуты—часы» сборок это ок.
- **Покрытие:** 1 ✅ (поллинг вне API-воркеров) · 2 ✅ · 3 ✅ · 4 ✅✅ (сборка вообще не зависит
  от процессов API).

### Вариант C — Event/queue-driven: YMQ + функция-консьюмер (self-rescheduling)

Как B, но вместо cron-скана всей таблицы — **очередь YMQ**. На `POST /indexes` кладём сообщение
`{index_id, vs_id, attempt}`. Функция-консьюмер (YMQ-триггер) поллит **один раз**; если ещё
`in_progress` — кладёт сообщение обратно с задержкой (delay/visibility-timeout) → само-
перепланирование; после N попыток/таймаута → DLQ → пометить `failed`.

```
POST /indexes ─► create row ─► vector_stores.create ─► YMQ.send{index_id,vs_id,attempt=0} ─► 200
        ▼
YMQ ──trigger──► index-poll-consumer (Function)
        │  retrieve(vs_id)
        │  completed → PATCH status=ready ; failed → PATCH status=failed
        │  in_progress → PATCH progress ; re-enqueue{attempt+1} с delay=15–30с
        │  attempt>MAX → DLQ → PATCH status=failed(timeout)
```

- **Меняется/добавляется:** ядро §2 **плюс** YMQ-очередь(+DLQ), функция-консьюмер, YMQ-триггер,
  тот же сервисный PATCH-контракт. `POST /indexes` дополнительно шлёт в YMQ.
- **Trade-offs:**
  - ✅ Максимально durable/надёжно: backpressure, ретраи, DLQ для «застрявших», ровно-один-в-работе
    на индекс. Ложится на **уже заведённый тикет про YMQ** (та же MQ-инфраструктура, что для
    OCR-очереди).
  - ✅ Нет «скана всей таблицы» — работает только по активным сборкам, дешевле при росте.
  - ⚠️ Больше всего движущихся частей (очередь, DLQ, идемпотентность, visibility-timeout tuning).
    Оверкилл, если сборок мало и они редкие.
- **Покрытие:** 1 ✅ · 2 ✅ · 3 ✅ · 4 ✅✅✅ (durable-очередь + DLQ + БД).

---

## 4. Сравнение и рекомендация

| Критерий | A: in-API поллер | B: YC timer-функция | C: YMQ + консьюмер |
|---|---|---|---|
| Новые компоненты | нет | +функция, +cron-триггер | +функция, +YMQ, +DLQ, +триггер |
| Сложность внедрения | низкая | средняя | высокая |
| Эксплуатация | низкая (1 контейнер) | средняя (ещё функция) | средняя-высокая |
| Стоимость | ≈0 | низкая (вызовы функции) | низкая (функция+YMQ) |
| Устойчивость к редеплою API | ✅ (lifespan-рестарт) | ✅✅ (независимо) | ✅✅✅ |
| Масштабирование API >1 воркера | нужен advisory-lock/leader | ✅ из коробки | ✅ из коробки |
| Backpressure/ретраи/DLQ | вручную | ограниченно | ✅ нативно |
| Консистентность с OCR/RAG/Watchdog | нет | ✅ полный паттерн | ✅ + MQ-тикет |
| Требования 1–4 | все ✅ | все ✅ | все ✅ |

**Рекомендация (провизорная, зависит от ответов в §7): Вариант A сейчас, спроектированный как
drop-in под B.**

Обоснование:
- A закрывает **все 4 требования** без единого нового компонента; риск и время — минимальные.
  Для музейного масштаба (немного орг, редкие ручные сборки, сегодня 1 uvicorn-воркер) этого
  достаточно.
- Дорогая часть редизайна — **общее ядро §2** (схема БД, немедленная строка, DELETE, polling на
  FE). Оно **идентично** во всех трёх вариантах. Значит A и B отличаются только тем, *где крутится
  цикл `retrieve`*. Если спроектировать статус-контракт сразу «сервисно» (durable в БД,
  идемпотентный апдейт), переезд A→B — это вынести один модуль в функцию и добавить cron-триггер,
  без миграций и без изменения FE.
- B/C оправданы, если (а) API пойдёт в несколько воркеров/реплик, (б) сборки частые/тяжёлые и
  нужна изоляция от API, или (в) команда хочет держать единый serverless-паттерн. C — если уже
  делаете YMQ по тикету и хотите одну общую механику очередей.

**Условие переключения рекомендации:** если ответ на §7-Q1 = «будет >1 воркера/реплики скоро» или
§7-Q2 = «предпочитаем serverless-паттерн» → сразу делать **B** (миновать A). C — только при явной
потребности в очереди/DLQ или если MQ-инфра всё равно вводится.

---

## 5. План внедрения рекомендованного (A, drop-in под B)

Порядок — так, чтобы каждый шаг был обратно совместим и деплоился отдельно.

**Шаг 0. Подтвердить семантику `failed`** на живом сторе AI Studio (см. §1.7 риск): как именно
приходит ошибка сборки. От этого зависит条件 перехода в `failed`.

**Шаг 1. Миграция БД (обратно совместимая).**
- Alembic-ревизия: `ALTER TABLE indexes ADD COLUMN status …DEFAULT 'ready' NOT NULL,
  file_counts JSONB NULL, error_message TEXT NULL, source_file_ids JSONB NULL,
  updated_at TIMESTAMPTZ …, expires_at TIMESTAMPTZ NULL, created_by INT NULL`;
  `ALTER COLUMN vector_store_id DROP NOT NULL`.
- **Миграция существующих индексов:** все текущие строки → `status='ready'` (они по определению
  готовы, раз создавались только после busy-poll). Опционально back-fill `expires_at` и
  `file_counts` разовым проходом `retrieve` по существующим `vector_store_id` (или пропустить —
  не критично). Ничего не ломается: старый `GET /indexes` продолжает отдавать `id/name/created_at`.

**Шаг 2. Сервис-слой `rag/`.**
- Разбить `create_index.py`: `create_vector_store(name, file_ids) -> id` (без цикла),
  `retrieve_index(vs_id) -> {status, file_counts}`, `delete_index(vs_id)`.
- Оставить старую `create_index` как тонкую обёртку на время миграции (совместимость).

**Шаг 3. API-эндпоинты (аддитивно, старые контракты живут).**
- `POST /indexes`: создать строку (`status=building`, `source_file_ids`), вызвать
  `create_vector_store`, записать `vector_store_id`, вернуть `IndexRecord{id,name,status,...}`.
  Убрать глобальный `index_task`. Конкуррентность — по строкам, per-org лимит (если нужен) —
  запросом «есть ли building в этой орг».
- Расширить `IndexRecord`/`GET /indexes`: добавить `status`, `progress` (из `file_counts`),
  `error_message` — **аддитивно** (старые поля на месте, FE не ломается).
- `DELETE /indexes/{id}` (admin, org-scoped): `delete_index(vs_id)` + строка → `deleted`
  (или физически удалить). Поведение для `building` — по ответу §7-Q4.
- `PATCH /indexes/{id}` (rename) — опционально.
- `GET /indexes/status` — оставить как есть на время (dead-код на FE), затем удалить.

**Шаг 4. Поллер (`app/core/index_poller.py`) + `lifespan` в `app/main.py`.**
- Цикл: каждые `INDEX_POLL_INTERVAL` (напр. 5с) `SELECT … WHERE status='building' FOR UPDATE
  SKIP LOCKED LIMIT k`; для каждой — `retrieve_index`; апдейт статуса; правила `failed`
  (§1.7); при завершении — `manager.send` (WS best-effort). Таймаут «застрявших» build
  (`updated_at` старше N) → `failed`. Опц. `pg_try_advisory_lock` чтобы петля крутилась одна.
- **Это и есть recovery:** после редеплоя lifespan снова поднимает петлю, `building`-строки
  подхватываются. Отдельного recovery-кода не требуется.

**Шаг 5. Frontend.**
- `CreateIndex.js`: после `POST /indexes` — не ждать WS как единственный источник; **поллить
  `GET /indexes`** каждые 3–5с, пока в списке есть `building`, рисовать per-row статус/прогресс.
  WS оставить как ускорение (не обязателен для корректности).
- Новый `api/DeleteIndex.js` + кнопка «Удалить» в таблице (подтверждение). Показ `failed` +
  кнопка «Повторить» (см. §6).
- Удалить dead-code `CheckIndexRunning.js`.

**Шаг 6. Развязать удаление файла (отдельный PR, независимо).** Пересмотреть
`rag/delete_file.py`/`files.py:266`: не резать чанки из всех сторов молча. Варианты: (а) хранить
связь файл↔индекс и трогать только релевантные сторы с уведомлением; (б) запрещать удаление файла,
пока он в живом индексе; (в) переиндексация индекса вместо точечной вырезки. Требует продуктового
решения.

**Шаг 7. Переезд на B (если решим по §7).** Вынести `index_poller` в функцию `index-poller`
(шаблон `Watchdog/`), добавить `PATCH /indexes/by-id/status` под `require_service_key`, cron-
триггер. Схема БД и FE **не меняются**. Убрать lifespan-петлю из API.

**Обратная совместимость API:** все изменения §3 аддитивны; существующие
`GET /indexes`, `POST /indexes` (тело `{name,file_ids}`), `POST /answer` (тело с `index_id`)
сохраняют контракт. Ломается только внутреннее поведение (когда пишется строка) — в лучшую
сторону.

---

## 6. Дополнительные фичи (дёшево ложатся на новую схему)

| Фича | Как ложится | Сложность |
|---|---|---|
| **Retry упавших** | `source_file_ids` уже в строке → `POST /indexes/{id}/retry`: `create_vector_store` заново, `status=building`. |低 (S) |
| **Переиндексация** | То же, что retry, но по актуальному набору файлов; старый стор удалить после готовности нового (blue-green). | S–M |
| **TTL/автоудаление сирот** | `expires_at` в БД + `vector_stores.list` sweep в поллере: строки без стора → `deleted`; сторы без строки → удалить. Закрывает «осиротевшие» сторы. | S |
| **Нотификации** | На переход `ready/failed` — WS (есть) + опц. email/тг; durable, т.к. переход виден в БД. | S |
| **История версий индекса** | Не мутировать строку при reindex, а создавать новую версию (`parent_id`/`version`), старую → `superseded`. Чат может пиниться на версию. | M |
| **Привязка индекса к чату** | Колонка `chat.index_id` → чат помнит индекс; удаление индекса не ломает молча (мягкая ошибка/подсказка). Убирает хрупкость §1.3. | S–M |
| **Отмена сборки** | `DELETE` в состоянии `building` = `vector_stores.delete` (отменяет). Уже в ядре. | S |
| **Прогресс-бар** | `file_counts{completed/total}` → процент в UI. Данные уже собираются поллером. | S |
| **Квота-гард** | Перед `create` — `vector_stores.list` count vs лимит 150; предупреждать/чистить. | S |
| **Аудит** | `created_by`/`updated_at` уже в схеме → кто/когда создал/удалил. | S |

---

## 7. Вопросы, которые уточняют финальную рекомендацию

1. **Масштаб API:** останется 1 uvicorn-воркер/1 инстанс, или планируется `--workers>1`/реплики?
   (Определяет: A достаточно, или сразу B.)
2. **Где держать поллер:** минимализм в VM (A) или вынести в YC-функцию по таймеру ради
   консистентности с OCR/RAG/Watchdog и декаплинга (B)?
3. **Масштаб/частота:** сколько индексов и как часто их создают (единичные ручные vs частые/
   пакетные), сколько организаций? (Нужна ли очередь/DLQ — вариант C.)
4. **Удаление «в процессе»:** отменять сборку сразу (удалять стор), запрещать до завершения, или
   ставить в очередь на удаление после готовности?
