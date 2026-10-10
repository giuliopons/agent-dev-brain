import asyncio, os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(TELEGRAM_TOKEN="1:x", ALLOWED_USER_ID="42")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot
from telegram import Update, Message
from telegram.ext import filters

tmp = Path(tempfile.mkdtemp())
def sh(*a, cwd=None): subprocess.run(a, cwd=cwd, check=True, capture_output=True)
sh("git", "init", "-q", "--bare", "-b", "main", str(tmp/"brain.git"))
sh("git", "clone", "-q", str(tmp/"brain.git"), str(tmp/"pc"))
for c in (("user.name","pc"),("user.email","pc@x")): sh("git","config",*c,cwd=tmp/"pc")
(tmp/"pc"/"note.md").write_text("x\n"); sh("git","add","-A",cwd=tmp/"pc"); sh("git","commit","-qm","init",cwd=tmp/"pc"); sh("git","push","-q","origin","main",cwd=tmp/"pc")
sh("git", "clone", "-q", str(tmp/"brain.git"), str(tmp/"agent"))
for c in (("user.name","agent-dev"),("user.email","a@x")): sh("git","config",*c,cwd=tmp/"agent")
(tmp/"state").mkdir()
bot.REPO, bot.STATE = tmp/"agent", tmp/"state"
bot.CAPTURE = tmp/"state"/"capture"; bot.INBOX = bot.CAPTURE/"inbox"; bot.ATTACH = bot.INBOX/"attachments"
_run = bot.run
async def run(cmd, timeout=120, env=None, cwd=None): return await _run(cmd, timeout, env, cwd or bot.REPO)
bot.run = run
sent = []
async def reply(update, text): sent.append(text)
bot.reply = reply
async def download(b, fid, stem, ext):
    d = bot.unique_path(bot.ATTACH, stem, ext); d.write_bytes(b"img"); return d
bot.download = download

class U:
    def __init__(self, d):
        d = {"message_id": 1, "date": 1760000000, "chat": {"id": 42, "type": "private"},
             "from": {"id": 42, "is_bot": False, "first_name": "G"}, **d}
        self.effective_message = Message.de_json(d, CTX)
        self.message = self.effective_message
def route(u):
    upd = Update(1, message=u.message)
    if filters.FORWARDED.check_update(upd) or filters.PHOTO.check_update(upd): return "capture"
    if (filters.TEXT & ~filters.COMMAND).check_update(upd): return "task"
    return "other"

class CTX: bot = None
async def main():
    fwd = U({"text": "guarda 😀 qui", "entities": [{"type":"text_link","offset":10,"length":3,"url":"https://e.com"}],
             "forward_origin": {"type":"channel","date":1,"message_id":7,"chat":{"id":-1,"type":"channel","title":"Canale","username":"can"}}})
    assert route(fwd) == "capture"
    assert route(U({"text": "riordina i link"})) == "task"
    await bot.handle_capture(fwd, CTX)
    inn = U({"text": "/in ciao\nseconda riga", "entities":[{"type":"bot_command","offset":0,"length":3}]})
    await bot.cmd_capture(inn, CTX)
    p1 = U({"photo":[{"file_id":"a","file_unique_id":"a","width":1,"height":1}], "media_group_id":"g", "caption":"album"})
    p2 = U({"photo":[{"file_id":"b","file_unique_id":"b","width":1,"height":1}], "media_group_id":"g"})
    assert route(p1) == "capture"
    await asyncio.gather(bot.handle_capture(p1, CTX), bot.handle_capture(p2, CTX))
    # concurrent push from PC between captures
    (tmp/"pc"/"pc.md").write_text("pc\n"); sh("git","add","-A",cwd=tmp/"pc"); sh("git","commit","-qm","pc",cwd=tmp/"pc"); sh("git","pull","-q","--rebase","origin","main",cwd=tmp/"pc"); sh("git","push","-q","origin","main",cwd=tmp/"pc")
    await bot.cmd_capture(U({"text": "/in dopo pc", "entities":[{"type":"bot_command","offset":0,"length":3}]}), CTX)
    print(sent)
    assert all(s.startswith("✅") for s in sent), sent
    log = subprocess.run(["git","-C",str(tmp/"brain.git"),"log","--format=%an %s","main"],capture_output=True,text=True).stdout
    print(log)
    files = subprocess.run(["git","-C",str(tmp/"brain.git"),"ls-tree","-r","--name-only","main"],capture_output=True,text=True).stdout
    print(files)
    for f in sorted(bot.INBOX.glob("*.md")): print("==", f.name); print(f.read_text())
    assert subprocess.run(["git","-C",str(tmp/"agent"),"status","--porcelain"],capture_output=True,text=True).stdout == ""
asyncio.run(main())
