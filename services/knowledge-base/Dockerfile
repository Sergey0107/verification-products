FROM python:3.11-slim

# 1. Переменные окружения
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=1000

# 2. Рабочая директория внутри контейнера
WORKDIR /app

# 3. Установка Python-зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=1000 -r requirements.txt

# 4. Копируем код приложения
COPY app ./app

# 5. Порт (информационно)
EXPOSE 8000

# 6. Команда запуска
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
