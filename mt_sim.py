from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml

DIRECTIONS = {"R": 1, "L": -1, "S": 0}
REQUIRED_KEYS = ("estados", "alfabeto", "estado_inicial", "transiciones")


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass(frozen=True)
class Transition:
    kind: str
    value: str
    next_state: str


@dataclass(frozen=True)
class Machine:
    states: tuple[str, ...]
    alphabet: tuple[str, ...]
    initial_state: str
    blank: str
    transitions: dict[tuple[str, str], Transition]


@dataclass(frozen=True)
class Configuration:
    step: int
    state: str
    head: int
    tape: dict[int, str]


def _scalar_text(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return sorted(duplicates)


def _parse_states(raw: object, errors: list[str]) -> list[str]:
    if not isinstance(raw, list):
        errors.append("El campo 'estados' debe ser una lista.")
        return []

    states: list[str] = []
    for index, item in enumerate(raw, start=1):
        text = _scalar_text(item)
        if text is None or text == "":
            errors.append(f"El estado #{index} no es un valor textual válido.")
            continue
        if any(char.isspace() for char in text):
            errors.append(f"El estado '{text}' no puede contener espacios.")
            continue
        states.append(text)

    if not states:
        errors.append("El conjunto 'estados' no puede estar vacío.")
    for duplicate in _duplicate_values(states):
        errors.append(f"El estado '{duplicate}' está repetido en 'estados'.")
    return states


def _parse_alphabet(raw: object, errors: list[str]) -> list[str]:
    if not isinstance(raw, list):
        errors.append("El campo 'alfabeto' debe ser una lista.")
        return []

    symbols: list[str] = []
    for index, item in enumerate(raw, start=1):
        text = _scalar_text(item)
        if text is None or len(text) != 1:
            errors.append(f"El símbolo #{index} del alfabeto debe ser un único carácter.")
            continue
        if text.isspace():
            errors.append("El alfabeto no puede contener espacios en blanco literales.")
            continue
        if text in DIRECTIONS:
            errors.append(f"El símbolo '{text}' está reservado para movimientos (R, L, S).")
            continue
        symbols.append(text)

    if not symbols:
        errors.append("El alfabeto no puede estar vacío.")
    for duplicate in _duplicate_values(symbols):
        errors.append(f"El símbolo '{duplicate}' está repetido en 'alfabeto'.")
    return symbols


def _parse_blank(mt: dict, alphabet: list[str], errors: list[str]) -> str:
    text = _scalar_text(mt.get("blanco", "B"))
    if text is None or len(text) != 1:
        errors.append("El campo 'blanco' debe ser un único carácter.")
        return "B"
    if text in DIRECTIONS:
        errors.append(f"El blanco '{text}' no puede ser una dirección reservada (R, L, S).")
    if text not in set(alphabet):
        errors.append(f"El símbolo blanco '{text}' no pertenece al alfabeto.")
    return text


def _parse_transitions(
    raw: object,
    states: list[str],
    alphabet: list[str],
    errors: list[str],
) -> dict[tuple[str, str], Transition]:
    if not isinstance(raw, list):
        errors.append("El campo 'transiciones' debe ser una lista.")
        return {}

    state_set = set(states)
    alphabet_set = set(alphabet)
    transitions: dict[tuple[str, str], Transition] = {}
    seen_keys: set[tuple[str, str]] = set()

    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            tokens = item.split()
        elif isinstance(item, (list, tuple)):
            tokens = []
            valid = True
            for value in item:
                text = _scalar_text(value)
                if text is None:
                    valid = False
                    break
                tokens.append(text)
            if not valid:
                errors.append(f"Transición #{index}: contiene un valor no válido.")
                continue
        else:
            errors.append(
                f"Transición #{index}: debe ser una cadena o una lista de 4 elementos."
            )
            continue

        if len(tokens) != 4:
            errors.append(
                f"Transición #{index}: se esperaban 4 campos y se encontraron {len(tokens)}."
            )
            continue

        current, read, action, next_state = tokens
        key = (current, read)
        if key in seen_keys:
            errors.append(
                f"Transición #{index}: ya existe una transición para ({current}, {read})."
            )
            continue
        seen_keys.add(key)

        transition_errors: list[str] = []
        if current not in state_set:
            transition_errors.append(f"el estado actual '{current}' no está en 'estados'")
        if read not in alphabet_set:
            transition_errors.append(f"el símbolo leído '{read}' no está en 'alfabeto'")
        if next_state not in state_set:
            transition_errors.append(
                f"el estado siguiente '{next_state}' no está en 'estados'"
            )

        transition: Transition | None
        if action in DIRECTIONS:
            transition = Transition("move", action, next_state)
        elif action in alphabet_set:
            transition = Transition("write", action, next_state)
        else:
            transition_errors.append(
                f"la acción '{action}' no es R/L/S ni un símbolo del alfabeto"
            )
            transition = None

        if transition_errors or transition is None:
            errors.append(
                f"Transición #{index} ({' '.join(tokens)}): "
                + "; ".join(transition_errors)
                + "."
            )
            continue

        transitions[key] = transition

    return transitions


def parse_machine(data: object) -> Machine:
    errors: list[str] = []

    if not isinstance(data, dict):
        raise ValidationError(
            ["El contenido del YAML debe ser un mapa con la clave 'mt'."]
        )

    mt = data.get("mt")
    if not isinstance(mt, dict):
        raise ValidationError(["Falta la clave 'mt' o su valor no es un mapa."])

    missing = [key for key in REQUIRED_KEYS if key not in mt]
    if missing:
        errors.append("Faltan campos obligatorios en 'mt': " + ", ".join(missing) + ".")

    states = _parse_states(mt.get("estados"), errors)
    alphabet = _parse_alphabet(mt.get("alfabeto"), errors)

    initial = _scalar_text(mt.get("estado_inicial"))
    if initial is None or initial == "":
        errors.append("El campo 'estado_inicial' debe ser un estado válido.")
        initial = ""
    elif any(char.isspace() for char in initial):
        errors.append("El estado inicial no puede contener espacios.")

    if states and initial and initial not in set(states):
        errors.append(f"El estado inicial '{initial}' no está en 'estados'.")

    blank = _parse_blank(mt, alphabet, errors)
    transitions = _parse_transitions(mt.get("transiciones"), states, alphabet, errors)

    if errors:
        raise ValidationError(errors)

    return Machine(
        states=tuple(states),
        alphabet=tuple(alphabet),
        initial_state=initial,
        blank=blank,
        transitions=transitions,
    )


def load_machine(path: str | Path) -> Machine:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return parse_machine(data)


def validate_word(machine: Machine, word: str) -> None:
    alphabet = set(machine.alphabet)
    invalid = sorted({char for char in word if char not in alphabet})
    if invalid:
        formatted = ", ".join(repr(char) for char in invalid)
        raise ValidationError(
            [f"La entrada contiene símbolos fuera del alfabeto: {formatted}."]
        )


def simulate(machine: Machine, word: str) -> Iterator[Configuration]:
    tape = {
        index: char
        for index, char in enumerate(word)
        if char != machine.blank
    }
    state = machine.initial_state
    head = 0
    step = 0

    yield Configuration(step, state, head, dict(tape))

    while True:
        symbol = tape.get(head, machine.blank)
        transition = machine.transitions.get((state, symbol))
        if transition is None:
            return

        if transition.kind == "write":
            if transition.value == machine.blank:
                tape.pop(head, None)
            else:
                tape[head] = transition.value
        else:
            head += DIRECTIONS[transition.value]

        state = transition.next_state
        step += 1
        yield Configuration(step, state, head, dict(tape))


def format_tape(tape: dict[int, str], head: int, blank: str) -> str:
    if tape:
        low = min(min(tape), head)
        high = max(max(tape), head)
    else:
        low = high = head

    cells: list[str] = []
    for position in range(low, high + 1):
        symbol = tape.get(position, blank)
        cells.append(f"[{symbol}]" if position == head else symbol)

    return "... " + " ".join(cells) + " ..."


def tape_content(tape: dict[int, str], blank: str) -> str:
    if not tape:
        return ""
    low = min(tape)
    high = max(tape)
    return "".join(tape.get(position, blank) for position in range(low, high + 1))


def format_configuration(configuration: Configuration, blank: str) -> str:
    tape = format_tape(configuration.tape, configuration.head, blank)
    return (
        f"Paso {configuration.step}: "
        f"estado={configuration.state}, cinta={tape}"
    )


def _print_validation_errors(title: str, errors: list[str]) -> None:
    print(f"{title}:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mt_sim.py",
        description=(
            "Simulador de máquinas de Turing de una cinta con transiciones de "
            "4 campos. El tercer campo es R, L o S para mover, o un símbolo "
            "del alfabeto para escribir."
        ),
    )
    parser.add_argument("maquina", help="Ruta al archivo YAML de la máquina.")
    parser.add_argument(
        "entrada",
        help="Cadena de entrada. Use \"\" para la cadena vacía.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        machine = load_machine(args.maquina)
    except FileNotFoundError:
        print(f"Error: no se encontró el archivo '{args.maquina}'.", file=sys.stderr)
        return 2
    except yaml.YAMLError as exc:
        print(f"Error de sintaxis YAML: {exc}", file=sys.stderr)
        return 2
    except UnicodeError as exc:
        print(f"Error de codificación: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Error al leer '{args.maquina}': {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        _print_validation_errors("Especificación inválida", exc.errors)
        return 2

    try:
        validate_word(machine, args.entrada)
    except ValidationError as exc:
        _print_validation_errors("Entrada inválida", exc.errors)
        return 2

    last: Configuration | None = None

    try:
        print(f"Máquina: {args.maquina}")
        print(f"Entrada: {args.entrada if args.entrada else '(vacía)'}")
        print(f"Blanco: {machine.blank}")
        print(f"Estado inicial: {machine.initial_state}")
        print()

        for configuration in simulate(machine, args.entrada):
            last = configuration
            print(format_configuration(configuration, machine.blank), flush=True)
    except KeyboardInterrupt:
        print()
        print("Ejecución cancelada por el usuario.")
        if last is not None:
            print(
                "Última descripción instantánea: "
                + format_configuration(last, machine.blank)
            )
        return 130
    except BrokenPipeError:
        return 0

    if last is not None:
        content = tape_content(last.tape, machine.blank)
        print()
        print("Resultado final")
        print(f"  Pasos ejecutados: {last.step}")
        print(f"  Estado final: {last.state}")
        print(f"  Cinta final: {content if content else '(vacía)'}")
        print(
            "  Descripción final: "
            + format_configuration(last, machine.blank)
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
