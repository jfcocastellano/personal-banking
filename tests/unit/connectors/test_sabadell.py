"""Tests for the Banco Sabadell Enable Banking connector."""

from banking.connectors.enable_banking import EnableBankingConnector
from banking.connectors.sabadell import SabadellConnector


def test_bank_name_is_a_public_class_attribute() -> None:
    assert SabadellConnector.BANK_NAME == "Banco Sabadell"


def test_session_id_key_is_bank_specific() -> None:
    assert SabadellConnector._SESSION_ID_KEY == "ENABLE_BANKING_SESSION_ID_SABADELL"


def test_is_subclass_of_enable_banking_connector() -> None:
    assert issubclass(SabadellConnector, EnableBankingConnector)
