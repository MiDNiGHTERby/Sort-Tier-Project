#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sort-tier-ui.py
Финальная версия:
- Прогрессбар только в консоли; в fallback включён verbose и прогрессбар отключён.
- Логи операций на английском (для парсера), UI и комментарии на русском.
- При режиме "Копировать" восстановление не предлагается.
- При выполнении восстановления создаётся лог восстановления sort-tier-back-<unix_ts>.log
  в исходной папке (откуда запускалась сортировка).
"""

from __future__ import annotations
import os
import sys
import shutil
import logging
import ctypes
import hashlib
import platform
import time
from ctypes import wintypes
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import List, Set, Tuple, Dict, Optional
import re

# Опциональные зависимости
try:
    from InquirerPy import inquirer  # type: ignore
    _INQUIRER_AVAILABLE = True
except Exception:
    _INQUIRER_AVAILABLE = False

try:
    import pyfiglet  # type: ignore
    _FIGLET_AVAILABLE = True
except Exception:
    _FIGLET_AVAILABLE = False

try:
    from tqdm import tqdm  # type: ignore
    _TQDM_AVAILABLE = True
except Exception:
    _TQDM_AVAILABLE = False

# tkinter для диалогов выбора папок (опционально)
try:
    import tkinter as tk
    from tkinter import filedialog
    _TK_AVAILABLE = True
except Exception:
    _TK_AVAILABLE = False

# send2trash опционально
try:
    from send2trash import send2trash  # type: ignore
    _SEND2TRASH_AVAILABLE = True
except Exception:
    _SEND2TRASH_AVAILABLE = False

# WinAPI для проверки системного атрибута файла (Windows)
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
# Наборы расширений
# -------------------------
IMAGE_EXTS = {"jpg","jpeg","png","gif","bmp","webp","tiff","tif","svg"}
AUDIO_EXTS = {"mp3","m4a","flac","wav","aac","ogg","wma","alac"}
VIDEO_EXTS = {"mp4","mkv","mov","avi","wmv","flv","webm","m4v"}
DOC_EXTS = {"pdf","doc","docx","odt","txt","rtf","xls","xlsx","csv","ppt","pptx","md"}
GRAPHICS_EXTS = {"psd","psb","ai","eps","cdr","xcf","kra","sketch","ps","ora","pdn"}
INSTALLER_EXTS = {"exe","msi"}
ARCHIVE_EXTS = {"zip","rar","7z","tar","gz","bz2","xz","torrent"}  # добавлен torrent
ISO_EXTS = {"iso"}

ALLOWED_EXTS: Set[str] = set()
ALLOWED_EXTS |= IMAGE_EXTS
ALLOWED_EXTS |= AUDIO_EXTS
ALLOWED_EXTS |= VIDEO_EXTS
ALLOWED_EXTS |= DOC_EXTS
ALLOWED_EXTS |= GRAPHICS_EXTS
ALLOWED_EXTS |= INSTALLER_EXTS
ALLOWED_EXTS |= ARCHIVE_EXTS
ALLOWED_EXTS |= ISO_EXTS

# -------------------------
# Конфигурация безопасности
# -------------------------
USER_ALLOWED_FOLDERS = {"desktop", "documents", "downloads", "pictures", "music", "videos"}

# -------------------------
# Флаг fallback (IDE / нет консоли)
# -------------------------
FALLBACK_MODE = False

# -------------------------
# Утилиты
# -------------------------
def is_windows() -> bool:
    return os.name == 'nt' or platform.system().lower().startswith('win')

def is_system_file(path: Path) -> bool:
    """Проверка системного атрибута файла (Windows)."""
    if not is_windows() or GetFileAttributesW is None:
        return False
    try:
        attrs = GetFileAttributesW(str(path))
        if attrs == 0xFFFFFFFF:
            return False
        return bool(attrs & FILE_ATTRIBUTE_SYSTEM)
    except Exception:
        return False

def ensure_unique_dest(dest: Path) -> Path:
    """Генерирует уникальное имя, если файл уже существует."""
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

def file_sha256(path: Path, chunk_size: int = 8192) -> str:
    """Вычисляет SHA256 файла."""
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

def setup_logger(log_path: Path):
    """Настройка логгера в файл."""
    logger = logging.getLogger("sort-tier")
    logger.setLevel(logging.DEBUG)
    # избегаем дублирования обработчиков
    if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == str(log_path) for h in logger.handlers):
        fh = logging.FileHandler(log_path, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter('%(asctime)s\t%(levelname)s\t%(message)s')
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger

# -------------------------
# Системный диск / разрешённые пути
# -------------------------
def get_system_drive() -> Optional[Path]:
    if not is_windows():
        return None
    sd = os.environ.get("SystemDrive", "C:")
    return Path(sd + os.sep)

def get_user_profile() -> Path:
    up = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return Path(up)

def allowed_on_system_drive(path: Path) -> bool:
    """Разрешает работу на системном диске только в стандартных пользовательских папках."""
    try:
        path = path.resolve()
    except Exception:
        pass
    sys_drive = get_system_drive()
    if sys_drive is None:
        return True
    try:
        if not str(path).lower().startswith(str(sys_drive).lower()):
            return True
    except Exception:
        return False
    user_profile = get_user_profile()
    allowed_dirs = []
    for name in USER_ALLOWED_FOLDERS:
        allowed_dirs.append(user_profile / name.capitalize())
        allowed_dirs.append(user_profile / name)
    allowed_dirs.append(user_profile)
    for d in allowed_dirs:
        try:
            if str(path).lower().startswith(str(d.resolve()).lower()):
                return True
        except Exception:
            continue
    return False

# -------------------------
# Прогрессбар (только в консоли)
# -------------------------
def get_pbar(total: int, desc: str, unit: str):
    """
    Возвращает tqdm progress bar только если:
    - tqdm установлен (_TQDM_AVAILABLE)
    - и мы НЕ в FALLBACK_MODE (т.е. запущено в реальной консоли)
    Иначе возвращает None.
    """
    if _TQDM_AVAILABLE and not FALLBACK_MODE:
        try:
            return tqdm(total=total, desc=desc, unit=unit)
        except Exception:
            return None
    return None

# -------------------------
# Операции с файлами (лог на английском для парсера)
# -------------------------
def decide_destination(src: Path, desired: Path) -> Tuple[Path, bool]:
    """Возвращает (chosen_dest, identical_flag)."""
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

def safe_move(src: Path, dest: Path, dry_run: bool, logger: logging.Logger, verbose: bool = False) -> Path:
    """Безопасное перемещение с логом на английском."""
    dest_parent = dest.parent
    if not dry_run:
        dest_parent.mkdir(parents=True, exist_ok=True)
    chosen_dest, identical = decide_destination(src, dest)
    if dry_run:
        logger.info(f"[DRY-RUN] Move: {src} -> {chosen_dest}")
        if verbose:
            print(f"[DRY-RUN] Move: {src} -> {chosen_dest}")
        return chosen_dest
    try:
        if identical and chosen_dest.exists():
            logger.info(f"Identical file exists, removing source: {src}")
            if verbose:
                print(f"[INFO] Identical exists, removing source: {src}")
            try:
                src.unlink()
                logger.info(f"Removed original (identical): {src}")
            except Exception as e:
                logger.warning(f"Failed to remove original after identical check: {e}")
            return chosen_dest
        shutil.move(str(src), str(chosen_dest))
        logger.info(f"Moved: {src} -> {chosen_dest}")
        if verbose:
            print(f"Moved: {src} -> {chosen_dest}")
    except Exception as e:
        logger.error(f"Failed to move {src} -> {chosen_dest}: {e}")
        if verbose:
            print(f"[ERROR] Failed to move {src} -> {chosen_dest}: {e}")
    return chosen_dest

def safe_copy(src: Path, dest: Path, dry_run: bool, logger: logging.Logger, verbose: bool = False) -> Path:
    """Безопасное копирование с логом на английском."""
    dest_parent = dest.parent
    if not dry_run:
        dest_parent.mkdir(parents=True, exist_ok=True)
    chosen_dest, identical = decide_destination(src, dest)
    if dry_run:
        logger.info(f"[DRY-RUN] Copy: {src} -> {chosen_dest}")
        if verbose:
            print(f"[DRY-RUN] Copy: {src} -> {chosen_dest}")
        return chosen_dest
    try:
        if identical and chosen_dest.exists():
            logger.info(f"Identical file exists, skipping copy: {src} -> {chosen_dest}")
            if verbose:
                print(f"[INFO] Identical exists, skipping copy: {src} -> {chosen_dest}")
            return chosen_dest
        tmp = chosen_dest.with_suffix(chosen_dest.suffix + ".tmp")
        try:
            shutil.copy2(str(src), str(tmp))
            if chosen_dest.exists():
                try:
                    chosen_dest.unlink()
                except Exception:
                    pass
            os.replace(str(tmp), str(chosen_dest))
            logger.info(f"Copied: {src} -> {chosen_dest}")
            if verbose:
                print(f"Copied: {src} -> {chosen_dest}")
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Failed to copy {src} -> {chosen_dest}: {e}")
        if verbose:
            print(f"[ERROR] Failed to copy {src} -> {chosen_dest}: {e}")
    return chosen_dest

# -------------------------
# Сбор файлов
# -------------------------
def collect_files(root_dir: Path, exclude_dirs: List[Path], allowed_exts: Set[str]) -> List[Path]:
    """Собирает файлы рекурсивно, применяя исключения и фильтр по расширениям."""
    exclude_dirs = [d.resolve() for d in (exclude_dirs or [])]
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

# -------------------------
# Организация (папка по дате + папки по расширениям). Лог на английском.
# -------------------------
def organize(root_dir: Path, target_dir: Path, allowed_exts: Set[str], categories_selected: Set[str],
             move_instead_of_copy: bool, dry_run: bool, exclude_dirs: List[Path] = None, verbose: bool = False) -> Path:
    """
    Организация файлов: создаём папку YYYY-MM-DD и сортируем по расширениям.
    Возвращает путь к созданному лог-файлу внутри папки даты.
    """
    target_dir = Path(target_dir)

    default_excludes = [Path(r"C:\Windows"), Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)"), Path(r"C:\ProgramData")]
    excludes = []
    for d in default_excludes:
        try:
            if not str(root_dir).lower().startswith(str(d).lower()):
                excludes.append(d)
        except Exception:
            excludes.append(d)
    if exclude_dirs:
        for d in exclude_dirs:
            excludes.append(d)

    files = collect_files(root_dir, exclude_dirs=excludes, allowed_exts=allowed_exts)

    def ext_to_category(ext: str) -> Optional[str]:
        ext = ext.lstrip('.').lower()
        if ext in IMAGE_EXTS:
            return "images"
        if ext in AUDIO_EXTS:
            return "audio"
        if ext in VIDEO_EXTS:
            return "video"
        if ext in DOC_EXTS:
            return "documents"
        if ext in GRAPHICS_EXTS:
            return "graphics"
        if ext in INSTALLER_EXTS:
            return "installers"
        if ext in ARCHIVE_EXTS:
            return "archives"
        if ext in ISO_EXTS:
            return "iso"
        return None

    filtered = []
    for f in files:
        cat = ext_to_category(f.suffix.lower().lstrip('.'))
        if cat and cat in categories_selected:
            filtered.append(f)

    # Папка для текущего запуска (по дате)
    today = datetime.now().strftime("%Y-%m-%d")
    date_root = target_dir / today
    try:
        date_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Уникальный лог внутри date_root
    unix_ts = int(time.time())
    log_filename = f"sort-tier-{unix_ts}.log"
    log_path = date_root / log_filename
    logger = setup_logger(log_path)
    logger.info(f"Start organizing. root={root_dir}, target={target_dir}, dry_run={dry_run}, move={move_instead_of_copy}, categories={categories_selected}")
    logger.info(f"Found files to consider (after extension filter): {len(filtered)}")
    if verbose:
        print(f"[DEBUG] Found files to consider: {len(filtered)}")
        print(f"[DEBUG] Log path: {log_path}")

    # Группировка по расширениям
    ext_groups = defaultdict(list)
    for f in filtered:
        ext = f.suffix.lower().lstrip('.') or 'noext'
        ext_groups[ext].append(f)

    iterator = []
    for ext, flist in ext_groups.items():
        for f in flist:
            iterator.append((ext, f))

    # Прогрессбар: только в консоли (не в fallback)
    pbar = get_pbar(total=len(iterator), desc="Обработка файлов", unit="файл")

    for ext, f in iterator:
        dest = date_root / ext / f.name
        action = "move" if move_instead_of_copy else "copy"
        if action == "move":
            safe_move(f, dest, dry_run, logger, verbose=verbose)
        else:
            safe_copy(f, dest, dry_run, logger, verbose=verbose)
        if pbar:
            pbar.update(1)
    if pbar:
        pbar.close()

    logger.info("Organizing finished.")
    if verbose:
        print("[DEBUG] Organizing finished.")
    return log_path

# -------------------------
# Восстановление (парсинг английского лога)
# -------------------------
OP_RE = re.compile(
    r'(?P<action>(?:Overwritten by move|Overwritten by copy|Moved|Copied|Move|Copy))\s*[:\-]?\s*(?P<src>.+?)\s*->\s*(?P<dst>.+)',
    re.IGNORECASE
)
DRY_RUN_TAG = '[DRY-RUN]'

def parse_log_for_restore(log_path: Path, verbose: bool = False):
    """Парсит лог и возвращает список операций для восстановления."""
    entries = []
    try:
        with log_path.open('r', encoding='utf-8', errors='ignore') as fh:
            lines = fh.readlines()
    except Exception as e:
        if verbose:
            print(f"[DEBUG] Failed to read log {log_path}: {e}")
        return entries

    for lineno, line in enumerate(lines, start=1):
        if DRY_RUN_TAG in line:
            continue
        m = OP_RE.search(line)
        if not m:
            continue
        act_raw = m.group('action').lower()
        typ = 'move' if 'move' in act_raw else 'copy'
        src = Path(m.group('src').strip())
        dst = Path(m.group('dst').strip())
        entries.append((typ, src, dst, lineno))

    if verbose and not entries:
        print(f"[DEBUG] No restore operations found in {log_path}. First 20 lines:")
        for i, l in enumerate(lines[:20], start=1):
            print(f"{i:03d}: {l.rstrip()}")
    return entries

def plan_restore(entries, verbose: bool = False):
    """Генерирует план действий для восстановления на основе записей лога."""
    actions = []
    for typ, orig_src, orig_dst, lineno in entries:
        dst_exists = orig_dst.exists()
        if not dst_exists:
            if verbose:
                print(f"[line {lineno}] Destination not found, skipping: {orig_dst}")
            continue
        if typ == 'move':
            target = orig_src
            if target.exists():
                base = target.stem
                suffix = target.suffix
                parent = target.parent
                i = 1
                while True:
                    candidate = parent / f"{base}_restored_{i}{suffix}"
                    if not candidate.exists():
                        target = candidate
                        break
                    i += 1
            actions.append(('move_back', orig_dst, target, lineno))
        elif typ == 'copy':
            if not orig_src.exists():
                actions.append(('copy_back', orig_dst, orig_src, lineno))
    return actions

def execute_restore_actions(actions, apply=False, yes=False, verbose: bool = False, src_root_for_log: Optional[Path] = None):
    """
    Выполняет план восстановления.
    Если src_root_for_log указан, создаёт лог восстановления sort-tier-back-<unix_ts>.log в этой папке.
    """
    if not actions:
        print("Нет доступных действий для восстановления.")
        return

    # Создаём лог восстановления (если указан src_root_for_log)
    back_log_path = None
    if src_root_for_log:
        try:
            src_root_for_log.mkdir(parents=True, exist_ok=True)
            unix_ts = int(time.time())
            back_log_name = f"sort-tier-back-{unix_ts}.log"
            back_log_path = src_root_for_log / back_log_name
            back_logger = setup_logger(back_log_path)
            back_logger.info(f"Start restore log. source_root={src_root_for_log}")
        except Exception:
            back_log_path = None
            back_logger = None
    else:
        back_logger = None

    print("План восстановления:")
    for act, src, dst, lineno in actions:
        print(f"  {act}: {src} -> {dst}  (log line {lineno})")
        if back_logger:
            back_logger.info(f"PLAN: {act}: {src} -> {dst}  (log line {lineno})")

    if not apply:
        print("\nDry-run: ничего не будет изменено. Запустите с подтверждением для выполнения.")
        return

    pbar = None
    if _TQDM_AVAILABLE and not FALLBACK_MODE:
        pbar = tqdm(total=len(actions), desc="Выполнение восстановления", unit="действие")

    for act, src, dst, lineno in actions:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if act == 'move_back':
                if not src.exists():
                    print(f"[WARN] Источник для перемещения не найден, пропускаем: {src}")
                    if back_logger:
                        back_logger.warning(f"Source not found, skipping move_back: {src}")
                    if pbar:
                        pbar.update(1)
                    continue
                if src.resolve() == dst.resolve():
                    print(f"[INFO] Источник и цель совпадают, пропускаем: {src}")
                    if back_logger:
                        back_logger.info(f"Source and destination identical, skipping: {src}")
                    if pbar:
                        pbar.update(1)
                    continue
                shutil.move(str(src), str(dst))
                print(f"Перемещено обратно: {src} -> {dst}")
                if back_logger:
                    back_logger.info(f"Moved back: {src} -> {dst}")
            elif act == 'copy_back':
                if not src.exists():
                    print(f"[WARN] Источник для копирования не найден, пропускаем: {src}")
                    if back_logger:
                        back_logger.warning(f"Source not found, skipping copy_back: {src}")
                    if pbar:
                        pbar.update(1)
                    continue
                final_dst = dst
                if final_dst.exists():
                    base = final_dst.stem
                    suffix = final_dst.suffix
                    parent = final_dst.parent
                    i = 1
                    while True:
                        candidate = parent / f"{base}_restored_{i}{suffix}"
                        if not candidate.exists():
                            final_dst = candidate
                            break
                        i += 1
                shutil.copy2(str(src), str(final_dst))
                print(f"Скопировано обратно: {src} -> {final_dst}")
                if back_logger:
                    back_logger.info(f"Copied back: {src} -> {final_dst}")
        except Exception as e:
            print(f"[ERROR] Ошибка при выполнении {act} {src} -> {dst}: {e}")
            if back_logger:
                back_logger.error(f"Error executing {act} {src} -> {dst}: {e}")
        if pbar:
            pbar.update(1)

    if pbar:
        pbar.close()

    print("Восстановление завершено.")
    if back_logger:
        back_logger.info("Restore finished.")
        print(f"Лог восстановления: {back_log_path.resolve()}")

# -------------------------
# UI: баннер, диалоги, выборы (на русском) и fallback
# -------------------------
CATEGORY_LABELS = [
    ("images", "Изображения"),
    ("audio", "Аудио"),
    ("video", "Видео"),
    ("documents", "Документы"),
    ("graphics", "Графика"),
    ("installers", "Инсталляторы"),
    ("archives", "Архивы"),
    ("iso", "Образы ISO")
]

def print_banner():
    """Печать figlet-баннера и подписи."""
    title = "SORT TIER"
    subtitle = "by MiDNiGHTERby"
    if _FIGLET_AVAILABLE:
        try:
            banner = pyfiglet.figlet_format(title, font="slant")
            print(banner)
            print(subtitle)
            print("-" * 60)
            return
        except Exception:
            pass
    print("=" * 60)
    print(f"{title} - {subtitle}")
    print("=" * 60)

try:
    from prompt_toolkit.output.win32 import NoConsoleScreenBufferError as _NoConsoleConsoleError  # type: ignore
except Exception:
    class _NoConsoleConsoleError(Exception):
        pass

def choose_categories_inquirer_safe() -> Set[str]:
    """Пытаемся использовать InquirerPy; при ошибке — fallback на текстовый ввод."""
    global FALLBACK_MODE
    if not _INQUIRER_AVAILABLE:
        FALLBACK_MODE = True
        return choose_categories_fallback()
    try:
        choices = [{"name": label, "value": key, "checked": (key in ("images","video"))} for key, label in CATEGORY_LABELS]
        ans = inquirer.checkbox(
            message="Выберите категории для обработки (пробел — переключить, Enter — подтвердить):",
            choices=choices,
            instruction="Используйте пробел для выбора, Enter для подтверждения"
        ).execute()
        return set(ans)
    except _NoConsoleConsoleError:
        print("[WARN] InquirerPy требует реальной консоли. Переходим на текстовый ввод.")
        FALLBACK_MODE = True
        return choose_categories_fallback()
    except Exception:
        FALLBACK_MODE = True
        return choose_categories_fallback()

def choose_categories_fallback() -> Set[str]:
    """Текстовый ввод для выбора категорий (fallback)."""
    print("Выберите категории (введите номера через пробел, например: 1 3 5). По умолчанию выбраны Изображения и Видео.")
    for i, (key, label) in enumerate(CATEGORY_LABELS, start=1):
        default_mark = "[X]" if key in ("images","video") else "[ ]"
        print(f"{i}) {label} {default_mark}")
    s = input("Введите номера (или Enter для выбора по умолчанию): ").strip()
    if not s:
        return {"images","video"}
    nums = []
    for part in s.split():
        try:
            nums.append(int(part))
        except Exception:
            continue
    selected = set()
    for n in nums:
        if 1 <= n <= len(CATEGORY_LABELS):
            selected.add(CATEGORY_LABELS[n-1][0])
    return selected

def choose_folder_dialog(prompt: str) -> Optional[Path]:
    """Диалог выбора папки через tkinter; fallback — текстовый ввод."""
    if _TK_AVAILABLE:
        try:
            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            folder = filedialog.askdirectory(title=prompt)
            try:
                root.destroy()
            except Exception:
                pass
            if folder:
                return Path(folder)
            return None
        except Exception:
            pass
    val = input(f"{prompt} (введите путь или нажмите Enter для отмены): ").strip()
    if not val:
        return None
    return Path(val)

def choose_yes_no_safe(prompt: str, default: bool = False) -> bool:
    """Безопасный yes/no: пытаемся InquirerPy, при ошибке — текстовый ввод."""
    global FALLBACK_MODE
    if _INQUIRER_AVAILABLE and not FALLBACK_MODE:
        try:
            return bool(inquirer.confirm(message=prompt, default=default).execute())
        except _NoConsoleConsoleError:
            FALLBACK_MODE = True
            return choose_yes_no(prompt, default)
        except Exception:
            FALLBACK_MODE = True
            return choose_yes_no(prompt, default)
    else:
        FALLBACK_MODE = True
        return choose_yes_no(prompt, default)

def choose_yes_no(prompt: str, default: bool = False) -> bool:
    """Текстовый ввод для подтверждений (y/n)."""
    yn = "Y/n" if default else "y/N"
    s = input(f"{prompt} [{yn}]: ").strip().lower()
    if not s:
        return default
    return s in ("y","yes","y")

def choose_move_or_copy() -> bool:
    """
    Выбор режима Переместить/Копировать.
    В консоли — radio select (InquirerPy); в fallback — ручной ввод.
    Возвращает True если выбран Переместить, False если Копировать.
    """
    global FALLBACK_MODE
    if _INQUIRER_AVAILABLE and not FALLBACK_MODE:
        try:
            ans = inquirer.select(
                message="Выберите режим:",
                choices=[
                    {"name": "Переместить (исходные файлы будут удалены)", "value": True},
                    {"name": "Копировать (исходные файлы останутся)", "value": False}
                ],
                default=False
            ).execute()
            return bool(ans)
        except _NoConsoleConsoleError:
            print("[WARN] InquirerPy требует реальной консоли. Переходим на текстовый ввод.")
            FALLBACK_MODE = True
        except Exception:
            FALLBACK_MODE = True

    # fallback: ручной ввод
    FALLBACK_MODE = True
    print("Введите 'yes' или 'y' для Переместить, иначе будет Копирование (по умолчанию).")
    s = input("Переместить? [y/N]: ").strip().lower()
    if s in ("y","yes","переместить","move"):
        return True
    return False

# -------------------------
# Вспомогательные проверки и main
# -------------------------
def validate_root_choice(root: Path) -> bool:
    """Проверка безопасности: на системном диске разрешены только стандартные пользовательские папки."""
    try:
        root = root.resolve()
    except Exception:
        pass
    if not is_windows():
        return True
    sys_drive = get_system_drive()
    if sys_drive is None:
        return True
    try:
        if not str(root).lower().startswith(str(sys_drive).lower()):
            return True
    except Exception:
        return False
    if allowed_on_system_drive(root):
        return True
    print("Операция запрещена: на системном диске разрешено работать только в стандартных пользовательских папках (Desktop, Documents, Downloads, Pictures, Music, Videos).")
    return False

def main():
    print_banner()

    # Выбор категорий
    categories = choose_categories_inquirer_safe()
    if not categories:
        print("Ни одна категория не выбрана. Выход.")
        return

    # Выбор режима: Переместить / Копировать
    move_flag = choose_move_or_copy()

    # Выбор исходной и целевой папок
    srcp = choose_folder_dialog("Выберите исходный каталог для сканирования")
    if not srcp:
        print("Исходный каталог не выбран. Выход.")
        return
    if not srcp.exists() or not srcp.is_dir():
        print("Исходный каталог не найден или не является директорией. Выход.")
        return
    if not validate_root_choice(srcp):
        return

    tgtp = choose_folder_dialog("Выберите целевой каталог для размещения отсортированных файлов (Enter = исходный)")
    if not tgtp:
        tgtp = srcp
    if not tgtp.exists():
        try:
            tgtp.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Не удалось создать целевой каталог {tgtp}: {e}")
            return

    # verbose включён только в fallback
    verbose_mode = FALLBACK_MODE

    # Подтверждение выполнения реальных операций (единственный ввод 'confirm')
    prompt_text = "Введите 'confirm' для выполнения реальных операций (вместо dry-run) или нажмите Enter для dry-run: "
    confirm_input = input(prompt_text).strip().lower()
    dry_run = False if confirm_input == "confirm" else True

    # Исключения (системные и игровые папки)
    exclude_dirs = [Path(r"C:\Windows"), Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)"), Path(r"C:\ProgramData")]
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    common_paths = [
        Path(program_files) / "Epic Games",
        Path(program_files_x86) / "Epic Games",
        Path(program_files) / "GOG",
        Path(program_files_x86) / "GOG",
        Path(program_files) / "Riot Games",
        Path(program_files_x86) / "Riot Games",
        Path(program_files) / "Steam",
        Path(program_files_x86) / "Steam",
        Path(program_files) / "Origin",
        Path(program_files_x86) / "Origin",
    ]
    for p in common_paths:
        if p.exists():
            exclude_dirs.append(p.resolve())

    print("\nЗапуск сортировки...")
    log_path = organize(srcp, tgtp, allowed_exts=ALLOWED_EXTS, categories_selected=categories,
                        move_instead_of_copy=move_flag, dry_run=dry_run, exclude_dirs=exclude_dirs, verbose=verbose_mode)

    print(f"\nГруппировка завершена. Лог: {log_path.resolve()}")
    if dry_run:
        print("Dry-run был включён — реальных перемещений/копирований не выполнено.")
    else:
        print("Реальные операции выполнены (проверьте лог для деталей).")

    # Если режим Копировать — не предлагаем восстановление, завершаем программу
    if not move_flag:
        if verbose_mode:
            print("[DEBUG] Режим копирования — восстановление не предлагается. Завершение.")
        return

    # Если режим Переместить — автоматически используем последний лог в папке даты (log_path)
    if log_path.exists():
        entries = parse_log_for_restore(log_path, verbose=verbose_mode)
        actions_plan = plan_restore(entries, verbose=verbose_mode)

        # Единый запрос подтверждения: GO
        go_prompt = "Выполнить восстановление (GO)? Введите 'go' для запуска, иначе Enter для отмены: "
        go_input = input(go_prompt).strip().lower()
        if go_input == "go":
            if not actions_plan:
                print("Нет доступных действий для восстановления.")
            else:
                # Передаём srcp как папку для логов восстановления
                execute_restore_actions(actions_plan, apply=True, yes=True, verbose=verbose_mode, src_root_for_log=srcp)
        else:
            print("Восстановление отменено.")
    else:
        print("Лог не найден — восстановление недоступно.")

if __name__ == "__main__":
    main()
