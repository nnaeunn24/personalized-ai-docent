from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .schemas import RequestBody

PromptKind = Literal["extraction", "classification", "followup"]
PromptBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12000)]
PromptVersion = Annotated[int, Field(ge=1)]


class PromptUpdate(RequestBody):
    expected_version: PromptVersion
    body: PromptBody | None = None
    restore_version: PromptVersion | None = None

    @model_validator(mode="after")
    def choose_operation(self):
        if (self.body is None) == (self.restore_version is None):
            raise ValueError("Provide one prompt body or restore version.")
        return self


class PromptTest(RequestBody):
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100000)]
    extraction_body: PromptBody
    classification_body: PromptBody
    extraction_version: PromptVersion | None = None
    classification_version: PromptVersion | None = None
