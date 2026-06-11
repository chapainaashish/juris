import stripe
from django.conf import settings
from django.core.management.base import BaseCommand

from profiles.models import Category
from subscriptions.models import SubscriptionPlan

# Configure Stripe API key
stripe.api_key = settings.STRIPE_SECRET_KEY


class Command(BaseCommand):
    help = "Create Stripe products and prices for subscription plans"

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("Setting up Stripe products and prices...")
        )

        # Get all categories
        categories = Category.objects.all()

        for category in categories:
            self.stdout.write(f"Processing category: {category.name}")

            # Check if a plan already exists for this category
            plan = SubscriptionPlan.objects.filter(category=category).first()

            if plan and plan.stripe_price_id.startswith("price_"):
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Plan for {category.name} already has a valid Stripe price ID: {plan.stripe_price_id}"
                    )
                )
                continue

            # Create or update the plan
            if not plan:
                plan = SubscriptionPlan(
                    category=category,
                    name=f"{category.name} Basic Plan",
                    description=f"Standard plan for {category.name.lower()}s with profile listing, client management, and basic analytics.",
                )

                # Set price based on category
                if category.name == Category.LAWYER:
                    plan.price_monthly = 199.00
                elif category.name == Category.NOTARY:
                    plan.price_monthly = 149.00
                elif category.name == Category.ACCOUNTANT:
                    plan.price_monthly = 179.00
                elif category.name == Category.TRANSLATOR:
                    plan.price_monthly = 99.00
                else:
                    plan.price_monthly = 149.00

            # Create Stripe product
            try:
                # Check if we have an existing product ID to reuse
                if hasattr(plan, "stripe_product_id") and plan.stripe_product_id:
                    product = stripe.Product.retrieve(plan.stripe_product_id)
                    self.stdout.write(f"Using existing Stripe product: {product.id}")
                else:
                    # Create new product
                    product = stripe.Product.create(
                        name=plan.name,
                        description=plan.description,
                        metadata={
                            "category": category.name,
                            "category_id": category.id,
                        },
                    )
                    self.stdout.write(f"Created Stripe product: {product.id}")

                # Create price for the product (in USD)
                price = stripe.Price.create(
                    product=product.id,
                    unit_amount=int(plan.price_monthly * 100),  # Convert to cents
                    currency=settings.STRIPE_CURRENCY,
                    recurring={"interval": "month"},
                    metadata={"category": category.name, "category_id": category.id},
                )

                # Update the plan with the Stripe IDs
                plan.stripe_price_id = price.id
                if not hasattr(plan, "stripe_product_id") or not plan.stripe_product_id:
                    plan.stripe_product_id = product.id

                plan.is_active = True
                plan.save()

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully created Stripe price {price.id} for {category.name}"
                    )
                )

            except stripe.error.StripeError as e:
                self.stdout.write(
                    self.style.ERROR(f"Stripe error for {category.name}: {str(e)}")
                )

        self.stdout.write(self.style.SUCCESS("Stripe setup completed"))
