from enum import Enum

import rdflib
from django.db import models

from activitypub.core.contexts import AS2, SCHEMA

from .linked_data import AbstractContextModel, Reference


class LanguageMap(Enum):
    UND = ("und", "und", "Undetermined")

    EN = ("en", "eng", "English")
    EN_US = ("en-US", "eng", "English (United States)")
    EN_GB = ("en-GB", "eng", "English (United Kingdom)")

    ZH = ("zh", "zho", "Chinese")
    ZH_CN = ("zh-CN", "zho", "Chinese (Simplified, China)")
    ZH_TW = ("zh-TW", "zho", "Chinese (Traditional, Taiwan)")

    HI = ("hi", "hin", "Hindi")
    HI_IN = ("hi-IN", "hin", "Hindi (India)")

    ES = ("es", "spa", "Spanish")
    ES_ES = ("es-ES", "spa", "Spanish (Spain)")
    ES_MX = ("es-MX", "spa", "Spanish (Mexico)")
    ES_AR = ("es-AR", "spa", "Spanish (Argentina)")

    FR = ("fr", "fra", "French")
    FR_FR = ("fr-FR", "fra", "French (France)")
    FR_CA = ("fr-CA", "fra", "French (Canada)")

    AR = ("ar", "ara", "Arabic")
    AR_SA = ("ar-SA", "ara", "Arabic (Saudi Arabia)")
    AR_EG = ("ar-EG", "ara", "Arabic (Egypt)")

    BN = ("bn", "ben", "Bengali")
    BN_BD = ("bn-BD", "ben", "Bengali (Bangladesh)")

    PT = ("pt", "por", "Portuguese")
    PT_BR = ("pt-BR", "por", "Portuguese (Brazil)")
    PT_PT = ("pt-PT", "por", "Portuguese (Portugal)")

    RU = ("ru", "rus", "Russian")
    RU_RU = ("ru-RU", "rus", "Russian (Russia)")

    UR = ("ur", "urd", "Urdu")
    UR_PK = ("ur-PK", "urd", "Urdu (Pakistan)")

    ID = ("id", "ind", "Indonesian")
    ID_ID = ("id-ID", "ind", "Indonesian (Indonesia)")

    DE = ("de", "deu", "German")
    DE_DE = ("de-DE", "deu", "German (Germany)")
    DE_AT = ("de-AT", "deu", "German (Austria)")

    JA = ("ja", "jpn", "Japanese")
    JA_JP = ("ja-JP", "jpn", "Japanese (Japan)")

    PA = ("pa", "pan", "Punjabi")
    PA_IN = ("pa-IN", "pan", "Punjabi (India)")

    MR = ("mr", "mar", "Marathi")
    MR_IN = ("mr-IN", "mar", "Marathi (India)")

    TE = ("te", "tel", "Telugu")
    TE_IN = ("te-IN", "tel", "Telugu (India)")

    TR = ("tr", "tur", "Turkish")
    TR_TR = ("tr-TR", "tur", "Turkish (Turkey)")

    KO = ("ko", "kor", "Korean")
    KO_KR = ("ko-KR", "kor", "Korean (South Korea)")

    VI = ("vi", "vie", "Vietnamese")
    VI_VN = ("vi-VN", "vie", "Vietnamese (Vietnam)")

    IT = ("it", "ita", "Italian")
    IT_IT = ("it-IT", "ita", "Italian (Italy)")

    TA = ("ta", "tam", "Tamil")
    TA_IN = ("ta-IN", "tam", "Tamil (India)")

    PL = ("pl", "pol", "Polish")
    PL_PL = ("pl-PL", "pol", "Polish (Poland)")

    UK = ("uk", "ukr", "Ukrainian")
    UK_UA = ("uk-UA", "ukr", "Ukrainian (Ukraine)")

    FA = ("fa", "fas", "Persian")
    FA_IR = ("fa-IR", "fas", "Persian (Iran)")

    NL = ("nl", "nld", "Dutch")
    NL_NL = ("nl-NL", "nld", "Dutch (Netherlands)")

    TH = ("th", "tha", "Thai")
    TH_TH = ("th-TH", "tha", "Thai (Thailand)")

    @property
    def code(self) -> str:
        return self.value[0].lower()

    @property
    def iso_639_3(self) -> str:
        return self.value[1]

    @property
    def iso_639_1(self):
        return None if self.code in ["und"] else self.code.split("-", 1)[0]

    @property
    def name(self) -> str:
        return self.value[2]


class Language(AbstractContextModel):
    """
    Language resource using URN-based URIs with BCP 47 codes.
    URIs are opaque identifiers, not dereferenceable URLs.
    """

    LINKED_DATA_FIELDS = {"iso_639_3": SCHEMA.identifier, "name": AS2.name}
    URI_PREFIX = "urn:bcp47:"

    code = models.CharField(
        max_length=10, unique=True, db_index=True, help_text="BCP 47 language tag"
    )
    name = models.CharField(max_length=100, help_text="Human-readable language name")
    iso_639_1 = models.CharField(
        max_length=2, null=True, db_index=True, help_text="ISO 639-1 code"
    )
    iso_639_3 = models.CharField(
        max_length=3, null=True, db_index=True, help_text="ISO 639-3 code"
    )

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    @classmethod
    def should_handle_reference(cls, g: rdflib.Graph, reference: Reference):
        return reference.uri.startswith(cls.URI_PREFIX)

    @classmethod
    def load_from_graph(cls, g: rdflib.Graph, reference: Reference):
        pass  # We are not really getting this from outside

    @classmethod
    def create_language(cls, code, iso_639_1, iso_639_3, name):
        normalized_code = code.lower()
        reference = Reference.make(uri=f"{cls.URI_PREFIX}{normalized_code}")

        language, _ = cls.objects.update_or_create(
            reference=reference,
            code=normalized_code,
            defaults={
                "name": name,
                "iso_639_3": iso_639_3,
                "iso_639_1": iso_639_1,
            },
        )

        return language

    @classmethod
    def load(cls):
        for lang in LanguageMap:
            cls.create_language(
                code=lang.code, iso_639_1=lang.iso_639_1, iso_639_3=lang.iso_639_3, name=lang.name
            )


__all__ = ["Language", "LanguageMap"]
