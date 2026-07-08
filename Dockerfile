# JobScout — deployability story (COURSE CONCEPT: deployment).
# The agent is CLI-first; this image runs the orchestrator anywhere.
#
# Build:  docker build -t jobscout .
# Run:    docker run -it --env-file .env \
#           -v $(pwd)/profile:/app/profile \
#           -v $(pwd)/logs:/app/logs \
#           -v $(pwd)/output:/app/output \
#           jobscout
#
# Secrets come in via --env-file at runtime — nothing is baked into the image.
#
# Playwright liveness verification (preferences.verify_liveness) is
# opt-in and deliberately NOT included in this image — Chromium adds
# ~300MB and a pile of system libs, and most users won't turn this
# feature on. To enable it in Docker, add after the pip install line:
#   RUN pip install playwright && playwright install --with-deps chromium

FROM python:3.12-slim

WORKDIR /app

# Layer-cache dependencies separately from source
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user: least privilege applies to the container too
RUN useradd -m scout && chown -R scout /app
USER scout

ENTRYPOINT ["python", "-m", "src.orchestrator"]
CMD []
