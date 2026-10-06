"""Linux: the drive watcher, kernel events, locks, autostart, Steam's state, burning with xorriso,
and the real agent process end to end (virtual drive, no hardware needed)."""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from shelf import autostart, launch, media
from shelf.disc import DiscTag, build_iso, read_tag_from_iso
from shelf.stores import Steam

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")

if sys.platform.startswith("linux"):
    from shelf import linux

ROOT = Path(__file__).resolve().parent.parent


# ── the drive watcher ─────────────────────────────────────────────────────────

class Box:
    """Fake drives, media, clocks and burner mode."""
    def __init__(self):
        self.drives = ["/dev/sr0"]
        self.media = {"/dev/sr0": False}
        self.mono, self.boot = 100.0, 5000.0
        self.paused = False
        self.events, self.power = [], []

    def watcher(self, **kw):
        return linux.DriveWatcher(lambda kind, devs, m: self.events.append((kind, devs[0])), self.power.append,
                                  drives=lambda: list(self.drives), media=lambda d: self.media.get(d, False),
                                  clock=lambda: self.mono, boottime=lambda: self.boot, uevents=lambda: None,
                                  paused=lambda: self.paused, announces=lambda d: True, **kw)


def test_watcher_turns_media_changes_into_events():
    b = Box()
    w = b.watcher()
    assert w.tick(False, True) and b.events == []                  # nothing changed
    b.media["/dev/sr0"] = True
    w.tick(False, True)
    b.media["/dev/sr0"] = False
    w.tick(True, False)
    assert b.events == [("arrival", "/dev/sr0"), ("removal", "/dev/sr0")]
    assert w.tick(False, False) is False                           # not due, no event: drives untouched


def test_watcher_follows_usb_drives_coming_and_going():
    b = Box()
    w = b.watcher()
    b.drives.append("/dev/sr1")
    b.media["/dev/sr1"] = True                                     # plugged in with a disc inside
    w.tick(True, False)
    b.drives.remove("/dev/sr1")
    w.tick(True, False)
    assert b.events == [("arrival", "/dev/sr1"), ("removal", "/dev/sr1")]


def test_disc_present_at_start_is_no_event():
    b = Box()
    b.media["/dev/sr0"] = True
    w = b.watcher()
    w.tick(False, True)
    assert b.events == []


def test_wake_up_is_reported_once():
    b = Box()
    w = b.watcher()
    b.boot += 3600                                                 # slept an hour: boottime ran, monotonic did not
    w.tick(False, False)
    w.tick(False, False)
    assert b.power == ["resume"] and w.settle_until > b.mono


def test_burner_mode_pauses_the_watcher_and_ends_without_events():
    b = Box()
    w = b.watcher()
    b.paused = True
    b.media["/dev/sr0"] = True                                     # a disc burned with the window open
    assert w.tick(True, False) is True
    assert b.events == []
    b.paused = False
    w.tick(False, False)                                           # window closed: taken as it is
    assert b.events == []
    b.media["/dev/sr0"] = False
    w.tick(True, False)
    b.media["/dev/sr0"] = True
    w.tick(True, False)
    assert b.events == [("removal", "/dev/sr0"), ("arrival", "/dev/sr0")]


def test_paused_watcher_does_not_spin():
    b = Box()
    w = b.watcher()
    b.paused = True
    assert w.tick(False, False) is False                           # not due: the timer keeps running


def test_run_wakes_up_on_a_kernel_event():
    b = Box()
    ours, kernel = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
    ours.setblocking(False)
    w = linux.DriveWatcher(lambda kind, devs, m: b.events.append((kind, devs[0])), b.power.append,
                           drives=lambda: list(b.drives), media=lambda d: b.media.get(d, False),
                           uevents=lambda: ours, announces=lambda d: True)
    th = threading.Thread(target=w.run, daemon=True)
    th.start()
    time.sleep(0.3)
    assert w.events_ok                                             # kernel events: no polling every 2 s
    b.media["/dev/sr0"] = True
    kernel.send(b"change@/devices/pci0000:00/ata2/host1/target1:0:0/1:0:0:0/block/sr0\0ACTION=change\0"
                b"DEVPATH=/devices/pci0000:00/ata2/host1/target1:0:0/1:0:0:0/block/sr0\0SUBSYSTEM=block\0"
                b"DEVNAME=sr0\0DEVTYPE=disk\0DISK_MEDIA_CHANGE=1\0")
    deadline = time.time() + 3
    while not b.events and time.time() < deadline:
        time.sleep(0.05)
    w.stop()
    th.join(3)
    kernel.close()
    assert b.events == [("arrival", "/dev/sr0")] and not th.is_alive()


def test_session_end_is_noticed(tmp_path):
    assert not linux.session_alive({"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": str(tmp_path)})
    (tmp_path / "wayland-0").write_text("")
    assert linux.session_alive({"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": str(tmp_path), "DISPLAY": ":987"})
    assert not linux.session_alive({"DISPLAY": ":987"})            # no X server 987 here
    assert linux.session_alive({"DISPLAY": "localhost:10.0"})      # remote X: nothing to watch
    assert linux.session_alive({})                                  # started from a console
    b = Box()
    w = linux.DriveWatcher(lambda *a: None, b.power.append, drives=lambda: [], media=lambda d: False,
                           uevents=lambda: None, alive=lambda: False)
    w.ALIVE = 0.1
    th = threading.Thread(target=w.run, daemon=True)
    th.start()
    th.join(3)
    assert not th.is_alive()                                        # left by itself


def test_uevent_parsing():
    ev = linux.parse_uevent(b"change@/devices/x/block/sr0\0ACTION=change\0SUBSYSTEM=block\0DEVNAME=sr0\0"
                            b"DISK_MEDIA_CHANGE=1\0")
    assert ev["ACTION"] == "change" and ev["DISK_MEDIA_CHANGE"] == "1" and linux.is_optical_event(ev)
    assert not linux.is_optical_event(linux.parse_uevent(b"add@/devices/x/block/sda\0SUBSYSTEM=block\0DEVNAME=sda\0"))
    assert not linux.is_optical_event(linux.parse_uevent(b"libudev\0garbage"))


def test_drives_and_kernel_polling_from_sysfs(tmp_path, monkeypatch):
    sysb, dev = tmp_path / "sys", tmp_path / "dev"
    dev.mkdir()
    for name in ("sr0", "sr10", "sr1", "sda"):
        (sysb / name / "device").mkdir(parents=True)
        (dev / name).write_text("")
    (dev / "sr10").unlink()                                        # sysfs knows it, /dev does not (yet)
    (sysb / "sr0" / "device" / "vendor").write_text("HL-DT-ST\n")
    (sysb / "sr0" / "device" / "model").write_text("DVDRAM GP65NB60 \n")
    (sysb / "sr0" / "events").write_text("media_change eject_request\n")
    (sysb / "sr0" / "events_poll_msecs").write_text("-1\n")
    (sysb / "sr1" / "events").write_text("\n")
    dfl = tmp_path / "dfl"
    dfl.write_text("2000\n")
    monkeypatch.setattr(linux, "SYS_BLOCK", sysb)
    monkeypatch.setattr(linux, "DEV", dev)
    monkeypatch.setattr(linux, "DFL_POLL", dfl)
    assert linux.optical_drives() == [str(dev / "sr0"), str(dev / "sr1")]
    assert linux.drive_label(str(dev / "sr0")) == "HL-DT-ST DVDRAM GP65NB60"
    assert linux.drive_label(str(dev / "sr1")) == "sr1" and linux.drive_name("/dev/sr1") == "sr1"
    assert linux.kernel_reports_media(str(dev / "sr0"))            # systemd's 2 s default polling
    dfl.write_text("0\n")
    assert not linux.kernel_reports_media(str(dev / "sr0"))        # polling off: the watcher polls itself
    assert not linux.kernel_reports_media(str(dev / "sr1"))


def test_drive_status_of_something_that_is_not_a_drive(tmp_path):
    f = tmp_path / "plain"
    f.write_text("x")
    assert linux.drive_status(str(f)) == linux.CDS_NO_INFO
    assert linux.drive_status(str(tmp_path / "missing")) == linux.CDS_NO_INFO
    assert linux.volume_info(str(f)) is None


# ── locks ─────────────────────────────────────────────────────────────────────

def test_single_instance_and_burner_locks():
    fd = linux.single_instance()
    try:
        assert fd is not None and linux.agent_running()
        assert linux.single_instance() is None                    # a second agent backs off
    finally:
        os.close(fd)
    assert not linux.agent_running()
    b = linux.hold_burner_mode()
    assert linux.burner_mode_on()
    os.close(b)
    assert not linux.burner_mode_on()                              # released however the app ends


def test_stop_agent_sends_sigterm_to_the_lock_holder():
    code = ("import time, sys; sys.path.insert(0, %r); from shelf import linux; fd = linux.single_instance(); "
            "print('ready', flush=True); time.sleep(30)") % str(ROOT)
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=dict(os.environ))
    try:
        assert p.stdout.readline().strip() == "ready"
        assert linux.agent_running()
        assert linux.stop_agent()
        assert p.wait(5) == -signal.SIGTERM
        assert not linux.agent_running() and not linux.stop_agent()
    finally:
        p.kill()


# ── autostart ─────────────────────────────────────────────────────────────────

def test_desktop_exec_quoting():
    assert autostart.exec_arg("/usr/bin/python3") == "/usr/bin/python3"
    assert autostart.exec_arg("/home/ryu/Steam shit/main.py") == '"/home/ryu/Steam shit/main.py"'
    assert autostart.exec_arg('a"b$c') == '"a\\\\"b\\\\$c"'          # \" and \$, then \ written as \\
    assert autostart.exec_arg("100%") == "100%%"


def test_autostart_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(autostart, "self_command", lambda *a: ["/opt/my apps/python", "/opt/shelf/main.py", *a])
    assert not autostart.enabled()
    autostart.set_enabled(True)
    f = tmp_path / "autostart" / "steam-shelf-agent.desktop"
    text = f.read_text()
    assert 'Exec="/opt/my apps/python" /opt/shelf/main.py --agent' in text and autostart.enabled()
    f.write_text(text + "Hidden=true\n")                           # turned off in the desktop's settings
    assert not autostart.enabled()
    autostart.set_enabled(True)
    monkeypatch.setattr(autostart, "self_command", lambda *a: ["/usr/bin/python3", "/srv/main.py", *a])
    autostart.refresh()                                            # the app moved: the entry follows
    assert "Exec=/usr/bin/python3 /srv/main.py --agent" in f.read_text()
    autostart.set_enabled(False)
    assert not f.exists() and not autostart.enabled()


def test_self_command_prefers_the_appimage(tmp_path, monkeypatch):
    app = tmp_path / "SteamShelf.AppImage"
    app.write_text("")
    monkeypatch.setenv("APPIMAGE", str(app))
    assert launch.self_command("--agent") == [str(app), "--agent"]
    monkeypatch.delenv("APPIMAGE")
    assert launch.self_command("--agent")[-2:] == [str(ROOT / "main.py"), "--agent"]


# ── Steam on Linux ────────────────────────────────────────────────────────────

REGISTRY = '''"Registry"
{
\t"HKCU"
\t{
\t\t"Software"
\t\t{
\t\t\t"Valve"
\t\t\t{
\t\t\t\t"Steam"
\t\t\t\t{
\t\t\t\t\t"language"\t\t"spanish"
\t\t\t\t\t"RunningAppID"\t\t"%s"
\t\t\t\t}
\t\t\t}
\t\t}
\t}
}
'''


def test_running_game_from_registry_vdf(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / ".local" / "share" / "Steam"
    (root / "steamapps").mkdir(parents=True)
    st = Steam()
    assert st.root() == root and st.running_app_id() == "0"
    (tmp_path / ".steam").mkdir()
    (tmp_path / ".steam" / "registry.vdf").write_text(REGISTRY % "1259420")
    assert st.is_running("1259420") and not st.is_running("1593500")
    flat = tmp_path / ".var" / "app" / "com.valvesoftware.Steam" / ".steam"
    flat.mkdir(parents=True)
    (flat / "registry.vdf").write_text(REGISTRY % "1593500")
    later = time.time() + 10
    os.utime(flat / "registry.vdf", (later, later))                # the Flatpak Steam is the one in use
    assert st.is_running("1593500")


# ── burning with xorriso ──────────────────────────────────────────────────────

TOC = "Drive current: -outdev '/dev/sr0'\nMedia current: %s\nMedia status : %s\n"


def test_media_state_parsing():
    s = media.media_state(TOC % ("CD-R", "is blank"))
    assert s["present"] and s["blank"] and not s["rewritable"]
    s = media.media_state(TOC % ("DVD+RW", "is written , is appendable"))
    assert s["present"] and not s["blank"] and s["overwriteable"] and s["rewritable"]
    s = media.media_state(TOC % ("CD-RW", "is written , is closed"))
    assert s["rewritable"] and not s["overwriteable"]
    s = media.media_state(TOC % ("DVD-R sequential recording", "is written , is closed"))
    assert not s["rewritable"]
    assert not media.media_state(TOC % ("is not present", "is not present"))["present"]
    assert not media.media_state("libburn : FAILURE : Cannot open busy device '/dev/sr0'")["present"]


@pytest.fixture
def fake_xorriso(monkeypatch, tmp_path):
    """xorriso answering -toc with a given disc; records the burn / blank calls."""
    calls, toc = [], {"text": TOC % ("CD-R", "is blank")}
    monkeypatch.setattr(media, "xorriso", lambda: "/usr/bin/xorriso")
    monkeypatch.setattr(media.os, "access", lambda p, m: True)
    monkeypatch.setattr(media, "_release", lambda dev: None)

    def run(args, timeout):
        if "-toc" in args:
            return 0, toc["text"]
        calls.append(args)
        return 0, ""
    monkeypatch.setattr(media, "_run", run)
    return calls, toc


def test_burn_checks_the_disc_first(fake_xorriso, tmp_path):
    calls, toc = fake_xorriso
    iso = tmp_path / "x.iso"
    assert media.burn(iso, "/dev/sr0") == "burned"
    assert calls == [["/usr/bin/xorriso", "-as", "cdrecord", "-v", "-eject", "dev=/dev/sr0", str(iso)]]
    for disc, code in [(("CD-R", "is written , is closed"), "not_blank"),
                       (("is not present", "is not present"), "no_disc")]:
        toc["text"] = TOC % disc
        with pytest.raises(media.BurnError) as e:
            media.burn(iso, "/dev/sr0")
        assert e.value.code == code
    toc["text"] = TOC % ("DVD+RW", "is written , is appendable")     # overwriteable: written again
    assert media.burn(iso, "/dev/sr0") == "burned"
    with pytest.raises(media.BurnError) as e:
        media.burn(iso, "/etc/passwd")
    assert e.value.code == "no_disc"


def test_erase_only_rewritable_discs(fake_xorriso):
    calls, toc = fake_xorriso
    toc["text"] = TOC % ("DVD-R sequential recording", "is written , is closed")
    with pytest.raises(media.EraseError) as e:
        media.erase("/dev/sr0")
    assert e.value.code == "not_rewritable" and calls == []
    toc["text"] = TOC % ("CD-RW", "is blank")
    media.erase("/dev/sr0")                                        # already blank: nothing to do
    assert calls == []
    toc["text"] = TOC % ("CD-RW", "is written , is closed")
    media.erase("/dev/sr0")
    assert calls == [["/usr/bin/xorriso", "-outdev", "/dev/sr0", "-blank", "as_needed"]]


def test_no_xorriso_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(media, "xorriso", lambda: None)
    with pytest.raises(media.BurnError) as e:
        media.burn(tmp_path / "x.iso", "/dev/sr0")
    assert e.value.code == "no_xorriso"


@pytest.mark.skipif(not shutil.which("xorriso"), reason="xorriso not installed")
def test_real_xorriso_burns_and_erases_a_pseudo_drive(tmp_path, monkeypatch):
    """xorriso's stdio: pseudo-drive behaves like a DVD+RW: the real commands, no hardware."""
    monkeypatch.setattr(media, "_LINUX_DRIVE", __import__("re").compile(r"^stdio:/.+$"))
    monkeypatch.setattr(media.os, "access", lambda p, m: True)
    disc = tmp_path / "drive.img"
    disc.write_bytes(b"")
    drive = f"stdio:{disc}"
    a = build_iso(DiscTag("steam", "1259420", "Days Gone"), tmp_path / "a.iso")
    b = build_iso(DiscTag("steam", "1593500", "God of War"), tmp_path / "b.iso")
    assert media.burn(a, drive) == "burned" and read_tag_from_iso(disc).title == "Days Gone"
    assert media.burn(b, drive) == "burned" and read_tag_from_iso(disc).title == "God of War"
    media.erase(drive)
    assert read_tag_from_iso(disc) is None


# ── opening steam:// with xdg-open ───────────────────────────────────────────

def _fake_bin(tmp_path, name, body):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(0o755)
    return d


def test_xdg_open_result_is_checked(tmp_path, monkeypatch):
    log = tmp_path / "opened"
    path = lambda body: str(_fake_bin(tmp_path, "xdg-open", body)) + ":/usr/bin:/bin"   # noqa: E731
    monkeypatch.setenv("PATH", path(f'echo "$1" >> {log}; exit 0'))
    assert launch.open_uri("steam://rungameid/1259420")
    assert log.read_text().split() == ["steam://rungameid/1259420"]
    monkeypatch.setenv("PATH", path("exit 4"))
    assert not launch.open_uri("steam://rungameid/1")             # no handler: the caller falls back
    monkeypatch.setattr(launch, "OPEN_WAIT", 0.3)
    monkeypatch.setenv("PATH", path("sleep 5"))
    t0 = time.time()
    assert launch.open_uri("steam://rungameid/1")                 # still running: Steam is starting up
    assert time.time() - t0 < 2


# ── the real agent, end to end ────────────────────────────────────────────────

def test_agent_process_end_to_end(tmp_path):
    """python main.py --agent on this Linux box: the virtual drive takes a test disc, the agent
    reads it, ignores it without the app's allowance, launches it with one, stops on SIGTERM."""
    data, home = tmp_path / "data", tmp_path / "home"
    home.mkdir()
    opened = tmp_path / "opened"
    env = dict(os.environ, STEAMSHELF_DATA_DIR=str(data), HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               STEAMSHELF_TAKEOVER_WAIT="2",
               PATH=str(_fake_bin(tmp_path, "xdg-open", f'echo "$1" >> {opened}; exit 0')) + ":/usr/bin:/bin")
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"countdown": 0, "enabled": True}))
    tag = DiscTag("steam", "1259420", "Days Gone")
    iso = build_iso(tag, tmp_path / "t.iso")
    run = data / "run" / "agent.lock"

    def lock_held():
        import fcntl
        try:
            fd = os.open(run, os.O_RDWR)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except OSError:
            return True
        finally:
            os.close(fd)

    def log():
        try:
            return (data / "agent.log").read_text()
        except OSError:
            return ""

    def wait(cond, secs=8.0):
        end = time.time() + secs
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.1)
        return False

    err = open(tmp_path / "stderr.txt", "w")
    p = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--agent"], env=env,
                         stdout=subprocess.DEVNULL, stderr=err)
    try:
        assert wait(lambda: "agent" in log() and lock_held()), log()
        second = subprocess.run([sys.executable, str(ROOT / "main.py"), "--agent"], env=env, timeout=20)
        assert second.returncode == 0 and "another agent is already running" in log()

        img = data / "virtual-drive" / "disc.iso"
        img.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(iso, img)                                     # no allowance: a leftover
        assert wait(lambda: "not a test started from the app" in log()), log()
        img.unlink()

        (data / "test_allow.json").write_text(json.dumps({"disc_id": tag.disc_id, "until": time.time() + 60}))
        shutil.copyfile(iso, img.with_suffix(".tmp"))
        os.replace(img.with_suffix(".tmp"), img)                      # what "Test" does
        assert wait(lambda: opened.exists()), log()
        # Steam is not installed in this HOME: the game's store page opens instead
        assert opened.read_text().split() == ["https://store.steampowered.com/app/1259420/"]
        assert "VIRTUAL disc in (media=True) -> launch" in log()

        p.send_signal(signal.SIGTERM)                                 # what "Game mode off" does
        assert p.wait(10) == 0
        assert "agent stopped" in log() and not lock_held()
    finally:
        if p.poll() is None:
            p.kill()
        err.close()


def test_new_agent_takes_over_when_the_old_one_leaves(tmp_path):
    """Logging out and in again where the old session's agent takes a few seconds to go."""
    data = tmp_path / "data"
    data.mkdir()
    env = dict(os.environ, STEAMSHELF_DATA_DIR=str(data), HOME=str(tmp_path), STEAMSHELF_TAKEOVER_WAIT="15")
    code = ("import time, sys; sys.path.insert(0, %r); from shelf import linux; fd = linux.single_instance(); "
            "print('ready', flush=True); time.sleep(30)") % str(ROOT)
    old = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=env)
    new = None
    try:
        assert old.stdout.readline().strip() == "ready"
        new = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--agent"], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.5)
        assert new.poll() is None                                     # waiting for the lock, not gone
        old.terminate()
        old.wait(5)
        log = data / "agent.log"
        end = time.time() + 10
        while time.time() < end and " up, " not in (log.read_text() if log.exists() else ""):
            time.sleep(0.1)
        assert " up, " in log.read_text()
        new.send_signal(signal.SIGTERM)
        assert new.wait(10) == 0
    finally:
        old.kill()
        if new is not None and new.poll() is None:
            new.kill()
