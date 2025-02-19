from django.urls import path

from . import projects_views

app_name = "bots"

urlpatterns = [
    path(
        "<str:object_id>",
        projects_views.ProjectDashboardView.as_view(),
        name="project-dashboard",
    ),
    path(
        "<str:object_id>/bots",
        projects_views.ProjectBotsView.as_view(),
        name="project-bots",
    ),
    path(
        "<str:object_id>/bots/<str:bot_object_id>",
        projects_views.ProjectBotDetailView.as_view(),
        name="project-bot-detail",
    ),
    path(
        "<str:object_id>/settings",
        projects_views.ProjectSettingsView.as_view(),
        name="project-settings",
    ),
    path(
        "<str:object_id>/keys",
        projects_views.ProjectApiKeysView.as_view(),
        name="project-api-keys",
    ),
    path(
        "<str:object_id>/keys/create/",
        projects_views.CreateApiKeyView.as_view(),
        name="create-api-key",
    ),
    path(
        "<str:object_id>/keys/<str:key_object_id>/delete/",
        projects_views.DeleteApiKeyView.as_view(),
        name="delete-api-key",
    ),
    path(
        "<str:object_id>/settings/credentials/",
        projects_views.CreateCredentialsView.as_view(),
        name="create-credentials",
    ),
    # Don't put anything after this, it will redirect to the dashboard
    path(
        "<str:object_id>/",
        projects_views.RedirectToDashboardView.as_view(),
        name="project-unrecognized",
    ),
    path(
        "<str:object_id>/<path:extra>",
        projects_views.RedirectToDashboardView.as_view(),
        name="project-unrecognized",
    ),
]
