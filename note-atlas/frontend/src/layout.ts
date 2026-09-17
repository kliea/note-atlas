/** Placement for topic nodes around a note hub, and hubs across the atlas. */

export const NOTE_NODE_WIDTH = 240;
export const NOTE_NODE_HEIGHT = 96;
export const TOPIC_NODE_WIDTH = 200;
export const TOPIC_NODE_HEIGHT = 84;
/** Minimum center-to-center distance between neighboring topic nodes. */
const TOPIC_SPACING = 220;
const MIN_RADIUS = 260;
export const CLUSTER_GAP = 820;

export type Side = "top" | "right" | "bottom" | "left";

export type Point = {
  x: number;
  y: number;
};

export type RadialSlot = {
  x: number;
  y: number;
  angle: number;
  sourceSide: Side;
  targetSide: Side;
};

export function hubOrigin(index: number): Point {
  return { x: index * CLUSTER_GAP, y: 0 };
}

export function radialSlots(count: number, origin: Point = { x: 0, y: 0 }): RadialSlot[] {
  if (count <= 0) {
    return [];
  }
  const radius = Math.max(MIN_RADIUS, (count * TOPIC_SPACING) / (2 * Math.PI));
  return Array.from({ length: count }, (_, index) => {
    // Start at 12 o'clock; y grows downward in the canvas.
    const angle = (2 * Math.PI * index) / count - Math.PI / 2;
    const sourceSide = sideFromAngle(angle);
    return {
      x: origin.x + Math.cos(angle) * radius - TOPIC_NODE_WIDTH / 2,
      y: origin.y + Math.sin(angle) * radius - TOPIC_NODE_HEIGHT / 2,
      angle,
      sourceSide,
      targetSide: oppositeSide(sourceSide),
    };
  });
}

export function sideFromAngle(angle: number): Side {
  const tau = Math.PI * 2;
  const normalized = ((angle % tau) + tau) % tau;
  const deg = (normalized * 180) / Math.PI;
  if (deg >= 45 && deg < 135) {
    return "bottom";
  }
  if (deg >= 135 && deg < 225) {
    return "left";
  }
  if (deg >= 225 && deg < 315) {
    return "top";
  }
  return "right";
}

export function oppositeSide(side: Side): Side {
  if (side === "top") {
    return "bottom";
  }
  if (side === "bottom") {
    return "top";
  }
  if (side === "left") {
    return "right";
  }
  return "left";
}

export function sideToward(from: Point, to: Point): Side {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx >= 0 ? "right" : "left";
  }
  return dy >= 0 ? "bottom" : "top";
}
