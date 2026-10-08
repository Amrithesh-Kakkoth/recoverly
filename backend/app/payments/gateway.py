from app.core.config import settings
from app.payments.paypal_rest import PayPalREST
from app.payments.toolkit import PayPalGateway, ToolkitGateway

_gateway = None


def get_gateway() -> PayPalGateway:
    global _gateway
    if _gateway is None:
        rest = PayPalREST(settings.paypal_base_url, settings.paypal_client_id,
                          settings.paypal_client_secret)
        toolkit = ToolkitGateway(settings.paypal_client_id, settings.paypal_client_secret)
        _gateway = PayPalGateway(rest, toolkit)
    return _gateway


def set_gateway(gw) -> None:
    global _gateway
    _gateway = gw
