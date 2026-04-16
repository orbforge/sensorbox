# orb-forge custom ImageBuilder builder service.
# Always-running FastAPI app that builds OpenWrt ImageBuilder containers
# on demand for devices needing custom kernel patches / DTS.

FROM docker.io/library/debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git curl python3 python3-pip python3-venv ca-certificates \
        build-essential gawk unzip file wget python3-distutils rsync \
        libncurses-dev zlib1g-dev xz-utils libelf-dev \
        python3-pyelftools swig && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Python deps for the API
RUN python3 -m pip install --break-system-packages \
    fastapi uvicorn pyyaml

WORKDIR /app
COPY app.py build.sh ./
RUN chmod +x build.sh

EXPOSE 8001
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
