from django.urls import include, path, re_path

from planner.views import spa_index

urlpatterns = [
    path("api/", include("planner.urls")),
    # Any other non-file path falls back to the React app.
    re_path(r"^(?!api/|static/|assets/).*$", spa_index, name="spa-index"),
]
