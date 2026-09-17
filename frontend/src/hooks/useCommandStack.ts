import { useCallback, useRef, useState } from "react";

export type Command = {
  label: string;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
};

const LIMIT = 50;

export function useCommandStack(): {
  push: (command: Command) => void;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  discard: (command: Command) => void;
  canUndo: boolean;
  canRedo: boolean;
} {
  const undoStack = useRef<Command[]>([]);
  const redoStack = useRef<Command[]>([]);
  const busy = useRef(false);
  const [, setRevision] = useState(0);

  const touch = useCallback(() => {
    setRevision((value) => value + 1);
  }, []);

  const push = useCallback(
    (command: Command) => {
      undoStack.current = [...undoStack.current, command].slice(-LIMIT);
      redoStack.current = [];
      touch();
    },
    [touch],
  );

  const undo = useCallback(async () => {
    if (busy.current) {
      return;
    }
    const command = undoStack.current.at(-1);
    if (!command) {
      return;
    }
    busy.current = true;
    try {
      await command.undo();
      undoStack.current = undoStack.current.slice(0, -1);
      redoStack.current = [...redoStack.current, command];
      touch();
    } finally {
      busy.current = false;
    }
  }, [touch]);

  const redo = useCallback(async () => {
    if (busy.current) {
      return;
    }
    const command = redoStack.current.at(-1);
    if (!command) {
      return;
    }
    busy.current = true;
    try {
      await command.redo();
      redoStack.current = redoStack.current.slice(0, -1);
      undoStack.current = [...undoStack.current, command].slice(-LIMIT);
      touch();
    } finally {
      busy.current = false;
    }
  }, [touch]);

  const discard = useCallback(
    (command: Command) => {
      undoStack.current = undoStack.current.filter((item) => item !== command);
      redoStack.current = redoStack.current.filter((item) => item !== command);
      touch();
    },
    [touch],
  );

  return {
    push,
    undo,
    redo,
    discard,
    canUndo: undoStack.current.length > 0,
    canRedo: redoStack.current.length > 0,
  };
}
