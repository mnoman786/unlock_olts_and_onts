"""
Full unlock scenario demo — two fake OLTs in one process, shared ONT state.

OLT-1 (port 2222) = the OLD OLT where ONTs are currently locked.
OLT-2 (port 2224) = the NEW OLT you want to move them to.

Flow:
  1. Connect tool to OLT-1 (port 2222) → scan → see all 15 ONTs
  2. Select ONTs and click Unlock → they are removed from OLT-1
  3. Connect tool to OLT-2 (port 2224) → scan → those same ONTs now appear there
     (simulating the ONT automatically re-registering on the new OLT)

Run:
    python sandbox/scenario_demo.py
"""

import copy
import threading
import time
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import paramiko
from sandbox.fake_olt import (
    HuaweiEngine, BASE_ONTS,
    _get_host_key, OLTServerInterface, _run_shell,
    TelnetServer,
)

# ══════════════════════════════════════════ Shared state between OLT-1 & OLT-2

# OLT-1 starts with all ONTs.  OLT-2 starts empty.
# When an ONT is deleted from OLT-1 → it moves to OLT-2 automatically.

_lock = threading.Lock()
_olt1_onts = copy.deepcopy(BASE_ONTS)   # source ONTs
_olt2_onts: list = []                    # destination starts empty


def _move_to_olt2(removed_ont: dict):
    """Called by OLT-1 engine when an ONT is deleted — moves it to OLT-2."""
    with _lock:
        # Avoid duplicates
        sns = {o['sn'] for o in _olt2_onts}
        if removed_ont['sn'] not in sns:
            _olt2_onts.append(copy.deepcopy(removed_ont))
    print(f'  [MOVE] SN {removed_ont["sn"]} left OLT-1 → appeared on OLT-2')


# ══════════════════════════════════════════ Custom engines with shared state

class OLT1Engine(HuaweiEngine):
    """Source OLT — owns the ONTs.  On delete, moves them to OLT-2."""

    def __init__(self):
        super().__init__()
        # Use the shared list (not a copy)
        self.onts = _olt1_onts

    def _remove_ont(self, o):
        _move_to_olt2(o)
        with _lock:
            if o in self.onts:
                self.onts.remove(o)


class OLT2Engine(HuaweiEngine):
    """Destination OLT — starts empty, gains ONTs as they are unlocked."""

    def __init__(self):
        super().__init__()
        self.onts = _olt2_onts

    # OLT-2 shows a different banner so the tool displays a different name
    BANNER = (
        '\r\n'
        '        Huawei Technologies Co., Ltd.\r\n'
        '        MA5800-X7  Optical Line Terminal  [DESTINATION OLT]\r\n'
        '        VRP Platform Software\r\n'
        '\r\n'
    )
    PROMPT        = 'MA5800-X7>'
    PROMPT_CONFIG = 'MA5800-X7(config)#'


# ══════════════════════════════════════════ SSH server (reused from fake_olt)

def _handle_ssh_client(client_sock, engine_cls, username, password):
    transport = paramiko.Transport(client_sock)
    transport.add_server_key(_get_host_key())
    server_iface = OLTServerInterface(username, password)
    try:
        transport.start_server(server=server_iface)
    except Exception:
        return
    chan = transport.accept(20)
    if chan is None:
        return
    server_iface.event.wait(10)
    engine = engine_cls()
    _run_shell(chan, engine)
    chan.close()
    transport.close()


def _start_ssh_server(host, port, engine_cls, username='admin', password='admin'):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(10)
    while True:
        try:
            client, _ = srv.accept()
            t = threading.Thread(
                target=_handle_ssh_client,
                args=(client, engine_cls, username, password),
                daemon=True,
            )
            t.start()
        except Exception:
            break


# ══════════════════════════════════════════════════════════════ Status ticker

def _status_ticker():
    """Print a status line every 10 s so you can watch ONTs move."""
    while True:
        time.sleep(10)
        with _lock:
            n1 = len(_olt1_onts)
            n2 = len(_olt2_onts)
        print(f'  [STATUS] OLT-1: {n1} ONT(s) remaining  |  OLT-2: {n2} ONT(s) registered')


# ══════════════════════════════════════════════════════════════════ Main

def main():
    HOST = '127.0.0.1'
    USERNAME = 'admin'
    PASSWORD  = 'admin'

    print()
    print('  ╔═══════════════════════════════════════════════════════════╗')
    print('  ║          Full Unlock Scenario — Two Fake OLTs             ║')
    print('  ╠═══════════════════════════════════════════════════════════╣')
    print('  ║  OLT-1 (SOURCE)       127.0.0.1:2222  — 15 ONTs locked   ║')
    print('  ║  OLT-2 (DESTINATION)  127.0.0.1:2224  — empty at start   ║')
    print('  ║                                                           ║')
    print('  ║  Username: admin   Password: admin                        ║')
    print('  ╠═══════════════════════════════════════════════════════════╣')
    print('  ║  STEP 1: Connect tool to port 2222 → scan → unlock ONTs  ║')
    print('  ║  STEP 2: Connect tool to port 2224 → scan → see them     ║')
    print('  ╚═══════════════════════════════════════════════════════════╝')
    print()

    # OLT-1 SSH on 2222
    t1 = threading.Thread(
        target=_start_ssh_server,
        args=(HOST, 2222, OLT1Engine, USERNAME, PASSWORD),
        daemon=True,
    )
    t1.start()
    print(f'  [OLT-1] SSH listening on {HOST}:2222  (source — has all ONTs)')

    # OLT-2 SSH on 2224
    t2 = threading.Thread(
        target=_start_ssh_server,
        args=(HOST, 2224, OLT2Engine, USERNAME, PASSWORD),
        daemon=True,
    )
    t2.start()
    print(f'  [OLT-2] SSH listening on {HOST}:2224  (destination — starts empty)')

    # Telnet mirrors
    tel1 = TelnetServer(HOST, 2323, OLT1Engine, USERNAME, PASSWORD)
    t3 = threading.Thread(target=tel1.start, daemon=True)
    t3.start()
    print(f'  [OLT-1] Telnet listening on {HOST}:2323')

    tel2 = TelnetServer(HOST, 2325, OLT2Engine, USERNAME, PASSWORD)
    t4 = threading.Thread(target=tel2.start, daemon=True)
    t4.start()
    print(f'  [OLT-2] Telnet listening on {HOST}:2325')

    # Status ticker
    threading.Thread(target=_status_ticker, daemon=True).start()

    print()
    print('  Press Ctrl+C to stop.\n')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print('\n  Stopped.')


if __name__ == '__main__':
    main()
