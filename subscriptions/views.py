from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from django.utils import timezone
import stripe
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    Notification,
    PaymentMethod,
    SubscriptionInvoice,
    SubscriptionPlan,
    VendorSubscription,
    Voucher,
    VoucherUsage,
)
from .notification_utils import (
    send_subscription_activated_notification,
    send_subscription_canceled_notification,
)
from .redis_utils import (
    set_card_info,
    set_days_left,
    set_has_card,
    set_payment_method_id,
    set_subscription_status,
)
from .serializers import (
    NotificationSerializer,
    PaymentMethodSerializer,
    SubscriptionActivateSerializer,
    SubscriptionInvoiceSerializer,
    SubscriptionPlanSerializer,
    VendorSubscriptionSerializer,
    VoucherValidateSerializer,
)
from .stripe_utils import (
    activate_subscription,
    cancel_subscription,
    create_setup_intent,
    create_stripe_customer,
    create_trial_subscription,
    get_payment_method_details,
)


class IsVendor(permissions.BasePermission):
    """Permission to only allow vendors to access their own subscription"""

    def has_permission(self, request, view):
        return hasattr(request.user, "vendorprofile")


class SubscriptionPlanViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for viewing subscription plans"""

    queryset = SubscriptionPlan.objects.filter(is_active=True)
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.queryset


class VendorSubscriptionView(generics.RetrieveAPIView):
    """API endpoint for managing a vendor's subscription"""

    serializer_class = VendorSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated, IsVendor]

    def get_object(self):
        """Get the vendor's subscription"""
        try:
            vendor = self.request.user.vendorprofile
            return VendorSubscription.objects.get(vendor=vendor)
        except VendorSubscription.DoesNotExist:
            raise Http404("You don't have an active subscription")


class InitTrialView(generics.CreateAPIView):
    """API endpoint to initialize a trial subscription"""

    permission_classes = [permissions.IsAuthenticated, IsVendor]

    def post(self, request, *args, **kwargs):
        vendor = request.user.vendorprofile

        # Check if vendor already has a subscription
        if hasattr(vendor, "subscription"):
            return Response(
                {"error": "Vendor already has a subscription"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if vendor profile is complete
        if not vendor.is_completed:
            return Response(
                {"error": "Vendor profile must be completed first"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if the vendor's category has a subscription plan
        try:
            plan = SubscriptionPlan.objects.get(
                category=vendor.category, is_active=True
            )
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {"error": "No subscription plan found for this vendor category"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create Stripe customer
        with transaction.atomic():
            customer_id = create_stripe_customer(vendor)

            # Create trial subscription in Stripe
            stripe_sub, trial_end = create_trial_subscription(vendor, customer_id)

            # Create local subscription record
            subscription = VendorSubscription.objects.create(
                vendor=vendor,
                plan=plan,
                stripe_customer_id=customer_id,
                stripe_subscription_id=stripe_sub.id,
                trial_ends_at=trial_end,
                status="trialing",
            )

            # Cache trial days left
            days_left = (trial_end - now()).days
            set_days_left(vendor.id, days_left)
            set_subscription_status(vendor.id, "trialing")

            # Return the subscription data
            serializer = VendorSubscriptionSerializer(subscription)
            return Response(serializer.data, status=status.HTTP_201_CREATED)


class SubscriptionActivateView(generics.UpdateAPIView):
    """API endpoint to activate a subscription after trial"""

    serializer_class = SubscriptionActivateSerializer
    permission_classes = [permissions.IsAuthenticated, IsVendor]

    def get_object(self):
        """Get the vendor's subscription"""
        vendor = self.request.user.vendorprofile
        return VendorSubscription.objects.get(vendor=vendor)

    def update(self, request, *args, **kwargs):
        subscription = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment_method_id = serializer.validated_data["payment_method_id"]
        voucher_code = serializer.validated_data.get("voucher_code")

        voucher = None
        if voucher_code:
            # Check if voucher is valid
            voucher = Voucher.objects.get(
                code=voucher_code,
                is_active=True,
                expires_at__gt=now(),
            )
            if voucher.used_count >= voucher.usage_limit:
                return Response(
                    {"error": "Voucher usage limit exceeded"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        with transaction.atomic():
            # Activate the subscription in Stripe
            stripe_subscription = activate_subscription(
                subscription, payment_method_id, voucher
            )

            # Get payment method details
            payment_details = get_payment_method_details(payment_method_id)

            # Create payment method record
            payment_method = PaymentMethod.objects.create(
                vendor=subscription.vendor,
                stripe_payment_method_id=payment_method_id,
                card_brand=payment_details["card_brand"],
                last4=payment_details["last4"],
                exp_month=payment_details["exp_month"],
                exp_year=payment_details["exp_year"],
                is_default=True,
            )

            # Update subscription record
            subscription.status = stripe_subscription.status

            # Fix datetime handling with timezone awareness
            from datetime import datetime
            from django.utils.timezone import make_aware

            if stripe_subscription.trial_end:
                if isinstance(stripe_subscription.trial_end, (int, float)):
                    # Convert timestamp to timezone-aware datetime
                    naive_dt = datetime.fromtimestamp(stripe_subscription.trial_end)
                    subscription.trial_ends_at = make_aware(naive_dt)
                else:
                    # Ensure the datetime is timezone-aware
                    if stripe_subscription.trial_end.tzinfo is None:
                        subscription.trial_ends_at = make_aware(
                            stripe_subscription.trial_end
                        )
                    else:
                        subscription.trial_ends_at = stripe_subscription.trial_end
            else:
                subscription.trial_ends_at = None

            if stripe_subscription.current_period_end:
                if isinstance(stripe_subscription.current_period_end, (int, float)):
                    # Convert timestamp to timezone-aware datetime
                    naive_dt = datetime.fromtimestamp(
                        stripe_subscription.current_period_end
                    )
                    subscription.current_period_end = make_aware(naive_dt)
                else:
                    # Ensure the datetime is timezone-aware
                    if stripe_subscription.current_period_end.tzinfo is None:
                        subscription.current_period_end = make_aware(
                            stripe_subscription.current_period_end
                        )
                    else:
                        subscription.current_period_end = (
                            stripe_subscription.current_period_end
                        )

            # Record voucher usage
            if voucher:
                subscription.voucher = voucher
                voucher.used_count += 1
                voucher.save()

            subscription.save()

            # Update Redis cache
            set_subscription_status(subscription.vendor.id, subscription.status)
            set_card_info(
                subscription.vendor.id,
                {
                    "brand": payment_details["card_brand"],
                    "last4": payment_details["last4"],
                    "exp_month": payment_details["exp_month"],
                    "exp_year": payment_details["exp_year"],
                },
            )
            set_has_card(subscription.vendor.id, True)
            set_payment_method_id(
                subscription.vendor.id, payment_method_id, permanent=True
            )

            # Send activation notification
            send_subscription_activated_notification(subscription)

            return Response(
                VendorSubscriptionSerializer(subscription).data,
                status=status.HTTP_200_OK,
            )

class AddPaymentMethodView(generics.GenericAPIView):
    """Add a new payment method and optionally set as default"""
    permission_classes = [permissions.IsAuthenticated, IsVendor]
    
    def post(self, request, *args, **kwargs):
        vendor = request.user.vendorprofile
        payment_method_id = request.data.get('payment_method_id')
        set_as_default = request.data.get('set_as_default', False)
        
        if not payment_method_id:
            return Response(
                {"error": "payment_method_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Check if already exists
            if PaymentMethod.objects.filter(
                vendor=vendor,
                stripe_payment_method_id=payment_method_id
            ).exists():
                return Response(
                    {"error": "Payment method already exists"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get details from Stripe
            payment_details = get_payment_method_details(payment_method_id)

            # Save to DB
            payment_method = PaymentMethod.objects.create(
                vendor=vendor,
                stripe_payment_method_id=payment_method_id,
                card_brand=payment_details["card_brand"],
                last4=payment_details["last4"],
                exp_month=payment_details["exp_month"],
                exp_year=payment_details["exp_year"],
                is_default=False
            )

            # If it needs to be the default
            if set_as_default:
                # Deactivate the others
                PaymentMethod.objects.filter(
                    vendor=vendor
                ).exclude(id=payment_method.id).update(is_default=False)

                payment_method.is_default = True
                payment_method.save()

                # Update in Stripe
                subscription = vendor.subscription
                stripe.Customer.modify(
                    subscription.stripe_customer_id,
                    invoice_settings={
                        'default_payment_method': payment_method_id
                    }
                )

                # Also update the specific Subscription in Stripe
                if subscription.stripe_subscription_id:
                    stripe.Subscription.modify(
                        subscription.stripe_subscription_id,
                        default_payment_method=payment_method_id
                    )
            
            return Response(
                PaymentMethodSerializer(payment_method).data,
                status=status.HTTP_201_CREATED
            )
            
        except stripe.error.StripeError as e:
            return Response(
                {"error": f"Stripe error: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
class SetPrimaryPaymentMethodView(generics.GenericAPIView):
    """Set an existing payment method as primary"""
    permission_classes = [permissions.IsAuthenticated, IsVendor]
    
    def post(self, request, pk=None):
        vendor = request.user.vendorprofile
        
        try:
            # Find the payment method
            payment_method = PaymentMethod.objects.get(
                id=pk, 
                vendor=vendor
            )
            
            # If already default, do nothing
            if payment_method.is_default:
                return Response(
                    {"message": "Already set as default"},
                    status=status.HTTP_200_OK
                )
            
            # Deactivate the others
            PaymentMethod.objects.filter(
                vendor=vendor
            ).update(is_default=False)

            # Activate this card
            payment_method.is_default = True
            payment_method.save()

            # Update in Stripe Customer
            subscription = vendor.subscription
            stripe.Customer.modify(
                subscription.stripe_customer_id,
                invoice_settings={
                    'default_payment_method': payment_method.stripe_payment_method_id
                }
            )
            
            return Response(
                {"success": True, "message": "Payment method set as primary"},
                status=status.HTTP_200_OK
            )
            
        except PaymentMethod.DoesNotExist:
            return Response(
                {"error": "Payment method not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except stripe.error.StripeError as e:
            return Response(
                {"error": f"Failed to update in Stripe: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

class SubscriptionCancelView(generics.UpdateAPIView):
    """API endpoint to cancel a subscription"""
    permission_classes = [permissions.IsAuthenticated, IsVendor]

    def update(self, request, *args, **kwargs):
        try:
            vendor = request.user.vendorprofile
            subscription = VendorSubscription.objects.get(vendor=vendor)

            # Cancel at period end by default
            cancel_at_period_end = request.data.get("cancel_at_period_end", True)

            with transaction.atomic():
                # Cancel in Stripe
                stripe_sub = cancel_subscription(
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=cancel_at_period_end,
                )

                # Update local record - keep status from Stripe
                subscription.status = stripe_sub.status
                subscription.canceled_at = now() if stripe_sub.cancel_at_period_end else None
                subscription.save()

                # Update cache
                set_subscription_status(vendor.id, subscription.status)

                # Send notification
                send_subscription_canceled_notification(subscription)

                return Response(
                    VendorSubscriptionSerializer(subscription).data,
                    status=status.HTTP_200_OK,
                )

        except VendorSubscription.DoesNotExist:
            return Response(
                {"error": "No active subscription found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class RetryFailedPaymentView(generics.GenericAPIView):
    """API endpoint to retry failed payment after updating payment method"""
    permission_classes = [permissions.IsAuthenticated, IsVendor]
    
    def post(self, request, *args, **kwargs):
        try:
            vendor = request.user.vendorprofile
            subscription = VendorSubscription.objects.get(vendor=vendor)
            
            # Check if past_due or unpaid
            if subscription.status not in ['past_due', 'unpaid']:
                return Response(
                    {"error": "No failed payment to retry"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Find the latest unpaid invoice
            invoices = stripe.Invoice.list(
                subscription=subscription.stripe_subscription_id,
                status='open',
                limit=1
            )
            
            if not invoices.data:
                return Response(
                    {"error": "No open invoices found"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            try:
                # Try to pay with the default payment method
                paid_invoice = stripe.Invoice.pay(invoices.data[0].id)

                # If payment succeeds, update local status
                subscription.status = 'active'
                subscription.save()

                # Update cache
                set_subscription_status(vendor.id, 'active')

                # Send success notification
                send_subscription_activated_notification(subscription)
                
                return Response({
                    "success": True,
                    "status": "active",
                    "message": "Payment successful. Your subscription is now active."
                }, status=status.HTTP_200_OK)
                
            except stripe.error.CardError as e:
                return Response({
                    "error": f"Payment failed: {str(e)}",
                    "decline_code": e.decline_code
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except VendorSubscription.DoesNotExist:
            return Response(
                {"error": "No subscription found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except stripe.error.StripeError as e:
            return Response(
                {"error": f"Stripe error: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

class SubscriptionReactivateView(generics.GenericAPIView):
    """API endpoint to reactivate a canceled subscription"""
    permission_classes = [permissions.IsAuthenticated, IsVendor]
    
    def post(self, request, *args, **kwargs):
        try:
            vendor = request.user.vendorprofile
            subscription = VendorSubscription.objects.get(vendor=vendor)
            
            # Check if canceled
            if not subscription.canceled_at:
                return Response(
                    {"error": "Subscription is not canceled"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if exists in Stripe
            if not subscription.stripe_subscription_id:
                return Response(
                    {"error": "No Stripe subscription found"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            with transaction.atomic():
                # Reactivate in Stripe
                stripe_sub = stripe.Subscription.modify(
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=False
                )
                
                # Update local record
                subscription.canceled_at = None
                subscription.status = stripe_sub.status
                subscription.save()
                
                # Update cache
                set_subscription_status(vendor.id, subscription.status)
                
                return Response(
                    VendorSubscriptionSerializer(subscription).data,
                    status=status.HTTP_200_OK
                )
                
        except VendorSubscription.DoesNotExist:
            return Response(
                {"error": "No subscription found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except stripe.error.StripeError as e:
            return Response(
                {"error": f"Stripe error: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


class PaymentMethodViewSet(viewsets.ModelViewSet):
    """API endpoint to manage payment methods"""

    serializer_class = PaymentMethodSerializer
    permission_classes = [permissions.IsAuthenticated, IsVendor]
    http_method_names = ["get", "post", "delete"]  # limit to needed methods

    def get_queryset(self):
        vendor = self.request.user.vendorprofile
        return PaymentMethod.objects.filter(vendor=vendor)

    def create(self, request, *args, **kwargs):
        vendor = request.user.vendorprofile

        # Check if vendor has a subscription
        try:
            subscription = vendor.subscription
        except VendorSubscription.DoesNotExist:
            return Response(
                {"error": "Vendor has no subscription"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create SetupIntent for adding a new card
        setup_intent = create_setup_intent(subscription.stripe_customer_id)

        return Response(
            {"client_secret": setup_intent.client_secret}, status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["delete"])
    def delete(self, request, pk=None):
        vendor = request.user.vendorprofile
        payment_method = get_object_or_404(PaymentMethod, id=pk, vendor=vendor)

        # Only allow deletion if there are other payment methods
        if PaymentMethod.objects.filter(vendor=vendor).count() <= 1:
            return Response(
                {"error": "Cannot delete the only payment method"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Delete the payment method
        payment_method.delete()

        # Clear related cache
        from .redis_utils import delete_payment_method_id

        delete_payment_method_id(vendor.id)

        return Response(status=status.HTTP_200_OK)


class SubscriptionInvoiceView(generics.ListAPIView):
    """API endpoint to list subscription invoices"""

    serializer_class = SubscriptionInvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, IsVendor]

    def get_queryset(self):
        vendor = self.request.user.vendorprofile
        try:
            subscription = vendor.subscription
            return SubscriptionInvoice.objects.filter(subscription=subscription)
        except VendorSubscription.DoesNotExist:
            return SubscriptionInvoice.objects.none()


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint to list user notifications"""

    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by(
            "-created_at"
        )

    @action(detail=True, methods=["post"])
    def mark_as_read(self, request, pk=None):
        notification = get_object_or_404(Notification, id=pk, user=request.user)
        notification.read = True
        notification.save()
        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"])
    def mark_all_as_read(self, request):
        Notification.objects.filter(user=request.user, read=False).update(read=True)
        return Response(status=status.HTTP_200_OK)


class VoucherValidateView(generics.GenericAPIView):
    """API endpoint to validate a voucher code"""

    serializer_class = VoucherValidateSerializer
    permission_classes = [permissions.IsAuthenticated, IsVendor]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        code = serializer.validated_data["code"]

        try:
            voucher = Voucher.objects.get(
                code=code,
                is_active=True,
                expires_at__gt=now(),
            )

            if voucher.used_count >= voucher.usage_limit:
                return Response(
                    {"valid": False, "message": "Voucher usage limit exceeded"},
                    status=status.HTTP_200_OK,
                )

            # Return voucher details
            return Response(
                {
                    "valid": True,
                    "voucher": {
                        "code": voucher.code,
                        "discount_type": voucher.discount_type,
                        "value": voucher.value,
                        "expires_at": voucher.expires_at,
                    },
                },
                status=status.HTTP_200_OK,
            )

        except Voucher.DoesNotExist:
            return Response(
                {"valid": False, "message": "Invalid or expired voucher code"},
                status=status.HTTP_200_OK,
            )
        
class ApplyVoucherToActiveSubscriptionView(generics.GenericAPIView):
    """API endpoint to apply voucher to active subscription"""
    permission_classes = [permissions.IsAuthenticated, IsVendor]
    serializer_class = VoucherValidateSerializer
    
    def post(self, request, *args, **kwargs):
        try:
            vendor = request.user.vendorprofile
            subscription = VendorSubscription.objects.get(vendor=vendor)
            
            # Check that subscription is active and not in trial
            if subscription.status != 'active':
                return Response(
                    {"error": "Subscription must be active"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if subscription.trial_ends_at and subscription.trial_ends_at > now():
                return Response(
                    {"error": "Cannot apply voucher during trial period"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            voucher_code = serializer.validated_data['code']

            with transaction.atomic():
                # Lock the voucher row to prevent concurrent use exceeding the limit
                try:
                    voucher = Voucher.objects.select_for_update().get(
                        code=voucher_code,
                        is_active=True,
                        expires_at__gt=now()
                    )
                except Voucher.DoesNotExist:
                    return Response(
                        {"error": "Invalid or expired voucher code"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Check email restriction
                if voucher.restricted_to_email:
                    if request.user.email != voucher.restricted_to_email:
                        return Response(
                            {"error": "This voucher is not valid for your account"},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                # Check usage limit (inside the lock)
                if voucher.used_count >= voucher.usage_limit:
                    return Response(
                        {"error": "Voucher usage limit exceeded"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Get or create Stripe coupon
                from .stripe_utils import get_or_create_stripe_coupon
                coupon = get_or_create_stripe_coupon(voucher)

                # Apply to existing subscription
                stripe_sub = stripe.Subscription.modify(
                    subscription.stripe_subscription_id,
                    discounts=[{'coupon': coupon.id}]
                )

                # Update Django records
                voucher.used_count += 1
                voucher.save()
                
                # Save reference in subscription
                subscription.voucher = voucher
                subscription.save()
                
                
                VoucherUsage.objects.create(
                     voucher=voucher,
                     subscription=subscription
                )
                
                return Response({
                    "success": True,
                    "message": f"Voucher applied successfully. {voucher.value}% discount for {voucher.duration_months} months",
                    "discount": {
                        "type": voucher.discount_type,
                        "value": voucher.value,
                        "duration_months": voucher.duration_months
                    }
                }, status=status.HTTP_200_OK)
                
        except VendorSubscription.DoesNotExist:
            return Response(
                {"error": "No subscription found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except stripe.error.StripeError as e:
            return Response(
                {"error": f"Failed to apply voucher: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )