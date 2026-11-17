import re


def to_cents(s):
    if not isinstance(s, str):
        raise ValueError("amount must be a string")

    amount = "".join(s.split()).replace(",", "")
    if amount.startswith("R"):
        amount = amount[1:]

    match = re.fullmatch(r"([+-]?)(\d+)(?:\.(\d{1,2}))?", amount)
    if not match:
        raise ValueError("amount must be numeric")

    sign, whole, fraction = match.groups()
    cents = int(whole) * 100 + int((fraction or "").ljust(2, "0"))
    return -cents if sign == "-" else cents


def vat_split(cents):
    quotient, remainder = divmod(cents * 15, 115)
    if remainder * 2 > 115 or (remainder * 2 == 115 and quotient % 2 != 0):
        quotient += 1

    vat_cents = quotient
    net_cents = cents - vat_cents
    return net_cents, vat_cents


if __name__ == "__main__":
    assert to_cents("R1,150.00") == 115000
    assert to_cents("1150") == 115000
    assert vat_split(115000) == (100000, 15000)