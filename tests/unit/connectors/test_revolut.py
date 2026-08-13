"""Tests for the Revolut Enable Banking connector."""

from banking.connectors.enable_banking import EnableBankingConnector
from banking.connectors.revolut import RevolutConnector


def test_bank_name_is_a_public_class_attribute() -> None:
    assert RevolutConnector.BANK_NAME == "Revolut"


def test_session_id_key_is_bank_specific() -> None:
    assert RevolutConnector._SESSION_ID_KEY == "ENABLE_BANKING_SESSION_ID_REVOLUT"


def test_is_subclass_of_enable_banking_connector() -> None:
    assert issubclass(RevolutConnector, EnableBankingConnector)
