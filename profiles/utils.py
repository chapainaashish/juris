import cloudinary
import cloudinary.uploader
from django.conf import settings
from django.utils.text import slugify


def generate_cloudinary_signature(folder="avatars", options=None):
    """
    Generate a signature for direct frontend uploads to Cloudinary.

    Args:
        folder: The folder path
        options: Additional options like max_file_size
    """
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_STORAGE["CLOUD_NAME"],
        api_key=settings.CLOUDINARY_STORAGE["API_KEY"],
        api_secret=settings.CLOUDINARY_STORAGE["API_SECRET"],
    )

    timestamp = cloudinary.utils.now()

    # Set up parameters for the signature
    params = {
        "timestamp": timestamp,
        "folder": folder,
    }

    if options:
        params.update(options)

    # Generate the signature
    signature = cloudinary.utils.api_sign_request(
        params, settings.CLOUDINARY_STORAGE["API_SECRET"]
    )

    # Return data needed for frontend upload
    result = {
        "signature": signature,
        "timestamp": timestamp,
        "cloud_name": settings.CLOUDINARY_STORAGE["CLOUD_NAME"],
        "api_key": settings.CLOUDINARY_STORAGE["API_KEY"],
        "folder": folder,
    }

    # Include max_file_size in the response if provided
    if options and "max_file_size" in options:
        result["max_file_size"] = options["max_file_size"]

    return result


def upload_to_cloudinary(file, vendor_id=None, folder_type="avatars", public_id=None):
    """
    Utility function to upload a file to Cloudinary from the backend,
    organizing files by vendor.

    Args:
        file: The file to upload
        vendor_id: The ID of the vendor (can be numeric ID or business name)
        folder_type: Type of content (avatars, documents, etc.)
        public_id: Optional custom public ID for the file
    """
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_STORAGE["CLOUD_NAME"],
        api_key=settings.CLOUDINARY_STORAGE["API_KEY"],
        api_secret=settings.CLOUDINARY_STORAGE["API_SECRET"],
    )

    # Folder structure: vendors/vendor_id/folder_type/
    base_folder = "vendors"
    if vendor_id:
        folder_path = f"{base_folder}/{vendor_id}/{folder_type}"
    else:
        folder_path = f"{base_folder}/unassigned/{folder_type}"

    # Set upload options
    options = {
        "folder": folder_path,
        "overwrite": True,
        "resource_type": "auto",
        "max_file_size": 2000000000,
    }

    if public_id:
        options["public_id"] = public_id

    # Upload the file to Cloudinary
    result = cloudinary.uploader.upload(file, **options)

    return result


def get_transformed_url(original_url, transformation):
    """
    Create a transformed version of a Cloudinary URL.
    Example transformations:
    - c_crop,g_face,h_400,w_400 (crop to 400x400 focused on face)
    - c_scale,w_200 (scale to 200px width)
    """
    # Split the URL to insert transformation
    parts = original_url.split("/upload/")
    if len(parts) != 2:
        return original_url

    return f"{parts[0]}/upload/{transformation}/{parts[1]}"


def get_vendor_folder_path(
    vendor_profile=None, user=None, business_name=None, session_token=None
):
    """
    Generate a consistent vendor folder path based on available information.
    Priority: vendor_profile > business_name > user > session_token
    """

    base_folder = "vendors"

    if vendor_profile and vendor_profile.business_name:
        return f"{base_folder}/{slugify(vendor_profile.business_name)}"
    elif business_name:
        return f"{base_folder}/{slugify(business_name)}"
    elif user:
        return f"{base_folder}/user_{user.id}"
    elif session_token:
        return f"{base_folder}/session_{session_token[:8]}"
    else:
        return f"{base_folder}/unassigned"
