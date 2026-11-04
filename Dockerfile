# Q1. What does the app need to run? Python
FROM python:3.13-slim

# Q2. Where do the files live inside the container?
WORKDIR /app

# Q3. How are the packages installed? Copy the list first, so this layer stays cached
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Q4. Which files does the app need? The code and the website (not the tests)
COPY app ./app
COPY static ./static

# Version label, set by the pipeline (defaults to "dev")
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

# Q5. How is it run, and how do we know it's healthy?
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]