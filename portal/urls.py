from django.urls import path, re_path
from . import views

urlpatterns = [
    path('healthz', views.health), path('api/account', views.accounts),
    path('api/account/data', views.account_data),
    path('api/account/export', views.account_data, {'operation': 'export'}),
    path('api/account/<str:operation>', views.accounts),
    path('api/<path:route>', views.api), re_path(r'^(?P<name>[^/]*)$', views.page),
]
