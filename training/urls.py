from django.urls import path

from . import views

urlpatterns = [
    path("", views.train_page, name="train"),
    path("next", views.next_api, name="train-next"),
    path("attempt", views.attempt_api, name="train-attempt"),
    path("solution", views.solution_api, name="train-solution"),
    path("bury", views.bury_api, name="train-bury"),
    path("report", views.report_api, name="train-report"),
]
