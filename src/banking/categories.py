"""ISO 18245 merchant category codes, mapped to Spanish labels.

The mapping is deliberately partial: Enable Banking documents
``merchant_category_code`` as an optional ISO 18245 string, and the codes the
banks actually send in production are only verified for *presence*, not for
their exact vocabulary. An unmapped code therefore degrades to the raw code the
bank sent, and a missing one to an empty cell — never to a guessed label.

Extend ``_ISO18245_LABELS`` when a production run surfaces a new common code:
the raw fallback makes a stale table harmless, only less readable.
"""

# Common consumer-facing ISO 18245 codes. One row per code; labels are the
# stable Spanish wording the sheet shows. Several codes may share a label on
# purpose (supermarkets, bakeries and food stores are one real-world category).
_ISO18245_LABELS: dict[str, str] = {
    "4111": "TRANSPORTE",
    "4121": "TRANSPORTE",
    "4215": "ENVÍOS",
    "4814": "TELEFONÍA",
    "4900": "SUMINISTROS",
    "5411": "ALIMENTACIÓN",
    "5451": "ALIMENTACIÓN",
    "5499": "ALIMENTACIÓN",
    "5541": "COMBUSTIBLE",
    "5651": "ROPA",
    "5732": "ELECTRÓNICA",
    "5811": "RESTAURACIÓN",
    "5812": "RESTAURACIÓN",
    "5814": "RESTAURACIÓN",
    "5815": "SUSCRIPCIONES DIGITALES",
    "5816": "SUSCRIPCIONES DIGITALES",
    "5818": "SUSCRIPCIONES DIGITALES",
    "5912": "FARMACIA",
    "6300": "SEGUROS",
    "7011": "ALOJAMIENTO",
    "7210": "LAVANDERÍA",
    "7230": "PELUQUERÍA",
    "7521": "ESTACIONAMIENTO",
    "7832": "CINE",
    "8011": "SALUD",
    "8021": "SALUD",
    "8699": "ASOCIACIONES",
}


def category_cell(code: str | None) -> str:
    """The raw tab's category cell: mapped label, raw code, or empty.

    Args:
        code: The ``merchant_category_code`` the bank sent, or ``None``.

    Returns:
        The Spanish label when the code is in the table, otherwise the code
        itself as-is; an absent or blank code yields an empty string so the
        cell stays empty instead of inventing a category.
    """
    if code is None:
        return ""
    normalized = code.strip()
    if not normalized:
        return ""
    return _ISO18245_LABELS.get(normalized, normalized)
