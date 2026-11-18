import type { Device } from "../../shared/data/types";
import { color } from "../../shared/theme/tokens";
import s from "./beamline.module.css";

interface Node {
  id: string;
  label: string;
  x: number;
  device?: string;
  detail: string;
}

// The beam runs left to right along y = 70; diagnostics hang below their pick-offs.
const NODES: Node[] = [
  { id: "fe", label: "Front end", x: 60, device: "lcu", detail: "low pulse 1/1000" },
  { id: "m1", label: "M1", x: 250, device: "pmc", detail: "far mirror, 2 axes" },
  { id: "m2", label: "M2", x: 420, device: "pmc", detail: "near mirror, 2 axes" },
  { id: "amp", label: "Amplifier aperture", x: 640, device: "nfc", detail: "near-field camera" },
  { id: "em", label: "Energy pick-off", x: 860, device: "em", detail: "pyro meter + reference" },
  { id: "tc", label: "Target chamber", x: 1080, device: "ffc", detail: "far-field camera" },
];

function status(devices: Device[], name?: string): Device | undefined {
  return devices.find((d) => d.name === name);
}

export function BeamlineSchematic({ devices, held }: { devices: Device[]; held: boolean }) {
  const path = "M 20 70 L 250 70 L 250 70 L 420 70 L 1080 70";
  return (
    <figure className={s.figure} aria-label="Beamline schematic with device status">
      <svg viewBox="0 0 1160 170" className={s.svg} role="img">
        <title>
          Beamline: front end, two steering mirrors, amplifier aperture, energy pick-off, target chamber
        </title>
        <line x1="20" x2="1140" y1="70" y2="70" stroke={color.rule} strokeWidth="10" strokeLinecap="round" />
        {/* the one orchestrated moment: the beam travels the line when the console opens */}
        <path
          d={path}
          pathLength={1}
          className={s.beam}
          fill="none"
          stroke={held ? color.hold : color.beam}
          strokeWidth="4"
          strokeLinecap="round"
        />
        {NODES.map((n) => {
          const d = status(devices, n.device);
          const bad = d?.faulted ?? false;
          return (
            <g key={n.id} transform={`translate(${n.x} 0)`}>
              {n.id === "m1" || n.id === "m2" ? (
                <line
                  x1="-14"
                  y1="86"
                  x2="14"
                  y2="54"
                  stroke={color.ink}
                  strokeWidth="5"
                  strokeLinecap="round"
                />
              ) : n.id === "tc" ? (
                <circle cx="0" cy="70" r="22" fill={color.panel} stroke={color.ink} strokeWidth="2" />
              ) : n.id === "amp" ? (
                <rect
                  x="-36"
                  y="48"
                  width="72"
                  height="44"
                  rx="3"
                  fill={color.beamSoft}
                  stroke={color.ink}
                  strokeWidth="2"
                />
              ) : (
                <rect
                  x="-16"
                  y="56"
                  width="32"
                  height="28"
                  rx="3"
                  fill={color.panel}
                  stroke={color.ink}
                  strokeWidth="2"
                />
              )}
              <text x="0" y="30" textAnchor="middle" className={s.label}>
                {n.label}
              </text>
              <circle cx="-42" cy="132" r="5" fill={bad ? color.hold : color.permit} />
              <text x="-32" y="136" className={s.detail}>
                {d
                  ? `${d.name}: ${bad ? "faulted" : "ok"}${d.crc_errors ? `, ${d.crc_errors} CRC retries` : ""}`
                  : n.detail}
              </text>
              <text x="-32" y="154" className={s.detail}>
                {n.detail}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
