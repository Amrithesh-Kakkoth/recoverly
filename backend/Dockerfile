FROM python:3.12-slim
WORKDIR /srv
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
# Dependencies first so code changes don't re-install them. The app imports the voice stack
# (Pipecat) and the PayPal Agent Toolkit at startup, so both extras are required.
COPY pyproject.toml requirements.lock ./
RUN mkdir app && touch app/__init__.py && pip install -c requirements.lock ".[voice,paypal,dev]" && rm -rf app build *.egg-info
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
