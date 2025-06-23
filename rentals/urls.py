from django.urls import path, include
from .views import RentalRequestViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'rental_requests', RentalRequestViewSet, basename='rental_request')

urlpatterns = [
    path('', include(router.urls)), 
]
