from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .bots_api_views import launch_bot
from .models import (
    ApiKey,
    Bot,
    BotEventManager,
    BotEventTypes,
    BotStates,
    Credentials,
    Project,
    Recording,
    RecordingStates,
    RecordingTypes,
    TranscriptionProviders,
    TranscriptionTypes,
    Utterance,
)
from .utils import generate_recordings_json_for_bot_detail_view


class ProjectUrlContextMixin:
    def get_project_context(self, object_id, project):
        return {
            "project": project,
        }


class ProjectDashboardView(LoginRequiredMixin, ProjectUrlContextMixin, View):
    def get(self, request, object_id):
        try:
            project = get_object_or_404(Project, object_id=object_id, organization=request.user.organization)
        except:
            return redirect("/")

        # Quick start guide status checks
        zoom_credentials = Credentials.objects.filter(project=project, credential_type=Credentials.CredentialTypes.ZOOM_OAUTH).exists()

        deepgram_credentials = Credentials.objects.filter(project=project, credential_type=Credentials.CredentialTypes.DEEPGRAM).exists()

        has_api_keys = ApiKey.objects.filter(project=project).exists()

        has_ended_bots = Bot.objects.filter(project=project, state=BotStates.ENDED).exists()

        context = self.get_project_context(object_id, project)
        context.update(
            {
                "quick_start": {
                    "has_credentials": zoom_credentials and deepgram_credentials,
                    "has_api_keys": has_api_keys,
                    "has_ended_bots": has_ended_bots,
                }
            }
        )

        return render(request, "projects/project_dashboard.html", context)


class ProjectApiKeysView(LoginRequiredMixin, ProjectUrlContextMixin, View):
    def get(self, request, object_id):
        project = get_object_or_404(Project, object_id=object_id, organization=request.user.organization)
        context = self.get_project_context(object_id, project)
        context["api_keys"] = ApiKey.objects.filter(project=project).order_by("-created_at")
        return render(request, "projects/project_api_keys.html", context)


class CreateApiKeyView(LoginRequiredMixin, View):
    def post(self, request, object_id):
        project = get_object_or_404(Project, object_id=object_id, organization=request.user.organization)
        name = request.POST.get("name")

        if not name:
            return HttpResponse("Name is required", status=400)

        api_key_instance, api_key = ApiKey.create(project=project, name=name)

        # Render the success modal content
        return render(
            request,
            "projects/partials/api_key_created_modal.html",
            {"api_key": api_key, "name": name},
        )


class DeleteApiKeyView(LoginRequiredMixin, ProjectUrlContextMixin, View):
    def delete(self, request, object_id, key_object_id):
        api_key = get_object_or_404(
            ApiKey,
            object_id=key_object_id,
            project__organization=request.user.organization,
        )
        api_key.delete()
        context = self.get_project_context(object_id, api_key.project)
        context["api_keys"] = ApiKey.objects.filter(project=api_key.project).order_by("-created_at")
        return render(request, "projects/project_api_keys.html", context)


class RedirectToDashboardView(LoginRequiredMixin, View):
    def get(self, request, object_id, extra=None):
        return redirect("bots:project-dashboard", object_id=object_id)


class CreateCredentialsView(LoginRequiredMixin, ProjectUrlContextMixin, View):
    def post(self, request, object_id):
        project = get_object_or_404(Project, object_id=object_id, organization=request.user.organization)

        try:
            credential_type = int(request.POST.get("credential_type"))
            if credential_type not in [choice[0] for choice in Credentials.CredentialTypes.choices]:
                return HttpResponse("Invalid credential type", status=400)

            # Get or create the credential instance
            credential, created = Credentials.objects.get_or_create(project=project, credential_type=credential_type)

            # Parse the credentials data based on type
            if credential_type == Credentials.CredentialTypes.ZOOM_OAUTH:
                credentials_data = {
                    "client_id": request.POST.get("client_id"),
                    "client_secret": request.POST.get("client_secret"),
                }

                if not all(credentials_data.values()):
                    return HttpResponse("Missing required credentials data", status=400)

            elif credential_type == Credentials.CredentialTypes.DEEPGRAM:
                credentials_data = {"api_key": request.POST.get("api_key")}

                if not all(credentials_data.values()):
                    return HttpResponse("Missing required credentials data", status=400)
            elif credential_type == Credentials.CredentialTypes.GOOGLE_TTS:
                credentials_data = {"service_account_json": request.POST.get("service_account_json")}

                if not all(credentials_data.values()):
                    return HttpResponse("Missing required credentials data", status=400)
            else:
                return HttpResponse("Unsupported credential type", status=400)

            # Store the encrypted credentials
            credential.set_credentials(credentials_data)

            # Return the entire settings page with updated context
            context = self.get_project_context(object_id, project)
            context["credentials"] = credential.get_credentials()
            context["credential_type"] = credential.credential_type
            if credential.credential_type == Credentials.CredentialTypes.ZOOM_OAUTH:
                return render(request, "projects/partials/zoom_credentials.html", context)
            elif credential.credential_type == Credentials.CredentialTypes.DEEPGRAM:
                return render(request, "projects/partials/deepgram_credentials.html", context)
            elif credential.credential_type == Credentials.CredentialTypes.GOOGLE_TTS:
                return render(request, "projects/partials/google_tts_credentials.html", context)
            else:
                return HttpResponse("Cannot render the partial for this credential type", status=400)

        except Exception as e:
            return HttpResponse(str(e), status=400)


class ProjectSettingsView(LoginRequiredMixin, ProjectUrlContextMixin, View):
    def get(self, request, object_id):
        project = get_object_or_404(Project, object_id=object_id, organization=request.user.organization)

        # Try to get existing credentials
        zoom_credentials = Credentials.objects.filter(project=project, credential_type=Credentials.CredentialTypes.ZOOM_OAUTH).first()

        deepgram_credentials = Credentials.objects.filter(project=project, credential_type=Credentials.CredentialTypes.DEEPGRAM).first()

        google_tts_credentials = Credentials.objects.filter(project=project, credential_type=Credentials.CredentialTypes.GOOGLE_TTS).first()

        context = self.get_project_context(object_id, project)
        context.update(
            {
                "zoom_credentials": zoom_credentials.get_credentials() if zoom_credentials else None,
                "zoom_credential_type": Credentials.CredentialTypes.ZOOM_OAUTH,
                "deepgram_credentials": deepgram_credentials.get_credentials() if deepgram_credentials else None,
                "deepgram_credential_type": Credentials.CredentialTypes.DEEPGRAM,
                "google_tts_credentials": google_tts_credentials.get_credentials() if google_tts_credentials else None,
                "google_tts_credential_type": Credentials.CredentialTypes.GOOGLE_TTS,
            }
        )

        return render(request, "projects/project_settings.html", context)


class ProjectBotsView(LoginRequiredMixin, ProjectUrlContextMixin, View):
    def get(self, request, object_id):
        project = get_object_or_404(Project, object_id=object_id, organization=request.user.organization)

        bots = Bot.objects.filter(project=project).order_by("-created_at")

        context = self.get_project_context(object_id, project)
        context.update(
            {
                "bots": bots,
                "BotStates": BotStates,
            }
        )

        return render(request, "projects/project_bots.html", context)


class ProjectBotDetailView(LoginRequiredMixin, ProjectUrlContextMixin, View):
    def get(self, request, object_id, bot_object_id):
        project = get_object_or_404(Project, object_id=object_id, organization=request.user.organization)

        bot = get_object_or_404(Bot, object_id=bot_object_id, project=project)

        # Prefetch recordings with their utterances and participants
        bot.recordings.all().prefetch_related(models.Prefetch("utterances", queryset=Utterance.objects.select_related("participant")))

        # Prefetch bot events with their debug screenshots
        bot.bot_events.prefetch_related("debug_screenshots")

        context = self.get_project_context(object_id, project)
        context.update(
            {
                "bot": bot,
                "BotStates": BotStates,
                "RecordingStates": RecordingStates,
                "recordings": generate_recordings_json_for_bot_detail_view(bot),
            }
        )

        return render(request, "projects/project_bot_detail.html", context)


class CreateBotView(LoginRequiredMixin, ProjectUrlContextMixin, View):
    def get(self, request, object_id):
        project = get_object_or_404(Project, object_id=object_id, organization=request.user.organization)

        class BotCreateForm(forms.Form):
            meeting_url = forms.URLField(required=True, label="Meeting URL", help_text="The URL of the meeting to join (Zoom, Google Meet, MS Teams)")
            bot_name = forms.CharField(required=False, label="Bot Name", initial="Meeting Bot", help_text="A friendly name for this bot")

        context = self.get_project_context(object_id, project)
        context["form"] = BotCreateForm()
        context["title"] = "Create Bot to Join Meeting"

        return render(request, "projects/project_create_bot.html", context)

    def post(self, request, object_id):
        project = get_object_or_404(Project, object_id=object_id, organization=request.user.organization)

        class BotCreateForm(forms.Form):
            meeting_url = forms.URLField(required=True, label="Meeting URL", help_text="The URL of the meeting to join (Zoom, Google Meet, MS Teams)")
            bot_name = forms.CharField(required=False, label="Bot Name", initial="Meeting Bot", help_text="A friendly name for this bot")

        form = BotCreateForm(request.POST)
        if form.is_valid():
            try:
                # Get form data
                meeting_url = form.cleaned_data["meeting_url"]
                bot_name = form.cleaned_data.get("bot_name") or "Meeting Bot"
                recording_format = "webm"  # Default to webm format

                # Create bot settings
                settings = {
                    "transcription_settings": {"deepgram": {"language": "en"}},
                    "recording_settings": {"format": recording_format},
                }

                # Create the Bot
                bot = Bot.objects.create(project=project, meeting_url=meeting_url, name=bot_name, settings=settings)

                # Create a recording
                Recording.objects.create(
                    bot=bot,
                    recording_type=RecordingTypes.AUDIO_AND_VIDEO,
                    transcription_type=TranscriptionTypes.NON_REALTIME,
                    transcription_provider=TranscriptionProviders.DEEPGRAM,
                    is_default_recording=True,
                )

                # Transition state from READY to JOINING
                BotEventManager.create_event(bot, BotEventTypes.JOIN_REQUESTED)

                # Launch the bot
                launch_bot(bot)

                messages.success(request, f"Bot created successfully and is joining the meeting. Bot ID: {bot.object_id}")
                return redirect("projects:project-bots", object_id=project.object_id)

            except Exception as e:
                messages.error(request, f"Error creating bot: {str(e)}")
        else:
            messages.error(request, "Please correct the errors below.")

        context = self.get_project_context(object_id, project)
        context["form"] = form
        context["title"] = "Create Bot to Join Meeting"

        return render(request, "projects/project_create_bot.html", context)
