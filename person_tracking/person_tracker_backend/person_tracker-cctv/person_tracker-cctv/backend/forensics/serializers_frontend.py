from rest_framework import serializers
from django.contrib.auth.models import User
from .models_frontend import UserSettings, SystemActivity

class UserSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSettings
        fields = '__all__'

class UserSerializer(serializers.ModelSerializer):
    settings = UserSettingsSerializer(read_only=True)
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active', 'settings']

class SystemActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemActivity
        fields = '__all__'
