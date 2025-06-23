import json
import pika
import httpx
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from .models import RentalRequest
from .serializers import RentalRequestSerializer
from django.core.cache import cache
from django.conf import settings
import requests

def get_keycloak_admin_token():
    cache_key = "keycloak_admin_token"
    token = cache.get(cache_key)
    if token:
        return token

    url = f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
    data = {
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
        "username": settings.KEYCLOAK_ADMIN_USERNAME,
        "password": settings.KEYCLOAK_ADMIN_PASSWORD,
        "grant_type": "password"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(url, data=data, headers=headers)
    if response.ok:
        token = response.json().get("access_token")
        cache.set(cache_key, token, timeout=300)
        return token

    raise Exception(f"[Token Error] {response.status_code}: {response.text}")

# RabbitMQ connection setup
def get_rabbitmq_channel():
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host='host.docker.internal',  # Use Docker's host bridge or service name
            port=5672,
            heartbeat=600,
            blocked_connection_timeout=300
        )
    )
    channel = connection.channel()
    channel.queue_declare(queue='generate_contract', durable=True)
    return connection, channel

class RentalRequestViewSet(viewsets.ModelViewSet):
    serializer_class = RentalRequestSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = RentalRequest.objects.all()
        client_id = self.request.query_params.get("client")
        rental_id = self.request.query_params.get("rental")
        equipment_id = self.request.query_params.get("equipment")

        if client_id:
            queryset = queryset.filter(client=client_id)
        if rental_id:
            queryset = queryset.filter(rental=rental_id)
        if equipment_id:
            queryset = queryset.filter(equipment=equipment_id)

        return queryset

    

    @action(detail=True, methods=['post'])
    def place_reservation(self, request, pk=None):
        try:
            request_obj = self.get_object()
            if request_obj.status != 'pending':
                return Response({"message": "Reservation already placed or not allowed."}, status=status.HTTP_400_BAD_REQUEST)
            request_obj.place_reservation()
            return Response({"message": "Reservation placed", "status": request_obj.status}, status=status.HTTP_200_OK)
        except RentalRequest.DoesNotExist:
            return Response({"message": "Rental request not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        try:
            request_obj = self.get_object()
            if request_obj.status == 'confirmed':
                return Response({"message": "Already confirmed."}, status=status.HTTP_400_BAD_REQUEST)

            request_obj.confirm()

            # Fetch email using rental (keycloak_id)
            keycloak_id = request_obj.client
            print("keycloak_id",keycloak_id)
            user_info = self.get_user_info_httpx(keycloak_id)
            if user_info is None or 'email' not in user_info:
                return Response({"message": f"Could not fetch email for rental keycloak_id {keycloak_id}"}, status=status.HTTP_400_BAD_REQUEST)

            email = user_info['email']
            event_type = 'rental.confirmed'
            message = {
                'event': event_type,
                'payload': {
                    'email': email,
                    'rental_request_id': request_obj.id,
                    'status': request_obj.status,
                    'user':keycloak_id
                }
            }

            connection, channel = get_rabbitmq_channel()
            channel.basic_publish(
                exchange='',
                routing_key='generate_contract',
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            connection.close()

            return Response({"message": f"Confirmed and event published for {email}", "status": request_obj.status}, status=status.HTTP_200_OK)
        except RentalRequest.DoesNotExist:
            return Response({"message": "Rental request not found"}, status=status.HTTP_404_NOT_FOUND)
    def get_user_info_httpx(self, keycloak_id):
        url = f"http://192.168.1.120:8000/user/user-details/{keycloak_id}/"
        try:
            token = get_keycloak_admin_token()
            headers = {"Authorization": f"Bearer {token}"}

            with httpx.Client(timeout=5) as client:
                response = client.get(url, headers=headers)
                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"Failed to get user info from API: {response.status_code} - {response.text}")
                    return None
        except httpx.RequestError as e:
            print(f"HTTPX request error: {e}")
            return None
        except Exception as e:
            print(f"Token retrieval or request failed: {e}")
            return None
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        try:
            request_obj = self.get_object()
            if request_obj.status == 'canceled':
                return Response({"message": "Already canceled."}, status=status.HTTP_400_BAD_REQUEST)

            request_obj.cancel()

            # Fetch email using client (keycloak_id)
            keycloak_id = request_obj.client
            user_info = self.get_user_info_httpx(keycloak_id)
            if user_info is None or 'email' not in user_info:
                return Response({"message": f"Could not fetch email for client keycloak_id {keycloak_id}"}, status=status.HTTP_400_BAD_REQUEST)

            email = user_info['email']
            event_type = 'rental.canceled'
            message = {
                'event': event_type,
                'payload': {
                    'email': email,
                    'rental_request_id': request_obj.id,
                    'status': request_obj.status,
                    'user':keycloak_id
                }
            }

            connection, channel = get_rabbitmq_channel()
            channel.basic_publish(
                exchange='',
                routing_key='generate_contract',
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            connection.close()

            return Response({"message": f"Canceled and event published for {email}", "status": request_obj.status}, status=status.HTTP_200_OK)
        except RentalRequest.DoesNotExist:
            return Response({"message": "Rental request not found"}, status=status.HTTP_404_NOT_FOUND)
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a rental request, notify user via RabbitMQ and email."""
        try:
            request_obj = self.get_object()

            if request_obj.status == 'active':
                return Response({"message": "Already active."}, status=status.HTTP_400_BAD_REQUEST)

            # Update status to active
            request_obj.status = 'active'
            request_obj.save()

            # Fetch email using client (Keycloak ID)
            keycloak_id = request_obj.client
            user_info = self.get_user_info_httpx(keycloak_id)
            if user_info is None or 'email' not in user_info:
                return Response(
                    {"message": f"Could not fetch email for client keycloak_id {keycloak_id}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            email = user_info['email']
            event_type = 'rental.activated'
            message = {
                'event': event_type,
                'payload': {
                    'email': email,
                    'rental_request_id': request_obj.id,
                    'status': request_obj.status,
                    'user': keycloak_id
                }
            }

            # Send to RabbitMQ
            connection, channel = get_rabbitmq_channel()
            channel.basic_publish(
                exchange='',
                routing_key='generate_contract',
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            connection.close()

            return Response(
                {"message": f"Activated and event published for {email}", "status": request_obj.status},
                status=status.HTTP_200_OK
            )

        except RentalRequest.DoesNotExist:
            return Response({"message": "Rental request not found"}, status=status.HTTP_404_NOT_FOUND)