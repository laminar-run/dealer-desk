from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from chaos.controls import Controls

Result = tuple[int, str, str | None]
Prepare = Callable[[Mapping[str, object]], Callable[[], Result]]
P = TypeVar("P")


@dataclass(frozen=True)
class MoveParams:
    x: int
    y: int


@dataclass(frozen=True)
class NoParams:
    pass


def parse_move(parameters: Mapping[str, object]) -> MoveParams:
    if set(parameters) != {"x", "y"}:
        raise ValueError
    x, y = parameters["x"], parameters["y"]
    if type(x) is not int or type(y) is not int:
        raise ValueError
    if not -(2**31) <= x < 2**31 or not -(2**31) <= y < 2**31:
        raise ValueError
    return MoveParams(x, y)


def parse_no_params(parameters: Mapping[str, object]) -> NoParams:
    if parameters:
        raise ValueError
    return NoParams()


def bind_action(
    parse: Callable[[Mapping[str, object]], P], handle: Callable[[P], Result]
) -> Prepare:
    def prepare(parameters: Mapping[str, object]) -> Callable[[], Result]:
        parsed = parse(parameters)
        return lambda: handle(parsed)

    return prepare


def action_definitions(root, controls: "Controls") -> dict[str, Prepare]:
    from chaos.scenarios import inject_critical_error

    return {
        "/window/move": bind_action(parse_move, controls.move),
        "/window/minimize": bind_action(parse_no_params, controls.minimize),
        "/input/ignore-next-click": bind_action(
            parse_no_params, controls.ignore_next_click
        ),
        "/dms/critical-error": bind_action(
            parse_no_params, lambda parameters: inject_critical_error(root)
        ),
    }
