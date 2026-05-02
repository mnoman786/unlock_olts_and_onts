import json
import sys
import os
import time

# Make sure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from olt_app import connections


def index(request):
    request.session.setdefault('_sid', request.session.session_key or 'anon')
    return render(request, 'olt_app/index.html')


def _sid(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


# ──────────────────────────────────────────────────────────── connect ───────

@csrf_exempt
@require_POST
def connect(request):
    data = json.loads(request.body)
    host     = data.get('host', '').strip()
    port     = int(data.get('port') or (22 if data.get('protocol') == 'ssh' else 23))
    username = data.get('username', '').strip()
    password = data.get('password', '')
    enable   = data.get('enable_password', '')
    protocol = data.get('protocol', 'ssh')
    vendor_override = data.get('vendor', 'auto')

    if not host or not username:
        return JsonResponse({'ok': False, 'error': 'Host and username are required.'})

    sid = _sid(request)
    connections.remove(sid)          # close any previous session
    mgr = connections.get_or_create(sid)

    try:
        banner = mgr.connect(host, port, username, password, protocol, enable)

        if vendor_override and vendor_override != 'auto':
            mgr.set_vendor_manually(vendor_override)
            vendor_key  = vendor_override
            vendor_name = vendor_override.capitalize()
        else:
            vendor_key, vendor_name = mgr.detect_vendor()

        mgr.enter_privileged(enable)

        onts = mgr.list_onts()

        ont_list = [{
            'sn':     o.serial_number,
            'port':   o.port_label(),
            'ont_id': o.ont_id,
            'status': o.status,
            'frame':  o.frame,
            'slot':   o.slot,
            'port_n': o.port,
            'desc':   o.description,
        } for o in onts]

        return JsonResponse({
            'ok':          True,
            'banner':      banner[:300].strip(),
            'vendor_key':  vendor_key,
            'vendor_name': vendor_name,
            'onts':        ont_list,
        })

    except Exception as e:
        connections.remove(sid)
        return JsonResponse({'ok': False, 'error': str(e)})


# ──────────────────────────────────────────────────────── delete_ont ────────

@csrf_exempt
@require_POST
def delete_ont(request):
    """Delete a single ONT by its index in the last scan result."""
    data = json.loads(request.body)
    sn      = data.get('sn', '')
    port    = data.get('port_n', '')
    slot    = data.get('slot', '')
    frame   = data.get('frame', '')
    ont_id  = data.get('ont_id', '')

    sid = _sid(request)
    mgr = connections.get(sid)
    if not mgr:
        return JsonResponse({'ok': False, 'error': 'Not connected. Please connect first.'})

    from vendors.base import ONTInfo
    ont = ONTInfo(
        serial_number=sn,
        ont_id=ont_id,
        port=port,
        slot=slot,
        frame=frame,
    )
    try:
        ok = mgr.delete_ont(ont)
        return JsonResponse({'ok': True, 'confirmed': ok, 'sn': sn})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e), 'sn': sn})


# ─────────────────────────────────────────────────────── reset_ont ──────────

@csrf_exempt
@require_POST
def reset_ont(request):
    """Send OMCI factory-reset to the ONT through the OLT."""
    data   = json.loads(request.body)
    sn     = data.get('sn', '')
    port   = data.get('port_n', '')
    slot   = data.get('slot', '')
    frame  = data.get('frame', '')
    ont_id = data.get('ont_id', '')

    sid = _sid(request)
    mgr = connections.get(sid)
    if not mgr:
        return JsonResponse({'ok': False, 'error': 'Not connected. Please connect first.'})

    from vendors.base import ONTInfo
    ont = ONTInfo(serial_number=sn, ont_id=ont_id, port=port, slot=slot, frame=frame)
    try:
        ok = mgr.reset_ont(ont)
        return JsonResponse({'ok': True, 'confirmed': ok, 'sn': sn})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e), 'sn': sn})


# ──────────────────────────────────────────────────────────── save ───────────

@csrf_exempt
@require_POST
def save_config(request):
    sid = _sid(request)
    mgr = connections.get(sid)
    if not mgr:
        return JsonResponse({'ok': False, 'error': 'Not connected.'})
    try:
        mgr.save()
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})


# ─────────────────────────────────────────────────────── disconnect ──────────

@csrf_exempt
@require_POST
def disconnect(request):
    sid = _sid(request)
    connections.remove(sid)
    return JsonResponse({'ok': True})


# ─────────────────────────────────────────────────────── raw command ─────────

@csrf_exempt
@require_POST
def raw_command(request):
    """Send a raw command to the OLT and return output (for debugging)."""
    data = json.loads(request.body)
    cmd  = data.get('command', '')
    sid  = _sid(request)
    mgr  = connections.get(sid)
    if not mgr:
        return JsonResponse({'ok': False, 'error': 'Not connected.'})
    try:
        out = mgr.send_raw(cmd)
        return JsonResponse({'ok': True, 'output': out})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})
