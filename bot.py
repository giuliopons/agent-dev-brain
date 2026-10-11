"""agent-dev: bot Telegram che esegue istruzioni con Claude Code sul vault brain.

Flusso di un messaggio:
  git pull --rebase  ->  claude -p "<messaggio>"  ->  git commit  ->  git push  ->  risposta

Messaggi inoltrati, foto, documenti, video e /in <testo> invece non passano da
Claude: vengono salvati così come sono in inbox/ (cattura, ex brain-bot).

Comandi: /in /new /undo /status /log
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

# --- Configurazione -------------------------------------------------------

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])

REPO = Path("/work/brain")                 # clone del vault (volume ./brain)
STATE = Path("/state")                     # volume ./state
SESSION_FILE = STATE / "session.json"      # session_id di Claude per --resume
LOG_FILE = STATE / "agent.log"             # una riga per task

CLAUDE_TIMEOUT = 15 * 60                   # secondi
MAX_TURNS = "30"
ALLOWED_TOOLS = "Read,Edit,Write,Glob,Grep,Bash(git:*)"
TELEGRAM_MAX = 4096                        # lunghezza massima di un messaggio

CAPTURE = STATE / "capture"                # clone usato solo per la cattura in inbox/
INBOX = CAPTURE / "inbox"
ATTACH = INBOX / "attachments"
TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Rome")  # ora nei nomi delle note in inbox/
MAX_DOWNLOAD = 20 * 1024 * 1024            # oltre, la Bot API non fa scaricare i file

# Variabili d'ambiente per Claude: tutte tranne il token del bot,
# così Claude non può leggerlo nemmeno per sbaglio.
CLAUDE_ENV = {k: v for k, v in os.environ.items() if k != "TELEGRAM_TOKEN"}

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO
)
# httpx logga ogni richiesta a Telegram (anche l'URL col token): lo zittisco
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("agent-dev")

# Un solo task alla volta: chi arriva mentre il lock è preso riceve "occupato"
lock = asyncio.Lock()
# La cattura ha il suo lock e il suo clone: non aspetta Claude e non finisce
# nei suoi commit (quindi /undo non la tocca). I messaggi aspettano in coda.
capture_lock = asyncio.Lock()
album_notes = {}                           # media_group_id -> nota già creata
pending_undo = None                        # hash del task che /undo_si può annullare


# --- Funzioni di supporto -------------------------------------------------

async def run(cmd, timeout=120, env=None, cwd=REPO):
    """Lancia un comando nel vault senza bloccare il bot.

    subprocess.run è "bloccante": con asyncio.to_thread gira in un thread a parte,
    così nel frattempo il bot può rispondere a /status.
    Restituisce un CompletedProcess (returncode, stdout, stderr).
    """
    return await asyncio.to_thread(
        subprocess.run, cmd, cwd=cwd, capture_output=True, text=True,
        timeout=timeout, env=env,
    )


async def git(*args):
    """Scorciatoia: git("status", "-s") -> run(["git", "status", "-s"])."""
    return await run(["git", *args])


async def head():
    """Hash del commit attuale (HEAD)."""
    return (await git("rev-parse", "HEAD")).stdout.strip()


async def pull():
    """git pull --rebase. Se fallisce (es. conflitto) annulla il rebase.

    Restituisce None se tutto ok, altrimenti il messaggio d'errore.
    Non risolve mai i conflitti da solo.
    """
    p = await git("pull", "--rebase")
    if p.returncode == 0:
        return None
    await git("rebase", "--abort")   # se non c'era un rebase in corso fallisce: va bene
    return (p.stderr or p.stdout).strip()


async def push():
    """git push. Se viene rifiutato perché nel frattempo qualcuno (brain-bot)
    ha pushato, si riallinea con un pull --rebase e riprova una volta.

    Restituisce None se tutto ok, altrimenti il messaggio d'errore.
    """
    p = await git("push")
    if p.returncode == 0:
        return None
    error = await pull()
    if error:
        return "push rifiutato e pull --rebase fallito:\n" + error
    p = await git("push")
    return None if p.returncode == 0 else (p.stderr or p.stdout).strip()


async def put_aside(reason):
    """Mette da parte le modifiche non committate con git stash,
    così l'albero torna pulito e il prossimo pull funziona. Niente va perso:
    si recuperano con `git stash list` / `git stash pop` nel clone."""
    await git("stash", "push", "--include-untracked", "-m", f"agent-dev: {reason}")


async def last_task_to_undo():
    """Trova l'ultimo commit di un task di agent-dev ("agent: …") non ancora annullato.

    Salta i commit di brain-bot e i miei (non li tocca mai), i commit "Revert …"
    (così un secondo /undo annulla il task precedente, non l'annullamento)
    e i task già annullati: git revert scrive "This reverts commit <hash>"
    nel messaggio, e da lì si capisce quali sono.
    Restituisce (hash, "abc1234 agent: …", data, altri) oppure None. "altri" sono gli oggetti
    dei commit più recenti del task che non sono task né annullamenti (catture, commit dal PC):
    se ce ne sono, /undo chiede conferma prima di annullare.
    """
    # un commit per record: hash, autore, data, oggetto, corpo separati da \x1f; record separati da \x1e
    out = (await git("log", "-30", "--date=format:%d/%m %H:%M",
                     "--format=%H%x1f%an%x1f%ad%x1f%s%x1f%b%x1e")).stdout
    commits = [c.strip("\n").split("\x1f") for c in out.split("\x1e") if c.strip()]
    already_reverted = {
        line.split()[-1].rstrip(".")
        for *_, body in commits
        for line in body.splitlines()
        if line.startswith("This reverts commit ")
    }
    others = []
    for commit_hash, author, date, subject, _ in commits:   # dal più recente
        is_task = author == "agent-dev" and subject.startswith(("agent: ", 'Revert "agent: '))
        if (author == "agent-dev" and subject.startswith("agent: ")
                and commit_hash not in already_reverted):
            return commit_hash, f"{commit_hash[:7]} {subject}", date, others
        if not is_task:
            others.append(subject)
    return None


def load_session():
    """Legge il session_id salvato, oppure None."""
    try:
        return json.loads(SESSION_FILE.read_text())["session_id"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None


def save_session(session_id):
    SESSION_FILE.write_text(json.dumps({"session_id": session_id}))


def write_log(instruction, outcome, commit=""):
    """Aggiunge una riga a state/agent.log: data | istruzione | esito | hash."""
    short = " ".join(instruction.split())[:80]
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} | {short} | {outcome} | {commit}\n"
    with LOG_FILE.open("a") as f:
        f.write(line)


def commit_message(instruction):
    """Messaggio di commit: 'agent: ' + inizio dell'istruzione, su una riga."""
    text = " ".join(instruction.split())
    return "agent: " + (text[:60] + "…" if len(text) > 60 else text)


async def reply(update, text):
    """Risponde spezzando i testi più lunghi del limite di Telegram.
    Testo semplice (niente Markdown), così caratteri strani non danno errore."""
    text = text.strip() or "(nessun testo)"
    for i in range(0, len(text), TELEGRAM_MAX):
        await update.effective_message.reply_text(text[i:i + TELEGRAM_MAX])


# --- Cattura in inbox/ (senza Claude) --------------------------------------
# Il contenuto viene salvato grezzo: niente titoli, niente riscritture.

async def capture_git(*args):
    """git nel clone di cattura; solleva RuntimeError se fallisce."""
    p = await run(["git", *args], cwd=CAPTURE)
    if p.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {(p.stderr or p.stdout).strip()}")
    return p.stdout


async def ensure_capture_clone():
    """Al primo avvio clona brain.git in /state/capture, con le stesse impostazioni di /work/brain."""
    if (CAPTURE / ".git").exists():
        return
    url = (await git("remote", "get-url", "origin")).stdout.strip()
    ssh = (await git("config", "--get", "core.sshCommand")).stdout.strip()
    opts = ["-c", f"core.sshCommand={ssh}"] if ssh else []
    p = await run(["git", "clone", "-q", *opts, url, str(CAPTURE)], cwd=STATE)
    if p.returncode != 0:
        raise RuntimeError("clone per la cattura fallito: " + (p.stderr or p.stdout).strip())
    for key in ("core.hooksPath", "user.name", "user.email"):
        value = (await git("config", "--get", key)).stdout.strip()
        if value:
            await capture_git("config", key, value)
    log.info("creato il clone per la cattura in %s", CAPTURE)


async def capture_pull():
    try:
        await capture_git("pull", "-q", "--rebase", "origin", "main")
    except RuntimeError:
        await run(["git", "rebase", "--abort"], cwd=CAPTURE)
        raise


async def capture_commit_and_push(message):
    # -A inbox: include anche eventuali file rimasti da un errore precedente
    await capture_git("add", "-A", "inbox")
    try:
        await capture_git("commit", "-q", "-m", message)
    except RuntimeError:
        # di solito gitleaks: metto da parte, così la prossima cattura non si blocca
        await run(["git", "stash", "push", "--include-untracked", "-m",
                   "cattura: commit rifiutato"], cwd=CAPTURE)
        raise
    for _ in range(3):
        try:
            await capture_git("push", "-q", "origin", "HEAD:main")
            return
        except RuntimeError:
            # qualcuno (PC, task di Claude) ha pushato nel frattempo: riallineo e riprovo
            await asyncio.sleep(2)
            await capture_pull()
    raise RuntimeError("push fallito dopo 3 tentativi (il commit resta nel clone di cattura)")


def unique_path(directory, stem, ext):
    path, n = directory / f"{stem}{ext}", 2
    while path.exists():
        path, n = directory / f"{stem}-{n}{ext}", n + 1
    return path


def apply_text_links(text, entities):
    """Trasforma i testi con link nascosto ('text_link') in [testo](url).

    Gli offset di Telegram sono in unità UTF-16 (le emoji contano 2),
    quindi si lavora sulla stringa codificata UTF-16.
    """
    links = [e for e in entities or [] if e["type"] == "text_link"]
    if not links:
        return text
    raw, out, pos = text.encode("utf-16-le"), [], 0
    for e in sorted(links, key=lambda e: e["offset"]):
        start, end = e["offset"] * 2, (e["offset"] + e["length"]) * 2
        out.append(raw[pos:start].decode("utf-16-le"))
        out.append(f"[{raw[start:end].decode('utf-16-le')}]({e['url']})")
        pos = end
    out.append(raw[pos:].decode("utf-16-le"))
    return "".join(out)


def forward_source(msg):
    """Da dove arriva un messaggio inoltrato (dict della Bot API), in forma leggibile."""
    o = msg.get("forward_origin")
    if not o:
        return None
    if o["type"] == "user":
        u = o["sender_user"]
        return " ".join(filter(None, [u.get("first_name"), u.get("last_name")]))
    if o["type"] == "hidden_user":
        return o["sender_user_name"]
    if o["type"] == "chat":
        return o["sender_chat"].get("title")
    if o["type"] == "channel":
        chat = o["chat"]
        if chat.get("username"):
            return f"{chat.get('title')} (https://t.me/{chat['username']}/{o['message_id']})"
        return chat.get("title")
    return None


def frontmatter(dt, fwd):
    lines = ["---", f"created: {dt:%Y-%m-%dT%H:%M}", "source: telegram"]
    if fwd:
        lines.append(f"forwarded_from: {json.dumps(fwd, ensure_ascii=False)}")
    return "\n".join(lines + ["---", "", ""])


def attachment_of(msg):
    """(file_id, estensione di riserva, dimensione) dell'allegato, oppure None."""
    if msg.get("photo"):
        p = msg["photo"][-1]                         # l'ultima è la più grande
        return p["file_id"], ".jpg", p.get("file_size", 0)
    if msg.get("document"):
        d = msg["document"]
        return d["file_id"], Path(d.get("file_name", "")).suffix or ".bin", d.get("file_size", 0)
    if msg.get("video"):
        v = msg["video"]
        return v["file_id"], ".mp4", v.get("file_size", 0)
    return None


async def download(bot, file_id, stem, default_ext):
    f = await bot.get_file(file_id)
    ext = Path(f.file_path or "").suffix or default_ext
    dest = unique_path(ATTACH, stem, ext)
    await f.download_to_drive(dest)
    return dest


async def capture(update, context, text):
    """Salva il messaggio in inbox/ così com'è, poi commit e push. Risponde ✅ o ❌."""
    msg = update.effective_message.to_dict()
    attachment = attachment_of(msg)
    if not text and not attachment:
        await reply(update, "🤷 Niente da salvare.")
        return
    if attachment and attachment[2] > MAX_DOWNLOAD:
        await reply(update, "❌ File oltre 20 MB: Telegram non lo lascia scaricare ai bot.")
        return

    dt = update.effective_message.date.astimezone(TZ)
    stem = f"{dt:%Y-%m-%d-%H%M%S}"
    async with capture_lock:
        try:
            await ensure_capture_clone()
            await capture_pull()
            ATTACH.mkdir(parents=True, exist_ok=True)

            body = []
            if attachment:
                saved = await download(context.bot, attachment[0], stem, attachment[1])
                body.append(f"![[{saved.name}]]")
            if text:
                body.append(text)

            group = msg.get("media_group_id")
            if group and group in album_notes and album_notes[group].exists():
                # foto successiva dello stesso album: va nella nota già creata
                note = album_notes[group]
                with open(note, "a", encoding="utf-8") as f:
                    f.write("\n" + "\n\n".join(body) + "\n")
            else:
                note = unique_path(INBOX, stem, ".md")
                note.write_text(frontmatter(dt, forward_source(msg)) + "\n\n".join(body) + "\n",
                                encoding="utf-8")
                if group:
                    album_notes[group] = note

            first_line = (text.splitlines() or ["allegato"])[0][:60]
            await capture_commit_and_push(f"inbox: {first_line}")
        except Exception as e:
            log.error("cattura fallita: %s", e)
            await reply(update, f"❌ Non salvato: {e}")
            return
    # niente ".md": Telegram trasformerebbe il nome del file in un link (.md = Moldavia)
    rel = note.relative_to(CAPTURE).with_suffix("")
    log.info("salvato %s", rel)
    await reply(update, f"✅ {rel}")


async def handle_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inoltri, foto, documenti, video: sempre in inbox/, mai a Claude."""
    m = update.effective_message
    text = apply_text_links(m.text or m.caption or "",
                            [e.to_dict() for e in (m.entities or m.caption_entities or ())])
    await capture(update, context, text)


async def cmd_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/in <testo>: salva il testo parola per parola, senza passare da Claude."""
    m = update.effective_message
    text = apply_text_links(m.text or "", [e.to_dict() for e in m.entities or ()])
    text = re.sub(r"^/in(@\w+)?\s*", "", text).strip()
    if not text:
        await reply(update, "Uso: /in testo da salvare in inbox")
        return
    await capture(update, context, text)


async def reject_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, "🎙 Vocali non ancora supportati: scrivilo, per ora.")


# --- Filtro utenti: gira PRIMA di tutto il resto ---------------------------

async def only_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Se il messaggio non viene da ALLOWED_USER_ID: nessuna risposta,
    solo una riga nel log, e ApplicationHandlerStop ferma ogni altro handler."""
    user, chat = update.effective_user, update.effective_chat
    if user is None or user.id != ALLOWED_USER_ID or (chat and chat.type != "private"):
        log.warning("ignorato utente non autorizzato: %s",
                    user.id if user else "sconosciuto")
        raise ApplicationHandlerStop


# --- Il task: un messaggio di testo = un'istruzione per Claude -------------

async def handle_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instruction = update.effective_message.text
    if lock.locked():
        await reply(update, "⏳ Occupato con un altro task. Riprova tra poco (/status).")
        return

    async with lock:
        await reply(update, "🤖 Ci lavoro…")

        # 1. allineo il clone con brain.git
        error = await pull()
        if error:
            write_log(instruction, "pull fallito")
            await reply(update, "❌ git pull --rebase fallito, mi fermo:\n" + error)
            return
        start = await head()

        # 2. Claude Code headless
        session_id = load_session()
        cmd = ["claude", "-p", instruction,
               "--output-format", "json",
               "--max-turns", MAX_TURNS,
               "--allowedTools", ALLOWED_TOOLS,
               "--dangerously-skip-permissions"]
        if session_id:
            cmd += ["--resume", session_id]

        try:
            p = await run(cmd, timeout=CLAUDE_TIMEOUT, env=CLAUDE_ENV)
        except subprocess.TimeoutExpired:
            await put_aside("timeout")
            write_log(instruction, "timeout")
            await reply(update, f"⌛ Claude non ha finito entro {CLAUDE_TIMEOUT // 60} minuti. "
                                "Eventuali modifiche sono in git stash.")
            return

        try:
            result = json.loads(p.stdout)
        except json.JSONDecodeError:
            await put_aside("errore claude")
            write_log(instruction, f"errore claude (exit {p.returncode})")
            hint = "\nSe la sessione non esiste più prova /new." if session_id else ""
            await reply(update, f"❌ Claude è uscito con errore (exit {p.returncode}):\n"
                                + (p.stderr or p.stdout)[-1500:] + hint)
            return

        # 3. salvo la sessione, così il prossimo messaggio continua la conversazione
        if result.get("session_id"):
            save_session(result["session_id"])

        answer = result.get("result") or ""
        if result.get("is_error"):
            await put_aside("errore claude")
            write_log(instruction, "errore claude")
            await reply(update, "❌ Claude ha restituito un errore:\n" + answer)
            return
        if result.get("subtype") == "error_max_turns":
            answer = f"⚠️ Raggiunto il limite di {MAX_TURNS} turni: lavoro forse incompleto.\n\n" + answer

        # 4. commit (se ci sono modifiche) e push (se ci sono commit nuovi)
        if (await git("status", "--porcelain")).stdout.strip():
            await git("add", "-A")
            c = await git("commit", "-m", commit_message(instruction))
            if c.returncode != 0:
                # di solito è gitleaks che ha trovato un possibile segreto
                await put_aside("commit rifiutato")
                write_log(instruction, "commit rifiutato")
                await reply(update, answer + "\n\n❌ Commit rifiutato (gitleaks?). "
                                    "Modifiche messe da parte con git stash:\n"
                                    + (c.stderr or c.stdout)[-1500:])
                return

        end = await head()
        if end == start:
            write_log(instruction, "ok, nessuna modifica")
            await reply(update, answer + "\n\n(nessuna modifica al vault)")
            return

        error = await push()
        if error:
            write_log(instruction, "push fallito", end[:7])
            await reply(update, answer + "\n\n❌ Commit fatto ma push fallito:\n" + error)
            return

        # 5. risposta: testo di Claude + riepilogo dei file cambiati
        stat = (await git("diff", "--stat", start, end)).stdout
        write_log(instruction, "ok", end[:7])
        await reply(update, f"{answer}\n\n✅ {end[:7]} pushato\n{stat}")


# --- Comandi ---------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update,
                "Scrivimi cosa fare sul vault: lo faccio con Claude Code, poi commit e push.\n"
                "Inoltri, foto, documenti e video li salvo in inbox/ così come sono, senza Claude.\n\n"
                "/in testo – salva il testo in inbox/ parola per parola\n"
                "/new – nuova conversazione con Claude\n"
                "/undo – annulla l'ultimo task di agent-dev (git revert; ripetibile)\n"
                "/undo_si – conferma, se dopo il task ci sono catture o commit dal PC\n"
                "/status – sessione, ultimo commit, occupato sì/no\n"
                "/log – ultimi task")


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SESSION_FILE.unlink(missing_ok=True)
    await reply(update, "🆕 Nuova sessione: il prossimo messaggio parte da zero.")


async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await undo(update, confirmed=False)


async def cmd_undo_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await undo(update, confirmed=True)


async def undo(update, confirmed):
    """git revert dell'ultimo task. Se dopo il task ci sono catture o commit dal PC,
    il task non è l'ultima cosa successa: prima di annullarlo chiede conferma (/undo_si)."""
    global pending_undo
    if lock.locked():
        await reply(update, "⏳ Occupato, riprova tra poco.")
        return
    async with lock:
        error = await pull()
        if error:
            await reply(update, "❌ git pull --rebase fallito:\n" + error)
            return
        target = await last_task_to_undo()
        if target is None:
            await reply(update, "🚫 Nessun task di agent-dev da annullare negli ultimi 30 commit.")
            return
        commit_hash, description, date, others = target
        if confirmed and pending_undo != commit_hash:
            # niente da confermare, o nel frattempo è cambiato il task da annullare
            pending_undo = None
            await reply(update, "🚫 Niente da confermare: rilancia /undo.")
            return
        if others and not confirmed:
            pending_undo = commit_hash
            shown = "\n".join(f"• {s}" for s in others[:3]) + ("\n• …" if len(others) > 3 else "")
            await reply(update,
                        f"⚠️ L'ultimo task è del {date}: {description}\n\n"
                        f"Dopo ci sono {len(others)} commit che non sono task di Claude "
                        f"e restano come sono:\n{shown}\n\n"
                        "Per annullare comunque il task: /undo_si")
            return
        pending_undo = None
        r = await git("revert", "--no-edit", commit_hash)
        if r.returncode != 0:
            await git("revert", "--abort")
            await reply(update, "❌ git revert fallito:\n" + (r.stderr or r.stdout))
            return
        error = await push()
        if error:
            await reply(update, "❌ Revert fatto ma push fallito:\n" + error)
            return
        write_log("/undo " + description, "ok", (await head())[:7])
        await reply(update, f"↩️ Annullato: {description}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last = (await git("log", "-1", "--format=%h %an: %s")).stdout.strip()
    await reply(update,
                f"Sessione: {load_session() or 'nessuna'}\n"
                f"Ultimo commit: {last}\n"
                f"Occupato: {'sì' if lock.locked() else 'no'}")


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lines = LOG_FILE.read_text().splitlines()[-20:]
    except FileNotFoundError:
        lines = []
    await reply(update, "\n".join(lines) or "Log vuoto.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Errori imprevisti: li scrive nel log del container invece di perderli."""
    log.error("errore non gestito", exc_info=context.error)


# --- Avvio -----------------------------------------------------------------

def main():
    # concurrent_updates: senza, mentre gira un task anche /status aspetterebbe in coda
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()

    # group=-1: gira prima di tutti gli altri handler (group 0)
    app.add_handler(TypeHandler(Update, only_me), group=-1)

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("undo", cmd_undo))
    app.add_handler(CommandHandler("undo_si", cmd_undo_confirm))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("in", cmd_capture))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE, reject_voice))
    # prima dei task: un inoltro non deve mai diventare un'istruzione per Claude
    app.add_handler(MessageHandler(
        filters.FORWARDED | filters.PHOTO | filters.Document.ALL | filters.VIDEO, handle_capture))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task))
    app.add_error_handler(on_error)

    log.info("agent-dev avviato, utente autorizzato: %s", ALLOWED_USER_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
