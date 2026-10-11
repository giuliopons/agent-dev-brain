# agent-dev-brain

## Scopo del progetto e utilizzo 

Lo scopo di questo "second brain" è imparare realmente cose, tenere traccia delle cose che sperimento, delle tecnologie, degli esempi, delle persone che incontro in un mondo dove la tecnologia corre sempre di più. Con l'uso di Claude Code, ChatGPT e altri strumenti AI si finisce per avere fatto cose, ma senza aver imparato nulla. Sai rifarle da solo? No. Che decisioni hai preso? Boh. Se da un lato miglioriamo i risultati, dall'altro stiamo perdendo controllo.

Per questo ora il mio flusso di lavoro prevede che quando provo qualcosa o noto qualcosa che mi interessa memorizzare, me lo appunto velocemente su delle note che invio via Telegram ad un mio bot, poi un giorno alla settimana rileggo le note, le approfondisco e le riscrivo io a mano nel "second brain" (un "vault" di file MarkDown organizzati e versionato con .git) spostandole nelle cartelle specifiche.

Questo mi permette di fissare alcuni concetti, perché ora come ora non è più importante la sintassi di un linguaggio ma la comprensione del processo, delle regole, del contesto e delle decisioni prese.

Rispetto ad altri second brain agentici (Karpathy) l'intenzione è diversa, sono io che devo imparare, non l'agente. Anche rispetto a modelli che devono "alleggerire" il carico informativo (Forte), l'idea è che l'umano può imparare di più.

Il mio vault ha questa organizzazione ma potete pensarlo come più si confà al vostro "primo cervello".

```
brain/
├── inbox/           # cattura grezza: note da Telegram (AAAA-MM-GG-hhmmss.md) da rileggere
│   └── attachments/ # foto e documenti allegati alle note
├── projects/        # cose con una fine; quando si chiudono vanno in archive/
├── areas/           # responsabilità continue, senza scadenza
├── resources/       # quello che ho imparato, per argomento
├── archive/         # progetti chiusi, aree abbandonate
├── CLAUDE.md        # regole delle note per Claude
└── .githooks/
    └── pre-commit   # gitleaks: blocca i commit con password e token
```

Un vault così strutturato può essere visionato ed esplorato con tool specifici come Obsidian che aiutano a mantenerlo leggibile, interconnesso e facilmente esplorabile.


## Il sistema

Questo sistema, nel mio caso, è installato su un MiniPC, un server casalingo e fa tre cose:

1. **Repository centrale del vault.** Un repo git bare con i contenuti del "secondo cervello": dal mio PC posso fare push e pull lì, e, se si vuole si può connettere una repository remota privata su GitHub.
2. **Bot Telegram per memorizzare cose grezze.** Dal telefono posso inviare brevi note, foto, link, vengono salvati in /inbox
3. **Bot Telegram con Claude Code.** Dal telefono posso fare domande in linguaggio naturale per estrarre informazioni dal second brain.

![Architettura: telefono → Telegram → container sul mini PC → brain.git → GitHub; il PC lavora con brain.git via VPN](docs/architettura.png)

Il bot per Telegram è pensato per **una sola persona**: risponde a un solo user id Telegram, nella chat privata e ignora tutti gli altri.

## Telegram

Il bot Telegram riceve i messaggi che possono essere di questo tipo:

- **un messaggio di testo** è un task per Claude: risponde con l'esito e l'hash del commit eventuale (gli puoi scrivere "segna in inbox che ho conosciuto Mario Rossi che si occupa di AI e mi ha suggerito di leggere...", ma anche "cerca Mario Rossi");
- **messaggi inoltrati, foto, documenti e video** vengono salvati grezzi in `inbox/`, con gli allegati in `inbox/attachments/` e un album in una sola nota. Arrivano subito, anche mentre Claude sta lavorando;
- **`/in <testo>`** salva un testo parola per parola;
- **comandi:** `/new` (nuova conversazione), `/undo` (annulla l'ultimo task di Claude; si può ripetere. Le catture non si annullano: se dopo il task ci sono catture o commit dal PC, chiede conferma con `/undo_si`), `/status`, `/log`.

I vocali non sono supportati, se siete abituati a parlare usate la trascrizione.

## Skill

Ovviamente se c'è un CLAUDE.md dentro al vault, Claude lo usa, quindi possiamo definire regole e meccanismi per migliorare l'organizzazione, tipo `/sistema-nota` che corregge la formattazione, sistema i titoli, le tag, ma non tocca il testo, oppure `/controlla-vault` che sistema link rotti ed altri errori...

L'agente deve aiutarmi a tenere in ordine la memoria, non a sostituirmi.


## Requisiti

- Un server **Ubuntu o Debian** sempre acceso (va bene un mini PC), con un utente che può usare `sudo`. Tutto il resto, Docker compreso, lo installa l'installer.
- Un **bot Telegram nuovo**, creato con @BotFather (ti dà il token), e il tuo **user id** numerico (te lo dice @userinfobot).
- Un **abbonamento Claude** (Pro o Max) oppure una **chiave API** Anthropic, a consumo.

Facoltativi:
- un **repo GitHub privato** per il backup. Se contiene già un vault viene importato, altrimenti crealo vuoto, senza README;
- la **chiave SSH pubblica del PC** (`~/.ssh/id_ed25519.pub`), per lavorare sul vault anche dal PC. Il server deve essere raggiungibile via SSH: in rete locale, oppure da fuori con una VPN.

## Installazione

Sul server:

```bash
git clone https://github.com/giuliopons/agent-dev-brain.git && cd agent-dev-brain
sudo bash install.sh
```

L'installer fa le domande una alla volta: token Telegram, user id, fuso orario, repo GitHub e chiave del PC (queste due si possono saltare). Poi:
1. crea l'utente `brain` e il repo centrale `/home/brain/brain.git`, che rifiuta force push e cancellazioni;
2. se hai indicato GitHub, ti mostra una deploy key da aggiungere al repo (Settings → Deploy keys, con "Allow write access") e aspetta che funzioni;
3. installa Docker e crea la chiave SSH del bot, valida solo per git e solo dal server stesso;
4. riempie il vault: lo importa da GitHub se c'è, altrimenti crea un **vault vuoto** da `template/`, con le cartelle PARA (`inbox/`, `projects/`, `areas/`, `resources/`, `archive/`), un `CLAUDE.md` con le regole delle note e l'hook gitleaks;
5. scrive `.env` (600) con le risposte e con il tuo uid/gid: il container gira con il tuo utente, così i file in `brain/` e `state/` restano tuoi;
6. costruisce l'immagine e ti fa scegliere l'accesso a Claude: abbonamento (lancia `claude setup-token`: apri il link, accedi, incolla il codice e poi il token che stampa) oppure chiave API. Se hai sbagliato scelta, esci da `setup-token` con Esc o Ctrl+C e premi Invio a vuoto: torni alla scelta;
7. avvia il bot e stampa i comandi per il PC.

Si può rilanciare quando vuoi: salta quello che è già fatto (i valori già in `.env`, il repo, le chiavi, il clone) e ripropone solo le domande facoltative rimaste senza risposta. Così si aggiunge il backup su GitHub in un secondo momento. 

Se durante l'installazione hai saltato la chiave del PC, puoi autorizzarlo dopo: copia la sua chiave pubblica SSH (sul PC: il contenuto di `~/.ssh/id_ed25519.pub`, una riga che inizia con `ssh-ed25519`) e incollala tra virgolette, sul server:

```bash
sudo bash install.sh --pc-key "ssh-ed25519 AAAA… utente@pc"
```

**Dal PC installare un clone del vault**, con la chiave autorizzata:

Avere anche il vault sul proprio PC è molto utile e comodo per la fase di verifica ed editing delle note per memorizzare i concetti, anche se opzionale, consiglio vivamente di farlo.

```bash
git clone brain@<server>:brain.git
git -C brain config core.hooksPath .githooks   # controllo dei segreti anche sul PC (serve gitleaks)
```

Se la chiave del PC non è quella di default (`~/.ssh/id_ed25519`), indicala nel clone, senza toccare `~/.ssh/config`: `git clone -c core.sshCommand="ssh -i <chiave> -o IdentitiesOnly=yes" brain@<server>:brain.git`.

Il PC fa push e pull **solo con il server** (nel mio caso il MiniPC): è il server che copia ogni modifica su GitHub. Non fare mai push su GitHub direttamente dal PC: GitHub avrebbe un commit che il server non conosce, il server smetterebbe di riuscire a copiarci sopra e il backup non si aggiornerebbe più. Con il clone fatto come sopra, GitHub non è tra i remote del PC e l'errore non può capitare.

**Hai già un vault?** Mettilo in un repo GitHub privato prima dell'installazione e indica quel repo: l'installer lo importa. Lo stesso vale per **rifare il server da zero**, per esempio dopo la rottura del disco: stesso comando, stesso repo GitHub, e il vault torna com'era (`.env` e `state/` vengono ricreati).

## Note comandi docker sul server MiniPC

Sul server:
```bash
sudo docker compose ps                  # sta girando?
sudo docker compose logs -f             # log del bot (Ctrl+C per uscire)
sudo docker compose restart             # riavvia il bot
sudo docker compose up -d               # avvio (riparte da solo anche dopo un reboot)
sudo docker compose exec agent-dev-brain bash # shell nel container
sudo tail -3 /home/brain/mirror.log     # esito delle copie su GitHub
```

Tutti i comandi docker vogliono `sudo`, di proposito: chi è nel gruppo `docker` ha di fatto i permessi di root, e quindi li avrebbe ogni processo che gira con il tuo utente.

**Aggiornare Claude Code:** `sudo docker compose build --no-cache && sudo docker compose up -d`. L'aggiornamento automatico dentro il container è spento (`DISABLE_AUTOUPDATER=1`).

## Appunti sulla sicurezza: cosa protegge e cosa no

Un bot che fa scrivere un'IA su un repo partendo da messaggi Telegram va installato sapendo dove sono i confini.

**Cosa protegge**
- **Chi può dare ordini.** Solo `ALLOWED_USER_ID` e solo in chat privata. Gli altri vengono ignorati senza risposta.
- **Testi di terzi.** Un messaggio inoltrato non diventa mai un'istruzione per Claude: viene solo salvato.
- **La storia del vault.** `brain.git` rifiuta force push e cancellazioni di branch: ogni modifica si annulla con `git revert` (`/undo`), e GitHub ha una copia.
- **Accesso al repo centrale.** La chiave del bot è in `authorized_keys` con `restrict,from="127.0.0.1,::1"`: solo git (git-shell), niente tunnel, valida solo dal server stesso.
- **Segreti nelle note.** Ogni commit del bot passa da gitleaks: tramite l'hook `.githooks/pre-commit` del vault se c'è, altrimenti direttamente. Il wrapper `/opt/githooks/pre-commit` è di root, quindi l'agente non può modificarlo (lo script del vault sì: vedi sotto).
- **Il server.** Claude gira in un container, con un utente non root e un limite di 1 GB di memoria. `.env` resta fuori dal container, e il token Telegram viene tolto dall'ambiente passato a Claude.

**Cosa NON protegge**
- **Prompt injection rimandata.** Gli inoltri finiscono in `inbox/` senza passare da Claude, ma quando poi chiedi a Claude di sistemare l'inbox li legge, e un testo malevolo può contenere istruzioni. Lo stesso vale per le pagine web che Claude apre.
- **Gli strumenti di Claude non sono limitati.** Claude viene lanciato con `--dangerously-skip-permissions`. Con quel flag, `--allowedTools` non restringe niente: Claude ha shell completa e accesso al web dentro il container. Il confine vero è il container, che usa `network_mode: host` (serve per arrivare a `127.0.0.1:22`) e quindi raggiunge anche i servizi in ascolto in locale sul server.
- **I segreti nell'ambiente di Claude.** Il token di Claude è per forza nel suo ambiente. Il token Telegram ne è escluso, ma un'istruzione malevola potrebbe comunque leggerlo dal processo del bot, che gira con lo stesso utente. gitleaks ferma gli errori, non chi lo aggira con `git commit --no-verify` o modificando `.githooks/pre-commit` nel vault.
- **Il tuo account Telegram.** Chi controlla il tuo account controlla il bot.

## File del progetto

| Percorso | Cosa |
|---|---|
| `bot.py` | il bot |
| `Dockerfile`, `docker-compose.yml` | immagine e servizio |
| `install.sh` | installazione e reinstallazione: utente `brain` (git-shell), `brain.git`, mirror su GitHub con cron orario di recupero, Docker, chiave del bot, clone, `.env`, avvio |
| `template/` | il vault vuoto creato al primo avvio, se non c'è niente da importare |
| `.env` (600, non versionato) | `TELEGRAM_TOKEN`, `ALLOWED_USER_ID`, `CLAUDE_CODE_OAUTH_TOKEN` o `ANTHROPIC_API_KEY`, `TZ`, `AGENT_UID`/`AGENT_GID` |
| `brain/` (non versionato) | clone del vault su cui lavora l'agente (autore `agent-dev`) |
| `state/capture/` | secondo clone, usato solo per la cattura in `inbox/`. Così le catture non finiscono nei commit dei task e `/undo` non le annulla |
| `state/agent.log` | una riga per task: data, istruzione, esito, hash |
| `state/session.json` | sessione Claude corrente (`/new` la cancella) |
| `state/claude/` | config e sessioni di Claude Code (`~/.claude` del container) |
| `state/ssh/` | chiave del bot, known_hosts, config (montata read-only) |

## Appunti su problemi vari nell'uso di questo sistema

- **Il bot non risponde** → `sudo docker compose ps` e `logs`. Token revocato? `.env` salvato?
- **"Claude è uscito con errore"** → token scaduto (dura circa un anno): svuota `CLAUDE_CODE_OAUTH_TOKEN=` in `.env` e rilancia `sudo bash install.sh`, che ripropone la scelta dell'accesso a Claude. Lo stesso vale per passare dall'abbonamento alla chiave API, o viceversa. Se l'errore parla di sessione: `/new`.
- **Task fallito o commit rifiutato da gitleaks** → le modifiche sono in `git stash` del clone: `git -C brain stash list`, `stash show -p`, poi `stash drop` (o `pop` per recuperarle).
- **pull --rebase fallito** → conflitto con un commit fatto altrove. Il bot si ferma senza toccare niente: risolvi a mano in `brain/`. Per usare git dall'host: `GIT_SSH_COMMAND="ssh -i state/ssh/id_ed25519 -o UserKnownHostsFile=state/ssh/known_hosts -o IdentitiesOnly=yes"`.
- **Cattura "❌ Non salvato"** → l'errore è nel messaggio. Se il commit è stato rifiutato da gitleaks, la nota è in `git -C state/capture stash list`. Un push fallito resta committato nel clone di cattura e riparte con la cattura successiva.
- **`ERRORE push GitHub` in `mirror.log`** → deploy key mancante o senza permesso di scrittura, oppure qualcuno ha fatto push su GitHub direttamente. Per riprovare a mano: `sudo -u brain -H /home/brain/bin/mirror.sh`.
- **Deploy key compromessa o persa** → cancellala su GitHub, poi `sudo rm /home/brain/.ssh/github_deploy*` e `sudo -u brain ssh-keygen -q -t ed25519 -N "" -f /home/brain/.ssh/github_deploy`, e aggiungi su GitHub la nuova `github_deploy.pub` con "Allow write access". Rilanciare `install.sh` non basta: con GitHub già configurato salta la deploy key.
- **Chiave del bot compromessa** → togli la sua riga da `/home/brain/.ssh/authorized_keys`, cancella `state/ssh/id_ed25519*` e rilancia `sudo bash install.sh`, che ne crea una nuova.
- **Token Telegram compromesso** → @BotFather `/revoke`, nuovo token in `.env`, `sudo docker compose up -d`.

## Licenza

MIT
