from django.db import models

class RentalRequest(models.Model):
    equipment = models.IntegerField(null=True, blank=True)
    rental = models.CharField(max_length=255,null=True, blank=True)
    client = models.CharField(max_length=255,null=True)  
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    quantity = models.IntegerField(null=True, blank=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=[("pending", "Pending"), ("confirmed", "Confirmed"), ("canceled", "Canceled")],
        default="pending"
    )

    def place_reservation(self):
        """Method to place a reservation"""
        # Only set status to "pending" if it is not already "pending"
        if self.status != "pending":
            self.status = "pending"
            self.save()

    def confirm(self):
        """Method to confirm the reservation"""
        # Confirm only if the status is "pending"
        if self.status == "pending":
            self.status = "confirmed"
            self.save()

    def cancel(self):
        """Method to cancel the reservation"""
        # Cancel only if it's not already canceled
        if self.status != "canceled":
            self.status = "canceled"
            self.save()

    def __str__(self):
        return f"RentalRequest {self.id} - {self.status} for Client {self.client}"
