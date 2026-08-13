class DocumentError(Exception):
    pass


class InvalidDocumentError(DocumentError):
    pass


class DocumentStateError(DocumentError):
    pass


class TextExtractionError(DocumentError):
    pass


class ProviderError(Exception):
    pass


class AnalysisError(Exception):
    pass


class AnalysisNotFoundError(AnalysisError):
    pass


class AnalysisConflictError(AnalysisError):
    pass


class AnalysisStateError(AnalysisError):
    pass


class AnalysisContextTooLargeError(AnalysisError):
    pass


class AnalysisValidationError(AnalysisError):
    pass


class ActionError(Exception):
    pass


class ActionNotFoundError(ActionError):
    pass


class ActionConflictError(ActionError):
    pass


class ActionStateError(ActionError):
    pass


class ActionContextTooLargeError(ActionError):
    pass


class ActionValidationError(ActionError):
    pass


class ComparisonError(Exception):
    pass


class ComparisonNotFoundError(ComparisonError):
    pass


class ComparisonConflictError(ComparisonError):
    pass


class ComparisonStateError(ComparisonError):
    pass


class ComparisonContextTooLargeError(ComparisonError):
    pass


class ComparisonValidationError(ComparisonError):
    pass


class IntelligenceError(Exception):
    pass


class IntelligenceNotFoundError(IntelligenceError):
    pass


class IntelligenceConflictError(IntelligenceError):
    pass


class IntelligenceStateError(IntelligenceError):
    pass


class IntelligenceContextTooLargeError(IntelligenceError):
    pass


class IntelligenceValidationError(IntelligenceError):
    pass
