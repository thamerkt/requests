from rest_framework import serializers
from .models import RentalRequest

class RentalRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalRequest
        fields = '__all__'
    
