"""
Direct ONT access — connect via patch cable to the ONT's LAN port,
then reset/unlock it without going through any OLT.

Common ONT local IPs:  192.168.1.1, 192.168.100.1, 192.168.0.1
Common credentials:    admin/admin, telecomadmin/admintelecom, root/admin
"""

import re
import socket
import time
from typing import List, Optional

from core.connector import OLTConnection

# ── Common ONT IPs to probe during auto-scan ─────────────────────────────────
COMMON_ONT_IPS = [
    '192.168.1.1',
    '192.168.100.1',
    '192.168.0.1',
    '192.168.1.254',
    '10.10.10.1',
    '10.0.0.1',
    '192.168.2.1',
]

COMMON_CREDENTIALS = [
    ('admin',          'admin'),
    ('telecomadmin',   'admintelecom'),
    ('telecomadmin',   'nE7jA%5m'),        # Huawei ISP default
    ('root',           'admin'),
    ('admin',          '1234'),
    ('admin',          'password'),
    ('user',           'user'),
    ('support',        'support'),
]

# ── Vendor detection from ONT local banner ────────────────────────────────────
ONT_VENDOR_PATTERNS = [
    ('huawei',    ['Huawei', 'HG8', 'EchoLife', 'MA5']),
    ('zte',       ['ZTE', 'F660', 'F670', 'F609', 'ZXHN']),
    ('fiberhome', ['FiberHome', 'AN5506', 'AN5516']),
    ('calix',     ['Calix', 'GigaSpire']),
    ('nokia',     ['Nokia', 'Alcatel', 'G-010']),
    ('vsol',      ['VSOL', 'V2802']),
]

# ── Factory reset commands per vendor ─────────────────────────────────────────
# Each entry: (pre_command, reset_command, confirm_response)
RESET_COMMANDS = {
    'huawei': [
        # Newer Huawei ONTs
        ('su',              'sendcmd 1 DB p Reset',            ''),
        ('enable',          'system reboot factory',           ''),
        ('',                'factory-reset',                   ''),
    ],
    'zte': [
        ('',                'sendcmd 1 DB p Reset',            ''),
        ('',                'sys reboot factory',              ''),
        ('enable',          'factory-reset',                   ''),
    ],
    'fiberhome': [
        ('',                'factory_reset',                   'y'),
        ('',                'restore_factory',                 ''),
        ('',                'restore default',                 ''),
    ],
    'nokia': [
        ('',                'factory-reset',                   ''),
        ('admin',           'system restore-factory',          ''),
    ],
    'generic': [
        ('',                'factory-reset',                   ''),
        ('',                'restore default',                 ''),
        ('',                'sendcmd 1 DB p Reset',            ''),
        ('',                'sys reboot factory',              ''),
        ('su',              'sendcmd 1 DB p Reset',            ''),
        ('enable',          'factory-reset',                   ''),
        ('',                'factory_reset',                   ''),
        ('',                'reset factory',                   ''),
    ],
}

# ── Info commands ─────────────────────────────────────────────────────────────
INFO_COMMANDS = [
    'display version',
    'show version',
    'show system info',
    'cat /proc/version',
    'show device info',
]


def _get_local_subnets() -> List[str]:
    """Return list of local subnet prefixes e.g. ['192.168.1', '10.0.0']"""
    subnets = set()
    try:
        # Get all local IPs
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ':' in ip:
                continue  # skip IPv6
            if ip.startswith('127.'):
                continue
            parts = ip.rsplit('.', 1)
            if parts:
                subnets.add(parts[0])
    except Exception:
        pass
    # Also try connecting to 8.8.8.8 to find the outbound interface IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        subnets.add(ip.rsplit('.', 1)[0])
    except Exception:
        pass
    return list(subnets) if subnets else ['192.168.1', '192.168.100']


def _probe_ip(ip: str, ports: list, timeout: float) -> dict:
    """Try each port on a single IP. Return first open port or None."""
    for port, proto in ports:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((ip, port))
            s.close()
            return {'ip': ip, 'port': port, 'protocol': proto}
        except Exception:
            continue
    return {}


def scan_for_onts(timeout: float = 0.8, full_subnet: bool = False) -> List[dict]:
    """
    Scan for ONTs on the network.

    full_subnet=False  — quick scan of common ONT IPs only (~2 sec)
    full_subnet=True   — scan entire local /24 subnet (~20–40 sec)
    """
    import concurrent.futures

    PORTS = [(23, 'telnet'), (22, 'ssh'), (80, 'http')]
    targets = []

    if full_subnet:
        subnets = _get_local_subnets()
        for subnet in subnets:
            for i in range(1, 255):
                targets.append(f'{subnet}.{i}')
    else:
        # Quick: common ONT IPs + current subnet gateway addresses
        targets = list(COMMON_ONT_IPS)
        for subnet in _get_local_subnets():
            for last in [1, 100, 254, 2]:
                ip = f'{subnet}.{last}'
                if ip not in targets:
                    targets.append(ip)

    results = []
    seen_ips = set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
        futures = {ex.submit(_probe_ip, ip, PORTS, timeout): ip for ip in targets}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result and result['ip'] not in seen_ips:
                seen_ips.add(result['ip'])
                results.append(result)

    # Sort by IP
    results.sort(key=lambda r: list(map(int, r['ip'].split('.'))))
    return results


def detect_ont_vendor(text: str) -> str:
    for vendor, patterns in ONT_VENDOR_PATTERNS:
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return vendor
    return 'generic'


class DirectONT:
    """Manages a direct connection to an ONT over its LAN port."""

    def __init__(self):
        self._conn: Optional[OLTConnection] = None
        self.vendor: str = 'generic'
        self.banner: str = ''
        self.ip: str = ''

    def connect(self, ip: str, port: int, username: str,
                password: str, protocol: str) -> str:
        self.ip = ip
        self._conn = OLTConnection(
            host=ip, port=port,
            username=username, password=password,
            protocol=protocol, timeout=15,
        )
        self.banner = self._conn.connect()
        self.vendor = detect_ont_vendor(self.banner)

        # Send a couple of info commands to improve vendor detection from banner
        for cmd in INFO_COMMANDS[:2]:
            try:
                out = self._conn.send(cmd, wait=1.5)
                if re.search(r'Login:|Username:|Password:', out, re.IGNORECASE):
                    break
                self.banner += out
                v = detect_ont_vendor(out)
                if v != 'generic':
                    self.vendor = v
                    break
                time.sleep(0.3)
            except Exception:
                break

        return self.banner

    def auto_connect(self, ip: str) -> dict:
        """
        Try all common credential + protocol combinations.
        Returns connection details on success.
        """
        for port, proto in [(23, 'telnet'), (22, 'ssh')]:
            for user, passwd in COMMON_CREDENTIALS:
                try:
                    self.connect(ip, port, user, passwd, proto)
                    return {
                        'ok': True,
                        'ip': ip, 'port': port,
                        'protocol': proto,
                        'username': user,
                        'vendor': self.vendor,
                        'banner': self.banner[:300],
                    }
                except Exception:
                    if self._conn:
                        try:
                            self._conn.disconnect()
                        except Exception:
                            pass
                    self._conn = None
                    continue
        return {'ok': False, 'error': 'Could not connect with any known credentials'}

    _LOGIN_RE = re.compile(r'Login:|Username:|login:|Password:|password:', re.IGNORECASE)

    def get_info(self) -> str:
        if not self._conn:
            return ''
        output = ''
        for cmd in INFO_COMMANDS:
            try:
                out = self._conn.send(cmd, wait=1.5)
                # Session timed out — ONT is showing a login prompt again
                if self._LOGIN_RE.search(out):
                    break
                if out.strip():
                    output += f'--- {cmd} ---\n{out}\n'
                time.sleep(0.5)
            except Exception:
                break
        # Fall back to banner captured at connect time
        if not output and self.banner:
            return f'--- Connection Banner ---\n{self.banner}\n'
        return output or '(No information retrieved)'

    def factory_reset(self) -> dict:
        """
        Send factory reset command directly to the ONT.
        Tries all known commands for the detected vendor.
        """
        if not self._conn:
            return {'ok': False, 'error': 'Not connected'}

        cmds = RESET_COMMANDS.get(self.vendor, []) + RESET_COMMANDS['generic']
        tried = []

        for pre, reset_cmd, confirm in cmds:
            try:
                if pre:
                    self._conn.send(pre, wait=1.0)

                out = self._conn.send(reset_cmd, wait=3.0)

                # Send confirmation if required
                if confirm:
                    if re.search(r'[Yy]/[Nn]|[Cc]onfirm|[Pp]roceed', out):
                        out += self._conn.send(confirm, wait=3.0)

                tried.append(reset_cmd)

                # Success indicators
                if re.search(
                    r'[Ss]uccess|[Rr]eset|[Rr]ebooting|[Rr]estarting|'
                    r'[Ff]actory|[Dd]one|OK\b',
                    out
                ):
                    return {
                        'ok': True,
                        'command': reset_cmd,
                        'output': out[:400],
                        'message': 'Factory reset sent. ONT will reboot in 10–30 seconds.',
                    }

                # If command was not rejected, consider it sent
                if not re.search(
                    r'[Uu]nknown command|[Ii]nvalid|[Nn]ot found|[Ee]rror',
                    out
                ):
                    return {
                        'ok': True,
                        'command': reset_cmd,
                        'output': out[:400],
                        'message': 'Reset command sent (no explicit confirmation from ONT).',
                    }

            except Exception as e:
                tried.append(f'{reset_cmd} (error: {e})')
                continue

        return {
            'ok': False,
            'error': f'No reset command worked. Tried: {", ".join(tried[:5])}',
        }

    def send_raw(self, cmd: str) -> str:
        if not self._conn:
            return 'Not connected'
        return self._conn.send(cmd, wait=2.0)

    def disconnect(self):
        if self._conn:
            try:
                self._conn.disconnect()
            except Exception:
                pass
        self._conn = None
