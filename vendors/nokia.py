import re
from typing import List
from .base import BaseVendor, ONTInfo


class NokiaVendor(BaseVendor):
    NAME = 'Nokia / ALU ISAM'

    def enter_privileged_mode(self, enable_password=None):
        # Nokia ISAM uses environment cli-engine
        self._send('environment cli-engine', wait=1.0)

    # ---------------------------------------------------------------- discover

    def get_all_onts(self) -> List[ONTInfo]:
        # Nokia/ALU ISAM 7360/7342 command
        out = self._send('show equipment ont summary', wait=6.0)
        onts = self._parse_ont_summary(out)
        if not onts:
            out = self._send('show equipment ont detail', wait=8.0)
            onts = self._parse_ont_detail(out)
        return onts

    def _parse_ont_summary(self, text: str) -> List[ONTInfo]:
        """
        Nokia ISAM format:
          ont-idx          admin     oper    sn
          1/1/1/1          up        up      ALCL12345678
        """
        onts = []
        pattern = re.compile(
            r'(\d+)/(\d+)/(\d+)/(\d+)\s+'
            r'\S+\s+'
            r'(\S+)\s+'
            r'([0-9A-Za-z]{8,20})'
        )
        for m in pattern.finditer(text):
            rack, shelf, slot, ont_id, status, sn = m.groups()
            onts.append(ONTInfo(
                serial_number=sn,
                ont_id=ont_id,
                port=slot,
                slot=shelf,
                frame=rack,
                status=status,
                raw_line=m.group(0),
            ))
        return onts

    def _parse_ont_detail(self, text: str) -> List[ONTInfo]:
        return self._parse_ont_summary(text)

    # ----------------------------------------------------------------- delete

    def delete_ont(self, ont: ONTInfo) -> bool:
        idx = f'{ont.frame}/{ont.slot}/{ont.port}/{ont.ont_id}'
        # First bring admin-state down
        self._send(f'configure equipment ont {idx} admin-state down', wait=2.0)
        out = self._send(f'configure no equipment ont {idx}', wait=3.0)
        return not re.search(r'[Ee]rror|[Ff]ailed', out)

    def reset_ont(self, ont: ONTInfo) -> bool:
        idx = f'{ont.frame}/{ont.slot}/{ont.port}/{ont.ont_id}'
        out = self._send(f'configure equipment ont {idx} reset', wait=5.0)
        return not bool(re.search(r'[Ee]rror|[Ff]ailed', out))

    def save_config(self):
        self._send('admin save', wait=4.0)
