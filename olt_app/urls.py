from django.urls import path
from . import views

urlpatterns = [
    # ── OLT management ───────────────────────────────────────────────────────
    path('',                   views.index,            name='index'),
    path('api/connect/',       views.connect,          name='connect'),
    path('api/delete/',        views.delete_ont,       name='delete_ont'),
    path('api/reset/',         views.reset_ont,        name='reset_ont'),
    path('api/save/',          views.save_config,      name='save_config'),
    path('api/disconnect/',    views.disconnect,        name='disconnect'),
    path('api/raw/',           views.raw_command,      name='raw_command'),

    # ── Direct ONT (patch cable) ─────────────────────────────────────────────
    path('api/ont/scan/',      views.ont_scan,          name='ont_scan'),
    path('api/ont/connect/',   views.ont_connect,       name='ont_connect'),
    path('api/ont/info/',      views.ont_info,          name='ont_info'),
    path('api/ont/reset/',     views.ont_factory_reset, name='ont_factory_reset'),
    path('api/ont/raw/',       views.ont_raw,           name='ont_raw'),
    path('api/ont/disconnect/',views.ont_disconnect,    name='ont_disconnect'),
]
