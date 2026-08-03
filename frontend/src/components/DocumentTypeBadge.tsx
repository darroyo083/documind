const TYPE_LABELS: Record<string, string> = {
  contract: "Contract",
  invoice: "Invoice",
  insurance_policy: "Insurance policy",
  bank_statement: "Bank statement",
  tax_document: "Tax document",
  employment_document: "Employment document",
  housing_document: "Housing document",
  pension_document: "Pension document",
  official_letter: "Official letter",
  receipt: "Receipt",
  report: "Report",
  other: "Other",
  unknown: "Unknown",
};

export default function DocumentTypeBadge({
  documentType,
}: {
  documentType: string;
}) {
  const label = TYPE_LABELS[documentType] ?? "Document";
  return (
    <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">
      {label}
    </span>
  );
}
