from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('forensics.urls')),
    path('api/', include('forensics.urls')), # This links to your app's urls
]

# This allows the browser to view the uploaded/processed videos
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Also allow Django to find your static files (CSS/JS) easily
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)