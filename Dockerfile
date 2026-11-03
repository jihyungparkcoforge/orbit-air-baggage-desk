# STRETCH GOAL 4: an image that runs the tests while it builds and then runs the app.
FROM python:3.12-slim

WORKDIR /app
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

# The build stops here if a test or a lint check fails.
RUN python -m pytest -q && ruff check .

# Keep the database outside the code so it can live in a volume.
RUN mkdir /data
VOLUME /data

ENTRYPOINT ["python", "main.py", "--db", "/data/baggage_desk.db"]
CMD ["list"]
