#!/usr/bin/env python3
"""
restore_from_sort-tier_log.py

Восстановление по organizer.log (best-effort).

Usage:
    python restore_from_sort-tier_log.py --log /path/to/organizer.log [--apply] [--yes] [--limit-dir /path/to/limit] [--verbose]

Options:
    --log       Path to organizer.log (required)
    --apply     Actually perform filesystem operations (default: dry-run)
    --yes       Skip interactive confirmation when --apply is used
    --limit-dir Only consider log entries where destination path is under this directory
    --verbose   Print more details during planning/execution
"""

import argparse
import re
from pathlib import Path
import shutil
import sys
import os

# Регулярное выражение для поиска операций вида:
# Moved: C:\path\to\file -> D:\dest\path\file
# Copied: ...
# Overwritten by move: ...
# Overwritten by copy: ...
OP_RE = re.compile(r'^(?:.*\t)?(?P<action>(?:Overwritten by move|Overwritten by copy|Moved|Copied)):\s+(?P<src>.+?)\s+->\s+(?P<dst>.+?)\s*$')

DRY_RUN_TAG = '[DRY-RUN]'

def parse_log(log_path: Path, limit_dir: Path = None, verbose: bool = False):
    """
    Возвращает список записей (action, orig_src, orig_dst).
    action in {'move','copy'} where:
      - 'move' corresponds to Moved / Overwritten by move
      - 'copy' corresponds to Copied / Overwritten by copy
    """
    entries = []
    with log_path.open('r', encoding='utf-8', errors='ignore') as fh:
        for lineno, line in enumerate(fh, start=1):
            if DRY_RUN_TAG in line:
                # пропускаем dry-run записи — они не отражают реальные изменения
                continue
            m = OP_RE.search(line)
            if not m:
                if verbose:
                    # иногда лог может содержать другие полезные строки; игнорируем
                    pass
                continue
            act_raw = m.group('action').lower()
            if 'move' in act_raw:
                typ = 'move'
            else:
                typ = 'copy'
            src = Path(m.group('src').strip())
            dst = Path(m.group('dst').strip())
            # Применяем ограничение по каталогу назначения, если задано
            if limit_dir:
                try:
                    if not str(dst.resolve()).lower().startswith(str(limit_dir.resolve()).lower()):
                        if verbose:
                            print(f"Skipping entry (outside limit-dir): {dst}")
                        continue
                except Exception:
                    # если не удалось резолвить — всё равно включаем
                    pass
            entries.append((typ, src, dst, lineno))
    return entries

def plan_restore(entries, verbose: bool = False):
    """
    Формирует план действий:
      - для 'move': если dst существует -> планируем move_back dst -> src (если src занят — создаём уникальное имя)
      - для 'copy': если dst существует and src missing -> планируем copy_back dst -> src
    Возвращает список действий: (action, src_path, dst_path)
      action in {'move_back','copy_back'}
    """
    actions = []
    for typ, orig_src, orig_dst, lineno in entries:
        dst_exists = orig_dst.exists()
        src_exists = orig_src.exists()
        if not dst_exists:
            if verbose:
                print(f"[line {lineno}] Destination not found, skipping: {orig_dst}")
            continue
        if typ == 'move':
            # файл был перемещён orig_src -> orig_dst; если orig_dst существует, переместим обратно
            target = orig_src
            if target.exists():
                # не перезаписываем существующий файл — создаём уникальное имя
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
            # файл был скопирован orig_src -> orig_dst; если orig_src отсутствует, копируем обратно
            if not orig_src.exists():
                actions.append(('copy_back', orig_dst, orig_src, lineno))
            else:
                if verbose:
                    print(f"[line {lineno}] Original exists, skipping copy_back: {orig_src}")
    return actions

def execute_actions(actions, apply=False, yes=False):
    if not actions:
        print("Нет доступных действий для восстановления.")
        return
    print("План восстановления:")
    for act, src, dst, lineno in actions:
        print(f"  {act}: {src} -> {dst}  (log line {lineno})")
    if not apply:
        print("\nDry-run: ничего не будет изменено. Запустите с --apply для выполнения.")
        return
    if not yes:
        ans = input("\nВыполнить перечисленные действия? Введите 'confirm' для продолжения: ").strip().lower()
        if ans != 'confirm':
            print("Подтверждение не получено. Отмена.")
            return
    # Выполнение
    for act, src, dst, lineno in actions:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if act == 'move_back':
                # если dst не существует — пропускаем
                if not src.exists():
                    print(f"[WARN] Источник для перемещения не найден, пропускаем: {src}")
                    continue
                # если dst и dst == src (редкий случай) — пропускаем
                if src.resolve() == dst.resolve():
                    print(f"[INFO] Источник и цель совпадают, пропускаем: {src}")
                    continue
                shutil.move(str(src), str(dst))
                print(f"Moved back: {src} -> {dst}")
            elif act == 'copy_back':
                if not src.exists():
                    print(f"[WARN] Источник для копирования не найден, пропускаем: {src}")
                    continue
                # если dst уже существует — создаём уникальное имя
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
                print(f"Copied back: {src} -> {final_dst}")
        except Exception as e:
            print(f"[ERROR] Ошибка при выполнении {act} {src} -> {dst}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Restore files from organizer.log (best-effort)")
    parser.add_argument('--log', required=True, help='Path to organizer.log')
    parser.add_argument('--apply', action='store_true', help='Apply changes (default is dry-run)')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt when --apply is used')
    parser.add_argument('--limit-dir', help='Only consider entries where destination is under this directory')
    parser.add_argument('--verbose', action='store_true', help='Verbose output during parsing/planning')
    args = parser.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"Лог не найден: {log_path}")
        sys.exit(1)

    limit_dir = Path(args.limit_dir) if args.limit_dir else None
    entries = parse_log(log_path, limit_dir=limit_dir, verbose=args.verbose)
    if args.verbose:
        print(f"Parsed {len(entries)} relevant log entries (excluding dry-run lines).")
    actions = plan_restore(entries, verbose=args.verbose)
    if args.verbose:
        print(f"Planned {len(actions)} actions.")
    execute_actions(actions, apply=args.apply, yes=args.yes)

if __name__ == '__main__':
    main()
