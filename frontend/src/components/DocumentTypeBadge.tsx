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

export function getDocumentTypeLabel(documentType: string): string {
  return TYPE_LABELS[documentType] ?? "Document";
}

export default function DocumentTypeBadge({
  documentType,
}: {
  documentType: string;
}) {
  const label = getDocumentTypeLabel(documentType);
  return (
    <span className="dm-document-type">
      {label}
    </span>
  );
}
