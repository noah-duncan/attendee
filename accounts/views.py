from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from bots.models import Project
from django.http import Http404

@login_required
def home(request):
    # Get the first bot for the user's organization
    project = Project.objects.filter(organization=request.user.organization).first()
    if not project:
        project = Project.objects.create(
            name=f"{request.user.email}'s first project",
            organization=request.user.organization
        )
    if project:
        return redirect('projects:project-dashboard', object_id=project.object_id)
    raise Http404("No projects found for this organization. You need to create a project first.")