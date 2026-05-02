"""
In-memory store for active OLTManager instances, keyed by Django session ID.
This is fine for a single-server admin tool.
"""
import threading
from typing import Dict, Optional
from core.manager import OLTManager

_lock = threading.Lock()
_store: Dict[str, OLTManager] = {}


def get(session_id: str) -> Optional[OLTManager]:
    with _lock:
        return _store.get(session_id)


def put(session_id: str, manager: OLTManager):
    with _lock:
        _store[session_id] = manager


def remove(session_id: str):
    with _lock:
        mgr = _store.pop(session_id, None)
        if mgr:
            try:
                mgr.disconnect()
            except Exception:
                pass


def get_or_create(session_id: str) -> OLTManager:
    with _lock:
        if session_id not in _store:
            _store[session_id] = OLTManager()
        return _store[session_id]
