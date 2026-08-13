"""Tests for the MyInvestor Enable Banking connector."""

from banking.connectors.enable_banking import EnableBankingConnector
from banking.connectors.myinvestor import MyInvestorConnector


def test_bank_name_is_a_public_class_attribute() -> None:
    assert MyInvestorConnector.BANK_NAME == "MyInvestor"


def test_session_id_key_is_bank_specific() -> None:
    assert MyInvestorConnector._SESSION_ID_KEY == "ENABLE_BANKING_SESSION_ID_MYINVESTOR"


def test_is_subclass_of_enable_banking_connector() -> None:
    assert issubclass(MyInvestorConnector, EnableBankingConnector)
