# Optional research CLI environment. This handoff did not run Docker.
# After validating a concrete image, pass its real digest as PYTHON_IMAGE.
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/qec-graph
COPY pyproject.toml requirements.txt ./
COPY qecgraph ./qecgraph
RUN python -m pip install --no-cache-dir .
WORKDIR /work
ENTRYPOINT ["qecgraph"]
CMD ["--help"]
