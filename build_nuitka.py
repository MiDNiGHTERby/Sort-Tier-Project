#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_nuitka.py
Оптимизированная сборка с Nuitka для минимизации срабатываний антивирусов.
Требует: pip install nuitka

Использование:
    python build_nuitka.py sort-tier-safe.py
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def build_with_nuitka(script_path: str):
    """Сборка с оптимальными флагами для минимизации AV срабатываний."""
    
    script = Path(script_path)
    if not script.exists():
        print(f"Ошибка: файл {script_path} не найден")
        sys.exit(1)
    
    output_dir = Path("dist")
    output_dir.mkdir(exist_ok=True)
    
    # Оптимальные флаги Nuitka для снижения срабатываний AV
    cmd = [
        "python", "-m", "nuitka",
        "--onefile",                          # Единый exe файл
        "--follow-imports",                   # Следовать импортам
        "--plugin-enable=numpy",              # Плагин numpy (если используется)
        "--remove-output",                    # Удалить промежуточные файлы
        "--output-dir=" + str(output_dir),    # Папка вывода
        "--windows-console-mode=attach",      # Консоль Windows
        "--assume-yes-for-downloads",         # Автозагрузка зависимостей
        "--company-name=SortTier",            # Компания
        "--product-name=Sort Tier",           # Продукт
        "--file-version=1.0.0.0",             # Версия файла
        "--product-version=1.0.0.0",          # Версия продукта
        str(script)
    ]
    
    print("🔨 Запуск сборки Nuitka...")
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
        print("❌ Ошибка: Nuitka не установлен.")
        print("Установите: pip install nuitka")
        return False

if __name__ == "__main__":
    script = sys.argv[1] if len(sys.argv) > 1 else "sort-tier-safe.py"
    build_with_nuitka(script)
