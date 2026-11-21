import itertools
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mt_sim

EXAMPLES = ROOT / "examples"


def spec(**overrides):
    data = {
        "mt": {
            "estados": ["q0"],
            "alfabeto": ["a", "B"],
            "estado_inicial": "q0",
            "transiciones": ["q0 a R q0"],
        }
    }
    data["mt"].update(overrides)
    return data


class ValidationTests(unittest.TestCase):
    def test_valid_spec(self):
        machine = mt_sim.parse_machine(spec())
        self.assertEqual(machine.initial_state, "q0")
        self.assertEqual(machine.blank, "B")
        self.assertEqual(machine.states, ("q0",))
        self.assertEqual(machine.alphabet, ("a", "B"))
        self.assertEqual(machine.transitions[("q0", "a")].kind, "move")

    def test_write_transition(self):
        machine = mt_sim.parse_machine(
            spec(alfabeto=["a", "X", "B"], transiciones=["q0 a X q0"])
        )
        transition = machine.transitions[("q0", "a")]
        self.assertEqual(transition.kind, "write")
        self.assertEqual(transition.value, "X")

    def test_missing_required_key(self):
        data = spec()
        del data["mt"]["transiciones"]
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(data)
        self.assertIn("transiciones", str(context.exception))

    def test_missing_mt(self):
        with self.assertRaises(mt_sim.ValidationError):
            mt_sim.parse_machine({"otra": {}})

    def test_initial_state_not_in_states(self):
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(spec(estado_inicial="q9"))
        self.assertIn("no está en 'estados'", str(context.exception))

    def test_transition_with_unknown_state(self):
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(spec(transiciones=["q9 a R q0"]))
        self.assertIn("estado actual", str(context.exception))

    def test_transition_with_unknown_next_state(self):
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(spec(transiciones=["q0 a R q9"]))
        self.assertIn("estado siguiente", str(context.exception))

    def test_transition_with_unknown_symbol(self):
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(spec(transiciones=["q0 z R q0"]))
        self.assertIn("símbolo leído", str(context.exception))

    def test_transition_with_unknown_write_symbol(self):
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(spec(transiciones=["q0 a Z q0"]))
        self.assertIn("acción", str(context.exception))

    def test_transition_with_wrong_field_count(self):
        for transition in ("q0 a R", "q0 a R q0 extra"):
            with self.subTest(transition=transition):
                with self.assertRaises(mt_sim.ValidationError) as context:
                    mt_sim.parse_machine(spec(transiciones=[transition]))
                self.assertIn("4 campos", str(context.exception))

    def test_duplicate_transition_is_rejected(self):
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(spec(transiciones=["q0 a R q0", "q0 a L q0"]))
        self.assertIn("ya existe una transición", str(context.exception))

    def test_write_and_move_conflict_is_rejected(self):
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(
                spec(
                    alfabeto=["a", "X", "B"],
                    transiciones=["q0 a R q0", "q0 a X q0"],
                )
            )
        self.assertIn("ya existe una transición", str(context.exception))

    def test_reserved_direction_symbol_is_rejected(self):
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(spec(alfabeto=["a", "R", "B"]))
        self.assertIn("reservado", str(context.exception))

    def test_blank_must_belong_to_alphabet(self):
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(spec(blanco="Z"))
        self.assertIn("no pertenece al alfabeto", str(context.exception))

    def test_duplicate_states_and_symbols(self):
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.parse_machine(
                spec(
                    estados=["q0", "q0"],
                    alfabeto=["a", "a", "B"],
                )
            )
        message = str(context.exception)
        self.assertIn("repetido en 'estados'", message)
        self.assertIn("repetido en 'alfabeto'", message)

    def test_numeric_symbols_are_normalized(self):
        data = {
            "mt": {
                "estados": ["q0"],
                "alfabeto": [0, 1, "B"],
                "estado_inicial": "q0",
                "blanco": "B",
                "transiciones": ["q0 0 R q0"],
            }
        }
        machine = mt_sim.parse_machine(data)
        self.assertEqual(machine.alphabet, ("0", "1", "B"))
        self.assertIn(("q0", "0"), machine.transitions)

    def test_list_transitions_are_accepted(self):
        machine = mt_sim.parse_machine(spec(transiciones=[["q0", "a", "R", "q0"]]))
        self.assertIn(("q0", "a"), machine.transitions)

    def test_empty_transition_list_is_valid(self):
        machine = mt_sim.parse_machine(spec(transiciones=[]))
        self.assertEqual(machine.transitions, {})

    def test_input_outside_alphabet(self):
        machine = mt_sim.parse_machine(spec())
        with self.assertRaises(mt_sim.ValidationError) as context:
            mt_sim.validate_word(machine, "ab")
        self.assertIn("fuera del alfabeto", str(context.exception))

    def test_load_machine_from_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "maquina.yaml"
            path.write_text(
                "mt:\n"
                "  estados: [q0]\n"
                "  alfabeto: ['a', 'B']\n"
                "  estado_inicial: q0\n"
                "  transiciones:\n"
                "    - q0 a R q0\n",
                encoding="utf-8",
            )
            machine = mt_sim.load_machine(path)
        self.assertEqual(machine.blank, "B")


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.multiplo = mt_sim.load_machine(EXAMPLES / "multiplo_3.yaml")
        cls.invierte = mt_sim.load_machine(EXAMPLES / "invierte_binario.yaml")

    def test_write_then_move_are_separate_steps(self):
        machine = mt_sim.parse_machine(
            spec(
                estados=["q0", "q1", "q2"],
                alfabeto=["a", "X", "B"],
                transiciones=["q0 a X q1", "q1 X R q2"],
            )
        )
        configurations = list(mt_sim.simulate(machine, "a"))
        self.assertEqual(configurations[1].state, "q1")
        self.assertEqual(configurations[1].head, 0)
        self.assertEqual(configurations[1].tape, {0: "X"})
        self.assertEqual(configurations[2].state, "q2")
        self.assertEqual(configurations[2].head, 1)
        self.assertEqual(mt_sim.tape_content(configurations[-1].tape, "B"), "X")

    def test_multiplo_de_tres(self):
        cases = [
            ("1001", "q_si", "1001", 5),
            ("101", "q_no", "101", 4),
            ("11", "q_si", "11", 3),
            ("", "q_si", "", 1),
        ]
        for word, expected_state, expected_tape, expected_steps in cases:
            with self.subTest(word=word):
                configurations = list(mt_sim.simulate(self.multiplo, word))
                final = configurations[-1]
                self.assertEqual(final.state, expected_state)
                self.assertEqual(mt_sim.tape_content(final.tape, "B"), expected_tape)
                self.assertEqual(final.step, expected_steps)

    def test_invierte_binario(self):
        cases = {
            "": "",
            "0": "0",
            "1": "1",
            "01": "10",
            "10": "01",
            "1011": "1101",
            "100": "001",
            "1001": "1001",
            "10110": "01101",
        }
        for word, expected in cases.items():
            with self.subTest(word=word):
                configurations = list(mt_sim.simulate(self.invierte, word))
                final = configurations[-1]
                self.assertEqual(final.state, "q_halt")
                self.assertEqual(mt_sim.tape_content(final.tape, "B"), expected)

    def test_infinite_machine_can_be_iterated_without_limit(self):
        machine = mt_sim.parse_machine(spec(transiciones=["q0 a R q0"]))
        configurations = list(itertools.islice(mt_sim.simulate(machine, "aaaa"), 5))
        self.assertEqual([item.step for item in configurations], [0, 1, 2, 3, 4])
        self.assertEqual([item.head for item in configurations], [0, 1, 2, 3, 4])

    def test_tape_extends_to_the_left(self):
        machine = mt_sim.parse_machine(
            spec(transiciones=["q0 a L q0", "q0 B L q0"])
        )
        configurations = list(itertools.islice(mt_sim.simulate(machine, "a"), 4))
        self.assertEqual([item.head for item in configurations], [0, -1, -2, -3])
        self.assertEqual(
            mt_sim.format_tape(
                configurations[-1].tape,
                configurations[-1].head,
                machine.blank,
            ),
            "... [B] B B a ...",
        )


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments, timeout=30):
        return subprocess.run(
            [sys.executable, str(ROOT / "mt_sim.py"), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def test_valid_run(self):
        result = self.run_cli(str(EXAMPLES / "multiplo_3.yaml"), "1001")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Resultado final", result.stdout)
        self.assertIn("Estado final: q_si", result.stdout)
        self.assertIn("Cinta final: 1001", result.stdout)

    def test_reverse_run(self):
        result = self.run_cli(str(EXAMPLES / "invierte_binario.yaml"), "1011")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Estado final: q_halt", result.stdout)
        self.assertIn("Cinta final: 1101", result.stdout)

    def test_invalid_specification_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalida.yaml"
            path.write_text(
                "mt:\n"
                "  estados: [q0]\n"
                "  alfabeto: ['a', 'B']\n"
                "  estado_inicial: q0\n"
                "  transiciones:\n"
                "    - q0 a R q9\n",
                encoding="utf-8",
            )
            result = self.run_cli(str(path), "a")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Especificación inválida", result.stderr)

    def test_cancellation_with_ctrl_c(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "infinita.yaml"
            path.write_text(
                "mt:\n"
                "  estados: [q0]\n"
                "  alfabeto: ['a', 'B']\n"
                "  estado_inicial: q0\n"
                "  transiciones:\n"
                "    - q0 a a q0\n",
                encoding="utf-8",
            )
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "mt_sim.py"), str(path), "a"],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert process.stdout is not None
            try:
                for _ in range(5):
                    line = process.stdout.readline()
                    if not line:
                        break
                process.send_signal(signal.SIGINT)
                stdout, stderr = process.communicate(timeout=10)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assertEqual(process.returncode, 130)
        self.assertIn("cancelada", (stdout + stderr).lower())


if __name__ == "__main__":
    unittest.main()
