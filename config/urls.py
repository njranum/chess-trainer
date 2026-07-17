from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from games.views import health_page
from puzzles.views import archive_page, openings_page

urlpatterns = [
    path("", RedirectView.as_view(url="/train/", permanent=False)),
    path("accounts/", include("django.contrib.auth.urls")),
    path("admin/", admin.site.urls),
    path("train/", include("training.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("openings/", openings_page, name="openings"),
    path("puzzles/", archive_page, name="puzzles"),
    path("games/", health_page, name="games-health"),
]
