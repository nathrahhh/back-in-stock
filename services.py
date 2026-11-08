
import html
import os
from urllib.parse import quote

import httpx


def get_stock_details(sku: str) -> dict:
    """
    Retrieve the latest stock information from the store API.
    The webhook payload is not treated as the source of truth.
    """
    stock_api_url = os.getenv("STOCK_API_URL")
    stock_api_key = os.getenv("STOCK_API_KEY")

    if not stock_api_url or not stock_api_key:
        raise RuntimeError("Stock API configuration is missing.")

    url = f"{stock_api_url.rstrip('/')}/{quote(sku, safe='')}"

    response = httpx.get(
        url,
        headers={"Authorization": f"Bearer {stock_api_key}"},
        timeout=10.0,
    )
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Stock API returned an invalid response.")

    return data


def is_product_in_stock(stock_details: dict) -> bool:
    """
    Confirm stock using the store API response.
    Both in_stock and a positive quantity must be present.
    """
    quantity = stock_details.get("quantity")
    in_stock = stock_details.get("in_stock")

    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("Stock API returned an invalid quantity.")

    return in_stock is True and quantity > 0


def send_back_in_stock_email(
    email: str,
    sku: str,
    product_name: str | None = None,
    idempotency_key: str | None = None,
) -> str | None:
    """
    Send a back-in-stock email through the Resend-compatible API.

    Returns the provider's message ID when available.
    """
    resend_api_key = os.getenv("RESEND_API_KEY")
    resend_base_url = os.getenv("RESEND_BASE_URL")

    if not resend_api_key or not resend_base_url:
        raise RuntimeError("Email API configuration is missing.")

    safe_name = html.escape(product_name or sku)
    safe_sku = html.escape(sku)

    subject = f"{safe_name} is back in stock!"

    email_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{subject}</title>
    </head>
    <body style="margin:0;padding:24px;background-color:#f5f5f5;
                 font-family:Arial,sans-serif;color:#222;">
        <div style="max-width:560px;margin:0 auto;background:#ffffff;
                    padding:32px;border-radius:12px;">
            <h1 style="font-size:24px;margin-top:0;">
                It's back in stock!
            </h1>
            <p style="font-size:16px;line-height:1.6;">
                Good news! <strong>{safe_name}</strong> is available again.
            </p>
            <p style="font-size:14px;color:#666;">
                Product SKU: {safe_sku}
            </p>
            <p style="font-size:16px;line-height:1.6;">
                Thank you for signing up for a stock notification.
            </p>
            <p style="font-size:13px;color:#888;">
                This is an automated notification.
            </p>
        </div>
    </body>
    </html>
    """

    payload = {
        "from": "Back in Stock <onboarding@resend.dev>",
        "to": [email],
        "subject": subject,
        "html": email_html,
    }

    headers = {
        "Authorization": f"Bearer {resend_api_key}",
        "Content-Type": "application/json",
    }

    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    url = f"{resend_base_url.rstrip('/')}/emails"

    response = httpx.post(
        url,
        json=payload,
        headers=headers,
        timeout=15.0,
    )
    response.raise_for_status()

    result = response.json()
    return result.get("id")
