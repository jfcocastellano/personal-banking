"""
Unit tests for NormalizedTransaction dataclass.

Requirements covered: 3.1 (field mapping), 3.4 (concepto default)
"""

import dataclasses
import pytest
from datetime import date
from decimal import Decimal

from src.normalizer import NormalizedTransaction


class TestNormalizedTransactionImmutability:
    """Verify that NormalizedTransaction is frozen (immutable)."""

    def test_frozen_raises_on_attribute_assignment(self):
        """Assigning to any field after construction must raise FrozenInstanceError."""
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("100.50"),
            concepto="Compra supermercado",
            banco="ING",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            tx.fecha = date(2025, 1, 15)  # type: ignore[misc]

    def test_frozen_raises_on_importe_assignment(self):
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("-20.00"),
            concepto="Cargo",
            banco="Sabadell",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            tx.importe = Decimal("0")  # type: ignore[misc]

    def test_frozen_raises_on_concepto_assignment(self):
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("50.00"),
            concepto="Nómina",
            banco="Revolut",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            tx.concepto = "Otro"  # type: ignore[misc]

    def test_frozen_raises_on_banco_assignment(self):
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("1.00"),
            concepto="",
            banco="MyInvestor",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            tx.banco = "ING"  # type: ignore[misc]

    def test_is_hashable(self):
        """Frozen dataclasses must be hashable (usable in sets/dict keys)."""
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("10.00"),
            concepto="Test",
            banco="ING",
        )
        # Constructing a set should not raise
        assert tx in {tx}


class TestNormalizedTransactionFieldTypes:
    """Verify that each field stores the correct type."""

    def test_fecha_is_date(self):
        tx = NormalizedTransaction(
            fecha=date(2025, 6, 15),
            importe=Decimal("0"),
            concepto="",
            banco="ING",
        )
        assert isinstance(tx.fecha, date)

    def test_importe_is_decimal(self):
        tx = NormalizedTransaction(
            fecha=date(2025, 6, 15),
            importe=Decimal("123.456"),
            concepto="",
            banco="ING",
        )
        assert isinstance(tx.importe, Decimal)

    def test_concepto_is_str(self):
        tx = NormalizedTransaction(
            fecha=date(2025, 6, 15),
            importe=Decimal("0"),
            concepto="Pago recibo",
            banco="ING",
        )
        assert isinstance(tx.concepto, str)

    def test_banco_is_str(self):
        tx = NormalizedTransaction(
            fecha=date(2025, 6, 15),
            importe=Decimal("0"),
            concepto="",
            banco="Sabadell",
        )
        assert isinstance(tx.banco, str)

    def test_importe_preserves_negative_sign(self):
        """Requirement 3.5: the sign of importe must be preserved."""
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("-99.99"),
            concepto="Cargo",
            banco="Revolut",
        )
        assert tx.importe < Decimal("0")

    def test_importe_preserves_positive_sign(self):
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("250.00"),
            concepto="Ingreso",
            banco="MyInvestor",
        )
        assert tx.importe > Decimal("0")

    def test_importe_zero(self):
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("0"),
            concepto="",
            banco="ING",
        )
        assert tx.importe == Decimal("0")


class TestNormalizedTransactionConcept:
    """Verify concepto field behaviour (Requirement 3.4)."""

    def test_concepto_can_be_empty_string(self):
        """concepto must accept an empty string without error."""
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("10.00"),
            concepto="",
            banco="ING",
        )
        assert tx.concepto == ""

    def test_concepto_with_value(self):
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("10.00"),
            concepto="Transferencia recibida",
            banco="Sabadell",
        )
        assert tx.concepto == "Transferencia recibida"


class TestNormalizedTransactionEquality:
    """Verify equality and hashing semantics of frozen dataclass."""

    def test_equal_instances_are_equal(self):
        tx1 = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("100.00"),
            concepto="Compra",
            banco="ING",
        )
        tx2 = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("100.00"),
            concepto="Compra",
            banco="ING",
        )
        assert tx1 == tx2

    def test_different_importe_not_equal(self):
        tx1 = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("100.00"),
            concepto="Compra",
            banco="ING",
        )
        tx2 = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("200.00"),
            concepto="Compra",
            banco="ING",
        )
        assert tx1 != tx2

    def test_different_banco_not_equal(self):
        tx1 = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("100.00"),
            concepto="Compra",
            banco="ING",
        )
        tx2 = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("100.00"),
            concepto="Compra",
            banco="Sabadell",
        )
        assert tx1 != tx2

    def test_equal_instances_have_same_hash(self):
        tx1 = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("100.00"),
            concepto="Compra",
            banco="ING",
        )
        tx2 = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("100.00"),
            concepto="Compra",
            banco="ING",
        )
        assert hash(tx1) == hash(tx2)

    def test_can_be_used_in_set_for_deduplication(self):
        """Frozen dataclasses should work as set elements for deduplication logic."""
        tx = NormalizedTransaction(
            fecha=date(2025, 1, 14),
            importe=Decimal("100.00"),
            concepto="Compra",
            banco="ING",
        )
        seen = {tx}
        assert tx in seen
        assert len(seen) == 1
