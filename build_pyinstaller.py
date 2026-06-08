#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pyinstaller.py
Альтернативная сборка с PyInstaller (часто лучше воспринимается антивирусами).

Требует: pip install pyinstaller

Использование:
    python build_pyinstaller.py sort-tier-safe.py
"""

import os
import sys
import subprocess
from pathlib import Path

def build_with_pyinstaller(script_path: str):
    """Сборка с PyInstaller для лучшей совместимости с AV."""
    
    script = Path(script_path)
    if not script.exists():
        print(f"Ошибка: файл {script_path} не найден")
        sys.exit(1)
    
    output_dir = Path("dist")
    build_dir = Path("build")
    
    # Оптимальные флаги PyInstaller
    cmd = [
        "pyinstaller",
        "--onefile",                              # Единый exe файл
        "--windowed",                             # Без консоли (опционально)
        f"--distpath={output_dir}",              # Папка вывода
        f"--buildpath={build_dir}",              # Папка сборки
        f"--specpath={build_dir}",               # Папка spec файла
        "--name=sort-tier",                      # Имя exe
        "--icon=icon.ico",                       # Иконка (если есть)
        "--add-data=.:.",                        # Добавить данные
        str(script)
    ]
    
    print("🔨 Запуск сборки PyInstaller...")
    print(f"Команда: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True)
        print("\n✅ Сборка завершена успешно!")
        print(f"📦 Exe находится в папке: {output_dir}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Ошибка сборки: {e}")
        return False
    except FileNotFoundError:
        print("❌ Ошибка: PyInstaller не установлен.")
        print("Установите: pip install pyinstaller")
        return False

if __name__ == "__main__":
    script = sys.argv[1] if len(sys.argv) > 1 else "sort-tier-safe.py"
    build_with_pyinstaller(script)
