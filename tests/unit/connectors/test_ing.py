"""Tests for the ING España Enable Banking connector."""

from banking.connectors.enable_banking import EnableBankingConnector
from banking.connectors.ing import IngConnector


def test_bank_name_is_a_public_class_attribute() -> None:
    assert IngConnector.BANK_NAME == "ING España"


def test_session_id_key_is_bank_specific() -> None:
    assert IngConnector._SESSION_ID_KEY == "ENABLE_BANKING_SESSION_ID_ING"


def test_is_subclass_of_enable_banking_connector() -> None:
    assert issubclass(IngConnector, EnableBankingConnector)
