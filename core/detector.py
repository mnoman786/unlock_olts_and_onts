import re

# Patterns checked against the login banner + prompt + response to a blank Enter
VENDOR_SIGNATURES = [
    # (vendor_name, display_name, list_of_regex_patterns)
    ('huawei', 'Huawei', [
        r'Huawei',
        r'MA5[568]\d{2}',
        r'SmartAX',
        r'\bVRP\b',
        r'Huawei Technologies',
        r'Copyright.*Huawei',
    ]),
    ('zte', 'ZTE', [
        r'\bZTE\b',
        r'ZTE Corporation',
        r'\bZXAN\b',
        r'C3[02]\d\b',
        r'C6[02]\d\b',
    ]),
    ('fiberhome', 'FiberHome', [
        r'FiberHome',
        r'Fiberhome',
        r'AN5516',
        r'AN5506',
        r'Copyright.*FiberHome',
    ]),
    ('nokia', 'Nokia / Alcatel-Lucent', [
        r'\bNokia\b',
        r'Alcatel',
        r'TiMOS',
        r'\bISAM\b',
        r'7360\b',
        r'7342\b',
        r'7330\b',
    ]),
    ('calix', 'Calix', [
        r'\bCalix\b',
        r'\bE7\b',
        r'E-Series',
        r'C-Series',
    ]),
    ('bdcom', 'BDCOM', [
        r'\bBDCOM\b',
        r'GP\d{4}',
    ]),
    ('vsol', 'VSOL', [
        r'\bVSOL\b',
        r'V1800',
        r'V2802',
    ]),
    ('dasan', 'Dasan / Zhone', [
        r'\bDasan\b',
        r'\bZhone\b',
        r'\bDZS\b',
    ]),
]


def detect_vendor(text: str):
    """
    Return (vendor_key, display_name) for the best match, or ('generic', 'Unknown').
    text should be the combined banner + prompt + initial probe response.
    """
    for key, display, patterns in VENDOR_SIGNATURES:
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return key, display
    return 'generic', 'Unknown'


def probe_vendor(connection):
    """
    Send a harmless command (blank Enter + '?') to get more banner/prompt text,
    then run detect_vendor on everything collected.
    """
    banner = connection.read_banner()

    # Send Enter to get the prompt
    extra = connection.send('', wait=1.0)
    banner += extra

    # Try '?' which most OLTs handle gracefully (shows help or error)
    help_out = connection.send('?', wait=1.5)
    banner += help_out

    vendor_key, display = detect_vendor(banner)

    # If still unknown, try 'display version' (Huawei) and 'show version' (most others)
    if vendor_key == 'generic':
        for cmd in ('display version', 'show version'):
            out = connection.send(cmd, wait=2.0)
            banner += out
            vendor_key, display = detect_vendor(banner)
            if vendor_key != 'generic':
                break

    return vendor_key, display
