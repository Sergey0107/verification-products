FROM python:3.11-slim

# 1. Переменные окружения
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 2. Рабочая директория внутри контейнера
WORKDIR /app

# 3. Системные зависимости (минимум)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. Установка Python-зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копируем код приложения
COPY app ./app

# 6. Порт (информационно)
EXPOSE 8000

# 7. Команда запуска
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
