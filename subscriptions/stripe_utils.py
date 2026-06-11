from datetime import datetime, timedelta

import stripe
from django.conf import settings
from django.utils.timezone import make_aware, now

# Configure Stripe API Key
stripe.api_key = settings.STRIPE_SECRET_KEY


def create_stripe_customer(vendor):
    """Create a new Stripe customer for a vendor"""
    customer = stripe.Customer.create(
        email=vendor.user.email,
        name=f"{vendor.user.first_name} {vendor.user.last_name}",
        metadata={
            "vendor_id": vendor.id,
            "business_name": vendor.business_name,
            "category": vendor.category.name,
        },
    )
    return customer.id


def create_trial_subscription(vendor, customer_id):
    """Create a trial subscription without payment method"""
    trial_end = now() + timedelta(days=settings.TRIAL_PERIOD_DAYS)

    # Get the appropriate price ID for this vendor's category
    plan = vendor.category.subscription_plan

    # Create the subscription with trial period
    subscription = stripe.Subscription.create(
        customer=customer_id,
        items=[{"price": plan.stripe_price_id}],
        trial_end=int(trial_end.timestamp()),
        metadata={"vendor_id": vendor.id},
    )

    return subscription, trial_end


def create_payment_intent(amount, customer_id, metadata=None):
    """Create a PaymentIntent for the subscription payment"""
    intent = stripe.PaymentIntent.create(
        amount=int(amount * 100),  # Convert to cents
        currency=settings.STRIPE_CURRENCY,
        customer=customer_id,
        metadata=metadata or {},
    )
    return intent


def create_setup_intent(customer_id):
    """Create a SetupIntent for adding payment method"""
    setup_intent = stripe.SetupIntent.create(
        customer=customer_id,
        payment_method_types=["card"],
    )
    return setup_intent


def get_or_create_stripe_coupon(voucher):
    """Reuse existing Stripe coupon or create a new one"""
    if voucher.stripe_coupon_id:
        try:
            return stripe.Coupon.retrieve(voucher.stripe_coupon_id)
        except:
            pass  # Coupon deleted in Stripe, recreate
    
    params = {'metadata': {'django_voucher_id': str(voucher.id)}}
    
    if voucher.discount_type == "percentage":
        params['percent_off'] = voucher.value
    elif voucher.discount_type == "fixed_amount":
        params['amount_off'] = voucher.value * 100  # convert to cents
        params['currency'] = settings.STRIPE_CURRENCY
    elif voucher.discount_type == "free_period":
        # Convert to 100% discount
        params['percent_off'] = 100
    
    # Duration logic
    if voucher.duration_months:
        params['duration'] = 'repeating'
        params['duration_in_months'] = voucher.duration_months
    else:
        params['duration'] = 'once'
    
    coupon = stripe.Coupon.create(**params)
    voucher.stripe_coupon_id = coupon.id
    voucher.save()
    
    return coupon


def activate_subscription(vendor_subscription, payment_method_id, voucher=None):
    """Activate a subscription after the trial period with a payment method"""
    # Get customer and subscription from Stripe
    customer_id = vendor_subscription.stripe_customer_id

    # Attach payment method to customer
    stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)

    # Set as default payment method
    stripe.Customer.modify(
        customer_id, invoice_settings={"default_payment_method": payment_method_id}
    )

    # If there's an existing subscription from trial, update it
    if vendor_subscription.stripe_subscription_id:
        # Update the existing subscription
        update_params = {
            "default_payment_method": payment_method_id,
        }
        
        # Apply voucher if provided
        if voucher:
            coupon = get_or_create_stripe_coupon(voucher)
            update_params["discounts"] = [{"coupon": coupon.id}]
        
        updated_subscription = stripe.Subscription.modify(
            vendor_subscription.stripe_subscription_id,
            **update_params
        )

        return updated_subscription
    else:
        # Create a new subscription
        plan = vendor_subscription.plan
        
        create_params = {
            "customer": customer_id,
            "items": [{"price": plan.stripe_price_id}],
            "default_payment_method": payment_method_id,
        }
        
        # Apply voucher if provided
        if voucher:
            coupon = get_or_create_stripe_coupon(voucher)
            create_params["discounts"] = [{"coupon": coupon.id}]

        new_subscription = stripe.Subscription.create(**create_params)

        return new_subscription


def cancel_subscription(subscription_id, cancel_at_period_end=True):
    """Cancel a subscription"""
    return stripe.Subscription.modify(
        subscription_id, cancel_at_period_end=cancel_at_period_end
    )


def get_payment_method_details(payment_method_id):
    """Get payment method details"""
    payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
    return {
        "card_brand": payment_method.card.brand,
        "last4": payment_method.card.last4,
        "exp_month": payment_method.card.exp_month,
        "exp_year": payment_method.card.exp_year,
    }


def get_invoice_url(invoice_id):
    """Get invoice PDF URL"""
    invoice = stripe.Invoice.retrieve(invoice_id)
    return invoice.invoice_pdf


def parse_stripe_timestamp(timestamp):
    """Convert a Stripe timestamp to a datetime object"""
    if not timestamp:
        return None
    return make_aware(datetime.fromtimestamp(timestamp))