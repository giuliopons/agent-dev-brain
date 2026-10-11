# agent-dev: bot Telegram che esegue Claude Code headless sul clone del vault brain.
# Aggiornare Claude Code: sudo docker compose build --no-cache && sudo docker compose up -d
FROM node:22-bookworm-slim

# uid/gid dell'utente dell'host che possiede brain/ e state/ (install.sh li scrive in .env)
ARG AGENT_UID=1000
ARG AGENT_GID=1000

ARG GITLEAKS_VERSION=8.30.1
ARG GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
ARG PTB_VERSION=22.8

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git openssh-client ca-certificates curl ripgrep python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*

# gitleaks: lo usa l'hook .githooks/pre-commit del vault per bloccare i segreti
RUN curl -fsSL -o /tmp/gl.tgz \
      "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
 && echo "${GITLEAKS_SHA256}  /tmp/gl.tgz" | sha256sum -c - \
 && tar -xzf /tmp/gl.tgz -C /usr/local/bin gitleaks \
 && rm /tmp/gl.tgz

RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

# venv: Debian bookworm non permette pip install nel Python di sistema
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir "python-telegram-bot==${PTB_VERSION}"

# l'immagine node ha già l'utente "node" (uid 1000): lo rinomino in "agent" e gli do l'uid dell'utente dell'host
RUN groupmod -n agent -g "${AGENT_GID}" node \
 && usermod -l agent -d /home/agent -m -u "${AGENT_UID}" -g "${AGENT_GID}" node

# Hook dei commit del bot (nei clone: core.hooksPath=/opt/githooks). Il wrapper è di root, quindi l'agente non può modificarlo.
# Se il vault ha .githooks/pre-commit lo lancia con sh (da Windows arriva senza bit di esecuzione),
# altrimenti fa direttamente il controllo dei segreti con gitleaks.
RUN mkdir -p /opt/githooks \
 && printf '%s\n' '#!/bin/sh' \
      'hook="$(git rev-parse --show-toplevel)/.githooks/pre-commit"' \
      '[ -f "$hook" ] && exec sh "$hook" "$@"' \
      'exec gitleaks git --pre-commit --staged --redact --no-banner' > /opt/githooks/pre-commit \
 && chmod 755 /opt/githooks/pre-commit

ENV PATH=/opt/venv/bin:$PATH \
    HOME=/home/agent \
    CLAUDE_CONFIG_DIR=/home/agent/.claude \
    DISABLE_AUTOUPDATER=1 \
    PYTHONUNBUFFERED=1

USER agent
WORKDIR /work/brain
CMD ["python3", "/app/bot.py"]
