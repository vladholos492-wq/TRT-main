# Инструкция по сборке BB TT Scanner

## Предварительные требования

1. **Python 3.11+** установлен и добавлен в PATH
2. **PowerShell** (встроен в Windows 10+)
3. **Интернет-соединение** для загрузки зависимостей

## Шаг 1: Подготовка окружения

```powershell
# Перейдите в папку проекта
cd bb_tt_scanner

# Создайте виртуальное окружение (опционально, но рекомендуется)
python -m venv venv
.\venv\Scripts\Activate.ps1

# Установите зависимости
python -m pip install -r requirements.txt

# Установите браузеры Playwright
python -m playwright install chromium
```

## Шаг 2: Тестовый запуск

Перед сборкой убедитесь, что приложение работает:

```powershell
python run.py
```

Если всё работает, переходите к сборке.

## Шаг 3: Сборка .exe

```powershell
# Запустите скрипт сборки
.\scripts\build_win.ps1
```

Скрипт:
1. Проверит наличие PyInstaller
2. Установит браузеры Playwright (если нужно)
3. Соберёт .exe в папку `dist/`

**Результат**: `dist\BB_TT_Scanner.exe`

## Шаг 4: Создание ярлыка на рабочем столе

```powershell
.\scripts\make_desktop_shortcut.ps1
```

Ярлык появится на рабочем столе: **"BB TT Scanner.lnk"**

## Решение проблем при сборке

### Ошибка: "PyInstaller не найден"
```powershell
python -m pip install pyinstaller
```

### Ошибка: "Playwright browsers не установлены"
```powershell
python -m playwright install chromium
```

### Ошибка: "Не удаётся найти модуль app"
Убедитесь, что вы запускаете скрипт из папки `bb_tt_scanner`:
```powershell
# Правильно:
cd bb_tt_scanner
.\scripts\build_win.ps1

# Неправильно:
.\bb_tt_scanner\scripts\build_win.ps1
```

### Большой размер .exe (>100 MB)
Это нормально — PyInstaller включает Python, библиотеки и браузер Chromium.

### .exe не запускается
1. Проверьте логи в консоли при запуске
2. Убедитесь, что все зависимости установлены
3. Попробуйте запустить из командной строки для просмотра ошибок:
   ```powershell
   .\dist\BB_TT_Scanner.exe
   ```

## Альтернативная сборка (onefolder)

Если onefile не работает, можно собрать onefolder:

Измените `scripts/build_win.ps1`, замените:
```powershell
"--onefile",
```
на:
```powershell
"--onedir",
```

Результат: папка `dist\BB_TT_Scanner\` с .exe и библиотеками.

## Распространение

Для распространения приложения:
1. Скопируйте `dist\BB_TT_Scanner.exe` (или всю папку `dist\BB_TT_Scanner\`)
2. Отправьте пользователю
3. Пользователь запускает .exe — всё работает!

**Важно**: Playwright браузеры уже включены в .exe, дополнительная установка не требуется.

---

**Готово!** Теперь у вас есть готовый .exe файл для запуска на любом Windows компьютере.



