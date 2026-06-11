from django.contrib import admin

from .models import (
    Address,
    Category,
    Certificate,
    Language,
    Media,
    ProfileCompletionSession,
    Service,
    ServiceCategory,
    VendorLegalInfo,
    VendorProfile,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ["street", "city", "postcode", "country"]
    search_fields = ["street", "city", "country"]
    list_filter = ["country"]


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ["name", "icon_url"]
    search_fields = ["name"]


class VendorLegalInfoInline(admin.StackedInline):
    model = VendorLegalInfo
    extra = 0


class MediaInline(admin.TabularInline):
    model = Media
    extra = 0
    readonly_fields = ["created_at"]


class CertificateInline(admin.TabularInline):
    model = Certificate
    extra = 0
    readonly_fields = ["created_at"]


class ServiceCategoryInline(admin.TabularInline):
    model = ServiceCategory
    extra = 0
    readonly_fields = ["created_at", "updated_at"]


@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = [
        "business_name",
        "user",
        "category",
        "is_completed",
        "social_media_status",
        "created_at",
    ]
    list_filter = ["category", "is_completed", "social_media_status", "created_at"]
    search_fields = ["business_name", "user__email", "bio", "experience"]
    inlines = [
        VendorLegalInfoInline,
        MediaInline,
        CertificateInline,
        ServiceCategoryInline,
    ]
    date_hierarchy = "created_at"
    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "user",
                    "category",
                    "business_name",
                    "address",
                    "languages",
                    "avatar_url",
                    "is_completed",
                ),
            },
        ),
        (
            "Profile Details",
            {
                "fields": ("bio", "experience"),
            },
        ),
        (
            "Website & Social Media",
            {
                "fields": (
                    "website",
                    "social_media_status",
                    "whatsapp",
                    "facebook",
                    "youtube",
                    "instagram",
                    "twitter",
                    "general_link",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )
    readonly_fields = ["created_at", "updated_at"]


@admin.register(VendorLegalInfo)
class VendorLegalInfoAdmin(admin.ModelAdmin):
    list_display = [
        "first_name_id",
        "last_name_id",
        "email",
        "bar_association",
        "vendor_profile",
    ]
    list_filter = ["bar_association"]
    search_fields = [
        "first_name_id",
        "last_name_id",
        "email",
        "vendor_profile__business_name",
    ]


@admin.register(ProfileCompletionSession)
class ProfileCompletionSessionAdmin(admin.ModelAdmin):
    list_display = ["token", "user", "is_completed", "created_at", "expires_at"]
    list_filter = ["is_completed", "created_at"]
    search_fields = ["token", "user__email", "business_name"]
    date_hierarchy = "created_at"
    readonly_fields = ["token", "created_at", "last_updated"]
    fieldsets = (
        (
            "Session Info",
            {
                "fields": (
                    "token",
                    "user",
                    "is_completed",
                    "expires_at",
                    "created_at",
                    "last_updated",
                ),
            },
        ),
        (
            "Basic Profile",
            {
                "fields": (
                    "category",
                    "business_name",
                    "address",
                    "languages",
                    "avatar_url",
                    "legal_info",
                ),
            },
        ),
        (
            "Extended Profile",
            {
                "fields": (
                    "bio",
                    "experience",
                    "website",
                    "social_media_status",
                    "whatsapp",
                    "facebook",
                    "youtube",
                    "instagram",
                    "twitter",
                    "general_link",
                ),
            },
        ),
    )


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
    list_display = ["id", "vendor_profile", "title", "file_type", "created_at"]
    list_filter = ["file_type", "created_at"]
    search_fields = ["title", "description", "vendor_profile__business_name"]
    readonly_fields = ["id", "created_at"]


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ["id", "vendor_profile", "title", "status", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["title", "details", "vendor_profile__business_name"]
    readonly_fields = ["id", "created_at"]
    actions = ["make_active", "make_inactive"]

    def make_active(self, request, queryset):
        queryset.update(status="active")

    make_active.short_description = "Mark selected certificates as active"

    def make_inactive(self, request, queryset):
        queryset.update(status="inactive")

    make_inactive.short_description = "Mark selected certificates as inactive"


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "vendor_profile", "is_active", "created_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["name", "description", "vendor_profile__business_name"]
    readonly_fields = ["id", "created_at", "updated_at"]


class ServiceInline(admin.TabularInline):
    model = Service
    extra = 0
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "name",
        "category",
        "vendor_profile",
        "is_active",
        "created_at",
    ]
    list_filter = ["is_active", "created_at", "category"]
    search_fields = [
        "name",
        "description",
        "vendor_profile__business_name",
        "category__name",
    ]
    readonly_fields = ["id", "created_at", "updated_at"]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related("vendor_profile", "category")
        return queryset
