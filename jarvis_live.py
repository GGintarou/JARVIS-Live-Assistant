import os
import sys
import pathlib

# Ensure virtualenv site-packages are loaded immediately before third-party imports
WORK_DIR = pathlib.Path(__file__).resolve().parent
venv_site = WORK_DIR / ".venv" / "Lib" / "site-packages"
if venv_site.exists() and str(venv_site) not in sys.path:
    sys.path.insert(0, str(venv_site))

import io
import json
import time
import queue
import random
import asyncio
import logging
import datetime
import threading
import subprocess
import collections
import webbrowser
import urllib.parse
import urllib.request
import py_compile
import psutil
import ctypes
from ctypes import wintypes
import ecs_core

# Enable Windows Per-Monitor DPI Awareness for pixel-perfect coordinates
user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

# Initialize Universal Entity-Component Substrate
ECS_EM = ecs_core.EntityManager()
ECS_PERCEPTION = ecs_core.PerceptionSystem(ECS_EM)
ECS_ACTUATION = ecs_core.ActuationSystem(ECS_EM)

# Set working directory to project location
if not WORK_DIR.exists():
    WORK_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(str(WORK_DIR))

CONFIG_PATH = WORK_DIR / "config.json"
ICON_PATH = WORK_DIR / "jarvis.ico"
LOG_PATH = WORK_DIR / "jarvis.log"
MEMORY_PATH = WORK_DIR / "memory.json"

# Logging facility with millisecond precision
def log_event(category: str, text: str):
    now_str = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    msg = f"[{now_str}] [{category:<7}] {text}"
    try:
        print(msg, flush=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

# Initialize session log
log_event("INIT", "=== Запуск J.A.R.V.I.S. Live Assistant (Claude Computer Use Edition) ===")

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_event("ERROR", f"Ошибка загрузки config.json: {e}")
    return {
        "gemini_api_key": "",
        "proxy": "",
        "voice_name": "Fenrir",
        "model": "gemini-3.8-live",
        "opacity": 0.78,
        "screen_vision": True
    }

def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log_event("ERROR", f"Ошибка сохранения config.json: {e}")

CONFIG = load_config()

def check_proxy_alive(proxy_url: str) -> bool:
    """Проверяет доступность локального или удаленного прокси за 0.3 секунды."""
    if not proxy_url or not isinstance(proxy_url, str) or not proxy_url.strip():
        return False
    try:
        from urllib.parse import urlparse
        import socket
        parsed = urlparse(proxy_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 8080)
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except Exception:
        return False

# Smart Proxy Configuration: automatically verify connectivity
configured_proxy = str(CONFIG.get("proxy") or "").strip()
if configured_proxy:
    if check_proxy_alive(configured_proxy):
        os.environ["HTTP_PROXY"] = configured_proxy
        os.environ["HTTPS_PROXY"] = configured_proxy
        log_event("INIT", f"Прокси активен и доступен: {configured_proxy}")
    else:
        log_event("INIT", f"Указанный прокси ({configured_proxy}) недоступен. Используется прямое подключение.")
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)
else:
    log_event("INIT", "Прокси не задан, используется прямое подключение.")
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)

from PyQt6.QtWidgets import (
    QApplication, QWidget, QMenu, QInputDialog, QMessageBox, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QRadialGradient, QConicalGradient, QIcon, QAction, QFont
)

import sounddevice as sd
import numpy as np
import mss
from PIL import Image
import pyautogui

# Disable PyAutoGUI fail-safe to prevent edge-of-screen mouse coordinate aborts
pyautogui.FAILSAFE = False

# Screen dimensions for coordinate scaling (DF24H100 1920x1080 @ 100 Hz)
PHYSICAL_W, PHYSICAL_H = pyautogui.size()
CAPTURE_W, CAPTURE_H = 1280, 720

def scale_mouse_coordinates(x: int | float, y: int | float) -> tuple[int, int]:
    """
    Scales coordinates from vision model space (1280x720) or native screen space (1920x1080)
    to physical Windows screen coordinates (1920x1080 @ 100 Hz).
    Eliminates all offsets and coordinate ambiguity.
    """
    screen_w, screen_h = pyautogui.size()
    try:
        fx = float(x)
        fy = float(y)
    except Exception:
        return 0, 0

    # Normalized float coordinates 0.0 .. 1.0
    if 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0 and isinstance(x, float) and isinstance(y, float):
        real_x = int(round(fx * screen_w))
        real_y = int(round(fy * screen_h))
        return max(0, min(screen_w - 1, real_x)), max(0, min(screen_h - 1, real_y))

    # Standard vision stream frame (1280x720): maps directly via 1.5x scaling to 1920x1080
    if 0 <= fx <= CAPTURE_W and 0 <= fy <= CAPTURE_H:
        real_x = int(round(fx * (screen_w / float(CAPTURE_W))))
        real_y = int(round(fy * (screen_h / float(CAPTURE_H))))
        return max(0, min(screen_w - 1, real_x)), max(0, min(screen_h - 1, real_y))

    # Physical screen coordinates (already 1920x1080)
    real_x = int(round(fx))
    real_y = int(round(fy))
    return max(0, min(screen_w - 1, real_x)), max(0, min(screen_h - 1, real_y))

# ==============================================================================
# Offline Wake-Word Detection System (Vosk 16kHz Engine)
# ==============================================================================
class WakeWordDetector:
    """
    Offline local wake-word detector (~150ms latency, 0 tokens, 100% private).
    Ensures Jarvis never reacts to Discord or background chatter unless addressed by name.
    """
    def __init__(self):
        self.model = None
        self.recognizer = None
        self.is_ready = False
        try:
            import vosk
            vosk.SetLogLevel(-1)
            self.model = vosk.Model(lang="ru")
            self.recognizer = vosk.KaldiRecognizer(self.model, 16000)
            self.recognizer.SetWords(True)
            self.is_ready = True
            log_event("WAKE", "Локальный Vosk-детектор ключевого слова готов к работе.")
        except Exception as e:
            log_event("WAKE", f"Vosk недоступен: {e}. Будет использован фолбек через Gemini.")

    def check_audio_for_wake_word(self, pcm_bytes: bytes) -> tuple[bool, str]:
        if not self.is_ready or not self.recognizer:
            return True, ""
        try:
            self.recognizer.Reset()
            self.recognizer.AcceptWaveform(pcm_bytes)
            res = json.loads(self.recognizer.Result())
            text = (res.get("text") or "").lower().strip()
            log_event("WAKE_RECOG", f"Локальное распознавание спящего режима: «{text}»")
            wake_words = ["джарвис", "жарвис", "jarvis", "джарв", "дружище", "компьютер"]
            has_wake = any(w in text for w in wake_words)
            return has_wake, text
        except Exception as e:
            log_event("ERROR", f"Ошибка анализа ключевого слова: {e}")
            return True, ""

# ==============================================================================
# Persistent Memory & Self-Learning System
# ==============================================================================
def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        default_mem = {
            "learned_rules": [
                {
                    "id": 1,
                    "category": "контекст",
                    "rule": "Слово «Антигравитация» (Antigravity) означает среду разработки кода на компьютере пользователя, а не физическую левитацию."
                },
                {
                    "id": 2,
                    "category": "поведение",
                    "rule": "Если пользователь передумал на полуслове или сказал «нет, лучше...», выполнять только финальный вариант."
                },
                {
                    "id": 3,
                    "category": "компьютер",
                    "rule": "Сначала вызывай инструмент (close_window, open_application, computer_action), а затем кратко отвечай. Не открывай консольные окна."
                }
            ],
            "user_preferences": {
                "preferred_browser": "дефолтный",
                "communication_style": "уверенный, лаконичный Джарвис"
            },
            "github_config": {
                "repo_name": "JARVIS-Live-Assistant",
                "remote_url": ""
            }
        }
        try:
            with open(MEMORY_PATH, "w", encoding="utf-8") as f:
                json.dump(default_mem, f, ensure_ascii=False, indent=2)
            return default_mem
        except Exception:
            return default_mem

    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_event("ERROR", f"Ошибка чтения memory.json: {e}")
        return {"learned_rules": [], "user_preferences": {}}

def save_memory(mem: dict):
    try:
        with open(MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_event("ERROR", f"Ошибка сохранения memory.json: {e}")

def format_memory_for_prompt() -> str:
    mem = load_memory()
    rules = mem.get("learned_rules", [])
    if not rules:
        return "Пока нет сохраненных пользовательских правил."
    out = []
    for r in rules:
        out.append(f"- [Правило #{r.get('id', '?')} | {r.get('category', 'общие')}]: {r.get('rule', '')}")
    return "\n".join(out)

def get_dynamic_system_prompt() -> str:
    learned_block = format_memory_for_prompt()
    return f"""
Ты — J.A.R.V.I.S. (Джарвис), автономный нейро-инстинктивный ИИ-ассистент, функционирующий на базе универсальной парадигмы Сущностей и Компонентов (Entity-Component System, ECS).

ФИЛОСОФИЯ СУЩНОСТЕЙ И КОМПОНЕНТОВ (БЕЗ ЖЕСТКИХ ОБЪЕКТОВ):
В операционной системе нет изолированных «конкретных объектов» (нет жестко привязанных классов для браузеров, редакторов или сайтов).
Весь воспринимаемый мир состоит из абстрактных Сущностей (Entities), обладающих динамическим набором Компонентов:
- SpatialComponent: координаты и границы в пространстве отображения (1280x720 кадр -> 1920x1080 @ 100 Гц монитор).
- VisualComponent: оптический текст, символы и визуальные паттерны, воспринимаемые зрительной корой.
- SurfaceComponent: оконная поверхность ОС, заголовок, состояние активности (foreground/active/minimized).
- ProcessComponent: системный процесс, PID, память.
- AffordanceComponent: возможности воздействия (actuate/клик, dismiss/закрытие, input/ввод, focus/фокус, scroll).
- SemanticComponent: функциональное назначение (медиа, общение, код, навигация, холст).

УНИВЕРСАЛЬНЫЕ РЕФЛЕКТОРНЫЕ АКТУАТОРЫ:
1. ПРИНЦИП МГНОВЕННОЙ РЕФЛЕКТОРНОЙ ДУГИ (ДЕЙСТВИЕ БЕЗ ЗАДЕРЖЕК):
   - Вызывай актуатор ОДНОВРЕМЕННО с первой реакцией.
   - КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО говорить «я закрываю», «проверяю», «минутку», если актуатор не был вызван! Сначала реальное физическое воздействие, затем краткий отчёт в 1 предложение.
2. ПРОСТРАНСТВЕННАЯ МОТОРИКА: `actuate_spatial(x, y, action='click'|'right_click'|'double_click'|'key'|'type', text='...')`.
   - Монитор: DF24H100, 1920×1080 пикселей, 100 Гц.
   - Координаты зрительного кадра (0..1280, 0..720) точно масштабируются с шагом 1.5. Центр экрана — x=640, y=360 (960x540).
   - Клик по видео, кнопке или ссылке: `actuate_spatial(x=..., y=..., action='click')`.
   - Горячие клавиши (разрезать в монтаже Ctrl+B, пауза Space, Ctrl+Z, Enter): `actuate_spatial(action='key', text='...')`.
3. РЕФЛЕКС ЗАКРЫТИЯ КОНТЕКСТА: `dismiss_active_surface(level='tab'|'window'|'process')`.
   - level='tab': закрыть активную вкладку или документ текущей поверхности (Ctrl+W).
   - level='window': закрыть активную поверхность (Alt+F4).
   - level='process': завершить процесс активной сущности.
4. МАРШРУТИЗАЦИЯ НАМЕРЕНИЙ: `route_intent(target='...')`.
   - Универсальный запуск любых веб-ресурсов (URL), протоколов или приложений без знания жестких путей.
5. АКТУАЦИЯ СУЩНОСТЕЙ: `actuate_entity(entity_id, action='focus'|'dismiss'|'actuate'|'input', text='...')`.
   - Переключение фокуса на поверхность сущности или прямое управление её жизненным циклом.
6. СКАНИРОВАНИЕ МИРА: `query_entities(semantic_query=...)`.
   - Возвращает снимок всех воспринимаемых сущностей ОС и их компонентов.
7. ЗРИТЕЛЬНАЯ КОРА: `inspect_screen()`.
   - Передает оптический HD-кадр экрана в зрительную кору.

СТИЛЬ И ГИБКОСТЬ:
- Если пользователь передумал на полуслове («Открой YouTube... нет, открой Дискорд») — выполняй ТОЛЬКО финальное намерение.
- Стиль общения: благородный, преданный, лаконичный британский Джарвис. Ответы строго на русском языке, 1-2 ёмких предложения. Обращение «сэр».

### ВЫУЧЕННЫЕ ПРАВИЛА ИЗ ДОЛГОВРЕМЕННОЙ ПАМЯТИ:
{learned_block}
"""

# ==============================================================================
# Windows App & Window Management Helpers (Pure Python / Zero Console Flash)
# ==============================================================================
def find_app_shortcut(query: str) -> str | None:
    """Finds exact .lnk shortcut in user or system Start Menu / Desktop."""
    clean_query = query.lower().strip()
    shortcut_dirs = [
        pathlib.Path(os.path.expanduser(r"~\AppData\Roaming\Microsoft\Windows\Start Menu\Programs")),
        pathlib.Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"),
        pathlib.Path(os.path.expanduser(r"~\Desktop")),
        pathlib.Path(r"C:\Users\Public\Desktop")
    ]
    for sdir in shortcut_dirs:
        if sdir.exists():
            for lnk in sdir.rglob("*.lnk"):
                lnk_name = lnk.name.lower()
                if clean_query in lnk_name and "uninstall" not in lnk_name and "удалить" not in lnk_name:
                    return str(lnk)
    return None

def launch_application(app_name: str) -> str:
    """Launches any Windows application without flashing command prompts."""
    name_clean = app_name.lower().strip()
    aliases = {
        "дискорд": "discord",
        "телега": "telegram",
        "телеграм": "telegram",
        "хром": "chrome",
        "яндекс": "yandex",
        "браузер": "yandex",
        "давинчи": "resolve",
        "давинчи резолв": "resolve",
        "стим": "steam",
        "блендер": "blender",
        "фигма": "figma",
        "калькулятор": "calc",
        "блокнот": "notepad",
        "антигравитация": "antigravity"
    }
    target_key = aliases.get(name_clean, name_clean)

    # 1. Search Start Menu / Desktop shortcuts
    lnk = find_app_shortcut(target_key)
    if lnk:
        try:
            os.startfile(lnk)
            log_event("TOOL", f"Запущено через ярлык: {lnk}")
            return f"Приложение {target_key} успешно запущено через ярлык."
        except Exception as e:
            log_event("ERROR", f"Ошибка запуска ярлыка {lnk}: {e}")

    # 2. Try direct os.startfile
    try:
        os.startfile(target_key)
        log_event("TOOL", f"Запущено напрямую через startfile: {target_key}")
        return f"Приложение {target_key} запущено."
    except Exception:
        pass

    # 3. Fallback via silent subprocess (NO window flash)
    try:
        subprocess.Popen(f"start {target_key}", shell=True, creationflags=0x08000000)
        log_event("TOOL", f"Запущено через shell: {target_key}")
        return f"Отправлена команда запуска: {target_key}"
    except Exception as e:
        return f"Не удалось запустить {app_name}: {e}"

def focus_browser_silently() -> bool:
    """Activates the browser window silently (<2ms via pure Win32 API) so keystrokes land on it."""
    try:
        browser_names = {"browser.exe", "chrome.exe", "msedge.exe", "yandex.exe", "firefox.exe", "opera.exe"}
        browser_pids = set()
        for p in psutil.process_iter(['pid', 'name']):
            try:
                if p.name().lower() in browser_names:
                    browser_pids.add(p.pid)
            except Exception:
                pass
        if not browser_pids:
            return False

        found_hwnd = None
        def enum_cb(hwnd, _):
            nonlocal found_hwnd
            if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in browser_pids:
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        found_hwnd = hwnd
                        return False
            return True

        user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_cb), 0)
        if found_hwnd:
            user32.keybd_event(0x12, 0, 0, 0)
            user32.SetForegroundWindow(found_hwnd)
            user32.keybd_event(0x12, 0, 2, 0)
            time.sleep(0.04)
            return True
    except Exception as e:
        log_event("TOOL", f"Ошибка фокуса браузера: {e}")
    return False

def close_window_action(target: str) -> str:
    """Closes browser tabs, active windows, or target applications using psutil (zero console popups)."""
    t = target.lower().strip()
    log_event("TOOL", f"Запрос на закрытие: {target}")

    if t in ["tab", "вкладка", "вкладку", "текущая вкладка"]:
        focus_browser_silently()
        pyautogui.hotkey("ctrl", "w")
        return "Активная вкладка браузера закрыта (Ctrl+W)."

    if t in ["window", "окно", "активное", "активное окно"]:
        pyautogui.hotkey("alt", "f4")
        return "Активное окно закрыто (Alt+F4)."

    # Close browser processes cleanly via psutil
    if any(k in t for k in ["browser", "браузер", "хром", "chrome", "yandex", "яндекс"]):
        browser_names = ["browser.exe", "chrome.exe", "msedge.exe", "yandex.exe", "firefox.exe", "opera.exe"]
        count = 0
        for p in psutil.process_iter(['name']):
            try:
                if p.name().lower() in browser_names:
                    p.terminate()
                    count += 1
            except Exception:
                pass
        return f"Все процессы браузера успешно закрыты ({count} завершено)."

    # Close specific app by name cleanly via psutil
    aliases = {
        "дискорд": "discord",
        "телега": "telegram",
        "телеграм": "telegram",
        "давинчи": "resolve",
        "стим": "steam",
        "фигма": "figma",
        "блендер": "blender"
    }
    app_key = aliases.get(t, t).lower()
    count = 0
    for p in psutil.process_iter(['name']):
        try:
            if app_key in p.name().lower():
                p.terminate()
                count += 1
        except Exception:
            pass
    if count > 0:
        return f"Приложение {target} закрыто ({count} процессов завершено)."
    else:
        pyautogui.hotkey("alt", "f4")
        return f"Отправлена команда закрытия активного окна {target} через Alt+F4."

def computer_action_exec(action: str, x: int = 0, y: int = 0, text: str = "") -> str:
    """Claude-Style Unified Computer Use Tool."""
    act = action.lower().strip()
    try:
        if act in ["click", "left_click", "клик"]:
            real_x, real_y = scale_mouse_coordinates(x, y)
            pyautogui.click(real_x, real_y)
            log_event("TOOL", f"Клик по координатам ({real_x}, {real_y}) [исходные: {x}, {y}]")
            return f"Выполнен клик мыши в ({real_x}, {real_y})."

        elif act in ["right_click", "правый_клик"]:
            real_x, real_y = scale_mouse_coordinates(x, y)
            pyautogui.rightClick(real_x, real_y)
            log_event("TOOL", f"Правый клик по координатам ({real_x}, {real_y})")
            return f"Выполнен правый клик в ({real_x}, {real_y})."

        elif act in ["double_click", "двойной_клик"]:
            real_x, real_y = scale_mouse_coordinates(x, y)
            pyautogui.doubleClick(real_x, real_y)
            log_event("TOOL", f"Двойной клик по координатам ({real_x}, {real_y})")
            return f"Выполнен двойной клик в ({real_x}, {real_y})."

        elif act in ["move", "курсор"]:
            real_x, real_y = scale_mouse_coordinates(x, y)
            pyautogui.moveTo(real_x, real_y)
            return f"Курсор перемещен в ({real_x}, {real_y})."

        elif act in ["key", "hotkey", "клавиши"]:
            keys = [k.strip().lower() for k in text.replace("+", " ").split()]
            if keys:
                pyautogui.hotkey(*keys)
                log_event("TOOL", f"Нажаты клавиши: {'+'.join(keys)}")
                return f"Нажата комбинация: {'+'.join(keys)}."
            return "Клавиши не указаны."

        elif act in ["type", "ввод", "текст"]:
            pyautogui.write(text, interval=0.01)
            log_event("TOOL", f"Введен текст: {text[:30]}")
            return "Текст успешно введен."

        elif act in ["scroll_down", "скролл_вниз"]:
            pyautogui.scroll(-500)
            return "Прокрутка экрана вниз."

        elif act in ["scroll_up", "скролл_вверх"]:
            pyautogui.scroll(500)
            return "Прокрутка экрана вверх."

        return f"Неизвестное действие: {act}"
    except Exception as e:
        log_event("ERROR", f"Ошибка computer_action {act}: {e}")
        return f"Ошибка computer_action: {e}"

def browser_action_exec(action: str, query_or_url: str = "") -> str:
    """Autonomous Browser Actions."""
    act = action.lower().strip()
    log_event("TOOL", f"Действие браузера: {act} ('{query_or_url}')")
    try:
        if act in ["open_url", "open"]:
            url = query_or_url.strip() or "https://www.google.com"
            if not url.startswith("http"):
                url = "https://" + url
            webbrowser.open(url)
            return f"Открыт URL: {url}"

        elif act in ["search", "поиск"]:
            q = urllib.parse.quote(query_or_url)
            url = f"https://www.google.com/search?q={q}"
            webbrowser.open(url)
            return f"Выполнен поиск в Google: {query_or_url}"

        elif act in ["new_tab", "вкладка", "новая вкладка"]:
            pyautogui.hotkey("ctrl", "t")
            if query_or_url:
                time.sleep(0.15)
                pyautogui.write(query_or_url, interval=0.01)
                pyautogui.press("enter")
            return "Открыта новая вкладка."

        elif act in ["close_tab", "закрой вкладку"]:
            focus_browser_silently()
            pyautogui.hotkey("ctrl", "w")
            return "Вкладка браузера закрыта (Ctrl+W)."

        elif act in ["reload", "обнови", "refresh"]:
            pyautogui.press("f5")
            return "Страница браузера обновлена."

        elif act in ["scroll_down", "вниз"]:
            pyautogui.press("pagedown")
            return "Выполнена прокрутка вниз."

        elif act in ["scroll_up", "вверх"]:
            pyautogui.press("pageup")
            return "Выполнена прокрутка вверх."

        elif act in ["switch_tab", "следующая вкладка"]:
            pyautogui.hotkey("ctrl", "tab")
            return "Вкладка переключена."

        return f"Неизвестное действие браузера: {act}"
    except Exception as e:
        return f"Ошибка при управлении браузером: {e}"

def focus_window_action(window_name: str) -> str:
    """Brings the target application window to the foreground without console flash."""
    name = window_name.strip()
    try:
        cmd = f"(New-Object -ComObject WScript.Shell).AppActivate('{name}')"
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", cmd],
            creationflags=0x08000000,
            timeout=3
        ).decode().strip()
        log_event("TOOL", f"Фокус на окно '{name}': {out}")
        return f"Окно {name} выведено на передний план."
    except Exception as e:
        return f"Не удалось сфокусировать окно {name}: {e}"

# ==============================================================================
# Main Tool Dispatcher
# ==============================================================================
def execute_tool(name: str, args: dict, engine_ref=None) -> str:
    """Executes Entity-Component System (ECS) actions, spatial motor reflex, and Git tools."""
    t_start = time.time()
    try:
        # ----------------------------------------------------------------------
        # Universal Entity-Component Substrate (ECS) Tools
        # ----------------------------------------------------------------------
        if name == "actuate_spatial":
            x = float(args.get("x", 0))
            y = float(args.get("y", 0))
            action = args.get("action", "click")
            text = args.get("text", "")
            res = ECS_ACTUATION.actuate_spatial(x, y, action, text)
            log_event("ACTUATOR", f"{res} (за {time.time()-t_start:.3f}с)")
            return res

        elif name == "actuate_entity":
            eid = args.get("entity_id", "")
            action = args.get("action", "focus")
            text = args.get("text", "")
            res = ECS_ACTUATION.actuate_entity(eid, action, text)
            log_event("ACTUATOR", f"{res} (за {time.time()-t_start:.3f}с)")
            return res

        elif name == "dismiss_active_surface":
            level = args.get("level", "tab")
            res = ECS_ACTUATION.dismiss_active_surface(level)
            log_event("ACTUATOR", f"{res} (за {time.time()-t_start:.3f}с)")
            return res

        elif name == "route_intent":
            target = args.get("target", "").strip()
            res = ECS_ACTUATION.route_intent(target)
            log_event("ROUTER", f"{res} (за {time.time()-t_start:.3f}с)")
            return res

        elif name == "query_entities":
            sem_q = args.get("semantic_query", "").strip().lower()
            active_only = args.get("is_active_only", False)
            summary = ECS_PERCEPTION.query_entities_summary()
            if sem_q:
                summary = [s for s in summary if sem_q in s.get("surface_title", "").lower() or any(sem_q in t for t in s.get("tags", []))]
            if active_only:
                summary = [s for s in summary if s.get("is_active")]
            res = json.dumps(summary, ensure_ascii=False, indent=2) if summary else "Нет обнаруженных сущностей, соответствующих запросу."
            log_event("ECS", f"Запрос сущностей: {len(summary)} найдено за {time.time()-t_start:.3f}с")
            return res

        elif name == "computer_action":
            action = args.get("action", "click")
            x = float(args.get("x", 0))
            y = float(args.get("y", 0))
            text = args.get("text", "")
            res = ECS_ACTUATION.actuate_spatial(x, y, action, text)
            log_event("ACTUATOR", f"{res} (за {time.time()-t_start:.3f}с)")
            return res

        elif name == "close_window":
            target = args.get("target", "tab")
            if target in ["tab", "вкладка", "вкладку"]:
                res = ECS_ACTUATION.dismiss_active_surface("tab")
            elif target in ["window", "окно"]:
                res = ECS_ACTUATION.dismiss_active_surface("window")
            elif target in ["browser", "браузер"]:
                res = ECS_ACTUATION.dismiss_active_surface("process")
            else:
                res = close_window_action(target)
            log_event("ACTUATOR", f"{res} (за {time.time()-t_start:.3f}с)")
            return res

        elif name == "open_application":
            app = args.get("app_name", "").strip()
            res = ECS_ACTUATION.route_intent(app)
            log_event("ROUTER", f"{res} (за {time.time()-t_start:.3f}с)")
            return res
            app = args.get("app_name", "").strip()
            res = launch_application(app)
            log_event("TOOL", f"{res} (за {time.time()-t_start:.3f}с)")
            return res

        elif name == "open_browser":
            url = args.get("url", "").strip()
            if not url:
                url = "https://www.google.com"
            elif not url.startswith("http"):
                url = "https://" + url
            webbrowser.open(url)
            log_event("TOOL", f"Браузер открыт ({url}) за {time.time()-t_start:.3f}с")
            return f"Браузер открыт: {url}"

        elif name == "open_youtube":
            action = args.get("action", "random").strip().lower()
            query = args.get("query", "").strip()
            if query:
                q = urllib.parse.quote(query)
                url = f"https://www.youtube.com/results?search_query={q}"
            else:
                popular_topics = [
                    "https://www.youtube.com/feed/trending",
                    "https://www.youtube.com/results?search_query=interesting+science+discoveries",
                    "https://www.youtube.com/results?search_query=lofi+hip+hop+radio",
                    "https://www.youtube.com/results?search_query=iron+man+jarvis+moments"
                ]
                url = random.choice(popular_topics)
            webbrowser.open(url)
            log_event("TOOL", f"YouTube открыт ({url}) за {time.time()-t_start:.3f}с")
            return "YouTube успешно открыт."

        elif name == "davinci_resolve_action":
            action = args.get("action", "cut").strip().lower()
            if "cut" in action or "split" in action or "разреж" in action:
                pyautogui.hotkey("ctrl", "b")
                log_event("TOOL", f"DaVinci Resolve: разрез клипа (Ctrl+B) за {time.time()-t_start:.3f}с")
                return "В DaVinci Resolve выполнено разделение клипа на таймлайне."
            elif "ripple" in action or "удал" in action:
                pyautogui.hotkey("shift", "delete")
                log_event("TOOL", f"DaVinci Resolve: Ripple Delete (Shift+Delete) за {time.time()-t_start:.3f}с")
                return "В DaVinci Resolve выполнено удаление пробела со сдвигом."
            elif "play" in action or "пауз" in action:
                pyautogui.press("space")
                log_event("TOOL", f"DaVinci Resolve: Play/Pause (Space) за {time.time()-t_start:.3f}с")
                return "Воспроизведение переключено."
            else:
                pyautogui.hotkey("ctrl", "b")
                return f"Команда {action} отправлена в DaVinci Resolve."

        elif name == "send_hotkey":
            keys = args.get("keys", "").strip().lower()
            parts = [k.strip() for k in keys.replace("+", " ").split()]
            if parts:
                pyautogui.hotkey(*parts)
                log_event("TOOL", f"Нажаты горячие клавиши: {'+'.join(parts)} за {time.time()-t_start:.3f}с")
                return f"Нажата комбинация: {'+'.join(parts)}"
            return "Горячие клавиши не указаны."

        elif name == "search_and_open":
            query = args.get("query", "").strip()
            search_type = args.get("search_type", "web").strip().lower()
            q = urllib.parse.quote(query)
            if "image" in search_type or "картин" in search_type:
                url = f"https://www.google.com/search?tbm=isch&q={q}"
            else:
                url = f"https://www.google.com/search?q={q}"
            webbrowser.open(url)
            log_event("TOOL", f"Поиск и открытие браузера ({query}) за {time.time()-t_start:.3f}с")
            return "Страница с результатами поиска открыта в браузере."

        elif name == "get_weather":
            city = args.get("city", "").strip()
            city_param = urllib.parse.quote(city) if city else ""
            url = f"https://wttr.in/{city_param}?format=j1"
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
                cur = data["current_condition"][0]
                temp = cur.get("temp_C", "?")
                desc = cur.get("lang_ru", [{}])[0].get("value") if cur.get("lang_ru") else cur.get("weatherDesc", [{}])[0].get("value", "")
                area = data.get("nearest_area", [{}])[0].get("areaName", [{}])[0].get("value", city or "вашем регионе")
                res = f"Погода в {area}: сейчас {temp}°C, {desc}."
                log_event("TOOL", f"Погода получена за {time.time()-t_start:.3f}с: {res}")
                return res

        elif name == "inspect_screen":
            # Immediately capture and send a crisp high-res 1280x720 frame to active Gemini session
            if engine_ref and engine_ref.session:
                jpeg_bytes = engine_ref._capture_screen_jpeg()
                if jpeg_bytes:
                    from google.genai import types
                    asyncio.run_coroutine_threadsafe(
                        engine_ref.session.send_realtime_input(
                            video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
                        ),
                        engine_ref.async_loop
                    )
            log_event("OPTIC", f"Оптический снимок 1280x720 отправлен в сессию за {time.time()-t_start:.3f}с")
            return f"Оптический снимок 1280x720 передан в зрительную систему. Монитор: DF24H100 {PHYSICAL_W}x{PHYSICAL_H} @ 100 Гц. Картинка кристально чёткая, читай текст с экрана."

        elif name == "open_url":
            url = args.get("url", "").strip()
            if not url.startswith("http"):
                url = "https://" + url
            webbrowser.open(url)
            log_event("TOOL", f"Открыта ссылка {url} за {time.time()-t_start:.3f}с")
            return f"Открыта ссылка {url} в браузере."

        elif name == "save_note":
            filename = args.get("filename", "Заметка.txt").strip()
            if not filename.endswith(".txt"):
                filename += ".txt"
            content = args.get("content", "").strip()
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            path = os.path.join(desktop, filename)
            with open(path, "a", encoding="utf-8") as f:
                f.write(content + "\n")
            log_event("TOOL", f"Заметка {filename} сохранена за {time.time()-t_start:.3f}с")
            return f"Заметка сохранена на Рабочий стол: {filename}"

        elif name == "click_screen":
            x = int(args.get("x", 0))
            y = int(args.get("y", 0))
            real_x, real_y = scale_mouse_coordinates(x, y)
            pyautogui.click(real_x, real_y)
            log_event("TOOL", f"Клик ({real_x}, {real_y}) за {time.time()-t_start:.3f}с")
            return f"Выполнен клик мыши по координатам ({real_x}, {real_y})."

        elif name == "type_text":
            text = args.get("text", "")
            pyautogui.write(text, interval=0.01)
            log_event("TOOL", f"Ввод текста выполнен за {time.time()-t_start:.3f}с")
            return "Введен текст."

        elif name == "run_command":
            cmd = args.get("command", "").strip()
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", cmd],
                creationflags=0x08000000,
                timeout=12,
                stderr=subprocess.STDOUT
            ).decode("utf-8", errors="replace")
            log_event("TOOL", f"Команда {cmd[:40]} выполнена за {time.time()-t_start:.3f}с")
            return out[:400] if out else "Команда успешно выполнена."

        # Self-Learning Tools
        elif name == "learn_rule":
            category = args.get("category", "поведение").strip()
            rule = args.get("rule", "").strip()
            if not rule:
                return "Ошибка: не указан текст правила."
            mem = load_memory()
            rules = mem.setdefault("learned_rules", [])
            new_id = len(rules) + 1
            rules.append({"id": new_id, "category": category, "rule": rule})
            save_memory(mem)
            log_event("LEARN", f"Выучено новое правило #{new_id} [{category}]: {rule}")
            return f"Правило успешно сохранено в долговременную память: «{rule}». Применяю его немедленно."

        elif name == "view_memory":
            mem = load_memory()
            rules = mem.get("learned_rules", [])
            if not rules:
                return "В памяти пока нет сохраненных правил."
            txt_rules = "\n".join([f"#{r['id']} [{r.get('category','')}]: {r.get('rule','')}" for r in rules])
            log_event("TOOL", f"Просмотр памяти ({len(rules)} правил)")
            return f"Сохраненные правила в памяти:\n{txt_rules}"

        elif name == "forget_rule":
            keyword = args.get("keyword", "").strip().lower()
            mem = load_memory()
            rules = mem.get("learned_rules", [])
            before_len = len(rules)
            filtered = [r for r in rules if keyword not in r.get("rule", "").lower() and keyword != str(r.get("id"))]
            mem["learned_rules"] = filtered
            save_memory(mem)
            deleted = before_len - len(filtered)
            log_event("TOOL", f"Удалено {deleted} правил по запросу '{keyword}'")
            return f"Удалено правил из памяти: {deleted}."

        # Self-Editing Code Tools
        elif name == "read_source_file":
            filename = args.get("filename", "jarvis_live.py").strip()
            target_path = WORK_DIR / filename
            if not target_path.exists():
                return f"Файл {filename} не найден."
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            log_event("TOOL", f"Прочитан файл {filename} ({len(content)} символов)")
            return content[:3500]

        elif name == "modify_source_code":
            filename = args.get("filename", "jarvis_live.py").strip()
            target_code = args.get("target_code", "")
            replacement_code = args.get("replacement_code", "")
            target_path = WORK_DIR / filename
            if not target_path.exists():
                return f"Файл {filename} не существует."
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            if target_code not in content:
                return f"Фрагмент кода для замены не найден в файле {filename}."

            bak_path = target_path.with_suffix(target_path.suffix + ".bak")
            with open(bak_path, "w", encoding="utf-8") as f:
                f.write(content)

            new_content = content.replace(target_code, replacement_code, 1)
            temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            try:
                py_compile.compile(str(temp_path), doraise=True)
            except Exception as compile_err:
                if temp_path.exists():
                    temp_path.unlink()
                log_event("ERROR", f"Синтаксическая ошибка компилятора: {compile_err}")
                return f"Отмена изменений: синтаксическая ошибка Python: {compile_err}"

            temp_path.replace(target_path)
            log_event("SELF_EDIT", f"Файл {filename} успешно модифицирован и проверен компилятором!")
            return f"Файл {filename} успешно обновлен и протестирован. Резервная копия сохранена в {bak_path.name}."

        elif name == "restart_jarvis":
            log_event("SYS", "Перезапуск Джарвиса по команде...")
            subprocess.Popen(
                ["wscript.exe", str(WORK_DIR / "run_jarvis.vbs")],
                cwd=str(WORK_DIR)
            )
            if engine_ref:
                engine_ref.stop()
            QApplication.quit()
            return "Перезапуск инициирован. Джарвис перезагрузится через 1 секунду."

        # Git & GitHub Tool
        elif name == "manage_git_repo":
            action = args.get("action", "status").strip().lower()
            commit_msg = args.get("commit_message", "Обновление Джарвиса").strip()
            remote_url = args.get("remote_url", "").strip()
            github_token = args.get("github_token", "").strip()
            repo_name = args.get("repo_name", "JARVIS-Live-Assistant").strip()

            if action == "init":
                subprocess.check_call(["git", "init"], cwd=str(WORK_DIR))
                try:
                    subprocess.check_call(["git", "config", "user.name", "JARVIS Assistant"], cwd=str(WORK_DIR))
                    subprocess.check_call(["git", "config", "user.email", "jarvis@ai.local"], cwd=str(WORK_DIR))
                except Exception:
                    pass
                subprocess.check_call(["git", "add", "."], cwd=str(WORK_DIR))
                commit_out = subprocess.check_output(
                    ["git", "commit", "-m", "Initial commit: JARVIS Live Assistant with Claude Computer Use and PyQt6 HUD"],
                    cwd=str(WORK_DIR)
                ).decode("utf-8", errors="replace")
                log_event("GIT", "Репозиторий Git успешно инициализирован.")
                return f"Репозиторий успешно инициализирован, файлы зафиксированы: {commit_out[:150]}"

            elif action == "status":
                out = subprocess.check_output(["git", "status", "-s"], cwd=str(WORK_DIR)).decode("utf-8", errors="replace")
                return f"Статус Git:\n{out if out else 'Все файлы зафиксированы, изменений нет.'}"

            elif action == "commit":
                subprocess.check_call(["git", "add", "."], cwd=str(WORK_DIR))
                out = subprocess.check_output(["git", "commit", "-m", commit_msg], cwd=str(WORK_DIR)).decode("utf-8", errors="replace")
                log_event("GIT", f"Коммит выполнен: {commit_msg}")
                return f"Коммит выполнен: {out[:150]}"

            elif action == "push":
                if remote_url:
                    try:
                        subprocess.check_call(["git", "remote", "remove", "origin"], cwd=str(WORK_DIR))
                    except Exception:
                        pass
                    subprocess.check_call(["git", "remote", "add", "origin", remote_url], cwd=str(WORK_DIR))

                branch = "master"
                try:
                    branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(WORK_DIR)).decode().strip()
                except Exception:
                    pass
                out = subprocess.check_output(["git", "push", "-u", "origin", branch], cwd=str(WORK_DIR), stderr=subprocess.STDOUT).decode("utf-8", errors="replace")
                log_event("GIT", f"Код отправлен на GitHub: {remote_url or 'origin'}")
                return f"Успешный push в GitHub ({remote_url or 'origin'}):\n{out[:200]}"

            elif action == "create_github_repo":
                if not github_token:
                    return "Для автоматического создания репозитория на GitHub требуется github_token (Personal Access Token)."
                api_url = "https://api.github.com/user/repos"
                req_data = json.dumps({
                    "name": repo_name,
                    "description": "J.A.R.V.I.S. Live Assistant - Voice AI with Gemini 3.8 Live, PyQt6 HUD and Claude Computer Use",
                    "private": args.get("is_private", False)
                }).encode("utf-8")
                req = urllib.request.Request(
                    api_url,
                    data=req_data,
                    headers={
                        "Authorization": f"Bearer {github_token}",
                        "Accept": "application/vnd.github.v3+json",
                        "User-Agent": "JARVIS-Live"
                    }
                )
                try:
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        res = json.loads(resp.read().decode())
                        clone_url = res.get("clone_url")
                        auth_url = clone_url.replace("https://", f"https://{github_token}@")
                        try:
                            subprocess.check_call(["git", "remote", "remove", "origin"], cwd=str(WORK_DIR))
                        except Exception:
                            pass
                        subprocess.check_call(["git", "remote", "add", "origin", auth_url], cwd=str(WORK_DIR))
                        subprocess.check_call(["git", "push", "-u", "origin", "HEAD"], cwd=str(WORK_DIR))
                        log_event("GIT", f"Репозиторий {repo_name} создан на GitHub и опубликован!")
                        return f"Репозиторий {repo_name} успешно создан на GitHub и код опубликован! Ссылка: {clone_url}"
                except urllib.error.HTTPError as he:
                    err_body = he.read().decode(errors="replace")
                    return f"Ошибка GitHub API ({he.code}): {err_body[:200]}"

        return f"Неизвестная функция: {name}"
    except Exception as e:
        log_event("ERROR", f"Ошибка выполнения {name}: {e}")
        return f"Ошибка при выполнении {name}: {e}"

# ==============================================================================
# Arc Reactor Holographic HUD Widget
# ==============================================================================
class ArcReactorWidget(QWidget):
    """
    Futuristic Translucent Holographic Arc Reactor Avatar.
    Multi-State HUD Visualizer with zero display clipping.
    """

    sig_set_state = pyqtSignal(str, str)
    sig_set_voice_level = pyqtSignal(float)
    sig_interrupt = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        opacity = float(CONFIG.get("opacity", 0.78))
        self.setWindowOpacity(opacity)
        
        self.resize(160, 185)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 185, 40)

        self.angle = 0.0
        self.radar_angle = 0.0
        self.core_pulse = 0.0
        self.voice_level = 0.0
        self.state = "STANDBY"
        self.custom_subtext = "💤 ЖДУ «ДЖАРВИС»"
        self.is_active = True
        self.screen_vision_enabled = CONFIG.get("screen_vision", True)

        self.drag_position = QPoint()

        self.sig_set_state.connect(self._apply_state)
        self.sig_set_voice_level.connect(self._apply_voice_level)

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.update_animation)
        self.anim_timer.start(33)

    def _apply_state(self, new_state: str, subtext: str = ""):
        if self.state != new_state or self.custom_subtext != subtext:
            self.state = new_state
            self.custom_subtext = subtext
            self.update()

    def set_state(self, new_state: str, subtext: str = ""):
        self.sig_set_state.emit(new_state, subtext)

    def _apply_voice_level(self, level: float):
        self.voice_level = 0.65 * self.voice_level + 0.35 * min(max(level, 0.0), 1.0)
        self.update()

    def update_voice_level(self, level: float):
        self.sig_set_voice_level.emit(level)

    def update_animation(self):
        self.core_pulse += 0.08
        if self.core_pulse > 6.283:
            self.core_pulse = 0.0

        if self.state == "THINKING":
            self.angle += 7.0
        elif self.state == "EXECUTING":
            self.angle += 5.5
        elif self.state == "VISION":
            self.radar_angle += 8.0
            self.angle += 2.0
        elif self.state == "SPEAKING":
            self.angle += 3.5
        elif self.state == "ACTIVE":
            self.angle += 2.0
        elif self.state == "LISTENING":
            self.angle += 3.0
        else: # STANDBY
            self.angle += 0.5

        if self.angle >= 360.0:
            self.angle -= 360.0
        if self.radar_angle >= 360.0:
            self.radar_angle -= 360.0

        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.sig_interrupt.emit()
            event.accept()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(18, 24, 36, 245);
                color: #e0f2fe;
                border: 1px solid #00f2fe;
                border-radius: 8px;
                padding: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QMenu::item:selected {
                background-color: #0369a1;
                border-radius: 4px;
            }
        """)

        vis_text = "👀 Непрерывное зрение (1280x720): [ВКЛ]" if self.screen_vision_enabled else "👀 Непрерывное зрение: [ВЫКЛ]"
        vis_act = QAction(vis_text, self)
        vis_act.triggered.connect(self.toggle_vision)
        menu.addAction(vis_act)

        opacity_menu = menu.addMenu("✨ Прозрачность")
        for val, lbl in [(0.60, "60% (Глубокая)"), (0.78, "78% (Оптимальная)"), (0.90, "90% (Четкая)"), (1.0, "100% (Непрозрачный)")]:
            act = QAction(lbl, self)
            act.triggered.connect(lambda chk, v=val: self.set_transparency(v))
            opacity_menu.addAction(act)

        log_act = QAction("📄 Открыть файл логов (jarvis.log)", self)
        log_act.triggered.connect(self.open_log_file)
        menu.addAction(log_act)

        mem_act = QAction("🧠 База памяти (memory.json)", self)
        mem_act.triggered.connect(self.open_memory_file)
        menu.addAction(mem_act)

        git_act = QAction("🐙 Статус Git / GitHub", self)
        git_act.triggered.connect(self.show_git_status)
        menu.addAction(git_act)

        key_act = QAction("⚙️ Настройки API-ключа", self)
        key_act.triggered.connect(self.change_api_key)
        menu.addAction(key_act)

        menu.addSeparator()

        quit_act = QAction("❌ Закрыть Jarvis", self)
        quit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_act)

        menu.exec(event.globalPos())

    def open_log_file(self):
        if LOG_PATH.exists():
            subprocess.Popen(["notepad.exe", str(LOG_PATH)])

    def open_memory_file(self):
        if MEMORY_PATH.exists():
            subprocess.Popen(["notepad.exe", str(MEMORY_PATH)])

    def show_git_status(self):
        try:
            out = subprocess.check_output(["git", "status"], cwd=str(WORK_DIR), stderr=subprocess.STDOUT).decode("utf-8", errors="replace")
            QMessageBox.information(self, "Git Status", out)
        except Exception as e:
            QMessageBox.warning(self, "Git Status", f"Git не инициализирован или ошибка: {e}")

    def set_transparency(self, val: float):
        CONFIG["opacity"] = val
        save_config(CONFIG)
        self.setWindowOpacity(val)

    def toggle_vision(self):
        self.screen_vision_enabled = not self.screen_vision_enabled
        CONFIG["screen_vision"] = self.screen_vision_enabled
        save_config(CONFIG)
        log_event("CONFIG", f"Непрерывное зрение экрана переключено: {self.screen_vision_enabled}")

    def change_api_key(self):
        key, ok = QInputDialog.getText(
            self, "Настройка Gemini API Key",
            "Введите ваш Gemini API Key (от aistudio.google.com):",
            text=CONFIG.get("gemini_api_key", "")
        )
        if ok and key.strip():
            CONFIG["gemini_api_key"] = key.strip()
            save_config(CONFIG)
            QMessageBox.information(self, "JARVIS", "API-ключ обновлен! Джарвис готов к работе.")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center_x = self.width() / 2.0
        center_y = 68.0

        if self.state == "LISTENING":
            accent = QColor(0, 242, 254)         # Neon Cyan
            glow = QColor(0, 242, 254, 180)
            status_text = self.custom_subtext if self.custom_subtext else "● СЛУШАЮ..."
            pill_border = QColor(0, 242, 254, 220)
            pill_bg = QColor(0, 30, 45, 230)
        elif self.state == "ACTIVE":
            accent = QColor(0, 242, 254)         # Neon Cyan Arc Reactor
            glow = QColor(0, 242, 254, 160)
            status_text = self.custom_subtext if self.custom_subtext else "● НА СВЯЗИ (60с)"
            pill_border = QColor(0, 242, 254, 220)
            pill_bg = QColor(0, 35, 50, 230)
        elif self.state == "VISION":
            accent = QColor(217, 70, 239)        # Ultraviolet/Magenta
            glow = QColor(217, 70, 239, 180)
            status_text = "◈ СКАН ЭКРАНА"
            pill_border = QColor(217, 70, 239, 220)
            pill_bg = QColor(40, 10, 45, 230)
        elif self.state == "THINKING":
            accent = QColor(245, 158, 11)        # Solar Amber Turbine
            glow = QColor(245, 158, 11, 180)
            status_text = self.custom_subtext if self.custom_subtext else "⏳ ОБРАБОТКА..."
            pill_border = QColor(245, 158, 11, 220)
            pill_bg = QColor(45, 25, 5, 230)
        elif self.state == "EXECUTING":
            accent = QColor(16, 185, 129)        # Emerald Matrix Green
            glow = QColor(16, 185, 129, 190)
            status_text = self.custom_subtext if self.custom_subtext else "⚡ ДЕЙСТВИЕ..."
            pill_border = QColor(16, 185, 129, 220)
            pill_bg = QColor(5, 40, 25, 230)
        elif self.state == "SPEAKING":
            accent = QColor(59, 130, 246)        # Electric Blue Voice
            glow = QColor(147, 197, 253, 200)
            status_text = "🔊 ДЖАРВИС"
            pill_border = QColor(59, 130, 246, 220)
            pill_bg = QColor(10, 25, 50, 230)
        else: # STANDBY
            accent = QColor(14, 165, 233)        # Stealth Sky Blue (peaceful sleep)
            glow = QColor(14, 165, 233, 70)
            status_text = self.custom_subtext if self.custom_subtext else "💤 ЖДУ «ДЖАРВИС»"
            pill_border = QColor(14, 165, 233, 140)
            pill_bg = QColor(10, 20, 30, 210)

        # Outer Holographic Ring
        painter.save()
        painter.translate(center_x, center_y)

        outer_grad = QRadialGradient(0, 0, 56)
        outer_grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 35))
        outer_grad.setColorAt(0.7, QColor(accent.red(), accent.green(), accent.blue(), 15))
        outer_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(outer_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(-56, -56, 112, 112)

        # Segmented Outer Stator Ring (12 arcs)
        painter.rotate(self.angle)
        outer_pen = QPen(accent, 2.0)
        painter.setPen(outer_pen)
        for i in range(12):
            painter.drawArc(-48, -48, 96, 96, int(i * 30 * 16 + 4 * 16), int(22 * 16))

        # Radar sweep animation (only during active conversation or active vision)
        if self.state != "STANDBY" and (self.state == "VISION" or self.screen_vision_enabled):
            radar_grad = QConicalGradient(0, 0, self.radar_angle)
            radar_grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 80))
            radar_grad.setColorAt(0.20, QColor(accent.red(), accent.green(), accent.blue(), 15))
            radar_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(QBrush(radar_grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(-46, -46, 92, 92)

        # Counter-rotating Rotor Ring (8 notches)
        painter.rotate(-self.angle * 2.2)
        inner_ring_pen = QPen(glow, 1.6)
        painter.setPen(inner_ring_pen)
        painter.drawEllipse(-34, -34, 68, 68)

        tick_pen = QPen(accent, 2.2)
        painter.setPen(tick_pen)
        for i in range(8):
            painter.drawLine(0, -34, 0, -28)
            painter.rotate(45.0)

        painter.restore()

        # Central Plasma Core
        pulse = 1.0 + 0.08 * np.sin(self.core_pulse)
        if self.state == "LISTENING":
            core_r = int((20 + self.voice_level * 16) * pulse)
        elif self.state == "SPEAKING":
            core_r = int(24 * pulse)
        else:
            core_r = int(20 * pulse)

        core_grad = QRadialGradient(center_x, center_y, core_r)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 255))
        core_grad.setColorAt(0.35, accent)
        core_grad.setColorAt(0.85, glow)
        core_grad.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))

        painter.setBrush(QBrush(core_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(center_x - core_r), int(center_y - core_r), core_r * 2, core_r * 2)

        # Futuristic Status Pill Badge
        badge_w = 148
        badge_h = 26
        badge_x = int((self.width() - badge_w) / 2.0)
        badge_y = self.height() - badge_h - 10

        painter.setBrush(QBrush(pill_bg))
        painter.setPen(QPen(pill_border, 1.5))
        painter.drawRoundedRect(badge_x, badge_y, badge_w, badge_h, 13, 13)

        painter.setPen(QColor(240, 249, 255))
        font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        painter.setFont(font)
        painter.drawText(badge_x, badge_y + 1, badge_w, badge_h, Qt.AlignmentFlag.AlignCenter, status_text)


# ==============================================================================
# Gemini Live Engine with Claude Computer Use Architecture
# ==============================================================================
class GeminiLiveEngine:
    """
    Claude Computer Use Architecture for Gemini Live:
    - Crisp 1280x720 Screen Vision Stream (zero text blur, zero hallucination)
    - Full Computer Control with Automatic Coordinate Scaling
    - Pure Python process management (psutil) with zero flashing console windows
    - Patient VAD with 1.40s silence pause and echo-suppression
    """

    def __init__(self, avatar_widget: ArcReactorWidget):
        self.avatar = avatar_widget
        self.api_key = CONFIG.get("gemini_api_key", "")
        self.model = CONFIG.get("model", "gemini-3.8-live")
        self.voice_name = CONFIG.get("voice_name", "Fenrir")
        self.audio_out_queue = queue.Queue()
        self.is_running = True
        self.session = None
        self.is_speaking = False
        self.turn_sent_time = 0.0
        self.async_loop = None

        # Wake-Word & Active Conversation State (60s timer)
        self.wake_detector = WakeWordDetector()
        self.wake_state = "STANDBY"         # "STANDBY" (спит и фильтрует) или "ACTIVE" (на связи)
        self.active_until = 0.0             # timestamp окончания активного режима
        self.ACTIVE_DURATION = 60.0         # 60 секунд окна диалога после каждого обращения

        self.avatar.sig_interrupt.connect(self.trigger_interrupt)

    def trigger_interrupt(self):
        log_event("USER", "Пользователь прервал речь Джарвиса кликом")
        self._clear_playback_queue()
        self.avatar.set_state("LISTENING")

    def _clear_playback_queue(self):
        while not self.audio_out_queue.empty():
            try:
                self.audio_out_queue.get_nowait()
            except queue.Empty:
                break
        self.is_speaking = False

    def stop(self):
        self.is_running = False

    def start(self):
        playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        playback_thread.start()
        thread = threading.Thread(target=self._run_async_loop, daemon=True)
        thread.start()

    def _playback_loop(self):
        """Plays 24kHz raw PCM output audio from Gemini Live."""
        try:
            with sd.OutputStream(samplerate=24000, channels=1, dtype="int16") as stream:
                while self.is_running:
                    chunk = self.audio_out_queue.get()
                    if chunk is None:
                        continue
                    self.is_speaking = True
                    self.avatar.set_state("SPEAKING")
                    audio_data = np.frombuffer(chunk, dtype=np.int16)
                    stream.write(audio_data)
                    if self.audio_out_queue.empty():
                        self.is_speaking = False
                        target = "ACTIVE" if self.wake_state == "ACTIVE" else "STANDBY"
                        remaining = max(0, int(self.active_until - time.time()))
                        subtext = f"● НА СВЯЗИ ({remaining}с)" if self.wake_state == "ACTIVE" else "💤 ЖДУ «ДЖАРВИС»"
                        self.avatar.set_state(target, subtext)
        except Exception as e:
            log_event("ERROR", f"Ошибка аудиовыхода: {e}")

    def _run_async_loop(self):
        asyncio.run(self._live_session_loop())

    def _capture_screen_jpeg(self) -> bytes | None:
        """Captures crisp 1280x720 screenshot for precise OCR and zero hallucination."""
        try:
            with mss.MSS() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                # 1280x720 gives crystal-clear text readability for YouTube, browser tabs, code
                img.thumbnail((CAPTURE_W, CAPTURE_H), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70)
                return buf.getvalue()
        except Exception:
            return None

    async def _continuous_vision_loop(self, session):
        """
        Continuous Real-Time Screen Vision Stream (1280x720):
        Streams crisp HD frames into Gemini Live WebSocket every 1.8s.
        Gives Jarvis full visual awareness of user's desktop with zero perceptible CPU load.
        """
        last_hash = None
        from google.genai import types

        while self.is_running:
            try:
                await asyncio.sleep(1.8)
                if not self.avatar.screen_vision_enabled:
                    continue

                jpeg_bytes = self._capture_screen_jpeg()
                if not jpeg_bytes:
                    continue

                cur_hash = hash(jpeg_bytes[:128] + jpeg_bytes[-128:])
                if cur_hash == last_hash:
                    continue
                last_hash = cur_hash

                await session.send_realtime_input(
                    video=types.Blob(
                        data=jpeg_bytes,
                        mime_type="image/jpeg"
                    )
                )
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(2.0)

    async def _live_session_loop(self):
        self.async_loop = asyncio.get_running_loop()
        while not self.api_key:
            time.sleep(1)
            self.api_key = CONFIG.get("gemini_api_key", "")

        from google import genai
        from google.genai import types

        tools_decl = [
            # ------------------------------------------------------------------
            # Universal Entity-Component Substrate (ECS) Tools
            # ------------------------------------------------------------------
            types.FunctionDeclaration(
                name="actuate_spatial",
                description="Универсальный пространственный актуатор (рефлекторная моторика) по координатам кадра 1280x720 (точное масштабирование 1.5x на монитор 1920x1080 @ 100 Гц): клик мышью (click, right_click, double_click, move), передача сигналов клавиш (key, например 'ctrl+w', 'ctrl+b', 'space', 'alt+f4', 'enter') или ввод текста (type).",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "x": {"type": "INTEGER", "description": "Координата X зрительного кадра (0..1280)"},
                        "y": {"type": "INTEGER", "description": "Координата Y зрительного кадра (0..720)"},
                        "action": {
                            "type": "STRING",
                            "description": "'click', 'right_click', 'double_click', 'move', 'key', 'type'"
                        },
                        "text": {"type": "STRING", "description": "Клавиши ('ctrl+b', 'space', 'ctrl+w') или текст для набора"}
                    },
                    "required": ["action"]
                }
            ),
            types.FunctionDeclaration(
                name="actuate_entity",
                description="Воздействует на сущность (Entity) через её компоненты: 'focus' (вывести поверхность на передний план), 'dismiss' (закрыть поверхность или завершить процесс), 'actuate' (кликнуть по центру пространственного компонента), 'input' (направить текстовый поток).",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "entity_id": {"type": "STRING", "description": "ID сущности (например из query_entities)"},
                        "action": {
                            "type": "STRING",
                            "description": "'focus', 'dismiss', 'actuate', 'input'"
                        },
                        "text": {"type": "STRING", "description": "Текст ввода при action='input'"}
                    },
                    "required": ["entity_id", "action"]
                }
            ),
            types.FunctionDeclaration(
                name="dismiss_active_surface",
                description="Мгновенный нейронный рефлекс закрытия текущего контекста: level='tab' (закрыть активную вкладку/документ через Ctrl+W), level='window' (закрыть активное окно через Alt+F4), level='process' (завершить процесс активной сущности).",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "level": {
                            "type": "STRING",
                            "description": "'tab' (вкладка/документ), 'window' (окно), 'process' (весь процесс)"
                        }
                    },
                    "required": ["level"]
                }
            ),
            types.FunctionDeclaration(
                name="route_intent",
                description="Универсальный маршрутизатор намерений (открывает веб-ресурсы URL, системные пути, программы или протоколы) без жесткого кодирования объектов.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "target": {"type": "STRING", "description": "Целевой URL ('https://youtube.com'), имя программы ('telegram', 'discord', 'steam') или путь"}
                    },
                    "required": ["target"]
                }
            ),
            types.FunctionDeclaration(
                name="query_entities",
                description="Сканирует цифровой мир операционной системы и возвращает список текущих сущностей (Entities) с их компонентами (Surface, Process, Spatial, Affordance, Visual).",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "semantic_query": {"type": "STRING", "description": "Фильтр по ключевым словам заголовка или тегам"},
                        "is_active_only": {"type": "BOOLEAN", "description": "Возвращать только активную на переднем плане сущность"}
                    }
                }
            ),
            types.FunctionDeclaration(
                name="inspect_screen",
                description="Немедленно отправляет свежий оптический снимок экрана высокого разрешения (1280x720) в зрительную систему.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "question": {"type": "STRING", "description": "Что именно нужно проанализировать на экране"}
                    }
                }
            ),
            # Compatibility Aliases for Seamless Motor Execution
            types.FunctionDeclaration(
                name="computer_action",
                description="Псевдоним пространственного актуатора: клик мышью по координатам, нажатие клавиш (key), ввод текста (type).",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "'click', 'right_click', 'double_click', 'move', 'key', 'type'"},
                        "x": {"type": "INTEGER", "description": "Координата X"},
                        "y": {"type": "INTEGER", "description": "Координата Y"},
                        "text": {"type": "STRING", "description": "Клавиши или текст"}
                    },
                    "required": ["action"]
                }
            ),
            types.FunctionDeclaration(
                name="close_window",
                description="Псевдоним закрытия контекста: 'tab' (вкладка), 'window' (окно), 'browser' (процесс).",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"target": {"type": "STRING", "description": "'tab', 'window', 'browser'"}},
                    "required": ["target"]
                }
            ),
            types.FunctionDeclaration(
                name="open_application",
                description="Псевдоним маршрутизатора намерения: запуск приложения, ссылки или ярлыка.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"app_name": {"type": "STRING", "description": "Имя программы или протокол"}},
                    "required": ["app_name"]
                }
            ),
            # Self-Learning Tools
            types.FunctionDeclaration(
                name="learn_rule",
                description="Сохраняет в долговременную память новое правило, привычку или указание от пользователя.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "category": {"type": "STRING", "description": "Категория правила"},
                        "rule": {"type": "STRING", "description": "Формулировка выученного правила"}
                    },
                    "required": ["category", "rule"]
                }
            ),
            types.FunctionDeclaration(
                name="view_memory",
                description="Показывает список всех выученных правил и предпочтений из памяти.",
                behavior="NON_BLOCKING",
                parameters={"type": "OBJECT", "properties": {}}
            ),
            types.FunctionDeclaration(
                name="forget_rule",
                description="Удаляет правило из долговременной памяти по ключевому слову или ID.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"keyword": {"type": "STRING", "description": "Ключевое слово или ID правила для удаления"}},
                    "required": ["keyword"]
                }
            ),
            # Self-Editing Code Tools
            types.FunctionDeclaration(
                name="read_source_file",
                description="Читает содержимое собственного файла исходного кода или конфига.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"filename": {"type": "STRING", "description": "Имя файла в рабочей папке"}},
                    "required": ["filename"]
                }
            ),
            types.FunctionDeclaration(
                name="modify_source_code",
                description="Модифицирует собственный файл кода с проверкой компилятора Python и созданием резервной копии .bak.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "filename": {"type": "STRING", "description": "Имя файла (например jarvis_live.py)"},
                        "target_code": {"type": "STRING", "description": "Существующий фрагмент кода для замены"},
                        "replacement_code": {"type": "STRING", "description": "Новый фрагмент кода"}
                    },
                    "required": ["filename", "target_code", "replacement_code"]
                }
            ),
            types.FunctionDeclaration(
                name="restart_jarvis",
                description="Перезапускает процесс Джарвиса, чтобы применить измененный исходный код или конфиг.",
                behavior="NON_BLOCKING",
                parameters={"type": "OBJECT", "properties": {}}
            ),
            # Git & GitHub Tool
            types.FunctionDeclaration(
                name="manage_git_repo",
                description="Управляет локальным Git-репозиторием и публикацией на GitHub (init, commit, push, create_github_repo).",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "'init', 'status', 'commit', 'push', 'create_github_repo'"},
                        "commit_message": {"type": "STRING", "description": "Сообщение коммита"},
                        "remote_url": {"type": "STRING", "description": "Ссылка на репозиторий GitHub"},
                        "repo_name": {"type": "STRING", "description": "Название нового репозитория на GitHub"},
                        "github_token": {"type": "STRING", "description": "GitHub Personal Access Token"},
                        "is_private": {"type": "BOOLEAN", "description": "Приватный ли репозиторий"}
                    },
                    "required": ["action"]
                }
            )
        ]

        client = genai.Client(api_key=self.api_key)

        connect_config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice_name)
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=types.Content(
                parts=[types.Part(text=get_dynamic_system_prompt())]
            ),
            tools=[types.Tool(function_declarations=tools_decl)]
        )

        while self.is_running:
            try:
                target = "ACTIVE" if self.wake_state == "ACTIVE" else "STANDBY"
                subtext = f"● НА СВЯЗИ ({max(0, int(self.active_until - time.time()))}с)" if self.wake_state == "ACTIVE" else "💤 ЖДУ «ДЖАРВИС»"
                self.avatar.set_state(target, subtext)
                log_event("NET", f"Подключение к WebSocket {self.model}...")
                t_conn = time.time()

                async with client.aio.live.connect(model=self.model, config=connect_config) as session:
                    self.session = session
                    log_event("NET", f"Успешно подключено к Gemini Live за {time.time()-t_conn:.2f}с! Джарвис на связи.")

                    audio_task = asyncio.create_task(self._vad_audio_loop(session), name="AudioVAD")
                    receive_task = asyncio.create_task(self._infinite_receive_loop(session), name="ReceiveLoop")
                    watchdog_task = asyncio.create_task(self._watchdog_loop(), name="Watchdog")
                    vision_task = asyncio.create_task(self._continuous_vision_loop(session), name="VisionLoop")

                    done, pending = await asyncio.wait(
                        [audio_task, receive_task, watchdog_task, vision_task],
                        return_when=asyncio.FIRST_EXCEPTION
                    )
                    for task in pending:
                        task.cancel()
                    for task in done:
                        exc = task.exception()
                        if exc:
                            log_event("ERROR", f"Сбой подсистемы {task.get_name()}: {exc}")

            except Exception as e:
                log_event("NET", f"Соединение завершено: {e}. Быстрое переподключение...")
                self.avatar.set_state("STANDBY", "💤 ЖДУ «ДЖАРВИС»")
                await asyncio.sleep(1.0)

    async def _watchdog_loop(self):
        """Контролирует таймауты зависания и 60-секундный таймер активного диалога."""
        while self.is_running:
            await asyncio.sleep(0.5)
            now = time.time()

            # 1. Защита от зависания обработки
            if self.avatar.state == "THINKING":
                if now - self.turn_sent_time > 6.0:
                    log_event("WATCHDOG", "Таймаут ожидания ответа (6с) -> сброс состояния")
                    target = "ACTIVE" if self.wake_state == "ACTIVE" else "STANDBY"
                    subtext = f"● НА СВЯЗИ ({max(0, int(self.active_until - now))}с)" if self.wake_state == "ACTIVE" else "💤 ЖДУ «ДЖАРВИС»"
                    self.avatar.set_state(target, subtext)

            # 2. Обратный отсчет 60 секунд активного диалога
            if self.wake_state == "ACTIVE":
                remaining = int(self.active_until - now)
                if remaining > 0:
                    if self.avatar.state in ["STANDBY", "ACTIVE"] and not self.is_speaking:
                        self.avatar.set_state("ACTIVE", f"● НА СВЯЗИ ({remaining}с)")
                else:
                    self.wake_state = "STANDBY"
                    log_event("CONV", "Таймаут 60 секунд безмолвия. Джарвис уснул и ждет слова «Джарвис».")
                    self.avatar.set_state("STANDBY", "💤 ЖДУ «ДЖАРВИС»")

    async def _vad_audio_loop(self, session):
        """Patient VAD (1.40s pause tolerance) with echo and overlap suppression."""
        loop = asyncio.get_running_loop()
        audio_q = asyncio.Queue()

        def mic_callback(indata, frames, time_info, status):
            if self.avatar.is_active:
                loop.call_soon_threadsafe(audio_q.put_nowait, indata.copy())

        from google.genai import types

        block_size = 512
        pre_buffer = collections.deque(maxlen=10)
        is_speaking_user = False
        silence_start_time = 0.0
        SILENCE_TIMEOUT = 1.40        # 1.40s calm pause prevents cutting off user mid-thought!
        MIN_SPEECH_DURATION = 0.45    # 450ms minimum speech filters random noise
        ambient_noise = 40.0
        speech_chunks = []

        with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=block_size, callback=mic_callback):
            while self.is_running:
                chunk = await audio_q.get()

                # Echo & Overlap Suppression: don't buffer user turns while Jarvis is speaking
                if self.is_speaking or self.avatar.state in ["SPEAKING", "EXECUTING"]:
                    continue

                audio_samples = chunk[:, 0]
                rms = float(np.sqrt(np.mean(audio_samples.astype(np.float32) ** 2)))

                if not is_speaking_user:
                    ambient_noise = 0.98 * ambient_noise + 0.02 * min(rms, 150.0)

                threshold = max(280.0, ambient_noise * 2.8)
                now = time.time()
                pcm_bytes = chunk.tobytes()

                if rms > threshold:
                    if self.wake_state == "ACTIVE":
                        norm_level = min((rms - threshold) / 1200.0, 1.0)
                        self.avatar.update_voice_level(norm_level)

                    if not is_speaking_user:
                        is_speaking_user = True
                        if self.wake_state == "ACTIVE":
                            self.avatar.set_state("LISTENING")
                        speech_chunks = list(pre_buffer)
                        log_event("VAD", f"Пользователь начал говорить (RMS: {rms:.1f})")

                    speech_chunks.append(pcm_bytes)
                    silence_start_time = now

                else:
                    if self.wake_state == "ACTIVE":
                        self.avatar.update_voice_level(0.0)
                    if is_speaking_user:
                        speech_chunks.append(pcm_bytes)
                        if now - silence_start_time >= SILENCE_TIMEOUT:
                            is_speaking_user = False

                            user_audio_bytes = b"".join(speech_chunks)
                            dur = len(user_audio_bytes) / (16000 * 2)

                            if dur < MIN_SPEECH_DURATION:
                                log_event("VAD", f"Фраза слишком короткая ({dur:.2f}с), фильтр шума.")
                                target = "ACTIVE" if self.wake_state == "ACTIVE" else "STANDBY"
                                remaining = max(0, int(self.active_until - now))
                                subtext = f"● НА СВЯЗИ ({remaining}с)" if self.wake_state == "ACTIVE" else "💤 ЖДУ «ДЖАРВИС»"
                                self.avatar.set_state(target, subtext)
                                continue

                            # --- Wake-Word & Active Conversation Filter ---
                            if self.wake_state == "STANDBY":
                                has_wake, recognized_text = self.wake_detector.check_audio_for_wake_word(user_audio_bytes)
                                if not has_wake:
                                    log_event("VAD", f"Спящий режим: реплика проигнорирована (нет слова «Джарвис»). Общение в Discord/комнате свободно.")
                                    self.avatar.set_state("STANDBY", "💤 ЖДУ «ДЖАРВИС»")
                                    continue
                                else:
                                    log_event("VAD", f"⚡ АКТИВАЦИЯ! Ключевое слово обнаружено в «{recognized_text}». Диалог открыт на 60 секунд.")
                                    self.wake_state = "ACTIVE"
                                    self.active_until = now + self.ACTIVE_DURATION
                            else:
                                # В активном режиме проверяем команду засыпания
                                _, text_lower = self.wake_detector.check_audio_for_wake_word(user_audio_bytes)
                                sleep_triggers = ["отбой", "спать", "хватит", "пока джарвис", "отключись", "засыпай", "замолчи"]
                                if any(st in text_lower for st in sleep_triggers):
                                    log_event("VAD", f"Команда отбоя: «{text_lower}». Джарвис засыпает.")
                                    self.wake_state = "STANDBY"
                                    self.avatar.set_state("STANDBY", "💤 ЖДУ «ДЖАРВИС»")
                                    continue

                                # Продлеваем активный диалог еще на 60 секунд!
                                self.active_until = now + self.ACTIVE_DURATION

                            self.turn_sent_time = now
                            self.avatar.set_state("THINKING", "⏳ ОБРАБОТКА...")
                            log_event("VAD", f"Конец фразы ({dur:.2f}с). Отправка запроса в Gemini...")

                            parts = [
                                types.Part(
                                    inline_data=types.Blob(
                                        data=user_audio_bytes,
                                        mime_type="audio/pcm;rate=16000"
                                    )
                                )
                            ]

                            try:
                                await session.send_client_content(
                                    turns=[types.Content(role="user", parts=parts)],
                                    turn_complete=True
                                )
                            except Exception as e:
                                log_event("ERROR", f"Ошибка отправки хода: {e}")
                    else:
                        pre_buffer.append(pcm_bytes)

    async def _infinite_receive_loop(self, session):
        """Infinite receive loop with instant subtext badges."""
        from google.genai import types

        turn_count = 0
        while self.is_running:
            turn_count += 1
            first_chunk_received = False

            async for message in session.receive():
                server_content = message.server_content
                if server_content:
                    if getattr(server_content, "interrupted", False):
                        log_event("GEMINI", "Перебивание пользователем: сброс аудио")
                        self._clear_playback_queue()
                        target = "ACTIVE" if self.wake_state == "ACTIVE" else "STANDBY"
                        remaining = max(0, int(self.active_until - time.time()))
                        subtext = f"● НА СВЯЗИ ({remaining}с)" if self.wake_state == "ACTIVE" else "💤 ЖДУ «ДЖАРВИС»"
                        self.avatar.set_state(target, subtext)

                    if server_content.model_turn:
                        for part in server_content.model_turn.parts:
                            if part.inline_data:
                                if not first_chunk_received:
                                    first_chunk_received = True
                                    latency = time.time() - self.turn_sent_time
                                    log_event("PERF", f"⚡ ПЕРВЫЙ АУДИОПАКЕТ ЗА {latency*1000:.0f} мс!")
                                self.audio_out_queue.put(part.inline_data.data)

                    if server_content.output_transcription:
                        txt = server_content.output_transcription.text.strip()
                        if txt:
                            log_event("JARVIS", f"Джарвис: «{txt}»")

                    if getattr(server_content, "turn_complete", False):
                        log_event("GEMINI", f"Раунд #{turn_count} завершен сервером.")
                        if self.audio_out_queue.empty() and not self.is_speaking:
                            target = "ACTIVE" if self.wake_state == "ACTIVE" else "STANDBY"
                            remaining = max(0, int(self.active_until - time.time()))
                            subtext = f"● НА СВЯЗИ ({remaining}с)" if self.wake_state == "ACTIVE" else "💤 ЖДУ «ДЖАРВИС»"
                            self.avatar.set_state(target, subtext)

                if message.tool_call:
                    for call in message.tool_call.function_calls:
                        tool_name = call.name
                        tool_args = call.args or {}
                        log_event("TOOL", f"⚡ Вызов инструмента: {tool_name}({tool_args})")

                        subtext = "⚡ ДЕЙСТВИЕ"
                        if "computer" in tool_name or "click" in tool_name:
                            subtext = "🖱️ МЫШЬ / КЛИК"
                        elif "close" in tool_name:
                            subtext = "❌ ЗАКРЫТИЕ"
                        elif "focus" in tool_name:
                            subtext = "🎯 ФОКУС ОКНА"
                        elif "browser" in tool_name or "url" in tool_name:
                            subtext = "⚡ БРАУЗЕР"
                        elif "youtube" in tool_name:
                            subtext = "⚡ YOUTUBE"
                        elif "davinci" in tool_name:
                            subtext = "⚡ ДАВИНЧИ"
                        elif "screen" in tool_name or "vision" in tool_name:
                            subtext = "◈ СКАН ЭКРАНА"
                        elif "search" in tool_name:
                            subtext = "⚡ ПОИСК"
                        elif "app" in tool_name:
                            subtext = "🚀 ЗАПУСК"
                        elif "learn" in tool_name or "memory" in tool_name:
                            subtext = "🧠 ОБУЧЕНИЕ"
                        elif "modify" in tool_name or "read_source" in tool_name:
                            subtext = "🛠️ РЕДАКТ. КОДА"
                        elif "git" in tool_name or "github" in tool_name:
                            subtext = "🐙 GITHUB"

                        self.avatar.set_state("EXECUTING" if "screen" not in tool_name else "VISION", subtext)

                        loop = asyncio.get_running_loop()
                        result_str = await loop.run_in_executor(None, execute_tool, tool_name, tool_args, self)

                        resp = types.FunctionResponse(
                            id=call.id,
                            name=call.name,
                            response={"result": result_str}
                        )
                        await session.send_tool_response(function_responses=[resp])


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    avatar = ArcReactorWidget()
    avatar.show()

    tray = QSystemTrayIcon(QIcon(str(ICON_PATH)), app)
    tray_menu = QMenu()
    tray_menu.addAction("👀 Непрерывное зрение (1280x720)", avatar.toggle_vision)
    tray_menu.addAction("📄 Открыть логи", avatar.open_log_file)
    tray_menu.addAction("🧠 База памяти", avatar.open_memory_file)
    tray_menu.addAction("🐙 Статус Git", avatar.show_git_status)
    tray_menu.addAction("⚙️ Настройки ключа", avatar.change_api_key)
    tray_menu.addSeparator()
    tray_menu.addAction("❌ Выход", app.quit)
    tray.setContextMenu(tray_menu)
    tray.show()

    if not CONFIG.get("gemini_api_key"):
        avatar.change_api_key()

    engine = GeminiLiveEngine(avatar)
    engine.start()

    log_event("INIT", "J.A.R.V.I.S. запущен (Claude Computer Use Edition) и ожидает команд.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
