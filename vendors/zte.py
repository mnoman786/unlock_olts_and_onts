import re
from typing import List
from .base import BaseVendor, ONTInfo


class ZTEVendor(BaseVendor):
    NAME = 'ZTE'

    def enter_privileged_mode(self, enable_password=None):
        out = self._send('enable', wait=1.0)
        if re.search(r'[Pp]assword', out) and enable_password:
            self._send(enable_password, wait=1.0)

    # ---------------------------------------------------------------- discover

    def _get_gpon_ports(self) -> List[str]:
        """Return list like ['1/1/1', '1/1/2', ...]"""
        out = self._send('show interface gpon-olt_1/1/1', wait=2.0)
        ports = set()
        # Try show running-config to find all gpon-olt interfaces
        run_out = self._send('show running-config | include gpon-olt', wait=4.0)
        for m in re.finditer(r'gpon-olt_(\d+/\d+/\d+)', run_out):
            ports.add(m.group(1))
        if not ports:
            # Fallback: brute-probe ports 1/1/1 through 1/1/16
            for p in range(1, 17):
                ports.add(f'1/1/{p}')
        return sorted(ports)

    def get_all_onts(self) -> List[ONTInfo]:
        onts: List[ONTInfo] = []

        # Global summary command (C600 / newer firmware)
        out = self._send('show gpon onu state', wait=5.0)
        parsed = self._parse_onu_state(out)
        if parsed:
            return parsed

        # Per-port approach
        for port in self._get_gpon_ports():
            out = self._send(f'show gpon onu state gpon-olt_{port}', wait=3.0)
            onts.extend(self._parse_onu_state(out, default_port=port))

        return onts

    def _parse_onu_state(self, text: str, default_port: str = '') -> List[ONTInfo]:
        """
        ZTE table row examples:
          gpon-olt_1/1/1     1   ZTEG1234ABCD   online
          1/1/1              2   HWTC00112233   offline
        """
        onts = []
        pattern = re.compile(
            r'(?:gpon-olt_)?(\d+)/(\d+)/(\d+)\s+'
            r'(\d+)\s+'
            r'([0-9A-Za-z:]{4,20})\s+'
            r'(\S+)'
        )
        for m in pattern.finditer(text):
            rack, slot, port, onu_id, sn, status = m.groups()
            onts.append(ONTInfo(
                serial_number=sn,
                ont_id=onu_id,
                port=port,
                slot=slot,
                frame=rack,
                status=status,
                raw_line=m.group(0),
            ))
        return onts

    # ----------------------------------------------------------------- delete

    def delete_ont(self, ont: ONTInfo) -> bool:
        port_str = f'{ont.frame}/{ont.slot}/{ont.port}'
        self._send('config', wait=1.0)
        # Method 1: remove authorization by SN
        out = self._send(
            f'no pon onu-authorized gpon-olt_{port_str} sn {ont.serial_number}',
            wait=2.0,
        )
        if re.search(r'[Ee]rror|[Ii]nvalid', out):
            # Method 2: delete by ONU id
            self._send(
                f'interface gpon-olt_{port_str}',
                wait=1.0,
            )
            out = self._send(f'no onu {ont.ont_id}', wait=2.0)
            self._send('exit', wait=1.0)
        return True

    def reset_ont(self, ont: ONTInfo) -> bool:
        port_str = f'{ont.frame}/{ont.slot}/{ont.port}'
        # ZTE: pon onu reset sends OMCI factory reset
        out = self._send(
            f'pon onu reset gpon-olt_{port_str} onu_id {ont.ont_id}',
            wait=5.0,
        )
        if re.search(r'[Ee]rror|[Ii]nvalid', out):
            out = self._send(
                f'onu factory-reset gpon-olt_{port_str} onu_id {ont.ont_id}',
                wait=5.0,
            )
        return not bool(re.search(r'[Ee]rror|[Ff]ail', out))

    def save_config(self):
        self._send('exit', wait=1.0)
        self._send('write', wait=4.0)
