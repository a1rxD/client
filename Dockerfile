FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y \
    python3 python3-pip xvfb x11vnc fluxbox xauth x11-utils \
    wine wine64 wine32 winbind cabextract ca-certificates git \
    fonts-dejavu libx11-6:i386 libxext6:i386 libfreetype6:i386 libnss3:i386 libgtk2.0-0:i386 && \
    rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/novnc/noVNC.git /opt/novnc && \
    ln -s /opt/novnc/vnc_lite.html /opt/novnc/index.html
ENV DISPLAY=:99 WINEARCH=win32 WINEPREFIX=/wine32 WINEDEBUG=-all
WORKDIR /app
COPY . /app
RUN pip3 install --no-cache-dir fastapi "uvicorn[standard]"
CMD ["python3","main.py"]
