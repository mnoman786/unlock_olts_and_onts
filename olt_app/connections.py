"""
In-memory store for active OLTManager and DirectONT instances,
keyed by Django session ID.
"""
import threading
from typing import Dict, Optional
from core.manager import OLTManager
from core.ont_direct import DirectONT

_lock = threading.Lock()
_store: Dict[str, OLTManager] = {}

# ── Direct ONT connections (separate store) ───────────────────────────────────
_ont_lock = threading.Lock()
_ont_store: Dict[str, DirectONT] = {}


def get_ont(session_id: str) -> Optional[DirectONT]:
    with _ont_lock:
        return _ont_store.get(session_id)


def remove_ont(session_id: str):
    with _ont_lock:
        ont = _ont_store.pop(session_id, None)
        if ont:
            try:
                ont.disconnect()
            except Exception:
                pass


def get_or_create_ont(session_id: str) -> DirectONT:
    with _ont_lock:
        if session_id not in _ont_store:
            _ont_store[session_id] = DirectONT()
        return _ont_store[session_id]


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
