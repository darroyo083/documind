class DocumentError(Exception):
    pass


class InvalidDocumentError(DocumentError):
    pass


class TextExtractionError(DocumentError):
    pass


class ProviderError(Exception):
    pass
