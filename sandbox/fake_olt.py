"""
Fake OLT Simulator — test the Unlock Tool without a real device.

Supports SSH (default port 2222) and Telnet (default port 2323).
Simulates Huawei, ZTE, FiberHome, or Generic vendor behaviour.

Usage:
    python sandbox/fake_olt.py                        # Huawei, SSH 2222 + Telnet 2323
    python sandbox/fake_olt.py --vendor zte
    python sandbox/fake_olt.py --vendor fiberhome --ssh-port 2222
    python sandbox/fake_olt.py --no-ssh               # Telnet only
    python sandbox/fake_olt.py --no-telnet            # SSH only

Connect the Unlock Tool to:
    Host: 127.0.0.1   Port: 2222 (SSH) or 2323 (Telnet)
    Username: admin   Password: admin
"""

import argparse
import io
import os
import socket
import sys
import textwrap
import threading
import time
import copy
from typing import Dict, List, Optional

import paramiko

# ══════════════════════════════════════════════════════════ Fake ONT data ════

BASE_ONTS = [
    {'sn': 'HWTC0A1B2C3D', 'frame': '0', 'slot': '1', 'port': '0', 'id': '1',  'status': 'online',  'desc': 'Customer-101'},
    {'sn': 'HWTC1E2F3A4B', 'frame': '0', 'slot': '1', 'port': '0', 'id': '2',  'status': 'online',  'desc': 'Customer-102'},
    {'sn': 'ZTEG5C6D7E8F', 'frame': '0', 'slot': '1', 'port': '1', 'id': '1',  'status': 'online',  'desc': 'Customer-103'},
    {'sn': 'ZTEG9A0B1C2D', 'frame': '0', 'slot': '1', 'port': '1', 'id': '2',  'status': 'offline', 'desc': 'Customer-104'},
    {'sn': 'FHTT3E4F5A6B', 'frame': '0', 'slot': '1', 'port': '2', 'id': '1',  'status': 'online',  'desc': 'Customer-105'},
    {'sn': 'FHTT7C8D9E0F', 'frame': '0', 'slot': '1', 'port': '2', 'id': '2',  'status': 'offline', 'desc': 'Customer-106'},
    {'sn': 'HWTC2A3B4C5D', 'frame': '0', 'slot': '2', 'port': '0', 'id': '1',  'status': 'online',  'desc': 'Customer-201'},
    {'sn': 'HWTC6E7F8A9B', 'frame': '0', 'slot': '2', 'port': '0', 'id': '2',  'status': 'online',  'desc': 'Customer-202'},
    {'sn': 'ZTEG0C1D2E3F', 'frame': '0', 'slot': '2', 'port': '1', 'id': '1',  'status': 'online',  'desc': 'Customer-203'},
    {'sn': 'ZTEG4A5B6C7D', 'frame': '0', 'slot': '2', 'port': '1', 'id': '2',  'status': 'online',  'desc': 'Customer-204'},
    {'sn': 'FHTT8E9F0A1B', 'frame': '0', 'slot': '2', 'port': '2', 'id': '1',  'status': 'offline', 'desc': 'Customer-205'},
    {'sn': 'HWTC2C3D4E5F', 'frame': '0', 'slot': '3', 'port': '0', 'id': '1',  'status': 'online',  'desc': 'Customer-301'},
    {'sn': 'ALCL6A7B8C9D', 'frame': '0', 'slot': '3', 'port': '0', 'id': '2',  'status': 'online',  'desc': 'Customer-302'},
    {'sn': 'CXNK0E1F2A3B', 'frame': '0', 'slot': '3', 'port': '1', 'id': '1',  'status': 'online',  'desc': 'Customer-303'},
    {'sn': 'BDCO4C5D6E7F', 'frame': '0', 'slot': '3', 'port': '1', 'id': '2',  'status': 'offline', 'desc': 'Customer-304'},
]


# ══════════════════════════════════════════════════════════ Vendor engines ═══

class VendorEngine:
    BANNER = ''
    PROMPT = '> '
    PROMPT_CONFIG = '(config)# '

    def __init__(self):
        self.onts: List[Dict] = copy.deepcopy(BASE_ONTS)
        self._mode = 'user'          # user / enable / config / interface
        self._iface = None           # current interface (frame/slot)

    def process(self, line: str) -> str:
        line = line.strip()
        if not line:
            return ''
        return self._dispatch(line)

    def _dispatch(self, line: str) -> str:
        low = line.lower()
        # ── mode changes ──
        if low in ('enable', 'en'):
            self._mode = 'enable'
            return ''
        if low in ('config', 'configure terminal', 'conf t'):
            self._mode = 'config'
            return ''
        if low.startswith('interface gpon'):
            parts = line.split()
            self._iface = parts[2] if len(parts) > 2 else '0/0'
            self._mode = 'interface'
            return f'Enter GPON interface {self._iface}\r\n'
        if low in ('quit', 'exit', 'q'):
            if self._mode == 'interface':
                self._mode = 'config'
                self._iface = None
            elif self._mode == 'config':
                self._mode = 'enable'
            else:
                self._mode = 'user'
            return ''
        # ── queries ──
        if low.startswith('display board'):
            return self._show_board()
        if low.startswith('display ont info') or low.startswith('show ont'):
            return self._show_onts_huawei()
        if low.startswith('show gpon onu') or low.startswith('show pon onu'):
            return self._show_onts_zte()
        if low.startswith('show ont autofind') or low.startswith('show onu'):
            return self._show_onts_fiberhome()
        if low.startswith('show equipment ont'):
            return self._show_onts_nokia()
        if low.startswith('display version') or low.startswith('show version'):
            return self._show_version()
        if low in ('save', 'write', 'commit', 'copy running startup'):
            return self._save()
        if low.startswith('ont restore-factory') or low.startswith('ont reset'):
            return self._reset_ont_omci(line)
        if low.startswith('pon onu reset') or low.startswith('onu factory-reset') or low.startswith('ont factory-reset'):
            return self._reset_ont_omci(line)
        if low.startswith('ont delete') or low.startswith('undo ont'):
            return self._delete_ont_huawei(line)
        if low.startswith('no pon onu') or low.startswith('no onu'):
            return self._delete_ont_zte(line)
        if low.startswith('no ont-port') or low.startswith('undo ont add'):
            return self._delete_ont_fiberhome(line)
        if low.startswith('configure no equipment ont'):
            return self._delete_ont_nokia(line)
        if '?' in low or low in ('help', 'h'):
            return self._help()
        return f'  ^{line}\r\n  % Unknown command.\r\n'

    # ── board ──────────────────────────────────────────────────────────────
    def _show_board(self) -> str:
        return (
            'Slot  Board    Status\r\n'
            '----  -------  ------\r\n'
            '   1  H801GPBH Normal\r\n'
            '   2  H801GPBH Normal\r\n'
            '   3  H801GPBH Normal\r\n'
        )

    # ── ONT lists ──────────────────────────────────────────────────────────
    def _show_onts_huawei(self) -> str:
        lines = [
            'F/S/P    ONT-ID  SN              Control  Run-state\r\n',
            '------   ------  --------------  -------  ---------\r\n',
        ]
        for o in self.onts:
            lines.append(
                f'{o["frame"]:>1}/{o["slot"]:>1}/{o["port"]:>1}'
                f'    {o["id"]:>4}  {o["sn"]:<16}  active   {o["status"]}\r\n'
            )
        lines.append(f'\r\nTotal: {len(self.onts)} ONT(s)\r\n')
        return ''.join(lines)

    def _show_onts_zte(self) -> str:
        lines = [
            'Interface        ONU-ID  SN              Status\r\n',
            '---------        ------  --------------  ------\r\n',
        ]
        for o in self.onts:
            port_str = f'{o["frame"]}/{o["slot"]}/{o["port"]}'
            lines.append(
                f'gpon-olt_{port_str:<10}  {o["id"]:>3}  {o["sn"]:<16}  {o["status"]}\r\n'
            )
        lines.append(f'\r\nTotal: {len(self.onts)} ONU(s)\r\n')
        return ''.join(lines)

    def _show_onts_fiberhome(self) -> str:
        lines = [
            'Slot  PON  ONU-ID  SN              Status\r\n',
            '----  ---  ------  --------------  ------\r\n',
        ]
        for o in self.onts:
            lines.append(
                f'{o["slot"]:>4}  {o["port"]:>3}  {o["id"]:>6}  {o["sn"]:<16}  {o["status"]}\r\n'
            )
        lines.append(f'\r\nTotal: {len(self.onts)} ONT(s)\r\n')
        return ''.join(lines)

    def _show_onts_nokia(self) -> str:
        lines = [
            'ont-idx       admin  oper   sn\r\n',
            '----------    -----  -----  ----------------\r\n',
        ]
        for o in self.onts:
            idx = f'{o["frame"]}/{o["slot"]}/{o["port"]}/{o["id"]}'
            lines.append(f'{idx:<14}  up     {o["status"]:<6}  {o["sn"]}\r\n')
        lines.append(f'\r\nTotal: {len(self.onts)} ONT(s)\r\n')
        return ''.join(lines)

    # ── delete ─────────────────────────────────────────────────────────────
    def _find_ont(self, port=None, ont_id=None, sn=None, slot=None):
        for o in self.onts:
            if sn and o['sn'].upper() == sn.upper():
                return o
            if port and ont_id:
                port_match = o['port'] == str(port) and o['id'] == str(ont_id)
                slot_match = (slot is None) or (o['slot'] == str(slot))
                if port_match and slot_match:
                    return o
        return None

    def _remove_ont(self, o):
        self.onts = [x for x in self.onts if x is not o]

    def _delete_ont_huawei(self, line: str) -> str:
        # ont delete <port> <id>
        import re
        m = re.search(r'ont delete\s+(\S+)\s+(\S+)', line, re.IGNORECASE)
        if not m:
            m = re.search(r'undo ont add\S*\s+(\S+)\s+sn\s+(\S+)', line, re.IGNORECASE)
            if m:
                port, sn = m.group(1), m.group(2)
                o = self._find_ont(sn=sn)
            else:
                return '  % Invalid command syntax.\r\n'
        else:
            port, ont_id = m.group(1), m.group(2)
            # Slot comes from the current interface context (interface gpon frame/slot)
            slot = self._iface.split('/')[-1] if self._iface else None
            o = self._find_ont(port=port, ont_id=ont_id, slot=slot)
        if o:
            self._remove_ont(o)
            return '  Command executed successfully.\r\n'
        return '  % ONT not found.\r\n'

    def _reset_ont_omci(self, line: str) -> str:
        import re
        m = re.search(r'(\d+)\s+(\d+)\s*$', line)
        if m:
            port, ont_id = m.group(1), m.group(2)
            slot = self._iface.split('/')[-1] if self._iface else None
            o = self._find_ont(port=port, ont_id=ont_id, slot=slot)
            if not o:
                m2 = re.search(r'sn\s+(\S+)', line, re.IGNORECASE)
                if m2:
                    o = self._find_ont(sn=m2.group(1))
            if o:
                print(f'  [OMCI RESET] SN {o["sn"]} received factory reset command — simulating reboot')
                o['status'] = 'offline'
                import threading, time
                def come_back():
                    time.sleep(8)
                    o['status'] = 'online'
                    print(f'  [OMCI RESET] SN {o["sn"]} rebooted and is back online')
                threading.Thread(target=come_back, daemon=True).start()
                return '  Command executed successfully.\r\n'
        return '  % ONT not found.\r\n'

    def _delete_ont_zte(self, line: str) -> str:
        import re
        m = re.search(r'sn\s+(\S+)', line, re.IGNORECASE)
        if m:
            o = self._find_ont(sn=m.group(1))
        else:
            m2 = re.search(r'no onu\s+(\S+)', line, re.IGNORECASE)
            o = self._find_ont(ont_id=m2.group(1)) if m2 else None
        if o:
            self._remove_ont(o)
            return ''
        return '  % ONU not found.\r\n'

    def _delete_ont_fiberhome(self, line: str) -> str:
        import re
        m = re.search(r'onu\s+(\S+)', line, re.IGNORECASE)
        if m:
            o = self._find_ont(ont_id=m.group(1))
            if o:
                self._remove_ont(o)
                return '  Done.\r\n'
        m2 = re.search(r'sn\s+(\S+)', line, re.IGNORECASE)
        if m2:
            o = self._find_ont(sn=m2.group(1))
            if o:
                self._remove_ont(o)
                return '  Done.\r\n'
        return '  % ONT not found.\r\n'

    def _delete_ont_nokia(self, line: str) -> str:
        import re
        m = re.search(r'ont\s+(\d+)/(\d+)/(\d+)/(\d+)', line, re.IGNORECASE)
        if m:
            _, _, port, ont_id = m.groups()
            o = self._find_ont(port=port, ont_id=ont_id)
            if o:
                self._remove_ont(o)
                return ''
        return '  % error: ONT not found\r\n'

    # ── misc ───────────────────────────────────────────────────────────────
    def _show_version(self) -> str:
        return self.BANNER + '\r\nVersion: Simulator 1.0\r\n'

    def _save(self) -> str:
        return '  Configuration saved successfully.\r\n'

    def _help(self) -> str:
        return (
            '  display  - Display information\r\n'
            '  show     - Show information\r\n'
            '  enable   - Enter privileged mode\r\n'
            '  config   - Enter configuration mode\r\n'
            '  quit     - Exit current mode\r\n'
            '  save     - Save configuration\r\n'
        )

    def prompt(self) -> str:
        if self._mode == 'interface':
            return f'{self.PROMPT_CONFIG[:-2]}-if-gpon-{self._iface}]# '
        if self._mode == 'config':
            return self.PROMPT_CONFIG
        return self.PROMPT


# ── Vendor subclasses ───────────────────────────────────────────────────────

class HuaweiEngine(VendorEngine):
    BANNER = (
        '\r\n'
        '        Huawei Technologies Co., Ltd.\r\n'
        '        MA5800-X17 Optical Line Terminal\r\n'
        '        VRP Platform Software\r\n'
        '\r\n'
    )
    PROMPT        = 'MA5800-X17>'
    PROMPT_CONFIG = 'MA5800-X17(config)#'


class ZTEEngine(VendorEngine):
    BANNER = (
        '\r\n'
        '        ZTE Corporation\r\n'
        '        ZXAN C300 OLT Platform\r\n'
        '\r\n'
    )
    PROMPT        = 'C300#'
    PROMPT_CONFIG = 'C300(config)#'


class FiberHomeEngine(VendorEngine):
    BANNER = (
        '\r\n'
        '        FiberHome Telecommunication Technologies Co.,Ltd.\r\n'
        '        AN5516-04 GPON OLT\r\n'
        '\r\n'
    )
    PROMPT        = 'Admin\\FiberHome>'
    PROMPT_CONFIG = 'Admin\\FiberHome(config)#'


class GenericEngine(VendorEngine):
    BANNER = '\r\n        Generic OLT Platform v2.1\r\n\r\n'
    PROMPT        = 'OLT>'
    PROMPT_CONFIG = 'OLT(config)#'


ENGINES = {
    'huawei':    HuaweiEngine,
    'zte':       ZTEEngine,
    'fiberhome': FiberHomeEngine,
    'generic':   GenericEngine,
}


# ══════════════════════════════════════════════════════════ SSH Server ════════

HOST_KEY_FILE = os.path.join(os.path.dirname(__file__), '.fake_olt_host_key')


def _get_host_key():
    if os.path.exists(HOST_KEY_FILE):
        return paramiko.RSAKey(filename=HOST_KEY_FILE)
    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(HOST_KEY_FILE)
    return key


class OLTServerInterface(paramiko.ServerInterface):
    def __init__(self, username, password):
        self._user = username
        self._pass = password
        self.event = threading.Event()

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        if username == self._user and password == self._pass:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_none(self, username):
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return 'password'

    def check_channel_shell_request(self, channel):
        self.event.set()
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True


def _handle_ssh_client(client_sock, addr, engine_cls, username, password):
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


def _run_shell(chan, engine: VendorEngine):
    chan.send(engine.BANNER.encode())
    time.sleep(0.2)
    chan.send(f'{engine.prompt()} '.encode())

    buf = ''
    while True:
        try:
            data = chan.recv(256)
        except Exception:
            break
        if not data:
            break

        for byte in data:
            ch = chr(byte) if isinstance(byte, int) else byte

            if ch in ('\r', '\n'):
                chan.send(b'\r\n')
                response = engine.process(buf)
                if response:
                    chan.send(response.encode('utf-8', errors='replace'))
                chan.send(f'{engine.prompt()} '.encode())
                buf = ''
            elif ch == '\x03':  # Ctrl+C
                buf = ''
                chan.send(b'\r\n')
                chan.send(f'{engine.prompt()} '.encode())
            elif ch in ('\x7f', '\x08'):  # Backspace
                if buf:
                    buf = buf[:-1]
                    chan.send(b'\x08 \x08')
            elif ch == '\x04':  # Ctrl+D
                break
            else:
                buf += ch
                chan.send(ch.encode('utf-8', errors='replace'))


class SSHServer:
    def __init__(self, host, port, engine_cls, username, password):
        self.host = host
        self.port = port
        self.engine_cls = engine_cls
        self.username = username
        self.password = password
        self._sock = None

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(10)
        print(f'  [SSH]    Listening on {self.host}:{self.port}')
        while True:
            try:
                client, addr = self._sock.accept()
                t = threading.Thread(
                    target=_handle_ssh_client,
                    args=(client, addr, self.engine_cls, self.username, self.password),
                    daemon=True,
                )
                t.start()
            except Exception:
                break


# ══════════════════════════════════════════════════════════ Telnet Server ═════

class TelnetServer:
    def __init__(self, host, port, engine_cls, username, password):
        self.host = host
        self.port = port
        self.engine_cls = engine_cls
        self.username = username
        self.password = password

    def start(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(10)
        print(f'  [Telnet] Listening on {self.host}:{self.port}')
        while True:
            try:
                client, addr = srv.accept()
                t = threading.Thread(
                    target=self._handle_client,
                    args=(client,),
                    daemon=True,
                )
                t.start()
            except Exception:
                break

    def _handle_client(self, sock):
        engine = self.engine_cls()
        try:
            # Send telnet negotiation: suppress go ahead
            sock.send(b'\xff\xfb\x03\xff\xfb\x01')
            sock.send(engine.BANNER.encode())
            sock.send(b'\r\nUsername: ')
            u = self._readline(sock, echo=True)
            sock.send(b'Password: ')
            p = self._readline(sock, echo=False)
            sock.send(b'\r\n')

            if u.strip() != self.username or p.strip() != self.password:
                sock.send(b'\r\nAuthentication failed.\r\n')
                sock.close()
                return

            sock.send(f'{engine.prompt()} '.encode())

            buf = ''
            while True:
                try:
                    data = sock.recv(256)
                except Exception:
                    break
                if not data:
                    break
                for byte in data:
                    # Skip telnet IAC sequences
                    if isinstance(byte, int):
                        if byte == 255:
                            continue
                        ch = chr(byte)
                    else:
                        ch = byte

                    if ch in ('\r', '\n', '\x00'):
                        if ch == '\r':
                            sock.send(b'\r\n')
                            response = engine.process(buf)
                            if response:
                                sock.send(response.encode('utf-8', errors='replace'))
                            sock.send(f'{engine.prompt()} '.encode())
                            buf = ''
                    elif ch in ('\x7f', '\x08'):
                        if buf:
                            buf = buf[:-1]
                            sock.send(b'\x08 \x08')
                    elif ch == '\x04':
                        sock.close()
                        return
                    elif ch.isprintable():
                        buf += ch
                        sock.send(ch.encode())
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _readline(self, sock, echo=True):
        buf = ''
        while True:
            try:
                data = sock.recv(1)
            except Exception:
                break
            if not data:
                break
            ch = chr(data[0]) if isinstance(data[0], int) else data
            if ch in ('\r', '\n', '\x00'):
                break
            elif ch in ('\x7f', '\x08'):
                if buf:
                    buf = buf[:-1]
                    if echo:
                        sock.send(b'\x08 \x08')
            elif ch.isprintable():
                buf += ch
                if echo:
                    sock.send(ch.encode())
        return buf


# ══════════════════════════════════════════════════════════════ Main ══════════

def main():
    parser = argparse.ArgumentParser(description='Fake OLT Simulator for testing')
    parser.add_argument('--vendor',   default='huawei',
                        choices=list(ENGINES.keys()),
                        help='OLT vendor to simulate (default: huawei)')
    parser.add_argument('--host',     default='127.0.0.1', help='Bind address')
    parser.add_argument('--ssh-port', type=int, default=2222, help='SSH port (default: 2222)')
    parser.add_argument('--telnet-port', type=int, default=2323, help='Telnet port (default: 2323)')
    parser.add_argument('--username', default='admin', help='Login username (default: admin)')
    parser.add_argument('--password', default='admin', help='Login password (default: admin)')
    parser.add_argument('--no-ssh',    action='store_true', help='Disable SSH server')
    parser.add_argument('--no-telnet', action='store_true', help='Disable Telnet server')
    args = parser.parse_args()

    engine_cls = ENGINES[args.vendor]

    print()
    print('  ╔══════════════════════════════════════════════╗')
    print('  ║     Fake OLT Simulator — Ready for testing   ║')
    print('  ╚══════════════════════════════════════════════╝')
    print(f'  Vendor   : {args.vendor.capitalize()} (simulated)')
    print(f'  Username : {args.username}')
    print(f'  Password : {args.password}')
    print(f'  ONTs     : {len(BASE_ONTS)} pre-loaded')
    print()

    threads = []

    if not args.no_ssh:
        srv = SSHServer(args.host, args.ssh_port, engine_cls, args.username, args.password)
        t = threading.Thread(target=srv.start, daemon=True)
        t.start()
        threads.append(t)

    if not args.no_telnet:
        srv = TelnetServer(args.host, args.telnet_port, engine_cls, args.username, args.password)
        t = threading.Thread(target=srv.start, daemon=True)
        t.start()
        threads.append(t)

    if not threads:
        print('  ERROR: Both SSH and Telnet are disabled. Nothing to start.')
        sys.exit(1)

    print()
    print('  Press Ctrl+C to stop.\n')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print('\n  Simulator stopped.')


if __name__ == '__main__':
    main()
