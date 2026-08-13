"""MyInvestor connector: Enable Banking PSD2 account, via the shared base class."""

from banking.connectors.enable_banking import EnableBankingConnector


class MyInvestorConnector(EnableBankingConnector):
    """Connector for MyInvestor accounts via the Enable Banking PSD2 API."""

    BANK_NAME = "MyInvestor"
    _SESSION_ID_KEY = "ENABLE_BANKING_SESSION_ID_MYINVESTOR"
