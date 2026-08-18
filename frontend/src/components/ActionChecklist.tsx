import type { ActionItem } from "../api";
import { formatIsoDate, isoDateParts, monthAbbrev } from "../utils/date";
import AnalysisSources from "./AnalysisSources";

const ACTION_TYPE_LABELS: Record<string, string> = {
  required_action: "Required action",
  deadline: "Deadline",
  reminder: "Reminder",
  recommended_action: "Recommended",
};

function timingDisplay(action: ActionItem): string | null {
  if (!action.due_date) return action.timing_text;
  const formatted = formatIsoDate(action.due_date);
  const timing = action.timing_text ?? "";
  const parts = isoDateParts(action.due_date);
  const month = parts ? monthAbbrev(parts.month) : null;
  const restatesDate = parts !== null && month !== null && timing.includes(String(parts.day)) && timing.includes(String(parts.year)) && timing.toLowerCase().includes(month.toLowerCase());
  if (restatesDate) return `Due ${formatted}`;
  return timing ? `Due ${formatted} / ${timing}` : `Due ${formatted}`;
}

export default function ActionChecklist({
  actions,
  busy,
  onToggle,
}: {
  actions: ActionItem[];
  busy: Set<string>;
  onToggle: (actionId: string, status: "pending" | "completed") => void;
}) {
  if (actions.length === 0) {
    return <p className="dm-analysis-empty">No actionable items were identified in this document.</p>;
  }

  return (
    <ul className="dm-action-list">
      {actions.map((action) => {
        const checked = action.status === "completed";
        const timing = timingDisplay(action);
        return (
          <li key={action.id} className={`dm-action-item ${checked ? "is-complete" : ""}`}>
            <input
              type="checkbox"
              id={`action-${action.id}`}
              checked={checked}
              disabled={busy.has(action.id)}
              onChange={() => onToggle(action.id, checked ? "pending" : "completed")}
              aria-label={`${checked ? "Mark as pending" : "Mark as completed"}: ${action.title}`}
            />
            <div>
              <label htmlFor={`action-${action.id}`}>{action.title}</label>
              <div className="dm-action-meta">
                <span className="dm-action-type">{ACTION_TYPE_LABELS[action.action_type] ?? "Action"}</span>
                {timing && <span className="dm-action-due">{timing}</span>}
              </div>
              {action.description && <p className="dm-action-description">{action.description}</p>}
              <AnalysisSources sources={action.sources} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
