FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

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

# BFGMiner submodules still use git:// which often times out.
# Rewrite to HTTPS before clone.
RUN git config --global url."https://github.com/".insteadOf git://github.com/ \
    && git config --global url."https://".insteadOf git:// \
    && git clone --recursive https://github.com/luke-jr/bfgminer.git /bfgminer \
    && cd /bfgminer \
    && ./autogen.sh \
    && ./configure --enable-scrypt --enable-opencl --enable-bfgminer \
    && make -j"$(nproc)" \
    && make install \
    && ldconfig \
    && bfgminer --version

WORKDIR /app

COPY worker/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY worker/miner_worker.py .
COPY comms/ ./comms/

CMD ["python3", "miner_worker.py"]
