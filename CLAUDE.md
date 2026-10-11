# agent-dev-brain

Il progetto di tutto il server del brain: il repo centrale `brain.git` con il mirror su GitHub e il bot Telegram che pilota Claude Code headless in Docker sul vault (`bot.py`). Si installa tutto con `install.sh`; `template/` è il vault vuoto. Uso e struttura: `README.md`. Stato e decisioni recenti: `HANDOFF.md`.

Questo file è per chi sviluppa il bot. Il Claude del bot non lo vede: il container monta solo `./brain`, che ha un suo `CLAUDE.md` con le regole del vault.

## Regole di lavoro
- **I commit li fa l'utente.** Lascia le modifiche non committate e proponi il messaggio.
- **Non scrivere mai in `brain/`.** È il clone del bot, e un albero sporco finisce nel commit del task successivo. Le modifiche al vault si fanno su una copia nella scratchpad. Git dall'host: `GIT_SSH_COMMAND` con la chiave in `state/ssh/`, perché `core.sshCommand` del clone punta ai path del container.
- **Docker solo con `sudo docker compose …`, lanciato dall'utente.** L'utente non è nel gruppo docker, per scelta: il gruppo docker equivale a root. Niente regole sudoers NOPASSWD.
- **Niente modifiche fuori da `~/agent-dev-brain` senza chiedere**, comprese quelle che sembrano innocue, come un `chmod`.
- Proposta già rifiutata, da non riproporre: in `bot.py`, controllare che l'albero sia pulito prima del task.

## Sicurezza (bot.py)
- Un messaggio inoltrato non deve mai diventare un'istruzione per Claude: va sempre in cattura (prompt injection).
- `TELEGRAM_TOKEN` resta fuori dall'env passato a `claude`.
- `only_me`: risponde solo a `ALLOWED_USER_ID` e solo in chat private.

## Installer (`install.sh`)
Un solo script, lanciato con `sudo bash install.sh` dall'utente proprietario (`$SUDO_USER`, non root). Regole che deve continuare a rispettare:
- **Rilanciabile.** Ogni passo controlla se è già fatto. Le domande riguardano solo i valori assenti: `.env` per token, user id, TZ e accesso a Claude; il remote `github` di `brain.git` per GitHub; una riga `no-port-forwarding` in `authorized_keys` per la chiave del PC. GitHub e PC si possono saltare, e vengono riproposti a ogni rilancio finché non sono configurati.
- **Vault:** se `brain.git` non ha `main`, prima lo importa da GitHub (fetch dal remote `github`), altrimenti lo crea da `template/`. Il seed parte da una copia in `mktemp`, perché `brain` non legge la home dell'utente (750). Il push del seed fa scattare `post-receive`, cioè il primo mirror.
- **uid:** `AGENT_UID`/`AGENT_GID` in `.env` → build args del Dockerfile e `user:` in compose. Default 1000.
- **Accesso a Claude:** ciclo finché `.env` non ha `CLAUDE_CODE_OAUTH_TOKEN` o `ANTHROPIC_API_KEY`; Invio a vuoto torna alla scelta.
- **Deploy key:** solo al primo collegamento con GitHub. Se GitHub è già configurato, un rilancio non la rigenera.
- `template/CLAUDE.md` è il `CLAUDE.md` del vault vuoto per chi installa: generico, niente di personale. Non c'entra con `brain/CLAUDE.md`.

### Provarlo in LXD
Su questo server `install.sh` non si lancia (vedi sotto): si prova in un container LXD, come è stato fatto l'11/10. Comandi da host (`giulio@agentsmith`), con sudo, lanciati dall'utente:
```bash
sudo snap install lxd && sudo lxd init --auto           # storage "dir": lo snapshot è una copia completa, lento
sudo lxc launch ubuntu:24.04 brain-test -c security.nesting=true -c limits.memory=1GiB
# Docker sull'host blocca il forward di lxdbr0: senza queste due regole il container non esce (non persistenti)
sudo iptables -I DOCKER-USER -i lxdbr0 -j ACCEPT
sudo iptables -I DOCKER-USER -o lxdbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
sudo lxc exec brain-test -- useradd -m -u 1500 -s /bin/bash -G sudo tester   # uid ≠ 1000 apposta
sudo lxc exec brain-test -- passwd tester
# copia della versione locale, anche non committata, senza ciò che è in .gitignore
git -C ~/agent-dev-brain ls-files -co --exclude-standard -z | tar -C ~/agent-dev-brain --null --ignore-failed-read -T - -czf /tmp/adb.tgz
sudo lxc file push --uid 1500 --gid 1500 /tmp/adb.tgz brain-test/home/tester/
sudo lxc exec brain-test -- su - tester -c 'mkdir -p agent-dev-brain && tar -xzf adb.tgz -C agent-dev-brain'
sudo lxc snapshot brain-test pulito                     # per ripartire: sudo lxc restore brain-test pulito
sudo lxc exec brain-test -- su - tester                 # dentro: cd agent-dev-brain && sudo bash install.sh
# accesso dal PC: porta 2222 dell'host → ssh del container
sudo lxc config device add brain-test ssh2222 proxy listen=tcp:0.0.0.0:2222 connect=tcp:127.0.0.1:22
```
- Serve un secondo bot Telegram: lo stesso token su due bot va in conflitto.
- Scenari da coprire: senza GitHub né PC; rilancio (con `--pc-key`); clone, push e pull dal PC (`ssh://brain@<host>:2222/home/brain/brain.git`); GitHub aggiunto dopo; `restore pulito` e reinstallazione dallo stesso repo GitHub, con il vault importato.
- `lxc` va lanciato sull'host. Dentro il container Ubuntu ha un finto `lxc` che installa lo snap lxd lì dentro.
- Il gruppo `lxd` equivale a root: Ubuntu ci mette l'utente da solo. Dopo il test: `sudo gpasswd -d giulio lxd`, oppure `sudo snap remove --purge lxd`.

## Test
python-telegram-bot 22.8 non è installato sull'host:
```bash
python3 -m venv /tmp/venv-test && /tmp/venv-test/bin/pip install -q python-telegram-bot==22.8
/tmp/venv-test/bin/python tests/test_capture.py
/tmp/venv-test/bin/python tests/test_undo.py
```
Dopo una modifica a `bot.py` serve un restart del container (`sudo docker compose restart`): `bot.py` è montato read-only e non viene ricostruito.

## Da NON toccare in /home/brain
Lì c'è l'infrastruttura del backup, che serve sia ad agent-dev sia al PC: `brain.git` (con il suo hook `post-receive` → `bin/mirror.sh`), il cron orario, `.ssh/`, `mirror.log` e l'utente `brain`. Per verificare il mirror: `sudo tail -3 /home/brain/mirror.log`. Per lo stesso motivo `install.sh` non si lancia su questo server senza chiedere: si prova in un container LXD (`brain-test`).
