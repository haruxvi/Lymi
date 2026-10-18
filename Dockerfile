# lymi como servidor: la agenda (workflows programados) y los webhooks, sin escritorio.
#
#   docker build -t lymi .
#   docker run -d --name lymi -v lymi-datos:/datos lymi
#
# La interfaz no va aqui a proposito: solo escucha en loopback (lanza corridas y
# aprueba efectos; exponerla no es una configuracion, es un fallo). Para verla,
# usa la app de escritorio o `lymi ui` en tu maquina.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY_NOTICES.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY workflows ./ejemplos/workflows
COPY agencias ./ejemplos/agencias
RUN uv sync --locked --no-dev

# Sin privilegios: lymi no necesita root para nada.
RUN useradd --create-home --uid 10001 lymi && mkdir /datos && chown lymi /datos
USER lymi
WORKDIR /datos
VOLUME ["/datos"]

ENV PATH="/app/.venv/bin:${PATH}"
# Ollama en la maquina anfitriona. Que el tier local salga del contenedor es una
# decision explicita: por defecto lymi exige que el modelo local este en loopback.
ENV LYMI_OLLAMA_URL=http://host.docker.internal:11434 \
    LYMI_ALLOW_REMOTE_LOCAL=1

# Primer arranque: copia los ejemplos al volumen sin pisar lo que ya haya.
CMD ["sh", "-c", "[ -d workflows ] || cp -r /app/ejemplos/workflows workflows; [ -d agencias ] || cp -r /app/ejemplos/agencias agencias; exec lymi serve --host 0.0.0.0"]

EXPOSE 8765
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/salud', timeout=4)"
