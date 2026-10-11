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

## Test
python-telegram-bot 22.8 non è installato sull'host:
```bash
python3 -m venv /tmp/ptb && /tmp/ptb/bin/pip install -q python-telegram-bot==22.8
/tmp/ptb/bin/python tests/test_capture.py
/tmp/ptb/bin/python tests/test_undo.py
```
Dopo una modifica a `bot.py` serve un restart del container (`sudo docker compose restart`): `bot.py` è montato read-only e non viene ricostruito.

## Da NON toccare in /home/brain
Lì c'è l'infrastruttura del backup, che serve sia ad agent-dev sia al PC: `brain.git` (con il suo hook `post-receive` → `bin/mirror.sh`), il cron orario, `.ssh/`, `mirror.log` e l'utente `brain`. Per verificare il mirror: `sudo tail -3 /home/brain/mirror.log`. Per lo stesso motivo `install.sh` non si lancia su questo server senza chiedere: si prova in un container LXD (`brain-test`).
