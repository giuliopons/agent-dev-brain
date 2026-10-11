#!/usr/bin/env bash
# Installa agent-dev-brain su un server Ubuntu/Debian: repo centrale del vault, mirror su GitHub
# (facoltativo), Docker e bot Telegram. Idempotente: rilanciarlo non rifà quello che c'è già.
#   sudo bash install.sh                        dalla cartella del repo
#   sudo bash install.sh --pc-key "ssh-ed25519 …"   autorizza un altro PC su brain.git
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Lancialo con sudo: sudo bash install.sh"; exit 1; }
OWNER=${SUDO_USER:-}
[ -n "$OWNER" ] && [ "$OWNER" != root ] || { echo "Lancialo con sudo dal tuo utente, non da root"; exit 1; }
OWNER_UID=$(id -u "$OWNER")
OWNER_GID=$(id -g "$OWNER")

DIR=$(cd "$(dirname "$0")" && pwd)
cd "$DIR"
ENV=$DIR/.env
SSHDIR=$DIR/state/ssh
SERVICE=agent-dev-brain

U=brain                       # utente di sistema che possiede il repo centrale (solo git-shell)
H=/home/$U
REPO=$H/brain.git
AK=$H/.ssh/authorized_keys

PC_KEY=""
while [ $# -gt 0 ]; do
  case $1 in
    --pc-key) PC_KEY=${2:?manca la chiave dopo --pc-key}; shift 2 ;;
    *) echo "Opzione sconosciuta: $1"; exit 1 ;;
  esac
done

step() { printf '\n== %s\n' "$*"; }
as_owner() { sudo -u "$OWNER" -H "$@"; }
as_brain() { sudo -u "$U" -H "$@"; }
# le domande leggono dal terminale anche se lo script arriva da una pipe
ask() { local answer; read -r -p "$1" answer </dev/tty; printf '%s' "$answer"; }

env_get() { [ -f "$ENV" ] && sed -n "s/^$1=//p" "$ENV" | tail -n 1 || true; }
env_set() {
  # sostituisce la riga KEY= (o la aggiunge) e riscrive il file sul posto:
  # proprietario e permessi (600) restano quelli di .env
  local tmp; tmp=$(mktemp)
  K=$1 V=$2 awk '$0 ~ "^" ENVIRON["K"] "=" { print ENVIRON["K"] "=" ENVIRON["V"]; done = 1; next }
                 { print }
                 END { if (!done) print ENVIRON["K"] "=" ENVIRON["V"] }' "$ENV" > "$tmp"
  cat "$tmp" > "$ENV"; rm -f "$tmp"
}

# ---------------------------------------------------------------- 1. domande
step "Configurazione"
[ -f "$ENV" ] || install -m 600 -o "$OWNER" -g "$OWNER_GID" .env.example "$ENV"

if [ -z "$(env_get TELEGRAM_TOKEN)" ]; then
  echo "Crea un bot NUOVO con @BotFather su Telegram (/newbot): ti dà un token."
  while :; do
    v=$(ask "Token del bot Telegram: ")
    [[ $v =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] && break
    echo "  non sembra un token (formato 123456:ABC…)"
  done
  env_set TELEGRAM_TOKEN "$v"
fi

if [ -z "$(env_get ALLOWED_USER_ID)" ]; then
  echo "Il bot risponde solo a te: il tuo user id numerico te lo dice @userinfobot."
  while :; do
    v=$(ask "Il tuo user id Telegram: ")
    [[ $v =~ ^[0-9]+$ ]] && break
    echo "  deve essere un numero"
  done
  env_set ALLOWED_USER_ID "$v"
fi

if [ -z "$(env_get TZ)" ]; then
  tz=$(timedatectl show -p Timezone --value 2>/dev/null || true)
  tz=${tz:-Europe/Rome}
  v=$(ask "Fuso orario per i nomi delle note [$tz]: ")
  env_set TZ "${v:-$tz}"
fi

env_set AGENT_UID "$OWNER_UID"
env_set AGENT_GID "$OWNER_GID"

GH=""
if ! { [ -d "$REPO" ] && as_brain git -C "$REPO" remote get-url github &>/dev/null; }; then
  echo
  echo "Backup su GitHub (facoltativo)"
  echo "  Il vault può essere copiato automaticamente su un tuo repo GitHub PRIVATO."
  echo "  - Repo nuovo: crealo su github.com vuoto (senza README né licenza) e scrivi qui il suo nome."
  echo "  - Repo con un vault già dentro: scrivi il suo nome e lo importo."
  echo "  - Invio: niente backup (puoi aggiungerlo dopo rilanciando l'installer)."
  while :; do
    GH=$(ask "Nome del repo (es. mario/brain): ")
    [ -z "$GH" ] || [[ $GH =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] && break
    echo "  formato utente/repo, per esempio mario/brain"
  done
fi

if [ -z "$PC_KEY" ] && ! grep -qs '^no-port-forwarding' "$AK"; then
  echo
  echo "Accesso dal PC (facoltativo)"
  echo "  Per scrivere le note anche dal PC (Obsidian + git), incolla la chiave SSH pubblica del PC:"
  echo "  è il contenuto di ~/.ssh/id_ed25519.pub (se non esiste: ssh-keygen -t ed25519 sul PC)."
  echo "  Invio: nessun PC (puoi aggiungerlo dopo con: sudo bash install.sh --pc-key \"…\")."
  while :; do
    PC_KEY=$(ask "Chiave pubblica: ")
    [ -z "$PC_KEY" ] || [[ $PC_KEY =~ ^(ssh-|ecdsa-)[^\ ]+\ [A-Za-z0-9+/=]+ ]] && break
    echo "  deve iniziare con ssh-ed25519, ssh-rsa o ecdsa-…"
  done
fi

# ---------------------------------------------------------------- 2. pacchetti di base
step "Pacchetti"
need=()
command -v git >/dev/null || need+=(git)
command -v curl >/dev/null || need+=(curl ca-certificates)
command -v sshd >/dev/null || [ -x /usr/sbin/sshd ] || need+=(openssh-server)
if [ ${#need[@]} -gt 0 ]; then apt-get update -q && apt-get install -y -q "${need[@]}"; fi
# il bot raggiunge brain.git via ssh su 127.0.0.1
systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd

# ---------------------------------------------------------------- 3. repo centrale
step "Repo centrale $REPO"
# utente dedicato, separato dal tuo account: niente login, solo git
grep -qx /usr/bin/git-shell /etc/shells || echo /usr/bin/git-shell >> /etc/shells
id "$U" &>/dev/null || useradd --create-home --shell /usr/bin/git-shell "$U"
chmod 750 "$H"
install -d -m 700 -o "$U" -g "$U" "$H/.ssh" "$H/bin"
touch "$AK"; chown "$U:$U" "$AK"; chmod 600 "$AK"

[ -d "$REPO" ] || as_brain git init -q --bare -b main "$REPO"
# niente force push né cancellazioni di branch: la storia si corregge solo con revert
as_brain git -C "$REPO" config receive.denyNonFastForwards true
as_brain git -C "$REPO" config receive.denyDeletes true

# accesso dal PC: solo git, niente tunnel né terminale
if [ -n "$PC_KEY" ]; then
  keybody=$(awk '{print $2}' <<<"$PC_KEY")
  grep -q "$keybody" "$AK" || \
    echo "no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $PC_KEY" >> "$AK"
  echo "chiave del PC autorizzata"
fi

# ---------------------------------------------------------------- 4. mirror su GitHub
if [ -n "$GH" ]; then
  step "Mirror su GitHub ($GH)"
  DK=$H/.ssh/github_deploy
  [ -f "$DK" ] || as_brain ssh-keygen -q -t ed25519 -N "" -C "brain-mirror@$(hostname)" -f "$DK"
  cat > "$H/.ssh/config" <<EOF
Host github-brain
  HostName github.com
  User git
  IdentityFile $DK
  IdentitiesOnly yes
EOF
  touch "$H/.ssh/known_hosts"
  grep -q "^github.com " "$H/.ssh/known_hosts" || ssh-keyscan -t ed25519 github.com >> "$H/.ssh/known_hosts" 2>/dev/null
  chown "$U:$U" "$H/.ssh/config" "$H/.ssh/known_hosts"; chmod 600 "$H/.ssh/config"
  as_brain git -C "$REPO" remote add github "git@github-brain:$GH.git"

  cat > "$H/bin/mirror.sh" <<'EOF'
#!/bin/sh
# Pushes branches and tags of the bare repo to GitHub. Called by the hook and by cron.
LOG=$HOME/mirror.log
exec 9>"$HOME/.mirror.lock"
flock -w 120 9 || exit 0
cd "$HOME/brain.git" || exit 1
if git push --quiet github 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*' >>"$LOG" 2>&1; then
  echo "$(date -Is) ok" >>"$LOG"
else
  echo "$(date -Is) ERRORE push GitHub" >>"$LOG"
fi
tail -n 300 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
EOF
  cat > "$REPO/hooks/post-receive" <<'EOF'
#!/bin/sh
# Mirror in background: the push from the laptop does not wait for GitHub.
nohup "$HOME/bin/mirror.sh" >/dev/null 2>&1 &
EOF
  chown "$U:$U" "$H/bin/mirror.sh" "$REPO/hooks/post-receive"
  chmod 750 "$H/bin/mirror.sh" "$REPO/hooks/post-receive"
  # recupero: se un mirror è fallito (rete giù), riprova ogni ora
  ( crontab -u "$U" -l 2>/dev/null | grep -v mirror.sh || true; \
    echo "17 * * * * HOME=$H $H/bin/mirror.sh" ) | crontab -u "$U" -

  echo
  echo "👉 Su GitHub: repo $GH → Settings → Deploy keys → Add deploy key,"
  echo "   incolla questa chiave e spunta 'Allow write access':"
  echo
  cat "$DK.pub"
  echo
  while :; do
    ask "Premi Invio quando l'hai aggiunta... " >/dev/null
    out=$(as_brain ssh -T git@github-brain 2>&1 || true)
    [[ $out == *"successfully authenticated"* ]] && { echo "✅ GitHub raggiungibile"; break; }
    echo "  GitHub non accetta ancora la chiave: $out"
  done
fi

# ---------------------------------------------------------------- 5. Docker
step "Docker"
if ! command -v docker >/dev/null; then
  . /etc/os-release   # ID = ubuntu | debian (https://docs.docker.com/engine/install/)
  apt-get update -q
  apt-get install -y -q ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
# di proposito il tuo utente NON entra nel gruppo docker (equivale a root): docker si usa con sudo
docker --version

# ---------------------------------------------------------------- 6. chiave del bot
step "Chiave SSH del bot"
# le cartelle le crea l'installer: se le creasse docker sarebbero di root e il container non ci scriverebbe
as_owner mkdir -p "$DIR/state/claude"
as_owner install -d -m 700 "$SSHDIR"
[ -f "$SSHDIR/id_ed25519" ] || as_owner ssh-keygen -q -t ed25519 -N "" -C "agent-dev@$(hostname)" -f "$SSHDIR/id_ed25519"
[ -s "$SSHDIR/known_hosts" ] || ssh-keyscan -t ed25519 127.0.0.1 2>/dev/null | as_owner tee "$SSHDIR/known_hosts" >/dev/null
[ -f "$SSHDIR/config" ] || as_owner tee "$SSHDIR/config" >/dev/null <<'EOF'
# ssh del container agent-dev-brain (montato read-only in /home/agent/.ssh)
Host 127.0.0.1
  User brain
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
  # known_hosts è read-only: non provare ad aggiungere altre chiavi dell'host
  UpdateHostKeys no
  StrictHostKeyChecking yes
EOF
chmod 600 "$SSHDIR/config"
# su brain.git la chiave del bot vale solo per git e solo dal server stesso
keybody=$(awk '{print $2}' "$SSHDIR/id_ed25519.pub")
grep -q "$keybody" "$AK" || echo "restrict,from=\"127.0.0.1,::1\" $(cat "$SSHDIR/id_ed25519.pub")" >> "$AK"

# ---------------------------------------------------------------- 7. contenuto del vault
step "Vault"
has_main() { as_brain git -C "$REPO" rev-parse -q --verify refs/heads/main >/dev/null; }
if ! has_main && as_brain git -C "$REPO" remote get-url github &>/dev/null; then
  # server rifatto da zero o vault già su GitHub: lo importo
  as_brain git -C "$REPO" fetch -q github 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*' || true
  has_main && echo "vault importato da GitHub"
fi
if ! has_main; then
  # vault nuovo dal modello in template/ (copiato fuori da casa tua: brain non ci può leggere)
  tmp=$(mktemp -d)
  cp -a "$DIR/template/." "$tmp/"
  chown -R "$U:$U" "$tmp"
  as_brain git -C "$tmp" init -q -b main
  as_brain git -C "$tmp" add -A
  as_brain git -C "$tmp" -c user.name="agent-dev-brain" -c user.email="install@localhost" \
    commit -q -m "vault iniziale"
  as_brain git -C "$tmp" push -q "$REPO" main   # fa scattare post-receive: il mirror parte da qui
  rm -rf "$tmp"
  echo "creato un vault vuoto (struttura PARA, CLAUDE.md, hook gitleaks)"
fi
has_main || { echo "❌ brain.git non ha il branch main: controlla il repo GitHub"; exit 1; }

# ---------------------------------------------------------------- 8. clone del bot
step "Clone del bot in brain/"
if [ ! -d "$DIR/brain/.git" ]; then
  as_owner env GIT_SSH_COMMAND="ssh -i $SSHDIR/id_ed25519 -o UserKnownHostsFile=$SSHDIR/known_hosts -o IdentitiesOnly=yes" \
    git clone -q "$U@127.0.0.1:brain.git" "$DIR/brain"
fi
# l'autore agent-dev serve a /undo per riconoscere i task del bot
as_owner git -C "$DIR/brain" config user.name agent-dev
as_owner git -C "$DIR/brain" config user.email "agent-dev@$(hostname).invalid"
as_owner git -C "$DIR/brain" config core.hooksPath /opt/githooks
# path dentro il container
as_owner git -C "$DIR/brain" config core.sshCommand \
  "ssh -i /home/agent/.ssh/id_ed25519 -o UserKnownHostsFile=/home/agent/.ssh/known_hosts -o IdentitiesOnly=yes"

# ---------------------------------------------------------------- 9. immagine e token Claude
step "Immagine Docker"
docker compose build

# finché non c'è un accesso valido: Invio a vuoto sul token o sulla chiave riporta alla scelta
while [ -z "$(env_get CLAUDE_CODE_OAUTH_TOKEN)" ] && [ -z "$(env_get ANTHROPIC_API_KEY)" ]; do
  step "Accesso a Claude"
  echo "1) abbonamento Claude (Pro/Max): genero un token con claude setup-token"
  echo "2) chiave API Anthropic, a consumo"
  choice=$(ask "Scegli [1]: ")
  if [ "${choice:-1}" = 2 ]; then
    while :; do
      v=$(ask "Chiave API (sk-ant-api…, Invio per tornare alla scelta): ")
      [ -z "$v" ] || [[ $v == sk-ant-* ]] && break
      echo "  deve iniziare con sk-ant-"
    done
    [ -n "$v" ] && env_set ANTHROPIC_API_KEY "$v"
  else
    echo "Apri il link che compare, accedi e incolla qui il codice del browser."
    echo "(Per tornare indietro: esci da setup-token con Esc o Ctrl+C e premi Invio alla domanda dopo.)"
    docker compose run --rm "$SERVICE" claude setup-token </dev/tty || true
    while :; do
      v=$(ask "Incolla il token stampato qui sopra (sk-ant-oat01-…, Invio per tornare alla scelta): ")
      [ -z "$v" ] || [[ $v == sk-ant-oat* ]] && break
      echo "  deve iniziare con sk-ant-oat"
    done
    [ -n "$v" ] && env_set CLAUDE_CODE_OAUTH_TOKEN "$v"
  fi
done

# ---------------------------------------------------------------- 10. avvio
step "Avvio"
docker compose up -d
docker compose ps

ip=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "✅ Fatto. Scrivi al bot su Telegram: un messaggio è un task, un inoltro finisce in inbox/."
echo
echo "Dal PC (con la chiave autorizzata):"
echo "  git clone $U@${ip:-<server>}:brain.git"
echo "  git -C brain config core.hooksPath .githooks   # hook gitleaks, serve gitleaks installato"
grep -qs '^no-port-forwarding' "$AK" || echo "  (nessun PC autorizzato: sudo bash install.sh --pc-key \"<riga di ~/.ssh/id_ed25519.pub del PC>\")"
echo
echo "Docker si usa con sudo: sudo docker compose logs -f, sudo docker compose ps"
