FROM nvidia/cuda:12.4-runtime-ubuntu22.04

# System dependencies
RUN apt-get update && apt-get install -y \
    curl git build-essential autoconf automake libtool pkg-config \
    libcurl4-openssl-dev libjansson-dev libudev-dev \
    ocl-icd-opencl-dev clinfo nvidia-opencl-icd \
    && rm -rf /var/lib/apt/lists/*

# Build BFGMiner from source
RUN git clone https://github.com/luke-jr/bfgminer.git /bfgminer \
    && cd /bfgminer \
    && ./autogen.sh \
    && ./configure --enable-scrypt --enable-opencl --enable-cuda --enable-bfgminer \
    && make -j$(nproc) \
    && make install \
    && ldconfig

WORKDIR /app

# Python orchestration layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY miner_worker.py .
CMD ["python", "miner_worker.py"]