# Steam Shelf

Put a disc in, the game starts.

Steam Shelf turns a blank CD-R or DVD-R into the physical copy of a game you
own on Steam. Burn one disc per game; every time that disc goes into the
drive, the game launches (Steam starts too if it was closed). If the game is
not installed, you land on its store page instead. Your PC feels like a
console, and the games you bought digitally finally have something you can
put on a shelf.

Part of the PimpMySteam ecosystem, next to Steam Curator and Steam Grunge Editor.
Works on **Windows and Linux**. Steam games, and any other game you add to Steam
(GOG, Epic, emulators…).

## Game mode and burner mode

- **Game mode**: Steam Shelf starts in the background when you log in (no window).
  Put a disc in and its game starts (or its store page opens).
- **Burner mode**: whenever the Steam Shelf window is open. You are making discs,
  so a disc going in does nothing: no card, no Steam. Close the window and game
  mode is back. The one exception is **Test with a virtual disc**, which behaves
  like game mode for that disc so you can see it work.

The "Game mode on/off" button turns the background part off entirely.

## How it works

- **The app** (`python main.py`): pick a game, then burn it, test it with a
  virtual disc, or just add it to your shelf.
- **The agent** (`python main.py --agent`): a small background process that
  starts when you log in and watches the disc drives. It runs whether the app or
  Steam is open or not, uses no CPU while idle, and has no window.
- **The disc describes itself**: a tiny `STEAMSHELF/DISC.JSON` says which
  game it is, plus the cover and a drive icon for Windows Explorer. Any PC with
  Steam Shelf can play it; nothing needs to be set up per disc.

### It never throws you into a game at boot

A game only starts when a disc is *inserted* while the PC is already on.

- A disc that is already in the drive when the PC starts (say the power went
  out) is never auto-launched. By default you get a small "In the drive: Play?"
  card instead; you can turn that off.
- The same goes for waking from sleep, when drives announce their discs again.
- A countdown card ("Starting in 5 · Cancel") comes before every launch. Set it
  to 0 to start at once.
- Settings › "Steam opens the game in": Steam desktop, or **Big Picture** for a
  TV / couch setup. With Big Picture, the card first opens Big Picture (starting
  Steam if it was closed), then the game or its store page opens inside it.

Rules and tests: `shelf/policy.py`, `tests/test_policy.py`.

### Safety

Anyone can burn a disc, so the tag is treated as untrusted: only known stores,
ids that match a strict pattern, and the launch link is built by Steam Shelf.
Nothing on a disc is ever executed (Windows has ignored `autorun` programs on
discs for years, and Steam Shelf only writes a label and an icon there).

## Try it without a blank disc

1. `pip install -r requirements.txt` then `python main.py` (Linux: see below).
2. **New disc** → pick a game → **Test with a virtual disc**.
3. The image goes into Steam Shelf's **virtual drive**, a folder the agent
   watches like one more CD/DVD drive. To the agent that is exactly a disc going
   in: it reads the disc, the countdown card appears and the game starts. Nothing
   is mounted, so it works on any PC (Windows' own image mounting is not needed).
4. Disc menu → **Eject the virtual disc**, and do it again. Closing the window
   ejects it too.
5. **Simulate the disc going in** shows the same card and launch without the
   agent at all.

The virtual drive only answers tests started from the app (for two minutes);
an image left in it does nothing. To try game mode with a real drive, burn a
disc, close Steam Shelf and put the disc in. Any CD or DVD also shows whether
the agent sees the drive (discs without a Steam Shelf tag are ignored). Watch it
live with `python main.py --agent` in a terminal (stop the background one first
from the app's **Game mode** button); the log is also in `agent.log` (Files, below).

## Burning

**Burn to a disc** burns it in the first drive and ejects the disc when done
(a minute or two; the app says so):

- **Windows**: through IMAPI2, what Explorer's "Burn to disc" uses. The files go
  straight to the disc; no image is handed to Windows Disc Image Burner, which
  refuses images made by other programs on some PCs ("isn't valid").
- **Linux**: with **xorriso** (see Linux below). It checks the disc first: a
  blank CD-R, DVD-R, DVD+R, or a DVD+RW / BD-RE (written again from the start).

The image is about 2.4 MB (a hidden filler and some padding keep every drive
happy), so any CD-R works. **Save the disc image** gives you the `.iso` for any
other burning program (Brasero, K3b, ImgBurn…).

## Linux

Everything works the same: game mode, burner mode, the countdown card, testing
with the virtual drive, burning, erasing. Any distribution with a desktop
(GNOME, KDE Plasma, Xfce, Cinnamon, MATE, Budgie, LXQt…), on X11 or Wayland,
with Steam installed natively, as a Flatpak or as a Snap.

```
sudo apt install python3-venv xorriso libxcb-cursor0   # Fedora: sudo dnf install xorriso xcb-util-cursor
                                                       # Arch:   sudo pacman -S libisoburn xcb-util-cursor
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
.venv/bin/python main.py --desktop-entry     # optional: Steam Shelf in your apps menu
```

- **The drive**: the agent reads discs straight from `/dev/sr0` (the kernel
  announces a disc going in; nothing has to be mounted, and it does not matter
  whether your desktop opens a window for the disc). A normal desktop login
  already gives you the drive. If the app says your user can't open it, add
  yourself to the drive's group and log in again:
  `sudo usermod -aG cdrom $USER` (Arch: `optical`).
- **Starting with your session**: Settings › "Watch the drive from the moment
  you log in" writes `~/.config/autostart/steam-shelf-agent.desktop`, which every
  desktop above runs. On sway, Hyprland, i3 and other bare compositors add
  `exec /path/to/.venv/bin/python /path/to/main.py --agent` to their config.
- **Wayland**: apps may not place their own windows there, so the countdown card
  opens through XWayland when it can (bottom-right, on top); otherwise your
  desktop places it.
- **Burning and erasing** use xorriso (libburnia), which needs read/write access
  to the drive (same as above). If the disc is mounted, Steam Shelf unmounts it
  through udisks first.
- **Games**: `steam://` links open with `xdg-open`, so whichever Steam you have
  starts the game. Windows-only games run through Proton as usual.

## Your library

Only your own games can go on a disc: the ones your PimpMySteam account owns,
or the ones Steam has installed on this PC. A store link or app id of a game you
don't own shows "Not in your library" and a link to the store.


Without an account, Steam Shelf lists the games Steam has installed on this PC.
Connect your PimpMySteam account (Settings › PimpMySteam account, the same app
token as Steam Curator, from pimpmysteam.com › Settings › Apps) and the
**Library** tab lists every game you own, with where each one stands:

- **Burned** (green): on at least one real disc. "On 2 discs" if you made copies.
- **Ready to burn** (gold): the disc image is made (maybe tested with a virtual
  disc) but not burned yet.
- **Was on a disc** (grey): you burned it before and later put another game on
  that disc, erased it or removed it. It stays in your Steam Shelf history.
- nothing: not on a disc. **Make disc** starts one with the game already picked.

Filters: All · Not on a disc · On a disc · Installed. The list is cached for 15
minutes (the server allows 30 reloads an hour). The token is only used to read
your game list; the Steam Web API key stays on the PimpMySteam server.

## Steam Family

Steam has no public way to list your family, so Settings › Steam Family takes
each member's profile link (`steamcommunity.com/id/…` or `/profiles/…`). The
PimpMySteam server reads their public game lists with its own Steam key (the
same data any Steam calculator shows; a private "Game details" setting blocks
it), so this needs your PimpMySteam account. Those games count as yours to burn
and carry a **Steam Family** tag in the Library, the New disc dialog and your
history (so the profile can show it). Your own copy always wins and a game two
members own is counted once. Lists refresh every 6 hours or with Reload.

## Third-party games (GOG, Epic, emulators, anything)

One path for all of them, on Windows and Linux alike: **add the game to Steam**
(Steam › Games › "Add a Non-Steam Game to My Library…", and pick the game, the
emulator, or the game's launcher). It then shows up under "Non-Steam games in
your Steam", Steam launches it the same way (`steam://rungameid/…`), and the
disc works like any other. Other launchers are deliberately not read: one way
in keeps discs predictable on every PC.

A shortcut's id differs from PC to PC, so the disc is also matched by its
title; on a PC without that shortcut the card says to add it to Steam first
(with the same name). On Linux, a Windows game added this way runs through
Proton (the shortcut's Properties › Compatibility). The cover is the art you
set for the shortcut in Steam, otherwise SteamGridDB with your key (Settings),
otherwise the title.

## Only a few discs? Put another game on one

Disc menu › **Put another game on this disc**, pick the game, then:

- **Point this disc to the new game**: works with any disc, including CD-R and
  DVD-R (write-once). Nothing is burned; on this PC the disc now opens the new
  game. Its label and cover still show the old one, and on another PC it still
  opens the old game. The card says "Disc says: …" so you don't lose track.
  Pointing it back to the original game undoes it.
- **Erase the disc and burn the new game**: rewritable discs only (CD-RW,
  DVD-RW, DVD+RW, BD-RE). Steam Shelf erases it in the drive (quick erase:
  IMAPI2 on Windows, xorriso on Linux) and burns the new game. Then it works on
  any PC.

## Covers

For a Steam game the cover is the one you set in Steam yourself (what the
Grunge Editor writes to `userdata/<you>/config/grid/<appid>p.png`; picked up
again whenever it changes), else Steam's official 600x900 art, else the wide
store header. SteamGridDB is never used for Steam games. For third-party games
it is the art you set for the shortcut in Steam, else SteamGridDB by title
(with your key), else the title on a plain cover.

## Covers from SteamGridDB (optional)

Settings › SteamGridDB covers: paste your own free API key (steamgriddb.com ›
Preferences › API). Then third-party games get community covers automatically,
and a third-party disc's menu gets **Change cover**: every safe-for-work grid
for that game, each with its artist's name (also shown on the card's tooltip).
**Back to the default cover** undoes it. The cover you pick is the one burned
on the disc.

## Your Steam Shelf on pimpmysteam.com

With your account connected, every game that reaches a real disc is sent to
PimpMySteam (after burning, and when you open the Library). The server checks
each one against your Steam library or your Steam Family's and shows the
verified ones on your profile's **Steam Shelf** widget, with the date of its
first disc and a tag where it applies (Steam Family, non-Steam).
Third-party games show their title only. Games the server could not verify
stay private. Reusing a disc never removes a game from the shelf; you can hide
one from your profile on the website.

Your own covers go up too: for every game whose cover is yours (the art you set
in Steam, or what you picked for a third-party game) the app sends a 300x450
WebP of about 20–30 KB, once, so the profile shows *your* cover instead of
Steam's. An account keeps 60 of them (the rest show Steam's art); supporters on
Ko-fi have no limit.

## History

Every game that reaches a real disc is kept in `history.json` with the date of
its first disc. Reusing or erasing that disc does not remove it. This is what
the Steam Shelf section of your pimpmysteam.com profile shows.

A free account shows **100 games** on its profile (supporters on Ko-fi: all of
them), so you choose which: the disc's menu › **Show on my profile**, or the
eye button on a Library row. A hidden game stays in your history; the next sync
tells the server. If more than 100 are marked visible, the profile shows the
first 100 you put on a disc and the app says so.

## Languages

The same 26 languages as Steam Curator (Settings › Language, or the system
language by default): English, Español, Deutsch, Français, Português, Русский,
简体中文, 繁體中文, 日本語, 한국어, Türkçe, हिन्दी, Italiano, Nederlands,
Українська, Polski, Čeština, Svenska, Dansk, Suomi, Norsk, Română, Magyar,
ไทย, Tiếng Việt, Bahasa Indonesia. Strings live in `locales/<code>.json`;
`en.json` is the source and a missing key falls back to English.

## Files

Everything lives in one folder: `%APPDATA%\SteamShelf\` on Windows,
`~/.local/share/SteamShelf/` on Linux (`$XDG_DATA_HOME` if you set it).

| Where | What |
|---|---|
| `settings.json` | settings (the agent re-reads them on every disc) |
| `shelf.json` | the discs you made |
| `iso/` | disc images |
| `virtual-drive/disc.iso` | the disc in the virtual drive (only while you test) |
| `creds.json` | your PimpMySteam app token and SteamGridDB key (Settings removes them) |
| `library.json` | owned games, cached 15 min |
| `history.json` | every game that was ever on a disc |
| `family.json`, `family/` | Steam Family members and their game lists |
| `covers/credits.json` | artists of the SteamGridDB covers you use |
| `agent.log` | what the agent saw and did |
| `run/` (Linux) | the agent's and the window's locks |
| `HKCU\...\CurrentVersion\Run\SteamShelfAgent` (Windows) | starts the agent when you log in (Settings) |
| `~/.config/autostart/steam-shelf-agent.desktop` (Linux) | the same on Linux |

## Development

```
pip install -r requirements.txt pytest
python -m pytest -q
```

## Building the installer / AppImage

```
pip install -r requirements-build.txt
python tools/build.py
```

Releases are built by GitHub Actions: `tools/release/release.yml` goes in
`.github/workflows/`, and pushing a tag `v1.0.0` runs the tests, builds the
Windows installer and the Linux AppImage, and publishes them on a GitHub
release with the matching section of `CHANGELOG.md` as notes.

- **Windows**: `dist\SteamShelf\` is the portable build (run `SteamShelf.exe`).
  With [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed
  (`winget install JRSoftware.InnoSetup`) you also get
  `dist\SteamShelf-<version>-setup.exe`: per-user install, no admin, stops the
  running agent before updating, removes the autostart entry on uninstall.
- **Linux**: `dist/SteamShelf/` plus `dist/SteamShelf-<version>-x86_64.AppImage`
  (appimagetool is downloaded into `tools/` the first time). Build it on the
  oldest distribution you want to support (Ubuntu 22.04 is a good base): the
  AppImage carries Python and Qt but uses the system's glibc. Users still need
  `xorriso` to burn. The app knows it runs from an AppImage and starts its
  agent and card from the same file; the autostart entry points at it.

The spec (`steamshelf.spec`) drops the Qt modules the app never loads
(QtQuick, QtQml, QtPdf, QtNetwork…) and numpy, which Pillow pulls in:
~160 MB on disk, ~60 MB as an AppImage.

The UI kit (`ui/theme.py`, `ui/components.py`, `ui/icons.py`) is the same one
Steam Curator uses. Fonts: Inter, Space Mono, Bebas Neue (OFL, `assets/fonts`).
Icons: Lucide (ISC, `assets/LICENSE-lucide.txt`).

## Roadmap

1. Windows and Linux (this). macOS is not planned.
2. Disc labels and case inserts printed from your Grunge Editor covers.
