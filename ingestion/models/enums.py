from enum import Enum


class DocumentType(str, Enum):
    RESEARCH_PAPER    = "research_paper"
    CLINICAL_GUIDELINE = "clinical_guideline"
    SOP               = "sop"
    DRUG_REFERENCE    = "drug_reference"
    INSURANCE_POLICY  = "insurance_policy"
    LAB_REPORT        = "lab_report"
    MEDICAL_IMAGE     = "medical_image"
    GENERAL           = "general"


class FileType(str, Enum):
    # Documents
    PDF  = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    CSV  = "csv"
    TXT  = "txt"
    # Images
    PNG  = "png"
    JPG  = "jpg"
    JPEG = "jpeg"
    TIFF = "tiff"
    # Structured / clinical data
    JSON = "json"
    XML  = "xml"
    FHIR = "fhir"

    @classmethod
    def from_extension(cls, ext: str) -> "FileType":
        """Map a file extension string to FileType, case-insensitive."""
        return cls(ext.lower().lstrip("."))

    @property
    def is_image(self) -> bool:
        return self in {FileType.PNG, FileType.JPG, FileType.JPEG, FileType.TIFF}

    @property
    def is_document(self) -> bool:
        return self in {
            FileType.PDF, FileType.DOCX, FileType.PPTX,
            FileType.XLSX, FileType.CSV, FileType.TXT,
        }

    @property
    def is_structured(self) -> bool:
        return self in {FileType.JSON, FileType.XML, FileType.FHIR}


class GovernanceState(str, Enum):
    DRAFT          = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED       = "approved"
    ARCHIVED       = "archived"

    def can_transition_to(self, next_state: "GovernanceState") -> bool:
        """Enforce the one-way governance state machine."""
        allowed: dict["GovernanceState", set["GovernanceState"]] = {
            GovernanceState.DRAFT:          {GovernanceState.PENDING_REVIEW},
            GovernanceState.PENDING_REVIEW: {GovernanceState.APPROVED, GovernanceState.DRAFT},
            GovernanceState.APPROVED:       {GovernanceState.ARCHIVED},
            GovernanceState.ARCHIVED:       set(),
        }
        return next_state in allowed[self]


class RiskLevel(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class ChunkType(str, Enum):
    TEXT    = "text"
    TABLE   = "table"
    IMAGE   = "image"
    FIGURE  = "figure"
    HEADING = "heading"


class ProcessingStatus(str, Enum):
    PENDING          = "pending"
    UPLOADING        = "uploading"
    CLASSIFYING      = "classifying"
    PARSING          = "parsing"
    ENRICHING        = "enriching"
    CHUNKING         = "chunking"
    EMBEDDING        = "embedding"
    GRAPHING         = "graphing"
    VALIDATING       = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    INDEXING         = "indexing"
    COMPLETED        = "completed"
    FAILED           = "failed"
    DEAD_LETTER      = "dead_letter"

    @property
    def is_terminal(self) -> bool:
        return self in {
            ProcessingStatus.COMPLETED,
            ProcessingStatus.FAILED,
            ProcessingStatus.DEAD_LETTER,
        }


class MedicalEntityType(str, Enum):
    DISEASE   = "disease"
    DRUG      = "drug"
    SYMPTOM   = "symptom"
    PROCEDURE = "procedure"
    TREATMENT = "treatment"
    GUIDELINE = "guideline"
    ANATOMY   = "anatomy"
    LAB_TEST  = "lab_test"


class OntologyStandard(str, Enum):
    SNOMED_CT = "snomed_ct"
    RXNORM    = "rxnorm"
    ICD_10    = "icd_10"
    LOINC     = "loinc"


class MedicalSpecialty(str, Enum):
    CARDIOLOGY         = "cardiology"
    ONCOLOGY           = "oncology"
    NEUROLOGY          = "neurology"
    ENDOCRINOLOGY      = "endocrinology"
    INFECTIOUS_DISEASE = "infectious_disease"
    PHARMACOLOGY       = "pharmacology"
    RADIOLOGY          = "radiology"
    SURGERY            = "surgery"
    PEDIATRICS         = "pediatrics"
    GENERAL            = "general"


class ParserType(str, Enum):
    DOCLING    = "docling"
    PADDLE_OCR = "paddle_ocr"
    COL_QWEN   = "col_qwen"
