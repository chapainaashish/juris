from django.contrib import admin
from django.utils.html import format_html

from .models import (
    LawyerCategory,
    LawyerOffering,
    LawyerProfile,
    LawyerSubcategory,
    OfferingType,
)


# Inline admin for OfferingType (Service Types)
class OfferingTypeInline(admin.TabularInline):
    model = OfferingType
    extra = 1
    fields = ["type", "is_active"]
    readonly_fields = []


@admin.register(LawyerCategory)
class LawyerCategoryAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "description",
        "subcategory_count",
        "profile_count",
        "created_at",
    ]
    list_filter = ["created_at"]
    search_fields = ["title", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]

    def subcategory_count(self, obj):
        return obj.subcategories.count()

    subcategory_count.short_description = "Subcategories"

    def profile_count(self, obj):
        return obj.lawyer_profiles.count()

    profile_count.short_description = "Lawyer Profiles"


@admin.register(LawyerSubcategory)
class LawyerSubcategoryAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "lawyercategory",
        "description",
        "profile_count",
        "created_at",
    ]
    list_filter = ["lawyercategory", "created_at"]
    search_fields = ["title", "description", "lawyercategory__title"]
    readonly_fields = ["id", "created_at", "updated_at"]

    def profile_count(self, obj):
        return obj.lawyer_profiles.count()

    profile_count.short_description = "Lawyer Profiles"


@admin.register(LawyerProfile)
class LawyerProfileAdmin(admin.ModelAdmin):
    list_display = [
        "business_name",
        "registration_number",
        "kyc_verification_status",
        "legal_verified",  # Add to list display
        "categories_display",
        "subcategories_display",
        "average_rating",
        "commission_percentage",
        "created_at",
    ]
    list_filter = [
        "kyc_verification_status",
        "legal_verified",  # Add to filters
        "lawyercategories",
        "lawyersubcategories",
        "created_at",
        "cancellation_threshold_hours",
    ]
    search_fields = [
        "vendor_profile__business_name",
        "registration_number",
        "fiscal_code",
        "vendor_profile__user__email",
        "vendor_profile__user__first_name",
        "vendor_profile__user__last_name",
    ]
    readonly_fields = [
        "id",
        "average_rating",
        "review_count",
        "legal_verified",  # Make read-only
        "created_at",
        "updated_at",
    ]
    filter_horizontal = ["lawyercategories", "lawyersubcategories"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("vendor_profile", "registration_number", "fiscal_code")},
        ),
        (
            "Categorization",
            {"fields": ("lawyercategories", "lawyersubcategories")},
        ),
        (
            "Verification & Settings",
            {
                "fields": (
                    "kyc_verification_status",
                    "legal_verified",
                    "cancellation_threshold_hours",
                    "commission_percentage",
                    "default_pricing_plan",
                )
            },
        ),
        (
            "Statistics",
            {"fields": ("average_rating", "review_count"), "classes": ("collapse",)},
        ),
        (
            "Timestamps",
            {"fields": ("id", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def business_name(self, obj):
        return obj.vendor_profile.business_name if obj.vendor_profile else "N/A"

    business_name.short_description = "Business Name"
    business_name.admin_order_field = "vendor_profile__business_name"

    def categories_display(self, obj):
        categories = obj.lawyercategories.all()
        if categories:
            category_list = [cat.title for cat in categories]
            return format_html(
                '<span style="color: #0066cc;">{}</span>', ", ".join(category_list)
            )
        return "No categories"

    categories_display.short_description = "Categories"

    def subcategories_display(self, obj):
        subcategories = obj.lawyersubcategories.all()
        if subcategories:
            subcat_list = [
                f"{subcat.title} ({subcat.lawyercategory.title})"
                for subcat in subcategories
            ]
            return format_html(
                '<span style="color: #009900;">{}</span>', ", ".join(subcat_list)
            )
        return "No subcategories"

    subcategories_display.short_description = "Subcategories"

    # Custom method to display legal_verified with icon
    def legal_verified_display(self, obj):
        if obj.legal_verified:
            return format_html('<span style="color: #28a745;">✓ Verified</span>')
        else:
            return format_html('<span style="color: #dc3545;">✗ Not Verified</span>')

    legal_verified_display.short_description = "Legal Verification"
    legal_verified_display.admin_order_field = "legal_verified"

    actions = [
        "verify_profiles",
        "reject_profiles",
        "set_pending",
        "set_legal_verified",
        "unset_legal_verified",
    ]

    def verify_profiles(self, request, queryset):
        updated = queryset.update(kyc_verification_status="verified")
        self.message_user(request, f"{updated} profiles were successfully verified.")

    verify_profiles.short_description = "Verify selected profiles"

    def reject_profiles(self, request, queryset):
        updated = queryset.update(kyc_verification_status="rejected")
        self.message_user(request, f"{updated} profiles were rejected.")

    reject_profiles.short_description = "Reject selected profiles"

    def set_pending(self, request, queryset):
        updated = queryset.update(kyc_verification_status="pending")
        self.message_user(request, f"{updated} profiles were set to pending.")

    set_pending.short_description = "Set selected profiles to pending"

    def set_legal_verified(self, request, queryset):
        updated = queryset.update(legal_verified=True)
        self.message_user(
            request, f"{updated} profiles were marked as legally verified."
        )

    set_legal_verified.short_description = "✅ Mark as legally verified"

    def unset_legal_verified(self, request, queryset):
        updated = queryset.update(legal_verified=False)
        self.message_user(
            request, f"{updated} profiles were marked as not legally verified."
        )

    unset_legal_verified.short_description = "❌ Remove legal verification"


@admin.register(LawyerOffering)
class LawyerOfferingAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "lawyer_business_name",
        "price_per_30min",
        "price_display",
        "service_types_count",
        "is_active",
        "created_at",
    ]
    list_filter = [
        "is_active",
        "lawyer_profile__lawyercategories",
        "lawyer_profile__kyc_verification_status",
        "created_at",
    ]
    search_fields = [
        "name",
        "lawyer_profile__vendor_profile__business_name",
        "lawyer_profile__registration_number",
    ]
    readonly_fields = [
        "id",
        "min_price",
        "max_price",
        "created_at",
        "updated_at",
    ]
    inlines = [OfferingTypeInline]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("lawyer_profile", "name", "price_per_30min")},
        ),
        (
            "Pricing Info",
            {"fields": ("min_price", "max_price"), "classes": ("collapse",)},
        ),
        ("Availability", {"fields": ("is_active",)}),
        (
            "Timestamps",
            {"fields": ("id", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def lawyer_business_name(self, obj):
        if obj.lawyer_profile and obj.lawyer_profile.vendor_profile:
            return obj.lawyer_profile.vendor_profile.business_name
        return "N/A"

    lawyer_business_name.short_description = "Lawyer Business"
    lawyer_business_name.admin_order_field = (
        "lawyer_profile__vendor_profile__business_name"
    )

    def price_display(self, obj):
        return f"{obj.price_per_30min} USD / 30min"

    price_display.short_description = "Base Price"

    def service_types_count(self, obj):
        active_count = obj.offering_types.filter(is_active=True).count()
        total_count = obj.offering_types.count()
        return f"{active_count}/{total_count} active"

    service_types_count.short_description = "Service Types"

    actions = ["activate_offerings", "deactivate_offerings"]

    def activate_offerings(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request, f"{updated} pricing plans were successfully activated."
        )

    activate_offerings.short_description = "✅ Activate selected pricing plans"

    def deactivate_offerings(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request, f"{updated} pricing plans were successfully deactivated."
        )

    deactivate_offerings.short_description = "❌ Deactivate selected pricing plans"


@admin.register(OfferingType)
class OfferingTypeAdmin(admin.ModelAdmin):
    list_display = [
        "offering_name",
        "lawyer_business_name",
        "type",
        "type_display_name",
        "price_30min",
        "price_60min",
        "is_free",
        "is_active",
        "created_at",
    ]
    list_filter = [
        "type",
        "is_active",
        "offering__is_active",
        "created_at",
    ]
    search_fields = [
        "offering__name",
        "offering__lawyer_profile__vendor_profile__business_name",
        "type",
    ]
    readonly_fields = ["id", "created_at", "updated_at"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("offering", "type", "is_active")},
        ),
        (
            "Timestamps",
            {"fields": ("id", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def offering_name(self, obj):
        return obj.offering.name if obj.offering else "N/A"

    offering_name.short_description = "Pricing Plan"
    offering_name.admin_order_field = "offering__name"

    def lawyer_business_name(self, obj):
        if obj.offering and obj.offering.lawyer_profile:
            return obj.offering.lawyer_profile.vendor_profile.business_name
        return "N/A"

    lawyer_business_name.short_description = "Lawyer Business"
    lawyer_business_name.admin_order_field = (
        "offering__lawyer_profile__vendor_profile__business_name"
    )

    def type_display_name(self, obj):
        return obj.get_type_display()

    type_display_name.short_description = "Service Type"

    def price_30min(self, obj):
        price = obj.get_price_for_duration(30)
        if price == 0:
            return format_html('<span style="color: #198754;">FREE</span>')
        return f"{price} USD"

    price_30min.short_description = "Price (30min)"

    def price_60min(self, obj):
        price = obj.get_price_for_duration(60)
        if price == 0:
            return format_html('<span style="color: #198754;">FREE</span>')
        return f"{price} USD"

    price_60min.short_description = "Price (60min)"

    def is_free(self, obj):
        return obj.is_free_service

    is_free.short_description = "Free Service"
    is_free.boolean = True

    actions = ["activate_types", "deactivate_types"]

    def activate_types(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request, f"{updated} service types were successfully activated."
        )

    activate_types.short_description = "✅ Activate selected service types"

    def deactivate_types(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request, f"{updated} service types were successfully deactivated."
        )

    deactivate_types.short_description = "❌ Deactivate selected service types"


# Inline admin for better management
class LawyerOfferingInline(admin.TabularInline):
    model = LawyerOffering
    extra = 0
    fields = ["name", "price_per_30min", "is_active"]
    readonly_fields = []


# Add inline to LawyerProfile
LawyerProfileAdmin.inlines = [LawyerOfferingInline]


# Customize admin site header
admin.site.site_header = "Lawyer Pricing Management"
admin.site.site_title = "Lawyer Admin"
admin.site.index_title = "Welcome to Lawyer Pricing Administration"
