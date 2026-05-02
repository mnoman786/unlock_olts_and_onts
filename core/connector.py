import time
import re
import socket
import telnetlib
import paramiko

# Allow legacy algorithms used by old OLT firmware
paramiko.Transport._preferred_kex = (
    'diffie-hellman-group14-sha256',
    'diffie-hellman-group14-sha1',
    'diffie-hellman-group-exchange-sha256',
    'diffie-hellman-group-exchange-sha1',
    'diffie-hellman-group1-sha1',
    'ecdh-sha2-nistp256',
    'ecdh-sha2-nistp384',
    'ecdh-sha2-nistp521',
)
paramiko.Transport._preferred_ciphers = (
    'aes128-ctr', 'aes192-ctr', 'aes256-ctr',
    'aes128-cbc', '3des-cbc', 'aes256-cbc',
)

PAGINATION_PATTERNS = [
    b'---- More ----',
    b'--More--',
    b' More ',
    b'Press any key',
    b'[Q to quit]',
]

MORE_ESCAPE = b' '  # space to continue, or send 'q' to quit pager


class ConnectionError(Exception):
    pass


class OLTConnection:
    def __init__(self, host, port=None, username=None, password=None,
                 protocol='ssh', enable_password=None, timeout=30):
        self.host = host
        self.protocol = protocol.lower()
        self.username = username
        self.password = password
        self.enable_password = enable_password
        self.timeout = timeout
        self._ssh_client = None
        self._channel = None
        self._telnet = None
        self.banner = ''

        if port is None:
            self.port = 22 if self.protocol == 'ssh' else 23
        else:
            self.port = int(port)

    # ------------------------------------------------------------------ connect

    def connect(self):
        try:
            if self.protocol == 'ssh':
                self._connect_ssh()
            else:
                self._connect_telnet()
        except Exception as e:
            raise ConnectionError(f"Failed to connect: {e}") from e
        self.banner = self._drain()
        return self.banner

    def _connect_ssh(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        self._ssh_client = client
        # Send keepalive every 30 s so the channel stays open while user picks ONTs
        transport = client.get_transport()
        if transport:
            transport.set_keepalive(30)
        self._channel = client.invoke_shell(width=250, height=100)
        # No timeout on the channel — we manage timing ourselves via deadline loops
        self._channel.settimeout(None)
        time.sleep(1.5)

    _LOGIN_FAIL_RE = re.compile(
        rb'wrong|failed|incorrect|denied|invalid|bad password|authentication fail',
        re.IGNORECASE,
    )
    _LOGIN_OK_RE = re.compile(rb'[>#\$%]|\$\s*$|>\s*$|#\s*$', re.IGNORECASE)

    def _connect_telnet(self):
        tn = telnetlib.Telnet(self.host, self.port, timeout=self.timeout)
        # Handle login prompts
        idx, _, _ = tn.expect([b'[Uu]sername', b'[Ll]ogin', b'[Uu]ser'], timeout=10)
        if idx >= 0:
            tn.write(self.username.encode('ascii') + b'\r\n')
        idx, _, _ = tn.expect([b'[Pp]assword'], timeout=10)
        if idx >= 0:
            tn.write(self.password.encode('ascii') + b'\r\n')
        # Read response and check for login failure
        time.sleep(1.5)
        try:
            post = tn.read_very_eager()
        except Exception:
            post = b''
        if self._LOGIN_FAIL_RE.search(post):
            tn.close()
            raise ConnectionError(
                f"Login rejected by {self.host} — check username/password."
            )
        self._telnet = tn

    # ------------------------------------------------------------------- send

    def send(self, command, wait=2.0, timeout=None):
        """Send a command and return the full response (handles pagination)."""
        t = timeout or self.timeout
        if self.protocol == 'ssh':
            return self._send_ssh(command, wait)
        else:
            return self._send_telnet(command, wait)

    def _send_ssh(self, command, wait=2.0):
        self._channel.send(command + '\n')
        return self._read_ssh(wait)

    def _read_ssh(self, wait=2.0):
        output = ''
        deadline = time.time() + wait + 10
        time.sleep(wait)
        while time.time() < deadline:
            if self._channel.recv_ready():
                chunk = self._channel.recv(65536).decode('utf-8', errors='replace')
                output += chunk
                # Handle pagination
                for pat in PAGINATION_PATTERNS:
                    if pat.decode('utf-8', errors='replace') in chunk:
                        self._channel.send(' ')
                        time.sleep(0.5)
                        break
                else:
                    # No more pagination; wait a bit for remaining data
                    time.sleep(0.3)
                    if not self._channel.recv_ready():
                        break
            else:
                time.sleep(0.2)
        return output

    def _send_telnet(self, command, wait=2.0):
        self._telnet.write(command.encode('ascii') + b'\r\n')
        output = b''
        deadline = time.time() + wait + 10
        time.sleep(wait)
        while time.time() < deadline:
            try:
                chunk = self._telnet.read_very_eager()
                if chunk:
                    output += chunk
                    for pat in PAGINATION_PATTERNS:
                        if pat in chunk:
                            self._telnet.write(MORE_ESCAPE)
                            time.sleep(0.5)
                            break
                    else:
                        time.sleep(0.3)
                        if not self._telnet.read_very_eager():
                            break
                else:
                    time.sleep(0.2)
            except (EOFError, OSError):
                break
        return output.decode('utf-8', errors='replace')

    # ------------------------------------------------------------------- drain

    def _drain(self):
        """Read whatever is currently in the buffer without sending anything."""
        time.sleep(1)
        if self.protocol == 'ssh':
            out = ''
            while self._channel.recv_ready():
                out += self._channel.recv(65536).decode('utf-8', errors='replace')
                time.sleep(0.1)
            return out
        else:
            try:
                data = self._telnet.read_very_eager()
                return data.decode('utf-8', errors='replace')
            except Exception:
                return ''

    # ----------------------------------------------------------------- helpers

    def read_banner(self):
        return self.banner

    def disconnect(self):
        try:
            if self._ssh_client:
                self._ssh_client.close()
            if self._telnet:
                self._telnet.close()
        except Exception:
            pass
