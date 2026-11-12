# Cross-build Windows .exe on macOS/Linux via Wine + Windows Python + PyInstaller.
# Build:  docker build -t adapter-win-build -f Dockerfile .
# Run:    docker run --rm \
#           -v <repo-root>:/src \
#           -v <this-dir>:/build \
#           adapter-win-build bash /build/build.sh
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV WINEARCH=win64
ENV WINEPREFIX=/opt/wine
ENV WINEDEBUG=-all
ENV PYTHONDONTWRITEBYTECODE=1

# wine64 is enough to run 64-bit Windows Python.
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        wine64 \
        wget \
        unzip \
        xvfb \
        xauth \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*
