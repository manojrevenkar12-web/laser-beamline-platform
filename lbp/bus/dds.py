"""Publishing beamline state on DDS (Eclipse Cyclone DDS), so other lab software can subscribe without polling.

Topics (docs/icd/dds.md):
  lbp/shot        reliable, keep last 100: one record per fired shot
  lbp/interlock   reliable, transient-local, keep last 1: the latest interlock decision, for late joiners
  lbp/alignment   reliable: one record per alignment run
  lbp/health      best effort: device health counters
  lbp/alert       reliable, keep last 100: alerts for the operators

`MemoryBus` records the same messages for tests and the evaluation; `DdsBus` puts them on the wire.
"""

# no "from __future__ import annotations": cyclonedds reads the field types at runtime

from dataclasses import dataclass

try:
    from cyclonedds.core import Policy, Qos
    from cyclonedds.domain import DomainParticipant
    from cyclonedds.idl import IdlStruct
    from cyclonedds.pub import DataWriter
    from cyclonedds.topic import Topic

    HAVE_DDS = True
except ImportError:  # pragma: no cover
    HAVE_DDS = False
    IdlStruct = object  # type: ignore[assignment,misc]


@dataclass
class ShotMsg(IdlStruct, typename="lbp.Shot"):  # type: ignore[call-arg,misc]
    shot_id: str
    day: int
    t_s: float
    energy_reported_j: float
    nf_x_mm: float
    nf_y_mm: float
    ff_x_urad: float
    ff_y_urad: float
    fluence_est_j_cm2: float


@dataclass
class InterlockMsg(IdlStruct, typename="lbp.Interlock"):  # type: ignore[call-arg,misc]
    decision_id: str
    day: int
    t_s: float
    permit: bool
    reasons: str
    predicted_fluence_j_cm2: float


@dataclass
class AlignmentMsg(IdlStruct, typename="lbp.Alignment"):  # type: ignore[call-arg,misc]
    day: int
    t_s: float
    reason: str
    iterations: int
    converged: bool
    seconds: float


@dataclass
class HealthMsg(IdlStruct, typename="lbp.Health"):  # type: ignore[call-arg,misc]
    device: str
    ok: int
    failures: int
    crc_errors: int
    faulted: bool


@dataclass
class AlertMsg(IdlStruct, typename="lbp.Alert"):  # type: ignore[call-arg,misc]
    alert_id: str
    day: int
    t_s: float
    severity: str
    kind: str
    message: str


TOPICS = {
    "lbp/shot": ShotMsg,
    "lbp/interlock": InterlockMsg,
    "lbp/alignment": AlignmentMsg,
    "lbp/health": HealthMsg,
    "lbp/alert": AlertMsg,
}


class MemoryBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, object]] = []

    def publish(self, topic: str, msg: object) -> None:
        if topic not in TOPICS or not isinstance(msg, TOPICS[topic]):
            raise TypeError(f"{topic}: {type(msg).__name__}")
        self.messages.append((topic, msg))


class NullBus:
    def publish(self, topic: str, msg: object) -> None:
        return None


class FanoutBus:
    """Publish to several buses: DDS for lab software, the API for the console and webhooks."""

    def __init__(self, *buses: object):
        self.buses = buses

    def publish(self, topic: str, msg: object) -> None:
        for b in self.buses:
            b.publish(topic, msg)  # type: ignore[attr-defined]


def qos_for(topic: str) -> object:
    if topic == "lbp/interlock":
        return Qos(Policy.Reliability.Reliable(1_000_000_000), Policy.Durability.TransientLocal, Policy.History.KeepLast(1))
    if topic == "lbp/health":
        return Qos(Policy.Reliability.BestEffort, Policy.History.KeepLast(1))
    return Qos(Policy.Reliability.Reliable(1_000_000_000), Policy.History.KeepLast(100))


class DdsBus:
    def __init__(self, domain: int = 0):
        if not HAVE_DDS:  # pragma: no cover
            raise RuntimeError("cyclonedds is not installed")
        self.dp = DomainParticipant(domain)
        self.writers = {}
        for name, typ in TOPICS.items():
            topic = Topic(self.dp, name.replace("/", "_"), typ)
            self.writers[name] = DataWriter(self.dp, topic, qos=qos_for(name))

    def publish(self, topic: str, msg: object) -> None:
        if not isinstance(msg, TOPICS[topic]):
            raise TypeError(f"{topic}: {type(msg).__name__}")
        self.writers[topic].write(msg)
