"""Validações compartilhadas entre o agente WhatsApp e a API da secretaria."""


def valida_cpf(cpf: str) -> str | None:
    """Valida o CPF (11 dígitos + dígitos verificadores).

    Devolve o CPF normalizado (só dígitos) se for válido; senão None.
    """
    digits = "".join(c for c in (cpf or "") if c.isdigit())
    if len(digits) != 11 or digits == digits[0] * 11:
        return None
    for i in (9, 10):
        soma = sum(int(digits[j]) * ((i + 1) - j) for j in range(i))
        if (soma * 10) % 11 % 10 != int(digits[i]):
            return None
    return digits
