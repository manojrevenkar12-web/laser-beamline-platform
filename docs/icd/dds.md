# DDS topics

Published by `lbp/bus/dds.py` on Eclipse Cyclone DDS, domain 0 by default. Types are IDL structs generated
from the Python dataclasses (module `lbp`).

| Topic | Type | QoS | When |
|---|---|---|---|
| `lbp_shot` | `lbp.Shot` | reliable, keep last 100 | every fired shot, after it is stored |
| `lbp_interlock` | `lbp.Interlock` | reliable, transient-local, keep last 1 | every interlock decision; a late joiner gets the latest |
| `lbp_alignment` | `lbp.Alignment` | reliable, keep last 100 | every alignment run |
| `lbp_health` | `lbp.Health` | best effort, keep last 1 | device counters at the end of a shift |
| `lbp_alert` | `lbp.Alert` | reliable, keep last 100 | every alert for the operators |

Fields are listed in `lbp/bus/dds.py`. A subscriber in another process:

```python
from cyclonedds.domain import DomainParticipant
from cyclonedds.sub import DataReader
from cyclonedds.topic import Topic
from lbp.bus.dds import InterlockMsg, qos_for

dp = DomainParticipant(0)
reader = DataReader(dp, Topic(dp, "lbp_interlock", InterlockMsg), qos=qos_for("lbp/interlock"))
for msg in reader.take_iter():
    print(msg.permit, msg.reasons)
```
