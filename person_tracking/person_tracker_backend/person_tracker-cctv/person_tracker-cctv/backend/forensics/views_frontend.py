from rest_framework import viewsets
from django.contrib.auth.models import User
from .models_frontend import UserSettings, SystemActivity
from .serializers_frontend import UserSerializer, SystemActivitySerializer

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

class SystemActivityViewSet(viewsets.ModelViewSet):
    queryset = SystemActivity.objects.all()
    serializer_class = SystemActivitySerializer
