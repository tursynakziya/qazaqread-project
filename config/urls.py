from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]

handler403 = "core.views.error_403"
handler404 = "core.views.error_404"

# Recordings are served through core.views.session_audio (with access checks),
# so MEDIA_URL is deliberately not exposed here.
if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()
