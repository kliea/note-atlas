import { createContext } from "react";

export type BoardSession = {
  startEdit: (nodeId: string) => void;
  updateText: (nodeId: string, text: string) => void;
  commitEdit: (nodeId: string, text: string) => void;
  cutConnection: (connectionId: number) => void;
  acceptSuggestion: (fromId: number, toId: number) => void;
  dismissSuggestion: (fromId: number, toId: number) => void;
  acceptPointContext: (noteId: number, pointId: number) => void;
  dismissPointContext: (noteId: number, pointId: number) => void;
  savePointContext: (noteId: number, pointId: number, context: string) => void;
  openStudy: (studyId: number, claimId: number | null) => void;
};

export const BoardSessionContext = createContext<BoardSession | null>(null);
