FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y python3 python3-pip xvfb x11vnc fluxbox xauth x11-utils wine64 winbind ca-certificates git fonts-dejavu && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/novnc/noVNC.git /opt/novnc && ln -s /opt/novnc/vnc_lite.html /opt/novnc/index.html
WORKDIR /app
COPY . /app
RUN pip3 install --no-cache-dir fastapi "uvicorn[standard]"
ENV DISPLAY=:99 WINEDEBUG=-all
CMD ["python3","main.py"]
