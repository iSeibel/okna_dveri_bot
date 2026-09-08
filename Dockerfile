FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости если нужны
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем файлы проекта
COPY . .

# Создаём папку для логов и базы данных
RUN mkdir -p /app/data

# Запускаем бота с небуферизованным выводом
CMD ["python", "-u", "main.py"]


