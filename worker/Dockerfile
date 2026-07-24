FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies (packages that exist on Ubuntu 22.04 / CUDA runtime base)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    build-essential \
    autoconf \
    automake \
    libtool \
    pkg-config \
    libcurl4-openssl-dev \
    libjansson-dev \
    libudev-dev \
    ocl-icd-opencl-dev \
    ocl-icd-libopencl1 \
    clinfo \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Build BFGMiner from source
RUN git clone https://github.com/luke-jr/bfgminer.git /bfgminer \
    && cd /bfgminer \
    && ./autogen.sh \
    && ./configure --enable-scrypt --enable-opencl --enable-bfgminer \
    && make -j$(nproc) \
    && make install \
    && ldconfig

WORKDIR /app

# Build context is repo root
COPY worker/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY worker/miner_worker.py .
COPY comms/ ./comms/

CMD ["python3", "miner_worker.py"]
