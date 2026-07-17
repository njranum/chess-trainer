from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard_page, name="dashboard"),
    path("trends.json", views.trends_json, name="dashboard-trends"),
]
