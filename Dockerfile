# Two build targets from one definition:
#   --target local   uvicorn server, used by docker-compose for development
#   --target lambda  AWS Lambda container image, what CI pushes to ECR
# The application code is identical; only the entrypoint differs.

# ---------------------------------------------------------------- local dev
FROM python:3.12-slim AS local

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# pyproject and sources are copied together: setuptools resolves `app*` at
# install time, so installing before the source exists would silently produce
# a distribution with no packages in it.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Non-root. The home directory matters: the host's AWS SSO cache is mounted at
# ~/.aws inside the container (see docker-compose.yml).
RUN useradd --create-home --uid 1000 app \
    && chown -R app:app /srv
USER app
ENV HOME=/home/app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ------------------------------------------------------------------- lambda
# Default target, so a bare `docker build .` produces the deployable image.
FROM public.ecr.aws/lambda/python:3.12 AS lambda

COPY pyproject.toml ${LAMBDA_TASK_ROOT}/
COPY app ${LAMBDA_TASK_ROOT}/app
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ${LAMBDA_TASK_ROOT}

# module.attribute — Mangum wraps the same FastAPI app.
CMD ["app.lambda_handler.handler"]
