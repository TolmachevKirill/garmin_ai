"""Garmin Health Pipeline.

Библиотека и CLI для выгрузки данных из Garmin Connect в файловую
"библиотеку" (markdown + CSV), которую затем загружаешь в ChatGPT Project.

Модули:
    config       - настройки, пути, переменные окружения
    client       - обёртка над python-garminconnect с логином/кэшем токенов
    cache        - локальный SQLite-кэш истории метрик и тренировок
    formatting   - шаблоны markdown-отчётов
    library      - запись файлов в библиотеку + индекс
    rollup       - сворачивание старых daily-файлов в monthly
    collectors/  - сбор данных: daily, weekly, activity
    cli          - точка входа командной строки
"""

__version__ = "0.1.0"
