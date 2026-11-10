# Optional research CLI environment. Pass PYTHON_IMAGE by digest to pin the base.
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/qec-graph
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY qecgraph ./qecgraph
RUN python -m pip install --no-cache-dir .
WORKDIR /work
ENTRYPOINT ["qecgraph"]
CMD ["--help"]
