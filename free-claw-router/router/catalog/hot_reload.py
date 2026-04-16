from __future__ import annotations
from pathlib import Path
from threading import Lock
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from router.catalog.registry import Registry

class _Handler(FileSystemEventHandler):
    def __init__(self, live: "CatalogLive") -> None:
        self._live = live

    def on_any_event(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".yaml"):
            self._live.reload()

class CatalogLive:
    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir)
        self._current = Registry.load_from_dir(self._dir)
        self._lock = Lock()
        self._observer: Observer | None = None

    def snapshot(self) -> Registry:
        with self._lock:
            return self._current

    def reload(self) -> None:
        try:
            new = Registry.load_from_dir(self._dir)
        except Exception:
            return
        with self._lock:
            self._current = new

    def start(self) -> None:
        obs = Observer()
        obs.schedule(_Handler(self), str(self._dir), recursive=False)
        obs.start()
        self._observer = obs

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
