# Восстановление alembic после сквоша миграций (без потери данных)

## Что произошло

В рамках API-02 вся цепочка миграций была схлопнута в одну — `alembic/versions/b6bcf27f08c6_initial_schema.py` (`down_revision = None`), а прежние ревизии (старый head — `c1a2b3d4e5f6`) удалены.

На стендах, где alembic уже накатывался, таблица `alembic_version` до сих пор хранит **старую** ревизию (`c1a2b3d4e5f6`). При старте контейнера API выполняется `alembic upgrade head` (см. `Infra/docker-compose.yml`), alembic не находит эту ревизию и падает:

```
Can't locate revision identified by 'c1a2b3d4e5f6'
```

Из-за `command: sh -c "alembic upgrade head && uvicorn ..."` API не стартует. **Нельзя** «чинить» это через `DROP SCHEMA public CASCADE` — это стирает все данные (пользователи, организации, чаты, файлы, индексы). Именно так база и терялась на каждом релизе.

## Правильное лечение: `alembic stamp` (данные сохраняются)

Живая схема прод/тест-БД уже соответствует схлопнутой `b6bcf27f08c6`, поэтому нужно просто переставить указатель alembic на актуальную ревизию, ничего не пересоздавая.

Выполнить **один раз на каждом стенде** (прод и тест — отдельно).

### 0. Бэкап (обязательно)

```bash
cd ~/Petergof/infrastructure          # на тесте: ~/Petergof/infrastructure-test
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > ~/backup-$(date +%F).sql
```

### 1. Сверить схему с миграцией

Миграция `b6bcf27f08c6` включает `UNIQUE(users.email)` и все текущие колонки. Миграции API-01/API-02, которые их добавляли, тоже удалены сквошем и на проде могли не примениться. Проверьте расхождения:

```bash
docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" -c "\d users"
docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" -c "\d indexes"
# дубликаты email (если UNIQUE ещё нет — сначала разрулить их):
docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" \
  -c "SELECT email, count(*) FROM users GROUP BY email HAVING count(*) > 1;"
```

Если чего-то не хватает — догнать вручную перед stamp, например:

```sql
ALTER TABLE users ADD CONSTRAINT uq_users_email UNIQUE (email);
```

### 2. Переставить указатель без потери данных

```bash
docker compose exec -T api alembic stamp --purge head
```

Важно: именно `--purge`. Обычный `alembic stamp head` сначала пытается **резолвить текущую** ревизию из `alembic_version`, а она (`c1a2b3d4e5f6`) удалена — и stamp падает с тем же `Can't locate revision`. `--purge` очищает `alembic_version` и проставляет актуальный head **без выполнения DDL и без изменения данных** (проверено на копии схемы: пользователи/организации остаются на месте).

Крайний случай, если и `--purge` недоступен — проставить версию напрямую:

```bash
docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" \
  -c "DELETE FROM alembic_version; INSERT INTO alembic_version (version_num) VALUES ('a7b3c9d1e2f4');"
```

> `a7b3c9d1e2f4` — актуальный head (после сида организации); `alembic stamp --purge head` подставит его сам.

### 3. Поднять API и проверить

```bash
docker compose up -d api
docker compose logs --tail=50 api        # без ошибок alembic, uvicorn стартовал
docker compose exec -T api alembic current # → a7b3c9d1e2f4 (head)
```

После stamp данные на месте, а будущие `alembic upgrade head` — идемпотентный no-op (см. защиту в `b6bcf27f08c6.upgrade()`).

## Организация «Петергоф»

Отдельная миграция `a7b3c9d1e2f4_seed_petergof_org` идемпотентно создаёт организацию «Петергоф», если её ещё нет (`INSERT ... ON CONFLICT (name) DO NOTHING`). На стенде, где организация уже есть, миграция ничего не меняет.

Сид создаёт только организацию. Чтобы сделать зарегистрированного пользователя её владельцем:

```sql
-- узнать id
SELECT id FROM users WHERE email = 'admin@example.com';
SELECT id FROM organizations WHERE name = 'Петергоф';
-- назначить владельцем
INSERT INTO user_organizations (user_id, org_id, role)
VALUES (<user_id>, <org_id>, 'owner')
ON CONFLICT (user_id, org_id) DO UPDATE SET role = 'owner';
```

## Чтобы это не повторилось

- Не удалять и не переписывать уже задеплоенные ревизии alembic. Новые изменения схемы — только новыми миграциями поверх текущего head.
- Перед `alembic upgrade head` в деплое делать бэкап БД (см. тикет INF-03).
