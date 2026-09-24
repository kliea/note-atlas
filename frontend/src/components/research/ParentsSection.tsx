import { useState, type ReactNode } from "react";
import type { ParentItem, ParentMark } from "../../types";

// Show this many Parents before "show more" (docs/specs/research-track.md, "Leads").
const MAX_SHOWN = 5;

type ParentsSectionProps = {
  parents: ParentItem[];
  onMark: (studyId: number, mark: ParentMark | null) => Promise<void>;
  onOpen: (studyId: number) => void;
  links: (parent: ParentItem) => ReactNode;
};

export function ParentsSection({ parents, onMark, onOpen, links }: ParentsSectionProps) {
  const [expanded, setExpanded] = useState(false);
  const chosen = parents.filter((p) => p.is_parent);
  const shown = chosen.slice(0, MAX_SHOWN);
  const more = [...chosen.slice(MAX_SHOWN), ...parents.filter((p) => !p.is_parent)];

  if (parents.length === 0) {
    return <p className="research-muted">No Parent Papers found yet.</p>;
  }

  return (
    <>
      {shown.length === 0 ? (
        <p className="research-muted">None of the references stand out as ones this paper builds on.</p>
      ) : (
        <ol className="research-parents">
          {shown.map((parent) => (
            <ParentRow key={parent.study_id} parent={parent} onMark={onMark} onOpen={onOpen} links={links} />
          ))}
        </ol>
      )}
      {more.length > 0 && (
        <>
          <button type="button" className="research-link-btn research-more" onClick={() => setExpanded(!expanded)}>
            {expanded ? "show fewer" : `show more (${more.length})`}
          </button>
          {expanded && (
            <ol className="research-parents research-parents-more">
              {more.map((parent) => (
                <ParentRow key={parent.study_id} parent={parent} onMark={onMark} onOpen={onOpen} links={links} />
              ))}
            </ol>
          )}
        </>
      )}
    </>
  );
}

type ParentRowProps = Omit<ParentsSectionProps, "parents"> & { parent: ParentItem };

function ParentRow({ parent, onMark, onOpen, links }: ParentRowProps) {
  const score = parent.score === null ? null : Math.round(parent.score * 10);
  return (
    <li className={`research-parent ${parent.is_parent ? "" : "research-parent-not"}`}>
      <div className="research-claim-line">
        <button type="button" className="research-link-btn" onClick={() => onOpen(parent.study_id)}>
          {parent.title}
        </button>
        <span className="research-muted">{parent.year ?? ""}</span>
        <span className={`research-badge research-badge-${parent.state}`}>{parent.state === "paper" ? "Paper" : "Lead"}</span>
        {parent.mark === "pinned" && <span className="research-badge research-badge-reader">marked by you</span>}
        {parent.mark === "unpinned" && <span className="research-badge research-badge-muted">unmarked by you</span>}
        {links(parent)}
      </div>
      <div className="research-parent-reason">
        {parent.reason ?? "no reason given"}
        {score !== null && <span className="research-muted"> · builds on {score}/10</span>}
        {parent.mention_count > 0 && <span className="research-muted"> · cited {parent.mention_count}×</span>}
      </div>
      <div className="research-claim-actions">
        {parent.is_parent ? (
          <button type="button" className="research-link-btn" onClick={() => void onMark(parent.study_id, "unpinned")}>
            not a Parent
          </button>
        ) : (
          <button type="button" className="research-link-btn" onClick={() => void onMark(parent.study_id, "pinned")}>
            mark as Parent
          </button>
        )}
        {parent.mark !== null && (
          <button type="button" className="research-link-btn" onClick={() => void onMark(parent.study_id, null)}>
            use Atlas's call
          </button>
        )}
      </div>
    </li>
  );
}
