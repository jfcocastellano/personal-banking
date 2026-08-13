"""ING España connector: Enable Banking PSD2 account, via the shared base class."""

from banking.connectors.enable_banking import EnableBankingConnector


class IngConnector(EnableBankingConnector):
    """Connector for ING España accounts via the Enable Banking PSD2 API."""

    BANK_NAME = "ING España"
    _SESSION_ID_KEY = "ENABLE_BANKING_SESSION_ID_ING"
