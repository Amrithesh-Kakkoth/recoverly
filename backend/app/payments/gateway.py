from app.core.config import settings
from app.payments.paypal_rest import PayPalREST

_gateway: PayPalREST | None = None


def get_gateway() -> PayPalREST:
    global _gateway
    if _gateway is None:
        _gateway = PayPalREST(settings.paypal_base_url, settings.paypal_client_id,
                              settings.paypal_client_secret)
    return _gateway


def set_gateway(gw) -> None:
    global _gateway
    _gateway = gw
