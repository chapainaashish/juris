from rest_framework import permissions

from profiles.models import VendorProfile


class IsLawyerVendor(permissions.BasePermission):
    """
    Custom permission to check if user is authenticated and has 'Lawyer' category
    """

    message = "Only vendors with 'Lawyer' category can perform this action."

    def has_permission(self, request, view):
        # First check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False

        # Admin users can always access
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Check if user has vendor profile with 'Lawyer' category
        try:
            vendor_profile = request.user.vendorprofile
            return vendor_profile.category and vendor_profile.category.name == "Lawyer"
        except VendorProfile.DoesNotExist:
            return False


class IsLawyerVendorOrReadOnly(permissions.BasePermission):
    """
    Custom permission for public endpoints where anyone can read,
    but only lawyer vendors can write
    """

    message = "Only vendors with 'Lawyer' category can modify this resource."

    def has_permission(self, request, view):
        # Allow read permissions for all users
        if request.method in permissions.SAFE_METHODS:
            return True

        # For write operations, check lawyer vendor status
        if not request.user or not request.user.is_authenticated:
            return False

        # Admin users can always access
        if request.user.is_staff or request.user.is_superuser:
            return True

        try:
            vendor_profile = request.user.vendorprofile
            return vendor_profile.category and vendor_profile.category.name == "Lawyer"
        except VendorProfile.DoesNotExist:
            return False


class IsAuthenticatedReadOrLawyerWrite(permissions.BasePermission):
    """
    Custom permission where:
    - Any authenticated user can READ
    - Only lawyer vendors can WRITE (create)
    - Only owner lawyers can MODIFY existing objects
    """

    message = "Authentication required. Only lawyer vendors can modify resources."

    def has_permission(self, request, view):
        # REQUIRE authentication for ALL operations
        if not request.user or not request.user.is_authenticated:
            return False

        # Admin users can always access
        if request.user.is_staff or request.user.is_superuser:
            return True

        # For read operations, any authenticated user can access
        if request.method in permissions.SAFE_METHODS:
            return True

        # For write operations, check lawyer vendor status
        try:
            vendor_profile = request.user.vendorprofile
            return vendor_profile.category and vendor_profile.category.name == "Lawyer"
        except VendorProfile.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        # REQUIRE authentication for ALL operations
        if not request.user or not request.user.is_authenticated:
            return False

        # Admin users can access everything
        if request.user.is_staff or request.user.is_superuser:
            return True

        # For read operations, any authenticated user can access
        if request.method in permissions.SAFE_METHODS:
            return True

        # For write operations on existing objects, check ownership
        if hasattr(obj, "lawyer"):
            # Availability and Unavailability objects
            return obj.lawyer.vendor_profile.user == request.user
        elif hasattr(obj, "vendor_profile"):
            # LawyerProfile object
            return obj.vendor_profile.user == request.user

        return False


class IsOwnerLawyerVendor(permissions.BasePermission):
    """
    Custom permission to check if user owns the lawyer profile/offering/offering_type/availability/unavailability
    and has 'Lawyer' category
    """

    message = "You can only access your own lawyer resources."

    def has_permission(self, request, view):
        # First check basic lawyer vendor permission
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_staff or request.user.is_superuser:
            return True
        try:
            vendor_profile = request.user.vendorprofile
            return vendor_profile.category and vendor_profile.category.name == "Lawyer"
        except VendorProfile.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        # Admin users can access everything
        if request.user.is_staff or request.user.is_superuser:
            return True

        # Check ownership based on object type
        if hasattr(obj, "vendor_profile"):
            # LawyerProfile object
            return obj.vendor_profile.user == request.user
        elif hasattr(obj, "lawyer_profile"):
            # LawyerOffering object
            return obj.lawyer_profile.vendor_profile.user == request.user
        elif hasattr(obj, "offering"):
            # OfferingType object - traverse through offering -> lawyer_profile -> vendor_profile
            return obj.offering.lawyer_profile.vendor_profile.user == request.user
        elif hasattr(obj, "lawyer"):
            # Availability and Unavailability objects - traverse through lawyer -> vendor_profile
            return obj.lawyer.vendor_profile.user == request.user

        return False
