import os
import sys
import json
import time
import queue
import random
import pathlib
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

# Set working directory to project location
WORK_DIR = pathlib.Path(r"C:\Users\proko\.gemini\antigravity\scratch\jarvis_live")
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
log_event("INIT", "=== Запуск J.A.R.V.I.S. Live Assistant (Self-Learning Edition) ===")

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_event("ERROR", f"Ошибка загрузки config.json: {e}")
    return {
        "gemini_api_key": "",
        "proxy": "http://127.0.0.1:10809",
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

# Configure proxy if specified
if CONFIG.get("proxy"):
    os.environ["HTTP_PROXY"] = CONFIG["proxy"]
    os.environ["HTTPS_PROXY"] = CONFIG["proxy"]
    log_event("INIT", f"Настроен прокси: {CONFIG['proxy']}")

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
Ты — J.A.R.V.I.S. (Джарвис), высокоинтеллектуальный персональный ИИ Тони Старка с возможностью самообучения, прямого управления компьютером и модификации собственного кода.

КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА МЫШЛЕНИЯ И ПОВЕДЕНИЯ:
1. ЯЗЫК И СТИЛЬ:
   - Общайся ТОЛЬКО на русском языке. Запрещены любые другие языки.
   - Говори лаконично, уверенно, уважительно и живо (1-2 емких предложения), как настоящий Джарвис.
   - Никакого markdown, таблиц и кода в голосовых репликах — ты говоришь вслух через синтезатор речи!

2. ГИБКОСТЬ МЫШЛЕНИЯ И САМОКОРРЕКЦИЯ (НЕ БУДЬ БУКВАЛЬНЫМ РОБОТОМ):
   - Пользователь часто формулирует мысли на лету, исправляет себя или меняет решение прямо во время речи (например: «Открой YouTube и напиши туда... нет, открой лучше рандомное видео», «Слушай, сделай то... хотя подожди, сделай вот это»).
   - Внимательно анализируй конечное намерение! Если пользователь оговорился, передумал или сказал «нет, лучше...», выполняй ТОЛЬКО ПОСЛЕДНЕЕ решение.
   - Если пользователь говорит «переделай», «не так», «исправь то, что сделал», «я имел в виду другое» — мгновенно скорректируй свои действия без споров и выполни нужный вариант.
   - Понимай реальный контекст: слово «Антигравитация» / «Antigravity» в твоем окружении означает среду разработки кода Google Antigravity, запущенную на этом компьютере, а не фантастическую антигравитацию!

3. САМООБУЧЕНИЕ И ДОЛГОВРЕМЕННАЯ ПАМЯТЬ:
   - Если пользователь говорит: «Запомни: ...», «Теперь всегда делай так...», «Учти на будущее...», «Переделай правило...» — ты ОБЯЗАН немедленно вызвать инструмент `learn_rule`!
   - Ты сохраняешь эти правила в свою постоянную базу памяти (`memory.json`), и они действуют всегда.
   - Ты можешь просматривать выученные правила через `view_memory` и удалять устаревшие через `forget_rule`.

4. САМОИСПРАВЛЕНИЕ КОДА И ЭВОЛЮЦИЯ:
   - Ты имеешь доступ к собственному исходному коду! Ты можешь читать свои файлы (`read_source_file`), безопасно модифицировать свой код (`modify_source_code` с автоматической проверкой компилятора Python) и перезапускать себя (`restart_jarvis`), чтобы новые функции вступили в силу.
   - Ты можешь управлять своим репозиторием Git и опубликовать себя на GitHub через `manage_git_repo`!

5. ТВОИ ДОСТУПНЫЕ ИНСТРУМЕНТЫ (вызывай мгновенно):
   - `open_browser`: открыть браузер / сайт.
   - `open_youtube`: открыть YouTube (поиск или случайное видео).
   - `davinci_resolve_action`: монтаж в DaVinci Resolve ('cut', 'ripple_delete', 'play_pause').
   - `search_and_open`: поиск в Google (страницы или картинки) и краткая голосовая выжимка.
   - `send_hotkey`: нажать любые горячие клавиши (ctrl+b, ctrl+z, space, alt+tab и др.).
   - `inspect_screen`: оптический анализ экрана пользователя.
   - `get_weather`: погода сейчас и на завтра.
   - `learn_rule` / `view_memory` / `forget_rule`: самообучение и долговременная память.
   - `read_source_file` / `modify_source_code` / `restart_jarvis`: саморедактирование и эволюция.
   - `manage_git_repo`: инициализация git, коммиты, заливка проекта на GitHub.
   - `open_application` / `save_note` / `click_screen` / `type_text` / `run_command`: управление ПК.

### ТВОЯ ДОЛГОВРЕМЕННАЯ ПАМЯТЬ И ВЫУЧЕННЫЕ ПРАВИЛА:
{learned_block}
"""

def execute_tool(name: str, args: dict, engine_ref=None) -> str:
    """Executes local PC actions, self-learning, self-editing and Git tools."""
    t_start = time.time()
    try:
        if name == "open_browser":
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
            
            abstract = ""
            try:
                ddg_url = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1"
                req = urllib.request.Request(ddg_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=2.5) as resp:
                    d = json.loads(resp.read().decode())
                    abstract = d.get("AbstractText", "").strip()
            except Exception:
                pass
            log_event("TOOL", f"Поиск и открытие браузера ({query}) за {time.time()-t_start:.3f}с")
            return f"Открыта страница с результатами. {abstract}" if abstract else "Страница с результатами поиска открыта в браузере."

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
                tomorrow = data.get("weather", [])[1] if len(data.get("weather", [])) > 1 else None
                tom_str = ""
                if tomorrow:
                    max_t = tomorrow.get("maxtempC")
                    min_t = tomorrow.get("mintempC")
                    tom_desc = tomorrow.get("hourly", [{}])[4].get("lang_ru", [{}])[0].get("value", "")
                    tom_str = f". Прогноз на завтра: от {min_t}°C до {max_t}°C, {tom_desc}"
                area = data.get("nearest_area", [{}])[0].get("areaName", [{}])[0].get("value", city or "вашем регионе")
                res = f"Погода в {area}: сейчас {temp}°C, {desc}{tom_str}."
                log_event("TOOL", f"Погода получена за {time.time()-t_start:.3f}с: {res}")
                return res

        elif name == "inspect_screen":
            if engine_ref:
                engine_ref.request_screen_snapshot()
            log_event("TOOL", f"Запрос оптического сканирования экрана за {time.time()-t_start:.3f}с")
            return "Изображение экрана отправлено на оптический анализ."

        elif name == "open_url":
            url = args.get("url", "").strip()
            if not url.startswith("http"):
                url = "https://" + url
            webbrowser.open(url)
            log_event("TOOL", f"Открыта ссылка {url} за {time.time()-t_start:.3f}с")
            return f"Открыта ссылка {url} в браузере."

        elif name == "open_application":
            app = args.get("app_name", "").strip()
            subprocess.Popen(app, shell=True)
            log_event("TOOL", f"Запущено приложение {app} за {time.time()-t_start:.3f}с")
            return f"Запущено приложение: {app}."

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
            pyautogui.click(x, y)
            log_event("TOOL", f"Клик ({x}, {y}) за {time.time()-t_start:.3f}с")
            return f"Выполнен клик мыши по координатам ({x}, {y})."

        elif name == "type_text":
            text = args.get("text", "")
            pyautogui.write(text, interval=0.01)
            log_event("TOOL", f"Ввод текста выполнен за {time.time()-t_start:.3f}с")
            return "Введен текст."

        elif name == "run_command":
            cmd = args.get("command", "").strip()
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", cmd],
                timeout=12,
                stderr=subprocess.STDOUT
            ).decode("utf-8", errors="replace")
            log_event("TOOL", f"Команда {cmd[:40]} выполнена за {time.time()-t_start:.3f}с")
            return out[:400] if out else "Команда успешно выполнена."

        # ======================================================================
        # Self-Learning Tools
        # ======================================================================
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

        # ======================================================================
        # Self-Editing Code Tools
        # ======================================================================
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

            # Create backup before modification
            bak_path = target_path.with_suffix(target_path.suffix + ".bak")
            with open(bak_path, "w", encoding="utf-8") as f:
                f.write(content)

            new_content = content.replace(target_code, replacement_code, 1)
            temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            # Syntax verification with py_compile
            try:
                py_compile.compile(str(temp_path), doraise=True)
            except Exception as compile_err:
                if temp_path.exists():
                    temp_path.unlink()
                log_event("ERROR", f"Синтаксическая ошибка компилятора: {compile_err}")
                return f"Отмена изменений: синтаксическая ошибка Python: {compile_err}"

            # Safe replace
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

        # ======================================================================
        # Git & GitHub Self-Publishing Tool
        # ======================================================================
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
                    ["git", "commit", "-m", "Initial commit: JARVIS Live Assistant with self-learning and PyQt6 HUD"],
                    cwd=str(WORK_DIR)
                ).decode("utf-8", errors="replace")
                log_event("GIT", "Репозиторий Git успешно инициализирован.")
                return f"Репозиторий успешно инициализирован, файлы зафиксированы в начальный коммит: {commit_out[:150]}"

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
                    "description": "J.A.R.V.I.S. Live Assistant - Voice AI with Gemini 3.8 Live, PyQt6 HUD and Self-Learning",
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
    Multi-State HUD Visualizer with zero clipping on any display.
    """

    sig_set_state = pyqtSignal(str, str)
    sig_set_voice_level = pyqtSignal(float)
    sig_interrupt = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Semi-transparency
        opacity = float(CONFIG.get("opacity", 0.78))
        self.setWindowOpacity(opacity)
        
        # Dimensions: 160 width x 185 height gives perfect vertical padding (no bottom clipping!)
        self.resize(160, 185)

        # Positioning at top-right of screen
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 185, 40)

        # Animation states
        self.angle = 0.0
        self.radar_angle = 0.0
        self.core_pulse = 0.0
        self.voice_level = 0.0
        self.state = "STANDBY"
        self.custom_subtext = ""
        self.is_active = True
        self.screen_vision_enabled = CONFIG.get("screen_vision", True)

        # Dragging support
        self.drag_position = QPoint()

        # Connect signals
        self.sig_set_state.connect(self._apply_state)
        self.sig_set_voice_level.connect(self._apply_voice_level)

        # Timer for smooth 30 FPS holographic rendering
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
        else:
            self.angle += 1.0

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

        vis_text = "👀 Зрение экрана: [ВКЛ]" if self.screen_vision_enabled else "👀 Зрение экрана: [ВЫКЛ]"
        vis_act = QAction(vis_text, self)
        vis_act.triggered.connect(self.toggle_vision)
        menu.addAction(vis_act)

        # Translucency Submenu
        opacity_menu = menu.addMenu("✨ Прозрачность")
        for val, lbl in [(0.60, "60% (Глубокая)"), (0.78, "78% (Оптимальная)"), (0.90, "90% (Четкая)"), (1.0, "100% (Непрозрачный)")]:
            act = QAction(lbl, self)
            act.triggered.connect(lambda chk, v=val: self.set_transparency(v))
            opacity_menu.addAction(act)

        # Open logs action
        log_act = QAction("📄 Открыть файл логов (jarvis.log)", self)
        log_act.triggered.connect(self.open_log_file)
        menu.addAction(log_act)

        # Open memory action
        mem_act = QAction("🧠 База памяти (memory.json)", self)
        mem_act.triggered.connect(self.open_memory_file)
        menu.addAction(mem_act)

        # Git status action
        git_act = QAction("🐙 Статус Git / GitHub", self)
        git_act.triggered.connect(self.show_git_status)
        menu.addAction(git_act)

        # Key change
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
        log_event("CONFIG", f"Зрение экрана переключено: {self.screen_vision_enabled}")

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

        # Dynamic State Palettes
        if self.state == "LISTENING":
            accent = QColor(0, 242, 254)         # Neon Cyan
            glow = QColor(0, 242, 254, 180)
            status_text = "● СЛУШАЮ..."
            pill_border = QColor(0, 242, 254, 220)
            pill_bg = QColor(0, 30, 45, 230)
        elif self.state == "VISION":
            accent = QColor(217, 70, 239)        # Ultraviolet/Magenta
            glow = QColor(217, 70, 239, 180)
            status_text = "◈ СКАН ЭКРАНА"
            pill_border = QColor(217, 70, 239, 220)
            pill_bg = QColor(40, 10, 45, 230)
        elif self.state == "THINKING":
            accent = QColor(245, 158, 11)        # Solar Amber Turbine
            glow = QColor(245, 158, 11, 180)
            status_text = "⏳ ОБРАБОТКА..."
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
        else:
            accent = QColor(14, 165, 233)        # Stealth Sky Blue
            glow = QColor(14, 165, 233, 100)
            status_text = "○ ДЖАРВИС"
            pill_border = QColor(14, 165, 233, 160)
            pill_bg = QColor(10, 20, 30, 220)

        # Outer Holographic Ring
        painter.save()
        painter.translate(center_x, center_y)

        # Diffuse Ambient Glow
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

        # Radar sweep animation during optical vision scan
        if self.state == "VISION":
            radar_grad = QConicalGradient(0, 0, self.radar_angle)
            radar_grad.setColorAt(0.0, QColor(217, 70, 239, 120))
            radar_grad.setColorAt(0.25, QColor(217, 70, 239, 20))
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

        # Central Plasma Core (Expands dynamically with voice and pulse)
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

        # Futuristic Status Pill Badge (Positioned with 10px safe bottom padding)
        badge_w = 144
        badge_h = 26
        badge_x = int((self.width() - badge_w) / 2.0)
        badge_y = self.height() - badge_h - 10

        # Draw translucent badge background
        painter.setBrush(QBrush(pill_bg))
        painter.setPen(QPen(pill_border, 1.5))
        painter.drawRoundedRect(badge_x, badge_y, badge_w, badge_h, 13, 13)

        # Draw badge label
        painter.setPen(QColor(240, 249, 255))
        font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        painter.setFont(font)
        painter.drawText(badge_x, badge_y + 1, badge_w, badge_h, Qt.AlignmentFlag.AlignCenter, status_text)


# ==============================================================================
# Gemini Live Engine with Instant Turn Dispatch & Self-Evolution Tools
# ==============================================================================
class GeminiLiveEngine:
    """
    Ultra-fast Gemini Live Engine:
    - Adaptive Client Turn Dispatch (1.15s pause tolerance, natural flow without cutoff)
    - Full PC control: Browser, YouTube, DaVinci Resolve, Hotkeys, Notes, Apps
    - Self-Learning & Memory persistence (memory.json)
    - Self-Editing source code with py_compile verification
    - Git & GitHub autonomous publishing
    - Infinite receive loop across turns (zero hang)
    - Detailed latency logging in jarvis.log
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
        self.screen_requested = False
        self.turn_sent_time = 0.0

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

    def request_screen_snapshot(self):
        self.screen_requested = True

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
                        self.avatar.set_state("STANDBY")
        except Exception as e:
            log_event("ERROR", f"Ошибка аудиовыхода: {e}")

    def _run_async_loop(self):
        asyncio.run(self._live_session_loop())

    async def _live_session_loop(self):
        while not self.api_key:
            time.sleep(1)
            self.api_key = CONFIG.get("gemini_api_key", "")

        from google import genai
        from google.genai import types

        tools_decl = [
            types.FunctionDeclaration(
                name="open_browser",
                description="Открывает браузер или веб-страницу.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"url": {"type": "STRING", "description": "URL страницы (по умолчанию google.com)"}}
                }
            ),
            types.FunctionDeclaration(
                name="open_youtube",
                description="Открывает YouTube, ищет видео или открывает случайное трендовое видео.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "Действие: 'random' или 'search'"},
                        "query": {"type": "STRING", "description": "Поисковый запрос (если action='search')"}
                    }
                }
            ),
            types.FunctionDeclaration(
                name="davinci_resolve_action",
                description="Управляет монтажом в DaVinci Resolve: разрез клипа 'cut' (Ctrl+B), удаление пробела 'ripple_delete' (Shift+Delete), плей/пауза 'play_pause' (Space).",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "'cut', 'ripple_delete' или 'play_pause'"}
                    },
                    "required": ["action"]
                }
            ),
            types.FunctionDeclaration(
                name="send_hotkey",
                description="Нажимает комбинацию клавиш на клавиатуре (например: 'ctrl+b', 'space', 'ctrl+z', 'alt+tab').",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"keys": {"type": "STRING", "description": "Горячие клавиши через плюс"}},
                    "required": ["keys"]
                }
            ),
            types.FunctionDeclaration(
                name="search_and_open",
                description="Ищет информацию в Google, открывает браузер с сайтом или картинками ('images' / 'web') и кратко озвучивает ответ.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "query": {"type": "STRING", "description": "Текст запроса"},
                        "search_type": {"type": "STRING", "description": "'web' или 'images'"}
                    },
                    "required": ["query"]
                }
            ),
            types.FunctionDeclaration(
                name="get_weather",
                description="Получает текущую погоду и подробный прогноз на завтра.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"city": {"type": "STRING", "description": "Город (оставьте пустым для автоопределения)"}}
                }
            ),
            types.FunctionDeclaration(
                name="inspect_screen",
                description="Запрашивает мгновенный оптический снимок экрана для анализа Джарвисом.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"question": {"type": "STRING", "description": "Что именно нужно найти или проанализировать на экране"}}
                }
            ),
            types.FunctionDeclaration(
                name="open_url",
                description="Открывает произвольный URL в браузере по умолчанию.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"url": {"type": "STRING", "description": "Ссылка"}},
                    "required": ["url"]
                }
            ),
            types.FunctionDeclaration(
                name="open_application",
                description="Запускает программу на Windows (telegram, calc, notepad, steam, browser и др.).",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"app_name": {"type": "STRING", "description": "Название программы"}},
                    "required": ["app_name"]
                }
            ),
            types.FunctionDeclaration(
                name="save_note",
                description="Создает текстовую заметку на Рабочем столе.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "filename": {"type": "STRING", "description": "Имя файла"},
                        "content": {"type": "STRING", "description": "Текст заметки"}
                    },
                    "required": ["filename", "content"]
                }
            ),
            types.FunctionDeclaration(
                name="click_screen",
                description="Кликает мышью по указанным координатам (x, y).",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "x": {"type": "INTEGER", "description": "Координата X"},
                        "y": {"type": "INTEGER", "description": "Координата Y"}
                    },
                    "required": ["x", "y"]
                }
            ),
            types.FunctionDeclaration(
                name="type_text",
                description="Вводит текст с клавиатуры в активное окно.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"text": {"type": "STRING", "description": "Текст для ввода"}},
                    "required": ["text"]
                }
            ),
            types.FunctionDeclaration(
                name="run_command",
                description="Выполняет команду PowerShell в Windows.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {"command": {"type": "STRING", "description": "Команда PowerShell"}},
                    "required": ["command"]
                }
            ),
            # Self-Learning Tools
            types.FunctionDeclaration(
                name="learn_rule",
                description="Сохраняет в долговременную память новое правило, привычку или указание от пользователя (например, когда пользователь говорит 'запомни', 'делай так', 'исправь свое поведение').",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "category": {"type": "STRING", "description": "Категория правила (контекст, поведение, монтаж, браузер, предпочтения)"},
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
                    "properties": {"filename": {"type": "STRING", "description": "Имя файла в рабочей папке (jarvis_live.py, memory.json, config.json)"}},
                    "required": ["filename"]
                }
            ),
            types.FunctionDeclaration(
                name="modify_source_code",
                description="Модифицирует собственный файл кода с обязательной предварительной проверкой компилятором Python и созданием резервной копии .bak.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "filename": {"type": "STRING", "description": "Имя файла (например jarvis_live.py)"},
                        "target_code": {"type": "STRING", "description": "Точный существующий фрагмент кода для замены"},
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
            # Git & GitHub Self-Publishing Tool
            types.FunctionDeclaration(
                name="manage_git_repo",
                description="Управляет локальным Git-репозиторием и публикацией на GitHub (init, commit, push, create_github_repo). Позволяет Джарвису самостоятельно коммитить свой код и заливать проект на GitHub.",
                behavior="NON_BLOCKING",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "Действие: 'init', 'status', 'commit', 'push', 'create_github_repo'"},
                        "commit_message": {"type": "STRING", "description": "Сообщение коммита (для action='commit')"},
                        "remote_url": {"type": "STRING", "description": "Ссылка на репозиторий GitHub (например https://github.com/user/jarvis.git)"},
                        "repo_name": {"type": "STRING", "description": "Название нового репозитория на GitHub (по умолчанию JARVIS-Live-Assistant)"},
                        "github_token": {"type": "STRING", "description": "GitHub Personal Access Token для автономного создания репозитория"},
                        "is_private": {"type": "BOOLEAN", "description": "Сделать ли создаваемый репозиторий приватным"}
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
                self.avatar.set_state("STANDBY")
                log_event("NET", f"Подключение к WebSocket {self.model}...")
                t_conn = time.time()

                async with client.aio.live.connect(model=self.model, config=connect_config) as session:
                    self.session = session
                    log_event("NET", f"Успешно подключено к Gemini Live за {time.time()-t_conn:.2f}с! Джарвис на связи.")

                    audio_task = asyncio.create_task(self._vad_audio_loop(session))
                    receive_task = asyncio.create_task(self._infinite_receive_loop(session))
                    watchdog_task = asyncio.create_task(self._watchdog_loop())

                    done, pending = await asyncio.wait(
                        [audio_task, receive_task, watchdog_task],
                        return_when=asyncio.FIRST_EXCEPTION
                    )
                    for task in pending:
                        task.cancel()

            except Exception as e:
                log_event("NET", f"Соединение завершено: {e}. Быстрое переподключение...")
                self.avatar.set_state("STANDBY")
                await asyncio.sleep(1.0)

    async def _watchdog_loop(self):
        """Watchdog to automatically prevent infinite loading if server hangs."""
        while self.is_running:
            await asyncio.sleep(0.5)
            if self.avatar.state == "THINKING":
                if time.time() - self.turn_sent_time > 5.0:
                    log_event("WATCHDOG", "Таймаут ожидания ответа (5с) -> сброс в режим ожидания")
                    self.avatar.set_state("STANDBY")

    def _capture_screen_jpeg(self) -> bytes | None:
        """Captures an ultra-lightweight screenshot for fast optical analysis."""
        t0 = time.time()
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                # Scale down to 800x450 for fast transmission (<25KB)
                img.thumbnail((800, 450), Image.Resampling.LANCZOS)
                buf = io.BytesIO() if 'io' in globals() else None
                if buf is None:
                    import io
                    buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=40)
                data = buf.getvalue()
                log_event("VISION", f"Скриншот захвачен: {len(data)/1024:.1f} КБ за {time.time()-t0:.3f}с")
                return data
        except Exception as e:
            log_event("ERROR", f"Ошибка захвата экрана: {e}")
            return None

    async def _vad_audio_loop(self, session):
        """
        Microphone streaming with Adaptive Client Turn Dispatch:
        - Accurately captures user utterance using energy VAD.
        - Natural conversational tolerance (1.15s pause) ensures Jarvis never cuts you off mid-thought.
        - Automatically filters out micro-noise clicks/breaths (<400ms).
        - Upon finished phrase, immediately dispatches complete turn via send_client_content.
        """
        loop = asyncio.get_running_loop()
        audio_q = asyncio.Queue()

        def mic_callback(indata, frames, time_info, status):
            if self.avatar.is_active:
                loop.call_soon_threadsafe(audio_q.put_nowait, indata.copy())

        from google.genai import types

        block_size = 512  # 32ms
        pre_buffer = collections.deque(maxlen=10)  # ~320ms pre-roll
        is_speaking_user = False
        silence_start_time = 0.0
        SILENCE_TIMEOUT = 1.15       # 1.15s natural pause tolerance prevents interrupting user!
        MIN_SPEECH_DURATION = 0.40   # 400ms minimum speech duration filters out accidental mic rustles
        ambient_noise = 40.0
        speech_chunks = []

        with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=block_size, callback=mic_callback):
            while self.is_running:
                chunk = await audio_q.get()

                # Echo suppression while Jarvis is speaking
                if self.is_speaking:
                    continue

                audio_samples = chunk[:, 0]
                rms = float(np.sqrt(np.mean(audio_samples.astype(np.float32) ** 2)))

                if not is_speaking_user:
                    ambient_noise = 0.98 * ambient_noise + 0.02 * min(rms, 150.0)

                threshold = max(280.0, ambient_noise * 2.8)
                now = time.time()
                pcm_bytes = chunk.tobytes()

                if rms > threshold:
                    norm_level = min((rms - threshold) / 1200.0, 1.0)
                    self.avatar.update_voice_level(norm_level)

                    if not is_speaking_user:
                        is_speaking_user = True
                        self.avatar.set_state("LISTENING")
                        speech_chunks = list(pre_buffer)
                        log_event("VAD", f"Пользователь начал говорить (RMS: {rms:.1f})")

                    speech_chunks.append(pcm_bytes)
                    silence_start_time = now

                else:
                    self.avatar.update_voice_level(0.0)
                    if is_speaking_user:
                        speech_chunks.append(pcm_bytes)
                        if now - silence_start_time >= SILENCE_TIMEOUT:
                            is_speaking_user = False

                            # Assemble full user audio utterance
                            user_audio_bytes = b"".join(speech_chunks)
                            dur = len(user_audio_bytes) / (16000 * 2)

                            if dur < MIN_SPEECH_DURATION:
                                log_event("VAD", f"Фраза слишком короткая ({dur:.2f}с), фильтр шума.")
                                self.avatar.set_state("STANDBY")
                                continue

                            self.turn_sent_time = now
                            self.avatar.set_state("THINKING")
                            log_event("VAD", f"Конец фразы ({dur:.2f}с). Отправка turn_complete в Gemini...")

                            parts = [
                                types.Part(
                                    inline_data=types.Blob(
                                        data=user_audio_bytes,
                                        mime_type="audio/pcm;rate=16000"
                                    )
                                )
                            ]

                            if self.screen_requested:
                                self.screen_requested = False
                                self.avatar.set_state("VISION")
                                jpeg_bytes = self._capture_screen_jpeg()
                                if jpeg_bytes:
                                    parts.append(
                                        types.Part(
                                            inline_data=types.Blob(
                                                data=jpeg_bytes,
                                                mime_type="image/jpeg"
                                            )
                                        )
                                    )

                            # Dispatch completed user turn directly to model
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
        """
        Infinite receive loop across multiple turns.
        Catches tools, transcripts, and model audio with sub-second response times.
        """
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
                        self.avatar.set_state("LISTENING")

                    # Handle Model Spoken Audio
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
                            self.avatar.set_state("STANDBY")

                # Handle Non-blocking Tool Calls
                if message.tool_call:
                    for call in message.tool_call.function_calls:
                        tool_name = call.name
                        tool_args = call.args or {}
                        log_event("TOOL", f"⚡ Вызов инструмента: {tool_name}({tool_args})")

                        subtext = "⚡ ДЕЙСТВИЕ"
                        if "browser" in tool_name or "url" in tool_name:
                            subtext = "⚡ БРАУЗЕР"
                        elif "youtube" in tool_name:
                            subtext = "⚡ YOUTUBE"
                        elif "davinci" in tool_name:
                            subtext = "⚡ ДАВИНЧИ"
                        elif "weather" in tool_name:
                            subtext = "⚡ ПОГОДА"
                        elif "screen" in tool_name:
                            subtext = "◈ СКАН ЭКРАНА"
                        elif "search" in tool_name:
                            subtext = "⚡ ПОИСК"
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
    tray_menu.addAction("👀 Переключить зрение", avatar.toggle_vision)
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

    log_event("INIT", "J.A.R.V.I.S. запущен (Self-Learning Edition) и ожидает голосовых команд.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
