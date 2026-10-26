"""Validações compartilhadas entre o agente WhatsApp e a API da secretaria."""


def tel_key(phone: str) -> str:
    """Chave de comparação de telefone: DDD + últimos 8 dígitos.

    Ignora formatação, o DDI 55 e o 9º dígito — o WhatsApp manda '5527999449781', mas
    o cadastro feito pela recepção guarda o que foi digitado ('27999449781',
    '(27) 99944-9781', '2799449781'...). Mesma regra de tel_key_sql().
    """
    d = "".join(c for c in (phone or "") if c.isdigit()).lstrip("0")
    if len(d) in (12, 13) and d.startswith("55"):
        d = d[2:]
    return d[:2] + d[-8:]


def tel_key_sql(col: str) -> str:
    """Expressão SQL equivalente a tel_key() para uma coluna de telefone."""
    x = (f"regexp_replace(regexp_replace(regexp_replace({col}, '\\D', '', 'g'), "
         "'^0+', ''), '^55(?=\\d{10,11}$)', '')")
    return f"(left({x}, 2) || right({x}, 8))"


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
