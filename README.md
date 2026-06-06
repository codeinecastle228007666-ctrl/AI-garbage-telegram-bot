# Telegram Bot — Система уведомлений на Notion

Асинхронный Telegram-бот на Python. Все данные хранятся в **Notion** (пользователи, подписки, расписания, логи).

## Возможности

- **Подписки** на типы уведомлений через интерактивное меню
- **Расписание** — интервал + временное окно для каждого типа
- **Автоматическая рассылка** — фоновый планировщик
- **Notion в качестве БД** — всё управляется через Notion API
- **Логирование** всех отправленных уведомлений в Notion

## Команды

| Команда | Описание |
|---------|----------|
| `/start` | Регистрация |
| `/help` | Справка |
| `/notify` | Управление подписками |
| `/schedule [тип] [инт] [с] [до]` | Настройка расписания |
| `/stop` | Отписка от всего |

## Быстрый старт

### 1. Подготовка Notion

1. Создай интеграцию в [Notion Integrations](https://www.notion.so/profile/integrations)
2. Скопируй токен (`ntn_...`) в `.env` → `NOTION_TOKEN`
3. Создай страницу в Notion, расшарь её для интеграции
4. Скопируй ID страницы в `.env` → `NOTION_PARENT_PAGE_ID`

### 2. Настройка

```bash
copy .env.example .env
# Заполни BOT_TOKEN, NOTION_TOKEN, NOTION_PARENT_PAGE_ID
```

### 3. Создание служебных БД

```bash
pip install -r requirements.txt
python notion_setup.py
```

Скопируй полученные ID баз в `.env`.

### 4. Запуск

```bash
python main.py
```

### Open Server Panel

Запусти `start_bot.bat` или настрой автозапуск:
- Модуль → Задания по расписанию (Cron)
- Команда: `python main.py`
- Рабочая директория: путь к проекту

## Структура

```
├── main.py              # Точка входа + планировщик
├── bot.py               # Bot + Dispatcher
├── handlers.py          # Команды
├── services.py          # Бизнес-логика (Notion)
├── models.py            # Перечисления
├── notion_client.py     # Async Notion API клиент
├── notion_setup.py      # Создание БД в Notion
├── config.py            # Конфиг из .env
├── requirements.txt     # aiogram, httpx, python-dotenv
├── start_bot.bat        # Запуск на Windows/OSP
├── osp_config.conf      # Подсказки для Open Server Panel
├── .env.example
└── README.md
```
