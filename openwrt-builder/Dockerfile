# sensorbox custom ImageBuilder builder service.
# Always-running FastAPI app that builds OpenWrt ImageBuilder containers
# on demand for devices needing custom kernel patches / DTS.

FROM docker.io/library/debian:bookworm-slim

# Full OpenWrt buildroot prerequisites (per upstream docs)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git curl ca-certificates wget \
        build-essential clang flex bison gawk gettext \
        libncurses-dev libssl-dev libelf-dev zlib1g-dev \
        python3 python3-dev python3-pip python3-venv \
        python3-distutils python3-setuptools python3-pyelftools \
        swig rsync unzip file xz-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Python deps for the API
RUN python3 -m pip install --break-system-packages \
    fastapi uvicorn pyyaml

WORKDIR /app
COPY app.py build.sh ./
RUN chmod +x build.sh

EXPOSE 8001
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
