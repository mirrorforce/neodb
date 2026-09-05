import time

import pytz
from django.contrib.sessions.middleware import SessionMiddleware
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from pytz.tzinfo import BaseTzInfo
from tz_detect.utils import offset_to_timezone


class APIAwareSessionMiddleware(SessionMiddleware):
    """
    SessionMiddleware that reads, but never persists, API request sessions.

    Native Product APIs can use the existing first-party Django session for
    authentication. API requests remain read-only with respect to the session
    store, so an API response cannot unexpectedly create or mutate a browser
    session.
    """

    def process_request(self, request):
        super().process_request(request)

    def process_response(self, request, response):
        if request.path.startswith("/api/"):
            return response
        return super().process_response(request, response)


class SiteConfigMiddleware:
    """
    Periodically refreshes SiteConfig from the database and writes
    values back to django.conf.settings for backward compatibility.
    """

    refresh_interval: float = 30.0

    def __init__(self, get_response):
        self.get_response = get_response
        self.config_ts: float = 0.0

    def __call__(self, request):
        from common.models import SiteConfig

        if not getattr(SiteConfig, "__forced__", False):
            now = time.monotonic()
            if (
                not getattr(SiteConfig, "system", None)
                or (now - self.config_ts) >= self.refresh_interval
            ):
                SiteConfig.system = SiteConfig.load_system()
                self.config_ts = now
                SiteConfig._apply_to_settings(SiteConfig.system)
        return self.get_response(request)


class SafeTimezoneMiddleware(MiddlewareMixin):
    """Drop-in replacement for tz_detect.middleware.TimezoneMiddleware.

    Handles invalid timezone strings (e.g. 'Etc/GMT 8') gracefully instead
    of crashing with UnknownTimeZoneError. The tz_detect app is still needed
    for JS-based detection and the detected_tz session key.
    """

    def process_request(self, request):
        tz = request.session.get("detected_tz")
        if tz:
            try:
                if isinstance(tz, BaseTzInfo):
                    timezone.activate(tz)
                elif isinstance(tz, str):
                    timezone.activate(pytz.timezone(tz))
                else:
                    timezone.activate(offset_to_timezone(tz))
                request.timezone_active = True
            except Exception:
                request.session.pop("detected_tz", None)
                timezone.deactivate()
        else:
            timezone.deactivate()


class IdentityMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.identity = None
        if hasattr(request, "user") and request.user.is_authenticated:
            from users.models import APIdentity

            try:
                request.identity = APIdentity.objects.get(user=request.user)
            except APIdentity.DoesNotExist:
                pass
