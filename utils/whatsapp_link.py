"""
Helper for generating WhatsApp deep links for the storefront.
"""
from typing import List, Dict, Any
from urllib.parse import quote


def generate_whatsapp_link(
    whatsapp_number: str,
    cart_id: str,
    products: List[Dict[str, Any]]
) -> str:
    """
    Generate a wa.me deep link that pre-fills a WhatsApp message with the cart ID
    and product names.

    Args:
        whatsapp_number: The tenant's WhatsApp number (from tenants.whatsapp_number).
                         Any non-digit characters are stripped automatically.
        cart_id: The Redis cart ID (UUID string).
        products: List of product dicts, each must have a "name" key.

    Returns:
        A wa.me URL string, e.g.:
        "https://wa.me/584121234567?text=pedido%3Aabc123%20Hamburguesa%20Papas"
    """
    # Normalize phone number — strip non-digits
    import re
    clean_number = re.sub(r'\D', '', whatsapp_number)

    # Build message text: "pedido:{cart_id} Product1 Product2 ..."
    product_names = " ".join(p["name"] for p in products)
    message_text = f"pedido:{cart_id} {product_names}".strip()

    # URL-encode the message
    encoded_text = quote(message_text)

    return f"https://wa.me/{clean_number}?text={encoded_text}"
