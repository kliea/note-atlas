import { useState, type ReactNode } from "react";
import type { LeadItem } from "../../types";

type LeadsSectionProps = {
  leads: LeadItem[];
  shown: number;
  empty: string;
  describe: (lead: LeadItem) => string;
  onDismiss: (studyId: number) => Promise<void>;
  onOpen: (studyId: number) => void;
  links: (lead: LeadItem) => ReactNode;
};

// Siblings or Ancestors: the first `shown` in rank order, the rest behind "show more".
export function LeadsSection({ leads, shown, empty, describe, onDismiss, onOpen, links }: LeadsSectionProps) {
  const [expanded, setExpanded] = useState(false);
  if (leads.length === 0) return <p className="research-muted">{empty}</p>;
  const visible = expanded ? leads : leads.slice(0, shown);
  const more = leads.length - shown;

  return (
    <>
      <ol className="research-parents">
        {visible.map((lead) => (
          <li key={lead.study_id} className={`research-parent research-lead-${lead.state}`}>
            <div className="research-claim-line">
              <button type="button" className="research-link-btn" onClick={() => onOpen(lead.study_id)}>
                {lead.title}
              </button>
              <span className="research-muted">{lead.year ?? ""}</span>
              <span className={`research-badge research-badge-${lead.state}`}>
                {lead.state === "paper" ? "in Library" : "Lead"}
              </span>
              {links(lead)}
            </div>
            <div className="research-parent-reason research-muted">{describe(lead)}</div>
            <div className="research-claim-actions">
              <button type="button" className="research-link-btn" onClick={() => void onDismiss(lead.study_id)}>
                not relevant
              </button>
            </div>
          </li>
        ))}
      </ol>
      {more > 0 && (
        <button type="button" className="research-link-btn research-more" onClick={() => setExpanded(!expanded)}>
          {expanded ? "show fewer" : `show more (${more})`}
        </button>
      )}
    </>
  );
}
