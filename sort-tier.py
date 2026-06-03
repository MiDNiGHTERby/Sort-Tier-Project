#!/usr/bin/env python3
"""
sort-tier.py
Полный обновлённый файл — самодостаточный скрипт для Windows 10.

Изменение: .iso теперь перемещается в целевую структуру (как обычные файлы).
.exe и .msi по-прежнему копируются и остаются в исходной папке.
.zip, 7z, .rar, .tar, .gz, .bz2, .xz также копируются, так как могут быть установщиками или архивами, которые пользователь хочет сохранить в исходной папке.
"""

import os
import shutil
import logging
import ctypes
import hashlib
from ctypes import wintypes
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import sys

# Попытка импортировать tkinter для диалогов выбора папок
try:
    import tkinter as tk
    from tkinter import filedialog
    _TK_AVAILABLE = True
except Exception:
    _TK_AVAILABLE = False

# Optional dependency for sending files to Recycle Bin
try:
    from send2trash import send2trash
    _SEND2TRASH_AVAILABLE = True
except Exception:
    _SEND2TRASH_AVAILABLE = False

# WinAPI для проверки системного атрибута (Windows)
FILE_ATTRIBUTE_SYSTEM = 0x4
GetFileAttributesW = None
if os.name == 'nt':
    try:
        GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW
        GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
        GetFileAttributesW.restype = wintypes.DWORD
    except Exception:
        GetFileAttributesW = None

# -------------------------
# РАЗРЕШЁННЫЕ РАСШИРЕНИЯ (редактируй при необходимости)
# -------------------------
IMAGE_EXTS = {
    "jpg","jpeg","png","gif","bmp","webp","tiff","tif","svg"
}
DOC_EXTS = {
    "pdf","doc","docx","odt","txt","rtf","xls","xlsx","csv","ppt","pptx", "epub","fb2","djvu"
}
VIDEO_EXTS = {
    "mp4","mkv","mov","avi","wmv","flv","webm","m4v","mpeg","mpg","3gp","vob","iso"
}
GRAPHICS_EXTS = {
    "psd","psb","ai","eps","cdr","xcf","kra","sketch","ps","ora","pdn", "afphoto"
}
# .iso удалён из INSTALLER_EXTS — теперь перемещается как обычный файл
INSTALLER_EXTS = {"exe","msi", "zip", "7z", "rar", "tar", "gz", "bz2", "xz"}
AUDIO_EXTS = {"mp3","m4a","flac","wav","aac","ogg","wma","alac", "m3u8"}
# Добавляем iso в общий набор ALLOWED_EXTS, но не в INSTALLER_EXTS
ALLOWED_EXTS = set()
ALLOWED_EXTS |= IMAGE_EXTS
ALLOWED_EXTS |= DOC_EXTS
ALLOWED_EXTS |= VIDEO_EXTS
ALLOWED_EXTS |= GRAPHICS_EXTS
ALLOWED_EXTS |= INSTALLER_EXTS
ALLOWED_EXTS |= AUDIO_EXTS
#ALLOWED_EXTS.add("iso")
# -------------------------

def is_system_file(path: Path) -> bool:
    if os.name != 'nt' or GetFileAttributesW is None:
        return False
    try:
        attrs = GetFileAttributesW(str(path))
        if attrs == 0xFFFFFFFF:
            return False
        return bool(attrs & FILE_ATTRIBUTE_SYSTEM)
    except Exception:
        return False

def month_key_from_ctime(path: Path) -> str:
    try:
        stat = path.stat()
        dt = datetime.fromtimestamp(stat.st_ctime)
        return dt.strftime("%Y-%m")
    except Exception:
        return "unknown"

def choose_directory_gui(prompt="Выберите каталог"):
    if not _TK_AVAILABLE:
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        folder = filedialog.askdirectory(title=prompt)
        try:
            root.destroy()
        except Exception:
            pass
        if folder:
            return Path(folder)
    except Exception:
        pass
    return None

def choose_directory_console(prompt="Введите путь к каталогу (или нажмите Enter для отмены): "):
    try:
        val = input(prompt).strip()
    except EOFError:
        return None
    if not val:
        return None
    return Path(val)

def choose_directory(prompt="Выберите каталог"):
    p = choose_directory_gui(prompt)
    if p:
        return p
    print(prompt)
    return choose_directory_console("Введите полный путь или нажмите Enter для отмены: ")

def ensure_unique_dest(dest: Path) -> Path:
    if not dest.exists():
        return dest
    base = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    i = 1
    while True:
        candidate = parent / f"{base}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1

def setup_logger(log_path: Path):
    logger = logging.getLogger("sort-tier")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(log_path, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter('%(asctime)s\t%(levelname)s\t%(message)s')
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger

def file_sha256(path: Path, chunk_size: int = 8192) -> str:
    h = hashlib.sha256()
    try:
        with path.open('rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""

def decide_destination(src: Path, desired: Path):
    if not desired.exists():
        return desired, False
    try:
        src_sum = file_sha256(src)
        dst_sum = file_sha256(desired)
    except Exception:
        src_sum = ""
        dst_sum = ""
    if src_sum and dst_sum and src_sum == dst_sum:
        return desired, True
    unique = ensure_unique_dest(desired)
    return unique, False

def send_to_trash(path: Path, dry_run: bool, logger: logging.Logger, fallback_trash_dir: Path = None):
    if dry_run:
        logger.info(f"[DRY-RUN] Send to trash: {path}")
        return True
    if _SEND2TRASH_AVAILABLE:
        try:
            send2trash(str(path))
            logger.info(f"Sent to Recycle Bin: {path}")
            return True
        except Exception as e:
            logger.warning(f"send2trash failed for {path}: {e}")
    if fallback_trash_dir is None:
        logger.error(f"No fallback trash dir provided for {path}")
        return False
    try:
        fallback_trash_dir.mkdir(parents=True, exist_ok=True)
        dest = ensure_unique_dest(fallback_trash_dir / path.name)
        shutil.move(str(path), str(dest))
        logger.info(f"Moved to local Trash: {path} -> {dest}")
        return True
    except Exception as e:
        logger.error(f"Failed to move {path} to local Trash {fallback_trash_dir}: {e}")
        return False

def safe_move(src: Path, dest: Path, dry_run: bool, logger):
    dest_parent = dest.parent
    if not dry_run:
        dest_parent.mkdir(parents=True, exist_ok=True)
    chosen_dest, overwrite = decide_destination(src, dest)
    if dry_run:
        if overwrite:
            logger.info(f"[DRY-RUN] Overwrite Move (identical): {src} -> {chosen_dest}")
        else:
            logger.info(f"[DRY-RUN] Move: {src} -> {chosen_dest}")
        return chosen_dest
    try:
        if overwrite and chosen_dest.exists():
            try:
                chosen_dest.unlink()
            except Exception as e:
                logger.warning(f"Не удалось удалить существующий файл перед перезаписью {chosen_dest}: {e}")
        shutil.move(str(src), str(chosen_dest))
        if overwrite:
            logger.info(f"Overwritten by move: {src} -> {chosen_dest}")
        else:
            logger.info(f"Moved: {src} -> {chosen_dest}")
    except Exception as e:
        logger.error(f"Failed to move {src} -> {chosen_dest}: {e}")
    return chosen_dest

def safe_copy(src: Path, dest: Path, dry_run: bool, logger):
    dest_parent = dest.parent
    if not dry_run:
        dest_parent.mkdir(parents=True, exist_ok=True)
    chosen_dest, overwrite = decide_destination(src, dest)
    if dry_run:
        if overwrite:
            logger.info(f"[DRY-RUN] Overwrite Copy (identical): {src} -> {chosen_dest}")
        else:
            logger.info(f"[DRY-RUN] Copy: {src} -> {chosen_dest}")
        return chosen_dest
    try:
        tmp = chosen_dest.with_suffix(chosen_dest.suffix + ".tmp")
        try:
            shutil.copy2(str(src), str(tmp))
            if overwrite and chosen_dest.exists():
                try:
                    chosen_dest.unlink()
                except Exception as e:
                    logger.warning(f"Не удалось удалить существующий файл перед перезаписью {chosen_dest}: {e}")
            os.replace(str(tmp), str(chosen_dest))
            if overwrite:
                logger.info(f"Overwritten by copy: {src} -> {chosen_dest}")
            else:
                logger.info(f"Copied: {src} -> {chosen_dest}")
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Failed to copy {src} -> {chosen_dest}: {e}")
    return chosen_dest

def safe_copy_only(src: Path, dest: Path, dry_run: bool, logger):
    return safe_copy(src, dest, dry_run, logger)

def safe_copy_and_trash(src: Path, dest: Path, dry_run: bool, logger, fallback_trash_dir: Path = None):
    dest_parent = dest.parent
    if not dry_run:
        dest_parent.mkdir(parents=True, exist_ok=True)
    chosen_dest, overwrite = decide_destination(src, dest)
    if dry_run:
        if overwrite:
            logger.info(f"[DRY-RUN] Overwrite Copy (identical) then Trash: {src} -> {chosen_dest}")
            logger.info(f"[DRY-RUN] Then send original to trash: {src}")
        else:
            logger.info(f"[DRY-RUN] Copy then Trash: {src} -> {chosen_dest}")
            logger.info(f"[DRY-RUN] Then send original to trash: {src}")
        return chosen_dest
    try:
        tmp = chosen_dest.with_suffix(chosen_dest.suffix + ".tmp")
        try:
            shutil.copy2(str(src), str(tmp))
            if overwrite and chosen_dest.exists():
                try:
                    chosen_dest.unlink()
                except Exception as e:
                    logger.warning(f"Не удалось удалить существующий файл перед перезаписью {chosen_dest}: {e}")
            os.replace(str(tmp), str(chosen_dest))
            logger.info(f"Copied: {src} -> {chosen_dest} (overwrite={overwrite})")
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Failed to copy {src} -> {chosen_dest}: {e}")
        return None
    ok = send_to_trash(src, dry_run=False, logger=logger, fallback_trash_dir=fallback_trash_dir)
    if not ok:
        logger.error(f"Failed to send original to trash: {src}")
    return chosen_dest

def collect_files(root_dir: Path, exclude_dirs=None, allowed_exts=None):
    exclude_dirs = [Path(d).resolve() for d in (exclude_dirs or [])]
    files = []
    for p in root_dir.rglob('*'):
        if not p.is_file():
            continue
        try:
            pr = p.resolve()
        except Exception:
            pr = p
        skip = False
        for ed in exclude_dirs:
            try:
                if str(pr).lower().startswith(str(ed).lower()):
                    skip = True
                    break
            except Exception:
                continue
        if skip:
            continue
        if is_system_file(p):
            continue
        if allowed_exts is not None:
            ext = p.suffix.lower().lstrip('.')
            if ext not in allowed_exts:
                continue
        files.append(p)
    return files

def organize(root_dir: Path, target_dir: Path, allowed_exts, dry_run=True, log_filename="organizer.log", copy_and_trash=False):
    target_dir = Path(target_dir)
    log_path = target_dir / log_filename
    logger = setup_logger(log_path)

    logger.info(f"Start organizing. root={root_dir}, target={target_dir}, dry_run={dry_run}, copy_and_trash={copy_and_trash}")
    default_excludes = [Path(r"C:\Windows"), Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)"), Path(r"C:\ProgramData")]
    excludes = []
    for d in default_excludes:
        try:
            if not str(root_dir).lower().startswith(str(d).lower()):
                excludes.append(d)
        except Exception:
            excludes.append(d)

    files = collect_files(root_dir, exclude_dirs=excludes, allowed_exts=allowed_exts)
    logger.info(f"Collected {len(files)} files to consider (after extension filter).")

    fallback_trash_dir = target_dir / "Trash"

    by_month = defaultdict(list)
    for f in files:
        key = month_key_from_ctime(f)
        by_month[key].append(f)

    for month, flist in by_month.items():
        month_dir = target_dir / month
        ext_groups = defaultdict(list)
        for f in flist:
            ext = f.suffix.lower() or '.noext'
            ext_groups[ext].append(f)

        singles_dir = month_dir / "Singles"
        for ext, group in ext_groups.items():
            normalized_ext = ext.lstrip('.')
            if len(group) == 1:
                src = group[0]
                dest = singles_dir / src.name
                # installers (exe, msi) are copied only; iso is NOT in INSTALLER_EXTS and will be moved
                if normalized_ext in INSTALLER_EXTS:
                    safe_copy_only(src, dest, dry_run, logger)
                else:
                    if copy_and_trash:
                        safe_copy_and_trash(src, dest, dry_run, logger, fallback_trash_dir=fallback_trash_dir)
                    else:
                        safe_move(src, dest, dry_run, logger)
            else:
                ext_dir = month_dir / normalized_ext
                for f in group:
                    dest = ext_dir / f.name
                    if normalized_ext in INSTALLER_EXTS:
                        safe_copy_only(f, dest, dry_run, logger)
                    else:
                        if copy_and_trash:
                            safe_copy_and_trash(f, dest, dry_run, logger, fallback_trash_dir=fallback_trash_dir)
                        else:
                            safe_move(f, dest, dry_run, logger)

    logger.info("Organizing finished.")

def main():
    print("sort-tier — утилита сортировки файлов по месяцу создания и расширению.")
    print("По умолчанию включён dry-run (операции не выполняются, только логируются).")

    src = choose_directory("Выберите исходный каталог для сканирования")
    if not src:
        print("Исходный каталог не выбран. Выход.")
        return
    if not src.exists() or not src.is_dir():
        print("Исходный каталог не найден или не является директорией. Выход.")
        return

    tgt = choose_directory("Выберите целевой каталог для размещения отсортированных файлов (можно выбрать тот же)")
    if not tgt:
        tgt = src
    if not tgt.exists():
        try:
            tgt.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Не удалось создать целевой каталог {tgt}: {e}")
            return

    dry_run = True
    copy_and_trash = False
    print(f"\nИсходный каталог: {src}")
    print(f"Целевой каталог: {tgt}")
    print(f"Dry-run: {dry_run} (по умолчанию).")
    print("Разрешённые расширения (пример):", ", ".join(sorted(list(ALLOWED_EXTS))[:30]) + ("..." if len(ALLOWED_EXTS)>30 else ""))
    ans = input("\nВыполнить реальные перемещения/копирования вместо dry-run? Введите 'yes' для выполнения, иначе будет dry-run: ").strip().lower()
    if ans in ("yes","y"):
        dry_run = False
        confirm = input("Подтвердите выполнение реальных операций (все действия будут выполнены). Введите 'confirm' для продолжения: ").strip().lower()
        if confirm != "confirm":
            print("Подтверждение не получено — остаёмся в dry-run режиме.")
            dry_run = True

    ans2 = input("\nВключить режим восстановления (копирование в целевую структуру и отправка оригиналов в корзину)? Введите 'yes' для включения: ").strip().lower()
    if ans2 in ("yes","y"):
        copy_and_trash = True
        if not _SEND2TRASH_AVAILABLE:
            print("Внимание: пакет send2trash не установлен. Будет использован локальный Trash в целевом каталоге для восстановления.")

    organize(src, tgt, allowed_exts=ALLOWED_EXTS, dry_run=dry_run, log_filename="organizer.log", copy_and_trash=copy_and_trash)
    print(f"\nГруппировка завершена. Лог: {(Path(tgt)/'organizer.log').resolve()}")
    if dry_run:
        print("Dry-run был включён — реальных перемещений/копирований не выполнено.")
    else:
        print("Реальные операции выполнены (проверьте лог для деталей).")

if __name__ == "__main__":
    main()
