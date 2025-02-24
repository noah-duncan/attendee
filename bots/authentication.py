import hashlib

from rest_framework import authentication, exceptions

from .models import ApiKey


class ApiKeyAuthentication(authentication.BaseAuthentication):
    def authenticate_header(self, request):
        return "Token"

    def authenticate(self, request):
        if "Authorization" not in request.headers:
            raise exceptions.AuthenticationFailed({"detail": "Missing Authorization header"})

        auth_header = request.headers.get("Authorization", "").split()

        if not auth_header or len(auth_header) != 2 or auth_header[0].lower() != "token":
            raise exceptions.AuthenticationFailed({"detail": "Invalid Authorization header. Should have this format: Token <api_key>"})

        api_key = auth_header[1]

        try:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            api_key_obj = ApiKey.objects.select_related("project").get(key_hash=key_hash, disabled_at__isnull=True)
        except ApiKey.DoesNotExist:
            raise exceptions.AuthenticationFailed({"detail": "Invalid or disabled API key"})

        # Return (None, api_key_obj) instead of (user, auth)
        return (None, api_key_obj)
