import { BaseEdge, EdgeLabelRenderer, type ConnectionLineComponentProps, type Edge, type EdgeProps } from "@xyflow/react";
import { saggingString } from "../../boardString";
import { useContext } from "react";
import { BoardSessionContext } from "../nodes/BoardNoteNode";

export type BoardStringData = {
  connectionId: number;
};

export type BoardStringEdge = Edge<BoardStringData, "boardString">;

export function BoardStringEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
  selected,
}: EdgeProps<BoardStringEdge>) {
  const session = useContext(BoardSessionContext);
  const { path, midX, midY } = saggingString(sourceX, sourceY, targetX, targetY);
  const connectionId = data?.connectionId;
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        className={selected ? "board-string selected" : "board-string"}
      />
      {connectionId != null && connectionId > 0 ? (
        <EdgeLabelRenderer>
          <button
            type="button"
            className="board-string-cut nodrag nopan"
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${midX}px, ${midY}px)`,
              pointerEvents: "all",
            }}
            aria-label="Cut connection"
            onClick={(event) => {
              event.stopPropagation();
              session?.cutConnection(connectionId);
            }}
          />
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

export function BoardConnectionLine({
  fromX,
  fromY,
  toX,
  toY,
}: ConnectionLineComponentProps) {
  const { path } = saggingString(fromX, fromY, toX, toY);
  return <path d={path} className="board-string-preview" fill="none" />;
}
