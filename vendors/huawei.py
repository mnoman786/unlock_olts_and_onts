import re
from typing import List
from .base import BaseVendor, ONTInfo


class HuaweiVendor(BaseVendor):
    NAME = 'Huawei'

    def enter_privileged_mode(self, enable_password=None):
        out = self._send('enable', wait=1.0)
        if re.search(r'[Pp]assword', out) and enable_password:
            self._send(enable_password, wait=1.0)
        self._send('config', wait=1.0)

    # ---------------------------------------------------------------- discover

    def _get_gpon_slots(self) -> List[str]:
        """Return list of slot numbers that have GPON boards."""
        out = self._send('display board 0', wait=3.0)
        slots = []
        for line in out.splitlines():
            # Lines like:  0    H801GPBH   ...  Normal
            if re.search(r'GPBH|GPBD|GPON|H801|H802', line, re.IGNORECASE):
                m = re.match(r'\s*(\d+)\s', line)
                if m:
                    slots.append(m.group(1))
        # Fallback: slots 0-7 are common
        return slots if slots else [str(i) for i in range(8)]

    def get_all_onts(self) -> List[ONTInfo]:
        onts: List[ONTInfo] = []

        # Try single global command first (works on MA5800)
        out = self._send('display ont info 0 all', wait=5.0)
        if re.search(r'ONT-ID|F/S/P', out):
            return self._parse_ont_output(out)

        # Per-slot approach for MA5600T style
        for slot in self._get_gpon_slots():
            # display ont info <slot> all  →  shows every port in that slot
            out = self._send(f'display ont info {slot} all', wait=5.0)
            onts.extend(self._parse_ont_output(out))

        return onts

    def _parse_ont_output(self, text: str) -> List[ONTInfo]:
        """
        Huawei table row example:
          0/ 0/ 0    1  4857544338...  active        online   -
        or
          F/ S/ P  ONT-ID  SN           ...
        """
        onts = []
        # Pattern: frame/slot/port  ont_id  serial_number  ...  run_state
        pattern = re.compile(
            r'(\d+)/\s*(\d+)/\s*(\d+)\s+'   # F/S/P
            r'(\d+)\s+'                       # ONT-ID
            r'([0-9A-Za-z\-]{8,20})\s+'          # SN (vendor prefix + hex)
            r'\S+\s+'                          # control flag
            r'(\S+)'                           # run state
        )
        for m in pattern.finditer(text):
            frame, slot, port, ont_id, sn, status = m.groups()
            onts.append(ONTInfo(
                serial_number=sn,
                ont_id=ont_id,
                port=port,
                slot=slot,
                frame=frame,
                status=status,
                raw_line=m.group(0),
            ))
        return onts

    # ----------------------------------------------------------------- delete

    def delete_ont(self, ont: ONTInfo) -> bool:
        self._send(f'interface gpon {ont.frame}/{ont.slot}', wait=1.0)
        out = self._send(f'ont delete {ont.port} {ont.ont_id}', wait=3.0)
        self._send('quit', wait=1.0)
        return bool(re.search(r'[Ss]uccess|[Cc]ommand executed', out))

    def reset_ont(self, ont: ONTInfo) -> bool:
        self._send(f'interface gpon {ont.frame}/{ont.slot}', wait=1.0)
        # ont restore-factory = OMCI factory reset (wipes ONT config)
        out = self._send(f'ont restore-factory {ont.port} {ont.ont_id}', wait=5.0)
        if re.search(r'[Ee]rror|[Ii]nvalid|[Ff]ail', out):
            # Fallback: some firmware uses ont-reset
            out = self._send(f'ont reset {ont.port} {ont.ont_id}', wait=5.0)
        self._send('quit', wait=1.0)
        return not bool(re.search(r'[Ee]rror|[Ff]ail', out))

    def save_config(self):
        self._send('quit', wait=1.0)   # exit interface mode
        self._send('quit', wait=1.0)   # exit config mode
        out = self._send('save', wait=2.0)
        if re.search(r'[Cc]onfirm|[Yy]/[Nn]', out):
            self._send('y', wait=3.0)
