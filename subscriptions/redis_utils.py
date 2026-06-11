import json
from datetime import timedelta

from django.core.cache import cache

# Define cache key prefixes
VENDOR_DAYS_LEFT_PREFIX = "vendor:{id}:days_left"
VENDOR_SUBSCRIPTION_STATUS_PREFIX = "vendor:{id}:subscription_status"
CATEGORY_PRICE_ID_PREFIX = "category:{name}:price_id"
VENDOR_CARD_PREFIX = "vendor:{id}:card"
VENDOR_HAS_CARD_PREFIX = "vendor:{id}:has_card"
VENDOR_PAYMENT_METHOD_PREFIX = "vendor:{id}:payment_method_id"

# Define TTL values in seconds
CARD_TTL = 60 * 15  # 15 minutes
HAS_CARD_TTL = 60 * 60 * 24  # 24 hours
SUBSCRIPTION_STATUS_TTL = 60 * 15  # 15 minutes
DAYS_LEFT_TTL = 60 * 60 * 6  # 6 hours
PRICE_ID_TTL = 60 * 60 * 24  # 24 hours
PAYMENT_METHOD_TTL = 60 * 60 * 24  # 24 hours


def get_vendor_days_left_key(vendor_id):
    return VENDOR_DAYS_LEFT_PREFIX.format(id=vendor_id)


def get_vendor_subscription_status_key(vendor_id):
    return VENDOR_SUBSCRIPTION_STATUS_PREFIX.format(id=vendor_id)


def get_category_price_id_key(category_name):
    return CATEGORY_PRICE_ID_PREFIX.format(name=category_name)


def get_vendor_card_key(vendor_id):
    return VENDOR_CARD_PREFIX.format(id=vendor_id)


def get_vendor_has_card_key(vendor_id):
    return VENDOR_HAS_CARD_PREFIX.format(id=vendor_id)


def get_vendor_payment_method_key(vendor_id):
    return VENDOR_PAYMENT_METHOD_PREFIX.format(id=vendor_id)


# Subscription days left methods
def set_days_left(vendor_id, days):
    key = get_vendor_days_left_key(vendor_id)
    cache.set(key, days, DAYS_LEFT_TTL)


def get_days_left(vendor_id):
    key = get_vendor_days_left_key(vendor_id)
    return cache.get(key)


# Subscription status methods
def set_subscription_status(vendor_id, status):
    key = get_vendor_subscription_status_key(vendor_id)
    cache.set(key, status, SUBSCRIPTION_STATUS_TTL)


def get_subscription_status(vendor_id):
    key = get_vendor_subscription_status_key(vendor_id)
    return cache.get(key)


# Price ID methods
def set_price_id(category_name, price_id):
    key = get_category_price_id_key(category_name)
    cache.set(key, price_id, PRICE_ID_TTL)


def get_price_id(category_name):
    key = get_category_price_id_key(category_name)
    return cache.get(key)


# Card methods
def set_card_info(vendor_id, card_info):
    key = get_vendor_card_key(vendor_id)
    cache.set(key, json.dumps(card_info), CARD_TTL)


def get_card_info(vendor_id):
    key = get_vendor_card_key(vendor_id)
    data = cache.get(key)
    if data:
        return json.loads(data)
    return None


# Has card methods
def set_has_card(vendor_id, has_card=True):
    key = get_vendor_has_card_key(vendor_id)
    cache.set(key, has_card, HAS_CARD_TTL)


def get_has_card(vendor_id):
    key = get_vendor_has_card_key(vendor_id)
    return cache.get(key, False)


# Payment method methods
def set_payment_method_id(vendor_id, payment_method_id, permanent=False):
    key = get_vendor_payment_method_key(vendor_id)
    ttl = None if permanent else PAYMENT_METHOD_TTL
    cache.set(key, payment_method_id, ttl)


def get_payment_method_id(vendor_id):
    key = get_vendor_payment_method_key(vendor_id)
    return cache.get(key)


def delete_payment_method_id(vendor_id):
    key = get_vendor_payment_method_key(vendor_id)
    cache.delete(key)


# Utility function to clear all vendor cache
def clear_vendor_cache(vendor_id):
    keys = [
        get_vendor_days_left_key(vendor_id),
        get_vendor_subscription_status_key(vendor_id),
        get_vendor_card_key(vendor_id),
        get_vendor_has_card_key(vendor_id),
        get_vendor_payment_method_key(vendor_id),
    ]

    for key in keys:
        cache.delete(key)
