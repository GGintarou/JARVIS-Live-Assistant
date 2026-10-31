import sys
import os
import pathlib

# Ensure virtualenv site-packages are loaded
WORK_DIR = pathlib.Path(__file__).resolve().parent
venv_site = WORK_DIR / ".venv" / "Lib" / "site-packages"
if venv_site.exists() and str(venv_site) not in sys.path:
    sys.path.insert(0, str(venv_site))

import time
import dataclasses
from typing import Type, TypeVar, Optional, Set, Dict, List
import ctypes
from ctypes import wintypes
import psutil
import pyautogui

user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

pyautogui.FAILSAFE = False
PHYSICAL_W, PHYSICAL_H = pyautogui.size()
CAPTURE_W, CAPTURE_H = 1280, 720

# ==============================================================================
# Abstract Components (Pure Data, No Hardcoded Object Logic)
# ==============================================================================

@dataclasses.dataclass
class Component:
    pass

@dataclasses.dataclass
class SpatialComponent(Component):
    x: float = 0.0  # normalized 0.0 .. 1.0 or pixel
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    z_index: int = 0
    display_index: int = 0

    def to_physical(self, screen_w: int = PHYSICAL_W, screen_h: int = PHYSICAL_H) -> tuple[int, int]:
        # If normalized
        if 0.0 <= self.x <= 1.0 and 0.0 <= self.y <= 1.0:
            return int(round(self.x * screen_w)), int(round(self.y * screen_h))
        # If in 1280x720 vision space
        if 0 <= self.x <= CAPTURE_W and 0 <= self.y <= CAPTURE_H:
            return int(round(self.x * (screen_w / float(CAPTURE_W)))), int(round(self.y * (screen_h / float(CAPTURE_H))))
        return int(round(self.x)), int(round(self.y))

@dataclasses.dataclass
class VisualComponent(Component):
    label: str = ""
    role: str = "generic"  # glyph, text_block, canvas, surface, control
    visible: bool = True

@dataclasses.dataclass
class SurfaceComponent(Component):
    hwnd: int = 0
    title: str = ""
    is_foreground: bool = False
    is_minimized: bool = False
    is_maximized: bool = False
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)

@dataclasses.dataclass
class ProcessComponent(Component):
    pid: int = 0
    name: str = ""
    binary_path: str = ""
    alive: bool = True

@dataclasses.dataclass
class AffordanceComponent(Component):
    can_actuate: bool = True   # Click / trigger
    can_input: bool = False    # Key text stream
    can_dismiss: bool = True   # Close / escape / terminate
    can_focus: bool = True     # Bring to foreground
    can_scroll: bool = False   # Scroll viewport

@dataclasses.dataclass
class SemanticComponent(Component):
    intent_affinity: str = "general"
    tags: Set[str] = dataclasses.field(default_factory=set)
    salience: float = 1.0

@dataclasses.dataclass
class MemoryComponent(Component):
    created_at: float = dataclasses.field(default_factory=time.time)
    last_perceived_at: float = dataclasses.field(default_factory=time.time)
    interaction_count: int = 0

T = TypeVar('T', bound=Component)

# ==============================================================================
# World State / Entity Manager
# ==============================================================================

class EntityManager:
    def __init__(self):
        self._next_id = 100
        self._entities: Dict[str, Dict[Type[Component], Component]] = {}

    def create_entity(self, *components: Component, entity_id: Optional[str] = None) -> str:
        if not entity_id:
            entity_id = f"ent_{self._next_id}"
            self._next_id += 1
        self._entities[entity_id] = {}
        for c in components:
            self._entities[entity_id][type(c)] = c
        return entity_id

    def add_component(self, entity_id: str, component: Component):
        if entity_id in self._entities:
            self._entities[entity_id][type(component)] = component

    def get_component(self, entity_id: str, component_type: Type[T]) -> Optional[T]:
        ent = self._entities.get(entity_id)
        if ent:
            return ent.get(component_type)
        return None

    def has_component(self, entity_id: str, component_type: Type[Component]) -> bool:
        ent = self._entities.get(entity_id)
        return bool(ent and component_type in ent)

    def find_entities(self, *required_components: Type[Component]) -> List[str]:
        results = []
        for eid, comps in self._entities.items():
            if all(rc in comps for rc in required_components):
                results.append(eid)
        return results

    def remove_entity(self, entity_id: str):
        self._entities.pop(entity_id, None)

    def clear(self):
        self._entities.clear()

    def all_entities(self) -> Dict[str, Dict[Type[Component], Component]]:
        return self._entities

# ==============================================================================
# Systems: Perception & Actuation
# ==============================================================================

class PerceptionSystem:
    def __init__(self, em: EntityManager):
        self.em = em

    def synchronize_surfaces(self) -> List[str]:
        """
        Discovers all visible OS surfaces (windows) and processes via pure Win32 API.
        Creates/updates Entities with Surface, Process, Spatial, and Affordance components.
        Zero hardcoded object names.
        """
        # Clear previous ephemeral surface entities
        for eid in self.em.find_entities(SurfaceComponent):
            self.em.remove_entity(eid)

        fg_hwnd = user32.GetForegroundWindow()
        discovered = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, _):
            if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()

                    # Filter out system utility windows or empty titles
                    if title and title not in ["Program Manager", "MSCTFIME UI", "Default IME"]:
                        pid = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        proc_name = ""
                        try:
                            proc = psutil.Process(pid.value)
                            proc_name = proc.name()
                        except Exception:
                            pass

                        rect = wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top

                        is_fg = (hwnd == fg_hwnd)

                        eid = f"surface_{hwnd}"
                        self.em.create_entity(
                            SurfaceComponent(
                                hwnd=hwnd,
                                title=title,
                                is_foreground=is_fg,
                                rect=(rect.left, rect.top, w, h)
                            ),
                            ProcessComponent(
                                pid=pid.value,
                                name=proc_name
                            ),
                            SpatialComponent(
                                x=float(rect.left),
                                y=float(rect.top),
                                w=float(w),
                                h=float(h)
                            ),
                            VisualComponent(
                                label=title,
                                role="surface"
                            ),
                            AffordanceComponent(
                                can_actuate=True,
                                can_input=True,
                                can_dismiss=True,
                                can_focus=True,
                                can_scroll=True
                            ),
                            SemanticComponent(
                                intent_affinity="workspace_surface",
                                tags={proc_name.lower().replace(".exe", "")} if proc_name else set()
                            ),
                            entity_id=eid
                        )
                        discovered.append(eid)
            return True

        cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_cb)
        user32.EnumWindows(cb, 0)
        return discovered

    def get_foreground_entity(self) -> Optional[str]:
        self.synchronize_surfaces()
        for eid in self.em.find_entities(SurfaceComponent):
            surf = self.em.get_component(eid, SurfaceComponent)
            if surf and surf.is_foreground:
                return eid
        return None

    def query_entities_summary(self) -> List[dict]:
        """Summarizes all known entities and their component states for the cognitive model."""
        self.synchronize_surfaces()
        summary = []
        for eid, comps in self.em.all_entities().items():
            item = {"entity_id": eid}
            surf = comps.get(SurfaceComponent)
            proc = comps.get(ProcessComponent)
            vis = comps.get(VisualComponent)
            spat = comps.get(SpatialComponent)
            aff = comps.get(AffordanceComponent)
            sem = comps.get(SemanticComponent)

            if surf:
                item["surface_title"] = surf.title
                item["is_active"] = surf.is_foreground
            if proc:
                item["process"] = proc.name
                item["pid"] = proc.pid
            if vis:
                item["label"] = vis.label
            if spat:
                item["bounds"] = (int(spat.x), int(spat.y), int(spat.w), int(spat.h))
            if sem:
                item["tags"] = list(sem.tags)
            summary.append(item)
        return summary

class ActuationSystem:
    def __init__(self, em: EntityManager):
        self.em = em

    def scale_coordinates(self, x: float, y: float) -> tuple[int, int]:
        """
        Scales coordinates to physical display (1920x1080 @ 100Hz).
        Gemini vision models output normalized [0..1000] integer coordinates.
        """
        screen_w, screen_h = pyautogui.size()
        fx, fy = float(x), float(y)
        # 1. Normalized float 0.0 .. 1.0
        if 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0:
            rx = int(round(fx * screen_w))
            ry = int(round(fy * screen_h))
            return max(0, min(screen_w - 1, rx)), max(0, min(screen_h - 1, ry))
        # 2. Gemini standard normalized integer space (0 .. 1000)
        if 0 <= fx <= 1000 and 0 <= fy <= 1000:
            rx = int(round((fx / 1000.0) * screen_w))
            ry = int(round((fy / 1000.0) * screen_h))
            return max(0, min(screen_w - 1, rx)), max(0, min(screen_h - 1, ry))
        # 3. Physical coordinates fallback (> 1000)
        rx, ry = int(round(fx)), int(round(fy))
        return max(0, min(screen_w - 1, rx)), max(0, min(screen_h - 1, ry))

    def actuate_spatial(self, x: float, y: float, action: str = "click", text: str = "") -> str:
        """Physical motor actuation on spatial coordinates in vision space."""
        rx, ry = self.scale_coordinates(x, y)
        act = action.lower().strip()
        if act in ["click", "left_click", "press"]:
            pyautogui.click(rx, ry)
            return f"Актуатор: физический клик в ({rx}, {ry}) [кадр: {x}, {y}]."
        elif act in ["right_click", "context_press"]:
            pyautogui.rightClick(rx, ry)
            return f"Актуатор: контекстный правый клик в ({rx}, {ry})."
        elif act in ["double_click", "double_press"]:
            pyautogui.doubleClick(rx, ry)
            return f"Актуатор: двойной клик в ({rx}, {ry})."
        elif act in ["move", "hover"]:
            pyautogui.moveTo(rx, ry)
            return f"Актуатор: позиционирование курсора в ({rx}, {ry})."
        elif act in ["type", "input"]:
            try:
                import pyperclip
                pyperclip.copy(text)
                time.sleep(0.04)
                pyautogui.hotkey("ctrl", "v")
            except Exception:
                pyautogui.write(text, interval=0.01)
            return f"Актуатор: ввод текстового потока ({len(text)} симв)."
        elif act in ["key", "hotkey"]:
            keys = [k.strip().lower() for k in text.replace("+", " ").split()]
            if keys:
                pyautogui.hotkey(*keys)
                return f"Актуатор: передача сигналов клавиш {'+'.join(keys)}."
            return "Клавиши не указаны."
        return f"Неизвестный тип пространственного действия: {act}"

    def focus_surface(self, hwnd: int) -> bool:
        """Restores and brings a Win32 surface to foreground without console flash."""
        try:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            # Win32 Alt trick to permit SetForegroundWindow across thread boundaries
            user32.keybd_event(0x12, 0, 0, 0)
            user32.SetForegroundWindow(hwnd)
            user32.keybd_event(0x12, 0, 2, 0)
            time.sleep(0.04)
            return True
        except Exception:
            return False

    def actuate_entity(self, entity_id: str, action: str, text: str = "") -> str:
        """Operates on an Entity purely through its attached Components."""
        surf = self.em.get_component(entity_id, SurfaceComponent)
        proc = self.em.get_component(entity_id, ProcessComponent)
        spat = self.em.get_component(entity_id, SpatialComponent)
        aff = self.em.get_component(entity_id, AffordanceComponent)

        act = action.lower().strip()

        if act == "focus":
            if surf and aff and aff.can_focus:
                self.focus_surface(surf.hwnd)
                return f"Сущность {entity_id} ('{surf.title[:30]}') выведена в активный фокус."
            return f"Сущность {entity_id} не поддерживает компонент фокусировки."

        elif act == "dismiss":
            if aff and aff.can_dismiss:
                # If surface exists, focus and send dismiss signal
                if surf:
                    self.focus_surface(surf.hwnd)
                    pyautogui.hotkey("alt", "f4")
                    return f"Сущность {entity_id} закрыта (Alt+F4)."
                elif proc:
                    try:
                        p = psutil.Process(proc.pid)
                        p.terminate()
                        return f"Процесс сущности {entity_id} ({proc.name}, PID {proc.pid}) завершен."
                    except Exception as e:
                        return f"Ошибка завершения процесса: {e}"
            return f"Сущность {entity_id} не поддерживает компонент закрытия."

        elif act == "actuate":
            if spat and aff and aff.can_actuate:
                rx, ry = spat.to_physical()
                pyautogui.click(rx, ry)
                return f"Сущность {entity_id} активирована кликом в ({rx}, {ry})."
            return f"Сущность {entity_id} не обладает пространственными координатами."

        elif act == "input":
            if surf:
                self.focus_surface(surf.hwnd)
            if text:
                pyautogui.write(text, interval=0.01)
                return f"Текстовый поток направлен в сущность {entity_id}."
            return "Текст для ввода пуст."

        return f"Неизвестное действие над сущностью: {act}"

    def dismiss_active_surface(self, level: str = "tab") -> str:
        """
        Neural Reflex: Dismisses active context without needing concrete object names.
        level='tab': sends Ctrl+W to current foreground surface.
        level='window': sends Alt+F4 to current foreground surface.
        level='process': terminates the OS process owning current foreground surface.
        """
        lvl = level.lower().strip()
        fg_hwnd = user32.GetForegroundWindow()
        if not fg_hwnd:
            return "Нет активной сущности на переднем плане."

        if lvl in ["tab", "вкладка", "вкладку"]:
            # Send dismiss tab signal to active surface
            pyautogui.hotkey("ctrl", "w")
            return "Активная вкладка/документ текущей сущности закрыта (Ctrl+W)."

        elif lvl in ["window", "окно", "поверхность"]:
            pyautogui.hotkey("alt", "f4")
            return "Активная поверхность закрыта (Alt+F4)."

        elif lvl in ["process", "процесс", "приложение"]:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(pid))
            if pid.value:
                try:
                    p = psutil.Process(pid.value)
                    p_name = p.name()
                    p.terminate()
                    return f"Процесс активной сущности ({p_name}, PID {pid.value}) завершен."
                except Exception as e:
                    return f"Ошибка завершения процесса: {e}"
        return f"Неизвестный уровень закрытия: {level}"

    def route_intent(self, target: str) -> str:
        """Universal Intent Router (URLs, applications, paths, system protocols)."""
        t = target.strip()
        # 1. Web URI
        if t.startswith(("http://", "https://")) or ("." in t and not " " in t and not "\\" in t and "/" in t):
            url = t if t.startswith("http") else "https://" + t
            os.startfile(url)
            return f"Маршрутизация намерения: открыт веб-ресурс {url}."

        # 2. If application is already open, focus its window directly!
        if focus_window_by_process(t):
            return f"Маршрутизация намерения: приложение '{t}' уже запущено и выведено на передний план."

        # 3. Windows Applications & Shortcuts resolver
        resolved = find_windows_app(t)
        if resolved:
            try:
                os.startfile(resolved)
                return f"Маршрутизация намерения: успешно запущено приложение '{t}' ({resolved})."
            except Exception:
                pass

        # 4. File system path
        if os.path.exists(t):
            os.startfile(t)
            return f"Маршрутизация намерения: открыт системный ресурс {t}."

        # 5. System start resolution
        try:
            os.startfile(t)
            return f"Маршрутизация намерения: активирован системный протокол {t}."
        except Exception:
            try:
                import subprocess
                subprocess.Popen(f"start {t}", shell=True, creationflags=0x08000000)
                return f"Маршрутизация намерения: передан вызов оболочке для '{t}'."
            except Exception as e:
                return f"Не удалось маршрутизировать намерение '{t}': {e}"

def focus_window_by_process(app_name: str) -> bool:
    """Finds any running process matching app_name and brings its top-level window to foreground."""
    clean = app_name.lower().strip()
    aliases = {
        "телеграм": "telegram", "телега": "telegram", "тг": "telegram",
        "дискорд": "discord", "диск": "discord",
        "яндекс": "yandex", "браузер": "browser", "хром": "chrome",
        "стим": "steam", "давинчи": "resolve"
    }
    target = aliases.get(clean, clean)
    target_pids = set()
    for p in psutil.process_iter(['pid', 'name']):
        try:
            p_name = p.info['name'].lower()
            if target in p_name:
                target_pids.add(p.info['pid'])
        except Exception:
            continue

    if not target_pids:
        return False

    try:
        hwinsta = user32.OpenWindowStationW("WinSta0", False, 0x37F)
        if hwinsta:
            user32.SetProcessWindowStation(hwinsta)
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x1FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
    except Exception:
        pass

    found_hwnds = []
    def enum_proc(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in target_pids:
            vis = user32.IsWindowVisible(hwnd)
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls_buf, 256)
            cls = cls_buf.value
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            if length > 0:
                user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if "message" not in cls.lower() and "observer" not in cls.lower() and cls not in ["IME", "MSCTFIME UI"]:
                found_hwnds.append((hwnd, vis, title, cls))
        return True

    cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_proc)
    user32.EnumWindows(cb, 0)

    found_hwnds.sort(key=lambda x: 0 if x[1] else 1)

    for hwnd, vis, title, cls in found_hwnds:
        try:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
            user32.BringWindowToTop(hwnd)
            user32.keybd_event(0x12, 0, 0, 0)
            user32.SetForegroundWindow(hwnd)
            user32.keybd_event(0x12, 0, 2, 0)
            time.sleep(0.08)
            return True
        except Exception:
            pass
    return False

def find_windows_app(name: str) -> Optional[str]:
    """Finds installed application executable or shortcut across Windows."""
    name_clean = name.lower().strip()
    aliases = {
        "discord": "discord",
        "дискорд": "discord",
        "диск": "discord",
        "telegram": "telegram",
        "телеграм": "telegram",
        "телега": "telegram",
        "тг": "telegram",
        "яндекс": "yandex",
        "yandex": "yandex",
        "яндекс музыка": "https://music.yandex.ru",
        "музыка": "https://music.yandex.ru",
        "музыку": "https://music.yandex.ru",
        "music": "https://music.yandex.ru",
        "steam": "steam",
        "стим": "steam",
        "davinci": "resolve",
        "давинчи": "resolve",
        "youtube": "https://youtube.com",
        "ютуб": "https://youtube.com",
        "ютубчик": "https://youtube.com",
        "вк": "https://vk.com",
        "погода": "https://yandex.ru/pogoda"
    }
    target = aliases.get(name_clean, name_clean)
    if target.startswith(("http://", "https://")):
        return target

    # Search common Windows shortcut locations
    search_dirs = [
        os.path.expanduser("~/Desktop"),
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
        os.path.expandvars(r"%LOCALAPPDATA%"),
    ]
    for d in search_dirs:
        if not os.path.exists(d):
            continue
        for root, dirs, files in os.walk(d):
            for f in files:
                f_lower = f.lower()
                if f_lower.endswith((".lnk", ".exe")):
                    base = os.path.splitext(f_lower)[0]
                    if target in base:
                        return os.path.join(root, f)

    # Windows URI protocol check
    if target in ["telegram", "discord", "steam"]:
        return f"{target}://"

    return None

def route_intent(target: str) -> str:
    """Module-level intent routing."""
    return ActuationSystem(None).route_intent(target)


print("ECS Data structures initialized successfully.")
