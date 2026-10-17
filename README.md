# Latte Art Competition Bot

Telegram-бот для проведения соревнований по латте-арту. Участники регистрируются, отправляют фото работ, админ оценивает по системе LAGS. Побеждает тот, кто наберёт больше баллов.

---

## Как это работает

### Поток для участника

1. **Регистрация** — `/start` → вводит имя → попадает в меню
2. **Подача работы** — `/submit` → фото → описание → подтверждение. Лимит: 3 работы в неделю
3. **Ожидание** — работа уходит на оценку админу
4. **Результат** — получает сообщение с баллами и комментарием (принять/отклонить)
5. **Рейтинг** — баллы суммируются, участник видит своё место в `/leaderboard`

### Поток для админа

1. **Вход** — `/admin_login` → вводит пароль из `.env`
2. **Оценка** — «Оценить работы» → по каждой работе: 4 критерия LAGS (0–10), комментарий, решение (принять/отклонить)
3. **Статистика** — участники, работы, средний балл
4. **Экспорт** — Excel с участниками, работами, рейтингом, оценками

### Система LAGS

4 критерия × 10 баллов = до 40 за работу:

- **Visual Quality** — визуальное качество
- **Creativity** — креативность
- **Technical Skills** — техника
- **Overall Harmony** — общая гармония

---

## Структура проекта

```
latte-art-competition-bot/
├── main.py              # Точка входа
├── models.py            # Модели БД
├── utils.py             # Утилиты
├── routers/             # Обработчики команд и callback
│   ├── user.py          # Логика участника
│   └── admin.py         # Логика админа
├── tests/               # Юнит-тесты
├── requirements.txt     # Зависимости
├── Procfile             # Для Heroku
├── .env                 # Секреты (создать вручную)
└── README.md
```

### main.py

- Загрузка переменных из `.env`
- Подключение к БД (SQLite по умолчанию)
- Создание Bot, Dispatcher
- **DBSessionMiddleware** — перед каждым хендлером создаётся сессия БД и передаётся в `session`
- Регистрация роутеров `user` и `admin`
- При старте — создание таблиц БД, сброс webhook
- Запуск long polling

### models.py

ORM-модели SQLAlchemy:

- **User** — участник (telegram_id, nickname, points, submissions_count, is_admin и т.д.)
- **Submission** — работа (фото, описание, статус, баллы по критериям)
- **Evaluation** — каждая оценка админом (история)
- **Challenge**, **Like**, **AdminSession**, **BotSettings** — зарезервировано/для совместимости

### utils.py

- **check_submission_limit** — проверка лимита 3 работы/неделю
- **get_user_ranking** — место в рейтинге по баллам
- **calculate_level_from_score**, **recalc_user_level_by_points** — уровни (внутренняя логика, в UI не показываются)
- **export_to_excel** — экспорт в .xlsx (участники, работы, рейтинг, оценки)

### routers/user.py

Обработчики для участников:

- `/start` — регистрация (FSM: имя)
- `/menu` — главное меню с кнопками
- `/profile` — профиль (имя, баллы, место, последние работы)
- `/submit` — подача работы (FSM: фото → описание → подтверждение)
- `/leaderboard` — топ-50 по баллам
- `/best_works` — топ-5 лучших работ
- Кнопка «Помощь» — правила и LAGS

### routers/admin.py

Обработчики для админа:

- `/admin_login` — вход по паролю (3 попытки, блокировка 5 мин)
- `/admin_menu` — админ-панель
- Оценка работ — FSM: Visual → Creativity → Technique → Harmony → комментарий → принять/отклонить
- Статистика, список участников
- Экспорт Excel

### tests/

- `test_utils.py` — тесты расчёта уровней
- `test_models.py` — тесты enum и моделей

---

## Установка и запуск

### 1. Зависимости

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Конфигурация

Создай `.env` в корне:

```
BOT_TOKEN=твой_токен_от_BotFather
ADMIN_PASSWORD=пароль_для_админа
```

Опционально:

```
DATABASE_URL=sqlite+aiosqlite:///latte_art_bot.db
```

### 3. Запуск

```bash
python main.py
```

---

## Команды

| Команда         | Описание              |
|-----------------|-----------------------|
| `/start`        | Регистрация           |
| `/menu`         | Главное меню          |
| `/profile`      | Профиль               |
| `/submit`       | Подать работу         |
| `/leaderboard`  | Рейтинг               |
| `/best_works`   | Лучшие работы         |
| `/admin_login`  | Вход в админ-панель   |

---

## Лимиты и правила

- **3 работы в неделю** на участника
- Описание до **300 символов**
- Оценка: 0–10 по каждому критерию, максимум **40 баллов** за работу

## Guides

- [Setup and environment](docs/setup.md)
- [Judging and leaderboard rules](docs/judging.md)
- [Excel exports](docs/exports.md)
- [Operations and recovery](docs/operations.md)
