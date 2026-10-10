# agent-dev-brain

Un server casalingo per un "secondo cervello" in Markdown, cioè un vault Obsidian versionato con git. Fa due cose:

1. **Repo centrale con backup.** Un repo git bare sul server: il PC fa push e pull lì, e il server lo copia su GitHub a ogni push (`setup-server.sh`).
2. **Bot Telegram con Claude Code.** Dal telefono mandi un'istruzione ("riassumi le note di ieri in una nota di sintesi") e Claude Code, in modalità headless dentro un container Docker, la esegue su un clone del vault, poi fa commit e push. Messaggi inoltrati, foto e documenti invece vengono salvati così come sono in `inbox/`, senza passare da Claude.

```
💻 PC ◄── push/pull ──► brain.git (sul server) ──mirror──► GitHub (privato)
                            ▲
📱 Telegram ─► bot.py (container) ─► claude -p ─► ./brain ─commit+push (ssh brain@127.0.0.1)
                  └─► cattura grezza in inbox/ (./state/capture) ─push─┘
```

Il bot è pensato per **una sola persona**: risponde a un solo user id Telegram, nelle chat private, e ignora tutti gli altri.

## Requisiti

- Un server Ubuntu/Debian sempre acceso (va bene un mini PC), con un utente amministratore con **uid 1000**: il container lavora con quell'uid sui file di `brain/` e `state/`.
- Un vault in un repo GitHub **privato**, per il mirror.
- Nel vault, uno script `.githooks/pre-commit` (per esempio uno che lancia `gitleaks git --pre-commit --staged`): il container lo esegue a ogni commit e senza quel file i commit falliscono. Un `CLAUDE.md` nel vault, con le regole delle note, è consigliato.
- Un bot Telegram nuovo, creato con @BotFather, e il tuo user id numerico.
- Un abbonamento Claude (token creato con `claude setup-token`) oppure una chiave API Anthropic.

## Installazione

Dalla cartella del repo, sul server:

```bash
git clone https://github.com/giuliopons/agent-dev-brain.git agent-dev && cd agent-dev

# 1. repo centrale + mirror. Alla fine stampa una deploy key da aggiungere su GitHub
#    (repo del vault → Settings → Deploy keys, con "Allow write access"), poi verifica:
sudo bash setup-server.sh <utente-github> "$(cat chiave_pubblica_del_pc.pub)"
sudo -u brain -H ssh -T git@github-brain
#    GH_REPO=nome-repo se il repo del vault non si chiama "brain"

# 2. riempi brain.git, che è vuoto: dal PC, con il server come remote principale
#    git push <remote-server> main

# 3. chiave e ssh del bot. Le cartelle vanno create a mano:
#    se le crea docker, finiscono a root e il container non ci scrive
mkdir -p state/claude && install -d -m 700 state/ssh
ssh-keygen -q -t ed25519 -N "" -C "agent-dev@$(hostname)" -f state/ssh/id_ed25519
ssh-keyscan -t ed25519 127.0.0.1 > state/ssh/known_hosts
cat > state/ssh/config <<'CFG'
# ssh del container agent-dev (montato read-only in /home/agent/.ssh)
Host 127.0.0.1
  User brain
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
  # known_hosts è read-only: non provare ad aggiungere altre chiavi dell'host
  UpdateHostKeys no
  StrictHostKeyChecking yes
CFG
chmod 600 state/ssh/config

# 4. Docker + chiave del bot in authorized_keys di brain (solo git, solo da localhost)
sudo bash setup-host.sh

# 5. clone del vault per il bot, con i path del container
GIT_SSH_COMMAND="ssh -i state/ssh/id_ed25519 -o UserKnownHostsFile=state/ssh/known_hosts -o IdentitiesOnly=yes" \
  git clone brain@127.0.0.1:brain.git brain
git -C brain config user.name agent-dev
git -C brain config user.email "agent-dev@$(hostname).invalid"
git -C brain config core.hooksPath /opt/githooks
git -C brain config core.sshCommand "ssh -i /home/agent/.ssh/id_ed25519 -o UserKnownHostsFile=/home/agent/.ssh/known_hosts -o IdentitiesOnly=yes"

# 6. segreti e avvio
cp .env.example .env && chmod 600 .env   # compila TELEGRAM_TOKEN e ALLOWED_USER_ID
sudo docker compose build
sudo docker compose run --rm agent-dev claude setup-token   # il valore va in .env
sudo docker compose up -d
```

Da qui in avanti il PC lavora con il server, non con GitHub: GitHub è solo una copia. Se fai push su GitHub direttamente dal PC, le due storie si separano e il mirror smette di funzionare.

Gli stessi passi servono per rifare il server da zero, per esempio dopo la rottura del disco: GitHub ha la copia completa del vault, e `.env` e `state/` vanno ricreati.

## Uso

Da Telegram:
- **un messaggio di testo** è un task per Claude: risponde con l'esito e l'hash del commit;
- **messaggi inoltrati, foto, documenti e video** vengono salvati grezzi in `inbox/`, con gli allegati in `inbox/attachments/` e un album in una sola nota. Arrivano subito, anche mentre Claude sta lavorando;
- **`/in <testo>`** salva un testo parola per parola;
- **comandi:** `/new` (nuova conversazione), `/undo` (annulla l'ultimo task; si può ripetere), `/status`, `/log`.

I vocali non sono supportati.

Sul server:
```bash
sudo docker compose ps                  # sta girando?
sudo docker compose logs -f             # log del bot (Ctrl+C per uscire)
sudo docker compose restart             # dopo aver modificato bot.py
sudo docker compose up -d               # avvio (riparte da solo anche dopo un reboot)
sudo docker compose exec agent-dev bash # shell nel container
sudo tail -3 /home/brain/mirror.log     # esito delle copie su GitHub
```

Tutti i comandi docker vogliono `sudo`, di proposito: chi è nel gruppo `docker` ha di fatto i permessi di root, e quindi li avrebbe ogni processo che gira con il tuo utente.

**Aggiornare Claude Code:** `sudo docker compose build --no-cache && sudo docker compose up -d`. L'aggiornamento automatico dentro il container è spento (`DISABLE_AUTOUPDATER=1`).

## Sicurezza: cosa protegge e cosa no

Un bot che fa scrivere un'IA su un repo partendo da messaggi Telegram va installato sapendo dove sono i confini.

**Cosa protegge**
- **Chi può dare ordini.** Solo `ALLOWED_USER_ID` e solo in chat privata. Gli altri vengono ignorati senza risposta.
- **Testi di terzi.** Un messaggio inoltrato non diventa mai un'istruzione per Claude: viene solo salvato.
- **La storia del vault.** `brain.git` rifiuta force push e cancellazioni di branch: ogni modifica si annulla con `git revert` (`/undo`), e GitHub ha una copia.
- **Accesso al repo centrale.** La chiave del bot è in `authorized_keys` con `restrict,from="127.0.0.1,::1"`: solo git (git-shell), niente tunnel, valida solo dal server stesso.
- **Segreti nelle note.** Ogni commit passa dall'hook `pre-commit` del vault (gitleaks). Il wrapper `/opt/githooks/pre-commit` è di root, quindi l'agente non può modificarlo.
- **Il server.** Claude gira in un container, con un utente non root e un limite di 1 GB di memoria. `.env` resta fuori dal container, e il token Telegram viene tolto dall'ambiente passato a Claude.

**Cosa NON protegge**
- **Prompt injection rimandata.** Gli inoltri finiscono in `inbox/` senza passare da Claude, ma quando poi chiedi a Claude di sistemare l'inbox li legge, e un testo malevolo può contenere istruzioni. Lo stesso vale per le pagine web che Claude apre.
- **Gli strumenti di Claude non sono limitati.** Claude viene lanciato con `--dangerously-skip-permissions`. Con quel flag, `--allowedTools` non restringe niente: Claude ha shell completa e accesso al web dentro il container. Il confine vero è il container, che usa `network_mode: host` (serve per arrivare a `127.0.0.1:22`) e quindi raggiunge anche i servizi in ascolto in locale sul server.
- **I segreti nell'ambiente di Claude.** Il token di Claude è per forza nel suo ambiente. Il token Telegram ne è escluso, ma un'istruzione malevola potrebbe comunque leggerlo dal processo del bot, che gira con lo stesso utente. gitleaks ferma gli errori, non chi lo aggira con `git commit --no-verify`.
- **Il tuo account Telegram.** Chi controlla il tuo account controlla il bot.

## File

| Percorso | Cosa |
|---|---|
| `bot.py` | il bot (montato nel container: dopo una modifica basta `restart`) |
| `Dockerfile`, `docker-compose.yml` | immagine e servizio |
| `setup-server.sh` | una tantum: utente `brain` (git-shell), `brain.git`, mirror su GitHub, cron orario di recupero |
| `setup-host.sh` | una tantum: Docker, chiave del bot in `authorized_keys` di `brain` |
| `.env` (600, non versionato) | `TELEGRAM_TOKEN`, `ALLOWED_USER_ID`, `CLAUDE_CODE_OAUTH_TOKEN`, `TZ` |
| `brain/` (non versionato) | clone del vault su cui lavora l'agente (autore `agent-dev`) |
| `state/capture/` | secondo clone, usato solo per la cattura in `inbox/`. Così le catture non finiscono nei commit dei task e `/undo` non le annulla |
| `state/agent.log` | una riga per task: data, istruzione, esito, hash |
| `state/session.json` | sessione Claude corrente (`/new` la cancella) |
| `state/claude/` | config e sessioni di Claude Code (`~/.claude` del container) |
| `state/ssh/` | chiave del bot, known_hosts, config (montata read-only) |
| `tests/test_capture.py` | test end-to-end della cattura, con repo temporanei |

## Test

```bash
python3 -m venv /tmp/ptb && /tmp/ptb/bin/pip install -q python-telegram-bot==22.8
/tmp/ptb/bin/python tests/test_capture.py
```

## Se qualcosa va storto

- **Il bot non risponde** → `sudo docker compose ps` e `logs`. Token revocato? `.env` salvato?
- **"Claude è uscito con errore"** → token scaduto (dura circa un anno): `sudo docker compose run --rm agent-dev claude setup-token`, nuovo valore in `.env`, `sudo docker compose up -d`. Se l'errore parla di sessione: `/new`.
- **Task fallito o commit rifiutato da gitleaks** → le modifiche sono in `git stash` del clone: `git -C brain stash list`, `stash show -p`, poi `stash drop` (o `pop` per recuperarle).
- **pull --rebase fallito** → conflitto con un commit fatto altrove. Il bot si ferma senza toccare niente: risolvi a mano in `brain/`. Per usare git dall'host: `GIT_SSH_COMMAND="ssh -i state/ssh/id_ed25519 -o UserKnownHostsFile=state/ssh/known_hosts -o IdentitiesOnly=yes"`.
- **Cattura "❌ Non salvato"** → l'errore è nel messaggio. Se il commit è stato rifiutato da gitleaks, la nota è in `git -C state/capture stash list`. Un push fallito resta committato nel clone di cattura e riparte con la cattura successiva.
- **`ERRORE push GitHub` in `mirror.log`** → deploy key mancante o senza permesso di scrittura, oppure qualcuno ha fatto push su GitHub direttamente. Per riprovare a mano: `sudo -u brain -H /home/brain/bin/mirror.sh`.
- **Chiave del bot compromessa** → togli la sua riga da `/home/brain/.ssh/authorized_keys`, crea una chiave nuova con `ssh-keygen` in `state/ssh/` e rilancia `sudo bash setup-host.sh`.
- **Token Telegram compromesso** → @BotFather `/revoke`, nuovo token in `.env`, `sudo docker compose up -d`.

## Licenza

MIT
