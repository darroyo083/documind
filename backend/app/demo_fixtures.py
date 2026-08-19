"""Small, deterministic, synthetic fixtures used only by the public demo."""

from datetime import UTC, date, datetime
from uuid import UUID

DEMO_SPACE_ID = UUID("6b6f0000-0000-4000-8000-000000000001")
MEMBERSHIP_DOCUMENT_ID = UUID("6b6f0000-0000-4000-8000-000000000101")
RENEWAL_DOCUMENT_ID = UUID("6b6f0000-0000-4000-8000-000000000102")
SCANNED_DOCUMENT_ID = UUID("6b6f0000-0000-4000-8000-000000000103")
MEMBERSHIP_CHUNK_ID = UUID("6b6f0000-0000-4000-8000-000000000201")
RENEWAL_CHUNK_ID = UUID("6b6f0000-0000-4000-8000-000000000202")
MEMBERSHIP_FACT_CHUNK_ID = UUID("6b6f0000-0000-4000-8000-000000000203")
RENEWAL_FACT_CHUNK_ID = UUID("6b6f0000-0000-4000-8000-000000000204")
MEMBERSHIP_ANALYSIS_ID = UUID("6b6f0000-0000-4000-8000-000000000301")
RENEWAL_ANALYSIS_ID = UUID("6b6f0000-0000-4000-8000-000000000302")
MEMBERSHIP_ACTIONS_ID = UUID("6b6f0000-0000-4000-8000-000000000401")
RENEWAL_ACTIONS_ID = UUID("6b6f0000-0000-4000-8000-000000000402")
COMPARISON_ID = UUID("6b6f0000-0000-4000-8000-000000000501")
ACTION_RENEWAL_ID = UUID("6b6f0000-0000-4000-8000-000000000601")
ACTION_CARD_ID = UUID("6b6f0000-0000-4000-8000-000000000602")

_CREATED = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
_UPDATED = datetime(2025, 2, 20, 10, 0, tzinfo=UTC)


def _citation(chunk_id: UUID, page_number: int, excerpt: str) -> dict:
    return {"chunk_id": chunk_id, "page_number": page_number, "excerpt": excerpt}


def _comparison_citation(document_id: UUID, chunk_id: UUID, page_number: int, excerpt: str) -> dict:
    return {
        "document_id": document_id,
        "chunk_id": chunk_id,
        "page_number": page_number,
        "excerpt": excerpt,
    }


def _global_hit(
    chunk_id: UUID,
    document_id: UUID,
    document_name: str,
    page_number: int,
    excerpt: str,
    score: float,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "document_name": document_name,
        "space_id": DEMO_SPACE_ID,
        "space_name": "Northwind Workspace",
        "page_number": page_number,
        "excerpt": excerpt,
        "score": score,
    }


def demo_space() -> dict:
    return {
        "id": DEMO_SPACE_ID,
        "name": "Northwind Workspace",
        "description": (
            "A synthetic membership document set showing how DocuMind keeps fees, "
            "deadlines, contradictions and source passages together."
        ),
        "created_at": _CREATED,
        "updated_at": _UPDATED,
    }


def demo_documents() -> list[dict]:
    return [
        {
            "id": MEMBERSHIP_DOCUMENT_ID,
            "original_filename": "Northwind_Membership_Agreement.pdf",
            "media_type": "application/pdf",
            "file_size": 184320,
            "page_count": 6,
            "status": "ready",
            "error_message": None,
            "failure_code": None,
            "created_at": _CREATED,
            "updated_at": _UPDATED,
        },
        {
            "id": RENEWAL_DOCUMENT_ID,
            "original_filename": "Northwind_Renewal_Notice.pdf",
            "media_type": "application/pdf",
            "file_size": 92160,
            "page_count": 3,
            "status": "ready",
            "error_message": None,
            "failure_code": None,
            "created_at": datetime(2025, 2, 1, 10, 0, tzinfo=UTC),
            "updated_at": _UPDATED,
        },
        {
            "id": SCANNED_DOCUMENT_ID,
            "original_filename": "Northwind_Scanned_Appendix.pdf",
            "media_type": "application/pdf",
            "file_size": 51200,
            "page_count": 1,
            "status": "failed",
            "error_message": "No extractable text. Scanned PDFs are not supported.",
            "failure_code": "no_extractable_text",
            "created_at": datetime(2025, 2, 2, 10, 0, tzinfo=UTC),
            "updated_at": _UPDATED,
        },
    ]


def demo_analysis(document_id: UUID) -> dict:
    if document_id == MEMBERSHIP_DOCUMENT_ID:
        return {
            "id": MEMBERSHIP_ANALYSIS_ID,
            "document_id": document_id,
            "status": "ready",
            "document_type": "Membership agreement",
            "normalized_title": "Northwind Membership Agreement",
            "summary": (
                "The agreement sets a monthly membership fee of CHF 420 and a CHF 50 "
                "access-card deposit. Building access is available from 06:00 to 22:00."
            ),
            "important_dates": [
                {
                    "label": "Agreement start",
                    "value": "1 January 2025",
                    "normalized_date": "2025-01-01",
                    "sources": [
                        _citation(MEMBERSHIP_CHUNK_ID, 1, "Membership begins on 1 January 2025.")
                    ],
                },
                {
                    "label": "Cancellation notice",
                    "value": "30 days before renewal",
                    "normalized_date": None,
                    "sources": [
                        _citation(
                            MEMBERSHIP_FACT_CHUNK_ID,
                            4,
                            "Cancellation requires 30 days' notice before renewal.",
                        )
                    ],
                },
            ],
            "key_facts": [
                {
                    "label": "Monthly membership fee",
                    "value": "CHF 420",
                    "sources": [
                        _citation(MEMBERSHIP_CHUNK_ID, 2, "The monthly membership fee is CHF 420.")
                    ],
                },
                {
                    "label": "Access-card deposit",
                    "value": "CHF 50, refundable on return",
                    "sources": [
                        _citation(
                            MEMBERSHIP_FACT_CHUNK_ID,
                            3,
                            "A refundable CHF 50 deposit is required for each access card.",
                        )
                    ],
                },
                {
                    "label": "Building access",
                    "value": "06:00–22:00 daily",
                    "sources": [
                        _citation(
                            MEMBERSHIP_FACT_CHUNK_ID,
                            5,
                            "Members may access the building daily from 06:00 to 22:00.",
                        )
                    ],
                },
            ],
            "provider": "demo-fixture",
            "model": "pre-generated",
            "created_at": _UPDATED,
            "updated_at": _UPDATED,
        }
    if document_id == RENEWAL_DOCUMENT_ID:
        return {
            "id": RENEWAL_ANALYSIS_ID,
            "document_id": document_id,
            "status": "ready",
            "document_type": "Renewal notice",
            "normalized_title": "Northwind Renewal Notice",
            "summary": (
                "The renewal notice proposes a higher monthly fee of CHF 460, narrows "
                "building access to 07:00–21:00, and introduces a 60-day cancellation line."
            ),
            "important_dates": [
                {
                    "label": "Renewal decision",
                    "value": "31 March 2025",
                    "normalized_date": "2025-03-31",
                    "sources": [
                        _citation(RENEWAL_CHUNK_ID, 1, "Please confirm renewal by 31 March 2025.")
                    ],
                },
                {
                    "label": "Renewal period",
                    "value": "1 April 2025",
                    "normalized_date": "2025-04-01",
                    "sources": [
                        _citation(
                            RENEWAL_FACT_CHUNK_ID,
                            2,
                            "The renewed membership period begins on 1 April 2025.",
                        )
                    ],
                },
            ],
            "key_facts": [
                {
                    "label": "Renewal fee",
                    "value": "CHF 460 per month",
                    "sources": [
                        _citation(RENEWAL_CHUNK_ID, 1, "The monthly renewal fee will be CHF 460.")
                    ],
                },
                {
                    "label": "Changed access hours",
                    "value": "07:00–21:00 daily",
                    "sources": [
                        _citation(
                            RENEWAL_FACT_CHUNK_ID,
                            2,
                            "Access hours for the renewal period are 07:00 to 21:00.",
                        )
                    ],
                },
                {
                    "label": "Cancellation line",
                    "value": "60 days before renewal",
                    "sources": [
                        _citation(
                            RENEWAL_FACT_CHUNK_ID,
                            3,
                            "The notice asks for 60 days' notice before renewal.",
                        )
                    ],
                },
            ],
            "provider": "demo-fixture",
            "model": "pre-generated",
            "created_at": _UPDATED,
            "updated_at": _UPDATED,
        }
    raise KeyError(document_id)


def demo_actions(document_id: UUID) -> dict:
    actions = {
        MEMBERSHIP_DOCUMENT_ID: {
            "id": MEMBERSHIP_ACTIONS_ID,
            "document_id": document_id,
            "status": "ready",
            "provider": "demo-fixture",
            "model": "pre-generated",
            "actions": [
                {
                    "id": ACTION_CARD_ID,
                    "action_type": "reminder",
                    "title": "Return the access card to recover the deposit",
                    "description": (
                        "Return each access card when membership ends so the CHF 50 "
                        "deposit can be refunded."
                    ),
                    "timing_text": "At membership end",
                    "due_date": None,
                    "status": "pending",
                    "completed_at": None,
                    "sources": [
                        _citation(
                            MEMBERSHIP_FACT_CHUNK_ID,
                            3,
                            "The CHF 50 access-card deposit is refundable on return.",
                        )
                    ],
                }
            ],
            "created_at": _UPDATED,
            "updated_at": _UPDATED,
        },
        RENEWAL_DOCUMENT_ID: {
            "id": RENEWAL_ACTIONS_ID,
            "document_id": document_id,
            "status": "ready",
            "provider": "demo-fixture",
            "model": "pre-generated",
            "actions": [
                {
                    "id": ACTION_RENEWAL_ID,
                    "action_type": "deadline",
                    "title": "Confirm the renewal decision",
                    "description": (
                        "Review the changed fee, access hours and cancellation language "
                        "before responding."
                    ),
                    "timing_text": "Before the end of March",
                    "due_date": date(2025, 3, 31),
                    "status": "pending",
                    "completed_at": None,
                    "sources": [
                        _citation(RENEWAL_CHUNK_ID, 1, "Please confirm renewal by 31 March 2025.")
                    ],
                }
            ],
            "created_at": _UPDATED,
            "updated_at": _UPDATED,
        },
    }
    return actions[document_id]


def demo_comparison() -> dict:
    membership_fee = _comparison_citation(
        MEMBERSHIP_DOCUMENT_ID,
        MEMBERSHIP_CHUNK_ID,
        2,
        "The monthly membership fee is CHF 420.",
    )
    renewal_fee = _comparison_citation(
        RENEWAL_DOCUMENT_ID,
        RENEWAL_CHUNK_ID,
        1,
        "The monthly renewal fee will be CHF 460.",
    )
    membership_hours = _comparison_citation(
        MEMBERSHIP_DOCUMENT_ID,
        MEMBERSHIP_FACT_CHUNK_ID,
        5,
        "Members may access the building daily from 06:00 to 22:00.",
    )
    renewal_hours = _comparison_citation(
        RENEWAL_DOCUMENT_ID,
        RENEWAL_FACT_CHUNK_ID,
        2,
        "Access hours for the renewal period are 07:00 to 21:00.",
    )
    membership_cancel = _comparison_citation(
        MEMBERSHIP_DOCUMENT_ID,
        MEMBERSHIP_FACT_CHUNK_ID,
        4,
        "Cancellation requires 30 days' notice before renewal.",
    )
    renewal_cancel = _comparison_citation(
        RENEWAL_DOCUMENT_ID,
        RENEWAL_FACT_CHUNK_ID,
        3,
        "The notice asks for 60 days' notice before renewal.",
    )
    return {
        "id": COMPARISON_ID,
        "status": "ready",
        "focus": "fees, access hours, and cancellation terms",
        "title": "Agreement vs renewal notice",
        "summary": (
            "The renewal increases the fee, shortens access hours, and contains a "
            "cancellation-period contradiction that deserves review."
        ),
        "documents": [
            {
                "document_id": MEMBERSHIP_DOCUMENT_ID,
                "original_filename": "Northwind_Membership_Agreement.pdf",
                "position": 0,
            },
            {
                "document_id": RENEWAL_DOCUMENT_ID,
                "original_filename": "Northwind_Renewal_Notice.pdf",
                "position": 1,
            },
        ],
        "dimensions": [
            {
                "label": "Monthly membership fee",
                "findings": [
                    {
                        "document_id": MEMBERSHIP_DOCUMENT_ID,
                        "value": "CHF 420",
                        "not_identified": False,
                        "sources": [membership_fee],
                    },
                    {
                        "document_id": RENEWAL_DOCUMENT_ID,
                        "value": "CHF 460",
                        "not_identified": False,
                        "sources": [renewal_fee],
                    },
                ],
                "synthesis": "The renewal is CHF 40 higher per month.",
                "sources": [membership_fee, renewal_fee],
            },
            {
                "label": "Building access hours",
                "findings": [
                    {
                        "document_id": MEMBERSHIP_DOCUMENT_ID,
                        "value": "06:00–22:00",
                        "not_identified": False,
                        "sources": [membership_hours],
                    },
                    {
                        "document_id": RENEWAL_DOCUMENT_ID,
                        "value": "07:00–21:00",
                        "not_identified": False,
                        "sources": [renewal_hours],
                    },
                ],
                "synthesis": "The renewal removes one hour at each end of the day.",
                "sources": [membership_hours, renewal_hours],
            },
            {
                "label": "Cancellation notice",
                "findings": [
                    {
                        "document_id": MEMBERSHIP_DOCUMENT_ID,
                        "value": "30 days before renewal",
                        "not_identified": False,
                        "sources": [membership_cancel],
                    },
                    {
                        "document_id": RENEWAL_DOCUMENT_ID,
                        "value": "60 days before renewal",
                        "not_identified": False,
                        "sources": [renewal_cancel],
                    },
                ],
                "synthesis": "The two documents state different notice periods.",
                "sources": [membership_cancel, renewal_cancel],
            },
        ],
        "key_differences": [
            {
                "title": "Fee increase",
                "description": "The proposed monthly fee rises from CHF 420 to CHF 460.",
                "sources": [membership_fee, renewal_fee],
            },
            {
                "title": "Narrower access window",
                "description": "Renewal access changes from 06:00–22:00 to 07:00–21:00.",
                "sources": [membership_hours, renewal_hours],
            },
            {
                "title": "Cancellation contradiction",
                "description": "The agreement and notice cite 30 and 60 days respectively.",
                "sources": [membership_cancel, renewal_cancel],
            },
        ],
        "commonalities": [
            {
                "title": "Same workspace and membership",
                "description": (
                    "Both documents describe the Northwind membership relationship and "
                    "its building access rules."
                ),
                "sources": [membership_fee, renewal_fee],
            },
        ],
        "provider": "demo-fixture",
        "model": "pre-generated",
        "error_message": None,
        "created_at": _UPDATED,
        "updated_at": _UPDATED,
    }


def demo_intelligence() -> dict:
    membership_fee = {
        "document_id": MEMBERSHIP_DOCUMENT_ID,
        "document_name": "Northwind_Membership_Agreement.pdf",
        "chunk_id": MEMBERSHIP_CHUNK_ID,
        "page_number": 2,
        "excerpt": "The monthly membership fee is CHF 420.",
    }
    renewal_fee = {
        "document_id": RENEWAL_DOCUMENT_ID,
        "document_name": "Northwind_Renewal_Notice.pdf",
        "chunk_id": RENEWAL_CHUNK_ID,
        "page_number": 1,
        "excerpt": "The monthly renewal fee will be CHF 460.",
    }
    membership_deposit = {
        **membership_fee,
        "chunk_id": MEMBERSHIP_FACT_CHUNK_ID,
        "page_number": 3,
        "excerpt": "A refundable CHF 50 deposit is required for each access card.",
    }
    membership_cancel = {
        **membership_fee,
        "chunk_id": MEMBERSHIP_FACT_CHUNK_ID,
        "page_number": 4,
        "excerpt": "Cancellation requires 30 days' notice before renewal.",
    }
    renewal_cancel = {
        **renewal_fee,
        "chunk_id": RENEWAL_FACT_CHUNK_ID,
        "page_number": 3,
        "excerpt": "The notice asks for 60 days' notice before renewal.",
    }
    return {
        "status": "ready",
        "is_stale": False,
        "ready_document_count": 2,
        "summary": (
            "Northwind's renewal notice raises the monthly fee from CHF 420 to CHF 460 "
            "and narrows building access. The cancellation period is inconsistent "
            "across the agreement and notice, so the member should confirm which term "
            "controls before responding."
        ),
        "key_facts": [
            {
                "title": "Renewal fee",
                "detail": "The proposed fee is CHF 460 per month, up from CHF 420.",
                "sources": [membership_fee, renewal_fee],
            },
            {
                "title": "Access-card deposit",
                "detail": "A refundable CHF 50 deposit is attached to each access card.",
                "sources": [membership_deposit],
            },
        ],
        "contradictions": [
            {
                "topic": "Cancellation period",
                "first_claim": "The membership agreement says 30 days' notice before renewal.",
                "first_sources": [membership_cancel],
                "second_claim": "The renewal notice asks for 60 days' notice before renewal.",
                "second_sources": [renewal_cancel],
            },
        ],
        "dates": [
            {
                "label": "Renewal decision",
                "date_text": "31 March 2025",
                "context": "The notice asks for a decision before the renewal period begins.",
                "sources": [renewal_fee],
            },
            {
                "label": "New period",
                "date_text": "1 April 2025",
                "context": "The proposed renewal begins on this date.",
                "sources": [renewal_fee],
            },
        ],
        "open_questions": [
            {
                "question": "Which cancellation period controls?",
                "explanation": (
                    "The agreement and renewal notice state different deadlines; "
                    "confirm with Northwind before acting."
                ),
                "sources": [membership_cancel, renewal_cancel],
            },
        ],
        "provider": "demo-fixture",
        "model": "pre-generated",
        "error_message": None,
        "created_at": _UPDATED,
        "updated_at": _UPDATED,
    }


def demo_answer(question: str) -> dict:
    normalized = question.strip().casefold()
    if "de qué va" in normalized or "de que va" in normalized:
        answer = (
            "Es un espacio sintético de membresía: DocuMind resume el acuerdo y el "
            "aviso de renovación, compara los cambios y mantiene cada afirmación "
            "vinculada a su página de origen."
        )
        citations = [
            _citation(MEMBERSHIP_CHUNK_ID, 2, "The monthly membership fee is CHF 420."),
            _citation(RENEWAL_CHUNK_ID, 1, "The monthly renewal fee will be CHF 460."),
        ]
    elif "monthly" in normalized and "fee" in normalized:
        answer = (
            "The current membership agreement lists a monthly fee of CHF 420. "
            "The renewal notice proposes CHF 460 per month."
        )
        citations = [
            _citation(MEMBERSHIP_CHUNK_ID, 2, "The monthly membership fee is CHF 420."),
            _citation(RENEWAL_CHUNK_ID, 1, "The monthly renewal fee will be CHF 460."),
        ]
    elif "renewal" in normalized and (
        "changed" in normalized or "notice" in normalized or "what" in normalized
    ):
        answer = (
            "The renewal notice changes the monthly fee to CHF 460 and narrows building "
            "access from 06:00–22:00 to 07:00–21:00. It also states a 60-day "
            "cancellation period, which conflicts with the agreement's 30-day term."
        )
        citations = [
            _citation(RENEWAL_CHUNK_ID, 1, "The monthly renewal fee will be CHF 460."),
            _citation(
                RENEWAL_FACT_CHUNK_ID, 2, "Access hours for the renewal period are 07:00 to 21:00."
            ),
            _citation(
                RENEWAL_FACT_CHUNK_ID, 3, "The notice asks for 60 days' notice before renewal."
            ),
        ]
    elif "contradiction" in normalized or "contradictions" in normalized:
        answer = (
            "Yes. The membership agreement says cancellation requires 30 days' notice "
            "before renewal, while the renewal notice asks for 60 days. The demo marks "
            "this as an open question to confirm."
        )
        citations = [
            _citation(
                MEMBERSHIP_FACT_CHUNK_ID, 4, "Cancellation requires 30 days' notice before renewal."
            ),
            _citation(
                RENEWAL_FACT_CHUNK_ID, 3, "The notice asks for 60 days' notice before renewal."
            ),
        ]
    else:
        answer = (
            "This public demo supports the suggested example questions. Live AI "
            "generation is disabled."
        )
        citations = []
    return {
        "answer": answer,
        "supported": bool(citations),
        "citations": [
            {
                "source_id": f"demo-source-{index + 1}",
                "source_kind": "private",
                "document_id": (
                    MEMBERSHIP_DOCUMENT_ID
                    if citation["chunk_id"] in {MEMBERSHIP_CHUNK_ID, MEMBERSHIP_FACT_CHUNK_ID}
                    else RENEWAL_DOCUMENT_ID
                ),
                "reference_document_id": None,
                "document_name": (
                    "Northwind_Membership_Agreement.pdf"
                    if citation["chunk_id"] in {MEMBERSHIP_CHUNK_ID, MEMBERSHIP_FACT_CHUNK_ID}
                    else "Northwind_Renewal_Notice.pdf"
                ),
                "page_number": citation["page_number"],
                "chunk_id": citation["chunk_id"],
                "excerpt": citation["excerpt"],
                "score": 1.0,
            }
            for index, citation in enumerate(citations)
        ],
        "embedding_model": "demo",
        "answer_model": "demo",
    }


def demo_search(query: str) -> list[dict]:
    normalized = query.strip().casefold()
    hits = [
        _global_hit(
            RENEWAL_CHUNK_ID,
            RENEWAL_DOCUMENT_ID,
            "Northwind_Renewal_Notice.pdf",
            1,
            "The monthly renewal fee will be CHF 460.",
            0.99,
        ),
        _global_hit(
            MEMBERSHIP_FACT_CHUNK_ID,
            MEMBERSHIP_DOCUMENT_ID,
            "Northwind_Membership_Agreement.pdf",
            3,
            "A refundable CHF 50 deposit is required for each access card.",
            0.97,
        ),
        _global_hit(
            MEMBERSHIP_CHUNK_ID,
            MEMBERSHIP_DOCUMENT_ID,
            "Northwind_Membership_Agreement.pdf",
            5,
            (
                "Building access may be suspended when an account is overdue or an "
                "access card is misused."
            ),
            0.95,
        ),
    ]
    terms = {
        "chf 460": {0},
        "access-card deposit": {1},
        "access card deposit": {1},
        "when can building access be suspended": {2},
        "access suspended": {2},
    }
    for phrase, indexes in terms.items():
        if phrase in normalized:
            return [hits[index] for index in sorted(indexes)]
    tokens = [token for token in normalized.split() if len(token) > 2]
    return [hit for hit in hits if any(token in hit["excerpt"].casefold() for token in tokens)]
