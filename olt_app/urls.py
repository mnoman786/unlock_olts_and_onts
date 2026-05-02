from django.urls import path
from . import views

urlpatterns = [
    path('',               views.index,       name='index'),
    path('api/connect/',   views.connect,     name='connect'),
    path('api/delete/',    views.delete_ont,  name='delete_ont'),
    path('api/reset/',     views.reset_ont,   name='reset_ont'),
    path('api/save/',      views.save_config, name='save_config'),
    path('api/disconnect/',views.disconnect,  name='disconnect'),
    path('api/raw/',       views.raw_command, name='raw_command'),
]
