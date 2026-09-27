"""Banco Sabadell connector: Enable Banking PSD2 account, via the shared base class."""

from banking.connectors.enable_banking import EnableBankingConnector


class SabadellConnector(EnableBankingConnector):
    """Connector for Banco Sabadell accounts via the Enable Banking PSD2 API."""

    BANK_NAME = "Banco Sabadell"
    _SESSION_ID_KEY = "ENABLE_BANKING_SESSION_ID_SABADELL"
