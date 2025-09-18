FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y \
    python3 python3-pip xvfb x11vnc fluxbox xauth x11-utils x11-apps xterm \
    git ca-certificates fonts-dejavu \
    libgtk-3-0 libglib2.0-0 libnss3 libasound2 libx11-xcb1 libxrandr2 \
    libxrender1 libxi6 libxtst6 libxdamage1 libxcomposite1 libatk1.0-0 \
    libatk-bridge2.0-0 libxkbcommon0 libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    wine wine64 wine32 winbind cabextract \
    libx11-6:i386 libxext6:i386 libfreetype6:i386 libnss3:i386 libgtk2.0-0:i386 \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/novnc/noVNC.git /opt/novnc \
 && ln -s /opt/novnc/vnc_lite.html /opt/novnc/index.html
WORKDIR /app
COPY . /app
RUN pip3 install --no-cache-dir fastapi "uvicorn[standard]"
ENV DISPLAY=:99 WINEDEBUG=-all LIBGL_ALWAYS_SOFTWARE=1
CMD ["python3","main.py"]
