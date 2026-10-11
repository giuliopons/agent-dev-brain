import asyncio, os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(TELEGRAM_TOKEN="1:x", ALLOWED_USER_ID="42")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot

tmp = Path(tempfile.mkdtemp())
def sh(*a, cwd=None): return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout
sh("git", "init", "-q", "--bare", "-b", "main", str(tmp/"brain.git"))
sh("git", "clone", "-q", str(tmp/"brain.git"), str(tmp/"agent"))
A = tmp/"agent"
for c in (("user.name","agent-dev"),("user.email","a@x")): sh("git","config",*c,cwd=A)
def commit(name, subject, author=None):
    (A/name).write_text(subject + "\n"); sh("git","add","-A",cwd=A)
    extra = ["-c", f"user.name={author}"] if author else []
    sh("git", *extra, "commit", "-qm", subject, cwd=A); sh("git","push","-q","origin","HEAD:main",cwd=A)
commit("init.md", "init", author="pc")
bot.REPO, bot.LOG_FILE = A, tmp/"agent.log"
_run = bot.run
async def run(cmd, timeout=120, env=None, cwd=None): return await _run(cmd, timeout, env, cwd or bot.REPO)
bot.run = run
sent = []
async def reply(update, text): sent.append(text)
bot.reply = reply
def files(): return sorted(p.name for p in A.glob("*.md"))

async def main():
    # 1. task seguito da una cattura e da un commit dal PC: /undo chiede conferma e non tocca niente
    commit("task1.md", "agent: crea task1")
    commit("inbox.md", "inbox: prova cattura")
    commit("pc.md", "nota dal PC", author="pc")
    await bot.cmd_undo(None, None)
    assert sent[-1].startswith("⚠️") and "2 commit" in sent[-1] and "/undo_si" in sent[-1], sent[-1]
    assert "task1.md" in files()
    # 2. /undo_si annulla proprio quel task; cattura e commit dal PC restano
    await bot.cmd_undo_confirm(None, None)
    assert sent[-1].startswith("↩️") and "crea task1" in sent[-1], sent[-1]
    assert files() == ["inbox.md", "init.md", "pc.md"], files()
    # 3. /undo_si senza un /undo prima: non annulla niente
    commit("task2.md", "agent: crea task2")
    await bot.cmd_undo_confirm(None, None)
    assert sent[-1].startswith("🚫 Niente da confermare"), sent[-1]
    assert "task2.md" in files()
    # 4. task che è l'ultimo commit: /undo annulla subito, come prima
    await bot.cmd_undo(None, None)
    assert sent[-1].startswith("↩️") and "crea task2" in sent[-1], sent[-1]
    # 5. secondo /undo di fila: salta il revert appena fatto (task, non "altri") e trova task1 già annullato
    #    → nessun task rimasto
    await bot.cmd_undo(None, None)
    assert sent[-1].startswith("🚫 Nessun task"), sent[-1]
    # 6. due task di fila, /undo e /undo: il secondo annulla il task precedente senza conferma
    commit("task3.md", "agent: crea task3"); commit("task4.md", "agent: crea task4")
    await bot.cmd_undo(None, None); await bot.cmd_undo(None, None)
    assert sent[-2].startswith("↩️") and "task4" in sent[-2], sent[-2]
    assert sent[-1].startswith("↩️") and "task3" in sent[-1], sent[-1]
    for s in sent: print("--", s)
    print(sh("git","log","--format=%an | %s",cwd=A))
    print("OK")
asyncio.run(main())
