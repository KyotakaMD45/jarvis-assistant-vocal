"""Download the small French Vosk speech model (~41 MB zip, ~66 MB unpacked) if it is missing."""
from __future__ import annotations

import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from jarvis.logger import get_logger
from jarvis.stt import model_dir

log = get_logger(__name__)

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"


_last_pct = -1


def _progress(done: int, total: int) -> None:
    global _last_pct
    if total > 0:
        pct = done * 100 // total
        if pct // 10 == _last_pct // 10 and pct != 100:
            return
        _last_pct = pct
        sys.stdout.write(f"\r      downloading speech model... {pct:3d}% ({done // 1_000_000} / {total // 1_000_000} MB)")
        sys.stdout.flush()


def ensure_model(cfg: dict) -> int:
    target = model_dir(cfg)
    if (target / "am" / "final.mdl").exists():
        print(f"      Speech model already present ({target.name}).")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            zip_path = Path(tmp) / "model.zip"
            with urllib.request.urlopen(MODEL_URL, timeout=30) as response, open(zip_path, "wb") as out:
                total = int(response.headers.get("Content-Length", 0))
                done = 0
                while chunk := response.read(256 * 1024):
                    out.write(chunk)
                    done += len(chunk)
                    _progress(done, total)
            print()
            with zipfile.ZipFile(zip_path) as archive:
                # Refuse paths that would escape the extraction folder.
                for name in archive.namelist():
                    if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                        raise RuntimeError(f"unsafe path in archive: {name}")
                archive.extractall(tmp)
            extracted = next(p for p in Path(tmp).iterdir() if p.is_dir() and (p / "am" / "final.mdl").exists())
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(extracted), str(target))
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] Could not download the speech model: {exc}")
        print("        Check your internet connection and run install.bat again.")
        log.error("Model download failed: %r", exc)
        return 1
    print(f"      Speech model installed in {target}.")
    return 0
