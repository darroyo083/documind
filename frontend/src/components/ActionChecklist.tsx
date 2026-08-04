import type { ActionItem } from "../api";
import { formatIsoDate, isoDateParts, monthAbbrev } from "../utils/date";
import AnalysisSources from "./AnalysisSources";

const ACTION_TYPE_LABELS: Record<string, string> = {
  required_action: "Required action",
  deadline: "Deadline",
  reminder: "Reminder",
  recommended_action: "Recommended",
};

function actionTypeLabel(actionType: string): string {
  return ACTION_TYPE_LABELS[actionType] ?? "Action";
}

function ActionTypeBadge({ actionType }: { actionType: string }) {
  const isRequired = actionType === "required_action";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
        isRequired
          ? "bg-indigo-50 text-indigo-700"
          : "bg-gray-100 text-gray-700"
      }`}
    >
      {actionTypeLabel(actionType)}
    </span>
  );
}

function timingDisplay(action: ActionItem): string | null {
  if (!action.due_date) return action.timing_text;
  const formatted = formatIsoDate(action.due_date);
  const timing = action.timing_text ?? "";
  const parts = isoDateParts(action.due_date);
  const month = parts ? monthAbbrev(parts.month) : null;
  const restatesDate =
    parts !== null &&
    month !== null &&
    timing.includes(String(parts.day)) &&
    timing.includes(String(parts.year)) &&
    timing.toLowerCase().includes(month.toLowerCase());
  if (restatesDate) return `Due ${formatted}`;
  return timing ? `Due ${formatted} · ${timing}` : `Due ${formatted}`;
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
    return (
      <p className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
        No actionable items were identified in this document.
      </p>
    );
  }

  return (
    <ul className="space-y-3">
      {actions.map((action) => {
        const checked = action.status === "completed";
        const isBusy = busy.has(action.id);
        const next = checked ? "pending" : "completed";
        const timing = timingDisplay(action);
        return (
          <li
            key={action.id}
            className={`rounded-lg border bg-white p-4 shadow-sm ${
              checked ? "border-gray-100" : "border-gray-200"
            }`}
          >
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                id={`action-${action.id}`}
                checked={checked}
                disabled={isBusy}
                onChange={() => onToggle(action.id, next)}
                aria-label={`${checked ? "Mark as pending" : "Mark as completed"}: ${action.title}`}
                className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
              />
              <div className="min-w-0 flex-1">
                <label
                  htmlFor={`action-${action.id}`}
                  className={`font-medium text-gray-900 ${
                    checked ? "line-through text-gray-400" : ""
                  }`}
                >
                  {action.title}
                </label>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <ActionTypeBadge actionType={action.action_type} />
                  {timing && (
                    <span className="text-sm text-gray-500">{timing}</span>
                  )}
                </div>
                {action.description && (
                  <p className="mt-2 text-sm leading-6 text-gray-600">
                    {action.description}
                  </p>
                )}
                <AnalysisSources sources={action.sources} />
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
