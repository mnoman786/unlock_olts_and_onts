from django.urls import path, include

urlpatterns = [
    path('', include('olt_app.urls')),
]
