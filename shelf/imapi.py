"""
Windows burns and images discs itself: IMAPI2 (MsftFileSystemImage +
MsftDiscFormat2Data), the mastering API behind Explorer's "Burn to disc".

- burn(): the files are laid out in a temporary folder, IMAPI builds the
  ISO 9660 + Joliet file system and writes it to the disc in one go. No image
  file is handed to Windows Disc Image Burner (which refused ours as "not
  valid" on some PCs, as Mount-DiskImage did).
- build(): the same file system saved to an .iso (for the virtual drive and
  "Save the disc image"), copied from IMAPI's IStream by a few lines of C#
  that Windows PowerShell compiles on the fly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_NO_WINDOW = 0x08000000

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$code = @'
using System;
using System.IO;
using System.Runtime.InteropServices.ComTypes;
public class SteamShelfIso {
  public unsafe static void Save(string path, object stream, int blockSize, int totalBlocks) {
    int read = 0;
    byte[] buf = new byte[blockSize];
    IntPtr pRead = (IntPtr)(&read);
    IStream s = stream as IStream;
    using (FileStream f = File.Create(path)) {
      while (totalBlocks-- > 0) { s.Read(buf, blockSize, pRead); f.Write(buf, 0, read); }
    }
  }
}
'@
$cp = New-Object System.CodeDom.Compiler.CompilerParameters
$cp.CompilerOptions = '/unsafe'
Add-Type -CompilerParameters $cp -TypeDefinition $code
$fsi = New-Object -ComObject IMAPI2FS.MsftFileSystemImage
$fsi.ChooseImageDefaultsForMediaType(2)          # CD-R: the smallest medium we burn to
$fsi.FileSystemsToCreate = 3                     # ISO 9660 + Joliet
$fsi.VolumeName = $env:SHELF_LABEL
$fsi.Root.AddTree($env:SHELF_SRC, $false)
$res = $fsi.CreateResultImage()
# .NET keeps its own current directory and does not expand anything: give it a full path
# and make sure the folder is there as .NET sees it
$out = [System.IO.Path]::GetFullPath($env:SHELF_OUT)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($out)) | Out-Null
[SteamShelfIso]::Save($out, $res.ImageStream, $res.BlockSize, $res.TotalBlocks)
Write-Output ('OK ' + $res.TotalBlocks + ' ' + $out)
"""


_BURN = r"""
$ErrorActionPreference = 'Stop'
$want = $env:SHELF_DRIVE + '\'
$master = New-Object -ComObject IMAPI2.MsftDiscMaster2
$rec = $null
foreach ($id in $master) {
  $r = New-Object -ComObject IMAPI2.MsftDiscRecorder2
  $r.InitializeDiscRecorder($id)
  if (@($r.VolumePathNames) -contains $want) { $rec = $r }
}
if ($rec -eq $null) { Write-Output 'NO_DRIVE'; exit 2 }
$fmt = New-Object -ComObject IMAPI2.MsftDiscFormat2Data
$fmt.Recorder = $rec
$fmt.ClientName = 'Steam Shelf'
try { $ok = $fmt.IsCurrentMediaSupported($rec) } catch { Write-Output ('NO_DISC ' + $_.Exception.Message); exit 3 }
if (-not $ok) { Write-Output 'NO_DISC unsupported media'; exit 3 }
$state = [int]$fmt.CurrentMediaStatus          # IMAPI_FORMAT2_DATA_MEDIA_STATE: 2 = blank, 4 = appendable, 0x4000 = finalized
$info = ('media type ' + $fmt.CurrentPhysicalMediaType + ', state 0x' + $state.ToString('X') +
         ', physically blank ' + $fmt.MediaPhysicallyBlank + ', heuristically blank ' + $fmt.MediaHeuristicallyBlank +
         ', drive ' + $rec.VendorId + ' ' + $rec.ProductId)
Write-Output ('INFO ' + $info)
if (-not ($fmt.MediaPhysicallyBlank -or $fmt.MediaHeuristicallyBlank -or ($state -band 2))) { Write-Output ('NOT_BLANK ' + $info); exit 4 }
$fsi = New-Object -ComObject IMAPI2FS.MsftFileSystemImage
$fsi.ChooseImageDefaults($rec)
$fsi.FileSystemsToCreate = 3                     # ISO 9660 + Joliet
$fsi.VolumeName = $env:SHELF_LABEL
$fsi.Root.AddTree($env:SHELF_SRC, $false)
$res = $fsi.CreateResultImage()
$fmt.ForceMediaToBeClosed = $true                # one session, readable in every drive
$fmt.Write($res.ImageStream)
try { $rec.EjectMedia() } catch { }
Write-Output 'BURNED'
"""


def _log(line: str) -> None:
    """DATA_DIR/imapi.log: what Windows said (for when a burn or an image goes wrong)."""
    import config
    import time
    try:
        with open(config.DATA_DIR / "imapi.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def _stage(files: dict[str, bytes]) -> Path:
    stage = Path(tempfile.mkdtemp(prefix="shelf-disc-"))
    for path, data in files.items():
        f = stage / Path(*path.split("/"))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        if path.endswith("PAD.BIN"):
            subprocess.run(["attrib", "+H", str(f)], creationflags=_NO_WINDOW, capture_output=True)
    return stage


def _powershell(script: str, env: dict, timeout: float) -> tuple[int, str, str]:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW,
                       env=dict(os.environ, **env))
    out = (r.stdout or "").strip().splitlines()
    last = out[-1] if out else ""
    msg = " ".join(((r.stderr or "") + " " + (r.stdout or "")).split())[:400]
    return r.returncode, last, msg


def build(files: dict[str, bytes], label: str, out: Path) -> None:
    """Write the image to `out`. Raises RuntimeError with PowerShell's message on failure."""
    stage = _stage(files)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        rc, last, msg = _powershell(_SCRIPT, {"SHELF_SRC": str(stage.resolve()), "SHELF_OUT": str(out.resolve()),
                                              "SHELF_LABEL": label}, 180)
        _log(f"image {out.name}: exit {rc}: {msg}")
        if rc != 0 or not last.startswith("OK "):
            raise RuntimeError(msg or f"powershell exit {rc}")
        if not out.is_file() or out.stat().st_size == 0:
            raise RuntimeError("no image was written")
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def burn(files: dict[str, bytes], label: str, drive: str) -> None:
    """Burn the files to the blank disc in `drive` ('H:') and eject it. Raises media.BurnError."""
    from shelf.media import BurnError
    import re
    if not re.fullmatch(r"[A-Za-z]:", drive):
        raise BurnError("no_disc")
    stage = _stage(files)
    try:
        rc, last, msg = _powershell(_BURN, {"SHELF_SRC": str(stage.resolve()), "SHELF_LABEL": label,
                                            "SHELF_DRIVE": drive.upper()}, 1800)
        _log(f"burn {drive} {label}: exit {rc}: {msg}")
        if last == "BURNED":
            return
        word = last.split(" ", 1)[0]
        code = {"NO_DRIVE": "no_disc", "NO_DISC": "no_disc", "NOT_BLANK": "not_blank"}.get(word, "failed")
        raise BurnError(code, msg if code == "failed" else last)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
