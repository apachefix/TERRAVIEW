import re

from apps.home.constants.country_calling_codes import COUNTRY_BY_CODE

def _digits(value):
    return re.sub(r"[^0-9]", "", str(value or ""))

def _explicit_country_code(digits):
    for code in sorted(COUNTRY_BY_CODE, key=len, reverse=True):
        if digits.startswith(code[1:]):
            remainder = digits[len(code) - 1:]
            if 6 <= len(remainder) <= 14:
                return code, remainder
    return None, digits

def normalize_international_phone(country_code, phone_number, required=True):
    raw = str(phone_number or "").strip()
    selected = str(country_code or "").strip()
    if not raw:
        if required:
            raise ValueError("Ingrese un numero telefonico valido.")
        return {"country_code": selected or "", "local_number": "", "full_number": ""}
    if re.search(r"[A-Za-z]", raw):
        raise ValueError("El telefono contiene caracteres no permitidos.")
    if selected and selected not in COUNTRY_BY_CODE:
        raise ValueError("Seleccione el codigo de pais.")
    digits = _digits(raw)
    if not digits:
        raise ValueError("Ingrese un numero telefonico valido.")
    explicit = raw.startswith("+") or raw.startswith("00")
    if raw.startswith("00"):
        digits = digits[2:]
        explicit = True
    inferred_code, inferred_local = _explicit_country_code(digits)
    if explicit:
        if not inferred_code:
            raise ValueError("Seleccione el codigo de pais.")
        selected, local = inferred_code, inferred_local
    else:
        if not selected:
            raise ValueError("Seleccione el codigo de pais.")
        # A pasted international number without plus is only stripped when it
        # starts with the selected valid code, avoiding arbitrary inference.
        if digits.startswith(selected[1:]) and len(digits) - len(selected[1:]) >= 6:
            local = digits[len(selected) - 1:]
        else:
            local = digits
    if not (6 <= len(local) <= 14):
        raise ValueError("Ingrese un numero telefonico valido.")
    full = selected + local
    if len(full) - 1 > 15:
        raise ValueError("El numero internacional no puede superar 15 digitos.")
    return {"country_code": selected, "local_number": local, "full_number": full}

def split_legacy_phone(country_code, phone_number):
    if country_code:
        try:
            return normalize_international_phone(country_code, phone_number, required=False)
        except ValueError:
            return {"country_code": country_code, "local_number": str(phone_number or ""), "full_number": str(phone_number or "")}
    raw = str(phone_number or "").strip()
    digits = _digits(raw)
    code, local = _explicit_country_code(digits)
    if raw.startswith("+") or (digits.startswith("56") and code == "+56"):
        if code:
            return {"country_code": code, "local_number": local, "full_number": code + local}
    return {"country_code": "+56", "local_number": raw, "full_number": ("+56" + digits) if digits else ""}
