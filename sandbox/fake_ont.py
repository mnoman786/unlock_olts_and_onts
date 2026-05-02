"""
Fake ONT — simulates a Huawei ONT locked to an OLT.

State machine:
  LOCKED   → ONT is registered to OLT-A (192.168.10.1), shows registration info
  REBOOTING→ factory reset sent, connection dropped, ONT offline for 15 s
  UNLOCKED → ONT came back clean, no OLT registration

Usage:
    python sandbox/fake_ont.py

Then in the tool:
    IP: 127.0.0.1  |  Port: 2323  |  Protocol: Telnet
    Username: admin  |  Password: admin

Workflow to test:
    1. Connect  →  Get Device Info  →  see OLT registration (LOCKED)
    2. Factory Reset  →  connection drops, ONT reboots
    3. Wait ~15 s, reconnect  →  Get Device Info  →  see clean config (UNLOCKED)
"""

import socket
import threading
import time
import re

HOST = '127.0.0.1'
PORT = 2323

# ── Shared ONT state (persists across sessions) ───────────────────────────────

_state_lock = threading.Lock()
_state = {
    'status':       'locked',   # 'locked' | 'rebooting' | 'unlocked'
    'reboot_at':    None,       # time.time() when reboot started
    'reboot_secs':  15,         # seconds offline after reset
}

def get_status():
    with _state_lock:
        s = _state.copy()
    if s['status'] == 'rebooting':
        elapsed = time.time() - s['reboot_at']
        if elapsed >= s['reboot_secs']:
            with _state_lock:
                _state['status'] = 'unlocked'
                _state['reboot_at'] = None
            return 'unlocked'
        return 'rebooting'
    return s['status']

def trigger_reset():
    with _state_lock:
        _state['status']    = 'rebooting'
        _state['reboot_at'] = time.time()

def restore_lock():
    """Re-lock the ONT (restart the sandbox scenario)."""
    with _state_lock:
        _state['status']    = 'locked'
        _state['reboot_at'] = None


# ── Banners / info per state ──────────────────────────────────────────────────

LOCKED_BANNER = (
    "\r\n"
    "EchoLife HG8245Q2 Telnet Server\r\n"
    "Huawei Technologies Co., Ltd.\r\n"
    "Serial Number : HWTC0A1B2C3D\r\n"
    "\r\n"
)

UNLOCKED_BANNER = (
    "\r\n"
    "EchoLife HG8245Q2 Telnet Server\r\n"
    "Huawei Technologies Co., Ltd.\r\n"
    "Serial Number : HWTC0A1B2C3D\r\n"
    "[Factory Default]\r\n"
    "\r\n"
)

LOCKED_INFO = """\
--- ONT Status ---
Serial Number   : HWTC0A1B2C3D
Hardware        : HG8245Q2
Software        : V5R019C00S125
OLT IP          : 192.168.10.1
OLT Vendor      : Huawei MA5800-X7
PLOAM Status    : REGISTERED
PLOAM Password  : 1234567890
LOID            : HW-ONT-00142
Registration    : LOCKED to OLT-A
Uptime          : 14 days 06:22:11
"""

UNLOCKED_INFO = """\
--- ONT Status ---
Serial Number   : HWTC0A1B2C3D
Hardware        : HG8245Q2
Software        : V5R019C00S125
OLT IP          : (none)
PLOAM Status    : UNREGISTERED
PLOAM Password  : (cleared)
LOID            : (cleared)
Registration    : FACTORY DEFAULT — not locked to any OLT
Uptime          : 00:00:43
"""

RESET_CMDS = re.compile(
    r'factory.?reset|sendcmd.*DB.*Reset|system reboot factory|restore default|reset factory',
    re.IGNORECASE,
)
INFO_CMDS = re.compile(
    r'display version|show version|show system|show device|display ont|cat /proc',
    re.IGNORECASE,
)


# ── Session handler ───────────────────────────────────────────────────────────

class FakeONTSession(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr

    def _send(self, text):
        try:
            self.conn.sendall(text.encode('utf-8', errors='replace'))
        except Exception:
            pass

    def _recv_line(self, timeout=60) -> str:
        self.conn.settimeout(timeout)
        buf = b''
        try:
            while True:
                ch = self.conn.recv(1)
                if not ch:
                    break
                if ch in (b'\r', b'\n'):
                    if buf:
                        break
                elif ch == b'\xff':
                    self.conn.recv(2)   # swallow telnet IAC options
                else:
                    buf += ch
        except (socket.timeout, OSError):
            pass
        return buf.decode('utf-8', errors='replace').strip()

    def run(self):
        try:
            self._session()
        except Exception:
            pass
        finally:
            try:
                self.conn.close()
            except Exception:
                pass

    def _session(self):
        status = get_status()

        if status == 'rebooting':
            remaining = max(0, _state['reboot_secs'] - (time.time() - _state['reboot_at']))
            self._send(
                f"\r\nONT is rebooting after factory reset...\r\n"
                f"Please wait ~{int(remaining)+1} seconds and reconnect.\r\n"
            )
            return

        banner = LOCKED_BANNER if status == 'locked' else UNLOCKED_BANNER
        self._send(banner)

        # Login loop
        for attempt in range(5):
            self._send("Login: ")
            username = self._recv_line()
            self._send("Password: ")
            password = self._recv_line()

            if username == 'admin' and password == 'admin':
                self._send("\r\nWelcome.\r\n\r\n")
                self._shell(status)
                return

            self._send("\r\nUser name or password is wrong, please try it again!\r\n")
            time.sleep(0.5)

        self._send("\r\nToo many failed attempts. Connection closed.\r\n")

    def _shell(self, status):
        prompt = 'WAP>' if status == 'locked' else 'WAP(factory-default)>'
        while True:
            self._send(f"\r\n{prompt} ")
            cmd = self._recv_line(timeout=120)
            if not cmd:
                break

            low = cmd.lower().strip()

            if low in ('exit', 'quit', 'logout'):
                self._send("Bye.\r\n")
                break

            elif low in ('?', 'help'):
                self._send(
                    "\r\ndisplay version   show device info and registration status\r\n"
                    "show version      same\r\n"
                    "factory-reset     wipe config and reboot\r\n"
                    "exit              disconnect\r\n"
                )

            elif INFO_CMDS.search(cmd):
                if 'proc' in low:
                    self._send("\r\nError: Unknown command.\r\n")
                else:
                    info = LOCKED_INFO if status == 'locked' else UNLOCKED_INFO
                    self._send("\r\n" + info)

            elif RESET_CMDS.search(cmd):
                if status == 'unlocked':
                    self._send("\r\nONT is already at factory defaults.\r\n")
                else:
                    self._send(
                        "\r\nClearing configuration...\r\n"
                        "Removing OLT registration...\r\n"
                        "Factory reset successful.\r\n"
                        f"ONT will reboot in {_state['reboot_secs']} seconds.\r\n"
                        "Rebooting...\r\n"
                    )
                    trigger_reset()
                    print(f"[fake_ont] Factory reset triggered — offline for {_state['reboot_secs']} s")
                    time.sleep(1)
                    break  # close connection = simulated reboot

            else:
                self._send(f"\r\nError: Unknown command '{cmd}'.\r\n")


# ── Server ────────────────────────────────────────────────────────────────────

def run_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(5)
    print("=" * 55)
    print("  Fake ONT Sandbox")
    print("=" * 55)
    print(f"  Telnet: {HOST}:{PORT}")
    print(f"  Login : admin / admin")
    print(f"  State : LOCKED (registered to OLT-A 192.168.10.1)")
    print()
    print("  In the tool → Direct ONT tab:")
    print(f"    IP=127.0.0.1  Port=2323  Protocol=Telnet")
    print()
    print("  Test steps:")
    print("    1. Connect → Get Device Info → see LOCKED status")
    print("    2. Factory Reset → connection drops (ONT rebooting)")
    print(f"    3. Wait {_state['reboot_secs']}s → reconnect → Get Device Info → see UNLOCKED")
    print("=" * 55)
    while True:
        conn, addr = srv.accept()
        status = get_status()
        print(f"[fake_ont] Connection from {addr[0]}:{addr[1]}  state={status}")
        FakeONTSession(conn, addr).start()


if __name__ == '__main__':
    run_server()
